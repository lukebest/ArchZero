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
