"""Shared simulation metrics contract for stub / ChampSim / gem5 / NoC."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, Field

from archzero.spec.metrics import HIGHER_IS_BETTER, METRIC_BY_ID


class TraceMetrics(BaseModel):
    trace: str
    mpki: float | None = None
    ipc: float | None = None
    cycles: int | None = None
    instructions: int | None = None
    dram_bw_gbps: float | None = None


@dataclass(frozen=True)
class MetricGate:
    """One numeric check the funnel is allowed to apply.

    Only gates that came from the spec should be constructed. Passing a
    defaulted cache threshold here is how a NoC study used to be graded as
    a prefetcher — don't.
    """

    metric_id: str
    op: str
    value: float
    source: str = "spec"


@dataclass
class GateOutcome:
    ok: bool
    adjudicated: bool
    applied: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)
    reported: list[str] = field(default_factory=list)
    reason: str = ""


class SimMetrics(BaseModel):
    evidence: str = "stub"  # stub | sim | analytic | directed
    backend: str = "stub"
    suite: str = "small"
    domain: str | None = None
    baseline_mpki: float | None = None
    mpki: float | None = None
    miss_reduction: float | None = None
    ipc: float | None = None
    bw_delta_frac: float | None = None
    area_mm2: float | None = None
    cycles: int | None = None
    # Interconnect / collective metrics. None = this backend does not produce them.
    p95_latency: float | None = None
    p99_latency: float | None = None
    completion_latency: float | None = None
    goodput: float | None = None
    link_utilization: float | None = None
    jitter_tolerance: float | None = None
    # Generic / matrix coverage. None = this backend does not produce it.
    coverage: float | None = None
    # Spatial accelerator / dataflow. None = this backend does not produce them.
    pe_utilization: float | None = None
    reuse_factor: float | None = None
    sram_traffic: float | None = None
    # Wafer-scale / multi-die fabric. None = this backend does not produce them.
    die_to_die_bw: float | None = None
    fabric_hop_latency: float | None = None
    per_trace: list[TraceMetrics] = Field(default_factory=list)
    note: str | None = None
    extra: dict[str, Any] = Field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        d = self.model_dump(mode="json", exclude_none=True)
        extra = d.pop("extra", {}) or {}
        d.update(extra)
        return d

    def measured(self, metric_id: str) -> float | None:
        blob = self.as_dict()
        raw = blob.get(metric_id)
        if raw is None:
            return None
        try:
            return float(raw)
        except (TypeError, ValueError):
            return None

    def apply_gates(self, gates: list[MetricGate] | None) -> GateOutcome:
        """Check only the gates the caller handed over.

        An empty list means *report-only*: we produced numbers but the spec
        never said what 'pass' is, so we must not invent a verdict.
        """
        reported = [
            mid
            for mid in (
                "miss_reduction",
                "bw_delta_frac",
                "area_mm2",
                "p95_latency",
                "p99_latency",
                "completion_latency",
                "goodput",
                "link_utilization",
                "jitter_tolerance",
                "coverage",
                "pe_utilization",
                "reuse_factor",
                "sram_traffic",
                "die_to_die_bw",
                "fabric_hop_latency",
            )
            if self.measured(mid) is not None
        ]
        if not gates:
            return GateOutcome(
                ok=True,
                adjudicated=False,
                reported=reported,
                reason="report-only: no spec-declared performance gate",
            )
        applied: list[str] = []
        failed: list[str] = []
        for gate in gates:
            got = self.measured(gate.metric_id)
            if got is None:
                failed.append(gate.metric_id)
                applied.append(gate.metric_id)
                continue
            spec = METRIC_BY_ID.get(gate.metric_id)
            higher = (spec.direction == HIGHER_IS_BETTER) if spec else gate.op == ">="
            ok = got >= gate.value if higher else got <= gate.value
            applied.append(gate.metric_id)
            if not ok:
                failed.append(gate.metric_id)
        return GateOutcome(
            ok=not failed,
            adjudicated=True,
            applied=applied,
            failed=failed,
            reported=reported,
            reason="acc numeric ok" if not failed else f"failed gates: {', '.join(failed)}",
        )

    def gate_ok(
        self,
        *,
        min_reduction: float = 0.15,
        max_bw: float = 0.05,
        area_budget_mm2: float | None = None,
        gates: list[MetricGate] | None = None,
    ) -> bool:
        """Legacy cache gate, plus an explicit ``gates=`` path.

        When this run did not produce cache metrics, the legacy defaults are
        *not* applied — that is how a NoC result used to fail ``>=15% MPKI``
        without ever having an MPKI.
        """
        if gates is not None:
            return self.apply_gates(gates).ok
        if self.miss_reduction is None and self.bw_delta_frac is None:
            return True
        r = float(self.miss_reduction or 0.0)
        bw = float(self.bw_delta_frac or 0.0)
        if r < min_reduction or bw > max_bw:
            return False
        if area_budget_mm2 is not None and self.area_mm2 is not None:
            if float(self.area_mm2) > float(area_budget_mm2):
                return False
        return True


def geo_mean(values: list[float]) -> float | None:
    vals = [v for v in values if v is not None and v > 0]
    if not vals:
        return None
    return math.exp(sum(math.log(v) for v in vals) / len(vals))


def compute_reduction(baseline: float | None, candidate: float | None) -> float | None:
    if baseline is None or candidate is None or baseline <= 0:
        return None
    return max(0.0, min(1.0, 1.0 - (candidate / baseline)))
