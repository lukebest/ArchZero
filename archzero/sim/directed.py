"""Directed mechanism-model backend (Tier3 paper-style dedicated sim proxy)."""

from __future__ import annotations

import json

from archzero.config import FactoryConfig
from archzero.sim.backend import SimBackend, SimRequest, SimResult
from archzero.sim.mechanism_model import infer_params, simulate_mechanism
from archzero.sim.metrics import SimMetrics


class DirectedSimBackend(SimBackend):
    name = "directed"

    def __init__(self, cfg: FactoryConfig) -> None:
        self.cfg = cfg

    def available(self) -> bool:
        return True

    def run(self, req: SimRequest) -> SimResult:
        knobs: dict = {}
        knob_path = req.workdir / "sim_knobs.json"
        if knob_path.exists():
            try:
                knobs.update(json.loads(knob_path.read_text(encoding="utf-8")))
            except json.JSONDecodeError:
                pass

        title = str(req.meta.get("title") or "")
        mechanism = str(req.meta.get("mechanism") or req.patch_hint or "")
        family = req.meta.get("family") or knobs.get("family")
        params = infer_params(
            title=title,
            mechanism=mechanism,
            knobs=knobs,
            family=str(family) if family else None,
        )
        metrics: SimMetrics = simulate_mechanism(
            params, candidate_id=req.candidate_id, suite=req.suite
        )
        # Apply ACC thresholds from meta when present
        min_red = float(req.meta.get("min_miss_reduction") or 0.15)
        max_bw = float(req.meta.get("max_bw_delta_frac") or 0.05)
        ok = metrics.gate_ok(min_reduction=min_red, max_bw=max_bw)
        log_path = req.workdir / f"sim_directed_{req.suite}.json"
        log_path.write_text(json.dumps(metrics.as_dict(), indent=2), encoding="utf-8")
        return SimResult(
            ok=ok,
            metrics=metrics.as_dict(),
            log=str(log_path),
            backend="directed",
        )
