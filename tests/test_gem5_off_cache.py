"""gem5 must not invent MPKI when the request is off-cache."""

from __future__ import annotations

from archzero.sim.backend import SimRequest
from archzero.sim.gem5 import Gem5Backend


def test_gem5_off_cache_inapplicable_without_binary(tmp_cfg, tmp_path):
    work = tmp_path / "w"
    work.mkdir()
    result = Gem5Backend(tmp_cfg).run(
        SimRequest(
            candidate_id="c-noc",
            workdir=work,
            patch_hint="request-grant",
            suite="small",
            meta={"domain": "noc", "family": "noc_rg"},
        )
    )
    assert result.ok
    assert result.unavailable
    assert result.metrics.get("inapplicable") is True
    assert result.metrics.get("domain") == "noc"
    assert "miss_reduction" not in result.metrics
    assert "mpki" not in result.metrics
    assert "ipc" not in result.metrics


def test_gem5_cache_without_knobs_does_not_invent_mpki(tmp_cfg, tmp_path):
    """Parsed IPC-only stats must not pick up a hardcoded 0.12 MPKI cut."""
    fake = tmp_path / "gem5"
    fake.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    fake.chmod(0o755)
    tmp_cfg.sim.gem5_bin = str(fake)
    work = tmp_path / "w"
    work.mkdir()
    (work / "stats.txt").write_text(
        "system.cpu.ipc 1.5\nsimInsts 1000\n", encoding="utf-8"
    )
    (work / "baseline_stats.txt").write_text(
        "system.cpu.ipc 1.4\nsimInsts 1000\n", encoding="utf-8"
    )
    result = Gem5Backend(tmp_cfg).run(
        SimRequest(
            candidate_id="c-cache",
            workdir=work,
            patch_hint="prefetch",
            suite="small",
            meta={"domain": "cache", "family": "prefetch"},
        )
    )
    assert result.metrics.get("miss_reduction") is None
    assert result.metrics.get("mpki") is None
