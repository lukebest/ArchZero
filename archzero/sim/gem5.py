"""gem5 backend — parse stats.txt into shared SimMetrics."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from archzero.config import FactoryConfig
from archzero.sim.backend import SimBackend, SimRequest, SimResult
from archzero.sim.families import CACHE, request_domain
from archzero.sim.gem5_harness import write_gem5_harness
from archzero.sim.inapplicable import off_cache_sim_result
from archzero.sim.metrics import SimMetrics, compute_reduction
from archzero.sim.parse_gem5 import parse_stats_txt
from archzero.sim.stub import StubSimBackend


class Gem5Backend(SimBackend):
    name = "gem5"

    def __init__(self, cfg: FactoryConfig) -> None:
        self.cfg = cfg
        self._fallback = StubSimBackend(cfg)

    def available(self) -> bool:
        bin_path = self.cfg.sim.gem5_bin
        return bool(bin_path and Path(bin_path).exists())

    def run(self, req: SimRequest) -> SimResult:
        loaded: dict = {}
        knob_path = req.workdir / "sim_knobs.json"
        if knob_path.exists():
            try:
                loaded.update(json.loads(knob_path.read_text(encoding="utf-8")))
            except json.JSONDecodeError:
                pass
        domain = request_domain(req.meta, loaded)
        if domain != CACHE:
            return off_cache_sim_result("gem5", domain)

        if not self.available():
            result = self._fallback.run(req)
            result.backend = "gem5-unavailable→stub"
            result.unavailable = True
            result.metrics["note"] = "gem5 binary missing; used stub"
            result.metrics["evidence"] = "stub"
            return result

        bin_path = Path(self.cfg.sim.gem5_bin)  # type: ignore[arg-type]
        script = req.workdir / "run_gem5.py"
        if not script.exists():
            write_gem5_harness(
                req.workdir,
                family=req.meta.get("family"),
                domain=req.meta.get("domain"),
            )
            script = req.workdir / "run_gem5.py"

        knobs = dict(loaded)

        try:
            proc = subprocess.run(
                [str(bin_path), str(script)],
                cwd=str(req.workdir),
                capture_output=True,
                text=True,
                timeout=1800,
                check=False,
            )
        except Exception as exc:  # noqa: BLE001
            return SimResult(
                ok=False,
                metrics={"evidence": "sim", "error": str(exc)},
                log=str(exc),
                backend="gem5",
            )

        stats = parse_stats_txt(req.workdir / "stats.txt")
        if not stats.get("mpki") and not stats.get("ipc"):
            return SimResult(
                ok=False,
                metrics={
                    "evidence": "sim",
                    "returncode": proc.returncode,
                    "error": "failed to parse stats.txt",
                    "stdout_tail": proc.stdout[-2000:],
                },
                log=proc.stdout + "\n" + proc.stderr,
                backend="gem5",
            )

        # Baseline may be recorded by agent as baseline_stats.txt
        base = parse_stats_txt(req.workdir / "baseline_stats.txt")
        reduction = compute_reduction(base.get("mpki"), stats.get("mpki"))
        if reduction is None and knobs.get("miss_reduction") is not None:
            try:
                reduction = float(knobs["miss_reduction"])
            except (TypeError, ValueError):
                reduction = None

        bw_delta = None
        if knobs.get("extra_bw") is not None:
            try:
                bw_delta = float(knobs["extra_bw"])
            except (TypeError, ValueError):
                bw_delta = None
        if base.get("dram_bw_gbps") and stats.get("dram_bw_gbps"):
            b0 = float(base["dram_bw_gbps"])
            if b0 > 0:
                bw_delta = (float(stats["dram_bw_gbps"]) - b0) / b0

        area = None
        if knobs.get("area") is not None:
            try:
                area = float(knobs["area"])
            except (TypeError, ValueError):
                area = None

        metrics = SimMetrics(
            evidence="sim",
            backend="gem5",
            suite=req.suite,
            baseline_mpki=base.get("mpki"),
            mpki=stats.get("mpki"),
            miss_reduction=reduction,
            ipc=stats.get("ipc"),
            bw_delta_frac=bw_delta,
            area_mm2=area,
            cycles=stats.get("cycles"),
            extra={"returncode": proc.returncode},
        )
        ok = proc.returncode == 0 and metrics.meta_gate_ok(req.meta)
        return SimResult(
            ok=ok,
            metrics=metrics.as_dict(),
            log=proc.stdout + "\n" + proc.stderr,
            backend="gem5",
        )
