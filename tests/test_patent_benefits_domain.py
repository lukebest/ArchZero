"""Patent benefit claims must not quote cache MPKI on a NoC problem."""

from __future__ import annotations

from pathlib import Path

from archzero.models import Candidate
from archzero.patent.disclosure import collect_benefits
from archzero.spec.ndf import load_problem_package


def test_collect_benefits_noc_keeps_p99_drops_miss_reduction():
    problem = load_problem_package(
        Path(__file__).resolve().parents[1] / "specs" / "noc_low_tail_collectives.md"
    )
    cand = Candidate(
        problem_id=problem.id,
        title="request-grant",
        mechanism="central request-grant arbiter",
        family="noc_rg",
        metrics={
            "t3_p99_latency": 1700.0,
            "t3_miss_reduction": 0.184,
            "t3_goodput": 0.42,
        },
    )
    benefits = collect_benefits(cand, problem)
    keys = {b.metric_key for b in benefits}
    assert "t3_p99_latency" in keys
    assert "t3_miss_reduction" not in keys
    p99 = next(b for b in benefits if b.metric_key == "t3_p99_latency")
    assert p99.display_value == "1700 cyc"
