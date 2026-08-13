"""Shared data models for the Idea Factory."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _uid(prefix: str = "") -> str:
    return f"{prefix}{uuid4().hex[:12]}" if prefix else uuid4().hex[:12]


class UsagePool(str, Enum):
    CURSOR = "cursor"  # pool 1: cursor-grok-4.6-high-fast, composer-2.5, …
    OTHER = "other"  # pool 2: third-party frontier models


class TaskClass(str, Enum):
    """Routes to a usage pool via ModelRouter."""

    BULK_SCREEN = "bulk_screen"  # Tier0, persona expansion — pool 1
    EVOLVE = "evolve"  # mutation / repair loops — pool 1
    ANALYTIC = "analytic"  # Tier2 verify-repair — pool 1
    COMPREHEND = "comprehend"  # paper reading — pool 1
    IDEATE = "ideate"  # clean-room generation — pool 1
    SYNTHESIZE = "synthesize"  # Tier1 synthesizer — pool 2
    SPEC_GEN = "spec_gen"  # specification drafting — pool 2
    FINAL_JUDGE = "final_judge"  # Tier4/5 adjudication — pool 2


class Tier(str, Enum):
    T0 = "tier0"
    T1 = "tier1"
    T2 = "tier2"
    T3 = "tier3"
    T4 = "tier4"
    T5 = "tier5"
    T6 = "tier6"  # physical signoff — reserved / not implemented yet


class EvidenceLevel(str, Enum):
    """How strongly a tier result is backed by real tooling."""

    STUB = "stub"
    ANALYTIC = "analytic"
    SIM = "sim"
    RTL = "rtl"
    SIGNOFF = "signoff"  # reserved for Tier6


class Verdict(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    SKIP = "skip"
    UNAVAILABLE = "unavailable"


class FailureKind(str, Enum):
    PHYSICS = "physics"  # conservation / bandwidth / Amdahl hard fail
    NOVELTY = "novelty"
    CORRECTNESS = "correctness"
    PERFORMANCE = "performance"
    FEASIBILITY = "feasibility"
    EQUIVALENCE = "equivalence"
    TOOLING = "tooling"
    BUDGET = "budget"
    UNKNOWN = "unknown"


class ClauseKind(str, Enum):
    CONTEXT = "CTX"
    REQUIREMENT = "REQ"
    ACCEPTANCE = "ACC"
    DEGREE_OF_FREEDOM = "DOF"
    NON_GOAL = "NNG"
    DECISION = "DEC"


class Clause(BaseModel):
    id: str
    kind: ClauseKind
    text: str
    refines: list[str] = Field(default_factory=list)
    measurable: bool = False


class ProblemPackage(BaseModel):
    """NDF-lite problem package — the factory's constitution for one campaign."""

    id: str = Field(default_factory=lambda: _uid("pp-"))
    title: str
    source_path: str | None = None
    clauses: list[Clause] = Field(default_factory=list)
    decisions: list[dict[str, Any]] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=_now)
    meta: dict[str, Any] = Field(default_factory=dict)

    def clause_ids(self) -> set[str]:
        return {c.id for c in self.clauses}

    def by_kind(self, kind: ClauseKind) -> list[Clause]:
        return [c for c in self.clauses if c.kind == kind]


class TierResult(BaseModel):
    tier: Tier
    verdict: Verdict
    score: float | None = None
    summary: str = ""
    metrics: dict[str, Any] = Field(default_factory=dict)
    artifacts: list[str] = Field(default_factory=list)  # artifact hashes
    clause_refs: list[str] = Field(default_factory=list)
    evidence: EvidenceLevel = EvidenceLevel.STUB
    model_id: str | None = None
    pool: UsagePool | None = None
    prompt_hash: str | None = None
    tool_versions: dict[str, str] = Field(default_factory=dict)
    downgraded: bool = False
    created_at: datetime = Field(default_factory=_now)


class FailureRecord(BaseModel):
    id: str = Field(default_factory=lambda: _uid("fail-"))
    candidate_id: str
    tier: Tier
    kind: FailureKind
    message: str
    clause_refs: list[str] = Field(default_factory=list)
    details: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=_now)


class Candidate(BaseModel):
    """Unified candidate flowing through the evaluation funnel."""

    id: str = Field(default_factory=lambda: _uid("cand-"))
    problem_id: str
    title: str
    mechanism: str  # natural-language mechanism description
    family: str = "unclassified"  # mechanism family for MAP-Elites
    workdir: str | None = None
    code_path: str | None = None
    spec_path: str | None = None
    clause_refs: list[str] = Field(default_factory=list)
    metrics: dict[str, Any] = Field(default_factory=dict)
    tier_history: list[TierResult] = Field(default_factory=list)
    failures: list[FailureRecord] = Field(default_factory=list)
    status: str = "new"  # new | active | passed | failed | archived
    parent_id: str | None = None
    content_hash: str | None = None
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)

    def last_tier(self) -> TierResult | None:
        return self.tier_history[-1] if self.tier_history else None

    def passed_through(self, tier: Tier) -> bool:
        """True if this candidate has a PASS or UNAVAILABLE result for the tier."""
        return any(
            t.tier == tier and t.verdict in {Verdict.PASS, Verdict.UNAVAILABLE}
            for t in self.tier_history
        )

    def hard_passed(self, tier: Tier) -> bool:
        """True only for a genuine PASS (not UNAVAILABLE)."""
        return any(t.tier == tier and t.verdict == Verdict.PASS for t in self.tier_history)


class Campaign(BaseModel):
    id: str = Field(default_factory=lambda: _uid("camp-"))
    name: str
    problem_id: str
    through_tier: Tier = Tier.T2
    status: str = "running"  # running | paused | done | failed
    created_at: datetime = Field(default_factory=_now)
    meta: dict[str, Any] = Field(default_factory=dict)


class UsageEvent(BaseModel):
    id: str = Field(default_factory=lambda: _uid("use-"))
    campaign_id: str | None = None
    task: TaskClass
    model_id: str
    pool: UsagePool
    agent_id: str | None = None
    run_id: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    created_at: datetime = Field(default_factory=_now)
