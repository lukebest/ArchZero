"""Combinatorial cross-domain divergence — mass ideation before Tier0.

Clean-room ideation (:mod:`archzero.generation.cleanroom`) produces a handful of
candidates from one prompt repeated N times, so the ideas cluster. Frontier
expansion (:mod:`archzero.generation.frontier`) does explore other paradigms but
runs *after* a campaign as a post-mortem.

This module front-loads the divergence: it samples cells from the
``theory lens x cross-domain source x expansion mode`` matrix and asks for a
batch of ideas per cell. One LLM call per cell keeps the call count at
``n_cells`` while the idea count is ``n_cells * per_cell``.
"""

from __future__ import annotations

import hashlib
import json
import logging
import random
import re
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass

from archzero.config import FactoryConfig
from archzero.generation.cleanroom import _parse_json
from archzero.generation.domains import DomainSource, select_domains
from archzero.generation.theories import THEORY_BY_ID, THEORY_LENSES, TheoryLens
from archzero.llm.client import CursorLLM
from archzero.models import Candidate, ProblemPackage, TaskClass

log = logging.getLogger("archzero.divergence")

VERTICAL = "vertical"
LATERAL = "lateral"
FOUNDATIONAL = "foundational"
EXPANSION_MODES: tuple[str, ...] = (VERTICAL, LATERAL, FOUNDATIONAL)

MODE_INSTRUCTIONS: dict[str, str] = {
    VERTICAL: (
        "纵向深化：在当前范式内把同一瓶颈压得更紧，给出更精确可测的机制。"
        "允许增量，但必须指出比现有做法强在哪个可量化维度。"
    ),
    LATERAL: (
        "横向迁移：找出跨域来源与本问题之间的抽象结构同构，把该领域的经典结果搬过来。"
        "必须明确写出「什么映射到什么」，而不是泛泛类比。"
    ),
    FOUNDATIONAL: (
        "根本重构：质疑这个问题是否应该以当前方式被解决。"
        "允许改变接口、改变抽象边界、或论证该瓶颈应当被消解而非优化。"
    ),
}

DIVERGE_PERSONA = """你是计算机体系结构机制发明者，正在做跨领域发散。

给你一个「理论透镜 + 跨域来源 + 发散模式」的组合，你要在这个组合的约束下产出多个**互不相同**的机制方案。

硬性要求：
1. 每个方案必须真正用上指定的理论透镜与跨域来源，但**只在 isomorphism 里点名源领域**；mechanism 用硬件语言写映射后的规则。
2. 每个方案必须落在数字 CMOS 物理可实现的范围内，不得违反守恒、带宽或 Amdahl 约束。
3. 同一次回答内的多个方案要机制上互不相同，不能是同一想法换措辞。
4. 必须引用问题包中的条款 ID（如 REQ-001、ACC-001）说明该方案回应了哪条要求。
5. title 与 mechanism 必须让做过 NoC/缓存的工程师不查隐喻词典就能实现（见机制写法）。

只返回 JSON：
{
  "ideas": [
    {
      "title": "硬件小节标题，不要跨学科专名",
      "family": "prefetch",
      "mechanism": "决策：...\\n状态：...\\n冲突：...\\n相对基线：...",
      "isomorphism": "跨域来源的什么结构映射到本问题的什么硬件规则",
      "expected_effect": "...",
      "risks": "...",
      "clause_refs": ["REQ-001"]
    }
  ]
}

title、mechanism、isomorphism、expected_effect、risks 必须原生用简体中文撰写。
family 用简短英文标识（如 prefetch、noc_rg、cache、sched）。
"""

_CJK = re.compile(r"[\u4e00-\u9fff]")
_ASCII = re.compile(r"[a-z0-9]+", re.I)


def _affinity_tokens(text: str) -> set[str]:
    """CJK bigrams + ASCII words. The repo tokenizer is ASCII-only."""
    text = text or ""
    toks = {t.lower() for t in _ASCII.findall(text) if len(t) > 2}
    cjk = "".join(_CJK.findall(text))
    toks |= {cjk[i : i + 2] for i in range(len(cjk) - 1)}
    return toks


def _affinity(problem_tokens: set[str], text: str) -> float:
    other = _affinity_tokens(text)
    if not problem_tokens or not other:
        return 0.0
    return len(problem_tokens & other) / len(other)


def select_lenses(ids: list[str] | None = None) -> tuple[TheoryLens, ...]:
    if not ids:
        return THEORY_LENSES
    picked = tuple(THEORY_BY_ID[i] for i in ids if i in THEORY_BY_ID)
    return picked or THEORY_LENSES


@dataclass(frozen=True)
class MatrixCell:
    lens: TheoryLens
    domain: DomainSource
    mode: str

    @property
    def id(self) -> str:
        return f"{self.mode}:{self.lens.id}:{self.domain.id}"


