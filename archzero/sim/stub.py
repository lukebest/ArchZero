"""Runnable stub simulator: synthetic traces + lightweight event model."""

from __future__ import annotations

import hashlib
import json
import random

from archzero.config import FactoryConfig
from archzero.sim.backend import SimBackend, SimRequest, SimResult
from archzero.sim.families import CACHE, family_domain
from archzero.sim.metrics import SimMetrics


class StubSimBackend(SimBackend):
    name = "stub"

    def __init__(self, cfg: FactoryConfig) -> None:
        self.cfg = cfg

    def available(self) -> bool:
        return True

    def run(self, req: SimRequest) -> SimResult:
        seed = int(
            hashlib.sha256(f"{req.candidate_id}:{req.suite}".encode()).hexdigest()[:8],
            16,
        )
        rng = random.Random(seed)

        loaded: dict = {}
        knob_path = req.workdir / "sim_knobs.json"
        if knob_path.exists():
            try:
                loaded.update(json.loads(knob_path.read_text(encoding="utf-8")))
            except json.JSONDecodeError:
                pass

        meta_domain = req.meta.get("domain")
        fam = req.meta.get("family") or loaded.get("family")
        if meta_domain in {"noc", "dataflow", "wafer"} or family_domain(fam) != CACHE:
            domain = (
                meta_domain
                if meta_domain in {"noc", "dataflow", "wafer"}
                else family_domain(fam)
            )
            metrics = SimMetrics(
                evidence="stub",
                backend="stub",
                suite=req.suite,
                domain=domain,
                note=(
                    "stub is a cache event model; this family is off-cache "
                    f"(domain={domain})"
                ),
            )
            log_path = req.workdir / f"sim_{req.suite}.json"
            log_path.write_text(json.dumps(metrics.as_dict(), indent=2), encoding="utf-8")
            return SimResult(
                ok=True,
                metrics=metrics.as_dict(),
                log=str(log_path),
                backend="stub",
            )

        knobs = {"miss_reduction": 0.12, "extra_bw": 0.02, "area": 0.3}
        knobs.update(loaded)

        baseline_mpki = 8.0 + rng.random()
        baseline_ipc = 1.4 + 0.2 * rng.random()
        reduction = float(knobs.get("miss_reduction", 0.12))
        reduction = max(0.0, min(0.9, reduction + rng.uniform(-0.03, 0.03)))
        mpki = baseline_mpki * (1.0 - reduction)
        ipc = baseline_ipc * (1.0 + 0.25 * reduction)
        bw_delta = float(knobs.get("extra_bw", 0.02))
        cycles = 10_000_000 if req.suite == "full" else 1_000_000

        metrics = SimMetrics(
            evidence="stub",
            backend="stub",
            suite=req.suite,
            baseline_mpki=baseline_mpki,
            mpki=mpki,
            miss_reduction=reduction,
            ipc=ipc,
            bw_delta_frac=bw_delta,
            area_mm2=float(knobs.get("area", 0.3)),
            cycles=cycles,
            note="synthetic stub — not architectural evidence",
        )
        log_path = req.workdir / f"sim_{req.suite}.json"
        log_path.write_text(json.dumps(metrics.as_dict(), indent=2), encoding="utf-8")
        min_red = float(req.meta.get("min_miss_reduction") or 0.15)
        max_bw = float(req.meta.get("max_bw_delta_frac") or 0.05)
        area_budget = req.meta.get("area_budget_mm2")
        ok = metrics.gate_ok(
            min_reduction=min_red,
            max_bw=max_bw,
            area_budget_mm2=float(area_budget) if area_budget is not None else None,
        )
        return SimResult(
            ok=ok,
            metrics=metrics.as_dict(),
            log=str(log_path),
            backend="stub",
        )
