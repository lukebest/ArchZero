"""Data model for the six-section patent disclosure."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field

from archzero.patent.prior_art import PriorArtResult

SECTION_TITLES: tuple[str, ...] = (
    "一、问题背景描述",
    "二、现有技术描述",
    "三、本方案的技术方案",
    "四、技术保护点",
    "五、有益效果",
    "六、与现有公开的专利/论文的检索与对比",
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


class BenefitClaim(BaseModel):
    """One quantified benefit, traceable back to a funnel metric.

    ``statement`` is LLM-worded prose, but ``metric_key`` / ``metric_value``
    come straight from ``Candidate.metrics``. A claim with ``metric_key=None``
    is qualitative and is rendered without a number.
    """

    statement: str
    metric_key: str | None = None
    metric_value: Any = None
    display_value: str = ""
    threshold: str = ""
    tier: str | None = None
    evidence_level: str = "analytic"  # stub | analytic | sim | rtl
    meets_threshold: bool | None = None

    @property
    def quantified(self) -> bool:
        return self.metric_key is not None and self.metric_value is not None


class ProtectionPoint(BaseModel):
    index: int
    title: str
    essential_features: list[str] = Field(default_factory=list)
    depends_on: int | None = None  # None = independent claim

    @property
    def kind(self) -> str:
        return "独立保护点" if self.depends_on is None else f"从属于第 {self.depends_on} 点"


class PatentDisclosure(BaseModel):
    candidate_id: str
    title: str
    problem_title: str = ""
    family: str = "unclassified"
    created_at: datetime = Field(default_factory=_now)

    background: str = ""
    background_clauses: list[str] = Field(default_factory=list)
    existing_tech: str = ""
    technical_solution: str = ""
    solution_steps: list[str] = Field(default_factory=list)
    protection_points: list[ProtectionPoint] = Field(default_factory=list)
    benefits: list[BenefitClaim] = Field(default_factory=list)
    benefits_note: str = ""
    prior_art: PriorArtResult = Field(default_factory=PriorArtResult)

    evidence_level: str = "analytic"
    provenance: dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)

    @property
    def quantified_benefits(self) -> list[BenefitClaim]:
        return [b for b in self.benefits if b.quantified]

    def to_json(self) -> str:
        import json

        return json.dumps(
            self.model_dump(mode="json"), indent=2, ensure_ascii=False
        )
