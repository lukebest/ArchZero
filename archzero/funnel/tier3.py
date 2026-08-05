"""Tier 3 — directed / small-suite simulation via SimBackend."""

from __future__ import annotations

import json
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

HARNESS_PERSONA = """You prepare a simulation harness for an architecture mechanism.
Write sim_knobs.json with miss_reduction, extra_bw, area reflecting the mechanism.
Optionally write a brief SIM_PLAN.md. Keep knobs physically plausible."""


async def evaluate_tier3(
    cfg: FactoryConfig,
    candidate: Candidate,
    problem: ProblemPackage,
    llm: CursorLLM,
) -> Candidate:
    work = Path(candidate.workdir or (cfg.scratch_dir / candidate.id))
    work.mkdir(parents=True, exist_ok=True)
    candidate.workdir = str(work)

    instruction = (
        f"Mechanism: {candidate.title}\n{candidate.mechanism}\n\n"
        f"Problem: {problem.title}\n"
        "Create sim_knobs.json for the stub/ChampSim/gem5 adapter."
    )
    try:
        await llm.work(HARNESS_PERSONA, instruction, TaskClass.ANALYTIC, cwd=work)
    except Exception:  # noqa: BLE001
        knobs = work / "sim_knobs.json"
        if not knobs.exists():
            knobs.write_text(
                json.dumps(
                    {
                        "miss_reduction": float(
                            candidate.metrics.get("t2_miss_reduction") or 0.12
                        ),
                        "extra_bw": 0.02,
                        "area": 0.3,
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )

    backend = get_backend(cfg)
    sim = backend.run(
        SimRequest(
            candidate_id=candidate.id,
            workdir=work,
            patch_hint=candidate.mechanism[:500],
            suite="small",
        )
    )
    candidate.metrics.update({f"t3_{k}": v for k, v in sim.metrics.items()})

    reduction = float(sim.metrics.get("miss_reduction") or 0)
    bw = float(sim.metrics.get("bw_delta_frac") or 0)
    gate_ok = sim.ok and reduction >= 0.10 and bw <= 0.05

    evidence = EvidenceLevel.STUB
    if sim.metrics.get("evidence") == "sim" or (
        not sim.unavailable and cfg.sim.backend != "stub"
    ):
        evidence = EvidenceLevel.SIM
    if str(sim.metrics.get("evidence") or "") == "stub":
        evidence = EvidenceLevel.STUB

    # Fail-closed: configured real backend unavailable → UNAVAILABLE, never PASS
    if sim.unavailable and cfg.funnel.strict_evidence and cfg.sim.backend != "stub":
        verdict = Verdict.UNAVAILABLE
        summary = (
            f"{sim.backend}: UNAVAILABLE (strict_evidence; configured "
            f"backend={cfg.sim.backend})"
        )
        result = TierResult(
            tier=Tier.T3,
            verdict=verdict,
            score=reduction,
            summary=summary,
            metrics=sim.metrics,
            evidence=EvidenceLevel.STUB,
            clause_refs=candidate.clause_refs,
        )
        apply_llm_provenance(result, llm)
        candidate.tier_history.append(result)
        candidate.status = "active"
        return candidate

    if cfg.sim.backend == "stub" or evidence == EvidenceLevel.STUB:
        # Explicit stub path: allowed only when backend is stub
        if cfg.sim.backend != "stub" and cfg.funnel.strict_evidence:
            verdict = Verdict.UNAVAILABLE
            summary = f"{sim.backend}: stub evidence rejected under strict_evidence"
        else:
            verdict = Verdict.PASS if gate_ok else Verdict.FAIL
            summary = f"{sim.backend}: stub evidence reduction={reduction:.2%} bwΔ={bw:.2%}"
            evidence = EvidenceLevel.STUB
    else:
        verdict = Verdict.PASS if gate_ok else Verdict.FAIL
        summary = f"{sim.backend}: reduction={reduction:.2%} bwΔ={bw:.2%} ok={gate_ok}"

    result = TierResult(
        tier=Tier.T3,
        verdict=verdict,
        score=reduction,
        summary=summary,
        metrics=sim.metrics,
        evidence=evidence,
        clause_refs=candidate.clause_refs,
    )
    apply_llm_provenance(result, llm)
    if verdict == Verdict.UNAVAILABLE:
        candidate.tier_history.append(result)
        candidate.status = "active"
        return candidate
    return attach_result(candidate, result, fail_message=summary)
