"""Load benchmark suite definitions and resolve traces_dir."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from archzero.config import ROOT, FactoryConfig

DEFAULT_SUITES: dict[str, Any] = {
    "small": {"traces": ["demo_a.champsimtrace.xz", "demo_b.champsimtrace.xz"]},
    "full": {
        "traces": [
            "demo_a.champsimtrace.xz",
            "demo_b.champsimtrace.xz",
            "demo_c.champsimtrace.xz",
        ]
    },
}


def load_suites(cfg: FactoryConfig) -> dict[str, Any]:
    path = None
    if cfg.sim.suites_file:
        path = Path(cfg.sim.suites_file)
    else:
        candidate = ROOT / "benchmarks" / "suites.yaml"
        if candidate.is_file():
            path = candidate
    if path and path.is_file():
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return data.get("suites") or data or DEFAULT_SUITES
    return DEFAULT_SUITES


def resolve_traces(cfg: FactoryConfig, suite: str) -> list[Path]:
    suites = load_suites(cfg)
    names = (suites.get(suite) or suites.get("small") or {}).get("traces") or []
    traces_dir = cfg.resolved_traces_dir()
    if traces_dir is None:
        return []
    out: list[Path] = []
    for name in names:
        p = traces_dir / name
        if p.is_file():
            out.append(p)
    return out
