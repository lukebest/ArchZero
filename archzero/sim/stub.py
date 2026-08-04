"""Runnable stub simulator: synthetic traces + lightweight event model."""

from __future__ import annotations

import hashlib
import json
import random
from pathlib import Path

from archzero.config import FactoryConfig
from archzero.sim.backend import SimBackend, SimRequest, SimResult


class StubSimBackend(SimBackend):
    name = "stub"

    def __init__(self, cfg: FactoryConfig) -> None:
        self.cfg = cfg

    def available(self) -> bool:
        return True

    def run(self, req: SimRequest) -> SimResult:
        # Deterministic per candidate+suite
        seed = int(hashlib.sha256(f"{req.candidate_id}:{req.suite}".encode()).hexdigest()[:8], 16)
        rng = random.Random(seed)

        # Read optional knobs from workdir
        knobs = {"miss_reduction": 0.12, "extra_bw": 0.02, "area": 0.3}
        knob_path = req.workdir / "sim_knobs.json"
        if knob_path.exists():
            try:
                knobs.update(json.loads(knob_path.read_text(encoding="utf-8")))
            except json.JSONDecodeError:
                pass

        # Synthetic baseline
        baseline_mpki = 8.0 + rng.random()
        baseline_ipc = 1.4 + 0.2 * rng.random()
        reduction = float(knobs.get("miss_reduction", 0.12))
        # noise
        reduction = max(0.0, min(0.9, reduction + rng.uniform(-0.03, 0.03)))
        mpki = baseline_mpki * (1.0 - reduction)
        ipc = baseline_ipc * (1.0 + 0.25 * reduction)
        bw_delta = float(knobs.get("extra_bw", 0.02))
        cycles = 10_000_000 if req.suite == "full" else 1_000_000

        metrics = {
            "backend": "stub",
            "suite": req.suite,
            "baseline_mpki": baseline_mpki,
            "mpki": mpki,
            "miss_reduction": reduction,
            "ipc": ipc,
            "bw_delta_frac": bw_delta,
            "area_mm2": float(knobs.get("area", 0.3)),
            "cycles": cycles,
        }
        log_path = req.workdir / f"sim_{req.suite}.json"
        log_path.write_text(json.dumps(metrics, indent=2), encoding="utf-8")
        ok = reduction >= 0.10 and bw_delta <= 0.05
        return SimResult(ok=ok, metrics=metrics, log=str(log_path), backend="stub")
