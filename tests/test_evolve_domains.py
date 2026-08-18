"""MAP-Elites personas and scoring must follow the problem domain."""

from __future__ import annotations

import re

import pytest

from archzero.evolve.domains import mutate_persona_for, score_variant


def test_noc_persona_does_not_require_cache_knobs():
    persona = mutate_persona_for("noc")
    required = re.search(r"knobs:\s*\{([^}]*)\}", persona)
    assert required is not None
    assert "miss_reduction" not in required.group(1)
    assert "不要发明 miss_reduction" in persona


def test_score_variant_noc_has_latency_not_mpki():
    scored = score_variant("noc", "request_grant", {})
    assert "p99_latency" in scored
    assert "miss_reduction" not in scored


def test_score_variant_dataflow_has_pe_utilization():
    scored = score_variant("dataflow", "ws", {})
    assert "pe_utilization" in scored


def test_score_variant_wafer_has_d2d_not_yield():
    scored = score_variant("wafer", "mesh_xy", {})
    assert "die_to_die_bw" in scored
    assert "yield_redundancy" not in scored


def test_score_variant_cache_keeps_miss_reduction():
    scored = score_variant("cache", "prefetch", {"miss_reduction": 0.2})
    assert scored["miss_reduction"] == pytest.approx(0.2)


def test_score_variant_cache_without_knobs_does_not_invent_012():
    scored = score_variant("cache", "prefetch", {})
    assert "miss_reduction" not in scored
    assert "12%" in (scored.get("note") or "")
