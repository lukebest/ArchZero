"""PDF text extraction helpers."""

from __future__ import annotations

from pathlib import Path


def extract_text(pdf: Path, max_pages: int | None = None) -> str:
    from pypdf import PdfReader

    reader = PdfReader(str(pdf))
    pages = reader.pages
    if max_pages is not None:
        pages = pages[:max_pages]
    chunks: list[str] = []
    for i, page in enumerate(pages):
        try:
            t = page.extract_text() or ""
        except Exception:  # noqa: BLE001
            t = ""
        chunks.append(f"--- page {i + 1} ---\n{t}")
    return "\n\n".join(chunks)


def first_n_pages(pdf: Path, n: int = 3) -> str:
    return extract_text(pdf, max_pages=n)
