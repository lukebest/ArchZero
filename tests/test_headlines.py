"""Domain headlines for dashboard / weekly report (not MPKI on off-cache)."""

from __future__ import annotations

import pytest

from archzero.models import Campaign, Candidate, Tier, TierResult, Verdict
from archzero.report.weekly import build_report
from archzero.sim.headlines import (
    candidate_headlines,
    headlines_text,
    metrics_domain,
    ranking_score,
)
from archzero.store.db import Store
from archzero.web.app import _serialize_candidate


def test_noc_headlines_skip_leaked_mpki():
    metrics = {
        "t3_p99_latency": 1746.0,
        "t3_goodput": 0.81,
        "t3_miss_reduction": 0.22,
    }
    headlines = candidate_headlines(metrics, family="request_grant")
    labels = [h["label"] for h in headlines]
    keys = [h["key"] for h in headlines]
    assert "p99" in labels
    assert "goodput" in labels
    assert "MPKI↓" not in labels
    assert "miss_reduction" not in keys
    assert metrics_domain(metrics, "request_grant") == "noc"
    text = headlines_text(metrics, family="request_grant")
    assert "p99=" in text
    assert "goodput=" in text
    assert "MPKI" not in text


def test_serialize_includes_headlines():
    c = Candidate(
        problem_id="p",
        title="RG",
        mechanism="request grant",
        family="request_grant",
        metrics={
            "t3_p99_latency": 1746,
            "t3_goodput": 0.81,
            "t3_miss_reduction": 0.2,
        },
    )
    blob = _serialize_candidate(c)
    assert blob["title_plain"] is None
    assert blob["has_plain"] is False
    assert blob["metrics_domain"] == "noc"
    labels = [h["label"] for h in blob["headlines"]]
    assert "p99" in labels
    assert "goodput" in labels
    assert "MPKI↓" not in labels


def test_weekly_survivor_shows_domain_headlines(tmp_cfg, demo_problem):
    store = Store(tmp_cfg.db_path)
    store.save_problem(demo_problem)
    camp = Campaign(problem_id=demo_problem.id, name="noc")
    store.save_campaign(camp)
    c = Candidate(
        problem_id=demo_problem.id,
        title="RG",
        mechanism="m",
        family="request_grant",
        status="active",
        metrics={"t3_p99_latency": 1746.0, "t3_goodput": 0.81},
    )
    c.tier_history.append(
        TierResult(tier=Tier.T3, verdict=Verdict.PASS, score=0.81, summary="ok")
    )
    store.save_candidate(c, campaign_id=camp.id)
    text = build_report(tmp_cfg, campaign_id=camp.id)
    assert "p99=" in text
    assert "goodput=" in text
    assert "tier_score=" in text
    assert " score=" not in text


def test_ranking_score_noc_uses_goodput_not_leaked_mpki():
    metrics = {
        "t3_p99_latency": 1746.0,
        "t3_goodput": 0.81,
        "t3_miss_reduction": 0.22,
    }
    assert ranking_score(metrics, family="request_grant") == pytest.approx(0.81)
    assert ranking_score({"t3_miss_reduction": 0.22}, family="request_grant") is None
    assert ranking_score({"t3_miss_reduction": 0.18}, family="prefetch") == pytest.approx(0.18)

def test_ranking_score_generic_infers_goodput():
    from archzero.sim.headlines import ranking_score
    assert ranking_score({"goodput": 0.55, "miss_reduction": 0.02}, domain="generic") == 0.55
    assert ranking_score({}, domain="generic") is None
