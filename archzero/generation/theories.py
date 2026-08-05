"""Theory lenses from paper §5.1 — Paradigm Shifts and Local Optima.

Cross-domain transfer historically drove architecture leaps (dataflow←λ-calculus,
OoO←compiler scheduling, systolic←signal processing, SIMT←graphics). ArchZero
uses these lenses so Generation does not only refine within one paradigm.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TheoryLens:
    id: str
    name: str
    paper_hint: str
    prompts: tuple[str, ...]


# Exact families cited in arXiv:2604.03312 §5.1
THEORY_LENSES: tuple[TheoryLens, ...] = (
    TheoryLens(
        id="information_theory",
        name="Information theory",
        paper_hint="Shannon limits, entropy bounds, minimum-energy computation",
        prompts=(
            "What Shannon / entropy bound constrains this bottleneck?",
            "Can the architecture skip, compress, or approximate bits that carry no mutual information with the decision?",
        ),
    ),
    TheoryLens(
        id="sampling_theory",
        name="Sampling theory",
        paper_hint="Nyquist-style reasoning about approximation, compression, skipping",
        prompts=(
            "Is the compute/sample rate over-specified relative to the signal bandwidth of the workload?",
            "Where can Nyquist-style undersampling or event-driven sampling replace continuous work?",
        ),
    ),
    TheoryLens(
        id="control_theory",
        name="Control theory",
        paper_hint="Feedback, stability, adaptive / self-tuning systems",
        prompts=(
            "What feedback loop would make this mechanism self-tuning under workload drift?",
            "Are there stability / oscillation risks if predictors and throttles couple?",
        ),
    ),
    TheoryLens(
        id="queueing_theory",
        name="Queueing theory",
        paper_hint="Little's Law and scheduling under contention",
        prompts=(
            "What does Little's Law imply for concurrency vs latency at this resource?",
            "Which scheduling discipline (PS, SRPT, priority) matches the claimed bottleneck?",
        ),
    ),
    TheoryLens(
        id="statistical_mechanics",
        name="Statistical mechanics",
        paper_hint="Phase transitions and emergent behavior in large parallel systems",
        prompts=(
            "Is there a phase transition (contention / coherence / thermal) as scale grows?",
            "Which macroscopic order parameter should the architecture track?",
        ),
    ),
    TheoryLens(
        id="game_theory",
        name="Game theory",
        paper_hint="Nash equilibria and mechanism design for multi-agent resource allocation",
        prompts=(
            "If agents/clients compete for this resource, what is the equilibrium allocation?",
            "Can mechanism design (prices, priorities) replace ad-hoc QoS heuristics?",
        ),
    ),
    TheoryLens(
        id="category_theory",
        name="Category theory",
        paper_hint="Compositionality and abstraction for modular hardware",
        prompts=(
            "What is the compositional interface so this mechanism composes without breaking equivalence?",
            "Which abstraction boundary is currently leaking implementation detail?",
        ),
    ),
    TheoryLens(
        id="coding_theory",
        name="Coding theory",
        paper_hint="Error correction and redundancy under variation",
        prompts=(
            "Where should redundancy / ECC sit relative to energy and bandwidth budgets?",
            "Can coding-theoretic puncturing or unequal error protection reshape the reliability–PPA trade-off?",
        ),
    ),
)


THEORY_BY_ID = {t.id: t for t in THEORY_LENSES}


def theory_catalog_markdown() -> str:
    lines = [
        "# Theory lenses (paper §5.1)",
        "",
        "Cross-domain transfer is the historical engine of architecture paradigm shifts.",
        "Each lens must be considered during Lateral / Foundational expansion.",
        "",
    ]
    for t in THEORY_LENSES:
        lines.append(f"## {t.name} (`{t.id}`)")
        lines.append("")
        lines.append(f"Paper: {t.paper_hint}")
        lines.append("")
        for p in t.prompts:
            lines.append(f"- {p}")
        lines.append("")
    return "\n".join(lines)


def offline_theory_questions(
    *,
    title: str,
    symptom: str = "",
    limit_per_lens: int = 1,
) -> list[dict[str, str]]:
    """Deterministic theory-driven open questions (no LLM)."""
    out: list[dict[str, str]] = []
    ctx = f" for «{title}»"
    if symptom:
        ctx += f" (symptom: {symptom[:120]})"
    for t in THEORY_LENSES:
        for p in t.prompts[:limit_per_lens]:
            out.append(
                {
                    "theory": t.id,
                    "question": f"[{t.name}] {p}{ctx}",
                }
            )
    return out
