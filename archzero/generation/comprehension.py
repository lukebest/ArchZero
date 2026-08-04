"""Multi-persona paper comprehension (Generation layer)."""

from __future__ import annotations

import asyncio
from pathlib import Path

from archzero.config import FactoryConfig
from archzero.generation.pdfutil import extract_text
from archzero.generation.personas import default_reading_personas, load_persona
from archzero.llm.client import CursorLLM
from archzero.models import TaskClass


async def comprehend_paper(
    cfg: FactoryConfig,
    pdf: Path,
    *,
    persona_names: list[str] | None = None,
    llm: CursorLLM | None = None,
) -> str:
    names = persona_names or default_reading_personas(cfg)
    paper = extract_text(pdf)
    own = llm is None
    llm = llm or CursorLLM(cfg)
    if own:
        await llm.setup()

    async def one(name: str) -> str:
        persona = load_persona(cfg, name)
        ctx = (
            f"Paper path: {pdf}\n\n"
            "Distill this paper for architecture research. Return markdown with sections:\n"
            "## Bottlenecks\n## Assumptions\n## Attack surfaces\n## Open mechanisms\n"
            "## Risks / invalidating conditions\n\n"
            f"PAPER TEXT:\n{paper[:120000]}"
        )
        try:
            return f"### Persona: {name}\n\n" + await llm.complete(
                persona, ctx, TaskClass.COMPREHEND
            )
        except Exception as exc:  # noqa: BLE001
            return f"### Persona: {name}\n\n[ERROR] {exc}"

    parts = await asyncio.gather(*[one(n) for n in names])
    synthesis_prompt = (
        "Merge the following persona distillations into one structured insight brief "
        "with sections Bottlenecks / Assumptions / Attack surfaces / Candidate directions / Risks.\n\n"
        + "\n\n".join(parts)
    )
    try:
        merged = await llm.complete(
            "You are a research synthesizer for computer architecture.",
            synthesis_prompt,
            TaskClass.COMPREHEND,
        )
    except Exception as exc:  # noqa: BLE001
        merged = f"[synthesis error] {exc}\n\n" + "\n\n".join(parts)

    if own:
        await llm.aclose()
    return f"# Comprehension: {pdf.name}\n\n{merged}\n\n---\n\n## Raw persona notes\n\n" + "\n\n".join(parts)
