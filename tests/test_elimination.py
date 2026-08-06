"""Failure-elimination causal metric tests."""

from __future__ import annotations

from archzero.metrics.elimination import compute_elimination, snapshot_failures
from archzero.models import (
    Campaign,
    Candidate,
    FailureKind,
    FailureRecord,
    Tier,
)
from archzero.store.db import Store


def _fail(store: Store, campaign_id: str, cand: Candidate, *, kind: FailureKind, msg: str):
    f = FailureRecord(
        candidate_id=cand.id,
        tier=Tier.T2,
        kind=kind,
        message=msg,
    )
    cand.failures.append(f)
    store.save_candidate(cand, campaign_id=campaign_id)
    store.save_failure(f)
    return f


def test_elimination_kind_removed(tmp_cfg, demo_problem):
    store = Store(tmp_cfg.db_path)
    src = Campaign(problem_id=demo_problem.id, name="src")
    dst = Campaign(problem_id=demo_problem.id, name="dst")
    store.save_problem(demo_problem)
    store.save_campaign(src)
    store.save_campaign(dst)

    c1 = Candidate(problem_id=demo_problem.id, title="a", mechanism="m")
    c2 = Candidate(problem_id=demo_problem.id, title="b", mechanism="m")
    _fail(store, src.id, c1, kind=FailureKind.PERFORMANCE, msg="mpki too low")
    _fail(store, src.id, c1, kind=FailureKind.PHYSICS, msg="bandwidth conservation")
    _fail(store, dst.id, c2, kind=FailureKind.PHYSICS, msg="bandwidth conservation")

    snap = snapshot_failures(store.list_failures(campaign_id=src.id))
    assert snap["n"] == 2
    elim = compute_elimination(
        store, source_campaign_id=src.id, followup_campaign_id=dst.id
    )
    assert "performance" in elim["kinds_eliminated"]
    assert "physics" in elim["kinds_persisted"]
    assert elim["kind_elimination_rate"] == 0.5
