"""Tier 0 — first-principles hard screen (pool 1 / bulk)."""

from __future__ import annotations

import json
import re

from archzero.config import FactoryConfig
from archzero.funnel.errors import infra_result, is_infra_error
from archzero.funnel.provenance import apply_llm_provenance
from archzero.funnel.taxonomy import attach_result
from archzero.llm.client import CursorLLM
from archzero.models import (
    Candidate,
    EvidenceLevel,
    ProblemPackage,
    TaskClass,
    Tier,
    TierResult,
    Verdict,
)

PERSONA = """你是计算机体系结构第一性原理硬筛评审。
否决违反守恒律、带宽上限、Amdahl 界限或问题包硬约束的机制。严厉但公允。
只返回 JSON：{verdict: pass|fail, score: 0-1, summary, physics_flags: [], clause_refs: []}
summary 必须原生简体中文；verdict 保持英文枚举。"""

BATCH_PERSONA = """你是计算机体系结构第一性原理硬筛评审，正在批量筛查。
否决违反守恒律、带宽上限、Amdahl 界限或问题包硬约束的机制。严厉但公允。
逐个独立判断，不要因为同批其他方案而放宽或收紧标准。

只返回 JSON：
{"results": [
  {"index": 1, "verdict": "pass", "score": 0.8, "summary": "...",
   "physics_flags": [], "clause_refs": []}
]}
必须为每个候选返回一条结果，index 与输入编号一一对应。
summary 必须原生简体中文；verdict 保持英文枚举。"""


def _parse_json(text: str) -> dict:
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if fence:
        text = fence.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            try:
                return json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                pass
        return {"verdict": "fail", "summary": text[:500], "score": 0.0}


def _constraints(problem: ProblemPackage) -> str:
    return "\n".join(f"{c.id} [{c.kind.value}]: {c.text}" for c in problem.clauses)


def _attach(candidate: Candidate, data: dict, llm: CursorLLM, prompt: str) -> Candidate:
    verdict_raw = str(data.get("verdict", "fail")).lower()
    verdict = Verdict.PASS if verdict_raw == "pass" else Verdict.FAIL
    result = TierResult(
        tier=Tier.T0,
        verdict=verdict,
        score=float(data.get("score") or 0.0),
        summary=str(data.get("summary") or ""),
        metrics={"physics_flags": data.get("physics_flags") or []},
        evidence=EvidenceLevel.ANALYTIC,
        clause_refs=list(data.get("clause_refs") or candidate.clause_refs),
    )
    apply_llm_provenance(result, llm, prompt=prompt)
    return attach_result(candidate, result, fail_message=result.summary)


async def evaluate_tier0_batch(
    cfg: FactoryConfig,
    candidates: list[Candidate],
    problem: ProblemPackage,
    llm: CursorLLM,
) -> list[Candidate]:
    """Screen a whole batch in one call — cuts Tier0 cost by ~batch_size.

    Only worth using on large divergence pools. A candidate the model forgot to
    score fails closed rather than slipping through unscreened.
    """
    if not candidates:
        return []
    listing = "\n\n".join(
        f"[{i + 1}] {c.title}\nFamily: {c.family}\n{c.mechanism}"
        for i, c in enumerate(candidates)
    )
    ctx = (
        f"PROBLEM CONSTRAINTS:\n{_constraints(problem)}\n\n"
        f"共 {len(candidates)} 个候选，逐个硬筛：\n\n{listing}\n"
    )
    try:
        data = _parse_json(
            await llm.complete(
                BATCH_PERSONA, ctx, TaskClass.BULK_SCREEN, expect_json=True
            )
        )
        rows = data.get("results") or []
    except Exception as exc:  # noqa: BLE001
        if is_infra_error(str(exc), exc):
            return [
                attach_result(c, infra_result(Tier.T0, f"tier0 batch error: {exc}"))
                for c in candidates
            ]
        rows = []
        data = {"error": str(exc)}

    by_index: dict[int, dict] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        try:
            by_index[int(row.get("index"))] = row
        except (TypeError, ValueError):
            continue

    out: list[Candidate] = []
    for i, cand in enumerate(candidates, start=1):
        row = by_index.get(i)
        if row is None:
            row = {
                "verdict": "fail",
                "score": 0.0,
                "summary": f"批量硬筛未返回该候选的评审结果（index={i}）"
                + (f"：{data.get('error')}" if data.get("error") else ""),
            }
        out.append(_attach(cand, row, llm, ctx))
    return out


async def evaluate_tier0(
    cfg: FactoryConfig,
    candidate: Candidate,
    problem: ProblemPackage,
    llm: CursorLLM,
) -> Candidate:
    constraints = _constraints(problem)
    ctx = (
        f"PROBLEM CONSTRAINTS:\n{constraints}\n\n"
        f"CANDIDATE: {candidate.title}\nFamily: {candidate.family}\n\n"
        f"{candidate.mechanism}\n"
    )
    try:
        data = _parse_json(
            await llm.complete(PERSONA, ctx, TaskClass.BULK_SCREEN, expect_json=True)
        )
    except Exception as exc:  # noqa: BLE001
        if is_infra_error(str(exc), exc):
            return attach_result(candidate, infra_result(Tier.T0, f"tier0 error: {exc}"))
        data = {"verdict": "fail", "summary": f"tier0 error: {exc}", "score": 0.0}

    return _attach(candidate, data, llm, ctx)
