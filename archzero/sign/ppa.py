"""PPA metrics schema for future Tier6 signoff."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class PPAMetrics(BaseModel):
    area_um2: float | None = None
    wns_ns: float | None = None
    tns_ns: float | None = None
    power_mw: float | None = None
    cells: int | None = None
    utilization: float | None = None
    extra: dict[str, Any] = Field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        d = self.model_dump(mode="json", exclude_none=True)
        extra = d.pop("extra", {}) or {}
        d.update(extra)
        return d
