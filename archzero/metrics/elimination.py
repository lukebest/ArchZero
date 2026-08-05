"""Causal failure-elimination metrics between source and follow-up campaigns."""

from __future__ import annotations

from collections import Counter
from typing import Any

from archzero.models import FailureRecord
from archzero.store.db import Store


def snapshot_failures(failures: list[FailureRecord]) -> dict[str, Any]:
    by_kind = dict(Counter(f.kind.value for f in failures))
    by_tier_kind = dict(
        Counter(f"{f.tier.value}/{f.kind.value}" for f in failures)
    )
    return {
        "failure_ids": [f.id for f in failures],
        "by_kind": by_kind,
        "by_tier_kind": by_tier_kind,
        "n": len(failures),
    }


def _msg_key(f: FailureRecord) -> str:
    return f"{f.tier.value}|{f.kind.value}|{(f.message or '')[:80]}"


def compute_elimination(
    store: Store,
    *,
    source_campaign_id: str,
    followup_campaign_id: str,
) -> dict[str, Any]:
    """Compare failure taxonomy before/after a follow-up campaign.

    A kind is *eliminated* when baseline count > 0 and follow-up count == 0.
    A kind is *reduced* when follow-up count < baseline but still > 0.
    Per-fingerprint elimination uses tier|kind|message[:80].
    """
    src = store.list_failures(campaign_id=source_campaign_id)
    dst = store.list_failures(campaign_id=followup_campaign_id)
    base_kind = Counter(f.kind.value for f in src)
    follow_kind = Counter(f.kind.value for f in dst)
    kinds = sorted(set(base_kind) | set(follow_kind))

    eliminated: list[str] = []
    reduced: list[str] = []
    persisted: list[str] = []
    introduced: list[str] = []
    for k in kinds:
        a, b = base_kind.get(k, 0), follow_kind.get(k, 0)
        if a > 0 and b == 0:
            eliminated.append(k)
        elif a > 0 and 0 < b < a:
            reduced.append(k)
        elif a > 0 and b >= a:
            persisted.append(k)
        elif a == 0 and b > 0:
            introduced.append(k)

    base_fp = {_msg_key(f) for f in src}
    follow_fp = {_msg_key(f) for f in dst}
    fp_eliminated = sorted(base_fp - follow_fp)
    fp_persisted = sorted(base_fp & follow_fp)

    n_base_kinds = sum(1 for k, n in base_kind.items() if n > 0)
    rate = (len(eliminated) / n_base_kinds) if n_base_kinds else None

    return {
        "source_campaign_id": source_campaign_id,
        "followup_campaign_id": followup_campaign_id,
        "baseline": snapshot_failures(src),
        "followup": snapshot_failures(dst),
        "kinds_eliminated": eliminated,
        "kinds_reduced": reduced,
        "kinds_persisted": persisted,
        "kinds_introduced": introduced,
        "fingerprints_eliminated": len(fp_eliminated),
        "fingerprints_persisted": len(fp_persisted),
        "kind_elimination_rate": rate,
    }
