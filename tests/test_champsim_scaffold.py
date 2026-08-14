"""ChampSim config / patch scaffold."""

from __future__ import annotations

import json

from archzero.sim.champsim_config import write_champsim_scaffold


def test_write_champsim_scaffold(tmp_path):
    out = write_champsim_scaffold(
        tmp_path,
        family="prefetch",
        knobs={"miss_reduction": 0.2, "extra_bw": 0.01, "table_entries": 512},
        title="Filter prefetch",
    )
    assert out["ok"]
    cfg = json.loads((tmp_path / "champsim_config.json").read_text())
    assert cfg["archzero_scaffold"] is True
    assert cfg["mechanism"]["family"] == "prefetch"
    assert cfg["ooo_cpu"][0]["L2C"]["prefetcher"] == "archzero_filter"
    assert (tmp_path / "MECHANISM_PATCH.md").is_file()
    assert (tmp_path / "champsim_patch.json").is_file()


def test_write_champsim_scaffold_noc_inapplicable(tmp_path):
    out = write_champsim_scaffold(
        tmp_path,
        family="noc_rg",
        knobs={"family": "noc_rg", "domain": "noc"},
        title="Request-grant arbiter",
    )
    assert out["inapplicable"] is True
    assert out["module"] is None
    cfg = json.loads((tmp_path / "champsim_config.json").read_text())
    assert cfg.get("inapplicable") is True
    assert cfg["mechanism"]["module"] is None
    assert cfg["ooo_cpu"] == []
    blob = json.dumps(cfg)
    assert "archzero_filter" not in blob
    md = (tmp_path / "MECHANISM_PATCH.md").read_text()
    assert "cannot host" in md.lower() or "inapplicable" in md.lower()

