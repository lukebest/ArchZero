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

        knobs = dict(loaded)
        baseline_mpki = 8.0 + rng.random()
        baseline_ipc = 1.4 + 0.2 * rng.random()
        cycles = 10_000_000 if req.suite == "full" else 1_000_000
        extra = knobs.get("extra_bw")
        if extra is None:
            extra = knobs.get("bw_delta_frac")
        try:
            bw_delta = float(extra) if extra is not None else None
        except (TypeError, ValueError):
            bw_delta = None
        area_raw = knobs.get("area_mm2", knobs.get("area"))
        try:
            area = float(area_raw) if area_raw is not None else None
        except (TypeError, ValueError):
            area = None

        raw = knobs.get("miss_reduction")
        if raw is None:
            metrics = SimMetrics(
                evidence="stub",
                backend="stub",
                suite=req.suite,
                baseline_mpki=baseline_mpki,
                mpki=baseline_mpki,
                miss_reduction=None,
                ipc=baseline_ipc,
                bw_delta_frac=bw_delta,
                area_mm2=area,
                cycles=cycles,
                note=(
                    "synthetic stub — no miss_reduction in knobs; "
                    "iso-baseline, not a 12% cut"
                ),
            )
        else:
            reduction = max(0.0, min(0.9, float(raw) + rng.uniform(-0.03, 0.03)))
            metrics = SimMetrics(
                evidence="stub",
                backend="stub",
                suite=req.suite,
                baseline_mpki=baseline_mpki,
                mpki=baseline_mpki * (1.0 - reduction),
                miss_reduction=reduction,
                ipc=baseline_ipc * (1.0 + 0.25 * reduction),
                bw_delta_frac=bw_delta,
                area_mm2=area,
                cycles=cycles,
                note="synthetic stub — not architectural evidence",
            )
        log_path = req.workdir / f"sim_{req.suite}.json"
        log_path.write_text(json.dumps(metrics.as_dict(), indent=2), encoding="utf-8")
        ok = metrics.meta_gate_ok(req.meta)
        return SimResult(
            ok=ok,
            metrics=metrics.as_dict(),
            log=str(log_path),
            backend="stub",
        )
