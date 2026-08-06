"""Import real PDFs from an OKF / LLM wiki `raw/` tree into ArchZero corpus.

Only PDFs are registered. Markdown summaries are never copied into clean-room
problem packages (to avoid leaking digested claims).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from archzero.corpus.ingest import add_paper_pdf
from archzero.corpus.status import default_corpus_root


def _slug(name: str) -> str:
    stem = Path(name).stem
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", stem).strip("-").lower()
    return (slug or "paper")[:80]


def discover_wiki_pdfs(wiki_root: Path) -> list[Path]:
    """Find PDFs under wiki_root/raw (preferred) or wiki_root recursively."""
    root = Path(wiki_root)
    if not root.is_dir():
        raise FileNotFoundError(f"wiki root not found: {root}")
    preferred = root / "raw"
    base = preferred if preferred.is_dir() else root
    return sorted(p for p in base.rglob("*.pdf") if p.is_file())


def import_wiki_pdfs(
    wiki_root: Path,
    *,
    corpus_root: Path | None = None,
    limit: int | None = None,
    family: str = "unclassified",
    dry_run: bool = False,
) -> dict[str, Any]:
    """Register wiki raw PDFs into corpus scaffold.

    Does not set cleanroom labels or success_rate. Skips non-PDF paths.
    """
    pdfs = discover_wiki_pdfs(wiki_root)
    if limit is not None:
        pdfs = pdfs[: max(0, limit)]
    root = corpus_root or default_corpus_root()
    results: list[dict[str, Any]] = []
    for pdf in pdfs:
        entry_id = _slug(pdf.name)
        if dry_run:
            results.append(
                {
                    "ok": True,
                    "dry_run": True,
                    "entry_id": entry_id,
                    "pdf": str(pdf),
                }
            )
            continue
        try:
            st = add_paper_pdf(
                entry_id=entry_id,
                pdf_path=pdf,
                title=pdf.stem,
                family=family,
                corpus_root=root,
            )
            st["source"] = str(pdf)
            results.append(st)
        except Exception as exc:  # noqa: BLE001
            results.append(
                {
                    "ok": False,
                    "entry_id": entry_id,
                    "pdf": str(pdf),
                    "error": str(exc),
                }
            )
    n_ok = sum(1 for r in results if r.get("ok"))
    return {
        "ok": True,
        "wiki_root": str(Path(wiki_root).resolve()),
        "corpus": str(root.resolve()),
        "n_found": len(pdfs),
        "n_imported": n_ok,
        "dry_run": dry_run,
        "disclaimer": (
            "Raw PDFs only — wiki markdown summaries were not imported. "
            "Corpus remains scaffold; no success_rate invented."
        ),
        "results": results,
    }
