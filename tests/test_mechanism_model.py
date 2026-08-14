"""Off-cache families must not fall through to the prefetch event model."""

from __future__ import annotations

from archzero.sim.mechanism_model import MechanismParams, infer_family, simulate_mechanism


def test_infer_family_request_grant_is_noc_not_prefetch():
    fam = infer_family("request-grant arbiter", "central grant table", domain="noc")
    assert fam == "request_grant"
    assert fam != "prefetch"


def test_infer_family_stream_prefetch_without_domain():
    assert infer_family("stream prefetch", "L2 streamer degree 2") == "prefetch"


def test_simulate_noc_rg_has_p99_not_miss_reduction():
    metrics = simulate_mechanism(MechanismParams(family="noc_rg"), candidate_id="noc-rg")
    dumped = metrics.as_dict()
    assert metrics.p99_latency is not None
    assert "miss_reduction" not in dumped
    assert metrics.miss_reduction is None
