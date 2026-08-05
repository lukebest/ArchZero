"""Recursive problem frontier + §5.1 paradigm expansion.

Paper (arXiv:2604.03312 §5.1): Lateral mode finds cross-domain structural
isomorphisms; Foundational mode questions whether the problem should be solved
at all. Theory lenses (information / sampling / control / queueing / …) bound
reasoning inside digital CMOS physics.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from archzero.config import FactoryConfig
from archzero.generation.theories import (
    THEORY_LENSES,
    offline_theory_questions,
    theory_catalog_markdown,
)
from archzero.llm.client import CursorLLM
from archzero.models import Clause, ClauseKind, ProblemPackage, TaskClass, _uid
from archzero.spec.ndf import write_problem_package
from archzero.store.artifacts import ArtifactStore


class ExpansionKind:
    VERTICAL = "vertical"
    LATERAL = "lateral"
    FOUNDATIONAL = "foundational"


class ParadigmCandidate(BaseModel):
    """Observable artifact: a potential paradigm / cross-domain leap."""

    id: str = Field(default_factory=lambda: _uid("para-"))
    kind: str  # vertical | lateral | foundational
    title: str
    theory_lenses: list[str] = Field(default_factory=list)
    cross_domain_source: str = ""  # e.g. "compiler instruction scheduling"
    isomorphism: str = ""  # abstract structural mapping
    why_not_local_optima: str = ""
    paradigm_shift_claim: str = ""
    open_questions: list[str] = Field(default_factory=list)
    new_clauses: list[dict[str, Any]] = Field(default_factory=list)
    problem_id: str | None = None
    parent_problem_id: str | None = None
    score_novelty: float | None = None


FRONTIER_PERSONA = """You are the recursive problem-generation engine of an Architecture Idea Factory
(paper: Computer Architecture's AlphaZero Moment, §3.2 + §5.1).

Your job is cross-domain discovery so search does NOT trap in local optima within one paradigm.
Historical paradigm shifts came from transfer: dataflow←λ-calculus, OoO←compiler scheduling,
systolic←signal processing, SIMT←graphics pipelines.

Produce THREE expansions:
1) vertical — deepen the SAME bottleneck with tighter, measurable constraints
2) lateral — identify an abstract structural isomorphism from ANOTHER domain and transfer it
3) foundational — question whether the problem should be solved this way at all (paradigm rethink)

For lateral and foundational you MUST cite one or more theory lenses from:
information_theory, sampling_theory, control_theory, queueing_theory,
statistical_mechanics, game_theory, category_theory, coding_theory.

