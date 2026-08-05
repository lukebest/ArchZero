"""Helpers to attach LLM / tool provenance onto TierResult."""

from __future__ import annotations

import hashlib
from typing import Any

from archzero.models import EvidenceLevel, TierResult, UsagePool


def prompt_hash(*parts: str) -> str:
    h = hashlib.sha256()
    for p in parts:
        h.update((p or "").encode("utf-8", errors="replace"))
        h.update(b"\0")
    return h.hexdigest()[:16]


def apply_llm_provenance(
    result: TierResult,
    llm: Any,
    *,
    evidence: EvidenceLevel | None = None,
    prompt: str | None = None,
) -> TierResult:
    """Copy last routed model info from an LLM client if present."""
    last = getattr(llm, "last_routed", None)
    if last is not None:
        result.model_id = getattr(last, "model_id", None) or result.model_id
        pool = getattr(last, "pool", None)
        if isinstance(pool, UsagePool):
            result.pool = pool
        elif isinstance(pool, str):
            try:
                result.pool = UsagePool(pool)
            except ValueError:
                pass
        result.downgraded = bool(getattr(last, "downgraded", False))
    if prompt:
        result.prompt_hash = prompt_hash(prompt)
    if evidence is not None:
        result.evidence = evidence
    return result
