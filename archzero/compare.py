"""Compare two Idea Factory campaigns (funnel + failure taxonomy)."""

from __future__ import annotations

from collections import Counter
from typing import Any

from archzero.config import FactoryConfig
from archzero.metrics.elimination import compute_elimination
from archzero.models import Tier, Verdict
from archzero.store.db import Store


def _funnel_stats(store: Store, campaign_id: str) -> list[dict[str, Any]]:
    cands = store.list_candidates(campaign_id=campaign_id)
    rows: list[dict[str, Any]] = []
    for tier in Tier:
        entered = passed = failed = 0
        for c in cands:
            for tr in c.tier_history:
                if tr.tier != tier:
                    continue
                entered += 1
                if tr.verdict == Verdict.PASS:
                    passed += 1
                elif tr.verdict == Verdict.FAIL:
                    failed += 1
        rows.append(
            {
                "tier": tier.value,
                "entered": entered,
                "passed": passed,
                "failed": failed,
            }
        )
    return rows


def _failure_counts(store: Store, campaign_id: str) -> dict[str, int]:
    return dict(Counter(f.kind.value for f in store.list_failures(campaign_id=campaign_id)))


def _survivors(store: Store, campaign_id: str) -> int:
    return sum(1 for c in store.list_candidates(campaign_id=campaign_id) if c.status == "active")


def compare_campaigns(cfg: FactoryConfig, a: str, b: str) -> dict[str, Any]:
    store = Store(cfg.db_path)
    ca, cb = store.get_campaign(a), store.get_campaign(b)
    if ca is None:
        raise ValueError(f"unknown campaign: {a}")
    if cb is None:
        raise ValueError(f"unknown campaign: {b}")

    fa, fb = _funnel_stats(store, a), _funnel_stats(store, b)
    by_tier = []
    for ta, tb in zip(fa, fb, strict=True):
        by_tier.append(
            {
                "tier": ta["tier"],
                "a": ta,
                "b": tb,
                "pass_delta": ta["passed"] - tb["passed"],
                "fail_delta": ta["failed"] - tb["failed"],
            }
        )

    fail_a, fail_b = _failure_counts(store, a), _failure_counts(store, b)
    kinds = sorted(set(fail_a) | set(fail_b))
    fail_rows = [
        {
            "kind": k,
            "a": fail_a.get(k, 0),
            "b": fail_b.get(k, 0),
            "delta": fail_a.get(k, 0) - fail_b.get(k, 0),
        }
        for k in kinds
    ]

    elimination = compute_elimination(
        store, source_campaign_id=a, followup_campaign_id=b
    )

    return {
        "a": {
            "id": ca.id,
            "name": ca.name,
            "through": ca.through_tier.value,
            "status": ca.status,
            "n_candidates": len(store.list_candidates(campaign_id=a)),
            "survivors": _survivors(store, a),
            "usage": store.usage_totals(a),
        },
        "b": {
            "id": cb.id,
            "name": cb.name,
            "through": cb.through_tier.value,
            "status": cb.status,
            "n_candidates": len(store.list_candidates(campaign_id=b)),
            "survivors": _survivors(store, b),
            "usage": store.usage_totals(b),
        },
        "funnel": by_tier,
        "failures": fail_rows,
        "elimination": elimination,
    }


def format_compare_text(data: dict[str, Any]) -> str:
    lines = [
        "# Compare campaigns",
        f"- A: `{data['a']['id']}` {data['a']['name']} (survivors={data['a']['survivors']})",
        f"- B: `{data['b']['id']}` {data['b']['name']} (survivors={data['b']['survivors']})",
        "",
        "| Tier | A pass/enter | B pass/enter | Δpass | Δfail |",
        "|------|-------------:|-------------:|------:|------:|",
    ]
    for row in data["funnel"]:
        a, b = row["a"], row["b"]
        lines.append(
            f"| {row['tier']} | {a['passed']}/{a['entered']} | {b['passed']}/{b['entered']} "
            f"| {row['pass_delta']:+d} | {row['fail_delta']:+d} |"
        )
    lines += ["", "## Failure taxonomy", "", "| Kind | A | B | Δ |", "|------|--:|--:|--:|"]
    for row in data["failures"]:
        lines.append(
            f"| {row['kind']} | {row['a']} | {row['b']} | {row['delta']:+d} |"
        )
    if not data["failures"]:
        lines.append("| — | 0 | 0 | 0 |")
    elim = data.get("elimination") or {}
    lines += [
        "",
        "## Failure elimination (A→B)",
        f"- kinds eliminated: {', '.join(elim.get('kinds_eliminated') or []) or '—'}",
        f"- kinds reduced: {', '.join(elim.get('kinds_reduced') or []) or '—'}",
        f"- kind_elimination_rate: {elim.get('kind_elimination_rate')}",
    ]
    return "\n".join(lines) + "\n"
