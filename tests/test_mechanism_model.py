"""Off-cache families must not fall through to the prefetch event model."""

from __future__ import annotations

from archzero.sim.mechanism_model import MechanismParams, infer_family, simulate_mechanism


def test_mechanism_params_default_has_no_invented_reduction():
    assert MechanismParams(family="prefetch").base_reduction is None
    assert MechanismParams(family="prefetch").reduction_declared is False


def test_infer_family_request_grant_is_noc_not_prefetch():
    fam = infer_family("request-grant arbiter", "central grant table", domain="noc")
    assert fam == "request_grant"
    assert fam != "prefetch"


def test_infer_family_stream_prefetch_without_domain():
    assert infer_family("stream prefetch", "L2 streamer degree 2") == "prefetch"


def test_infer_params_without_knobs_does_not_declare_reduction():
    from archzero.sim.mechanism_model import infer_params

    params = infer_params(title="prefetch table", mechanism="stride prefetch", knobs={})
    assert params.reduction_declared is False
    assert params.base_reduction is None
    metrics = simulate_mechanism(params, candidate_id="no-knobs")
    assert metrics.miss_reduction is None
    assert "18% cut" in (metrics.note or "")
    assert metrics.mpki == metrics.baseline_mpki


def test_infer_params_with_knobs_declares_reduction():
    from archzero.sim.mechanism_model import infer_params

    params = infer_params(
        title="prefetch table",
        mechanism="stride prefetch",
        knobs={"miss_reduction": 0.2, "family": "prefetch"},
    )
    assert params.reduction_declared is True
    metrics = simulate_mechanism(params, candidate_id="with-knobs")
    assert metrics.miss_reduction is not None
    assert 0.0 < float(metrics.miss_reduction) <= 0.9


def test_simulate_noc_rg_has_p99_not_miss_reduction():
    metrics = simulate_mechanism(MechanismParams(family="noc_rg"), candidate_id="noc-rg")
    dumped = metrics.as_dict()
    assert metrics.p99_latency is not None
    assert "miss_reduction" not in dumped
    assert metrics.miss_reduction is None
