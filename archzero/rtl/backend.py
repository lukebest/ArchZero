"""RtlBackend ABC + PyCircuitBackend."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from archzero.config import FactoryConfig


@dataclass
class RtlRequest:
    candidate_id: str
    workdir: Path
    design_entry: Path  # design.py or tb_*.py
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class RtlResult:
    ok: bool
    unavailable: bool = False
    backend: str = ""
    verilog_files: list[str] = field(default_factory=list)
    manifest: dict[str, Any] = field(default_factory=dict)
    compile_stats: dict[str, Any] = field(default_factory=dict)
    log: str = ""
    tool_versions: dict[str, str] = field(default_factory=dict)


class RtlBackend(ABC):
    name: str = "base"

    @abstractmethod
    def available(self) -> bool: ...

    @abstractmethod
    def build(self, req: RtlRequest) -> RtlResult: ...


class NullRtlBackend(RtlBackend):
    name = "null"

    def available(self) -> bool:
        return False

    def build(self, req: RtlRequest) -> RtlResult:
        return RtlResult(
            ok=False,
            unavailable=True,
            backend="null",
            log="pyCircuit toolchain not configured",
        )


class PyCircuitBackend(RtlBackend):
    name = "pycircuit"

    def __init__(self, cfg: FactoryConfig) -> None:
        self.cfg = cfg

    def _root(self) -> Path:
        return self.cfg.resolved_pycircuit_root()

    def _toolchain(self) -> Path | None:
        if self.cfg.rtl.pyc_toolchain_root:
            p = Path(self.cfg.rtl.pyc_toolchain_root)
            return p if p.is_dir() else None
        # default relative to repo / pycircuit
        for cand in (
            self._root().parent.parent / ".pycircuit_out" / "toolchain" / "install",
            self._root() / ".pycircuit_out" / "toolchain" / "install",
            Path.cwd() / ".pycircuit_out" / "toolchain" / "install",
        ):
            if cand.is_dir():
                return cand
        return None

    def available(self) -> bool:
        root = self._root()
        if not root.is_dir():
            return False
        # Frontend package present
        frontend = root / "compiler" / "frontend" / "pycircuit"
        if not frontend.is_dir():
            return False
        # pycc optional for "available" — build() will report UNAVAILABLE if missing
        return True

    def _versions(self) -> dict[str, str]:
        vers: dict[str, str] = {}
        for tool in ("verilator", "iverilog", "yosys", "pycc"):
            path = shutil.which(tool)
            if path:
                try:
                    out = subprocess.run(
                        [path, "--version"],
                        capture_output=True,
                        text=True,
                        timeout=10,
                        check=False,
                    )
                    vers[tool] = (out.stdout or out.stderr).splitlines()[0][:120]
                except Exception:  # noqa: BLE001
                    vers[tool] = path
        return vers

    def build(self, req: RtlRequest) -> RtlResult:
        if not self.available():
            return RtlResult(
                ok=False,
                unavailable=True,
                backend="pycircuit",
                log="vendor/pycircuit missing — run tools/setup_pycircuit.sh",
                tool_versions=self._versions(),
            )
        toolchain = self._toolchain()
        root = self._root()
        frontend = root / "compiler" / "frontend"
        env = os.environ.copy()
        env["PYTHONPATH"] = str(frontend) + os.pathsep + env.get("PYTHONPATH", "")
        if toolchain:
            env["PYC_TOOLCHAIN_ROOT"] = str(toolchain)
            env["PATH"] = str(toolchain / "bin") + os.pathsep + env.get("PATH", "")

        out_dir = req.workdir / "pyc_build"
        out_dir.mkdir(parents=True, exist_ok=True)
        entry = req.design_entry
        if not entry.is_file():
            return RtlResult(
                ok=False,
                unavailable=False,
                backend="pycircuit",
                log=f"missing design entry {entry}",
                tool_versions=self._versions(),
            )

        cmd = [
            "python3",
            "-m",
            "pycircuit.cli",
            "build",
            str(entry),
            "--out-dir",
            str(out_dir),
            "--target",
            "both",
            "--jobs",
            "2",
        ]
        try:
            proc = subprocess.run(
                cmd,
                cwd=str(req.workdir),
                capture_output=True,
                text=True,
                timeout=1800,
                check=False,
                env=env,
            )
        except FileNotFoundError:
            return RtlResult(
                ok=False,
                unavailable=True,
                backend="pycircuit",
                log="python3 or pycircuit.cli not found",
                tool_versions=self._versions(),
            )
        except Exception as exc:  # noqa: BLE001
            return RtlResult(
                ok=False,
                unavailable=True,
                backend="pycircuit",
                log=str(exc),
                tool_versions=self._versions(),
            )

        manifest: dict[str, Any] = {}
        stats: dict[str, Any] = {}
        verilog: list[str] = []
        for man in out_dir.rglob("manifest.json"):
            try:
                manifest = json.loads(man.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                pass
        for st in out_dir.rglob("compile_stats.json"):
            try:
                stats = json.loads(st.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                pass
        for v in out_dir.rglob("*.v"):
            verilog.append(str(v.relative_to(req.workdir)))

        ok = proc.returncode == 0 and bool(verilog)
        # If pycc missing, treat as unavailable
        unavailable = proc.returncode != 0 and (
            "pycc" in (proc.stderr + proc.stdout).lower()
            or toolchain is None
        )
        return RtlResult(
            ok=ok,
            unavailable=unavailable,
            backend="pycircuit",
            verilog_files=verilog,
            manifest=manifest,
            compile_stats=stats,
            log=(proc.stdout + "\n" + proc.stderr)[-8000:],
            tool_versions=self._versions(),
        )


def get_rtl_backend(cfg: FactoryConfig) -> RtlBackend:
    from archzero.rtl.registry import resolve_rtl_backend

    return resolve_rtl_backend(cfg)
