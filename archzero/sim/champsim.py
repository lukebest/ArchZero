"""ChampSim backend — enabled when binary is configured and present."""

from __future__ import annotations

import subprocess
from pathlib import Path

from archzero.config import FactoryConfig
from archzero.sim.backend import SimBackend, SimRequest, SimResult
from archzero.sim.stub import StubSimBackend


class ChampSimBackend(SimBackend):
    name = "champsim"

    def __init__(self, cfg: FactoryConfig) -> None:
        self.cfg = cfg
        self._fallback = StubSimBackend(cfg)

    def available(self) -> bool:
        bin_path = self.cfg.sim.champsim_bin
        return bool(bin_path and Path(bin_path).exists())

    def run(self, req: SimRequest) -> SimResult:
        if not self.available():
            # Graceful: fall back to stub but mark unavailable for real backend
            result = self._fallback.run(req)
            result.backend = "champsim-unavailable→stub"
            result.unavailable = True
            result.metrics["note"] = "ChampSim binary missing; used stub"
            return result

        bin_path = Path(self.cfg.sim.champsim_bin)  # type: ignore[arg-type]
        # Expect agent to have written a patch / config under workdir
        config = req.workdir / "champsim_config.json"
        cmd = [str(bin_path), "--json", str(config)] if config.exists() else [str(bin_path)]
        try:
            proc = subprocess.run(
                cmd,
                cwd=str(req.workdir),
                capture_output=True,
                text=True,
                timeout=600,
                check=False,
            )
        except Exception as exc:  # noqa: BLE001
            return SimResult(
                ok=False,
                metrics={"error": str(exc)},
                log=str(exc),
                backend="champsim",
            )
        ok = proc.returncode == 0
        return SimResult(
            ok=ok,
            metrics={"returncode": proc.returncode, "stdout_tail": proc.stdout[-2000:]},
            log=proc.stdout + "\n" + proc.stderr,
            backend="champsim",
        )
