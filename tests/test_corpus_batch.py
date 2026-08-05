"""Corpus batch offline eval scaffold."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from archzero.corpus.batch_eval import evaluate_corpus_batch
from archzero.corpus.ingest import add_paper_pdf
from archzero.models import Tier


@pytest.mark.asyncio
async def test_batch_eval_scaffold(tmp_cfg, tmp_path):
    root = tmp_path / "corpus"
    root.mkdir()
    paper = root / "papers" / "stub-a"
    paper.mkdir(parents=True)
    (paper / "problem.md").write_text(
        """---
id: pp-stub-a
title: "Stub A"
---

# Stub A

### REQ-001 — Miss reduction

Shall reduce MPKI by ≥ 15%.

### ACC-001 — Analytic

`measurable: true`

Predicted MPKI reduction ≥ 15%; Magic Gap ≤ 2×.
""",
        encoding="utf-8",
    )
    (root / "manifest.json").write_text(
        json.dumps(
            {
                "status": "scaffold",
                "target_size": 95,
                "entries": [
                    {
                        "id": "stub-a",
                        "title": "Stub A",
                        "spec": "papers/stub-a/problem.md",
                        "family": "prefetch",
                        "pdf": None,
                        "evaluated": False,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    # Harden: reject non-pdf
    bad = tmp_path / "note.txt"
    bad.write_text("hello")
    with pytest.raises(ValueError, match="not a PDF"):
        add_paper_pdf(entry_id="x", pdf_path=bad, corpus_root=root)

    data = await evaluate_corpus_batch(
        tmp_cfg, corpus_root=root, through=Tier.T2, limit=1
    )
    assert data["ok"]
    assert data["success_rate"] is None
    assert data["n_entries"] == 1
    assert data["results"][0]["ok"] is True
