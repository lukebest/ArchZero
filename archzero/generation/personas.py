"""Load Gauntlet personas (read-only submodule reuse)."""

from __future__ import annotations

from pathlib import Path

from archzero.config import FactoryConfig


def load_persona(cfg: FactoryConfig, name: str) -> str:
    """Load persona by stem or slash path, e.g. 'dr_microarch' or 'reading_assistant/foo'."""
    base = cfg.gauntlet_personas
    # Try exact relative path
    candidates = [
        base / f"{name}.md",
        base / name if name.endswith(".md") else None,
    ]
    for c in candidates:
        if c and c.is_file():
            return _strip(c.read_text(encoding="utf-8"))
    # Fuzzy: search under base
    stem = name.split("/")[-1]
    matches = list(base.rglob(f"{stem}.md"))
    if matches:
        return _strip(matches[0].read_text(encoding="utf-8"))
    raise FileNotFoundError(f"persona not found: {name} under {base}")


def _strip(text: str) -> str:
    text = text.strip()
    if text.startswith("**System Prompt:**"):
        text = text[len("**System Prompt:**") :].strip()
    return text


def list_personas(cfg: FactoryConfig, subdir: str | None = None) -> list[str]:
    root = cfg.gauntlet_personas if subdir is None else cfg.gauntlet_personas / subdir
    if not root.is_dir():
        return []
    out: list[str] = []
    for p in sorted(root.rglob("*.md")):
        if p.name.startswith("template_"):
            continue
        rel = p.relative_to(cfg.gauntlet_personas).with_suffix("").as_posix()
        out.append(rel)
    return out


def default_review_personas(cfg: FactoryConfig) -> list[str]:
    preferred = ["dr_microarch", "dr_memory_systems", "dr_accelerator"]
    available = set(list_personas(cfg))
    found = [p for p in preferred if p in available]
    if found:
        return found
    # Fall back to any top-level personas
    tops = [p for p in available if "/" not in p]
    return tops[:3] or ["synthesizer"]


def default_reading_personas(cfg: FactoryConfig, limit: int = 3) -> list[str]:
    readers = list_personas(cfg, "reading_assistant")
    if readers:
        return readers[:limit]
    return default_review_personas(cfg)


def load_synthesizer(cfg: FactoryConfig) -> str:
    for name in ("synthesizer_archresearch", "synthesizer"):
        try:
            return load_persona(cfg, name)
        except FileNotFoundError:
            continue
    return (
        "You are a senior computer architecture synthesizer. "
        "Merge expert reviews into a decisive verdict with clear pass/fail "
        "and structured failure reasons."
    )
