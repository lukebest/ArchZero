"""Domain-shaped analytic helpers for Tier2 ``model.py``.

Cache models already import :mod:`archzero.analytic.core`. NoC and dataflow
models should call these instead of inventing an MPKI number.
"""

from __future__ import annotations

from typing import Any


def noc_model(family: str = "request_grant", *, message_b: float = 4096.0) -> dict[str, Any]:
    from archzero.sim.noc import run_matrix

    agg = run_matrix(family_id=family, message_b=message_b, suite="small")["aggregate"]
    return {
        **agg,
        "domain": "noc",
        "family": family,
        "meets_target": None,
    }


def dataflow_model(family: str = "output_stationary") -> dict[str, Any]:
    from archzero.sim.dataflow import run_matrix

    agg = run_matrix(family_id=family, suite="small")["aggregate"]
    return {
        **agg,
        "domain": "dataflow",
        "family": family,
        "meets_target": None,
    }


def wafer_model(family: str = "mesh_xy") -> dict[str, Any]:
    from archzero.sim.wafer import run_matrix

    agg = run_matrix(family_id=family)["aggregate"]
    return {**agg, "domain": "wafer", "family": family, "meets_target": None}

