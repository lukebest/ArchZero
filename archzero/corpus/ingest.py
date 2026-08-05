"""Register real paper PDFs into the corpus scaffold (no fake success rates)."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from archzero.corpus.status import default_corpus_root

ALLOWED_LABELS = {"reproduce", "equivalent", "alternative", "defective", None}


def _load_manifest(root: Path) -> dict[str, Any]:
    path = root / "manifest.json"
    if not path.is_file():
        raise FileNotFoundError(f"missing {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _save_manifest(root: Path, data: dict[str, Any]) -> None:
    (root / "manifest.json").write_text(
        json.dumps(data, indent=2) + "\n", encoding="utf-8"
    )


def add_paper_pdf(
    *,
    entry_id: str,
    pdf_path: Path,
    title: str | None = None,
    family: str = "unclassified",
    cleanroom_label: str | None = None,
    corpus_root: Path | None = None,
    copy: bool = True,
) -> dict[str, Any]:
    """Attach a real PDF to a corpus entry (creates entry if missing).

    Does not mark the corpus complete or compute success_rate.
    """
    if cleanroom_label not in ALLOWED_LABELS:
        raise ValueError(
            f"cleanroom_label must be one of "
            f"{sorted(x for x in ALLOWED_LABELS if x)}"
        )
    pdf_path = Path(pdf_path)
    if not pdf_path.is_file():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")
    head = pdf_path.read_bytes()[:5]
    if head != b"%PDF-":
        raise ValueError(f"not a PDF (missing %PDF- magic): {pdf_path}")

    root = corpus_root or default_corpus_root()
    data = _load_manifest(root)
    entries: list[dict[str, Any]] = list(data.get("entries") or [])
    entry = next((e for e in entries if e.get("id") == entry_id), None)
    created = False
    if entry is None:
        entry = {
            "id": entry_id,
            "title": title or entry_id,
            "spec": f"papers/{entry_id}/problem.md",
            "pdf": None,
            "family": family,
            "expected_label": None,
            "cleanroom_label": None,
            "quantitative": False,
            "evaluated": False,
            "notes": "ingested PDF — still scaffold until evaluated",
        }
        entries.append(entry)
        created = True
        paper_dir = root / "papers" / entry_id
        paper_dir.mkdir(parents=True, exist_ok=True)
        spec = paper_dir / "problem.md"
        if not spec.exists():
            spec.write_text(
                f"---\nid: pp-corpus-{entry_id}\ntitle: \"{entry.get('title')}\"\n"
                f"corpus_entry: \"{entry_id}\"\n---\n\n# {entry.get('title')}\n\n"
                "### REQ-001 — Placeholder\n\n"
                "Replace with NDF-lite clauses before running clean-room evaluation.\n",
                encoding="utf-8",
            )

    dest_rel = f"papers/{entry_id}/paper.pdf"
    dest = root / dest_rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    if copy:
        shutil.copy2(pdf_path, dest)
        entry["pdf"] = dest_rel
    else:
        entry["pdf"] = str(pdf_path.resolve())
    entry["pdf_real"] = True
    if title:
        entry["title"] = title
    if family:
        entry["family"] = family
    if cleanroom_label is not None:
        entry["cleanroom_label"] = cleanroom_label
        entry["expected_label"] = cleanroom_label
    entry["notes"] = "real PDF attached — evaluate before claiming success_rate"
    data["entries"] = entries
    if data.get("status") != "complete":
        data["status"] = "scaffold"
    _save_manifest(root, data)
    return {
        "ok": True,
        "created": created,
        "entry_id": entry_id,
        "pdf": entry["pdf"],
        "cleanroom_label": entry.get("cleanroom_label"),
        "status": data.get("status"),
        "message": "PDF registered; corpus remains scaffold until evaluated.",
    }
