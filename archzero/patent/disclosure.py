"""Assemble the six-section patent disclosure from a funnel candidate.

Division of labour: the funnel owns the numbers, the LLM owns the prose.
Section 5 (有益效果) reads ``Candidate.metrics`` directly and only asks the LLM
to word each claim, so a review deck can never quote a speedup the pipeline
never measured.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from archzero.config import FactoryConfig
from archzero.generation.cleanroom import _parse_json
from archzero.llm.client import CursorLLM
from archzero.models import Candidate, ClauseKind, ProblemPackage, TaskClass, Tier
from archzero.patent.models import (
    SECTION_TITLES,
    BenefitClaim,
    PatentDisclosure,
    ProtectionPoint,
)
from archzero.patent.prior_art import PriorArtResult, prior_art_markdown, run_prior_art
from archzero.spec.acc_parse import parse_acceptance_thresholds

log = logging.getLogger("archzero.patent.disclosure")

# (metric key, quantity, label, formatter, ACC threshold attr, higher_is_better)
# Ordered strongest-evidence-first: only the first entry per quantity survives,
# so a Tier4 measurement supersedes the Tier2 analytic estimate of the same thing.
_METRIC_SPECS: tuple[tuple[str, str, str, str, str | None, bool], ...] = (
    ("t4_miss_reduction", "miss_reduction", "MPKI 降低（全量仿真）", "pct", "min_miss_reduction", True),
    ("t3_miss_reduction", "miss_reduction", "MPKI 降低（小规模仿真）", "pct", "min_miss_reduction", True),
    ("t2_miss_reduction", "miss_reduction", "MPKI 降低（解析模型）", "pct", "min_miss_reduction", True),
    ("t4_bw_delta_frac", "bw_delta", "DRAM 带宽变化（全量仿真）", "pct", "max_bw_delta_frac", False),
    ("t3_bw_delta_frac", "bw_delta", "DRAM 带宽变化（小规模仿真）", "pct", "max_bw_delta_frac", False),
    ("t2_bw_delta_frac", "bw_delta", "DRAM 带宽变化（解析模型）", "pct", "max_bw_delta_frac", False),
    ("t4_ipc", "ipc", "IPC（全量仿真）", "num", None, True),
    ("t3_ipc", "ipc", "IPC（小规模仿真）", "num", None, True),
    ("t2_ipc_speedup", "ipc", "IPC 加速比（解析模型）", "x", None, True),
    ("t3_area_mm2", "area", "面积", "mm2", "area_budget_mm2", False),
    ("t3_magic_gap", "magic_gap", "Magic Gap（模型 vs 仿真）", "x", "max_magic_gap", False),
)

_DIGIT = re.compile(r"\d")

_TIER_OF_PREFIX = {
    "t2_": (Tier.T2.value, "analytic"),
    "t3_": (Tier.T3.value, "sim"),
    "t4_": (Tier.T4.value, "sim"),
    "t5_": (Tier.T5.value, "rtl"),
}

BACKGROUND_PERSONA = """你为一份华为内部专利评审材料撰写「问题背景描述」。

要求：
1. 面向不熟悉本课题的评审专家，先讲清楚这个瓶颈为什么在业务上重要。
2. 必须基于给定的问题包条款，不要引入条款里没有的事实或数字。
3. 300-500 字，分 2-3 段，不要用列表。

只返回 JSON：{"background": "..."}  内容用简体中文。"""

EXISTING_TECH_PERSONA = """你为一份华为内部专利评审材料撰写「现有技术描述」。

要求：
1. 归纳目前业界主流做法及其固有缺陷，缺陷要指向本方案要解决的那个瓶颈。
2. 若给出了检索到的文献，必须基于文献内容归纳，不要编造不存在的工作。
3. 若没有检索结果，只做保守的常识性归纳，并在结尾注明「未经检索核实」。
4. 300-500 字。

只返回 JSON：{"existing_tech": "..."}  内容用简体中文。"""

SOLUTION_PERSONA = """你为一份华为内部专利评审材料撰写「技术方案」。

要求：
1. 把机制描述整理成可实施的方案：结构组成 + 工作流程。
2. steps 给出 4-8 个实施步骤，每步一句话，可被硬件工程师直接理解。
3. 只依据给定材料，不要补充材料里没有的实现细节。

只返回 JSON：{"solution": "整体方案叙述", "steps": ["步骤1", "步骤2"]}
内容用简体中文。"""

PROTECTION_PERSONA = """你为一份华为内部专利评审材料提炼「技术保护点」。

要求：
1. 给出 3-8 个保护点，第 1 个必须是最上位的独立保护点。
2. 每个保护点列出其必要技术特征（essential_features），特征要具体到可被侵权比对。
3. 从属保护点用 depends_on 指明它从属于第几个（从 1 开始计数）；独立保护点 depends_on 为 null。
4. 保护点之间不要重复，覆盖面要从上位到下位逐层收窄。

