"""Analytic dataflow backend: iso-resource GEMM mapper, no invented MPKI."""

from __future__ import annotations

from pathlib import Path

import pytest

from archzero.sim.backend import SimRequest, get_backend
from archzero.sim.dataflow import (
    Array,
    evaluate_gemm,
    infer_dataflow_family,
    run_matrix,
)
from archzero.sim.registry import resolve_backend_for_domain
from archzero.spec.acc_parse import parse_acceptance_thresholds
from archzero.spec.ndf import load_problem_package
from archzero.spec.wizard import scaffold_problem


def test_square_os_is_fully_utilized():
    stats = evaluate_gemm(family="output_stationary", m=256, n=256, k=256)
    assert stats["pe_utilization"] == pytest.approx(1.0)
    assert stats["reuse_factor"] > 1.0
    assert 0 < stats["sram_traffic"] < 1.0


def test_leftover_pes_drop_utilization():
    full = evaluate_gemm(family="output_stationary", m=16, n=16, k=8)
    leftover = evaluate_gemm(family="output_stationary", m=17, n=17, k=8)
    assert full["pe_utilization"] == pytest.approx(1.0)
    assert leftover["pe_utilization"] < 0.9


def test_weight_stationary_reuses_b_better_than_os_on_skinny_n():
    """Wide N, small M: WS keeps B, OS reloads A for every N-tile."""
    os_ = evaluate_gemm(family="output_stationary", m=32, n=1024, k=64)
    ws = evaluate_gemm(family="weight_stationary", m=32, n=1024, k=64)
    assert ws["reuse_factor"] > os_["reuse_factor"]


def test_row_stationary_occupancy_tax():
    os_ = evaluate_gemm(family="output_stationary", m=256, n=256, k=256)
    rs = evaluate_gemm(family="row_stationary", m=256, n=256, k=256)
    assert rs["pe_utilization"] < os_["pe_utilization"]
    assert rs["sram_traffic"] < os_["sram_traffic"]


def test_infer_family_does_not_match_short_tokens_in_prose():
    assert infer_dataflow_family("this is a mapper", "sparse weights", None) == (
        "output_stationary"
    )
    assert infer_dataflow_family("t", "m", "ws") == "weight_stationary"
    assert infer_dataflow_family("Eyeriss-style rows", "keep a row in RF", None) == (
        "row_stationary"
    )


def test_backend_emits_dataflow_metrics_not_mpki(tmp_cfg, tmp_path: Path):
    tmp_cfg.sim.backend = "dataflow"
    backend = get_backend(tmp_cfg)
    work = tmp_path / "df"
    work.mkdir()
    result = backend.run(
        SimRequest(
            candidate_id="c1",
            workdir=work,
            patch_hint="output-stationary tiling",
            suite="small",
            meta={"title": "OS mapper", "family": "os"},
        )
    )
    assert result.ok
    assert result.backend == "dataflow"
    assert "pe_utilization" in result.metrics
    assert "reuse_factor" in result.metrics
    assert "sram_traffic" in result.metrics
    assert "miss_reduction" not in result.metrics


def test_domain_routes_and_report_only_scaffold(tmp_cfg, tmp_path: Path):
    path = scaffold_problem(
        title="df route",
        workload="w",
        symptom="s",
        constraint="c",
        domain="dataflow",
        out_dir=tmp_path,
    )
    th = parse_acceptance_thresholds(load_problem_package(path))
    backend, name, reason = resolve_backend_for_domain(tmp_cfg, th.domain)
    assert name == "dataflow"
    assert reason is not None
    assert backend.name == "dataflow"
    work = tmp_path / "w"
    work.mkdir()
    outcome = backend.run(
        SimRequest(candidate_id="c", workdir=work, patch_hint="os", suite="small")
    ).metrics
    from archzero.sim.metrics import SimMetrics

    metrics = SimMetrics.model_validate(
        {k: v for k, v in outcome.items() if k in SimMetrics.model_fields}
    )
    gate = metrics.apply_gates(th.spec_gates())
    assert gate.ok
    assert not gate.adjudicated
    assert "pe_utilization" in gate.reported


def test_run_matrix_iso_resource_is_stated():
    report = run_matrix(family_id="output_stationary", suite="small")
    iso = report["iso_resource"]
    assert iso["pe_rows"] == Array().rows
    assert iso["sram_bytes"] == Array().sram_bytes
    assert len(report["matrix"]) == 2
