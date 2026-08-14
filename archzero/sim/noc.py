"""Analytic NoC / collective-communication backend.

This is a first-principles α-β + bisection model, not a flit-level simulator.
It exists so a problem package about p99 completion latency can be *measured*
instead of being silently graded on MPKI. What it will not do is invent a
PASS/FAIL when the spec never stated a numeric gate — that is the caller's
job via :meth:`SimMetrics.apply_gates`.

Geometry and timing follow ``specs/noc_*.md``:

- 8×6 node grid
- 2D mesh at 64 B/cycle vs folded 2D torus at 32 B/cycle (iso-wire / iso-bisection)
- X-link delay 7 cycles, Y-link delay 9 cycles
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from typing import Any

from archzero.config import FactoryConfig
from archzero.sim.backend import SimBackend, SimRequest, SimResult
from archzero.sim.metrics import SimMetrics

COLS = 8
ROWS = 6
N_NODES = COLS * ROWS
X_DELAY = 7
Y_DELAY = 9
MESH_BPC = 64.0
TORUS_BPC = 32.0
DEFAULT_MESSAGE_B = 4096.0

COLLECTIVES: tuple[str, ...] = (
    "allgather",
    "allreduce",
    "gather",
    "reduce",
    "broadcast",
    "alltoall",
)
SYNC_COLLECTIVES = frozenset({"allgather", "allreduce"})


def _ring_avg(n: int) -> float:
    """Mean wraparound distance on a ring of ``n`` nodes."""
    if n <= 1:
        return 0.0
    if n % 2 == 0:
        return n / 4.0
    return (n * n - 1) / (4.0 * n)


def _line_avg(n: int) -> float:
    """Mean |i-j| on a line of ``n`` nodes."""
    if n <= 1:
        return 0.0
    return (n * n - 1) / (3.0 * n)


@dataclass(frozen=True)
class Topology:
    name: str
    cols: int = COLS
    rows: int = ROWS
    link_bpc: float = MESH_BPC
    wrap: bool = False

    @property
    def n(self) -> int:
        return self.cols * self.rows

    @property
    def avg_x(self) -> float:
        return _ring_avg(self.cols) if self.wrap else _line_avg(self.cols)

    @property
    def avg_y(self) -> float:
        return _ring_avg(self.rows) if self.wrap else _line_avg(self.rows)

    @property
    def avg_hops(self) -> float:
        return self.avg_x + self.avg_y

    @property
    def diameter(self) -> int:
        if self.wrap:
            return self.cols // 2 + self.rows // 2
        return (self.cols - 1) + (self.rows - 1)

    @property
    def hop_cycles(self) -> float:
        hops = self.avg_hops
        if hops <= 0:
            return 0.0
        return (self.avg_x * X_DELAY + self.avg_y * Y_DELAY) / hops

    @property
    def bisection_bpc(self) -> float:
        """Min cut bandwidth. Iso-wire makes mesh and torus equal on 8×6."""
        # Vertical cut (split columns): ``rows`` links, torus has wrap → 2×.
        vert_links = self.rows * (2 if self.wrap else 1)
        # Horizontal cut (split rows): ``cols`` links.
        horz_links = self.cols * (2 if self.wrap else 1)
        return min(vert_links, horz_links) * self.link_bpc

    @property
    def degree(self) -> float:
        return 4.0 if self.wrap else 3.2  # interior 4, edge 3, corner 2; 8×6 avg ≈ 3.17


MESH = Topology(name="mesh", link_bpc=MESH_BPC, wrap=False)
TORUS = Topology(name="torus", link_bpc=TORUS_BPC, wrap=True)


@dataclass(frozen=True)
class FamilyModel:
    id: str
    # Multiplier on no-load completion for mean contention / arbitration waste.
    contention: float
    tail_p95: float
    tail_p99: float
    # Fraction of peak bisection that carries useful bytes.
    goodput_eff: float
    # Extra diameters of control-plane setup for synchronized collectives.
    sync_setup_diameters: float
    # Bufferless deflection tax (1.0 = none).
    bufferless_tax: float


FAMILIES: dict[str, FamilyModel] = {
    "packet_switched": FamilyModel(
        "packet_switched", 1.35, 1.80, 2.60, 0.55, 0.0, 1.35
    ),
    "request_grant": FamilyModel(
        "request_grant", 1.08, 1.25, 1.45, 0.48, 1.0, 1.10
    ),
    "push_on_pull": FamilyModel(
        "push_on_pull", 1.15, 1.40, 1.70, 0.58, 0.0, 1.15
    ),
    "presched": FamilyModel(
        "presched", 1.02, 1.08, 1.12, 0.70, 0.0, 1.05
    ),
}


def infer_noc_family(title: str, mechanism: str, family: str | None) -> str:
    blob = f"{title} {mechanism} {family or ''}".lower()
    if any(k in blob for k in ("presched", "pre-sched", "compiled", "slot table", "排图")):
        return "presched"
    if any(k in blob for k in ("push-on-pull", "push_on_pull", "noc_pop", "pull window")):
        return "push_on_pull"
    if any(
        k in blob
        for k in ("request-grant", "request_grant", "noc_rg", "grant", "arbiter")
    ):
        return "request_grant"
    return "packet_switched"


def _noload_cycles(topo: Topology, pattern: str, message_b: float) -> float:
    """Hockney / bisection bound with no contention."""
    n = topo.n
    alpha = topo.hop_cycles
    beta = 1.0 / topo.link_bpc
    logn = math.ceil(math.log2(n))
    # Bandwidth-bound term: bytes that must cross the bisection, over B_bisect.
    half = n / 2.0
    if pattern == "broadcast":
        latency = logn * (2.5 * alpha + message_b * beta)
        volume_cut = (n / 2.0) * message_b
    elif pattern == "reduce":
        latency = logn * (2.5 * alpha + message_b * beta)
        volume_cut = (n / 2.0) * message_b
    elif pattern == "gather":
        latency = topo.diameter * alpha + message_b * beta
        volume_cut = (n / 2.0) * message_b
        # Root injection also bounds gather/reduce-to-one.
        inj = (n - 1) * message_b / (topo.degree * topo.link_bpc)
        latency = max(latency, inj)
    elif pattern == "allgather":
        latency = logn * alpha + (n - 1) * message_b * beta
        volume_cut = half * (n * message_b) / 2.0
    elif pattern == "allreduce":
        # Rabenseifner-style: reduce-scatter + allgather.
        latency = 2.0 * logn * alpha + 2.0 * (n - 1) / n * message_b * beta
        volume_cut = half * message_b
    elif pattern == "alltoall":
        latency = topo.diameter * alpha + message_b * beta
        volume_cut = (half * half) * message_b
        inj = (n - 1) * message_b / (topo.degree * topo.link_bpc)
        latency = max(latency, inj)
    elif pattern == "p2p":
        latency = topo.avg_hops * alpha + message_b * beta
        volume_cut = half * message_b
    else:
        latency = topo.avg_hops * alpha + message_b * beta
        volume_cut = half * message_b
    bw_bound = volume_cut / topo.bisection_bpc if topo.bisection_bpc else latency
    return max(latency, bw_bound)


def evaluate_config(
    *,
    topo: Topology,
    pattern: str,
    family: FamilyModel,
    bufferless: bool,
    message_b: float,
) -> dict[str, float]:
    base = _noload_cycles(topo, pattern, message_b)
    if bufferless:
        base *= family.bufferless_tax
    if pattern in SYNC_COLLECTIVES and family.sync_setup_diameters:
        base += family.sync_setup_diameters * topo.diameter * topo.hop_cycles
    mean = base * family.contention
    p95 = mean * family.tail_p95
    p99 = mean * family.tail_p99
    # Useful bytes relative to (completion × bisection): a unitless efficiency.
    useful = message_b * (topo.n if pattern != "p2p" else 1.0)
    capacity = mean * topo.bisection_bpc
    raw_util = min(1.0, useful / capacity) if capacity else 0.0
    goodput = raw_util * family.goodput_eff
    return {
        "completion_latency": mean,
        "p95_latency": p95,
        "p99_latency": p99,
        "goodput": goodput,
        "link_utilization": raw_util,
        "noload_cycles": base,
        "bisection_bpc": topo.bisection_bpc,
        "link_bpc": topo.link_bpc,
        "avg_hops": topo.avg_hops,
        "diameter": float(topo.diameter),
    }


def run_matrix(
    *,
    family_id: str,
    message_b: float = DEFAULT_MESSAGE_B,
    suite: str = "small",
) -> dict[str, Any]:
    family = FAMILIES[family_id]
    if suite == "full":
        topos = (MESH, TORUS)
        buffers = (False, True)
        patterns = COLLECTIVES + ("p2p",)
    else:
        topos = (MESH,)
        buffers = (False,)
        patterns = ("allreduce", "allgather", "alltoall", "broadcast", "p2p")

    rows: list[dict[str, Any]] = []
    for topo in topos:
        for bufferless in buffers:
            for pattern in patterns:
                m = evaluate_config(
                    topo=topo,
                    pattern=pattern,
                    family=family,
                    bufferless=bufferless,
                    message_b=message_b,
                )
                rows.append(
                    {
                        "topology": topo.name,
                        "bufferless": bufferless,
                        "pattern": pattern,
                        **m,
                    }
                )

    def _geo(key: str) -> float:
        vals = [r[key] for r in rows if r[key] > 0]
        if not vals:
            return 0.0
        return math.exp(sum(math.log(v) for v in vals) / len(vals))

    headline = next(
        (
            r
            for r in rows
            if r["topology"] == "mesh"
            and not r["bufferless"]
            and r["pattern"] == "allreduce"
        ),
        rows[0],
    )
    return {
        "family": family_id,
        "message_b": message_b,
        "iso_wire": {
            "mesh_link_bpc": MESH.link_bpc,
            "torus_link_bpc": TORUS.link_bpc,
            "mesh_bisection_bpc": MESH.bisection_bpc,
            "torus_bisection_bpc": TORUS.bisection_bpc,
            "iso_bisection": abs(MESH.bisection_bpc - TORUS.bisection_bpc) < 1e-6,
        },
        "headline": headline,
        "aggregate": {
            "completion_latency": _geo("completion_latency"),
            "p95_latency": _geo("p95_latency"),
            "p99_latency": _geo("p99_latency"),
            "goodput": _geo("goodput"),
            "link_utilization": _geo("link_utilization"),
        },
        "matrix": rows,
        "coverage": len(rows) / (2 * 2 * (len(COLLECTIVES) + 1)),
    }


class NocAnalyticBackend(SimBackend):
    name = "noc"

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
        family_id = infer_noc_family(
            str(req.meta.get("title") or ""),
            str(req.meta.get("mechanism") or req.patch_hint or ""),
            str(req.meta.get("family") or knobs.get("family") or ""),
        )
        message_b = float(knobs.get("message_b") or knobs.get("message_bytes") or DEFAULT_MESSAGE_B)
        report = run_matrix(family_id=family_id, message_b=message_b, suite=req.suite)
        agg = report["aggregate"]
        metrics = SimMetrics(
            evidence="analytic",
            backend="noc",
            suite=req.suite,
            domain="noc",
            completion_latency=agg["completion_latency"],
            p95_latency=agg["p95_latency"],
            p99_latency=agg["p99_latency"],
            goodput=agg["goodput"],
            link_utilization=agg["link_utilization"],
            note=(
                "analytic α-β + bisection model on 8×6 iso-wire mesh/torus; "
                "not a flit-level trace. Tail multipliers are family contention "
                "assumptions, not measured distributions."
            ),
            extra={
                "family": family_id,
                "iso_wire": report["iso_wire"],
                "headline": report["headline"],
                "coverage": report["coverage"],
                "n_configs": len(report["matrix"]),
            },
        )
        log_path = req.workdir / f"sim_noc_{req.suite}.json"
        payload = {"metrics": metrics.as_dict(), "matrix": report["matrix"]}
        log_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        # ok=True means the model ran. Adjudication is the caller's job.
        return SimResult(
            ok=True,
            metrics=metrics.as_dict(),
            log=str(log_path),
            backend="noc",
        )
