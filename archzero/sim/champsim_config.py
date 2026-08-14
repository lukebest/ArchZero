"""Emit ChampSim config + mechanism-patch scaffold from knobs / family.

This does not compile a custom ChampSim binary. It writes auditable artifacts
(`champsim_config.json`, `MECHANISM_PATCH.md`, `champsim_patch.json`) so Tier3/4
runs have an explicit mechanism→simulator contract before empirics.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from archzero.sim.families import champsim_hosts, family_domain

_FAMILY_MODULE = {
    "prefetch": "prefetcher",
    "replacement": "replacement",
    "bypass": "cache",
    "other": "ooo_cpu",
    "unclassified": "ooo_cpu",
}


def build_champsim_config(
    *,
    family: str | None,
    knobs: dict[str, Any],
    title: str = "",
) -> dict[str, Any]:
    """Minimal ChampSim-style JSON config reflecting mechanism intent."""
    fam = (family or knobs.get("family") or "unclassified").lower()
    if not champsim_hosts(fam):
        kind = family_domain(fam)
        return {
            "archzero_scaffold": True,
            "inapplicable": True,
            "executable_name": "champsim",
            "mechanism": {
                "title": title,
                "family": fam,
                "module": None,
                "domain": kind,
            },
            "ooo_cpu": [],
            "notes": (
                f"ChampSim cannot host family={fam!r} (domain={kind}). "
                "ChampSim is a CPU / cache simulator; this family needs the "
                f"{kind} analytic backend, not an L2 prefetcher module."
            ),
        }
    module = _FAMILY_MODULE.get(fam, "ooo_cpu")
    entries = int(knobs.get("table_entries") or knobs.get("entries") or 256)
    degree = int(knobs.get("prefetch_degree") or knobs.get("degree") or 2)
    return {
        "archzero_scaffold": True,
        "executable_name": "champsim",
        "block_size": 64,
        "page_size": 4096,
        "heartbeat_frequency": 10_000_000,
        "mechanism": {
            "title": title,
            "family": fam,
            "module": module,
            "table_entries": entries,
            "prefetch_degree": degree if fam == "prefetch" else None,
            "miss_reduction_target": knobs.get("miss_reduction"),
            "extra_bw": knobs.get("extra_bw"),
            "area_mm2": knobs.get("area"),
        },
        "ooo_cpu": [
            {
                "name": "cpu0",
                "frequency": 4000,
                "L1I": {
                    "sets": 64,
                    "ways": 8,
                    "rq_size": 64,
                    "wq_size": 64,
                    "pq_size": 32,
                    "mshr_size": 8,
                    "latency": 4,
                },
                "L1D": {
                    "sets": 64,
                    "ways": 8,
                    "rq_size": 64,
                    "wq_size": 64,
                    "pq_size": 32,
                    "mshr_size": 16,
                    "latency": 4,
                },
                "L2C": {
                    "sets": 1024,
                    "ways": 16,
                    "rq_size": 32,
                    "wq_size": 32,
                    "pq_size": 16,
                    "mshr_size": 32,
                    "latency": 10,
                    "prefetcher": "no" if fam != "prefetch" else "archzero_filter",
                    "replacement": "lru" if fam != "replacement" else "archzero_rrpv",
                },
            }
        ],
        "notes": (
            "Scaffold config for ArchZero. Replace archzero_* modules with real "
            "ChampSim prefetcher/replacement sources and rebuild before empirics."
        ),
    }


def render_patch_markdown(
    *,
    family: str | None,
    knobs: dict[str, Any],
    title: str,
    config_name: str = "champsim_config.json",
) -> str:
    fam = (family or knobs.get("family") or "unclassified").lower()
    if not champsim_hosts(fam):
        kind = family_domain(fam)
        return (
            f"# ChampSim mechanism patch scaffold\n\n"
            f"- **Title:** {title or '(untitled)'}\n"
            f"- **Family:** `{fam}`\n"
            f"- **Domain:** `{kind}`\n"
            f"- **Inapplicable:** ChampSim cannot host this family.\n\n"
            "ChampSim is a CPU / cache simulator. NoC, dataflow, and wafer-scale "
            "families have no L2 prefetcher or replacement module to patch. Use the "
            f"`{kind}` analytic backend instead of compiling ChampSim.\n\n"
            "## Knobs\n\n"
            "```json\n"
            f"{json.dumps(knobs, indent=2)}\n"
            "```\n"
        )
    module = _FAMILY_MODULE.get(fam, "ooo_cpu")
    return (
        f"# ChampSim mechanism patch scaffold\n\n"
        f"- **Title:** {title or '(untitled)'}\n"
        f"- **Family:** `{fam}`\n"
        f"- **Target module:** `{module}`\n"
        f"- **Config:** `{config_name}`\n\n"
        "## Intent\n\n"
        "Emit knobs into a ChampSim JSON config and document the source files that "
        "must be patched/rebuilt for a real empirical run.\n\n"
        "## Knobs\n\n"
        "```json\n"
        f"{json.dumps(knobs, indent=2)}\n"
        "```\n\n"
        "## Rebuild steps\n\n"
        "1. Apply family-specific prefetcher/replacement sources under ChampSim tree.\n"
        "2. Point `champsim_config.json` L2C module names at those sources.\n"
        "3. `JOBS=2 bash tools/setup_champsim.sh` (or rebuild binary).\n"
        "4. Re-run Tier3 with `sim.backend = champsim`.\n\n"
        "_This file is scaffolding — not evidence of a compiled mechanism._\n"
    )


def write_champsim_scaffold(
    workdir: Path,
    *,
    family: str | None = None,
    knobs: dict[str, Any] | None = None,
    title: str = "",
    overwrite: bool = False,
) -> dict[str, Any]:
    """Write config + patch artifacts under workdir. Returns paths / summary."""
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    knobs = dict(knobs or {})
    knob_path = workdir / "sim_knobs.json"
    if knob_path.is_file() and not knobs:
        try:
            knobs.update(json.loads(knob_path.read_text(encoding="utf-8")))
        except json.JSONDecodeError:
            pass

    config = build_champsim_config(family=family, knobs=knobs, title=title)
    config_path = workdir / "champsim_config.json"
    if overwrite or not config_path.exists():
        config_path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")

    inapplicable = bool(config.get("inapplicable"))
    patch_meta = {
        "family": (family or knobs.get("family") or "unclassified"),
        "module": config["mechanism"]["module"],
        "config": "champsim_config.json",
        "knobs": knobs,
        "scaffold": True,
        "inapplicable": inapplicable,
    }
    patch_json = workdir / "champsim_patch.json"
    if overwrite or not patch_json.exists():
        patch_json.write_text(json.dumps(patch_meta, indent=2) + "\n", encoding="utf-8")

    md_path = workdir / "MECHANISM_PATCH.md"
    if overwrite or not md_path.exists():
        md_path.write_text(
            render_patch_markdown(family=family, knobs=knobs, title=title),
            encoding="utf-8",
        )

    return {
        "ok": True,
        "config": str(config_path),
        "patch_json": str(patch_json),
        "patch_md": str(md_path),
        "family": patch_meta["family"],
        "module": patch_meta["module"],
        "inapplicable": inapplicable,
    }
