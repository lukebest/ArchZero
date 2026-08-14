"""Offline demo campaign so researchers can explore funnel UI without LLM calls."""

from __future__ import annotations

from pathlib import Path

from archzero.config import FactoryConfig
from archzero.models import (
    Campaign,
    Candidate,
    FailureKind,
    FailureRecord,
    Tier,
    TierResult,
    Verdict,
)
from archzero.spec.acc_parse import parse_acceptance_thresholds
from archzero.spec.ndf import load_problem_package
from archzero.store.db import Store

DEMO_MECHANISMS = [
    (
        "Dead-block filter + selective prefetch",
        "prefetch",
        "A small PC-indexed dead-block predictor gates L2 prefetch issuance. "
        "Only predicted live lines receive prefetch fills; dead lines are filtered. "
        "Expected: ≥15% MPKI cut at ≤5% bandwidth growth.",
        True,
        True,
        True,
    ),
    (
        "Signature-based miss coalescer",
        "coalesce",
        "Coalesce temporally adjacent L2 misses sharing a region signature before "
        "hitting the memory controller. Reduces request traffic under decode bursts.",
        True,
        True,
        False,
    ),
    (
        "Thermodynamic free-energy cache",
        "physics-violating",
        "Claims to store 2× bits without area by recycling thermal noise as free energy. "
        "Violates conservation; should fail Tier0.",
        False,
        False,
        False,
    ),
    (
        "History-length adaptive streamer",
        "streamer",
        "Adaptive stream length based on decode token-phase detection. "
        "Uses a 2KB table; area proxy ~0.25mm².",
        True,
        False,
        False,
    ),
    (
        "Bypass-aware writeback throttle",
        "writeback",
        "Throttle dirty writebacks when HBM queue depth exceeds a watermark, "
        "preferring demand fills for decode critical path.",
        True,
        True,
        True,
    ),
]


def seed_demo_campaign(cfg: FactoryConfig, *, force: bool = False) -> dict:
    """Create a synthetic campaign with mixed pass/fail tier history."""
    cfg.ensure_dirs()
    store = Store(cfg.db_path)

    # Avoid duplicate demo campaigns unless forced
    existing = [
        c
        for c in store.list_campaigns()
        if c.meta.get("demo") is True or c.name.startswith("Demo funnel")
    ]
    if existing and not force:
        return {
            "campaign_id": existing[0].id,
            "created": False,
            "n_candidates": len(store.list_candidates(campaign_id=existing[0].id)),
            "note": "demo campaign already exists; pass force=True to add another",
        }

    demo_spec = Path(__file__).resolve().parents[1] / "specs" / "demo.md"
    pp = load_problem_package(demo_spec)
    store.save_problem(pp)

    camp = Campaign(
        name="Demo funnel (offline seed)",
        problem_id=pp.id,
        through_tier=Tier.T3,
        status="done",
        meta={"demo": True, "offline": True},
    )
    store.save_campaign(camp)

    for title, family, mechanism, pass_t0, pass_t1, pass_t2 in DEMO_MECHANISMS:
        cand = Candidate(
            problem_id=pp.id,
            title=title,
            mechanism=mechanism,
            family=family,
            clause_refs=["REQ-001", "ACC-001", "DOF-001"],
            status="active" if pass_t2 else "failed",
            metrics={
                "t2_miss_reduction": 0.18 if pass_t2 else 0.08,
                "demo": True,
            },
        )
        work = cfg.scratch_dir / "demo" / cand.id
        work.mkdir(parents=True, exist_ok=True)
        cand.workdir = str(work)

        def add(tier: Tier, ok: bool, score: float, summary: str) -> None:
            cand.tier_history.append(
                TierResult(
                    tier=tier,
                    verdict=Verdict.PASS if ok else Verdict.FAIL,
                    score=score,
                    summary=summary,
                    clause_refs=cand.clause_refs,
                )
            )
            if not ok:
                kind = (
                    FailureKind.PHYSICS
                    if tier == Tier.T0
                    else FailureKind.PERFORMANCE
                    if tier == Tier.T2
                    else FailureKind.FEASIBILITY
                )
                f = FailureRecord(
                    candidate_id=cand.id,
                    tier=tier,
                    kind=kind,
                    message=summary,
                    clause_refs=cand.clause_refs,
                )
                cand.failures.append(f)
                store.save_failure(f)

        add(Tier.T0, pass_t0, 0.9 if pass_t0 else 0.1, "Tier0 hard screen")
        if pass_t0:
            add(Tier.T1, pass_t1, 0.75 if pass_t1 else 0.2, "Tier1 adversarial review")
        if pass_t0 and pass_t1:
            add(Tier.T2, pass_t2, 0.8 if pass_t2 else 0.25, "Tier2 analytic model")
        if pass_t0 and pass_t1 and pass_t2:
            add(Tier.T3, True, 0.7, "Tier3 stub sim pass")

        store.save_candidate(cand, campaign_id=camp.id)

    return {
        "campaign_id": camp.id,
        "created": True,
        "n_candidates": len(DEMO_MECHANISMS),
        "problem_id": pp.id,
    }


