"""Semantic-ish candidate dedup (token Jaccard; no embedding dependency)."""

from __future__ import annotations

import re
from dataclasses import dataclass

from archzero.models import Candidate

_TOKEN = re.compile(r"[a-z0-9]+", re.I)


def tokenize(text: str) -> set[str]:
    return {t.lower() for t in _TOKEN.findall(text or "") if len(t) > 2}


def jaccard(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


@dataclass
class DedupResult:
    kept: list[Candidate]
    dropped: list[tuple[Candidate, Candidate, float]]  # dropped, near, score


def dedup_candidates(
    candidates: list[Candidate],
    *,
    threshold: float = 0.85,
) -> DedupResult:
    """Drop near-duplicates by title+mechanism token Jaccard."""
    kept: list[Candidate] = []
    dropped: list[tuple[Candidate, Candidate, float]] = []
    kept_toks: list[set[str]] = []
    for c in candidates:
        tok = tokenize(f"{c.title} {c.mechanism}")
        near_i = -1
        near_score = 0.0
        for i, kt in enumerate(kept_toks):
            score = jaccard(tok, kt)
            if score >= threshold and score > near_score:
                near_i = i
                near_score = score
        if near_i >= 0:
            dropped.append((c, kept[near_i], near_score))
        else:
            kept.append(c)
            kept_toks.append(tok)
    return DedupResult(kept=kept, dropped=dropped)
