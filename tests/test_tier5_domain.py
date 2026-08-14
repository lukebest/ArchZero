"""Tier5 must not grade a NoC study against the coupled_l2 cache baseline."""

from __future__ import annotations

from pathlib import Path

import pytest

from archzero.models import Candidate, Verdict
from archzero.spec.ndf import load_problem_package


@pytest.mark.asyncio
async def test_tier5_unavailable_for_noc_domain(tmp_cfg, fake_llm):
    from archzero.funnel.tier5 import evaluate_tier5

    problem = load_problem_package(
        Path(__file__).resolve().parents[1] / "specs" / "noc_low_tail_collectives.md"
    )
    c = Candidate(
        problem_id=problem.id,
        title="request-grant",
        mechanism="central request-grant arbiter",
        family="noc_rg",
        workdir=str(tmp_cfg.scratch_dir / "t5-noc"),
    )
    Path(c.workdir).mkdir(parents=True)
    out = await evaluate_tier5(tmp_cfg, c, problem, fake_llm)
    tr = out.tier_history[-1]
    assert tr.verdict == Verdict.UNAVAILABLE
    assert "coupled_l2" in tr.summary or "domain=noc" in tr.summary
    assert out.status == "active"
    assert not (Path(c.workdir) / "design.py").exists()