NOC_MECHANISMS = [
    (
        "Hierarchical request-grant with idle-slot injection",
        "noc_rg",
        "A per-quadrant arbiter aggregates collective requests and issues grants on a "
        "coarse slot boundary; dynamic point-to-point traffic fills unclaimed slots. "
        "Targets p99 collective completion latency without idling links.",
    ),
    (
        "Push-on-pull credit windows for collectives",
        "noc_pop",
        "Receivers advertise pull windows sized by their reduction progress; senders push "
        "only into advertised windows. No global scheduler, so jitter degrades throughput "
        "gracefully instead of breaking a static schedule.",
    ),
    (
        "Compiled slot table with jitter-absorbing gaps",
        "noc_presched",
        "Offline conflict-free slot/path tables per collective phase, padded with gaps sized "
        "to the measured arrival spread; point-to-point traffic is inserted into gaps.",
    ),
]


def seed_noc_report_campaign(cfg: FactoryConfig, *, force: bool = False) -> dict:
    """Seed a NoC campaign the analytic backend can measure but not adjudicate.

    The spec asks for p99 / goodput vs baseline and never pins a numeric gate,
    so Tier2/Tier3 report numbers and stay report-only — they do not invent
    ``>=15% MPKI``.
    """
    from archzero.funnel.pipeline import acc_gate_for_campaign
    from archzero.sim.backend import SimRequest
    from archzero.sim.noc import NocAnalyticBackend

    cfg.ensure_dirs()
    store = Store(cfg.db_path)

    existing = [c for c in store.list_campaigns() if c.meta.get("demo_noc_report")]
    if existing and not force:
        return {
            "campaign_id": existing[0].id,
            "created": False,
            "n_candidates": len(store.list_candidates(campaign_id=existing[0].id)),
            "note": "NoC report demo already exists; pass force=True to add another",
        }

    spec = Path(__file__).resolve().parents[1] / "specs" / "noc_low_tail_collectives.md"
    if not spec.is_file():  # pragma: no cover
        return {"campaign_id": None, "created": False, "note": f"missing {spec}"}
    pp = load_problem_package(spec)
    store.save_problem(pp)

    through, acc_meta = acc_gate_for_campaign(cfg, pp, Tier.T4)
    th = parse_acceptance_thresholds(pp)
    backend = NocAnalyticBackend(cfg)

    camp = Campaign(
        name="NoC tail latency (offline seed · report-only)",
        problem_id=pp.id,
        through_tier=through,
        status="done",
        meta={"demo": True, "offline": True, "demo_noc_report": True, "acc": acc_meta},
    )
    store.save_campaign(camp)

    for title, family, mechanism in NOC_MECHANISMS:
        cand = Candidate(
            problem_id=pp.id,
            title=title,
            mechanism=mechanism,
            family=family,
            clause_refs=["REQ-001", "ACC-001", "ACC-003"],
            status="active",
            metrics={"demo": True},
        )
        work = cfg.scratch_dir / "demo-noc" / cand.id
        work.mkdir(parents=True, exist_ok=True)
        cand.workdir = str(work)
        sim = backend.run(
            SimRequest(
                candidate_id=cand.id,
                workdir=work,
                patch_hint=mechanism,
                suite="small",
                meta={"title": title, "mechanism": mechanism, "family": family},
            )
        )
        cand.metrics.update({f"t3_{k}": v for k, v in sim.metrics.items()})
        p99 = sim.metrics.get("p99_latency")
        goodput = sim.metrics.get("goodput")
        cand.tier_history.append(
            TierResult(
                tier=Tier.T0,
                verdict=Verdict.PASS,
                score=0.85,
                summary="Tier0 hard screen: no conservation or bisection-bandwidth violation",
                clause_refs=cand.clause_refs,
            )
        )
        cand.tier_history.append(
            TierResult(
                tier=Tier.T1,
                verdict=Verdict.PASS,
                score=0.7,
                summary="Tier1 adversarial review: iso-wire comparison protocol respected",
                clause_refs=cand.clause_refs,
            )
        )
        cand.tier_history.append(
            TierResult(
                tier=Tier.T2,
                verdict=Verdict.PASS,
                score=float(goodput or 0.0),
                summary=(
                    f"Tier2 report-only：可测 {', '.join(th.measurable_performance)}，"
                    f"规范未给出数值门限，不裁决 PASS/FAIL"
                ),
                metrics={"thresholds": th.as_dict(), "acc_gradable": True, "report_only": True},
                clause_refs=cand.clause_refs,
            )
        )
        cand.tier_history.append(
            TierResult(
                tier=Tier.T3,
                verdict=Verdict.PASS,
                score=float(goodput or 0.0),
                summary=(
                    f"noc analytic: p99={float(p99 or 0):.0f}cyc "
                    f"goodput={float(goodput or 0):.2f} report-only"
                ),
                metrics={**sim.metrics, "adjudicated": False},
                clause_refs=cand.clause_refs,
            )
        )
        store.save_candidate(cand, campaign_id=camp.id)

    return {
        "campaign_id": camp.id,
        "created": True,
        "n_candidates": len(NOC_MECHANISMS),
        "problem_id": pp.id,
        "through": through.value,
    }


