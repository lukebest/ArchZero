"""Analytic wafer-scale fabric backend: hop + bisection, no invented yield."""

from __future__ import annotations

from pathlib import Path

from archzero.sim.backend import SimRequest, get_backend
from archzero.sim.metrics import SimMetrics
from archzero.sim.wafer import evaluate_family, infer_wafer_family, run_matrix
from archzero.spec.acc_parse import parse_acceptance_thresholds
from archzero.spec.ndf import load_problem_package
from archzero.spec.wizard import scaffold_problem


def test_compiled_partition_beats_mesh_on_hops_and_bw():
    mesh = evaluate_family("mesh_xy")
    compiled = evaluate_family("compiled_partition")
    assert compiled["fabric_hop_latency"] < mesh["fabric_hop_latency"]
    assert compiled["die_to_die_bw"] > mesh["die_to_die_bw"]


def test_spare_bypass_pays_a_hop_tax():
    mesh = evaluate_family("mesh_xy")
    spare = evaluate_family("spare_bypass")
    assert spare["fabric_hop_latency"] > mesh["fabric_hop_latency"]


def test_infer_wafer_family():
    assert infer_wafer_family("", "", "mesh_xy") == "mesh_xy"
    assert infer_wafer_family("compiled placement", "分区", "") == "compiled_partition"
    assert infer_wafer_family("spare dies", "绕行坏裸片", "") == "spare_bypass"
    assert infer_wafer_family("vanilla fabric", "xy routing", "") == "mesh_xy"


def test_backend_does_not_emit_cache_or_unmeasurable(tmp_cfg, tmp_path: Path):
    tmp_cfg.sim.backend = "wafer"
    backend = get_backend(tmp_cfg)
    work = tmp_path / "w"
    work.mkdir()
    result = backend.run(
        SimRequest(
            candidate_id="c1",
            workdir=work,
            patch_hint="mesh xy routing",
            suite="small",
            meta={"title": "Mesh", "family": "mesh_xy"},
        )
    )
    assert result.ok
    assert result.backend == "wafer"
    assert "die_to_die_bw" in result.metrics
    assert "fabric_hop_latency" in result.metrics
    assert "miss_reduction" not in result.metrics
    assert "yield_redundancy" not in result.metrics
    assert "thermal_density" not in result.metrics


def test_scaffolded_wafer_is_report_only(tmp_path: Path):
    path = scaffold_problem(
        title="wafer gates",
        workload="w",
        symptom="s",
        constraint="c",
        domain="wafer",
        out_dir=tmp_path,
    )
    th = parse_acceptance_thresholds(load_problem_package(path))
    report = run_matrix(family_id="mesh_xy")
    agg = report["aggregate"]
    metrics = SimMetrics(
        evidence="analytic",
        backend="wafer",
        domain="wafer",
        fabric_hop_latency=agg["fabric_hop_latency"],
        die_to_die_bw=agg["die_to_die_bw"],
    )
    outcome = metrics.apply_gates(th.spec_gates())
    assert outcome.ok
    assert outcome.adjudicated is False
    assert "die_to_die_bw" in outcome.reported
    assert "fabric_hop_latency" in outcome.reported
