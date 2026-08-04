"""Lint NDF-lite problem packages."""

from __future__ import annotations

from archzero.models import ClauseKind, ProblemPackage


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
