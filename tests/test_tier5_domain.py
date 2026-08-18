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


@pytest.mark.asyncio
async def test_tier5_unavailable_for_generic_spec_with_noc_family(tmp_cfg, fake_llm, tmp_path):
    from archzero.funnel.tier5 import evaluate_tier5

    spec = tmp_path / "generic.md"
    spec.write_text(
        "---\n"
        "id: pp-generic-noc\n"
        "title: unnamed interconnect study\n"
        "---\n\n"
        "# Unnamed interconnect study\n\n"
        "### REQ-001 — Mechanism\n\n"
        "Improve collective completion without stating a numeric gate.\n\n"
        "### ACC-001 — Report\n\n"
        "Report the measured behaviour. Do not invent a cache miss metric.\n",
        encoding="utf-8",
    )
    problem = load_problem_package(spec)
    from archzero.spec.acc_parse import parse_acceptance_thresholds

    assert parse_acceptance_thresholds(problem).domain == "generic"
    c = Candidate(
        problem_id=problem.id,
        title="request-grant",
        mechanism="central request-grant arbiter",
        family="noc_rg",
        workdir=str(tmp_cfg.scratch_dir / "t5-generic-noc"),
    )
    Path(c.workdir).mkdir(parents=True)
    out = await evaluate_tier5(tmp_cfg, c, problem, fake_llm)
    tr = out.tier_history[-1]
    assert tr.verdict == Verdict.UNAVAILABLE
    assert "coupled_l2" in tr.summary
    assert not (Path(c.workdir) / "design.py").exists()
