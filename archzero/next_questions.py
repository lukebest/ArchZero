"""Turn structured funnel failures into next-round open questions (offline).

Paper Feedback layer is deferred; this is a lightweight Generation-side
stand-in so researchers can recycle Tier failures into new problem frontiers
without deployment telemetry.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path

from archzero.config import FactoryConfig
from archzero.store.db import Store

KIND_PROMPTS = {
    "physics": "Which first-principles bound (bandwidth / Amdahl / conservation) should the next problem package encode as a hard REQ?",
    "novelty": "Is the scarce resource a sharper problem statement rather than another mechanism variant?",
    "correctness": "What executable acceptance check (ACC) would have caught this earlier in Tier2?",
    "performance": "Should Tier2/3 targets be tightened, or is the mechanism family exhausted under current DOF?",
    "feasibility": "Which area/power/timing non-goals (NNG) or DOF limits need to be explicit?",
    "equivalence": "Is the commit-point equivalence referee underspecified for Tier5 candidates?",
    "tooling": "Is the campaign blocked on sim/RTL tooling rather than idea quality?",
    "budget": "Should pool-2 tasks be deferred so Cursor Models pool can finish the funnel?",
    "unknown": "What missing clause would make this failure attributable?",
}


def questions_from_campaign(cfg: FactoryConfig, campaign_id: str, *, limit: int = 12) -> dict:
    store = Store(cfg.db_path)
    camp = store.get_campaign(campaign_id)
    if camp is None:
        raise ValueError(f"unknown campaign: {campaign_id}")

    fails = store.list_failures(campaign_id=campaign_id)
    counts = Counter(f.kind.value for f in fails)
    questions: list[str] = []

    for kind, n in counts.most_common():
        stem = KIND_PROMPTS.get(kind, KIND_PROMPTS["unknown"])
        questions.append(f"[{kind}×{n}] {stem}")

    # Concrete failure snippets as follow-ups
    for f in fails[: max(0, limit - len(questions))]:
        questions.append(
            f"[{f.tier.value}/{f.kind.value}] Revisit after: {f.message[:160]}"
        )

    # Deduplicate while preserving order
    seen: set[str] = set()
    uniq: list[str] = []
    for q in questions:
        if q not in seen:
            seen.add(q)
            uniq.append(q)
        if len(uniq) >= limit:
            break

    return {
        "campaign_id": campaign_id,
        "campaign_name": camp.name,
        "n_failures": len(fails),
        "taxonomy": dict(counts),
        "open_questions": uniq,
        "note": "Offline stand-in for paper Feedback→Generation; telemetry still deferred.",
    }


def write_questions_markdown(payload: dict, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        f"# Next open questions — {payload['campaign_name']}",
        "",
        f"Campaign `{payload['campaign_id']}` · failures={payload['n_failures']}",
        "",
        payload["note"],
        "",
        "## Taxonomy",
        "",
    ]
    for k, v in sorted(payload["taxonomy"].items(), key=lambda kv: -kv[1]):
        lines.append(f"- `{k}`: {v}")
    lines += ["", "## Questions for next Generation round", ""]
    for i, q in enumerate(payload["open_questions"], 1):
        lines.append(f"{i}. {q}")
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")
    return path
