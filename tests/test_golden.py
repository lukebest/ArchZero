"""Golden candidate expectations (offline stubs)."""

from __future__ import annotations

import json
from pathlib import Path

from archzero.sim.metrics import SimMetrics


def test_golden_suite_file_present():
    path = Path(__file__).parent / "golden" / "candidates.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    assert len(data) >= 2
    ids = {row["id"] for row in data}
    assert "gold-prefetch-filter" in ids


def test_sim_metrics_gate():
    ok = SimMetrics(
        evidence="stub",
        miss_reduction=0.15,
        bw_delta_frac=0.02,
    )
    assert ok.gate_ok()
    bad = SimMetrics(evidence="stub", miss_reduction=0.05, bw_delta_frac=0.02)
    assert not bad.gate_ok()
