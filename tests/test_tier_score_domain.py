"""Tier3/4 and keep-N must not treat a missing MPKI as score=0 on NoC."""

from __future__ import annotations

from pathlib import Path

import pytest

from archzero.funnel.pipeline import candidate_keep_score
from archzero.llm.fake import FakeLLM
from archzero.models import Candidate, Tier, TierResult, Verdict
from archzero.spec.ndf import load_problem_package

ROOT = Path(__file__).resolve().parents[1]
NOC_SPEC = ROOT / "specs" / "noc_low_tail_collectives.md"


@pytest.mark.asyncio
async def test_tier3_noc_score_is_goodput_not_zero_mpki(tmp_cfg):
    from archzero.funnel.tier3 import evaluate_tier3

    tmp_cfg.sim.backend = "stub"
    tmp_cfg.funnel.strict_evidence = True
    problem = load_problem_package(NOC_SPEC)
    work = tmp_cfg.scratch_dir / "t3-noc"
    work.mkdir(parents=True)
    (work / "sim_knobs.json").write_text(
        '{"family": "request_grant", "domain": "noc"}', encoding="utf-8"
    )
    cand = Candidate(
        problem_id=problem.id,
        title="RG",
        mechanism="Request-grant admission.",
        family="request_grant",
        workdir=str(work),
    )
    llm = FakeLLM(responses={"analytic": "{}"})
    out = await evaluate_tier3(tmp_cfg, cand, problem, llm)
    last = out.tier_history[-1]
    assert last.tier is Tier.T3
    assert last.score is not None
    assert last.score != 0.0
    assert last.score == pytest.approx(float(out.metrics.get("t3_goodput")), rel=1e-3)
    assert "reduction=0.00%" not in last.summary
    assert "miss_reduction" not in (last.summary or "")
    assert "goodput" in last.summary or "p99" in last.summary


@pytest.mark.asyncio
async def test_tier4_noc_score_not_invented_mpki(tmp_cfg):
    from archzero.funnel.tier4 import evaluate_tier4

    tmp_cfg.sim.backend = "stub"
    problem = load_problem_package(NOC_SPEC)
    work = tmp_cfg.scratch_dir / "t4-noc"
    work.mkdir(parents=True)
    (work / "sim_knobs.json").write_text(
        '{"family": "request_grant", "domain": "noc"}', encoding="utf-8"
    )
    cand = Candidate(
        problem_id=problem.id,
        title="RG",
        mechanism="Request-grant admission.",
        family="request_grant",
        workdir=str(work),
    )
    llm = FakeLLM(
        responses={
            "final_judge": '{"verdict":"pass","score":0.8,"summary":"ok","clause_refs":[]}'
        }
    )
    out = await evaluate_tier4(tmp_cfg, cand, problem, llm)
    last = out.tier_history[-1]
    assert last.tier is Tier.T4
    assert last.score == pytest.approx(0.8)
    assert last.score != 0.0


def test_keep_score_ranks_noc_by_goodput_not_zero():
    low = Candidate(
        problem_id="p",
        title="low",
        mechanism="low goodput",
        family="request_grant",
        metrics={"t3_goodput": 0.40, "t3_p99_latency": 2000},
    )
    high = Candidate(
        problem_id="p",
        title="high",
        mechanism="high goodput",
        family="request_grant",
        metrics={"t3_goodput": 0.81, "t3_p99_latency": 1200},
    )
    # leftover dishonest score=0 must not beat a real goodput
    low.tier_history.append(
        TierResult(tier=Tier.T3, verdict=Verdict.PASS, score=0.0, summary="mpki?")
    )
    high.tier_history.append(
        TierResult(tier=Tier.T3, verdict=Verdict.PASS, score=0.0, summary="ok")
    )
    assert candidate_keep_score(high, Tier.T3) > candidate_keep_score(low, Tier.T3)
    assert candidate_keep_score(high, Tier.T3) == pytest.approx(0.81)
    leaked = Candidate(
        problem_id="p",
        title="leaked",
        mechanism="leaked mpki",
        family="request_grant",
        metrics={"t3_miss_reduction": 0.22},
    )
    assert candidate_keep_score(leaked, Tier.T3) == 0.0


def test_keep_score_after_t2_does_not_prefer_worse_p99():
    from archzero.funnel.pipeline import candidate_keep_score
    from archzero.models import Candidate, Tier, TierResult, Verdict

    worse = Candidate(
        problem_id="p",
        title="worse p99",
        mechanism="m",
        family="request_grant",
        metrics={"t2_p99_latency": 9000.0, "t2_goodput": 0.35},
    )
    better = Candidate(
        problem_id="p",
        title="better goodput",
        mechanism="m",
        family="request_grant",
        metrics={"t2_p99_latency": 1200.0, "t2_goodput": 0.80},
    )
    # Simulate the old bug: T2 score was the p99 cycle count
    worse.tier_history.append(
        TierResult(tier=Tier.T2, verdict=Verdict.PASS, score=9000.0, summary="p99")
    )
    better.tier_history.append(
        TierResult(tier=Tier.T2, verdict=Verdict.PASS, score=1200.0, summary="p99")
    )
    assert candidate_keep_score(better, Tier.T2) > candidate_keep_score(worse, Tier.T2)
    assert candidate_keep_score(better, Tier.T2) == pytest.approx(0.80)
    assert candidate_keep_score(worse, Tier.T2) == pytest.approx(0.35)


def test_soft_fallback_backends_include_domain_sims():
    from archzero.funnel.tier4 import _SOFT_FALLBACK_BACKENDS

    assert {"noc", "dataflow", "wafer"} <= _SOFT_FALLBACK_BACKENDS
