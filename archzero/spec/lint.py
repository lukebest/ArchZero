"""Lint NDF-lite problem packages."""

from __future__ import annotations

from archzero.models import ClauseKind, ProblemPackage
from archzero.spec.acc_parse import PERFORMANCE_GATES, parse_acceptance_thresholds
from archzero.spec.metrics import METRIC_BY_ID


def lint_acceptance(pp: ProblemPackage) -> list[str]:
    """Flag acceptance criteria the funnel cannot honestly grade.

    A spec can be perfectly well-formed NDF and still be ungradable, because
    a declared metric may have no evaluator in this repo. Saying so at lint
    time is much cheaper than discovering it after a few hundred LLM calls.
    """
    th = parse_acceptance_thresholds(pp)
    issues: list[str] = []

    for mid in th.unmeasurable_metrics:
        spec = METRIC_BY_ID.get(mid)
        if spec is None:
            continue
        issues.append(
            f"ACC 声明了 `{mid}`（{spec.name}），但本仓库没有评估器能产出该量："
            f"{spec.note or '尚未实现'}"
        )

    if th.domain == "wafer" and any(
        mid in th.unmeasurable_metrics
        for mid in ("yield_redundancy", "thermal_density")
    ):
        issues.append(
            "晶圆领域：本仓库只测织物 hop / die-to-die BW；良率与热密度没有模型，漏斗不会用 hop/d2d 冒充它们。"
        )

    if th.report_only:
        measured = ", ".join(th.measurable_performance) or "—"
        issues.append(
            f"ACC 未给出数值门限。漏斗将测量 {measured} 并报告，"
            f"但不会据此给出 PASS/FAIL（report-only）。"
        )
    elif not th.has_spec_performance_gate:
        missing = ", ".join(sorted(PERFORMANCE_GATES & th.defaulted))
        issues.append(
            f"没有任何 ACC/REQ 条款给出漏斗可检查的性能门限，以下将使用缺省值"
            f"（并非你的规范所声明）：{missing}"
        )

    if not th.gradable:
        issues.append(
            f"strict_acc 下 Tier2+ 将拒判此问题包（领域推断：{th.domain}）。"
            f"可选做法：在某条 ACC 中补一个漏斗能测的门限，或设 funnel.strict_acc = false "
            f"接受缓存缺省门限（结论不可信）。"
        )

    return issues


def lint_package(pp: ProblemPackage) -> list[str]:
    issues: list[str] = []
    ids = [c.id for c in pp.clauses]
    if len(ids) != len(set(ids)):
        seen: set[str] = set()
        for i in ids:
            if i in seen:
                issues.append(f"duplicate clause id: {i}")
            seen.add(i)

    id_set = set(ids)
    for c in pp.clauses:
        for ref in c.refines:
            if ref not in id_set:
                issues.append(f"{c.id} refines unknown clause {ref}")

    accs = [c for c in pp.clauses if c.kind == ClauseKind.ACCEPTANCE]
    if not accs:
        issues.append("no ACC-* acceptance criteria defined")
    else:
        for a in accs:
            if not a.measurable and "measure" not in a.text.lower() and "shall" not in a.text.lower():
                issues.append(f"{a.id} acceptance criterion may not be measurable")

    reqs = [c for c in pp.clauses if c.kind == ClauseKind.REQUIREMENT]
    if not reqs:
        issues.append("no REQ-* requirements defined")

    if not pp.title.strip():
        issues.append("empty title")

    return issues