def problem_text(problem: ProblemPackage) -> str:
    parts = [problem.title]
    parts.extend(c.text for c in problem.clauses)
    parts.extend(problem.open_questions)
    return "\n".join(p for p in parts if p)


def build_matrix(
    problem: ProblemPackage,
    *,
    n_cells: int,
    lens_ids: list[str] | None = None,
    domain_ids: list[str] | None = None,
    modes: tuple[str, ...] = EXPANSION_MODES,
    seed: str | int | None = None,
) -> list[MatrixCell]:
    """Pick ``n_cells`` cells with even lens/domain/mode coverage.

    Selection is greedy on least-used lens, then least-used domain, then
    least-used mode, with problem affinity as the tiebreaker. That keeps the
    matrix balanced for small ``n_cells`` while still favouring sources whose
    vocabulary overlaps the problem package.
    """
    lenses = select_lenses(lens_ids)
    domains = select_domains(domain_ids)
    modes = tuple(modes) or EXPANSION_MODES

    pool = [
        MatrixCell(lens=lens, domain=domain, mode=mode)
        for lens in lenses
        for domain in domains
        for mode in modes
    ]
    if not pool:
        return []

    ptoks = _affinity_tokens(problem_text(problem))
    aff: dict[str, float] = {}
    for cell in pool:
        key = cell.id
        if key not in aff:
            aff[key] = _affinity(
                ptoks,
                f"{cell.lens.name} {cell.lens.paper_hint} "
                f"{cell.domain.name} {cell.domain.classic_result} {cell.domain.transfer_hint}",
            )

    rng = random.Random(seed if seed is not None else problem.id)
    rng.shuffle(pool)

    lens_use: Counter[str] = Counter()
    dom_use: Counter[str] = Counter()
    mode_use: Counter[str] = Counter()
    chosen: list[MatrixCell] = []

    for _ in range(min(n_cells, len(pool))):
        best_i = min(
            range(len(pool)),
            key=lambda i: (
                lens_use[pool[i].lens.id],
                dom_use[pool[i].domain.id],
                mode_use[pool[i].mode],
                -aff[pool[i].id],
            ),
        )
        cell = pool.pop(best_i)
        lens_use[cell.lens.id] += 1
        dom_use[cell.domain.id] += 1
        mode_use[cell.mode] += 1
        chosen.append(cell)
    return chosen


def _cell_prompt(
    cell: MatrixCell,
    problem: ProblemPackage,
    per_cell: int,
) -> str:
    clauses = "\n".join(f"{c.id} [{c.kind.value}]: {c.text}" for c in problem.clauses)
    lens_qs = "\n".join(f"- {q}" for q in cell.lens.prompts)
    return (
        f"发散模式: {cell.mode}\n"
        f"{MODE_INSTRUCTIONS[cell.mode]}\n\n"
        f"理论透镜: {cell.lens.name} ({cell.lens.id})\n"
        f"透镜内涵: {cell.lens.paper_hint}\n"
        f"透镜必须回答的问题:\n{lens_qs}\n\n"
        f"跨域来源: {cell.domain.name} ({cell.domain.id})\n"
        f"该领域经典结果: {cell.domain.classic_result}\n"
        f"迁移提示: {cell.domain.transfer_hint}\n\n"
        f"问题包标题: {problem.title}\n"
        f"问题包条款:\n{clauses}\n\n"
        f"请在上述组合约束下产出 {per_cell} 个互不相同的机制方案。"
        f"mechanism 必须是「决策 / 状态 / 冲突 / 相对基线」四段硬件说明，"
        f"不要用 {cell.domain.name} 或 {cell.lens.name} 的术语写正文。"
        f"只改问题包已声明的拓扑、接口与自由度；"
        f"不要发明 credit、额外拓扑、缓存 set 索引或规格里没有的资源。"
    )


def _content_hash(title: str, mechanism: str) -> str:
    return hashlib.sha256((title + "\n" + mechanism).encode("utf-8")).hexdigest()[:16]


def _to_candidates(
    raw: dict,
    cell: MatrixCell,
    problem: ProblemPackage,
) -> list[Candidate]:
    ideas = raw.get("ideas")
    if not isinstance(ideas, list):
        return []
    out: list[Candidate] = []
    for item in ideas:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        mechanism = str(item.get("mechanism") or "").strip()
        if not title or not mechanism:
            continue
        out.append(
            Candidate(
                problem_id=problem.id,
                title=title,
                mechanism=mechanism,
                family=str(item.get("family") or "unclassified"),
                clause_refs=[str(c) for c in (item.get("clause_refs") or [])],
                content_hash=_content_hash(title, mechanism),
                metrics={
                    "diverge_lens": cell.lens.id,
                    "diverge_domain": cell.domain.id,
                    "diverge_mode": cell.mode,
                    "diverge_isomorphism": item.get("isomorphism"),
                    "expected_effect": item.get("expected_effect"),
                    "risks": item.get("risks"),
                },
            )
        )
    return out


