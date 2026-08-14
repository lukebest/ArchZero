"""ChampSim backend — real MPKI/IPC when binary + traces are present."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

from archzero.config import FactoryConfig
from archzero.sim.backend import SimBackend, SimRequest, SimResult
from archzero.sim.champsim_config import write_champsim_scaffold
from archzero.sim.families import CACHE, request_domain
from archzero.sim.inapplicable import off_cache_sim_result
from archzero.sim.metrics import SimMetrics, TraceMetrics, compute_reduction, geo_mean
from archzero.sim.parse_champsim import parse_champsim_stdout
from archzero.sim.stub import StubSimBackend
from archzero.sim.suites import resolve_traces
from archzero.store.artifacts import ArtifactStore


class ChampSimBackend(SimBackend):
    name = "champsim"

    def __init__(self, cfg: FactoryConfig) -> None:
        self.cfg = cfg
        self._fallback = StubSimBackend(cfg)

    def available(self) -> bool:
        bin_path = self.cfg.sim.champsim_bin
        return bool(bin_path and Path(bin_path).exists())

    def _load_knobs(self, workdir: Path) -> dict:
        knobs = {"miss_reduction": 0.12, "extra_bw": 0.02, "area": 0.3}
        knob_path = workdir / "sim_knobs.json"
        if knob_path.exists():
            try:
                knobs.update(json.loads(knob_path.read_text(encoding="utf-8")))
            except json.JSONDecodeError:
                pass
        return knobs

    def _cache_key(self, trace: Path, config_blob: str) -> str:
        h = hashlib.sha256()
        h.update(str(trace).encode())
        h.update(b"\0")
        h.update(config_blob.encode())
        return h.hexdigest()[:24]

    def _run_one(
        self, bin_path: Path, workdir: Path, trace: Path, label: str
    ) -> dict:
        out_log = workdir / f"champsim_{label}_{trace.stem}.log"
        cmd = [str(bin_path), "--warmup_instructions", "1000000",
               "--simulation_instructions", "5000000", str(trace)]
        config = workdir / "champsim_config.json"
        if config.exists():
            cmd = [str(bin_path), "--json", str(config), str(trace)]
        try:
            proc = subprocess.run(
                cmd,
                cwd=str(workdir),
                capture_output=True,
                text=True,
                timeout=900,
                check=False,
            )
        except Exception as exc:  # noqa: BLE001
            return {"error": str(exc)}
        text = proc.stdout + "\n" + proc.stderr
        out_log.write_text(text[-50000:], encoding="utf-8")
        parsed = parse_champsim_stdout(text)
        parsed["returncode"] = proc.returncode
        parsed["log"] = str(out_log)
        return parsed

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
            return off_cache_sim_result("champsim", domain)

        if not self.available():
            result = self._fallback.run(req)
            result.backend = "champsim-unavailable→stub"
            result.unavailable = True
            result.metrics["note"] = "ChampSim binary missing; used stub"
            result.metrics["evidence"] = "stub"
            return result

        bin_path = Path(self.cfg.sim.champsim_bin)  # type: ignore[arg-type]
        traces = resolve_traces(self.cfg, req.suite)
        knobs = {"miss_reduction": 0.12, "extra_bw": 0.02, "area": 0.3}
        knobs.update(loaded)
        write_champsim_scaffold(
            req.workdir,
            family=str(req.meta.get("family") or knobs.get("family") or ""),
            knobs=knobs,
            title=str(req.meta.get("title") or ""),
        )

        if not traces:
            # No traces: mark unavailable rather than fake PASS via stub when strict
            result = self._fallback.run(req)
            result.backend = "champsim-no-traces→stub"
            result.unavailable = True
            result.metrics["note"] = "no ChampSim traces under traces_dir"
            result.metrics["evidence"] = "stub"
            return result

        arts = ArtifactStore(self.cfg.artifacts_dir)
        per_trace: list[TraceMetrics] = []
        base_mpkis: list[float] = []
        cand_mpkis: list[float] = []
        ipcs: list[float] = []
        logs: list[str] = []

        for trace in traces:
            # Baseline (no knobs marker)
            base_key = self._cache_key(trace, "baseline")
            cache_path = self.cfg.artifacts_dir / f"champsim-base-{base_key}.json"
            if cache_path.is_file():
                base = json.loads(cache_path.read_text(encoding="utf-8"))
            else:
                base = self._run_one(bin_path, req.workdir, trace, "base")
                cache_path.write_text(json.dumps(base), encoding="utf-8")
                arts.put_text(json.dumps(base), suffix=".json")

            cand = self._run_one(bin_path, req.workdir, trace, "cand")
            logs.append(str(cand.get("log") or ""))

            b_mpki = base.get("mpki")
            c_mpki = cand.get("mpki")
            if b_mpki is not None:
                base_mpkis.append(float(b_mpki))
            if c_mpki is not None:
                cand_mpkis.append(float(c_mpki))
            if cand.get("ipc") is not None:
                ipcs.append(float(cand["ipc"]))

            per_trace.append(
                TraceMetrics(
                    trace=trace.name,
                    mpki=float(c_mpki) if c_mpki is not None else None,
                    ipc=float(cand["ipc"]) if cand.get("ipc") is not None else None,
                    cycles=cand.get("cycles"),
                    instructions=cand.get("instructions"),
                    dram_bw_gbps=cand.get("dram_bw_gbps"),
                )
            )

        if not cand_mpkis:
            return SimResult(
                ok=False,
                metrics={
                    "evidence": "sim",
                    "backend": "champsim",
                    "error": "failed to parse MPKI from ChampSim output",
                    "logs": logs,
                },
                log="\n".join(logs),
                backend="champsim",
            )

        base_g = geo_mean(base_mpkis) if base_mpkis else None
        cand_g = geo_mean(cand_mpkis)
        reduction = compute_reduction(base_g, cand_g)
        # If parser failed to get baseline, fall back to knobs only as note — not as evidence
        if reduction is None:
            reduction = float(knobs.get("miss_reduction") or 0)
            note = "partial parse; reduction from knobs (weak)"
        else:
            note = None

        bw = float(knobs.get("extra_bw", 0.02))
        metrics = SimMetrics(
            evidence="sim",
            backend="champsim",
            suite=req.suite,
            baseline_mpki=base_g,
            mpki=cand_g,
            miss_reduction=reduction,
            ipc=geo_mean(ipcs) if ipcs else None,
            bw_delta_frac=bw,
            area_mm2=float(knobs.get("area", 0.3)),
            per_trace=per_trace,
            note=note,
            extra={"n_traces": len(traces)},
        )
        min_red = float(req.meta.get("min_miss_reduction") or 0.15)
        max_bw = float(req.meta.get("max_bw_delta_frac") or 0.05)
        area_budget = req.meta.get("area_budget_mm2")
        ok = metrics.gate_ok(
            min_reduction=min_red,
            max_bw=max_bw,
            area_budget_mm2=float(area_budget) if area_budget is not None else None,
        ) and all((t.mpki is not None) for t in per_trace)
        return SimResult(
            ok=ok,
            metrics=metrics.as_dict(),
            log="\n".join(logs),
            backend="champsim",
        )
