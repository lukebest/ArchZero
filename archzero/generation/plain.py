"""Rewrite a metaphorical mechanism into engineer-readable Chinese."""

from __future__ import annotations

import json

from archzero.config import FactoryConfig
from archzero.llm.language import MECHANISM_STYLE
from archzero.models import Candidate, TaskClass

REWRITE_PERSONA = f"""你把体系结构机制改写成芯片工程师能实现的说明。
保留原方案的真实硬件决策，删除隐喻、跨学科专名和空话。
只返回 JSON：{{"title_plain": "...", "mechanism_plain": "..."}}
title_plain 是一句话硬件标题。
mechanism_plain 必须遵守下面的写法。

{MECHANISM_STYLE}
"""


def _parse_json(text: str) -> dict:
    text = (text or "").strip()
    if text.startswith("```"):
        lines = text.splitlines()
        text = "\n".join(lines[1:-1] if lines and lines[-1].strip() == "```" else lines[1:])
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start >= 0 and end > start:
            try:
                return json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                return {}
        return {}


def has_plain_rewrite(candidate: Candidate) -> bool:
    metrics = candidate.metrics or {}
    plain = str(metrics.get("mechanism_plain") or "").strip()
    return bool(plain) and ("决策：" in plain or "状态：" in plain or len(plain) > 40)


async def rewrite_mechanism_plain(
    cfg: FactoryConfig,
    candidate: Candidate,
    *,
    force: bool = False,
) -> dict[str, str]:
    """Fill ``title_plain`` / ``mechanism_plain`` on candidate.metrics."""
    metrics = dict(candidate.metrics or {})
    if not force and has_plain_rewrite(candidate):
        return {
            "title_plain": str(metrics.get("title_plain") or candidate.title),
            "mechanism_plain": str(metrics["mechanism_plain"]),
            "cached": True,
        }

    from archzero.llm.client import CursorLLM

    prompt = (
        f"原标题：{candidate.title}\n\n"
        f"原机制：\n{candidate.mechanism}\n"
    )
    iso = metrics.get("diverge_isomorphism")
    if iso:
        prompt += f"\n原 isomorphism（仅供理解，不要写进 mechanism_plain）：{iso}\n"
    async with CursorLLM(cfg) as llm:
        raw = await llm.complete(
            REWRITE_PERSONA,
            prompt,
            TaskClass.ANALYTIC,
            expect_json=True,
        )
    data = _parse_json(raw)
    title_plain = str(data.get("title_plain") or candidate.title).strip()
    mechanism_plain = str(data.get("mechanism_plain") or "").strip()
    if not mechanism_plain:
        raise ValueError("rewrite returned empty mechanism_plain")
    metrics["title_plain"] = title_plain
    metrics["mechanism_plain"] = mechanism_plain
    candidate.metrics = metrics
    return {
        "title_plain": title_plain,
        "mechanism_plain": mechanism_plain,
        "cached": False,
    }
