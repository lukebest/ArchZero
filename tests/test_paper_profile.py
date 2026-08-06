"""Paper profile + directed/ensemble markers."""

from __future__ import annotations

from pathlib import Path

import pytest

from archzero.config import load_config
from archzero.corpus.status import corpus_status


@pytest.mark.paper
def test_paper_toml_profile():
    path = Path(__file__).resolve().parents[1] / "archzero.paper.toml"
    cfg = load_config(path)
    assert cfg.funnel.ensemble_n == 3
    assert cfg.funnel.use_verifiers is True
    assert cfg.sim.backend == "directed"


@pytest.mark.paper
def test_corpus_scaffold_status():
    st = corpus_status()
    assert st["ok"]
    assert st["status"] == "scaffold"
    assert st["entries"] >= 3
    assert st["success_rate"] is None
    assert st.get("with_pdf", 0) >= 3
    assert "reproduce" in (st.get("label_schema") or [])


@pytest.mark.paper
def test_paper_toml_llm_dedicated_sim():
    path = Path(__file__).resolve().parents[1] / "archzero.paper.toml"
    cfg = load_config(path)
    assert cfg.funnel.llm_dedicated_sim is True


@pytest.mark.directed
@pytest.mark.asyncio
async def test_directed_backend_smoke(tmp_cfg, demo_problem, fake_llm):
    import json

    from archzero.funnel.tier3 import evaluate_tier3
    from archzero.models import Candidate, Verdict

    tmp_cfg.sim.backend = "directed"
    work = tmp_cfg.scratch_dir / "dirsmoke"
    work.mkdir(parents=True)
    (work / "sim_knobs.json").write_text(
        json.dumps(
            {"miss_reduction": 0.30, "extra_bw": 0.02, "area": 0.25, "family": "prefetch"}
        )
    )
    c = Candidate(
        problem_id=demo_problem.id,
        title="Filtered prefetch",
        mechanism="256-entry filtered prefetch degree 2",
        family="prefetch",
        workdir=str(work),
        metrics={"t2_miss_reduction": 0.22},
    )
    out = await evaluate_tier3(tmp_cfg, c, demo_problem, fake_llm)
    assert out.tier_history[-1].verdict in {Verdict.PASS, Verdict.FAIL}
    assert out.tier_history[-1].metrics.get("evidence") == "directed"


@pytest.mark.ensemble
@pytest.mark.asyncio
async def test_ensemble_marker_smoke(tmp_cfg, demo_problem, fake_llm):
    from archzero.funnel.tier2 import evaluate_tier2
    from archzero.models import Candidate, Verdict

    tmp_cfg.funnel.ensemble_n = 3
    c = Candidate(
        problem_id=demo_problem.id,
        title="ens",
        mechanism="Filtered prefetch.",
        workdir=str(tmp_cfg.scratch_dir / "ens2"),
    )
    Path(c.workdir).mkdir(parents=True)
    out = await evaluate_tier2(tmp_cfg, c, demo_problem, fake_llm)
    assert out.tier_history[-1].verdict == Verdict.PASS
    assert out.tier_history[-1].metrics["ensemble"]["n"] == 3
