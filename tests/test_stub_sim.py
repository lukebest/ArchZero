from pathlib import Path

from archzero.config import FactoryConfig
from archzero.sim.backend import SimRequest, get_backend


def test_stub_sim_deterministic(tmp_path):
    cfg = FactoryConfig(state_dir=tmp_path / "state")
    cfg.ensure_dirs()
    backend = get_backend(cfg)
    assert backend.name == "stub"
    work = tmp_path / "w"
    work.mkdir()
    (work / "sim_knobs.json").write_text(
        '{"miss_reduction": 0.2, "extra_bw": 0.01, "area": 0.2}', encoding="utf-8"
    )
    r1 = backend.run(
        SimRequest(candidate_id="c1", workdir=work, patch_hint="x", suite="small")
    )
    r2 = backend.run(
        SimRequest(candidate_id="c1", workdir=work, patch_hint="x", suite="small")
    )
    assert r1.ok
    assert r1.metrics["mpki"] == r2.metrics["mpki"]
