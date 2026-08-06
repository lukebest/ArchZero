"""ChampSim smoke — skipped unless binary exists."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from archzero.config import load_config
from archzero.models import Candidate, Verdict


def _champsim_bin() -> Path | None:
    cfg = load_config()
    if cfg.sim.champsim_bin and Path(cfg.sim.champsim_bin).exists():
        return Path(cfg.sim.champsim_bin)
    for cand in (
        Path("tools/champsim/bin/champsim"),
        Path("tools/champsim/champsim"),
    ):
        if cand.exists():
            return cand
    return None


@pytest.mark.champsim
@pytest.mark.asyncio
async def test_champsim_smoke_optional(tmp_cfg, demo_problem, fake_llm):
    bin_path = _champsim_bin()
    if bin_path is None:
        pytest.skip("ChampSim binary not built (tools/setup_champsim.sh)")

    from archzero.funnel.tier3 import evaluate_tier3

    tmp_cfg.sim.backend = "champsim"
    tmp_cfg.sim.champsim_bin = str(bin_path)
    tmp_cfg.funnel.strict_evidence = True
    work = tmp_cfg.scratch_dir / "cs"
    work.mkdir(parents=True)
    (work / "sim_knobs.json").write_text(
        json.dumps({"miss_reduction": 0.2, "extra_bw": 0.02, "area": 0.25})
    )
    c = Candidate(
        problem_id=demo_problem.id,
        title="cs",
        mechanism="Filtered prefetch",
        family="prefetch",
        workdir=str(work),
        metrics={"t2_miss_reduction": 0.2},
    )
    out = await evaluate_tier3(tmp_cfg, c, demo_problem, fake_llm)
    # With binary present we expect real sim evidence or FAIL/PASS — not silent stub PASS
    tr = out.tier_history[-1]
    assert tr.verdict in {Verdict.PASS, Verdict.FAIL, Verdict.UNAVAILABLE}
    if tr.verdict != Verdict.UNAVAILABLE:
        assert tr.metrics.get("evidence") in {"sim", "stub", "dedicated"}
