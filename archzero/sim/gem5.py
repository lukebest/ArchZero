"""gem5 backend — enabled when binary is configured and present."""

from __future__ import annotations

import subprocess
from pathlib import Path

from archzero.config import FactoryConfig
from archzero.sim.backend import SimBackend, SimRequest, SimResult
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
        if not self.available():
            result = self._fallback.run(req)
            result.backend = "gem5-unavailable→stub"
            result.unavailable = True
            result.metrics["note"] = "gem5 binary missing; used stub"
            return result

        bin_path = Path(self.cfg.sim.gem5_bin)  # type: ignore[arg-type]
        script = req.workdir / "run_gem5.py"
        if not script.exists():
            return SimResult(
                ok=False,
                metrics={"error": "missing run_gem5.py"},
                log="agent must write run_gem5.py",
                backend="gem5",
            )
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
                metrics={"error": str(exc)},
                log=str(exc),
                backend="gem5",
            )
        return SimResult(
            ok=proc.returncode == 0,
            metrics={"returncode": proc.returncode, "stdout_tail": proc.stdout[-2000:]},
            log=proc.stdout + "\n" + proc.stderr,
            backend="gem5",
        )
