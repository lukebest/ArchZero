"""Tier2 must speak the problem's domain, not invent an MPKI contract."""

from __future__ import annotations

from pathlib import Path

import pytest

from archzero.funnel.tier2 import (
    CODE_PERSONA_CACHE,
    CODE_PERSONA_DATAFLOW,
    CODE_PERSONA_NOC,
    _sanitize_domain_metrics,
    _threshold_gate,
    code_persona_for,
)
from archzero.llm.fake import FakeLLM
from archzero.models import Candidate, Tier, Verdict
from archzero.spec.acc_parse import parse_acceptance_thresholds
from archzero.spec.ndf import load_problem_package
from archzero.spec.wizard import scaffold_problem


def test_code_persona_is_domain_shaped():
    cache = code_persona_for("cache")
    noc = code_persona_for("noc")
    dataflow = code_persona_for("dataflow")
    wafer = code_persona_for("wafer")
    assert "predicted_mpki" in cache
    assert "noc_model" in noc
    assert "dataflow_model" in dataflow
    assert "wafer_model" in wafer
    assert "keys predicted_mpki" in cache
    assert "keys predicted_mpki" not in noc
    assert "keys predicted_mpki" not in dataflow
    assert "do NOT invent predicted_mpki" in CODE_PERSONA_NOC
    assert "do NOT invent predicted_mpki" in CODE_PERSONA_DATAFLOW
    assert "predicted_mpki" in CODE_PERSONA_CACHE


def test_sanitize_strips_leaked_cache_keys_on_noc():
    th = parse_acceptance_thresholds(load_problem_package(
        Path(__file__).resolve().parents[1] / "specs" / "noc_low_tail_collectives.md"
    ))
    raw = {
        "predicted_mpki": 6.5,
        "miss_reduction": 0.2,
        "ipc_speedup": 1.08,
        "meets_target": True,
        "p99_latency": 1700.0,
        "goodput": 0.4,
    }
    cleaned = _sanitize_domain_metrics(raw, th, strict=True)
    assert "miss_reduction" not in cleaned
    assert cleaned["meets_target"] is None
    assert cleaned["p99_latency"] == 1700.0
    kept = _sanitize_domain_metrics(raw, th, strict=False)
    assert kept["miss_reduction"] == 0.2


@pytest.mark.asyncio
async def test_tier2_noc_helper_model_is_report_only(tmp_cfg):
    from archzero.funnel.tier2 import evaluate_tier2

    tmp_cfg.funnel.strict_acc = True
    tmp_cfg.funnel.use_verifiers = False
    problem = load_problem_package(
        Path(__file__).resolve().parents[1] / "specs" / "noc_low_tail_collectives.md"
    )
    llm = FakeLLM(
        responses={
            "spec_gen": "# Spec\nAssumptions: α-β.\n",
            "analytic": (
                "```python\n"
                "from archzero.analytic.domains import noc_model\n"
                "def run_model():\n"
                "    return noc_model('request_grant')\n"
                "```"
            ),
        }
    )
    cand = Candidate(
        problem_id=problem.id,
        title="RG arbiter",
        family="noc_rg",
        mechanism="Request-grant admission at the source.",
    )
    out = await evaluate_tier2(tmp_cfg, cand, problem, llm)
    last = out.tier_history[-1]
    assert last.tier is Tier.T2
    assert last.verdict is Verdict.PASS
    model = last.metrics["model"]
    assert "p99_latency" in model
    assert "miss_reduction" not in model
    assert model.get("meets_target") is None
    assert last.score == pytest.approx(float(model["goodput"]), rel=1e-3)
    assert last.score < 2.0  # not a p99 cycle count


@pytest.mark.asyncio
async def test_tier2_rejects_cache_model_on_noc_when_strict(tmp_cfg, fake_llm):
    from archzero.funnel.tier2 import evaluate_tier2

    tmp_cfg.funnel.strict_acc = True
    tmp_cfg.funnel.use_verifiers = False
    problem = load_problem_package(
        Path(__file__).resolve().parents[1] / "specs" / "noc_low_tail_collectives.md"
    )
    cand = Candidate(
        problem_id=problem.id,
        title="RG arbiter",
        family="noc_rg",
        mechanism="Grant slots.",
    )
    out = await evaluate_tier2(tmp_cfg, cand, problem, fake_llm)
    last = out.tier_history[-1]
    assert last.verdict is Verdict.FAIL
    assert "no noc metrics" in last.summary


@pytest.mark.asyncio
async def test_tier2_dataflow_helper_model(tmp_cfg, tmp_path: Path):
    from archzero.funnel.tier2 import evaluate_tier2

    tmp_cfg.funnel.strict_acc = True
    tmp_cfg.funnel.use_verifiers = False
    path = scaffold_problem(
        title="df t2",
        workload="w",
        symptom="s",
        constraint="c",
        domain="dataflow",
        out_dir=tmp_path,
    )
    problem = load_problem_package(path)
    llm = FakeLLM(
        responses={
            "spec_gen": "# Spec\nAssumptions: iso-resource 16x16.\n",
            "analytic": (
                "```python\n"
                "from archzero.analytic.domains import dataflow_model\n"
                "def run_model():\n"
                "    return dataflow_model('weight_stationary')\n"
                "```"
            ),
        }
    )
    cand = Candidate(
        problem_id=problem.id,
        title="WS mapper",
        family="ws",
        mechanism="Weight-stationary GEMM mapping.",
    )
    out = await evaluate_tier2(tmp_cfg, cand, problem, llm)
    last = out.tier_history[-1]
    assert last.verdict is Verdict.PASS
    assert "pe_utilization" in last.metrics["model"]
    assert "miss_reduction" not in last.metrics["model"]


def test_threshold_gate_still_report_only_for_noc():
    th = parse_acceptance_thresholds(
        load_problem_package(
            Path(__file__).resolve().parents[1] / "specs" / "noc_low_tail_collectives.md"
        )
    )
    ok, note = _threshold_gate({"p99_latency": 1000, "goodput": 0.3}, th)
    assert ok
    assert "report-only" in note

def test_headline_score_noc_uses_goodput_not_p99():
    from archzero.funnel.tier2 import _headline_score
    from archzero.spec.acc_parse import parse_acceptance_thresholds
    from archzero.spec.ndf import load_problem_package

    th = parse_acceptance_thresholds(
        load_problem_package(
            Path(__file__).resolve().parents[1] / "specs" / "noc_low_tail_collectives.md"
        )
    )
    worse_tail = {"p99_latency": 9000.0, "goodput": 0.35, "completion_latency": 4000.0}
    better_tail = {"p99_latency": 1200.0, "goodput": 0.80, "completion_latency": 800.0}
    assert _headline_score(worse_tail, th) == pytest.approx(0.35)
    assert _headline_score(better_tail, th) == pytest.approx(0.80)
    assert _headline_score(better_tail, th) > _headline_score(worse_tail, th)
