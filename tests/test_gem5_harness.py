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
    text = script.read_text()
    assert "sim_knobs" in text
    assert '{"miss_reduction": 0.12' not in text
    assert (tmp_path / "GEM5_HARNESS.md").is_file()


def test_gem5_harness_without_knobs_does_not_invent_reduction(tmp_path):
    import runpy

    write_gem5_harness(tmp_path, knobs={}, family="prefetch", overwrite=True)
    script = (tmp_path / "run_gem5.py").read_text(encoding="utf-8")
    assert "0.12" not in script
    runpy.run_path(str(tmp_path / "run_gem5.py"))
    stats = (tmp_path / "stats.txt").read_text(encoding="utf-8")
    base = (tmp_path / "baseline_stats.txt").read_text(encoding="utf-8")
    assert "no_invented_miss_reduction" in stats
    assert "miss_reduction=" not in stats
    # iso-baseline: candidate L2 miss rate matches the baseline file
    miss_line = [
        ln for ln in stats.splitlines() if "overall_miss_rate" in ln
    ][0]
    base_miss = [
        ln for ln in base.splitlines() if "overall_miss_rate" in ln
    ][0]
    assert miss_line.split()[-1] == base_miss.split()[-1]



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
