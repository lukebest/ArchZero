"""Verify / lightly replay an exported campaign bundle."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from archzero.config import FactoryConfig
from archzero.sim.backend import SimRequest
from archzero.sim.families import CACHE, family_domain
from archzero.sim.headlines import candidate_headlines
from archzero.sim.stub import StubSimBackend
from archzero.spec.acc_parse import parse_acceptance_thresholds
from archzero.spec.ndf import load_problem_package


def _bundle_domain(root: Path, manifest: dict[str, Any], families: dict[str, str]) -> str:
    raw = str(manifest.get("domain") or "").strip().lower()
    if raw in {"cache", "noc", "dataflow", "wafer"}:
        return raw
    problem = root / "problem.md"
    if problem.is_file():
        try:
            return parse_acceptance_thresholds(load_problem_package(problem)).domain
        except Exception:  # noqa: BLE001
            pass
    for fam in families.values():
        kind = family_domain(fam)
        if kind != CACHE:
            return kind
    return CACHE


def _candidate_families(root: Path) -> dict[str, str]:
    path = root / "candidates.json"
    if not path.is_file():
        return {}
    try:
        index = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    out: dict[str, str] = {}
    for entry in index or []:
        cid = str(entry.get("id") or "")
        if cid and entry.get("family"):
            out[cid] = str(entry["family"])
    return out


def _replay_row(
    cand_id: str,
    sim,
    *,
    domain: str,
    family: str | None,
) -> dict[str, Any]:
    headlines = candidate_headlines(sim.metrics, family=family)
    row: dict[str, Any] = {
        "id": cand_id,
        "ok": sim.ok,
        "domain": domain,
        "headlines": headlines,
        "evidence": sim.metrics.get("evidence"),
    }
    if domain == CACHE and sim.metrics.get("miss_reduction") is not None:
        row["miss_reduction"] = sim.metrics.get("miss_reduction")
    return row


def reproduce_bundle(cfg: FactoryConfig, bundle: Path) -> dict[str, Any]:
    root = bundle if bundle.is_dir() else bundle.parent
    manifest_path = root / "manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError(f"missing manifest.json under {root}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    families = _candidate_families(root)
    domain = _bundle_domain(root, manifest, families)
    checks: dict[str, Any] = {
        "manifest": True,
        "problem": (root / "problem.md").is_file(),
        "candidates": (root / "candidates.json").is_file(),
        "report": (root / "REPORT.md").is_file(),
        "git_sha": manifest.get("git_sha"),
        "sim_backend": manifest.get("sim_backend"),
        "tool_versions": manifest.get("tool_versions"),
        "domain": domain,
    }

    stub = StubSimBackend(cfg)
    replays = []
    arts = root / "artifacts"
    if arts.is_dir():
        for cand_dir in sorted(p for p in arts.iterdir() if p.is_dir()):
            knobs = cand_dir / "sim_knobs.json"
            if not knobs.is_file():
                continue
            family = families.get(cand_dir.name)
            try:
                loaded = json.loads(knobs.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                loaded = {}
            if isinstance(loaded, dict):
                family = family or loaded.get("family")
                knob_domain = str(loaded.get("domain") or "")
            else:
                knob_domain = ""
            replay_domain = (
                knob_domain
                if knob_domain in {"cache", "noc", "dataflow", "wafer"}
                else domain
            )
            if family_domain(family) != CACHE:
                replay_domain = family_domain(family)
            sim = stub.run(
                SimRequest(
                    candidate_id=cand_dir.name,
                    workdir=cand_dir,
                    patch_hint="reproduce",
                    suite="small",
                    meta={"domain": replay_domain, "family": family},
                )
            )
            replays.append(
                _replay_row(
                    cand_dir.name, sim, domain=replay_domain, family=family
                )
            )
    checks["stub_replays"] = replays
    checks["ok"] = checks["problem"] and checks["candidates"]
    return checks
