"""Analytic wafer-scale / multi-die fabric backend.

This is a first-principles hop + bisection model, not a thermal or yield
simulator. It measures die-to-die bandwidth and fabric hop latency so a
``new-spec --domain wafer`` package can be *reported* instead of refused.
Yield and power-density stay unmeasurable — those evaluators do not exist,
and this backend will not invent them.

Iso-resource point:

- 6×6 die grid (36 dies), SRAM-resident, no off-wafer DRAM
- 100 GB/s per inter-die link
- 24 cycles per hop (SERDES + uncore)
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from archzero.config import FactoryConfig
from archzero.sim.backend import SimBackend, SimRequest, SimResult
from archzero.sim.metrics import SimMetrics

GRID = 6
HOP_CYCLES = 24.0
LINK_GBPS = 100.0

FAMILIES: tuple[str, ...] = (
    "mesh_xy",
    "spare_bypass",
    "compiled_partition",
)


def _line_avg(n: int) -> float:
    if n <= 1:
        return 0.0
    return (n * n - 1) / (3.0 * n)


@dataclass(frozen=True)
class Fabric:
    grid: int = GRID
    hop_cycles: float = HOP_CYCLES
    link_gbps: float = LINK_GBPS

    @property
    def n(self) -> int:
        return self.grid * self.grid

    @property
    def avg_hops_xy(self) -> float:
        return 2.0 * _line_avg(self.grid)

    @property
    def bisection_links(self) -> int:
        return self.grid

    @property
    def raw_bisection_gbps(self) -> float:
        return self.link_gbps * self.bisection_links


@dataclass(frozen=True)
class FamilyModel:
    hop_tax: float
    bw_eff: float
    live_frac: float
    note: str


FAMILIES_MODEL: dict[str, FamilyModel] = {
    "mesh_xy": FamilyModel(1.0, 0.70, 1.0, "dimension-order routing, all dies live"),
    "spare_bypass": FamilyModel(
        1.20, 0.62, 34 / 36, "two isolated dies; XY detour around holes"
    ),
    "compiled_partition": FamilyModel(
        0.55, 0.85, 1.0, "communicating partitions placed adjacent"
    ),
}


def infer_wafer_family(title: str, mechanism: str, family: str | None) -> str:
    fam = (family or "").strip().lower().replace("-", "_")
    if fam in FAMILIES_MODEL:
        return fam
    blob = f"{title} {mechanism} {family or ''}".lower()
    if any(k in blob for k in ("compiled", "partition", "placement", "放置", "分区")):
        return "compiled_partition"
    if any(k in blob for k in ("spare", "bypass", "defect", "冗余", "绕行", "坏裸片")):
        return "spare_bypass"
    return "mesh_xy"


def evaluate_family(family_id: str, fabric: Fabric | None = None) -> dict[str, float]:
    fabric = fabric or Fabric()
    model = FAMILIES_MODEL[family_id]
    hops = fabric.avg_hops_xy * model.hop_tax
    latency = hops * fabric.hop_cycles
    bw = fabric.raw_bisection_gbps * model.bw_eff * model.live_frac
    return {
        "fabric_hop_latency": latency,
        "die_to_die_bw": bw,
        "avg_hops": hops,
        "live_frac": model.live_frac,
        "bisection_gbps": fabric.raw_bisection_gbps,
    }


def run_matrix(*, family_id: str) -> dict[str, Any]:
    fabric = Fabric()
    stats = evaluate_family(family_id, fabric)
    return {
        "family": family_id,
        "iso_resource": {
            "grid": fabric.grid,
            "n_dies": fabric.n,
            "link_gbps": fabric.link_gbps,
            "hop_cycles": fabric.hop_cycles,
            "bisection_links": fabric.bisection_links,
        },
        "aggregate": {
            "fabric_hop_latency": stats["fabric_hop_latency"],
            "die_to_die_bw": stats["die_to_die_bw"],
        },
        "headline": stats,
        "note": FAMILIES_MODEL[family_id].note,
    }


class WaferAnalyticBackend(SimBackend):
    name = "wafer"

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
        family_id = infer_wafer_family(
            str(req.meta.get("title") or ""),
            str(req.meta.get("mechanism") or req.patch_hint or ""),
            str(req.meta.get("family") or knobs.get("family") or ""),
        )
        if family_id not in FAMILIES_MODEL:
            family_id = "mesh_xy"
        report = run_matrix(family_id=family_id)
        agg = report["aggregate"]
        metrics = SimMetrics(
            evidence="analytic",
            backend="wafer",
            suite=req.suite,
            domain="wafer",
            fabric_hop_latency=agg["fabric_hop_latency"],
            die_to_die_bw=agg["die_to_die_bw"],
            note=(
                "analytic 6×6 die-grid hop + bisection model; not a thermal or "
                "yield simulator. Does not emit yield_redundancy or thermal_density."
            ),
            extra={
                "family": family_id,
                "iso_resource": report["iso_resource"],
                "headline": report["headline"],
                "family_note": report["note"],
            },
        )
        log_path = req.workdir / f"sim_wafer_{req.suite}.json"
        payload = {"metrics": metrics.as_dict(), "report": report}
        log_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return SimResult(
            ok=True,
            metrics=metrics.as_dict(),
            log=str(log_path),
            backend="wafer",
        )
