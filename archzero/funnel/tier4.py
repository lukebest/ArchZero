"""Tier 4 — fuller simulation suite + final-judge adjudication."""

from __future__ import annotations

import json
import re
from pathlib import Path

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
from archzero.sim.backend import SimRequest, get_backend

JUDGE_PERSONA = """You are the final simulation adjudicator for an architecture funnel.
Given problem acceptance criteria and simulation metrics, decide pass/fail.
Return JSON: {verdict: pass|fail, score:0-1, summary, clause_refs:[]}"""


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


async def evaluate_tier4(
    cfg: FactoryConfig,
    candidate: Candidate,
    problem: ProblemPackage,
    llm: CursorLLM,
) -> Candidate:
    work = Path(candidate.workdir or (cfg.scratch_dir / candidate.id))
    work.mkdir(parents=True, exist_ok=True)
    candidate.workdir = str(work)

    backend = get_backend(cfg)
    sim = backend.run(
        SimRequest(
            candidate_id=candidate.id,
            workdir=work,
            patch_hint=candidate.mechanism[:500],
            suite="full",
        )
    )
    candidate.metrics.update({f"t4_{k}": v for k, v in sim.metrics.items()})

    evidence = EvidenceLevel.STUB
    if not sim.unavailable and cfg.sim.backend != "stub":
        evidence = EvidenceLevel.SIM
    if str(sim.metrics.get("evidence") or "") == "stub":
        evidence = EvidenceLevel.STUB

    if sim.unavailable and cfg.funnel.strict_evidence and cfg.sim.backend != "stub":
        result = TierResult(
            tier=Tier.T4,
            verdict=Verdict.UNAVAILABLE,
            score=float(sim.metrics.get("miss_reduction") or 0),
            summary=f"{sim.backend}: UNAVAILABLE under strict_evidence",
            metrics=sim.metrics,
            evidence=EvidenceLevel.STUB,
            clause_refs=candidate.clause_refs,
        )
        apply_llm_provenance(result, llm)
        candidate.tier_history.append(result)
        candidate.status = "active"
        return candidate

    acc = "\n".join(
        f"{c.id}: {c.text}" for c in problem.clauses if c.id.startswith("ACC")
    )
    ctx = (
        f"PROBLEM: {problem.title}\nACCEPTANCE:\n{acc}\n\n"
        f"CANDIDATE: {candidate.title}\n"
        f"SIM METRICS:\n{json.dumps(sim.metrics, indent=2)}\n"
        f"backend={sim.backend} unavailable_flag={sim.unavailable} evidence={evidence.value}"
    )
    try:
        data = _parse_json(
            await llm.complete(JUDGE_PERSONA, ctx, TaskClass.FINAL_JUDGE, expect_json=True)
        )
    except Exception as exc:  # noqa: BLE001
        # Fail closed on judge error when not stub; stub uses heuristic
        reduction = float(sim.metrics.get("miss_reduction") or 0)
        if evidence == EvidenceLevel.STUB and cfg.sim.backend == "stub":
            data = {
                "verdict": "pass" if sim.ok and reduction >= 0.15 else "fail",
                "summary": f"judge fallback (stub): {exc}",
                "score": reduction,
            }
        else:
            data = {
                "verdict": "fail",
                "summary": f"judge error (fail-closed): {exc}",
                "score": reduction,
            }

    verdict = Verdict.PASS if str(data.get("verdict")).lower() == "pass" else Verdict.FAIL
    result = TierResult(
        tier=Tier.T4,
        verdict=verdict,
        score=float(data.get("score") or sim.metrics.get("miss_reduction") or 0),
        summary=str(data.get("summary") or ""),
        metrics=sim.metrics,
        evidence=evidence,
        clause_refs=list(data.get("clause_refs") or candidate.clause_refs),
    )
    apply_llm_provenance(result, llm, prompt=ctx)
    return attach_result(candidate, result, fail_message=result.summary)
