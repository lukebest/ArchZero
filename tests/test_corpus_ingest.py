"""Corpus real-PDF registration."""

from __future__ import annotations

from pathlib import Path

from archzero.corpus.ingest import add_paper_pdf
from archzero.corpus.status import corpus_status


def test_add_paper_pdf(tmp_path):
    # Fresh corpus root
    root = tmp_path / "corpus"
    root.mkdir()
    (root / "manifest.json").write_text(
        '{"status":"scaffold","target_size":95,"entries":[]}\n', encoding="utf-8"
    )
    pdf = tmp_path / "real.pdf"
    pdf.write_bytes(b"%PDF-1.1\n%%EOF\n")
    st = add_paper_pdf(
        entry_id="paper-a",
        pdf_path=pdf,
        title="Real Paper A",
        family="prefetch",
        cleanroom_label="equivalent",
        corpus_root=root,
    )
    assert st["ok"]
    assert st["status"] == "scaffold"
    assert (root / "papers" / "paper-a" / "paper.pdf").is_file()
    status = corpus_status(root)
    assert status["entries"] == 1
    assert status.get("pdf_real", 0) == 1
    assert status["success_rate"] is None
