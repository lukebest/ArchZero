"""dedicated_sim participates in Tier3 adjudication under paper profile."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from archzero.llm.fake import FakeLLM
from archzero.models import Candidate, Verdict
from archzero.sim.generate import GeneratedSim


@pytest.mark.asyncio
async def test_llm_dedicated_sim_selftest_fail_fails_tier3(
    tmp_cfg, demo_problem, monkeypatch
):
    from archzero.funnel import tier3 as t3

    tmp_cfg.funnel.llm_dedicated_sim = True
    tmp_cfg.sim.backend = "directed"
    tmp_cfg.funnel.strict_evidence = True

    async def _bad_llm(workdir, *_, **__):
        work = Path(workdir)
        path = work / "dedicated_sim.py"
        path.write_text("# broken\n", encoding="utf-8")
        return GeneratedSim(
            family="prefetch",
            path=path,
            selftest_ok=False,
            metrics={},
            log="selftest failed",
        )

    monkeypatch.setattr(t3, "generate_dedicated_sim_llm", _bad_llm)

    work = tmp_cfg.scratch_dir / "ded-fail"
    work.mkdir(parents=True)
    (work / "sim_knobs.json").write_text(
        json.dumps({"miss_reduction": 0.3, "extra_bw": 0.01, "area": 0.2}),
        encoding="utf-8",
    )
    c = Candidate(
        problem_id=demo_problem.id,
        title="Filtered prefetch",
        mechanism="256-entry dead-block filter",
        family="prefetch",
        workdir=str(work),
        metrics={"t2_miss_reduction": 0.25},
    )
    llm = FakeLLM(
        responses={
            "analytic": '{"miss_reduction":0.3,"extra_bw":0.01}',
        }
    )
    out = await t3.evaluate_tier3(tmp_cfg, c, demo_problem, llm)
    assert out.tier_history[-1].verdict == Verdict.FAIL
    assert out.metrics.get("t3_dedicated_adjudication") == "selftest_fail"
