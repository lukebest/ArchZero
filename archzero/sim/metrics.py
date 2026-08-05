"""Shared simulation metrics contract for stub / ChampSim / gem5."""

from __future__ import annotations

import math
from typing import Any

from pydantic import BaseModel, Field


class TraceMetrics(BaseModel):
    trace: str
    mpki: float | None = None
    ipc: float | None = None
    cycles: int | None = None
    instructions: int | None = None
    dram_bw_gbps: float | None = None


class SimMetrics(BaseModel):
    evidence: str = "stub"  # stub | sim
    backend: str = "stub"
    suite: str = "small"
    baseline_mpki: float | None = None
    mpki: float | None = None
    miss_reduction: float | None = None
    ipc: float | None = None
    bw_delta_frac: float | None = None
    area_mm2: float | None = None
    cycles: int | None = None
    per_trace: list[TraceMetrics] = Field(default_factory=list)
    note: str | None = None
    extra: dict[str, Any] = Field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        d = self.model_dump(mode="json", exclude_none=True)
        extra = d.pop("extra", {}) or {}
        d.update(extra)
        return d

    def gate_ok(self, *, min_reduction: float = 0.10, max_bw: float = 0.05) -> bool:
        r = float(self.miss_reduction or 0.0)
        bw = float(self.bw_delta_frac or 0.0)
        return r >= min_reduction and bw <= max_bw


def geo_mean(values: list[float]) -> float | None:
    vals = [v for v in values if v is not None and v > 0]
    if not vals:
        return None
    return math.exp(sum(math.log(v) for v in vals) / len(vals))


def compute_reduction(baseline: float | None, candidate: float | None) -> float | None:
    if baseline is None or candidate is None or baseline <= 0:
        return None
    return max(0.0, min(1.0, 1.0 - (candidate / baseline)))
