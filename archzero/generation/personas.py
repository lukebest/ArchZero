"""Load review / reading personas from archzero/personas (vendored prompts)."""

from __future__ import annotations

from pathlib import Path

from archzero.config import FactoryConfig

# Minimal built-ins if the personas directory is missing or empty.
_FALLBACK_REVIEW = {
    "dr_microarch": (
        "You are a senior microarchitecture researcher. Critique proposals for "
        "pipeline correctness, area/timing realism, and whether claimed speedups "
        "survive first-principles bounds. Be adversarial but constructive."
    ),
    "prof_workloads": (
        "You are a workload and benchmarking expert. Challenge whether evaluation "
        "suites and metrics match the claimed bottleneck. Reject metric gaming."
    ),
    "prof_simtools": (
        "You are a simulation and modeling expert. Demand falsifiable models, "
        "clear assumptions, and Magic-Gap honesty between analytic and sim results."
    ),
}

_FALLBACK_SYNTH = (
    "You are a senior computer architecture synthesizer. "
    "Merge expert reviews into a decisive verdict with clear pass/fail "
    "and structured failure reasons."
)


def _personas_root(cfg: FactoryConfig) -> Path:
    return cfg.personas_root


def load_persona(cfg: FactoryConfig, name: str) -> str:
    """Load persona by stem or slash path, e.g. 'dr_microarch' or 'reading_assistant/foo'."""
    base = _personas_root(cfg)
    candidates = [
        base / f"{name}.md",
        base / name if name.endswith(".md") else None,
    ]
    for c in candidates:
        if c and c.is_file():
            return _strip(c.read_text(encoding="utf-8"))
    stem = name.split("/")[-1]
    matches = list(base.rglob(f"{stem}.md")) if base.is_dir() else []
    if matches:
        return _strip(matches[0].read_text(encoding="utf-8"))
    if name in _FALLBACK_REVIEW:
        return _FALLBACK_REVIEW[name]
    if name in ("synthesizer", "synthesizer_archresearch"):
        return _FALLBACK_SYNTH
    raise FileNotFoundError(f"persona not found: {name} under {base}")


def _strip(text: str) -> str:
    text = text.strip()
    if text.startswith("**System Prompt:**"):
        text = text[len("**System Prompt:**") :].strip()
    return text


def list_personas(cfg: FactoryConfig, subdir: str | None = None) -> list[str]:
    root = _personas_root(cfg) if subdir is None else _personas_root(cfg) / subdir
    if not root.is_dir():
        if subdir is None:
            return list(_FALLBACK_REVIEW.keys())
        return []
    out: list[str] = []
    base = _personas_root(cfg)
    for p in sorted(root.rglob("*.md")):
        if p.name.startswith("template_") or p.name.upper() == "README.MD":
            continue
        if p.name == "README.md":
            continue
        rel = p.relative_to(base).with_suffix("").as_posix()
        out.append(rel)
    return out


def default_review_personas(cfg: FactoryConfig) -> list[str]:
    preferred = ["dr_microarch", "prof_workloads", "prof_simtools"]
    available = set(list_personas(cfg))
    found = [p for p in preferred if p in available]
    if found:
        return found
    tops = [p for p in available if "/" not in p and not p.startswith("synthesizer")]
    return tops[:3] or list(_FALLBACK_REVIEW.keys())


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
    return _FALLBACK_SYNTH
