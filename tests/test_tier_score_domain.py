"""Tier3/4 and keep-N must not treat a missing MPKI as score=0 on NoC."""

from __future__ import annotations

import json
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


def test_tier3_score_generic_does_not_use_leaked_mpki():
    from archzero.funnel.tier3 import _tier3_score

    leaked = {"miss_reduction": 0.22, "goodput": 0.80}
    assert _tier3_score(leaked, family="request_grant", domain="generic") == pytest.approx(
        0.80
    )
    mpki_only = {"miss_reduction": 0.22}
    assert _tier3_score(mpki_only, family="request_grant", domain="generic") is None
    assert _tier3_score(mpki_only, family="prefetch", domain="generic") == pytest.approx(
        0.22
    )
    assert _tier3_score(mpki_only, family="prefetch", domain="cache") == pytest.approx(
        0.22
    )


def test_tier3_fallback_knobs_do_not_invent_018():
    from archzero.funnel.tier3 import _fallback_knobs

    empty = Candidate(
        problem_id="p", title="t", mechanism="m", family="prefetch", metrics={}
    )
    knobs = _fallback_knobs(empty, "cache")
    assert "miss_reduction" not in knobs
    assert "extra_bw" not in knobs
    assert knobs["family"] == "prefetch"
    copied = Candidate(
        problem_id="p",
        title="t",
        mechanism="m",
        family="prefetch",
        metrics={"t2_miss_reduction": 0.22},
    )
    assert _fallback_knobs(copied, "cache")["miss_reduction"] == pytest.approx(0.22)


@pytest.mark.asyncio
async def test_tier3_cache_without_t2_does_not_write_invented_knobs(tmp_cfg, demo_problem):
    from archzero.funnel.tier3 import evaluate_tier3

    class Boom(FakeLLM):
        async def work(self, *args, **kwargs):
            raise RuntimeError("no harness")

    tmp_cfg.sim.backend = "stub"
    work = tmp_cfg.scratch_dir / "t3-empty"
    work.mkdir(parents=True)
    cand = Candidate(
        problem_id=demo_problem.id,
        title="empty t2",
        mechanism="prefetch without measured T2",
        family="prefetch",
        workdir=str(work),
        metrics={},
    )
    out = await evaluate_tier3(tmp_cfg, cand, demo_problem, Boom())
    written = json.loads((work / "sim_knobs.json").read_text(encoding="utf-8"))
    assert "miss_reduction" not in written
    assert out.metrics.get("t3_miss_reduction") is None


def test_soft_fallback_backends_include_domain_sims():
    from archzero.funnel.tier4 import _SOFT_FALLBACK_BACKENDS

    assert {"noc", "dataflow", "wafer"} <= _SOFT_FALLBACK_BACKENDS
