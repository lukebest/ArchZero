"""Read corpus/manifest.json and report scaffold status (no fake success rates)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from archzero.config import ROOT


def default_corpus_root() -> Path:
    return ROOT / "corpus"


def corpus_status(corpus_root: Path | None = None) -> dict[str, Any]:
    root = corpus_root or default_corpus_root()
    manifest_path = root / "manifest.json"
    if not manifest_path.is_file():
        return {
            "ok": False,
            "status": "missing",
            "path": str(root),
            "message": "corpus/manifest.json not found",
        }
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    entries = list(data.get("entries") or [])
    target = int(data.get("target_size") or 95)
    evaluated = sum(1 for e in entries if e.get("evaluated"))
    status = str(data.get("status") or "scaffold")
    # Never invent a numeric success rate on scaffold data
    success_rate = None
    if status == "complete" and evaluated > 0:
        ok = sum(1 for e in entries if e.get("success"))
        success_rate = ok / evaluated

    return {
        "ok": True,
        "status": status,
        "path": str(root),
        "description": data.get("description"),
        "entries": len(entries),
        "target_size": target,
        "coverage": f"{len(entries)}/{target}",
        "evaluated": evaluated,
        "success_rate": success_rate,
        "disclaimer": data.get("disclaimer")
        or "Scaffold only — not a 95-paper evaluation result.",
        "entry_ids": [e.get("id") for e in entries],
        "label_schema": data.get("label_schema") or [],
        "with_pdf": sum(1 for e in entries if e.get("pdf")),
        "pdf_real": sum(1 for e in entries if e.get("pdf_real")),
        "evaluation_protocol": data.get("evaluation_protocol"),
    }
