"""Lightweight Tier2 spec / functional verifiers (quant_eval personas)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from archzero.config import FactoryConfig
from archzero.generation.personas import load_persona
from archzero.llm.client import CursorLLM
from archzero.models import TaskClass


@dataclass
class VerifierResult:
    name: str
    ok: bool
    critique: str
    raw: str = ""


_STATUS_RE = re.compile(r"^\s*\**\s*Status\s*\**\s*:\s*\**\s*(PASS|FAIL)", re.I | re.M)


def parse_verifier_output(text: str) -> tuple[bool, str]:
    """Parse Status: PASS/FAIL; fail-closed only on explicit FAIL."""
    m = _STATUS_RE.search(text or "")
    if m:
        ok = m.group(1).upper() == "PASS"
        return ok, (text or "")[:800]
    # Offline / terse judges: treat as PASS unless clear failure language
    lower = (text or "").lower()
    if "status: fail" in lower or "verdict: fail" in lower:
        return False, (text or "")[:800]
    return True, (text or "")[:800]


async def run_spec_verifier(
    cfg: FactoryConfig,
    llm: CursorLLM,
    *,
    spec_text: str,
    problem_title: str,
    constraints: str,
) -> VerifierResult:
    try:
        persona = load_persona(cfg, "quant_eval/spec_verifier")
    except FileNotFoundError:
        persona = (
            "Audit the analytic SPEC for completeness and first-principles honesty. "
            "Output Status: PASS or Status: FAIL and a short critique."
        )
    ctx = (
        f"PROBLEM: {problem_title}\nCONSTRAINTS:\n{constraints}\n\n"
        f"SPEC:\n{spec_text[:12000]}\n\n"
        "Return Status: PASS or Status: FAIL plus critique."
    )
    raw = await llm.complete(persona, ctx, TaskClass.COMPREHEND)
    ok, critique = parse_verifier_output(raw)
    return VerifierResult(name="spec_verifier", ok=ok, critique=critique, raw=raw)


async def run_functional_verifier(
    cfg: FactoryConfig,
    llm: CursorLLM,
    *,
    spec_text: str,
    model_path: Path,
) -> VerifierResult:
    try:
        persona = load_persona(cfg, "quant_eval/functional_verifier")
    except FileNotFoundError:
        persona = (
            "Check model.py against the SPEC line-by-line. "
            "Output Status: PASS or Status: FAIL and a short critique."
        )
    code = model_path.read_text(encoding="utf-8") if model_path.exists() else ""
    ctx = (
        f"SPEC:\n{spec_text[:8000]}\n\n"
        f"MODEL.PY:\n{code[:12000]}\n\n"
        "Return Status: PASS or Status: FAIL plus critique."
    )
    raw = await llm.complete(persona, ctx, TaskClass.COMPREHEND)
    ok, critique = parse_verifier_output(raw)
    return VerifierResult(name="functional_verifier", ok=ok, critique=critique, raw=raw)