def seed_acc_refusal_campaign(cfg: FactoryConfig, *, force: bool = False) -> dict:
    """Seed a wafer-scale campaign the funnel still refuses to grade past Tier1.

    NoC is now measurable. The honesty demo moved to a domain that still has
    no evaluator, so a new user can see both: numbers for interconnect, and
    an explicit refusal for wafer-scale fabric metrics.
    """
    from archzero.funnel.pipeline import acc_gate_for_campaign
    from archzero.spec.wizard import scaffold_problem

    cfg.ensure_dirs()
    store = Store(cfg.db_path)

    existing = [c for c in store.list_campaigns() if c.meta.get("demo_acc_refusal")]
    if existing and not force:
        return {
            "campaign_id": existing[0].id,
            "created": False,
            "n_candidates": len(store.list_candidates(campaign_id=existing[0].id)),
            "note": "refusal demo already exists; pass force=True to add another",
        }

    spec_dir = cfg.state_dir / "demo_specs"
    path = scaffold_problem(
        title="WSE fabric partition latency",
        workload="tensor-parallel LLM on SRAM-resident wafer",
        symptom="collectives stall on die-boundary hops",
        constraint="no off-wafer DRAM; power-density cap",
        domain="wafer",
        out_dir=spec_dir,
    )
    pp = load_problem_package(path)
    store.save_problem(pp)

    through, acc_meta = acc_gate_for_campaign(cfg, pp, Tier.T4)
    th = parse_acceptance_thresholds(pp)

    camp = Campaign(
        name="WSE fabric (offline seed · ACC 拒判)",
        problem_id=pp.id,
        through_tier=through,
        status="done",
        meta={"demo": True, "offline": True, "demo_acc_refusal": True, "acc": acc_meta},
    )
    store.save_campaign(camp)

    cand = Candidate(
        problem_id=pp.id,
        title="Spare-die bypass with compiled collective schedule",
        mechanism=(
            "Route around defective dies using precomputed slot tables; "
            "recompute on isolation. Targets hop latency under a redundancy budget."
        ),
        family="wse_fabric",
        clause_refs=["REQ-001", "ACC-001"],
        status="active",
        metrics={"demo": True},
    )
    cand.tier_history.append(
        TierResult(
            tier=Tier.T0,
            verdict=Verdict.PASS,
            score=0.8,
            summary="Tier0: no conservation violation in the stated redundancy budget",
            clause_refs=cand.clause_refs,
        )
    )
    cand.tier_history.append(
        TierResult(
            tier=Tier.T1,
            verdict=Verdict.PASS,
            score=0.65,
            summary="Tier1: defect model is stated; thermal coupling remains a threat",
            clause_refs=cand.clause_refs,
        )
    )
    cand.tier_history.append(
        TierResult(
            tier=Tier.T2,
            verdict=Verdict.UNAVAILABLE,
            score=0.0,
            summary=f"Tier2 拒判（strict_acc）：{th.ungradable_reason()}",
            metrics={"thresholds": th.as_dict(), "acc_gradable": False},
            clause_refs=cand.clause_refs,
        )
    )
    store.save_candidate(cand, campaign_id=camp.id)

    return {
        "campaign_id": camp.id,
        "created": True,
        "n_candidates": 1,
        "problem_id": pp.id,
        "through": through.value,
    }
