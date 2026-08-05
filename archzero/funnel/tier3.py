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
from archzero.sim.generate import generate_dedicated_sim, generate_dedicated_sim_llm
from archzero.sim.mechanism_model import report_magic_gap
from archzero.sim.metrics import SimMetrics
from archzero.spec.acc_parse import parse_acceptance_thresholds

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
    th = parse_acceptance_thresholds(problem)

    instruction = (
        f"Mechanism: {candidate.title}\n{candidate.mechanism}\n\n"
        f"Problem: {problem.title}\n"
        "Create sim_knobs.json for the stub/ChampSim/gem5/directed adapter."
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
                            candidate.metrics.get("t2_miss_reduction") or 0.18
                        ),
                        "extra_bw": 0.02,
                        "area": 0.3,
                        "family": candidate.family or "other",
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )

    # Generate audit-able dedicated simulator source (prefetch/replacement/bypass…)
    knobs_path = work / "sim_knobs.json"
    knobs_data = {}
    if knobs_path.exists():
        try:
            knobs_data = json.loads(knobs_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            knobs_data = {}
    if cfg.funnel.llm_dedicated_sim:
        gen = await generate_dedicated_sim_llm(
            work,
            title=candidate.title,
            mechanism=candidate.mechanism,
            knobs=knobs_data,
            family=candidate.family,
            llm=llm,
        )
    else:
        gen = generate_dedicated_sim(
            work,
            title=candidate.title,
            mechanism=candidate.mechanism,
            knobs=knobs_data,
            family=candidate.family,
        )
    candidate.metrics["t3_dedicated_selftest"] = gen.selftest_ok
    candidate.metrics["t3_dedicated_family"] = gen.family
    if gen.selftest_ok and gen.metrics:
        candidate.metrics["t3_dedicated_miss_reduction"] = gen.metrics.get(
            "miss_reduction"
        )

    backend = get_backend(cfg)
    sim = backend.run(
        SimRequest(
            candidate_id=candidate.id,
            workdir=work,
            patch_hint=candidate.mechanism[:500],
            suite="small",
            meta={
                "title": candidate.title,
                "mechanism": candidate.mechanism,
                "family": candidate.family,
                "min_miss_reduction": th.min_miss_reduction,
                "max_bw_delta_frac": th.max_bw_delta_frac,
            },
        )
    )
    candidate.metrics.update({f"t3_{k}": v for k, v in sim.metrics.items()})

    reduction = float(sim.metrics.get("miss_reduction") or 0)
    bw = float(sim.metrics.get("bw_delta_frac") or 0)
    metrics_obj = SimMetrics(
        miss_reduction=reduction,
        bw_delta_frac=bw,
        evidence=str(sim.metrics.get("evidence") or "stub"),
        backend=sim.backend,
    )
    gate_ok = sim.ok and metrics_obj.gate_ok(
        min_reduction=th.min_miss_reduction, max_bw=th.max_bw_delta_frac
    )

    model_red = candidate.metrics.get("t2_miss_reduction")
    gap = report_magic_gap(
        float(model_red) if model_red is not None else None,
        reduction,
    )
    if gap is not None:
        candidate.metrics["t3_magic_gap"] = gap
        if gap > th.max_magic_gap:
            gate_ok = False

    evidence = EvidenceLevel.STUB
    ev = str(sim.metrics.get("evidence") or "")
    if ev == "directed":
        evidence = EvidenceLevel.SIM
    elif ev == "sim" or (not sim.unavailable and cfg.sim.backend not in {"stub", "directed"}):
        evidence = EvidenceLevel.SIM
    if ev == "stub":
        evidence = EvidenceLevel.STUB

    # Fail-closed: configured real backend unavailable → UNAVAILABLE, never PASS
    if sim.unavailable and cfg.funnel.strict_evidence and cfg.sim.backend not in {
        "stub",
        "directed",
    }:
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
            metrics={**sim.metrics, "thresholds": th.as_dict(), "magic_gap": gap,
                 "dedicated_selftest": gen.selftest_ok,
                 "dedicated_family": gen.family,
                 "dedicated_metrics": gen.metrics},
            evidence=EvidenceLevel.STUB,
            clause_refs=candidate.clause_refs,
        )
        apply_llm_provenance(result, llm)
        candidate.tier_history.append(result)
        candidate.status = "active"
        return candidate

    if cfg.sim.backend == "stub" or evidence == EvidenceLevel.STUB:
        if cfg.sim.backend not in {"stub", "directed"} and cfg.funnel.strict_evidence:
            verdict = Verdict.UNAVAILABLE
            summary = f"{sim.backend}: stub evidence rejected under strict_evidence"
        else:
            verdict = Verdict.PASS if gate_ok else Verdict.FAIL
            gap_note = f" magic_gap={gap:.2f}" if gap is not None else ""
            summary = (
                f"{sim.backend}: stub evidence reduction={reduction:.2%} "
                f"bwΔ={bw:.2%}{gap_note}"
            )
            evidence = EvidenceLevel.STUB
    else:
        verdict = Verdict.PASS if gate_ok else Verdict.FAIL
        gap_note = f" magic_gap={gap:.2f}" if gap is not None else ""
        summary = (
            f"{sim.backend}: reduction={reduction:.2%} bwΔ={bw:.2%} "
            f"ok={gate_ok}{gap_note}"
        )

    result = TierResult(
        tier=Tier.T3,
        verdict=verdict,
        score=reduction,
        summary=summary,
        metrics={**sim.metrics, "thresholds": th.as_dict(), "magic_gap": gap,
                 "dedicated_selftest": gen.selftest_ok,
                 "dedicated_family": gen.family,
                 "dedicated_metrics": gen.metrics},
        evidence=evidence,
        clause_refs=candidate.clause_refs,
    )
    apply_llm_provenance(result, llm)
    if verdict == Verdict.UNAVAILABLE:
        candidate.tier_history.append(result)
        candidate.status = "active"
        return candidate
    return attach_result(candidate, result, fail_message=summary)
