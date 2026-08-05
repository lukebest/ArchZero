"""Environment checks for architecture researchers before a campaign run."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from archzero.config import FactoryConfig
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

    personas = cfg.gauntlet_personas
    n_personas = len(list(personas.rglob("*.md"))) if personas.is_dir() else 0
    checks.append(
        Check(
            name="Gauntlet personas",
            ok=n_personas > 0,
            detail=f"{n_personas} personas under {personas}"
            if n_personas
            else f"missing directory {personas} (run: git submodule update --init)",
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
    checks.append(
        Check(
            name=f"sim backend ({cfg.sim.backend})",
            ok=avail or cfg.sim.backend == "stub",
            detail="available" if avail else "unavailable — will fall back to stub",
            severity="warn" if cfg.sim.backend != "stub" and not avail else "info",
        )
    )

    demo = Path(__file__).resolve().parents[1] / "specs" / "demo.md"
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

    return checks
