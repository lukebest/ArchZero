"""gem5 harness template."""

from __future__ import annotations

from archzero.sim.gem5_harness import write_gem5_harness


def test_write_gem5_harness(tmp_path):
    out = write_gem5_harness(
        tmp_path, knobs={"miss_reduction": 0.18, "extra_bw": 0.02}
    )
    assert out["ok"]
    script = tmp_path / "run_gem5.py"
    assert script.is_file()
    assert "sim_knobs" in script.read_text()
    assert (tmp_path / "GEM5_HARNESS.md").is_file()



def test_gem5_harness_inapplicable_for_noc(tmp_path):
    out = write_gem5_harness(
        tmp_path,
        family="noc_rg",
        knobs={"family": "noc_rg", "domain": "noc"},
    )
    assert out["inapplicable"] is True
    script = (tmp_path / "run_gem5.py").read_text(encoding="utf-8")
    assert "overall_miss_rate" not in script
    assert "miss_reduction" not in script
    md = (tmp_path / "GEM5_HARNESS.md").read_text(encoding="utf-8")
    assert "cpu/cache" in md.lower() or "analytic" in md.lower()
