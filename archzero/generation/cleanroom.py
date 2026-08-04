"""Clean-room ideation protocol (§4.3 of the paper).

Phases:
1. Extract [CONTEXT][SYMPTOM][CONSTRAINT] from first 3 pages only
2. Desensitize / strip solution spoilers
3. N independent mechanism generations
4. Score vs full paper: reproduce | equivalent | alternative | defective
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
from pathlib import Path

from archzero.config import FactoryConfig
from archzero.generation.pdfutil import extract_text, first_n_pages
from archzero.llm.client import CursorLLM
from archzero.models import Candidate, ProblemPackage, TaskClass

EXTRACT_PERSONA = """You extract architecture research problem kernels.
Output ONLY a JSON object with keys: context, symptom, constraint, non_goals.
Do not propose solutions. Do not mention named mechanisms from the paper."""

DESENSE_PERSONA = """You redact solution spoilers from a problem kernel.
Remove mechanism names, unique structures, and inventiveness hints.
Keep measurable symptoms and hard constraints. Return JSON with same keys."""

IDEATE_PERSONA = """You invent novel computer-architecture mechanisms.
Given a desensitized problem kernel, propose ONE concrete mechanism.
Return JSON: {title, family, mechanism, expected_effect, risks, clause_refs}.
mechanism must be detailed enough to later build an analytic model."""

SCORE_PERSONA = """You are an ideation judge for clean-room evaluation.
Compare a candidate mechanism to the full paper.
Return JSON: {label: reproduce|equivalent|alternative|defective, score: 0-1, rationale, novelty_notes}."""


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
        return {"raw": text}


async def cleanroom_ideate(
    cfg: FactoryConfig,
    pdf: Path,
    *,
    problem: ProblemPackage | None = None,
    n: int = 5,
    llm: CursorLLM | None = None,
) -> list[Candidate]:
    own = llm is None
    llm = llm or CursorLLM(cfg)
    if own:
        await llm.setup()

    head = first_n_pages(pdf, 3)
    full = extract_text(pdf)

    extract_ctx = f"FIRST THREE PAGES ONLY:\n\n{head[:80000]}"
    if problem:
        extract_ctx += (
            "\n\nAlso respect this problem package clauses:\n"
            + "\n".join(f"{c.id}: {c.text[:200]}" for c in problem.clauses)
        )
    kernel = _parse_json(
        await llm.complete(EXTRACT_PERSONA, extract_ctx, TaskClass.IDEATE, expect_json=True)
    )
    redacted = _parse_json(
        await llm.complete(
            DESENSE_PERSONA,
            json.dumps(kernel, indent=2),
            TaskClass.IDEATE,
            expect_json=True,
        )
    )

    async def gen_one(i: int) -> Candidate:
        prompt = (
            f"Independent generation #{i + 1} of {n}. Be diverse; explore different families.\n"
            f"KERNEL:\n{json.dumps(redacted, indent=2)}"
        )
        data = _parse_json(
            await llm.complete(IDEATE_PERSONA, prompt, TaskClass.IDEATE, expect_json=True)
        )
        title = str(data.get("title") or f"Mechanism {i + 1}")
        mechanism = str(data.get("mechanism") or data.get("raw") or "")
        family = str(data.get("family") or "unclassified")
        content_hash = hashlib.sha256(
            (title + "\n" + mechanism).encode("utf-8")
        ).hexdigest()[:16]
        return Candidate(
            problem_id=problem.id if problem else "ad-hoc",
            title=title,
            mechanism=mechanism,
            family=family,
            clause_refs=list(data.get("clause_refs") or []),
            content_hash=content_hash,
            metrics={
                "expected_effect": data.get("expected_effect"),
                "risks": data.get("risks"),
                "kernel": redacted,
            },
        )

    cands = list(await asyncio.gather(*[gen_one(i) for i in range(n)]))

    # Score against full paper
    async def score_one(c: Candidate) -> Candidate:
        prompt = (
            f"CANDIDATE:\n{c.title}\n\n{c.mechanism}\n\n"
            f"FULL PAPER TEXT (for judging only):\n{full[:100000]}"
        )
        try:
            data = _parse_json(
                await llm.complete(
                    SCORE_PERSONA, prompt, TaskClass.IDEATE, expect_json=True
                )
            )
            c.metrics["cleanroom_label"] = data.get("label")
            c.metrics["cleanroom_score"] = data.get("score")
            c.metrics["cleanroom_rationale"] = data.get("rationale")
        except Exception as exc:  # noqa: BLE001
            c.metrics["cleanroom_error"] = str(exc)
        return c

    cands = list(await asyncio.gather(*[score_one(c) for c in cands]))
    if own:
        await llm.aclose()
    return cands
