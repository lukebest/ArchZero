"""Golden candidate expectations (offline stubs / directed)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from archzero.llm.fake import FakeLLM
from archzero.models import Candidate, Verdict
from archzero.sim.metrics import SimMetrics
from archzero.spec.acc_parse import parse_acceptance_thresholds

GOLDEN_PATH = Path(__file__).parent / "golden" / "candidates.json"


def load_golden_cases() -> list[dict]:
    return json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))


def test_golden_suite_size():
    data = load_golden_cases()
    assert len(data) >= 10
    ids = {row["id"] for row in data}
    assert "gold-prefetch-filter" in ids
    assert "gold-champsim-unavailable" in ids
    assert "gold-directed-prefetch" in ids


def test_sim_metrics_gate_uses_acc_defaults():
    ok = SimMetrics(
        evidence="stub",
        miss_reduction=0.15,
        bw_delta_frac=0.02,
    )
    assert ok.gate_ok()
    bad = SimMetrics(evidence="stub", miss_reduction=0.10, bw_delta_frac=0.02)
    assert not bad.gate_ok()  # default min_reduction is 0.15


def test_acc_parse_demo(demo_problem):
    th = parse_acceptance_thresholds(demo_problem)
    assert th.min_miss_reduction == pytest.approx(0.15)
    assert th.max_bw_delta_frac == pytest.approx(0.05)
    assert th.max_magic_gap == pytest.approx(2.0)
    assert th.area_budget_mm2 == pytest.approx(0.5)


@pytest.mark.asyncio
@pytest.mark.parametrize("case", load_golden_cases(), ids=lambda c: c["id"])
async def test_golden_tier_gate(case, tmp_cfg, demo_problem, fake_llm):
    from archzero.funnel.tier0 import evaluate_tier0
    from archzero.funnel.tier3 import evaluate_tier3

    expect = case["expect"]
    work = tmp_cfg.scratch_dir / case["id"]
    work.mkdir(parents=True)
    c = Candidate(
        problem_id=demo_problem.id,
        title=case["title"],
        mechanism=case.get("mechanism") or case["title"],
        family=case.get("family") or "unclassified",
        workdir=str(work),
        metrics=dict(case.get("metrics") or {}),
    )

    if expect.get("tier0") == "fail":
        llm = FakeLLM(
            responses={
                "bulk_screen": (
                    '{"verdict":"fail","score":0.1,"summary":"physics violate",'
                    '"physics_flags":["energy"],"clause_refs":["REQ-001"]}'
                )
            }
        )
        out = await evaluate_tier0(tmp_cfg, c, demo_problem, llm)
        assert out.tier_history[-1].verdict == Verdict.FAIL
        return

    if "tier3" not in expect:
        pytest.skip("no tier3 expectation")

    backend = expect.get("backend") or "stub"
    tmp_cfg.sim.backend = backend
    if backend == "champsim":
        tmp_cfg.sim.champsim_bin = "/nonexistent/champsim"
        tmp_cfg.funnel.strict_evidence = True

    fixture = case.get("fixture") or {}
    if fixture:
        (work / "sim_knobs.json").write_text(json.dumps(fixture), encoding="utf-8")

    out = await evaluate_tier3(tmp_cfg, c, demo_problem, fake_llm)
    got = out.tier_history[-1].verdict.value
    assert got == expect["tier3"], f"{case['id']}: expected {expect['tier3']} got {got}"

    if expect.get("evidence") == "directed":
        assert out.tier_history[-1].metrics.get("evidence") == "directed"
    if expect.get("magic_gap_gt") is not None:
        gap = out.metrics.get("t3_magic_gap") or out.tier_history[-1].metrics.get(
            "magic_gap"
        )
        assert gap is not None and float(gap) > float(expect["magic_gap_gt"])
