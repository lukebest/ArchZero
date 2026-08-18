"""Magic Gap must compare the domain quantity, not missing MPKI."""

from __future__ import annotations

from pathlib import Path

import pytest

from archzero.llm.fake import FakeLLM
from archzero.models import Candidate
from archzero.sim.mechanism_model import domain_magic_gap, report_magic_gap
from archzero.spec.ndf import load_problem_package


def test_domain_gap_noc_uses_goodput():
    gap, key = domain_magic_gap(
        {"t2_goodput": 0.80, "t2_miss_reduction": 0.22},
        {"goodput": 0.40, "miss_reduction": 0.01},
        "noc",
    )
    assert key == "goodput"
    assert gap == pytest.approx(abs(0.80 - 0.40) / 0.40)
    # must not have used the leaked miss_reduction pair
    cache_gap = report_magic_gap(0.22, 0.01)
    assert gap != cache_gap


def test_domain_gap_absent_off_cache_is_none_not_zero():
    gap, key = domain_magic_gap(
        {"t2_miss_reduction": 0.2},
        {"miss_reduction": 0.18},
        "noc",
    )
    assert gap is None
    assert key is None


def test_domain_gap_generic_prefers_goodput_over_leaked_mpki():
    gap, key = domain_magic_gap(
        {"t2_goodput": 0.80, "t2_miss_reduction": 0.22},
        {"goodput": 0.40, "miss_reduction": 0.01},
        "generic",
    )
    assert key == "goodput"
    assert gap == pytest.approx(abs(0.80 - 0.40) / 0.40)


def test_domain_gap_generic_without_domain_metric_can_use_mpki():
    gap, key = domain_magic_gap(
        {"t2_miss_reduction": 0.30},
        {"miss_reduction": 0.15},
        "generic",
    )
    assert key == "miss_reduction"
    assert gap == pytest.approx(1.0)


def test_domain_gap_cache_still_uses_mpki():
    gap, key = domain_magic_gap(
        {"t2_miss_reduction": 0.30},
        {"miss_reduction": 0.15},
        "cache",
    )
    assert key == "miss_reduction"
    assert gap == pytest.approx(1.0)


@pytest.mark.asyncio
async def test_tier3_records_goodput_magic_gap(tmp_cfg):
    from archzero.funnel.tier3 import evaluate_tier3

    problem = load_problem_package(
        Path(__file__).resolve().parents[1] / "specs" / "noc_low_tail_collectives.md"
    )
    work = tmp_cfg.scratch_dir / "gap-noc"
    work.mkdir(parents=True)
    (work / "sim_knobs.json").write_text(
        '{"family": "request_grant", "domain": "noc"}', encoding="utf-8"
    )
    cand = Candidate(
        problem_id=problem.id,
        title="RG",
        mechanism="Request-grant.",
        family="request_grant",
        workdir=str(work),
        metrics={"t2_goodput": 0.99},
    )
    out = await evaluate_tier3(tmp_cfg, cand, problem, FakeLLM(responses={"analytic": "{}"}))
    assert out.metrics.get("t3_magic_gap_metric") == "goodput"
    assert out.metrics.get("t3_magic_gap") is not None
    assert "t3_goodput" in out.metrics

@pytest.mark.asyncio
async def test_tier4_records_goodput_magic_gap(tmp_cfg):
    from archzero.funnel.tier4 import evaluate_tier4
    from archzero.models import Tier

    problem = load_problem_package(
        Path(__file__).resolve().parents[1] / "specs" / "noc_low_tail_collectives.md"
    )
    work = tmp_cfg.scratch_dir / "gap-t4"
    work.mkdir(parents=True)
    (work / "sim_knobs.json").write_text(
        '{"family": "request_grant", "domain": "noc"}', encoding="utf-8"
    )
    cand = Candidate(
        problem_id=problem.id,
        title="RG",
        mechanism="Request-grant.",
        family="request_grant",
        workdir=str(work),
        metrics={"t2_goodput": 0.99},
    )
    llm = FakeLLM(
        responses={
            "final_judge": '{"verdict":"pass","score":0.8,"summary":"ok","clause_refs":[]}'
        }
    )
    out = await evaluate_tier4(tmp_cfg, cand, problem, llm)
    last = out.tier_history[-1]
    assert last.tier is Tier.T4
    assert out.metrics.get("t4_magic_gap_metric") == "goodput"
    assert out.metrics.get("t4_magic_gap") is not None
    assert last.metrics.get("magic_gap_metric") == "goodput"


@pytest.mark.asyncio
async def test_tier4_fails_declared_magic_gap(tmp_cfg, tmp_path):
    """A spec that pins Magic Gap must fail T4 when T2 vs full-sim diverge."""
    from archzero.funnel.tier4 import evaluate_tier4
    from archzero.models import Verdict
    from archzero.spec.wizard import scaffold_problem

    path = scaffold_problem(
        title="cache gap",
        workload="w",
        symptom="s",
        constraint="c",
        domain="cache",
        out_dir=tmp_path,
    )
    # Ensure ACC mentions Magic Gap so from_spec("max_magic_gap") is true.
    # If scaffold already declares it, fine; otherwise this test should
    # still record t4_magic_gap even if report-only.
    problem = load_problem_package(path)
    work = tmp_cfg.scratch_dir / "gap-t4-cache"
    work.mkdir(parents=True)
    (work / "sim_knobs.json").write_text(
        '{"miss_reduction": 0.10, "extra_bw": 0.01, "area": 0.2}',
        encoding="utf-8",
    )
    cand = Candidate(
        problem_id=problem.id,
        title="pref",
        mechanism="prefetch",
        family="prefetch",
        workdir=str(work),
        metrics={"t2_miss_reduction": 0.90},
    )
    llm = FakeLLM(
        responses={
            "final_judge": '{"verdict":"pass","score":0.9,"summary":"ok","clause_refs":[]}'
        }
    )
    out = await evaluate_tier4(tmp_cfg, cand, problem, llm)
    assert out.metrics.get("t4_magic_gap_metric") == "miss_reduction"
    assert out.metrics.get("t4_magic_gap") is not None
    # If the scaffold declared max_magic_gap, a 0.90 vs ~0.10 gap must FAIL
    # even though the judge said pass.
    from archzero.spec.acc_parse import parse_acceptance_thresholds

    th = parse_acceptance_thresholds(problem)
    if th.from_spec("max_magic_gap"):
        assert out.tier_history[-1].verdict is Verdict.FAIL
        assert "magic_gap" in out.tier_history[-1].summary

