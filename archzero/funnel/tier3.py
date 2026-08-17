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
from archzero.sim.backend import SimRequest
from archzero.sim.champsim_config import write_champsim_scaffold
from archzero.sim.gem5_harness import write_gem5_harness
from archzero.sim.generate import generate_dedicated_sim, generate_dedicated_sim_llm
from archzero.sim.headlines import headlines_text, ranking_score
from archzero.sim.mechanism_model import domain_magic_gap
from archzero.sim.metrics import SimMetrics
from archzero.sim.registry import resolve_backend_for_domain
from archzero.spec.acc_parse import parse_acceptance_thresholds

HARNESS_PERSONA_CACHE = """You prepare a simulation harness for an architecture mechanism.
Write sim_knobs.json with miss_reduction, extra_bw, area reflecting the mechanism.
Optionally write a brief SIM_PLAN.md. Keep knobs physically plausible."""

HARNESS_PERSONA_DOMAIN = """You prepare a simulation harness for an off-cache architecture
mechanism (NoC / dataflow / wafer-scale fabric). Write sim_knobs.json with a
`family` key naming the mechanism family and a `domain` key. Do NOT invent
miss_reduction, extra_bw, or area — those are cache metrics and do not apply.
Optionally write a brief SIM_PLAN.md."""

HARNESS_PERSONA = HARNESS_PERSONA_CACHE