Return JSON ONLY:
{
  "expansions": [
    {
      "kind": "vertical|lateral|foundational",
      "title": "...",
      "theory_lenses": ["queueing_theory", ...],
      "cross_domain_source": "field / classic result being transferred",
      "isomorphism": "what maps to what in the architecture problem",
      "why_not_local_optima": "why this is not incremental within the current paradigm",
      "paradigm_shift_claim": "one sentence on the potential shift (or 'incremental' for vertical)",
      "score_novelty": 0.0-1.0,
      "open_questions": ["..."],
      "new_clauses": [{"id":"REQ-2xx","kind":"REQ","text":"..."}]
    }
  ]
}
"""


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
            try:
                return json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                pass
        return {"expansions": []}


def _kind_map() -> dict[str, ClauseKind]:
    m = {k.value: k for k in ClauseKind}
    m.update(
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
    return m


def _package_from_expansion(
    parent: ProblemPackage,
    exp: dict[str, Any],
    i: int,
) -> tuple[ProblemPackage, ParadigmCandidate]:
    kind_map = _kind_map()
    clauses = list(parent.clauses)
    for raw in exp.get("new_clauses") or []:
        kid = str(raw.get("kind") or "REQ")
        kind = kind_map.get(kid, ClauseKind.REQUIREMENT)
        cid = str(raw.get("id") or f"{kind.value}-{200 + i}")
        clauses.append(
            Clause(
                id=cid,
                kind=kind,
                text=str(raw.get("text") or ""),
                measurable=kind == ClauseKind.ACCEPTANCE,
            )
        )
    lenses = [str(x) for x in (exp.get("theory_lenses") or [])]
    kind = str(exp.get("kind") or ExpansionKind.VERTICAL)
    pp = ProblemPackage(
        title=str(exp.get("title") or f"{parent.title} / {kind}"),
        clauses=clauses,
        open_questions=list(exp.get("open_questions") or parent.open_questions),
        meta={
            "parent_id": parent.id,
            "frontier_kind": kind,
            "theory_lenses": lenses,
            "cross_domain_source": exp.get("cross_domain_source"),
            "isomorphism": exp.get("isomorphism"),
            "paradigm_shift_claim": exp.get("paradigm_shift_claim"),
            "section": "paper_5.1",
        },
    )
    cand = ParadigmCandidate(
        kind=kind,
        title=pp.title,
        theory_lenses=lenses,
        cross_domain_source=str(exp.get("cross_domain_source") or ""),
        isomorphism=str(exp.get("isomorphism") or ""),
        why_not_local_optima=str(exp.get("why_not_local_optima") or ""),
        paradigm_shift_claim=str(exp.get("paradigm_shift_claim") or ""),
        open_questions=list(exp.get("open_questions") or []),
        new_clauses=list(exp.get("new_clauses") or []),
        problem_id=pp.id,
        parent_problem_id=parent.id,
        score_novelty=float(exp["score_novelty"])
        if exp.get("score_novelty") is not None
        else None,
    )
    return pp, cand


def offline_expand(
    problem: ProblemPackage,
) -> tuple[list[ProblemPackage], list[ParadigmCandidate]]:
    """Deterministic §5.1-shaped expansions without LLM (for tests / dry-run)."""
    symptom = ""
    for c in problem.clauses:
        if c.kind == ClauseKind.CONTEXT:
            symptom = c.text[:200]
            break
    tq = offline_theory_questions(title=problem.title, symptom=symptom, limit_per_lens=1)
    # Pick representative lenses for each mode
    lateral_lens = ["queueing_theory", "control_theory"]
    found_lens = ["information_theory", "category_theory"]
    expansions = [
        {
            "kind": ExpansionKind.VERTICAL,
            "title": f"{problem.title} — tighter measurable bound",
            "theory_lenses": ["queueing_theory"],
            "cross_domain_source": "same-domain refinement",
            "isomorphism": "n/a (vertical)",
            "why_not_local_optima": "Still within current paradigm; useful for calibration.",
            "paradigm_shift_claim": "incremental",
            "score_novelty": 0.2,
            "open_questions": [
                q["question"] for q in tq if q["theory"] == "queueing_theory"
            ],
            "new_clauses": [
                {
                    "id": "REQ-210",
                    "kind": "REQ",
                    "text": "Tighten the primary metric with an explicit Little's Law / concurrency bound.",
                }
            ],
        },
        {
            "kind": ExpansionKind.LATERAL,
            "title": f"{problem.title} — cross-domain transfer",
            "theory_lenses": lateral_lens,
            "cross_domain_source": "control + queueing (feedback scheduling)",
            "isomorphism": "Treat the contended resource as a controlled queue; map setpoint→QoS target.",
            "why_not_local_optima": "Imports a feedback/scheduling structure not native to the current microarch knob set.",
            "paradigm_shift_claim": "From static mechanism to closed-loop resource allocation.",
            "score_novelty": 0.7,
            "open_questions": [
                q["question"]
                for q in tq
                if q["theory"] in lateral_lens
            ],
            "new_clauses": [
                {
                    "id": "DOF-210",
                    "kind": "DOF",
                    "text": "Allow closed-loop control / adaptive scheduling as first-class design freedom.",
                }
            ],
        },
        {
            "kind": ExpansionKind.FOUNDATIONAL,
            "title": f"{problem.title} — reframe the problem",
            "theory_lenses": found_lens,
            "cross_domain_source": "information theory + compositionality",
            "isomorphism": "Ask which bits/operations are unnecessary vs which must be exact.",
            "why_not_local_optima": "Questions whether the bottleneck should be solved by more mechanism at all.",
            "paradigm_shift_claim": "From 'accelerate the work' to 'avoid / approximate the work under entropy bounds'.",
            "score_novelty": 0.85,
            "open_questions": [
                q["question"]
                for q in tq
                if q["theory"] in found_lens
            ],
            "new_clauses": [
                {
                    "id": "NNG-210",
                    "kind": "NNG",
                    "text": "Do not assume every request must be served at full fidelity; allow principled approximation.",
                }
            ],
        },
    ]
    packages: list[ProblemPackage] = []
    candidates: list[ParadigmCandidate] = []
    for i, exp in enumerate(expansions):
        pp, cand = _package_from_expansion(problem, exp, i)
        packages.append(pp)
        candidates.append(cand)
    return packages, candidates


def render_paradigm_report(
    parent: ProblemPackage,
    candidates: list[ParadigmCandidate],
) -> str:
    lines = [
        f"# Paradigm / frontier expansion — {parent.title}",
        "",
        f"Parent problem: `{parent.id}`",
        "",
        "Aligned with paper §5.1 (Paradigm Shifts and Local Optima):",
        "Lateral = cross-domain isomorphism; Foundational = reframe/abandon the problem framing.",
        "",
        "## Theory catalog",
        "",
    ]
    for t in THEORY_LENSES:
        lines.append(f"- `{t.id}` — {t.name}: {t.paper_hint}")
    lines += ["", "## Candidates", ""]
    for c in candidates:
        lines.append(f"### [{c.kind}] {c.title}")
        lines.append("")
        lines.append(f"- id: `{c.id}`")
        lines.append(f"- new problem: `{c.problem_id}`")
        lines.append(f"- theories: {', '.join(c.theory_lenses) or '—'}")
        lines.append(f"- cross-domain source: {c.cross_domain_source or '—'}")
        lines.append(f"- isomorphism: {c.isomorphism or '—'}")
        lines.append(f"- why not local optima: {c.why_not_local_optima or '—'}")
        lines.append(f"- paradigm claim: {c.paradigm_shift_claim or '—'}")
        if c.score_novelty is not None:
            lines.append(f"- novelty score: {c.score_novelty}")
        if c.open_questions:
            lines.append("- open questions:")
            for q in c.open_questions:
                lines.append(f"  - {q}")
        lines.append("")
    return "\n".join(lines)


async def expand_frontier(
    cfg: FactoryConfig,
    problem: ProblemPackage,
    *,
    signals: list[str] | None = None,
    out_dir: Path | None = None,
    llm: CursorLLM | None = None,
    offline: bool = False,
    persist_artifacts: bool = True,
) -> dict[str, Any]:
    """Run vertical/lateral/foundational expansion; return packages + paradigm candidates."""
    if offline:
        packages, candidates = offline_expand(problem)
    else:
        own = llm is None
        llm = llm or CursorLLM(cfg)
        if own:
            await llm.setup()
        try:
            ctx = {
                "title": problem.title,
                "clauses": [
                    {"id": c.id, "kind": c.kind.value, "text": c.text}
                    for c in problem.clauses
                ],
                "open_questions": problem.open_questions,
                "failure_signals": signals or [],
                "theory_lenses": [
                    {
                        "id": t.id,
                        "name": t.name,
                        "hint": t.paper_hint,
                        "prompts": list(t.prompts),
                    }
                    for t in THEORY_LENSES
                ],
                "instruction": (
                    "Prefer lateral and foundational leaps that cite theories. "
                    "Vertical may be incremental."
                ),
            }
            data = _parse_json(
                await llm.complete(
                    FRONTIER_PERSONA,
                    json.dumps(ctx, indent=2),
                    TaskClass.IDEATE,
                    expect_json=True,
                )
            )
            packages = []
            candidates = []
            exps = data.get("expansions") or []
            if len(exps) < 3:
                # Fill missing modes offline so the funnel always sees three axes
                off_p, off_c = offline_expand(problem)
                have = {str(e.get("kind")) for e in exps}
                for p, c in zip(off_p, off_c, strict=True):
                    if c.kind not in have:
                        packages.append(p)
                        candidates.append(c)
            for i, exp in enumerate(exps):
                pp, cand = _package_from_expansion(problem, exp, i)
                packages.append(pp)
                candidates.append(cand)
        finally:
            if own:
                await llm.aclose()

    report = render_paradigm_report(problem, candidates)
    report_path = None
    artifact_hashes: list[str] = []
    written_specs: list[str] = []

    if out_dir is not None:
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "THEORY_LENSES.md").write_text(
            theory_catalog_markdown(), encoding="utf-8"
        )
        report_path = out_dir / "PARADIGM_REPORT.md"
        report_path.write_text(report, encoding="utf-8")
        (out_dir / "paradigm_candidates.json").write_text(
            json.dumps([c.model_dump(mode="json") for c in candidates], indent=2),
            encoding="utf-8",
        )
        for pp in packages:
            path = write_problem_package(pp, out_dir / f"{pp.id}.md")
            written_specs.append(str(path))

    if persist_artifacts:
        arts = ArtifactStore(cfg.artifacts_dir)
        artifact_hashes.append(arts.put_text(report, suffix=".md"))
        artifact_hashes.append(
            arts.put_json([c.model_dump(mode="json") for c in candidates])
        )

    return {
        "parent_id": problem.id,
        "packages": packages,
        "candidates": candidates,
        "report": report,
        "report_path": str(report_path) if report_path else None,
        "spec_paths": written_specs,
        "artifact_hashes": artifact_hashes,
        "offline": offline,
    }
