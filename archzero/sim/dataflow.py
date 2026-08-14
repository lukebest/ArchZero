"""Analytic spatial-accelerator / dataflow backend.

This is a first-principles PE-array mapper for GEMM, not Timeloop or SCALE-Sim.
It exists so a problem package about PE utilisation and SRAM traffic can be
*measured* instead of being refused or graded on MPKI. It will not invent a
PASS/FAIL when the spec never stated a numeric gate.

Iso-resource point (matches ``new-spec --domain dataflow`` wording):

- 16×16 PE array
- 256 KiB on-chip SRAM
- 4-byte elements
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from typing import Any

from archzero.config import FactoryConfig
from archzero.sim.backend import SimBackend, SimRequest, SimResult
from archzero.sim.metrics import SimMetrics

PE_ROWS = 16
PE_COLS = 16
SRAM_BYTES = 256 * 1024
ELEM_B = 4.0

SHAPES: tuple[tuple[str, int, int, int], ...] = (
    ("square", 256, 256, 256),
    ("skinny", 32, 1024, 64),
    ("tall", 1024, 32, 256),
)

FAMILIES: tuple[str, ...] = (
    "output_stationary",
    "weight_stationary",
    "input_stationary",
    "row_stationary",
)


@dataclass(frozen=True)
class Array:
    rows: int = PE_ROWS
    cols: int = PE_COLS
    sram_bytes: int = SRAM_BYTES

    @property
    def n_pe(self) -> int:
        return self.rows * self.cols


def _tiles(dim: int, pe: int) -> int:
    return math.ceil(dim / pe) if pe else 1


def evaluate_gemm(
    *,
    family: str,
    m: int,
    n: int,
    k: int,
    array: Array | None = None,
) -> dict[str, float]:
    """Map ``C[M,N] += A[M,K] @ B[K,N]`` onto a PE array.

    Cycles are the product of spatial tiles and the stationary-axis length.
    DRAM traffic counts each operand reload implied by that tiling. SRAM
    traffic is on-chip buffer→PE bytes divided by the naive 2-operand MAC
    volume, so lower means more multicast / RF reuse.
    """
    array = array or Array()
    macs = float(m * n * k)
    occupancy = 1.0
    if family == "output_stationary":
        # C stationary: map M×N spatially, stream K.
        tiles = _tiles(m, array.rows) * _tiles(n, array.cols)
        cycles = tiles * k
        # A reloaded per N-tile; B reloaded per M-tile.
        dram = (m * k * ELEM_B) * _tiles(n, array.cols) + (k * n * ELEM_B) * _tiles(
            m, array.rows
        )
        tm, tn = min(array.rows, m), min(array.cols, n)
        sram = tiles * k * (tm + tn) * ELEM_B
    elif family == "weight_stationary":
        # B stationary: map K×N spatially, stream M. B is fetched once.
        tiles = _tiles(k, array.rows) * _tiles(n, array.cols)
        cycles = tiles * m
        dram = (k * n * ELEM_B) + (m * k * ELEM_B) * _tiles(n, array.cols)
        tk, tn = min(array.rows, k), min(array.cols, n)
        sram = tiles * m * (tk + tn) * ELEM_B
    elif family == "input_stationary":
        # A stationary: map M×K spatially, stream N. A is fetched once.
        tiles = _tiles(m, array.rows) * _tiles(k, array.cols)
        cycles = tiles * n
        dram = (m * k * ELEM_B) + (k * n * ELEM_B) * _tiles(m, array.rows)
        tm, tk = min(array.rows, m), min(array.cols, k)
        sram = tiles * n * (tm + tk) * ELEM_B
    elif family == "row_stationary":
        # Eyeriss-style row mapping: OS geometry with diagonal occupancy tax.
        occupancy = (array.rows + array.cols - 1) / float(array.n_pe)
        occupancy = min(1.0, occupancy * (array.rows / 2.0))
        # Keep occupancy in a realistic 0.55–0.85 band for a 16×16 array.
        occupancy = max(0.55, min(0.85, occupancy))
        tiles = _tiles(m, array.rows) * _tiles(n, array.cols)
        cycles = tiles * k
        dram = (m * k * ELEM_B) * _tiles(n, array.cols) + (k * n * ELEM_B) * _tiles(
            m, array.rows
        )
        tm, tn = min(array.rows, m), min(array.cols, n)
        # Row-stationary keeps a row in RF, so SRAM sees fewer A fills.
        sram = tiles * k * (tm * 0.5 + tn) * ELEM_B
    else:
        raise ValueError(f"unknown dataflow family {family!r}")

    dram += m * n * ELEM_B  # write C once
    pe_util = (macs * occupancy) / (array.n_pe * cycles) if cycles else 0.0
    pe_util = max(0.0, min(1.0, pe_util))
    operand_vol = 2.0 * macs * ELEM_B
    reuse = operand_vol / dram if dram else 0.0
    sram_traffic = sram / operand_vol if operand_vol else 0.0
    return {
        "pe_utilization": pe_util,
        "reuse_factor": reuse,
        "sram_traffic": sram_traffic,
        "cycles": float(cycles),
        "dram_bytes": dram,
        "sram_bytes": sram,
        "occupancy": occupancy,
        "macs": macs,
    }


_FAMILY_SHORT: dict[str, str] = {
    "os": "output_stationary",
    "ws": "weight_stationary",
    "is": "input_stationary",
    "rs": "row_stationary",
}


def infer_dataflow_family(title: str, mechanism: str, family: str | None) -> str:
    fam = (family or "").strip().lower().replace("-", "_")
    if fam in FAMILIES:
        return fam
    if fam in _FAMILY_SHORT:
        return _FAMILY_SHORT[fam]
    blob = f"{title} {mechanism}".lower()
    if any(k in blob for k in ("row_stationary", "row-stationary", "eyeriss")):
        return "row_stationary"
    if any(k in blob for k in ("weight_stationary", "weight-stationary")):
        return "weight_stationary"
    if any(k in blob for k in ("input_stationary", "input-stationary")):
        return "input_stationary"
    if any(k in blob for k in ("output_stationary", "output-stationary")):
        return "output_stationary"
    return "output_stationary"


def run_matrix(*, family_id: str, suite: str = "small") -> dict[str, Any]:
    array = Array()
    shapes = SHAPES if suite == "full" else SHAPES[:2]
    rows: list[dict[str, Any]] = []
    for name, m, n, k in shapes:
        stats = evaluate_gemm(family=family_id, m=m, n=n, k=k, array=array)
        rows.append({"shape": name, "M": m, "N": n, "K": k, **stats})

    def _geo(key: str) -> float:
        vals = [r[key] for r in rows if r[key] > 0]
        if not vals:
            return 0.0
        return math.exp(sum(math.log(v) for v in vals) / len(vals))

    headline = next((r for r in rows if r["shape"] == "square"), rows[0])
    return {
        "family": family_id,
        "iso_resource": {
            "pe_rows": array.rows,
            "pe_cols": array.cols,
            "sram_bytes": array.sram_bytes,
            "elem_bytes": ELEM_B,
        },
        "headline": headline,
        "aggregate": {
            "pe_utilization": _geo("pe_utilization"),
            "reuse_factor": _geo("reuse_factor"),
            "sram_traffic": _geo("sram_traffic"),
        },
        "matrix": rows,
        "coverage": len(rows) / len(SHAPES),
    }


class DataflowAnalyticBackend(SimBackend):
    name = "dataflow"

    def __init__(self, cfg: FactoryConfig) -> None:
        self.cfg = cfg

    def available(self) -> bool:
        return True

    def run(self, req: SimRequest) -> SimResult:
        knobs: dict[str, Any] = {}
        knob_path = req.workdir / "sim_knobs.json"
        if knob_path.exists():
            try:
                knobs.update(json.loads(knob_path.read_text(encoding="utf-8")))
            except json.JSONDecodeError:
                pass
        family_id = infer_dataflow_family(
            str(req.meta.get("title") or ""),
            str(req.meta.get("mechanism") or req.patch_hint or ""),
            str(req.meta.get("family") or knobs.get("family") or ""),
        )
        if family_id not in FAMILIES:
            family_id = "output_stationary"
        report = run_matrix(family_id=family_id, suite=req.suite)
        agg = report["aggregate"]
        metrics = SimMetrics(
            evidence="analytic",
            backend="dataflow",
            suite=req.suite,
            domain="dataflow",
            pe_utilization=agg["pe_utilization"],
            reuse_factor=agg["reuse_factor"],
            sram_traffic=agg["sram_traffic"],
            note=(
                "analytic PE-array GEMM mapper on a 16×16 / 256 KiB iso-resource "
                "point; not Timeloop or a cycle-accurate systolic RTL. "
                "Reuse and SRAM traffic follow the tiling implied by the family."
            ),
            extra={
                "family": family_id,
                "iso_resource": report["iso_resource"],
                "headline": report["headline"],
                "coverage": report["coverage"],
                "n_configs": len(report["matrix"]),
            },
        )
        log_path = req.workdir / f"sim_dataflow_{req.suite}.json"
        payload = {"metrics": metrics.as_dict(), "matrix": report["matrix"]}
        log_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return SimResult(
            ok=True,
            metrics=metrics.as_dict(),
            log=str(log_path),
            backend="dataflow",
        )
