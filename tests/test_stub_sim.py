
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



def test_stub_does_not_invent_mpki_for_noc_domain(tmp_path):
    cfg = FactoryConfig(state_dir=tmp_path / "state")
    cfg.ensure_dirs()
    backend = get_backend(cfg)
    work = tmp_path / "w"
    work.mkdir()
    r = backend.run(
        SimRequest(
            candidate_id="c-noc",
            workdir=work,
            patch_hint="request-grant",
            suite="small",
            meta={"domain": "noc", "family": "request_grant"},
        )
    )
    assert r.ok
    assert r.metrics.get("domain") == "noc"
    assert "miss_reduction" not in r.metrics
    assert "mpki" not in r.metrics
    assert "ipc" not in r.metrics
    assert r.metrics.get("evidence") == "stub"


def test_stub_cache_without_knobs_does_not_invent_reduction(tmp_path):
    cfg = FactoryConfig(state_dir=tmp_path / "state")
    cfg.ensure_dirs()
    backend = get_backend(cfg)
    work = tmp_path / "w"
    work.mkdir()
    r = backend.run(
        SimRequest(
            candidate_id="c-empty",
            workdir=work,
            patch_hint="prefetch",
            suite="small",
            meta={"domain": "cache", "family": "prefetch"},
        )
    )
    assert r.metrics.get("miss_reduction") is None
    assert "12% cut" in (r.metrics.get("note") or "")
    assert r.metrics.get("mpki") == r.metrics.get("baseline_mpki")