只返回 JSON：
{"points": [
  {"title": "...", "essential_features": ["...", "..."], "depends_on": null}
]}
内容用简体中文。"""

BENEFIT_PERSONA = """你为一份华为内部专利评审材料撰写「有益效果」的文字表述。

给你一组**已实测**的指标。你的任务只是把每个指标写成一句专利文书风格的效果陈述。

铁律：
1. 严禁修改、四舍五入或新增任何数字。数字由系统填充，你只写文字。
2. 每条 statement 中不要写具体数值，用「显著降低」「满足验收门限」这类表述，
   数值会由系统在渲染时附加。
3. 若指标列表为空，则只在 qualitative 中给出不含数字的定性效果。

只返回 JSON：
{"statements": {"指标键名": "该指标对应的效果陈述"},
 "qualitative": ["不含数字的定性效果1", "..."]}
内容用简体中文。"""


def _fmt(kind: str, value: float) -> str:
    if kind == "pct":
        return f"{value * 100:.1f}%"
    if kind == "x":
        return f"{value:.2f}×"
    if kind == "mm2":
        return f"{value:.3f} mm²"
    return f"{value:.3f}"


def _as_float(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _tier_for(metric_key: str) -> tuple[str | None, str]:
    for prefix, (tier, evidence) in _TIER_OF_PREFIX.items():
        if metric_key.startswith(prefix):
            return tier, evidence
    return None, "analytic"


def collect_benefits(
    candidate: Candidate,
    problem: ProblemPackage | None = None,
) -> list[BenefitClaim]:
    """Pull measured metrics out of the candidate. No LLM, no invention.

    Only the strongest evidence level per label survives, so a Tier4 sim number
    supersedes the Tier2 analytic estimate for the same quantity.
    """
    thresholds = parse_acceptance_thresholds(problem) if problem else None
    seen: set[str] = set()
    out: list[BenefitClaim] = []

    for key, quantity, label, kind, thr_attr, higher_better in _METRIC_SPECS:
        if key not in candidate.metrics or quantity in seen:
            continue
        value = _as_float(candidate.metrics.get(key))
        if value is None:
            continue
        seen.add(quantity)
        tier, evidence = _tier_for(key)

        threshold_text = ""
        meets: bool | None = None
        if thresholds is not None and thr_attr:
            limit = getattr(thresholds, thr_attr, None)
            if limit is not None:
                op = "≥" if higher_better else "≤"
                threshold_text = f"验收门限 {op} {_fmt(kind, float(limit))}"
                meets = value >= limit if higher_better else value <= limit

        out.append(
            BenefitClaim(
                statement=label,
                metric_key=key,
                metric_value=value,
                display_value=_fmt(kind, value),
                threshold=threshold_text,
                tier=tier,
                evidence_level=evidence,
                meets_threshold=meets,
            )
        )

    rtl = candidate.metrics.get("t5_rtl")
    if isinstance(rtl, dict) and rtl.get("equiv"):
        out.append(
            BenefitClaim(
                statement="RTL 实现已通过等价性验证",
                metric_key="t5_rtl.equiv",
                metric_value=rtl.get("equiv"),
                display_value="通过",
                tier=Tier.T5.value,
                evidence_level="rtl",
                meets_threshold=True,
            )
        )
    return out


def _strongest_evidence(candidate: Candidate) -> str:
    order = ["stub", "analytic", "sim", "rtl", "signoff"]
    best = "stub"
    for res in candidate.tier_history:
        level = res.evidence.value if hasattr(res.evidence, "value") else str(res.evidence)
        if level in order and order.index(level) > order.index(best):
            best = level
    return best


def _provenance(candidate: Candidate) -> dict:
    history = []
    for res in candidate.tier_history:
        history.append(
            {
                "tier": res.tier.value,
                "verdict": res.verdict.value,
                "score": res.score,
                "evidence": res.evidence.value
                if hasattr(res.evidence, "value")
                else str(res.evidence),
                "model_id": res.model_id,
                "prompt_hash": res.prompt_hash,
                "summary": res.summary[:200],
            }
        )
    return {
        "candidate_id": candidate.id,
        "family": candidate.family,
        "status": candidate.status,
        "clause_refs": candidate.clause_refs,
        "tier_history": history,
        "diverge_lens": candidate.metrics.get("diverge_lens"),
        "diverge_domain": candidate.metrics.get("diverge_domain"),
        "diverge_mode": candidate.metrics.get("diverge_mode"),
    }


def _read_artifact(candidate: Candidate, name: str, limit: int = 6000) -> str:
    if not candidate.workdir:
        return ""
    path = Path(candidate.workdir) / name
    if not path.is_file():
        return ""
    try:
        return path.read_text(encoding="utf-8")[:limit]
    except OSError:
        return ""


def _clause_block(problem: ProblemPackage | None, kinds: tuple[ClauseKind, ...]) -> str:
    if problem is None:
        return ""
    rows = [c for c in problem.clauses if c.kind in kinds]
    return "\n".join(f"{c.id}: {c.text}" for c in rows)


async def build_disclosure(
    cfg: FactoryConfig,
    candidate: Candidate,
    *,
    problem: ProblemPackage | None = None,
    llm: CursorLLM | None = None,
    search: bool = True,
    prior_art: PriorArtResult | None = None,
) -> PatentDisclosure:
    """Build all six sections. Each section degrades independently."""
    own = llm is None
    llm = llm or CursorLLM(cfg)
    if own:
        await llm.setup()

    disc = PatentDisclosure(
        candidate_id=candidate.id,
        title=candidate.title,
        problem_title=problem.title if problem else "",
        family=candidate.family,
        evidence_level=_strongest_evidence(candidate),
        provenance=_provenance(candidate),
    )

    try:
        # Section 6 first: sections 2 and 4 read better when they know the field.
        if prior_art is not None:
            disc.prior_art = prior_art
        else:
            disc.prior_art = await run_prior_art(
                cfg, candidate, problem=problem, llm=llm, search=search
            )

        ctx_clauses = _clause_block(
            problem, (ClauseKind.CONTEXT, ClauseKind.REQUIREMENT, ClauseKind.ACCEPTANCE)
        )
        disc.background_clauses = [
            c.id
            for c in (problem.clauses if problem else [])
            if c.kind
            in (ClauseKind.CONTEXT, ClauseKind.REQUIREMENT, ClauseKind.ACCEPTANCE)
        ]

        # 1. 问题背景
        try:
            data = _parse_json(
                await llm.complete(
                    BACKGROUND_PERSONA,
                    f"问题包标题：{disc.problem_title}\n\n条款：\n{ctx_clauses}",
                    TaskClass.PATENT_DRAFT,
                    expect_json=True,
                )
            )
            disc.background = str(data.get("background") or "").strip()
        except Exception as exc:  # noqa: BLE001
            disc.warnings.append(f"问题背景生成失败：{exc}")
            disc.background = ctx_clauses

        # 2. 现有技术
        try:
            hits_text = "\n".join(
                f"- {h.title} ({h.year or 'n.d.'}): {h.abstract[:500]}"
                for h in disc.prior_art.hits[:10]
            ) or "（无检索结果）"
            data = _parse_json(
                await llm.complete(
                    EXISTING_TECH_PERSONA,
                    f"本方案要解决的问题：\n{ctx_clauses}\n\n检索到的文献：\n{hits_text}",
                    TaskClass.PATENT_DRAFT,
                    expect_json=True,
                )
            )
            disc.existing_tech = str(data.get("existing_tech") or "").strip()
        except Exception as exc:  # noqa: BLE001
            disc.warnings.append(f"现有技术生成失败：{exc}")

        # 3. 技术方案
        spec_text = _read_artifact(candidate, "SPECIFICATION.md")
        model_text = _read_artifact(candidate, "model.py", limit=4000)
        solution_ctx = (
            f"方案标题：{candidate.title}\n\n机制描述：\n{candidate.mechanism}\n"
        )
        if spec_text:
            solution_ctx += f"\n形式化规格（Tier2 产出）：\n{spec_text}\n"
        if model_text:
            solution_ctx += f"\n解析模型代码（Tier2 产出）：\n{model_text}\n"
        try:
            data = _parse_json(
                await llm.complete(
                    SOLUTION_PERSONA,
                    solution_ctx,
                    TaskClass.PATENT_DRAFT,
                    expect_json=True,
                )
            )
            disc.technical_solution = str(data.get("solution") or "").strip()
            disc.solution_steps = [
                str(s).strip() for s in (data.get("steps") or []) if str(s).strip()
            ]
        except Exception as exc:  # noqa: BLE001
            disc.warnings.append(f"技术方案生成失败：{exc}")
            disc.technical_solution = candidate.mechanism

        # 4. 技术保护点
        try:
            data = _parse_json(
                await llm.complete(
                    PROTECTION_PERSONA,
                    solution_ctx,
                    TaskClass.PATENT_DRAFT,
                    expect_json=True,
                )
            )
            for i, row in enumerate(data.get("points") or [], start=1):
                if not isinstance(row, dict):
                    continue
                depends = row.get("depends_on")
                disc.protection_points.append(
                    ProtectionPoint(
                        index=i,
                        title=str(row.get("title") or f"保护点 {i}"),
                        essential_features=[
                            str(f) for f in (row.get("essential_features") or [])
                        ],
                        depends_on=int(depends) if isinstance(depends, int) else None,
                    )
                )
        except Exception as exc:  # noqa: BLE001
            disc.warnings.append(f"技术保护点生成失败：{exc}")

        # 5. 有益效果 — numbers from the funnel, wording from the LLM
        disc.benefits = collect_benefits(candidate, problem)
        if not disc.benefits:
            disc.benefits_note = (
                "该候选尚无实测指标（未跑到 Tier2 及以后），本节仅为定性描述，"
                "评审前请补充仿真数据。"
            )
            disc.warnings.append("无可引用的实测指标")
        try:
            listing = "\n".join(
                f"- {b.metric_key}: {b.statement}" for b in disc.benefits
            ) or "（无实测指标）"
            data = _parse_json(
                await llm.complete(
                    BENEFIT_PERSONA,
                    f"方案：{candidate.title}\n\n已实测指标：\n{listing}",
                    TaskClass.PATENT_DRAFT,
                    expect_json=True,
                )
            )
            worded = data.get("statements") or {}
            for benefit in disc.benefits:
                text = worded.get(benefit.metric_key or "")
                if not isinstance(text, str) or not text.strip():
                    continue
                # The measured value is rendered from metric_value; a number in
                # the prose can only be one the model made up.
                if _DIGIT.search(text):
                    disc.warnings.append(
                        f"{benefit.metric_key} 的措辞含自造数字，已丢弃并保留指标标签"
                    )
                    continue
                benefit.statement = text.strip()
            for extra in data.get("qualitative") or []:
                if str(extra).strip():
                    disc.benefits.append(
                        BenefitClaim(
                            statement=str(extra).strip(),
                            evidence_level="analytic",
                        )
                    )
        except Exception as exc:  # noqa: BLE001
            disc.warnings.append(f"有益效果措辞生成失败，保留原始指标标签：{exc}")
    finally:
        if own:
            await llm.aclose()

    return disc


def disclosure_markdown(disc: PatentDisclosure) -> str:
    lines = [
        f"# 专利交底书 — {disc.title}",
        "",
        f"- 候选 ID: `{disc.candidate_id}`",
        f"- 所属问题: {disc.problem_title or '（未关联问题包）'}",
        f"- 机制族: `{disc.family}`",
        f"- 最强证据等级: `{disc.evidence_level}`",
        f"- 生成时间: {disc.created_at.isoformat()}",
        "",
    ]

    lines += [f"## {SECTION_TITLES[0]}", "", disc.background or "_未生成_", ""]
    if disc.background_clauses:
        lines.append(f"依据条款: {', '.join(disc.background_clauses)}")
        lines.append("")

    lines += [f"## {SECTION_TITLES[1]}", "", disc.existing_tech or "_未生成_", ""]

    lines += [f"## {SECTION_TITLES[2]}", "", disc.technical_solution or "_未生成_", ""]
    if disc.solution_steps:
        lines.append("实施步骤：")
        lines.append("")
        for i, step in enumerate(disc.solution_steps, start=1):
            lines.append(f"{i}. {step}")
        lines.append("")

    lines += [f"## {SECTION_TITLES[3]}", ""]
    if disc.protection_points:
        for p in disc.protection_points:
            lines.append(f"### 保护点 {p.index}（{p.kind}）：{p.title}")
            lines.append("")
            for f in p.essential_features:
                lines.append(f"- {f}")
            lines.append("")
    else:
        lines += ["_未生成_", ""]

    lines += [f"## {SECTION_TITLES[4]}", ""]
    if disc.benefits_note:
        lines += [f"> {disc.benefits_note}", ""]
    quantified = [b for b in disc.benefits if b.quantified]
    if quantified:
        lines.append("| 效果 | 实测值 | 门限 | 达标 | 证据 | 来源 |")
        lines.append("| --- | --- | --- | --- | --- | --- |")
        for b in quantified:
            meets = "-" if b.meets_threshold is None else ("是" if b.meets_threshold else "否")
            lines.append(
                f"| {b.statement} | {b.display_value} | {b.threshold or '-'} | "
                f"{meets} | {b.evidence_level} | {b.tier or '-'} |"
            )
        lines.append("")
    qualitative = [b for b in disc.benefits if not b.quantified]
    if qualitative:
        lines.append("定性效果：")
        lines.append("")
        for b in qualitative:
            lines.append(f"- {b.statement}")
        lines.append("")

    lines.append(prior_art_markdown(disc.prior_art))

    if disc.warnings:
        lines += ["## 生成告警", ""]
        for w in disc.warnings:
            lines.append(f"- {w}")
        lines.append("")
    return "\n".join(lines)
