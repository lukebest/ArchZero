"""Parse NDF ACC/REQ clauses into numeric acceptance thresholds."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from archzero.models import ProblemPackage

_PCT = r"(\d+(?:\.\d+)?)\s*%"
_NUM = r"(\d+(?:\.\d+)?)"


@dataclass(frozen=True)
class AcceptanceThresholds:
    """Numeric gates derived from ACC (falling back to REQ)."""

    min_miss_reduction: float = 0.15
    max_bw_delta_frac: float = 0.05
    max_magic_gap: float = 2.0
    area_budget_mm2: float | None = 0.5
    source_clauses: dict[str, str] = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "min_miss_reduction": self.min_miss_reduction,
            "max_bw_delta_frac": self.max_bw_delta_frac,
            "max_magic_gap": self.max_magic_gap,
            "area_budget_mm2": self.area_budget_mm2,
            "source_clauses": dict(self.source_clauses),
        }


def _pct_to_frac(match: re.Match[str] | None) -> float | None:
    if not match:
        return None
    return float(match.group(1)) / 100.0


def _scan_text(text: str) -> dict[str, float | None]:
    lower = text.lower()
    out: dict[str, float | None] = {
        "min_miss_reduction": None,
        "max_bw_delta_frac": None,
        "max_magic_gap": None,
        "area_budget_mm2": None,
    }

    # Miss / MPKI reduction ≥ N%
    if any(k in lower for k in ("mpki", "miss", "reduction")):
        m = re.search(
            rf"(?:≥|>=|at least|shall show|reduction)\s*{_PCT}",
            text,
            re.IGNORECASE,
        )
        if not m:
            m = re.search(rf"{_PCT}\s*(?:mpki|miss)", text, re.IGNORECASE)
        if m:
            out["min_miss_reduction"] = _pct_to_frac(m)

    # Bandwidth ≤ N% / by more than N%
    if "bandwidth" in lower or "bw" in lower or "dram" in lower:
        m = re.search(
            rf"(?:≤|<=|not increase|by more than|at most)\s*{_PCT}",
            text,
            re.IGNORECASE,
        )
        if m:
            out["max_bw_delta_frac"] = _pct_to_frac(m)

    # Magic Gap ≤ N×
    if "magic gap" in lower:
        m = re.search(
            rf"magic\s*gap[^≤<=\d]*?(?:≤|<=)\s*{_NUM}\s*[×x]",
            text,
            re.IGNORECASE,
        )
        if m:
            out["max_magic_gap"] = float(m.group(1))

    # Area ≤ N mm²
    if "mm" in lower and "area" in lower:
        m = re.search(
            rf"(?:≤|<=)\s*{_NUM}\s*mm",
            text,
            re.IGNORECASE,
        )
        if m:
            out["area_budget_mm2"] = float(m.group(1))

    return out


def parse_acceptance_thresholds(pp: ProblemPackage) -> AcceptanceThresholds:
    """Extract thresholds from ACC clauses, with REQ fallback, then defaults."""
    sources: dict[str, str] = {}
    min_red: float | None = None
    max_bw: float | None = None
    max_gap: float | None = None
    area: float | None = None

    # Prefer ACC, then REQ
    ordered = sorted(
        pp.clauses,
        key=lambda c: (0 if c.id.startswith("ACC") else 1 if c.id.startswith("REQ") else 2, c.id),
    )
    for clause in ordered:
        if not (clause.id.startswith("ACC") or clause.id.startswith("REQ") or clause.id.startswith("CTX")):
            continue
        found = _scan_text(clause.text)
        for key, val in found.items():
            if val is None:
                continue
            if key == "min_miss_reduction" and min_red is None:
                min_red = val
                sources[clause.id] = clause.text[:160]
            elif key == "max_bw_delta_frac" and max_bw is None:
                max_bw = val
                sources[clause.id] = clause.text[:160]
            elif key == "max_magic_gap" and max_gap is None:
                max_gap = val
                sources[clause.id] = clause.text[:160]
            elif key == "area_budget_mm2" and area is None:
                area = val
                sources[clause.id] = clause.text[:160]

    return AcceptanceThresholds(
        min_miss_reduction=min_red if min_red is not None else 0.15,
        max_bw_delta_frac=max_bw if max_bw is not None else 0.05,
        max_magic_gap=max_gap if max_gap is not None else 2.0,
        area_budget_mm2=area if area is not None else 0.5,
        source_clauses=sources,
    )
