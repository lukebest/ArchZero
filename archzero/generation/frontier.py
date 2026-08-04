"""Recursive problem frontier: vertical / lateral / foundational expansion."""

from __future__ import annotations

import json
import re
from pathlib import Path

from archzero.config import FactoryConfig
from archzero.llm.client import CursorLLM
from archzero.models import (
    Clause,
    ClauseKind,
    ProblemPackage,
    TaskClass,
)
from archzero.spec.ndf import write_problem_package

FRONTIER_PERSONA = """You expand architecture research problem frontiers.
Given a problem package and failure/open-question signals, propose THREE expansions:
1) vertical — deepen the same bottleneck with tighter constraints
2) lateral — transfer the question to an adjacent subsystem
3) foundational — challenge a root assumption
Return JSON: {expansions: [{kind, title, new_clauses: [{id, kind, text}], open_questions: []}]}"""


def _parse_json(text: str) -> dict:
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if fence:
        text = fence.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            return json.loads(text[start : end + 1])
        return {"expansions": []}


async def expand_frontier(
    cfg: FactoryConfig,
    problem: ProblemPackage,
    *,
    signals: list[str] | None = None,
    out_dir: Path | None = None,
    llm: CursorLLM | None = None,
) -> list[ProblemPackage]:
    own = llm is None
    llm = llm or CursorLLM(cfg)
    if own:
        await llm.setup()

    ctx = {
        "title": problem.title,
        "clauses": [{"id": c.id, "kind": c.kind.value, "text": c.text} for c in problem.clauses],
        "open_questions": problem.open_questions,
        "signals": signals or [],
    }
    data = _parse_json(
        await llm.complete(
            FRONTIER_PERSONA,
            json.dumps(ctx, indent=2),
            TaskClass.IDEATE,
            expect_json=True,
        )
    )
    packages: list[ProblemPackage] = []
    kind_map = {k.value: k for k in ClauseKind}
    # also accept short keys
    kind_map.update(
        {
            "CTX": ClauseKind.CONTEXT,
            "REQ": ClauseKind.REQUIREMENT,
            "ACC": ClauseKind.ACCEPTANCE,
            "DOF": ClauseKind.DEGREE_OF_FREEDOM,
            "NNG": ClauseKind.NON_GOAL,
            "DEC": ClauseKind.DECISION,
            "context": ClauseKind.CONTEXT,
            "requirement": ClauseKind.REQUIREMENT,
            "acceptance": ClauseKind.ACCEPTANCE,
        }
    )

    for i, exp in enumerate(data.get("expansions") or []):
        clauses = list(problem.clauses)
        for raw in exp.get("new_clauses") or []:
            kid = str(raw.get("kind") or "REQ")
            kind = kind_map.get(kid, ClauseKind.REQUIREMENT)
            cid = str(raw.get("id") or f"{kind.value}-{100 + i}")
            clauses.append(
                Clause(id=cid, kind=kind, text=str(raw.get("text") or ""), measurable=kind == ClauseKind.ACCEPTANCE)
            )
        pp = ProblemPackage(
            title=str(exp.get("title") or f"{problem.title} / {exp.get('kind')}"),
            clauses=clauses,
            open_questions=list(exp.get("open_questions") or problem.open_questions),
            meta={"parent_id": problem.id, "frontier_kind": exp.get("kind")},
        )
        packages.append(pp)
        if out_dir:
            write_problem_package(pp, out_dir / f"{pp.id}.md")

    if own:
        await llm.aclose()
    return packages
