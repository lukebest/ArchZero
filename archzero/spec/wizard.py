"""Problem package scaffolding for architecture researchers."""

from __future__ import annotations

import re
from pathlib import Path

from archzero.models import Clause, ClauseKind, ProblemPackage
from archzero.spec.ndf import write_problem_package


def _slug(title: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "-", title.strip().lower()).strip("-")
    return (s or "problem")[:48]


def scaffold_problem(
    *,
    title: str,
    workload: str,
    symptom: str,
    constraint: str,
    target_metric: str = ">=15% MPKI reduction",
    area_budget: str = "<= 0.5 mm^2",
    bandwidth_slack: str = "<=5%",
    non_goals: str = "Do not change ISA or require OS changes.",
    dof: str = "Predictor family, table size, history length.",
    out_dir: Path,
) -> Path:
    """Create a lint-ready NDF-lite problem package from researcher fields."""
    pid = f"pp-{_slug(title)}"
    clauses = [
        Clause(
            id="CTX-001",
            kind=ClauseKind.CONTEXT,
            text=f"Workload: {workload}\n\nSymptom: {symptom}",
        ),
        Clause(
            id="CTX-002",
            kind=ClauseKind.CONTEXT,
            text=f"Hardware / resource envelope: {constraint}\nArea budget: {area_budget}.",
            refines=["CTX-001"],
        ),
        Clause(
            id="REQ-001",
            kind=ClauseKind.REQUIREMENT,
            text=f"The mechanism shall achieve: {target_metric} versus the unmodified baseline.",
            refines=["CTX-001"],
        ),
        Clause(
            id="REQ-002",
            kind=ClauseKind.REQUIREMENT,
            text=(
                f"The mechanism must not increase DRAM bandwidth demand by more than "
                f"{bandwidth_slack} at iso-IPC."
            ),
            refines=["CTX-002"],
        ),
        Clause(
            id="NNG-001",
            kind=ClauseKind.NON_GOAL,
            text=non_goals,
        ),
        Clause(
            id="ACC-001",
            kind=ClauseKind.ACCEPTANCE,
            text=(
                "An analytic model (Tier2) shall show the target metric under stated "
                "assumptions; Magic Gap vs any available sim <= 2x."
            ),
            refines=["REQ-001"],
            measurable=True,
        ),
        Clause(
            id="ACC-002",
            kind=ClauseKind.ACCEPTANCE,
            text=(
                "Stub or ChampSim/gem5 simulation shall confirm performance and "
                "bandwidth constraints on the stated workload suite."
            ),
            refines=["REQ-001", "REQ-002"],
            measurable=True,
        ),
        Clause(
            id="DOF-001",
            kind=ClauseKind.DEGREE_OF_FREEDOM,
            text=f"Open degrees of freedom: {dof}",
        ),
    ]
    pp = ProblemPackage(
        id=pid,
        title=title,
        clauses=clauses,
        open_questions=[
            f"What mechanisms attack: {symptom}?",
            "Which DOF dimensions are worth MAP-Elites features?",
        ],
        meta={"workload": workload, "scaffolded": True},
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{_slug(title)}.md"
    write_problem_package(pp, path)
    return path
