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

EXTRACT_PERSONA = """你提取体系结构研究问题内核。
只返回 JSON，键为：context, symptom, constraint, non_goals。
各字段内容用简体中文。不要提出解决方案，不要点名论文中的具体机制。"""

DESENSE_PERSONA = """你对问题内核做脱敏，去掉解法剧透。
删除机制名称、独特结构与发明性暗示；保留可测症状与硬约束。
返回相同键的 JSON；字段内容用简体中文。"""
IDEATE_PERSONA = """你是计算机体系结构机制发明者。
根据脱敏后的问题内核，提出一个具体机制方案。
只返回 JSON：{title, family, mechanism, expected_effect, risks, clause_refs}。
title、mechanism、expected_effect、risks 必须原生用简体中文撰写（不要英文稿）。
family 用简短英文标识（如 prefetch、noc_rg、cache）。
mechanism 需足够具体，以便后续建立解析模型。"""

SCORE_PERSONA = """你是 clean-room 出题评审。
将候选机制与全文论文对照。
只返回 JSON：{label: reproduce|equivalent|alternative|defective, score: 0-1, rationale, novelty_notes}。
rationale 与 novelty_notes 必须原生简体中文；label 保持英文枚举值。"""


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