async def diverge(
    cfg: FactoryConfig,
    problem: ProblemPackage,
    *,
    n_cells: int = 12,
    per_cell: int = 6,
    lens_ids: list[str] | None = None,
    domain_ids: list[str] | None = None,
    llm: CursorLLM | None = None,
    seed: str | int | None = None,
    on_candidates: Callable[[list[Candidate]], None] | None = None,
    should_stop: Callable[[], bool] | None = None,
) -> list[Candidate]:
    """Run the divergence matrix and return the raw idea pool.

    Cell failures are logged and skipped; a partial pool is far more useful
    than aborting the whole campaign because one prompt came back malformed.
    ``on_candidates`` is called as each cell finishes so the dashboard can
    show ideas before the whole matrix returns.
    """
    from archzero.worker.queue import LocalWorkerPool, WorkerJob

    cells = build_matrix(
        problem,
        n_cells=n_cells,
        lens_ids=lens_ids,
        domain_ids=domain_ids,
        seed=seed,
    )
    if not cells:
        return []

    own = llm is None
    llm = llm or CursorLLM(cfg)
    if own:
        await llm.setup()

    async def _handle(job: WorkerJob[MatrixCell]) -> list[Candidate]:
        if should_stop is not None and should_stop():
            return []
        cell = job.payload
        raw = _parse_json(
            await llm.complete(
                DIVERGE_PERSONA,
                _cell_prompt(cell, problem, per_cell),
                TaskClass.IDEATE,
                expect_json=True,
            )
        )
        cands = _to_candidates(raw, cell, problem)
        if on_candidates and cands:
            on_candidates(cands)
        return cands

    try:
        pool = LocalWorkerPool(concurrency=cfg.budget.concurrency)
        results = await pool.map(
            [WorkerJob(id=c.id, payload=c) for c in cells],
            _handle,
            should_stop=should_stop,
        )
    finally:
        if own:
            await llm.aclose()

    candidates: list[Candidate] = []
    for res in results:
        if res.ok and res.value:
            candidates.extend(res.value)
        elif not res.ok:
            log.warning(
                "diverge_cell_failed",
                extra={"cell": res.job_id, "error": res.error},
            )
    return candidates


def divergence_markdown(
    problem: ProblemPackage,
    cells: list[MatrixCell],
    candidates: list[Candidate],
) -> str:
    """Human-readable dump of the idea pool, grouped by matrix cell."""
    by_cell: dict[str, list[Candidate]] = {}
    for c in candidates:
        key = (
            f"{c.metrics.get('diverge_mode')}:"
            f"{c.metrics.get('diverge_lens')}:"
            f"{c.metrics.get('diverge_domain')}"
        )
        by_cell.setdefault(key, []).append(c)

    lines = [
        f"# 跨领域发散 — {problem.title}",
        "",
        f"- 矩阵 cell 数: {len(cells)}",
        f"- idea 总数: {len(candidates)}",
        "",
    ]
    for cell in cells:
        got = by_cell.get(cell.id, [])
        lines.append(f"## {cell.mode} · {cell.lens.name} × {cell.domain.name}")
        lines.append("")
        if not got:
            lines.append("_该 cell 未产出可用 idea_")
            lines.append("")
            continue
        for c in got:
            lines.append(f"### {c.title}")
            lines.append("")
            lines.append(f"- family: `{c.family}`")
            if c.clause_refs:
                lines.append(f"- 条款: {', '.join(c.clause_refs)}")
            iso = c.metrics.get("diverge_isomorphism")
            if iso:
                lines.append(f"- 同构映射: {iso}")
            lines.append("")
            lines.append(c.mechanism)
            lines.append("")
    return "\n".join(lines)


def coverage_summary(cells: list[MatrixCell]) -> dict[str, dict[str, int]]:
    """Per-axis usage counts — used by the CLI and by tests."""
    return {
        "lens": dict(Counter(c.lens.id for c in cells)),
        "domain": dict(Counter(c.domain.id for c in cells)),
        "mode": dict(Counter(c.mode for c in cells)),
    }


def pool_stats(candidates: list[Candidate]) -> dict[str, dict[str, int]]:
    """Idea counts per axis — lets the funnel report which sources survived."""
    return {
        "lens": dict(Counter(str(c.metrics.get("diverge_lens")) for c in candidates)),
        "domain": dict(
            Counter(str(c.metrics.get("diverge_domain")) for c in candidates)
        ),
        "mode": dict(Counter(str(c.metrics.get("diverge_mode")) for c in candidates)),
    }


def dumps_pool(candidates: list[Candidate]) -> str:
    return json.dumps(
        [c.model_dump(mode="json") for c in candidates], indent=2, ensure_ascii=False
    )
