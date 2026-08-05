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
