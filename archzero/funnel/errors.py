"""Transient infrastructure errors vs mechanism verdicts.

A Cursor bridge ConnectError is not evidence the idea is bad. Record it as
retryable UNAVAILABLE so resume re-runs that tier instead of treating the
candidate as a hard FAIL — and so keep-N does not promote it.
"""

from __future__ import annotations

from archzero.llm.client import LLMError
from archzero.models import Candidate, EvidenceLevel, Tier, TierResult, Verdict

_INFRA_MARKERS = (
    "connecterror",
    "connection attempts failed",
    "bridge request failed",
    "connection refused",
    "connection reset",
    "all connection attempts",
    "temporarily unavailable",
    "status 429",
    "status 502",
    "status 503",
    "run failed:",
    "timed out",
    "timeout",
)

_TIER_ORDER = (Tier.T0, Tier.T1, Tier.T2, Tier.T3, Tier.T4, Tier.T5, Tier.T6)


def is_infra_error(message: str, exc: BaseException | None = None) -> bool:
    if isinstance(exc, LLMError) and exc.retryable:
        return True
    blob = f"{type(exc).__name__ if exc else ''} {message or ''} {exc or ''}".lower()
    return any(m in blob for m in _INFRA_MARKERS)


def is_retryable_result(result: TierResult) -> bool:
    return bool((result.metrics or {}).get("retryable"))


def infra_result(tier: Tier, message: str) -> TierResult:
    text = (message or "infrastructure error").strip()
    return TierResult(
        tier=tier,
        verdict=Verdict.UNAVAILABLE,
        score=0.0,
        summary=f"{text}（基础设施错误，可重试）",
        metrics={"retryable": True},
        evidence=EvidenceLevel.ANALYTIC,
    )


def strip_retryable_for_tier(candidate: Candidate, tier: Tier) -> Candidate:
    """Drop the previous retryable verdict so a new attempt can replace it."""
    candidate.tier_history = [
        t for t in candidate.tier_history if not (t.tier == tier and is_retryable_result(t))
    ]
    return candidate


def soften_infra_failures(candidate: Candidate) -> bool:
    """Rewrite already-recorded infra FAILs into retryable UNAVAILABLE."""
    changed = False
    hist: list[TierResult] = []
    for t in candidate.tier_history:
        if t.verdict == Verdict.FAIL and is_infra_error(t.summary):
            hist.append(
                t.model_copy(
                    update={
                        "verdict": Verdict.UNAVAILABLE,
                        "metrics": {**(t.metrics or {}), "retryable": True},
                    }
                )
            )
            changed = True
        else:
            hist.append(t)
    if not changed:
        return False
    candidate.tier_history = hist
    candidate.failures = [
        f for f in candidate.failures if not is_infra_error(f.message)
    ]
    candidate.status = "active"
    return True


def needs_resume(candidate: Candidate, through: Tier) -> bool:
    """True when resume should spend another LLM call on this candidate.

    Dedup leftovers (no history) and hard FAILs stay out. Retryable
    infrastructure gaps and mid-funnel stops come back in.
    """
    if candidate.hard_passed(through):
        return False
    if not candidate.tier_history:
        return False
    if any(t.verdict == Verdict.FAIL for t in candidate.tier_history):
        return False
    if any(is_retryable_result(t) for t in candidate.tier_history):
        return True
    last = candidate.last_tier()
    if last is None or last.verdict != Verdict.PASS:
        return False
    return _TIER_ORDER.index(last.tier) < _TIER_ORDER.index(through)


def resume_pool(candidates: list[Candidate], through: Tier) -> list[Candidate]:
    return [c for c in candidates if needs_resume(c, through)]
