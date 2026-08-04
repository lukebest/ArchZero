"""NDF-lite problem package loader / writer."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

from archzero.models import Clause, ClauseKind, ProblemPackage

CLAUSE_RE = re.compile(
    r"^###\s+(?P<id>(?:CTX|REQ|ACC|DOF|NNG|DEC)-\d+)\s*[—\-–:]\s*(?P<title>.+)$",
    re.MULTILINE,
)
REFINES_RE = re.compile(r"`refines:\s*([^`]+)`")
KIND_MAP = {
    "CTX": ClauseKind.CONTEXT,
    "REQ": ClauseKind.REQUIREMENT,
    "ACC": ClauseKind.ACCEPTANCE,
    "DOF": ClauseKind.DEGREE_OF_FREEDOM,
    "NNG": ClauseKind.NON_GOAL,
    "DEC": ClauseKind.DECISION,
}


def _split_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    if not text.startswith("---"):
        return {}, text
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}, text
    meta = yaml.safe_load(parts[1]) or {}
    return meta, parts[2].lstrip("\n")


def _parse_clauses(body: str) -> list[Clause]:
    matches = list(CLAUSE_RE.finditer(body))
    clauses: list[Clause] = []
    for i, m in enumerate(matches):
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
        block = body[start:end].strip()
        cid = m.group("id")
        prefix = cid.split("-", 1)[0]
        kind = KIND_MAP[prefix]
        refines: list[str] = []
        for rm in REFINES_RE.finditer(block):
            refines.extend(x.strip() for x in rm.group(1).split(",") if x.strip())
        measurable = kind == ClauseKind.ACCEPTANCE or "measurable: true" in block.lower()
        # Strip meta lines from text
        lines = [
            ln
            for ln in block.splitlines()
            if not ln.strip().startswith("`refines:")
            and "measurable:" not in ln.lower()
        ]
        text = "\n".join(lines).strip() or m.group("title").strip()
        clauses.append(
            Clause(id=cid, kind=kind, text=text, refines=refines, measurable=measurable)
        )
    return clauses


def load_problem_package(path: Path) -> ProblemPackage:
    text = path.read_text(encoding="utf-8")
    meta, body = _split_frontmatter(text)
    title = meta.get("title") or path.stem
    clauses = _parse_clauses(body)
    open_questions = meta.get("open_questions") or []
    decisions = meta.get("decisions") or []
    # Also harvest DEC-* as decisions
    for c in clauses:
        if c.kind == ClauseKind.DECISION:
            decisions.append({"id": c.id, "text": c.text})
    return ProblemPackage(
        id=meta.get("id") or f"pp-{path.stem}",
        title=title,
        source_path=str(path.resolve()),
        clauses=clauses,
        decisions=decisions,
        open_questions=list(open_questions),
        meta={k: v for k, v in meta.items() if k not in {"title", "id", "open_questions", "decisions"}},
    )


def render_problem_package(pp: ProblemPackage) -> str:
    fm = {
        "id": pp.id,
        "title": pp.title,
        "open_questions": pp.open_questions,
        "decisions": pp.decisions,
        **pp.meta,
    }
    lines = ["---", yaml.safe_dump(fm, sort_keys=False).strip(), "---", "", f"# {pp.title}", ""]
    for c in pp.clauses:
        lines.append(f"### {c.id} — {c.kind.value}")
        if c.refines:
            lines.append(f"`refines: {', '.join(c.refines)}`")
        if c.measurable:
            lines.append("`measurable: true`")
        lines.append("")
        lines.append(c.text)
        lines.append("")
    return "\n".join(lines)


def write_problem_package(pp: ProblemPackage, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_problem_package(pp), encoding="utf-8")
    return path
