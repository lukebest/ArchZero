"""Tier gate tests with FakeLLM (offline)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from archzero.llm.fake import FakeLLM
from archzero.models import Candidate, EvidenceLevel, TaskClass, Tier, Verdict
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


def _batch_candidates(problem, n: int) -> list[Candidate]:
    return [
        Candidate(
            problem_id=problem.id,
            title=f"t0-batch-{i}",
            mechanism=f"Mechanism variant {i}.",
        )
        for i in range(n)
    ]


@pytest.mark.asyncio
async def test_tier0_batch_screens_all_in_one_call(tmp_cfg, demo_problem):
    from archzero.funnel.tier0 import evaluate_tier0_batch

    llm = FakeLLM(
        responses={
            "bulk_screen": json.dumps(
                {
                    "results": [
                        {"index": 1, "verdict": "pass", "score": 0.9, "summary": "ok"},
                        {"index": 2, "verdict": "fail", "score": 0.1, "summary": "违反带宽上限"},
                        {"index": 3, "verdict": "pass", "score": 0.7, "summary": "ok"},
                    ]
                },
                ensure_ascii=False,
            )
        }
    )
    out = await evaluate_tier0_batch(
        tmp_cfg, _batch_candidates(demo_problem, 3), demo_problem, llm
    )

    assert len([c for c in llm.calls if c["op"] == "complete"]) == 1
    verdicts = [c.tier_history[-1].verdict for c in out]
    assert verdicts == [Verdict.PASS, Verdict.FAIL, Verdict.PASS]
    assert out[0].tier_history[-1].evidence == EvidenceLevel.ANALYTIC


@pytest.mark.asyncio
async def test_tier0_batch_fails_closed_on_missing_rows(tmp_cfg, demo_problem):
    """An unscreened candidate must not slip through as a pass."""
    from archzero.funnel.tier0 import evaluate_tier0_batch

    llm = FakeLLM(
        responses={
            "bulk_screen": json.dumps(
                {"results": [{"index": 1, "verdict": "pass", "score": 0.9}]}
            )
        }
    )
    out = await evaluate_tier0_batch(
        tmp_cfg, _batch_candidates(demo_problem, 3), demo_problem, llm
    )

    assert [c.tier_history[-1].verdict for c in out] == [
        Verdict.PASS,
        Verdict.FAIL,
        Verdict.FAIL,
    ]
    assert "未返回" in out[2].tier_history[-1].summary


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


@pytest.mark.asyncio
@pytest.mark.ensemble
async def test_tier2_ensemble_majority(tmp_cfg, demo_problem, fake_llm):
    from archzero.funnel.tier2 import evaluate_tier2

    tmp_cfg.funnel.ensemble_n = 3
    tmp_cfg.funnel.use_verifiers = True
    c = Candidate(
        problem_id=demo_problem.id,
        title="ens",
        mechanism="Filtered prefetch.",
        workdir=str(tmp_cfg.scratch_dir / "ens"),
    )
    Path(c.workdir).mkdir(parents=True)
    out = await evaluate_tier2(tmp_cfg, c, demo_problem, fake_llm)
    tr = out.tier_history[-1]
    assert tr.verdict == Verdict.PASS
    assert tr.metrics["ensemble"]["n"] == 3
    assert tr.metrics["ensemble"]["passes"] == 3
    assert len(tr.metrics.get("verifiers") or []) == 2


@pytest.mark.asyncio
async def test_tier2_verifier_fail_blocks(tmp_cfg, demo_problem):
    from archzero.funnel.tier2 import evaluate_tier2

    tmp_cfg.funnel.ensemble_n = 1
    tmp_cfg.funnel.use_verifiers = True
    llm = FakeLLM(
        responses={
            "spec_gen": "# Spec\nAssumptions ok\n",
            "comprehend": "**Status:** FAIL\nCritique:\n- Missing equations\n",
            "analytic": (
                "```python\ndef run_model():\n"
                "    return {'predicted_mpki':6.0,'miss_reduction':0.2,"
                "'ipc_speedup':1.1,'meets_target':True}\n```"
            ),
        }
    )
    c = Candidate(
        problem_id=demo_problem.id,
        title="vf",
        mechanism="mech",
        workdir=str(tmp_cfg.scratch_dir / "vf"),
    )
    Path(c.workdir).mkdir(parents=True)
    out = await evaluate_tier2(tmp_cfg, c, demo_problem, llm)
    assert out.tier_history[-1].verdict == Verdict.FAIL
    assert "verifier" in out.tier_history[-1].summary.lower()


@pytest.mark.asyncio
async def test_fake_llm_cache_knobs_do_not_invent_018(tmp_path):
    llm = FakeLLM()
    await llm.work(
        "You prepare a simulation harness for an architecture mechanism.",
        "Create sim_knobs.json for the stub adapter.",
        TaskClass.ANALYTIC,
        cwd=tmp_path,
    )
    knobs = json.loads((tmp_path / "sim_knobs.json").read_text(encoding="utf-8"))
    assert "miss_reduction" not in knobs
    assert knobs.get("domain") == "cache"
