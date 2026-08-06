"""Emit ChampSim config + mechanism-patch scaffold from knobs / family.

This does not compile a custom ChampSim binary. It writes auditable artifacts
(`champsim_config.json`, `MECHANISM_PATCH.md`, `champsim_patch.json`) so Tier3/4
runs have an explicit mechanism→simulator contract before empirics.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

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
        "_This file is scaffolding — not evidence of a compiled mechanism._\n\n## Source stubs\n\nSee `champsim_src/` for family-specific `.cc`/`.h` templates to copy into ChampSim.\n"
    )




def _templates_dir() -> Path:
    return Path(__file__).resolve().parent / "templates" / "champsim"


def emit_source_templates(
    workdir: Path,
    *,
    family: str | None,
    overwrite: bool = False,
) -> list[str]:
    """Copy family-specific .cc/.h scaffolds into workdir/champsim_src/."""
    fam = (family or "unclassified").lower()
    mapping = {
        "prefetch": ["archzero_filter.h", "archzero_filter.cc"],
        "replacement": ["archzero_rrpv.h", "archzero_rrpv.cc"],
    }
    names = mapping.get(fam, [])
    if not names:
        return []
    src_root = _templates_dir()
    dest_root = Path(workdir) / "champsim_src"
    dest_root.mkdir(parents=True, exist_ok=True)
    written: list[str] = []
    for name in names:
        src = src_root / name
        if not src.is_file():
            continue
        dest = dest_root / name
        if overwrite or not dest.exists():
            shutil.copy2(src, dest)
        written.append(str(dest.relative_to(workdir)))
    readme_src = src_root / "README.md"
    readme_dst = dest_root / "README.md"
    if readme_src.is_file() and (overwrite or not readme_dst.exists()):
        shutil.copy2(readme_src, readme_dst)
        written.append(str(readme_dst.relative_to(workdir)))
    return written

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

    patch_meta = {
        "family": (family or knobs.get("family") or "unclassified"),
        "module": config["mechanism"]["module"],
        "config": "champsim_config.json",
        "knobs": knobs,
        "scaffold": True,
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

    sources = emit_source_templates(
        workdir, family=str(patch_meta["family"]), overwrite=overwrite
    )

    return {
        "ok": True,
        "config": str(config_path),
        "patch_json": str(patch_json),
        "patch_md": str(md_path),
        "family": patch_meta["family"],
        "module": patch_meta["module"],
        "sources": sources,
    }
