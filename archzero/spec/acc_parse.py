"""Parse NDF ACC/REQ clauses into numeric acceptance thresholds.

Two properties matter more than the parsing itself:

1. **Provenance.** Every gate number records whether it came from a clause or
   from a fallback default. Previously a NoC spec and the cache demo produced
   byte-identical threshold dicts, so a researcher could not tell that three of
   the four numbers grading their interconnect study had been invented.
2. **Refusal.** If a spec's acceptance criteria rest on quantities no tier can
   measure, that is reported via :attr:`AcceptanceThresholds.unmeasurable_metrics`
   so the funnel can decline to grade instead of silently falling back to
   ``>=15% MPKI`` — the same fail-closed stance Tier5/Tier6 take.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from archzero.models import ClauseKind, ProblemPackage
from archzero.spec.metrics import (
    GENERIC,
    METRIC_BY_ID,
    detect_metrics,
    infer_domain,
)

_PCT = r"(\d+(?:\.\d+)?)\s*%"
_NUM = r"(\d+(?:\.\d+)?)"

# Legacy gate field -> registry metric id. These four are the only numbers the
# Tier2/3/4 gates currently understand.
GATE_FIELDS: dict[str, str] = {
    "min_miss_reduction": "miss_reduction",
    "max_bw_delta_frac": "bw_delta_frac",
    "max_magic_gap": "magic_gap",
    "area_budget_mm2": "area_mm2",
}

DEFAULTS: dict[str, float] = {
    "min_miss_reduction": 0.15,
    "max_bw_delta_frac": 0.05,
    "max_magic_gap": 2.0,
    "area_budget_mm2": 0.5,
}

# Magic Gap is a model-vs-simulation consistency check, not a performance
# target. A spec that pins only Magic Gap has told the funnel nothing about
# what "better" means, so it does not count as a substantive gate.
PERFORMANCE_GATES: frozenset[str] = frozenset(
    {"min_miss_reduction", "max_bw_delta_frac", "area_budget_mm2"}
)


@dataclass(frozen=True)
class ThresholdSource:
    """One gate number traced back to the clause that stated it."""

    gate_field: str
    metric_id: str
    op: str
    value: float
    unit: str
    clause_id: str
    clause_text: str


@dataclass(frozen=True)
class AcceptanceThresholds:
    """Numeric gates derived from ACC (falling back to REQ)."""

    min_miss_reduction: float = 0.15
    max_bw_delta_frac: float = 0.05
    max_magic_gap: float = 2.0
    area_budget_mm2: float | None = 0.5
    source_clauses: dict[str, str] = field(default_factory=dict)
    # --- provenance ---
    defaulted: frozenset[str] = frozenset(GATE_FIELDS)
    declared_metrics: tuple[str, ...] = ()
    unmeasurable_metrics: tuple[str, ...] = ()
    domain: str = GENERIC
    parsed: tuple[ThresholdSource, ...] = ()

    def as_dict(self) -> dict:
        return {
            "min_miss_reduction": self.min_miss_reduction,
            "max_bw_delta_frac": self.max_bw_delta_frac,
            "max_magic_gap": self.max_magic_gap,
            "area_budget_mm2": self.area_budget_mm2,
            "source_clauses": dict(self.source_clauses),
            "defaulted": sorted(self.defaulted),
            "declared_metrics": list(self.declared_metrics),
            "unmeasurable_metrics": list(self.unmeasurable_metrics),
            "measurable_performance": list(self.measurable_performance),
            "report_only": self.report_only,
            "domain": self.domain,
        }

    def from_spec(self, gate_field: str) -> bool:
        """True when this gate number was read from a clause, not invented."""
        return gate_field not in self.defaulted

    @property
    def fully_defaulted(self) -> bool:
        """No gate number came from the spec at all."""
        return set(self.defaulted) >= set(GATE_FIELDS)

    @property
    def has_spec_performance_gate(self) -> bool:
        """Did the spec pin at least one gate that defines what 'better' means?"""
        return bool(PERFORMANCE_GATES - self.defaulted)

    @property
    def measurable_declared(self) -> tuple[str, ...]:
        return tuple(
            mid
            for mid in self.declared_metrics
            if mid in METRIC_BY_ID and METRIC_BY_ID[mid].measurable
        )

    @property
    def measurable_performance(self) -> tuple[str, ...]:
        """Declared metrics we can produce, excluding Magic Gap."""
        return tuple(mid for mid in self.measurable_declared if mid != "magic_gap")

    @property
    def report_only(self) -> bool:
        """We can measure something, but the spec never pinned a numeric gate."""
        return bool(self.measurable_performance) and not self.has_spec_performance_gate

    def spec_gates(self) -> list:
        """Numeric gates that came from the spec, not from tool defaults.

        Imported lazily so this module does not depend on the sim package.
        """
        from archzero.sim.metrics import MetricGate

        gates: list[MetricGate] = []
        for src in self.parsed:
            if src.gate_field not in PERFORMANCE_GATES:
                continue
            gates.append(
                MetricGate(
                    metric_id=src.metric_id,
                    op=src.op,
                    value=src.value,
                    source="spec",
                )
            )
        return gates

    @property
    def gradable(self) -> bool:
        """Can the funnel honestly evaluate this spec?

        Yes when we can produce at least one declared performance metric
        (report-only is still honest — we just will not invent a PASS/FAIL).
        No when the acceptance criteria rest only on quantities no tier
        measures *and* the spec never pinned a gate we can check. That is
        the case that used to silently become ``>=15% MPKI``.
        """
        if self.measurable_performance:
            return True
        if not self.unmeasurable_metrics:
            return True
        return self.has_spec_performance_gate

    def ungradable_reason(self) -> str:
        if self.gradable:
            return ""
        names = "、".join(
            f"{mid}（{METRIC_BY_ID[mid].name}）"
            for mid in self.unmeasurable_metrics
            if mid in METRIC_BY_ID
        )
        return (
            f"该问题包（领域推断：{self.domain}）的验收标准依赖本仓库尚无评估器的指标："
            f"{names}。同时没有任何一条 ACC/REQ 给出漏斗能检查的性能门限，"
            f"因此 min_miss_reduction / max_bw_delta_frac / area_budget_mm2 全是缺省值。"
            f"继续评判等于用「>=15% MPKI、<=5% DRAM 带宽、<=0.5 mm²」的缓存门限"
            f"去裁决该领域的方案，结论不可信。"
        )

    def unmeasurable_note(self) -> str:
        """Warning for specs that are gradable but still have blind spots."""
        if not self.unmeasurable_metrics:
            return ""
        names = "、".join(
            f"{mid}（{METRIC_BY_ID[mid].name}）"
            for mid in self.unmeasurable_metrics
            if mid in METRIC_BY_ID
        )
        return f"以下声明指标本仓库无评估器，漏斗不会检查：{names}。"

    def provenance_rows(self) -> list[tuple[str, str, str, str]]:
        """(gate_field, value, origin, clause) rows for CLI/report rendering."""
        by_field = {p.gate_field: p for p in self.parsed}
        rows: list[tuple[str, str, str, str]] = []
        for gate_field in GATE_FIELDS:
            value = getattr(self, gate_field)
            src = by_field.get(gate_field)
            if src is None:
                rows.append((gate_field, str(value), "缺省值（非规范声明）", "—"))
            else:
                rows.append((gate_field, str(value), "规范声明", src.clause_id))
        return rows


def _pct_to_frac(match: re.Match[str] | None) -> float | None:
    if not match:
        return None
    return float(match.group(1)) / 100.0


def _scan_text(text: str) -> tuple[dict[str, float | None], set[str]]:
    """Extract gate numbers, but only for metrics the clause actually names.

    Returns ``(gate_values, declared_metric_ids)``. Gating each regex on a
    word-boundary alias match is what stops ``admission control`` from
    registering as a cache-miss requirement.
    """
    present = {m.id for m in detect_metrics(text)}
    out: dict[str, float | None] = dict.fromkeys(GATE_FIELDS, None)

    if "miss_reduction" in present:
        m = re.search(
            rf"(?:≥|>=|at least|shall show|reduction)\s*{_PCT}",
            text,
            re.IGNORECASE,
        )
        if not m:
            m = re.search(rf"{_PCT}\s*(?:mpki|miss)", text, re.IGNORECASE)
        if m:
            out["min_miss_reduction"] = _pct_to_frac(m)

    if "bw_delta_frac" in present:
        m = re.search(
            rf"(?:≤|<=|not increase|by more than|at most)\s*{_PCT}",
            text,
            re.IGNORECASE,
        )
        if m:
            out["max_bw_delta_frac"] = _pct_to_frac(m)

    if "magic_gap" in present:
        m = re.search(
            rf"magic\s*gap[^≤<=\d]*?(?:≤|<=)\s*{_NUM}\s*[×x]",
            text,
            re.IGNORECASE,
        )
        if m:
            out["max_magic_gap"] = float(m.group(1))

    if "area_mm2" in present and "mm" in text.lower():
        m = re.search(rf"(?:≤|<=)\s*{_NUM}\s*mm", text, re.IGNORECASE)
        if m:
            out["area_budget_mm2"] = float(m.group(1))

    return out, present


def parse_acceptance_thresholds(pp: ProblemPackage) -> AcceptanceThresholds:
    """Extract thresholds from ACC clauses, with REQ fallback, then defaults."""
    sources: dict[str, str] = {}
    found: dict[str, float] = {}
    parsed: list[ThresholdSource] = []
    declared: dict[str, None] = {}

    # Prefer ACC, then REQ, then CTX for numbers.
    ordered = sorted(
        pp.clauses,
        key=lambda c: (
            0 if c.id.startswith("ACC") else 1 if c.id.startswith("REQ") else 2,
            c.id,
        ),
    )
    for clause in ordered:
        if not (
            clause.id.startswith("ACC")
            or clause.id.startswith("REQ")
            or clause.id.startswith("CTX")
        ):
            continue
        values, present = _scan_text(clause.text)
        # Only ACC/REQ define the acceptance contract; CTX is background.
        if clause.kind in (ClauseKind.ACCEPTANCE, ClauseKind.REQUIREMENT):
            for mid in present:
                declared.setdefault(mid, None)
        for gate_field, val in values.items():
            if val is None or gate_field in found:
                continue
            found[gate_field] = val
            sources[clause.id] = clause.text[:160]
            spec = METRIC_BY_ID[GATE_FIELDS[gate_field]]
            parsed.append(
                ThresholdSource(
                    gate_field=gate_field,
                    metric_id=spec.id,
                    op=spec.default_op,
                    value=val,
                    unit=spec.unit,
                    clause_id=clause.id,
                    clause_text=clause.text[:160],
                )
            )

    declared_ids = tuple(sorted(declared))
    unmeasurable = tuple(
        mid for mid in declared_ids if mid in METRIC_BY_ID and not METRIC_BY_ID[mid].measurable
    )
    acc_req_text = "\n".join(
        c.text
        for c in pp.clauses
        if c.kind in (ClauseKind.ACCEPTANCE, ClauseKind.REQUIREMENT)
    )

    return AcceptanceThresholds(
        min_miss_reduction=found.get("min_miss_reduction", DEFAULTS["min_miss_reduction"]),
        max_bw_delta_frac=found.get("max_bw_delta_frac", DEFAULTS["max_bw_delta_frac"]),
        max_magic_gap=found.get("max_magic_gap", DEFAULTS["max_magic_gap"]),
        area_budget_mm2=found.get("area_budget_mm2", DEFAULTS["area_budget_mm2"]),
        source_clauses=sources,
        defaulted=frozenset(f for f in GATE_FIELDS if f not in found),
        declared_metrics=declared_ids,
        unmeasurable_metrics=unmeasurable,
        domain=infer_domain(acc_req_text),
        parsed=tuple(parsed),
    )
