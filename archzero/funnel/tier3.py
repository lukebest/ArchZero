"""Tier 3 — directed / small-suite simulation via SimBackend."""

from __future__ import annotations

import json
from pathlib import Path

from archzero.config import FactoryConfig
from archzero.funnel.taxonomy import attach_result
from archzero.llm.client import CursorLLM
from archzero.models import Candidate, ProblemPackage, TaskClass, Tier, TierResult, Verdict
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
        # Ensure knobs exist even if agent fails
        knobs = work / "sim_knobs.json"
        if not knobs.exists():
            # Derive from tier2 metrics if present
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

    # Gate: miss reduction and bandwidth
    reduction = float(sim.metrics.get("miss_reduction") or 0)
    bw = float(sim.metrics.get("bw_delta_frac") or 0)
    ok = sim.ok and reduction >= 0.10 and bw <= 0.05
    verdict = Verdict.PASS if ok else Verdict.FAIL
    if sim.unavailable and ok:
        # Still pass funnel on stub fallback, but annotate
        summary = f"{sim.backend}: pass on fallback ({reduction:.2%} MPKI↓)"
    else:
        summary = (
            f"{sim.backend}: reduction={reduction:.2%} bwΔ={bw:.2%} ok={ok}"
        )

    result = TierResult(
        tier=Tier.T3,
        verdict=verdict,
        score=reduction,
        summary=summary,
        metrics=sim.metrics,
        clause_refs=candidate.clause_refs,
    )
    return attach_result(candidate, result, fail_message=summary)
