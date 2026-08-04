"""Tier 1 — adversarial multi-expert review + synthesizer (Gauntlet protocol)."""

from __future__ import annotations

import asyncio
import json
import re

from archzero.config import FactoryConfig
from archzero.funnel.taxonomy import attach_result
from archzero.generation.personas import (
    default_review_personas,
    load_persona,
    load_synthesizer,
)
from archzero.llm.client import CursorLLM
from archzero.models import Candidate, ProblemPackage, TaskClass, Tier, TierResult, Verdict


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
        return {"verdict": "fail", "summary": text[:800], "score": 0.0}


async def evaluate_tier1(
    cfg: FactoryConfig,
    candidate: Candidate,
    problem: ProblemPackage,
    llm: CursorLLM,
    *,
    persona_names: list[str] | None = None,
) -> Candidate:
    names = persona_names or default_review_personas(cfg)
    constraints = "\n".join(f"{c.id}: {c.text}" for c in problem.clauses)
    base_ctx = (
        f"PROBLEM:\n{problem.title}\n{constraints}\n\n"
        f"PROPOSAL TITLE: {candidate.title}\nFAMILY: {candidate.family}\n\n"
        f"{candidate.mechanism}\n\n"
        "Write a critical expert review. End with a JSON block:\n"
        '{"lean":"pass|fail","score":0-1,"key_risks":[],"fixes":[]}'
    )

    async def review(name: str) -> str:
        persona = load_persona(cfg, name)
        try:
            return f"## {name}\n\n" + await llm.complete(
                persona, base_ctx, TaskClass.COMPREHEND
            )
        except Exception as exc:  # noqa: BLE001
            return f"## {name}\n\n[ERROR] {exc}"

    reviews = await asyncio.gather(*[review(n) for n in names])
    synth_persona = load_synthesizer(cfg)
    synth_ctx = (
        "Synthesize the expert reviews into a final gate decision for the funnel.\n"
        "Return JSON ONLY: "
        '{"verdict":"pass|fail","score":0-1,"summary":"...","clause_refs":[],'
        '"failure_modes":[]}\n\n'
        + "\n\n".join(reviews)
    )
    try:
        data = _parse_json(
            await llm.complete(
                synth_persona, synth_ctx, TaskClass.SYNTHESIZE, expect_json=True
            )
        )
    except Exception as exc:  # noqa: BLE001
        data = {"verdict": "fail", "summary": f"tier1 synth error: {exc}", "score": 0.0}

    verdict = Verdict.PASS if str(data.get("verdict", "")).lower() == "pass" else Verdict.FAIL
    result = TierResult(
        tier=Tier.T1,
        verdict=verdict,
        score=float(data.get("score") or 0.0),
        summary=str(data.get("summary") or ""),
        metrics={
            "failure_modes": data.get("failure_modes") or [],
            "reviews": [r[:2000] for r in reviews],
        },
        clause_refs=list(data.get("clause_refs") or candidate.clause_refs),
    )
    # Persist reviews into candidate workdir metrics reference
    candidate.metrics["tier1_reviews"] = len(reviews)
    return attach_result(candidate, result, fail_message=result.summary)
