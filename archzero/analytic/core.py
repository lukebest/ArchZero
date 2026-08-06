"""Shared analytic kernel for Tier2 models.

Candidates import these helpers when generating model.py so equations stay
composable and Magic Gap calculations are consistent.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Workload:
    name: str
    baseline_mpki: float
    baseline_ipc: float
    mem_bandwidth_gbps: float
    peak_bandwidth_gbps: float


@dataclass
class MechanismEffect:
    miss_reduction_frac: float  # 0.15 = 15% fewer misses
    extra_bw_frac: float = 0.0
    area_mm2: float = 0.0
    power_mw: float = 0.0


def amdahl_speedup(fraction_improved: float, speedup: float) -> float:
    fraction_improved = max(0.0, min(1.0, fraction_improved))
    if speedup <= 0:
        return 1.0
    return 1.0 / ((1.0 - fraction_improved) + fraction_improved / speedup)


def predicted_mpki(w: Workload, effect: MechanismEffect) -> float:
    return w.baseline_mpki * (1.0 - effect.miss_reduction_frac)


def bandwidth_ok(w: Workload, effect: MechanismEffect, slack: float = 0.05) -> bool:
    demand = w.mem_bandwidth_gbps * (1.0 + effect.extra_bw_frac)
    return demand <= w.peak_bandwidth_gbps * (1.0 + slack)


def magic_gap(model_value: float, sim_value: float | None) -> float | None:
    if sim_value is None or sim_value == 0:
        return None
    return abs(model_value - sim_value) / abs(sim_value)


def score_mechanism(
    w: Workload,
    effect: MechanismEffect,
    *,
    target_miss_reduction: float = 0.15,
    area_budget_mm2: float = 0.5,
    bw_slack: float = 0.05,
) -> dict:
    new_mpki = predicted_mpki(w, effect)
    reduction = 1.0 - (new_mpki / w.baseline_mpki if w.baseline_mpki else 1.0)
    # Rough IPC uplift: assume memory-bound fraction ~ min(1, mpki*0.05)
    mem_frac = min(1.0, w.baseline_mpki * 0.05)
    local_speedup = 1.0 / max(1e-6, (1.0 - reduction))
    ipc_speedup = amdahl_speedup(mem_frac, local_speedup)
    ok_bw = bandwidth_ok(w, effect, slack=bw_slack)
    ok_area = effect.area_mm2 <= area_budget_mm2
    ok_perf = reduction >= target_miss_reduction
    return {
        "predicted_mpki": new_mpki,
        "miss_reduction": reduction,
        "ipc_speedup": ipc_speedup,
        "bandwidth_ok": ok_bw,
        "area_ok": ok_area,
        "meets_target": ok_perf and ok_bw and ok_area,
    }
