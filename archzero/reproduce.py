"""Verify / lightly replay an exported campaign bundle."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from archzero.config import FactoryConfig
from archzero.sim.backend import SimRequest
from archzero.sim.stub import StubSimBackend


def reproduce_bundle(cfg: FactoryConfig, bundle: Path) -> dict[str, Any]:
    root = bundle if bundle.is_dir() else bundle.parent
    manifest_path = root / "manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError(f"missing manifest.json under {root}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    checks: dict[str, Any] = {
        "manifest": True,
        "problem": (root / "problem.md").is_file(),
        "candidates": (root / "candidates.json").is_file(),
        "report": (root / "REPORT.md").is_file(),
        "git_sha": manifest.get("git_sha"),
        "sim_backend": manifest.get("sim_backend"),
        "tool_versions": manifest.get("tool_versions"),
    }

    # Offline stub replay for each artifact workdir with sim_knobs.json
    stub = StubSimBackend(cfg)
    replays = []
    arts = root / "artifacts"
    if arts.is_dir():
        for cand_dir in sorted(p for p in arts.iterdir() if p.is_dir()):
            knobs = cand_dir / "sim_knobs.json"
            if not knobs.is_file():
                continue
            sim = stub.run(
                SimRequest(
                    candidate_id=cand_dir.name,
                    workdir=cand_dir,
                    patch_hint="reproduce",
                    suite="small",
                )
            )
            replays.append(
                {
                    "id": cand_dir.name,
                    "ok": sim.ok,
                    "miss_reduction": sim.metrics.get("miss_reduction"),
                    "evidence": sim.metrics.get("evidence"),
                }
            )
    checks["stub_replays"] = replays
    checks["ok"] = checks["problem"] and checks["candidates"]
    return checks
