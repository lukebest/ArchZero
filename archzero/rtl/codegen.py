"""Prompts / helpers for LLM → pyCircuit DSL generation."""

from __future__ import annotations

from pathlib import Path

from archzero.config import FactoryConfig
from archzero.models import ClauseKind, ProblemPackage

DSL_PERSONA = """You implement architecture mechanisms as pyCircuit (pyc4.0) Python DSL.

Write these files in the workspace:
1) design.py — @module hardware for the mechanism (use pycircuit Circuit/module/u APIs)
2) tb_design.py — @testbench that exercises commit-point observable behavior
3) EQUIV_GATE.md — fixed commit-point equivalence definition (do not change once written)
4) DECISION.md — which DOF parameters you explored and why

Rules:
- Prefer hierarchy-preserving @module boundaries
- Use pycircuit.spec.dse.product() to expand DOF parameters when useful
- Do NOT invent Yosys/OpenROAD flows; RTL + testbench only
- Keep designs synthesizable and deterministic
"""


def dof_prompt(problem: ProblemPackage) -> str:
    dofs = problem.by_kind(ClauseKind.DEGREE_OF_FREEDOM)
    if not dofs:
        return "No DOF clauses; choose modest, plausible parameters."
    lines = ["DOF clauses (expand with pycircuit.spec.dse.product when useful):"]
    for d in dofs:
        lines.append(f"- {d.id}: {d.text}")
    return "\n".join(lines)


def api_digest(cfg: FactoryConfig, *, max_chars: int = 6000) -> str:
    root = cfg.resolved_pycircuit_root()
    chunks: list[str] = []
    for rel in (
        "docs/FRONTEND_API.md",
        "compiler/frontend/pycircuit/api_contract.py",
    ):
        path = root / rel
        if path.is_file():
            chunks.append(f"# {rel}\n" + path.read_text(encoding="utf-8")[: max_chars // 2])
    if not chunks:
        chunks.append(
            "pyCircuit API digest unavailable (vendor/pycircuit not checked out).\n"
            "Use: from pycircuit import Circuit, module, u\n"
            "@module\ndef build(m: Circuit, ...): ..."
        )
    return "\n\n".join(chunks)[:max_chars]


def ensure_baseline_link(cfg: FactoryConfig, workdir: Path) -> Path | None:
    """Symlink or note XiangShan-pyc baseline design if present."""
    root = cfg.resolved_pycircuit_root()
    name = cfg.rtl.baseline_design
    candidates = [
        root / "designs" / "XiangShan-pyc" / "build" / name / "verilog",
        root / "designs" / "XiangShan-pyc" / name,
        root / "designs" / name,
    ]
    for c in candidates:
        if c.exists():
            link = workdir / "baseline_rtl"
            if not link.exists():
                try:
                    link.symlink_to(c, target_is_directory=c.is_dir())
                except OSError:
                    (workdir / "BASELINE_RTL.txt").write_text(
                        f"baseline: {c}\n", encoding="utf-8"
                    )
            return c
    return None
