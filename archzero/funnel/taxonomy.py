"""Structured failure taxonomy for feedback into Generation."""

from __future__ import annotations

from collections import Counter

from archzero.models import Candidate, FailureKind, FailureRecord, Tier, TierResult, Verdict


def classify_message(message: str, tier: Tier) -> FailureKind:
    m = message.lower()
    if any(k in m for k in ("bandwidth", "conservation", "amdahl", "thermodynamic", "physics")):
        return FailureKind.PHYSICS
    if "novel" in m or "reproduce" in m or "prior art" in m:
        return FailureKind.NOVELTY
    if "correct" in m or "bug" in m or "assert" in m or "exception" in m:
        return FailureKind.CORRECTNESS
    if "perf" in m or "mpki" in m or "ipc" in m or "slow" in m:
        return FailureKind.PERFORMANCE
    if "area" in m or "power" in m or "feasib" in m or "timing" in m:
        return FailureKind.FEASIBILITY
    if "equiv" in m or "lec" in m or "commit" in m:
        return FailureKind.EQUIVALENCE
    if "tool" in m or "unavailable" in m or "missing binary" in m:
        return FailureKind.TOOLING
    if "budget" in m or "quota" in m:
        return FailureKind.BUDGET
    if tier == Tier.T0:
        return FailureKind.PHYSICS
    return FailureKind.UNKNOWN


def record_failure(
    candidate: Candidate,
    tier: Tier,
    message: str,
    *,
    kind: FailureKind | None = None,
    clause_refs: list[str] | None = None,
    details: dict | None = None,
) -> FailureRecord:
    f = FailureRecord(
        candidate_id=candidate.id,
        tier=tier,
        kind=kind or classify_message(message, tier),
        message=message,
        clause_refs=clause_refs or candidate.clause_refs,
        details=details or {},
    )
    candidate.failures.append(f)
    return f


def attach_result(
    candidate: Candidate,
    result: TierResult,
    *,
    fail_message: str | None = None,
) -> Candidate:
    candidate.tier_history.append(result)
    if result.verdict == Verdict.FAIL:
        candidate.status = "failed"
        record_failure(
            candidate,
            result.tier,
            fail_message or result.summary or "failed",
            clause_refs=result.clause_refs,
            details=result.metrics,
        )
    elif result.verdict == Verdict.PASS:
        candidate.status = "active"
    return candidate


def summarize_failures(failures: list[FailureRecord]) -> dict[str, int]:
    return dict(Counter(f.kind.value for f in failures))


def failures_as_signals(failures: list[FailureRecord], limit: int = 20) -> list[str]:
    out: list[str] = []
    for f in failures[:limit]:
        out.append(f"[{f.tier.value}/{f.kind.value}] {f.message}")
    return out
