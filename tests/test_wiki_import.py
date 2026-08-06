"""Wiki raw PDF → corpus import (no summaries)."""

from __future__ import annotations

import json

from archzero.corpus.wiki_import import discover_wiki_pdfs, import_wiki_pdfs


def test_import_wiki_pdfs_dry_and_real(tmp_path):
    wiki = tmp_path / "wiki"
    raw = wiki / "raw" / "papers"
    raw.mkdir(parents=True)
    pdf = raw / "FlashAttention_Demo.pdf"
    pdf.write_bytes(b"%PDF-1.4\n%PDF-stub\n")
    (wiki / "papers").mkdir()
    (wiki / "papers" / "flashattention.md").write_text(
        "---\ntitle: leak\n---\nDo not import this summary.\n", encoding="utf-8"
    )

    found = discover_wiki_pdfs(wiki)
    assert found == [pdf]

    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "manifest.json").write_text(
        json.dumps({"status": "scaffold", "target_size": 95, "entries": []}),
        encoding="utf-8",
    )

    dry = import_wiki_pdfs(wiki, corpus_root=corpus, dry_run=True)
    assert dry["n_found"] == 1
    assert dry["n_imported"] == 1
    assert dry["results"][0]["dry_run"] is True
    assert not list((corpus / "papers").glob("**/*"))

    real = import_wiki_pdfs(wiki, corpus_root=corpus, family="prefetch")
    assert real["n_imported"] == 1
    man = json.loads((corpus / "manifest.json").read_text())
    assert man["status"] == "scaffold"
    assert man["entries"][0]["pdf_real"] is True
    assert (corpus / "papers" / man["entries"][0]["id"] / "paper.pdf").is_file()
    assert not (
        corpus / "papers" / man["entries"][0]["id"] / "flashattention.md"
    ).exists()
