"""Generated dedicated simulator + weekly elimination section."""

from __future__ import annotations

from pathlib import Path

from archzero.models import Campaign, FailureKind, FailureRecord, Tier, Candidate
from archzero.metrics.elimination import compute_elimination
from archzero.report.weekly import build_report
from archzero.sim.generate import generate_dedicated_sim
from archzero.store.db import Store


def test_generate_prefetch_selftest(tmp_path):
    g = generate_dedicated_sim(
        tmp_path,
        title="Filtered prefetch",
        mechanism="256-entry dead-block filter degree 2",
        knobs={"miss_reduction": 0.3, "extra_bw": 0.02},
        family="prefetch",
    )
    assert g.selftest_ok
    assert g.path.exists()
    assert "miss_reduction" in g.metrics
    assert (tmp_path / "DEDICATED_SIM.md").exists()


def test_generate_replacement_and_bypass(tmp_path):
    r = generate_dedicated_sim(
        tmp_path / "r",
        title="RRPV",
        mechanism="history length 12 512 entries",
        family="replacement",
        knobs={"miss_reduction": 0.28},
    )
    b = generate_dedicated_sim(
        tmp_path / "b",
        title="Bypass throttle",
        mechanism="bypass threshold 0.6",
        family="bypass",
        knobs={"miss_reduction": 0.2, "bypass_threshold": 0.6},
    )
    assert r.selftest_ok and b.selftest_ok


def test_weekly_includes_elimination(tmp_cfg, demo_problem):
    store = Store(tmp_cfg.db_path)
    store.save_problem(demo_problem)
    src = Campaign(problem_id=demo_problem.id, name="src")
    dst = Campaign(problem_id=demo_problem.id, name="dst")
    store.save_campaign(src)
    c1 = Candidate(problem_id=demo_problem.id, title="a", mechanism="m")
    c2 = Candidate(problem_id=demo_problem.id, title="b", mechanism="m")
    f1 = FailureRecord(
        candidate_id=c1.id, tier=Tier.T2, kind=FailureKind.PERFORMANCE, message="mpki"
    )
    f2 = FailureRecord(
        candidate_id=c2.id, tier=Tier.T2, kind=FailureKind.PHYSICS, message="bw"
    )
    c1.failures.append(f1)
    store.save_candidate(c1, campaign_id=src.id)
    store.save_failure(f1)
    store.save_candidate(c2, campaign_id=dst.id)
    store.save_failure(f2)
    elim = compute_elimination(
        store, source_campaign_id=src.id, followup_campaign_id=dst.id
    )
    dst.meta["elimination"] = elim
    dst.meta["parent_campaign_id"] = src.id
    store.save_campaign(dst)

    text = build_report(tmp_cfg, campaign_id=dst.id)
    assert "Failure elimination" in text
    assert "performance" in text or "kinds eliminated" in text
