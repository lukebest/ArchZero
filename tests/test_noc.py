"""Analytic NoC backend: iso-wire physics and report-only gating."""

from __future__ import annotations

from archzero.config import ROOT
from archzero.sim.backend import SimRequest
from archzero.sim.metrics import MetricGate, SimMetrics
from archzero.sim.noc import (
    FAMILIES,
    MESH,
    TORUS,
    evaluate_config,
    infer_noc_family,
    run_matrix,
)
from archzero.spec.acc_parse import parse_acceptance_thresholds
from archzero.spec.ndf import load_problem_package


def test_iso_bisection_holds_on_8x6():
    assert MESH.bisection_bpc == TORUS.bisection_bpc
    assert MESH.link_bpc == 2 * TORUS.link_bpc
    assert TORUS.avg_hops < MESH.avg_hops
    assert TORUS.diameter < MESH.diameter


def test_torus_does_not_win_from_extra_links_alone():
    """Iso-wire: torus has more links but half the per-link bandwidth."""
    ps = FAMILIES["packet_switched"]
    mesh = evaluate_config(
        topo=MESH, pattern="alltoall", family=ps, bufferless=False, message_b=4096
    )
    torus = evaluate_config(
        topo=TORUS, pattern="alltoall", family=ps, bufferless=False, message_b=4096
    )
    # Bisection-bound alltoall should be in the same ballpark; torus must not
    # look 2× faster just because it wraps.
    assert torus["bisection_bpc"] == mesh["bisection_bpc"]
    ratio = mesh["completion_latency"] / torus["completion_latency"]
    assert 0.5 < ratio < 2.0


def test_request_grant_adds_setup_on_sync_collectives():
    rg = FAMILIES["request_grant"]
    ps = FAMILIES["packet_switched"]
    rg_ar = evaluate_config(
        topo=MESH, pattern="allreduce", family=rg, bufferless=False, message_b=4096
    )
    # p99/mean is the tail tax — RG should be tighter than packet switching.
    rg_tail = rg_ar["p99_latency"] / rg_ar["completion_latency"]
    ps_ar = evaluate_config(
        topo=MESH, pattern="allreduce", family=ps, bufferless=False, message_b=4096
    )
    ps_tail = ps_ar["p99_latency"] / ps_ar["completion_latency"]
    assert rg_tail < ps_tail


def test_presched_has_the_tightest_tail():
    report = {
        fid: run_matrix(family_id=fid, suite="small")["aggregate"]
        for fid in FAMILIES
    }
    tails = {
        fid: agg["p99_latency"] / agg["completion_latency"]
        for fid, agg in report.items()
    }
    assert tails["presched"] == min(tails.values())


def test_family_inference():
    assert infer_noc_family("RG arbiter", "issues grants", "noc_rg") == "request_grant"
    assert infer_noc_family("Compiled slot table", "排图", "") == "presched"
    assert infer_noc_family("Pull windows", "push-on-pull", "noc_pop") == "push_on_pull"
    assert infer_noc_family("Vanilla mesh", "packet switched baseline", "") == "packet_switched"


def test_backend_emits_noc_metrics_not_mpki(tmp_cfg, tmp_path):
    from archzero.sim.noc import NocAnalyticBackend

    work = tmp_path / "w"
    work.mkdir()
    backend = NocAnalyticBackend(tmp_cfg)
    result = backend.run(
        SimRequest(
            candidate_id="c1",
            workdir=work,
            patch_hint="Hierarchical request-grant with idle-slot injection",
            suite="small",
            meta={"title": "RG", "family": "noc_rg"},
        )
    )
    assert result.ok
    assert result.backend == "noc"
    assert result.metrics["p99_latency"] > 0
    assert result.metrics["goodput"] > 0
    assert "miss_reduction" not in result.metrics
    assert result.metrics["iso_wire"]["iso_bisection"] is True


def test_noc_result_is_report_only_against_the_real_spec():
    th = parse_acceptance_thresholds(
        load_problem_package(ROOT / "specs" / "noc_low_tail_collectives.md")
    )
    metrics = SimMetrics(
        evidence="analytic",
        backend="noc",
        domain="noc",
        p99_latency=12000,
        goodput=0.4,
        link_utilization=0.6,
    )
    outcome = metrics.apply_gates(th.spec_gates())
    assert outcome.ok
    assert outcome.adjudicated is False
    assert "p99_latency" in outcome.reported
    assert metrics.gate_ok() is True


def test_declared_noc_gate_can_still_fail():
    metrics = SimMetrics(p99_latency=20000, goodput=0.1)
    outcome = metrics.apply_gates(
        [MetricGate(metric_id="p99_latency", op="<=", value=1000.0)]
    )
    assert outcome.adjudicated is True
    assert outcome.ok is False
    assert "p99_latency" in outcome.failed
