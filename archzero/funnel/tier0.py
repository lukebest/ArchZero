"""Tier 0 — first-principles hard screen (pool 1 / bulk)."""

from __future__ import annotations

import json
import re

from archzero.config import FactoryConfig
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


async def evaluate_tier0(
    cfg: FactoryConfig,
    candidate: Candidate,
    problem: ProblemPackage,
    llm: CursorLLM,
) -> Candidate:
    constraints = "\n".join(
        f"{c.id} [{c.kind.value}]: {c.text}" for c in problem.clauses
    )
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
        data = {"verdict": "fail", "summary": f"tier0 error: {exc}", "score": 0.0}

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
    apply_llm_provenance(result, llm, prompt=ctx)
    return attach_result(candidate, result, fail_message=result.summary)
