"""Tier gate tests with FakeLLM (offline)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from archzero.llm.fake import FakeLLM
from archzero.models import Candidate, EvidenceLevel, Tier, Verdict
from archzero.sim.parse_champsim import parse_champsim_stdout
from archzero.sim.parse_gem5 import parse_stats_text


@pytest.mark.asyncio
async def test_tier0_pass(tmp_cfg, demo_problem, fake_llm):
    from archzero.funnel.tier0 import evaluate_tier0

    c = Candidate(
        problem_id=demo_problem.id,
        title="t0",
        mechanism="Filtered prefetch within area budget.",
        workdir=str(tmp_cfg.scratch_dir / "t0"),
    )
    Path(c.workdir).mkdir(parents=True)
    out = await evaluate_tier0(tmp_cfg, c, demo_problem, fake_llm)
    assert out.tier_history[-1].verdict == Verdict.PASS
    assert out.tier_history[-1].model_id == "fake-model"
    assert out.tier_history[-1].evidence == EvidenceLevel.ANALYTIC


@pytest.mark.asyncio
async def test_tier2_disagreement_fails(tmp_cfg, demo_problem):
    from archzero.funnel.tier2 import evaluate_tier2

    llm = FakeLLM(
        responses={
            "spec_gen": "# Spec\n",
            "analytic": (
                "```python\ndef run_model():\n"
                "    return {'predicted_mpki':6.0,'miss_reduction':0.2,"
                "'ipc_speedup':1.1,'meets_target':True}\n```"
            ),
        },
        sequence=[
            '{"verdict":"fail","score":0.2,"summary":"insight says no","clause_refs":[]}'
        ],
    )
    c = Candidate(
        problem_id=demo_problem.id,
        title="t2",
        mechanism="mech",
        workdir=str(tmp_cfg.scratch_dir / "t2"),
    )
    Path(c.workdir).mkdir(parents=True)
    out = await evaluate_tier2(tmp_cfg, c, demo_problem, llm)
    assert out.tier_history[-1].verdict == Verdict.FAIL
    assert out.tier_history[-1].metrics.get("disagreement") is True


@pytest.mark.asyncio
async def test_tier3_strict_unavailable(tmp_cfg, demo_problem, fake_llm):
    from archzero.funnel.tier3 import evaluate_tier3

    tmp_cfg.sim.backend = "champsim"
    tmp_cfg.sim.champsim_bin = "/nonexistent/champsim"
    tmp_cfg.funnel.strict_evidence = True
    c = Candidate(
        problem_id=demo_problem.id,
        title="t3",
        mechanism="mech",
        workdir=str(tmp_cfg.scratch_dir / "t3"),
        metrics={"t2_miss_reduction": 0.2},
    )
    Path(c.workdir).mkdir(parents=True)
    out = await evaluate_tier3(tmp_cfg, c, demo_problem, fake_llm)
    assert out.tier_history[-1].verdict == Verdict.UNAVAILABLE
    assert out.status != "failed"


@pytest.mark.asyncio
async def test_tier3_stub_pass(tmp_cfg, demo_problem, fake_llm):
    from archzero.funnel.tier3 import evaluate_tier3

    tmp_cfg.sim.backend = "stub"
    c = Candidate(
        problem_id=demo_problem.id,
        title="t3s",
        mechanism="mech",
        workdir=str(tmp_cfg.scratch_dir / "t3s"),
    )
    Path(c.workdir).mkdir(parents=True)
    (Path(c.workdir) / "sim_knobs.json").write_text(
        json.dumps({"miss_reduction": 0.2, "extra_bw": 0.01, "area": 0.2})
    )
    out = await evaluate_tier3(tmp_cfg, c, demo_problem, fake_llm)
    assert out.tier_history[-1].verdict == Verdict.PASS
    assert out.tier_history[-1].evidence == EvidenceLevel.STUB


@pytest.mark.asyncio
async def test_tier5_unavailable_without_pycircuit(tmp_cfg, demo_problem, fake_llm):
    from archzero.funnel.tier5 import evaluate_tier5

    tmp_cfg.rtl.pycircuit_root = str(tmp_cfg.state_dir / "missing_pyc")
    c = Candidate(
        problem_id=demo_problem.id,
        title="t5",
        mechanism="mech",
        workdir=str(tmp_cfg.scratch_dir / "t5"),
    )
    Path(c.workdir).mkdir(parents=True)
    out = await evaluate_tier5(tmp_cfg, c, demo_problem, fake_llm)
    assert out.tier_history[-1].verdict == Verdict.UNAVAILABLE
    assert out.tier_history[-1].evidence == EvidenceLevel.RTL


@pytest.mark.asyncio
async def test_tier6_reserved(tmp_cfg, demo_problem, fake_llm):
    from archzero.funnel.tier6 import evaluate_tier6

    c = Candidate(
        problem_id=demo_problem.id,
        title="t6",
        mechanism="mech",
        workdir=str(tmp_cfg.scratch_dir / "t6"),
    )
    Path(c.workdir).mkdir(parents=True)
    out = await evaluate_tier6(tmp_cfg, c, demo_problem, fake_llm)
    tr = out.tier_history[-1]
    assert tr.tier == Tier.T6
    assert tr.verdict == Verdict.UNAVAILABLE
    assert tr.evidence == EvidenceLevel.SIGNOFF
    assert "reserved" in tr.summary.lower()


def test_parse_champsim_mpki_ipc():
    sample = """
    CPU 0 cumulative IPC: 1.234 instructions: 5000000 cycles: 4050000
    LLC TOTAL     ACCESS: 100000  HIT: 80000  MISS: 20000  MPKI: 4.000
    AVG DRAM BW 12.5 GB/s
    """
    m = parse_champsim_stdout(sample)
    assert m["mpki"] == pytest.approx(4.0)
    assert m["ipc"] == pytest.approx(1.234)


def test_parse_gem5_stats():
    sample = """
    simInsts                                1000000
    system.cpu.ipc                          1.5
    system.l2.overallMisses::total          5000
    system.cpu.numCycles                    666666
    """
    m = parse_stats_text(sample)
    assert m["ipc"] == pytest.approx(1.5)
    assert m["mpki"] == pytest.approx(5.0)
