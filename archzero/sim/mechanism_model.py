"""Lightweight mechanism-specific event models for Tier3 directed sim.

Not cycle-accurate: family-parameterized miss/bandwidth proxies so analytic
models can be checked for Magic Gap without a full ChampSim build.
"""

from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass
from typing import Any

from archzero.analytic.core import magic_gap
from archzero.sim.metrics import SimMetrics


@dataclass
class MechanismParams:
    family: str  # prefetch | replacement | bypass | filter | coalesce | streamer | other
    table_entries: int = 256
    history_len: int = 8
    prefetch_degree: int = 2
    filter_accuracy: float = 0.72
    bypass_threshold: float = 0.5
    base_reduction: float = 0.18
    extra_bw: float = 0.02
    area_mm2: float = 0.25


_FAMILY_HINTS = (
    ("prefetch", ("prefetch", "streamer", "stream")),
    ("filter", ("filter", "dead-block", "deadblock")),
    ("replacement", ("replacement", "rrpv", "lru", "ship")),
    ("bypass", ("bypass", "writeback", "throttle")),
    ("coalesce", ("coalesce", "merge")),
)


def infer_family(title: str, mechanism: str, explicit: str | None = None) -> str:
    if explicit:
        return explicit.lower().strip()
    blob = f"{title} {mechanism}".lower()
    for family, keys in _FAMILY_HINTS:
        if any(k in blob for k in keys):
            return family
    return "other"


def infer_params(
    *,
    title: str,
    mechanism: str,
    knobs: dict[str, Any] | None = None,
    family: str | None = None,
) -> MechanismParams:
    knobs = knobs or {}
    fam = infer_family(title, mechanism, family or knobs.get("family"))
    # Pull integers from mechanism text when present
    entries = _int_near(mechanism, r"(\d+)\s*(?:entry|entries)", 256)
    hist = _int_near(mechanism, r"history[^\d]{0,12}(\d+)", 8)
    degree = _int_near(mechanism, r"(?:degree|distance)[^\d]{0,8}(\d+)", 2)
    return MechanismParams(
        family=fam,
        table_entries=int(knobs.get("table_entries") or entries),
        history_len=int(knobs.get("history_len") or hist),
        prefetch_degree=int(knobs.get("prefetch_degree") or degree),
        filter_accuracy=float(knobs.get("filter_accuracy") or 0.72),
        bypass_threshold=float(knobs.get("bypass_threshold") or 0.5),
        base_reduction=float(knobs.get("miss_reduction") or 0.18),
        extra_bw=float(knobs.get("extra_bw") or 0.02),
        area_mm2=float(knobs.get("area") or 0.25),
    )


def _int_near(text: str, pattern: str, default: int) -> int:
    m = re.search(pattern, text or "", re.I)
    if not m:
        return default
    try:
        return max(1, int(m.group(1)))
    except ValueError:
        return default


def simulate_mechanism(
    params: MechanismParams,
    *,
    candidate_id: str = "anon",
    suite: str = "small",
) -> SimMetrics:
    """Family-specific event-model proxies (deterministic per candidate+suite)."""
    seed = int(
        hashlib.sha256(f"{candidate_id}:{suite}:{params.family}".encode()).hexdigest()[:8],
        16,
    )
    # Stable pseudo-noise in [-0.01, 0.01]
    noise = ((seed % 2001) / 100000.0) - 0.01

    if params.family in {"prefetch", "filter", "streamer"}:
        pollution = min(0.35, 0.04 * max(0, params.prefetch_degree - 1))
        capacity = min(1.0, math.log2(max(2, params.table_entries)) / 10.0)
        reduction = (
            params.base_reduction
            * params.filter_accuracy
            * (1.0 - pollution)
            * (0.7 + 0.3 * capacity)
        )
        bw = params.extra_bw + 0.01 * max(0, params.prefetch_degree - 2)
    elif params.family == "replacement":
        hist_factor = min(1.0, params.history_len / 16.0)
        table_factor = min(1.0, params.table_entries / 512.0)
        reduction = params.base_reduction * (0.55 + 0.45 * hist_factor * table_factor)
        bw = params.extra_bw * 0.5
    elif params.family == "bypass":
        useful = min(1.0, max(0.0, params.bypass_threshold))
        reduction = params.base_reduction * (0.4 + 0.6 * useful)
        bw = max(0.0, params.extra_bw - 0.01 * useful)
    elif params.family == "coalesce":
        reduction = params.base_reduction * 0.85
        bw = max(0.0, params.extra_bw - 0.005)
    else:
        reduction = params.base_reduction * 0.75
        bw = params.extra_bw

    reduction = max(0.0, min(0.9, reduction + noise))
    bw = max(0.0, min(0.5, bw))
    baseline_mpki = 8.2
    mpki = baseline_mpki * (1.0 - reduction)
    ipc = 1.45 * (1.0 + 0.22 * reduction)

    return SimMetrics(
        evidence="directed",
        backend="directed",
        suite=suite,
        baseline_mpki=baseline_mpki,
        mpki=mpki,
        miss_reduction=reduction,
        ipc=ipc,
        bw_delta_frac=bw,
        area_mm2=params.area_mm2,
        cycles=1_000_000 if suite != "full" else 10_000_000,
        note=f"mechanism event-model family={params.family} (not ChampSim)",
        extra={
            "family": params.family,
            "table_entries": params.table_entries,
            "history_len": params.history_len,
            "prefetch_degree": params.prefetch_degree,
        },
    )


def report_magic_gap(model_reduction: float | None, sim_reduction: float | None) -> float | None:
    if model_reduction is None or sim_reduction is None:
        return None
    return magic_gap(float(model_reduction), float(sim_reduction))