def _harness_persona(domain: str) -> str:
    if domain in {"noc", "dataflow", "wafer"}:
        return HARNESS_PERSONA_DOMAIN
    return HARNESS_PERSONA_CACHE


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
        await llm.work(_harness_persona(th.domain), instruction, TaskClass.ANALYTIC, cwd=work)
    except Exception:  # noqa: BLE001
        knobs = work / "sim_knobs.json"
        if not knobs.exists():
            if th.domain != "cache":
                knobs.write_text(
                    json.dumps(
                        {
                            "family": candidate.family,
                            "domain": th.domain,
                        },
                        indent=2,
                    ),
                    encoding="utf-8",
                )
            else:
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
    if cfg.sim.backend == "champsim":
        sc = write_champsim_scaffold(
            work,
            family=candidate.family,
            knobs=knobs_data,
            title=candidate.title,
        )
        candidate.metrics["t3_champsim_module"] = sc.get("module")
    if cfg.sim.backend == "gem5":
        gh = write_gem5_harness(
            work, knobs=knobs_data, family=candidate.family, domain=th.domain
        )
        candidate.metrics["t3_gem5_harness"] = gh.get("path")
        if "inapplicable" in gh:
            candidate.metrics["t3_gem5_inapplicable"] = gh["inapplicable"]
    candidate.metrics["t3_dedicated_family"] = gen.family
    if gen.selftest_ok and gen.metrics and "miss_reduction" in gen.metrics:
        candidate.metrics["t3_dedicated_miss_reduction"] = gen.metrics.get(
            "miss_reduction"
        )

    backend, backend_name, route_reason = resolve_backend_for_domain(cfg, th.domain)
    if route_reason:
        candidate.metrics["t3_backend_route"] = route_reason
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
                "area_budget_mm2": th.area_budget_mm2,
                "domain": th.domain,
            },
        )
    )
    candidate.metrics.update({f"t3_{k}": v for k, v in sim.metrics.items()})

    known = set(SimMetrics.model_fields)
    metrics_obj = SimMetrics.model_validate(
        {k: v for k, v in sim.metrics.items() if k in known}
    )
    outcome = metrics_obj.apply_gates(th.spec_gates())
    gate_ok = sim.ok and outcome.ok
    candidate.metrics["t3_adjudicated"] = outcome.adjudicated
    reduction = metrics_obj.miss_reduction
    bw = metrics_obj.bw_delta_frac
    score = ranking_score(
        sim.metrics, family=candidate.family, domain=th.domain
    )
    if score is None and th.domain in ("cache", "generic") and reduction is not None:
        score = float(reduction)

    # Paper profile: dedicated_sim is adjudicating evidence, not audit-only.
    if cfg.funnel.llm_dedicated_sim and not gen.selftest_ok:
        gate_ok = False
        candidate.metrics["t3_dedicated_adjudication"] = "selftest_fail"
    elif (
        cfg.funnel.llm_dedicated_sim
        and gen.selftest_ok
        and gen.metrics
        and th.from_spec("min_miss_reduction")
    ):
        ded_red = float(gen.metrics.get("miss_reduction") or 0.0)
        if ded_red < th.min_miss_reduction:
            gate_ok = False
            candidate.metrics["t3_dedicated_adjudication"] = "acc_miss"
        else:
            candidate.metrics["t3_dedicated_adjudication"] = "ok"

    gap, gap_metric = domain_magic_gap(
        candidate.metrics, sim.metrics, th.domain
    )
    if gap is not None:
        candidate.metrics["t3_magic_gap"] = gap
        candidate.metrics["t3_magic_gap_metric"] = gap_metric
        if th.from_spec("max_magic_gap") and gap > th.max_magic_gap:
            gate_ok = False

    evidence = EvidenceLevel.STUB
    ev = str(sim.metrics.get("evidence") or "")
    if ev == "directed":
        evidence = EvidenceLevel.SIM
    elif ev == "analytic":
        evidence = EvidenceLevel.ANALYTIC
    elif ev == "sim" or (not sim.unavailable and backend_name not in {"stub", "directed"}):
        evidence = EvidenceLevel.SIM
    if ev == "stub":
        evidence = EvidenceLevel.STUB

    # Fail-closed: configured real backend unavailable → UNAVAILABLE, never PASS
    if sim.unavailable and cfg.funnel.strict_evidence and backend_name not in {
        "stub",
        "directed",
        "noc",
        "dataflow",
        "wafer",
    }:
        verdict = Verdict.UNAVAILABLE
        summary = (
            f"{sim.backend}: UNAVAILABLE (strict_evidence; configured "
            f"backend={cfg.sim.backend})"
        )
        result = TierResult(
            tier=Tier.T3,
            verdict=verdict,
            score=score,
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

    if backend_name == "stub" or evidence == EvidenceLevel.STUB:
        if backend_name not in {"stub", "directed", "noc", "dataflow", "wafer"} and cfg.funnel.strict_evidence:
            verdict = Verdict.UNAVAILABLE
            summary = f"{sim.backend}: stub evidence rejected under strict_evidence"
        else:
            verdict = Verdict.PASS if gate_ok else Verdict.FAIL
            gap_note = f" magic_gap={gap:.2f}({gap_metric})" if gap is not None else ""
            if th.domain not in ("cache", "generic") or reduction is None:
                hl = headlines_text(sim.metrics, family=candidate.family)
                extra = f" {hl}" if hl else f" domain={th.domain}"
                adj = " report-only" if not outcome.adjudicated else ""
                summary = f"{sim.backend}:{extra}{adj}{gap_note}"
            else:
                summary = (
                    f"{sim.backend}: stub evidence reduction={float(reduction):.2%} "
                    f"bwΔ={float(bw or 0):.2%}{gap_note}"
                )
            evidence = EvidenceLevel.STUB
    else:
        verdict = Verdict.PASS if gate_ok else Verdict.FAIL
        gap_note = f" magic_gap={gap:.2f}({gap_metric})" if gap is not None else ""
        if metrics_obj.p99_latency is not None:
            adj = "report-only" if not outcome.adjudicated else f"ok={gate_ok}"
            summary = (
                f"{sim.backend}: p99={metrics_obj.p99_latency:.0f}cyc "
                f"goodput={metrics_obj.goodput or 0:.2f} {adj}{gap_note}"
            )
        elif metrics_obj.pe_utilization is not None:
            adj = "report-only" if not outcome.adjudicated else f"ok={gate_ok}"
            summary = (
                f"{sim.backend}: pe_utilization={metrics_obj.pe_utilization:.2f} "
                f"{adj}{gap_note}"
            )
        elif metrics_obj.die_to_die_bw is not None:
            adj = "report-only" if not outcome.adjudicated else f"ok={gate_ok}"
            summary = (
                f"{sim.backend}: die_to_die_bw={metrics_obj.die_to_die_bw:.1f} "
                f"{adj}{gap_note}"
            )
        else:
            if reduction is None:
                hl = headlines_text(sim.metrics, family=candidate.family)
                summary = (
                    f"{sim.backend}: {hl or ('domain=' + th.domain)} "
                    f"ok={gate_ok}{gap_note}"
                )
            else:
                summary = (
                    f"{sim.backend}: reduction={float(reduction):.2%} "
                    f"bwΔ={float(bw or 0):.2%} "
                    f"ok={gate_ok}{gap_note}"
                )

    result = TierResult(
        tier=Tier.T3,
        verdict=verdict,
        score=score,
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
