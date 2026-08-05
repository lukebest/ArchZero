"""Environment checks for architecture researchers before a campaign run."""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass

from archzero.config import ROOT, FactoryConfig
from archzero.sim.backend import get_backend


@dataclass
class Check:
    name: str
    ok: bool
    detail: str
    severity: str = "error"  # error | warn | info


def run_doctor(cfg: FactoryConfig) -> list[Check]:
    checks: list[Check] = []

    key = (cfg.cursor_api_key or os.environ.get("CURSOR_API_KEY") or "").strip()
    checks.append(
        Check(
            name="CURSOR_API_KEY",
            ok=bool(key),
            detail="set" if key else "missing — export from Cursor Dashboard → Integrations",
            severity="error",
        )
    )

    personas = cfg.personas_root
    n_personas = (
        len([p for p in personas.rglob("*.md") if p.name != "README.md"])
        if personas and personas.is_dir()
        else 0
    )
    checks.append(
        Check(
            name="personas",
            ok=n_personas > 0,
            detail=f"{n_personas} personas under {personas}"
            if n_personas
            else f"missing directory {personas} (expected archzero/personas)",
            severity="error",
        )
    )

    cfg.ensure_dirs()
    checks.append(
        Check(
            name="state dir",
            ok=cfg.state_dir.is_dir(),
            detail=str(cfg.state_dir),
            severity="info",
        )
    )

    backend = get_backend(cfg)
    avail = backend.available()
    if cfg.sim.backend == "stub":
        sim_ok = True
        sim_detail = "stub (synthetic evidence)"
        sim_sev = "info"
    elif avail:
        sim_ok = True
        sim_detail = "available"
        sim_sev = "info"
    else:
        sim_ok = False
        sim_detail = (
            "unavailable — strict_evidence will mark T3+ UNAVAILABLE (no stub PASS)"
            if cfg.funnel.strict_evidence
            else "unavailable — may fall back depending on config"
        )
        sim_sev = "warn"
    checks.append(
        Check(
            name=f"sim backend ({cfg.sim.backend})",
            ok=sim_ok,
            detail=sim_detail,
            severity=sim_sev,
        )
    )

    traces = cfg.resolved_traces_dir()
    n_traces = len(list(traces.glob("*"))) if traces and traces.is_dir() else 0
    checks.append(
        Check(
            name="traces_dir",
            ok=n_traces > 0 or cfg.sim.backend == "stub",
            detail=f"{n_traces} files under {traces}" if traces else "not configured",
            severity="warn" if cfg.sim.backend == "champsim" and n_traces == 0 else "info",
        )
    )

    pyc = cfg.resolved_pycircuit_root()
    pyc_ok = pyc.is_dir() and (pyc / "compiler" / "frontend" / "pycircuit").is_dir()
    checks.append(
        Check(
            name="pyCircuit",
            ok=pyc_ok,
            detail=str(pyc) if pyc_ok else f"missing {pyc} — run tools/setup_pycircuit.sh",
            severity="warn",
        )
    )

    for tool in ("verilator", "iverilog", "yosys"):
        path = shutil.which(tool)
        checks.append(
            Check(
                name=tool,
                ok=bool(path) or tool == "yosys",
                detail=path or "not on PATH",
                severity="info" if tool == "yosys" else ("warn" if not path else "info"),
            )
        )

    checks.append(
        Check(
            name="Tier6 signoff",
            ok=True,
            detail="planned / reserved (sign.enabled=false)"
            if not cfg.sign.enabled
            else "enabled but backend not implemented",
            severity="info",
        )
    )

    demo = ROOT / "specs" / "demo.md"
    checks.append(
        Check(
            name="demo problem package",
            ok=demo.is_file(),
            detail=str(demo) if demo.is_file() else "specs/demo.md missing",
            severity="warn",
        )
    )

    try:
        import cursor_sdk  # noqa: F401

        checks.append(
            Check(name="cursor-sdk", ok=True, detail="importable", severity="info")
        )
    except ImportError:
        checks.append(
            Check(
                name="cursor-sdk",
                ok=False,
                detail="not installed — run: uv sync",
                severity="error",
            )
        )

    checks.append(
        Check(
            name="funnel.strict_evidence",
            ok=True,
            detail=str(cfg.funnel.strict_evidence),
            severity="info",
        )
    )

    return checks
