"""Funnel orchestrator: generate → Tier0..TierN with concurrency, resume, dedupe."""

from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path
from typing import Any, Awaitable, Callable

from archzero.config import FactoryConfig
from archzero.feedback.source import FeedbackSource, NullFeedbackSource
from archzero.funnel.tier0 import evaluate_tier0
from archzero.funnel.tier1 import evaluate_tier1
from archzero.funnel.tier2 import evaluate_tier2
from archzero.funnel.tier3 import evaluate_tier3
from archzero.funnel.tier4 import evaluate_tier4
from archzero.funnel.tier5 import evaluate_tier5
from archzero.generation.cleanroom import cleanroom_ideate
from archzero.llm.client import CursorLLM
from archzero.models import (
    Campaign,
    Candidate,
    ProblemPackage,
    TaskClass,
    Tier,
    Verdict,
)
from archzero.spec.ndf import load_problem_package
from archzero.store.db import Store

TierFn = Callable[
    [FactoryConfig, Candidate, ProblemPackage, CursorLLM],
    Awaitable[Candidate],
]

TIER_ORDER = [Tier.T0, Tier.T1, Tier.T2, Tier.T3, Tier.T4, Tier.T5]

TIER_FNS: dict[Tier, TierFn] = {
    Tier.T0: evaluate_tier0,
    Tier.T1: evaluate_tier1,
    Tier.T2: evaluate_tier2,
    Tier.T3: evaluate_tier3,
    Tier.T4: evaluate_tier4,
    Tier.T5: evaluate_tier5,
}


def _content_hash(title: str, mechanism: str) -> str:
    return hashlib.sha256((title + "\n" + mechanism).encode()).hexdigest()[:16]


def _load_seeds(seed_dir: Path, problem: ProblemPackage) -> list[Candidate]:
    cands: list[Candidate] = []
    for path in sorted(seed_dir.glob("*.md")):
        text = path.read_text(encoding="utf-8")
        lines = text.splitlines()
        title = path.stem
        family = "unclassified"
        body_lines = []
        for ln in lines:
            if ln.startswith("# "):
                title = ln[2:].strip()
            elif ln.lower().startswith("family:"):
                family = ln.split(":", 1)[1].strip()
            else:
                body_lines.append(ln)
        mechanism = "\n".join(body_lines).strip()
        cands.append(
            Candidate(
                problem_id=problem.id,
                title=title,
                mechanism=mechanism,
                family=family,
                content_hash=_content_hash(title, mechanism),
            )
        )
    return cands


async def run_campaign(
    cfg: FactoryConfig,
    *,
    spec_path: Path,
    pdf: Path | None = None,
    through: Tier = Tier.T2,
    name: str | None = None,
    seed_dir: Path | None = None,
    n_generate: int = 10,
    feedback: FeedbackSource | None = None,
) -> dict[str, Any]:
    cfg.ensure_dirs()
    store = Store(cfg.db_path)
    problem = load_problem_package(spec_path)
    store.save_problem(problem)

    feedback = feedback or NullFeedbackSource()
    # Hook point for telemetry (deferred)
    try:
        drift = feedback.drift_questions()
        if drift:
            problem.open_questions.extend(drift)
    except NotImplementedError:
        pass

    campaign = Campaign(
        name=name or f"{problem.title} → {through.value}",
        problem_id=problem.id,
        through_tier=through,
    )
    store.save_campaign(campaign)

    async with CursorLLM(cfg, store=store, campaign_id=campaign.id) as llm:
        # Generate or load seeds
        if seed_dir and seed_dir.is_dir():
            candidates = _load_seeds(seed_dir, problem)
        elif pdf is not None:
            candidates = await cleanroom_ideate(
                cfg, pdf, problem=problem, n=n_generate, llm=llm
            )
        else:
            # Spec-only synthetic ideation without PDF
            from archzero.generation.cleanroom import IDEATE_PERSONA, _parse_json

            candidates = []
            for i in range(n_generate):
                prompt = (
                    f"Independent generation #{i + 1}. Explore DOF in the problem.\n"
                    f"TITLE: {problem.title}\n"
                    + "\n".join(f"{c.id}: {c.text}" for c in problem.clauses)
                )
                try:
                    data = _parse_json(
                        await llm.complete(
                            IDEATE_PERSONA,
                            prompt,
                            TaskClass.IDEATE,
                            expect_json=True,
                        )
                    )
                except Exception as exc:  # noqa: BLE001
                    data = {
                        "title": f"Heuristic candidate {i + 1}",
                        "family": "prefetch",
                        "mechanism": f"Fallback mechanism due to error: {exc}. "
                        "Use a dead-block predictor + filtered prefetch.",
                    }
                title = str(data.get("title") or f"Candidate {i + 1}")
                mechanism = str(data.get("mechanism") or "")
                candidates.append(
                    Candidate(
                        problem_id=problem.id,
                        title=title,
                        mechanism=mechanism,
                        family=str(data.get("family") or "unclassified"),
                        clause_refs=list(data.get("clause_refs") or []),
                        content_hash=_content_hash(title, mechanism),
                    )
                )

        # Dedupe
        unique: list[Candidate] = []
        seen: set[str] = set()
        for c in candidates:
            h = c.content_hash or _content_hash(c.title, c.mechanism)
            c.content_hash = h
            if h in seen or store.find_by_hash(h):
                continue
            seen.add(h)
            work = cfg.scratch_dir / "campaigns" / campaign.id / c.id
            work.mkdir(parents=True, exist_ok=True)
            c.workdir = str(work)
            store.save_candidate(c, campaign_id=campaign.id)
            unique.append(c)

        # Run tiers
        active = unique
        stop_idx = TIER_ORDER.index(through)
        for tier in TIER_ORDER[: stop_idx + 1]:
            keep = cfg.quotas.keep_for(tier)
            fn = TIER_FNS[tier]

            async def run_one(cand: Candidate, _fn=fn, _tier=tier) -> Candidate:
                # Resume: skip if already passed this tier
                if cand.passed_through(_tier):
                    return cand
                try:
                    return await _fn(cfg, cand, problem, llm)
                except Exception as exc:  # noqa: BLE001
                    from archzero.funnel.taxonomy import attach_result
                    from archzero.models import TierResult

                    return attach_result(
                        cand,
                        TierResult(
                            tier=_tier,
                            verdict=Verdict.FAIL,
                            summary=f"exception: {exc}",
                            score=0.0,
                        ),
                        fail_message=str(exc),
                    )

            # Concurrent evaluation
            sem = asyncio.Semaphore(cfg.budget.concurrency)

            async def guarded(c: Candidate) -> Candidate:
                async with sem:
                    out = await run_one(c)
                    store.save_candidate(out, campaign_id=campaign.id)
                    for f in out.failures:
                        store.save_failure(f)
                    return out

            active = list(await asyncio.gather(*[guarded(c) for c in active]))

            def _passed_tier(c: Candidate, t: Tier = tier) -> bool:
                for tr in c.tier_history:
                    if tr.tier == t and tr.verdict in {
                        Verdict.PASS,
                        Verdict.UNAVAILABLE,
                    }:
                        return True
                return False

            passed = [c for c in active if _passed_tier(c)]
            # Rank by score
            def score_of(c: Candidate) -> float:
                for t in reversed(c.tier_history):
                    if t.tier == tier and t.score is not None:
                        return t.score
                return 0.0

            passed.sort(key=score_of, reverse=True)
            active = passed[:keep]
            for c in active:
                c.status = "active"
                store.save_candidate(c, campaign_id=campaign.id)

        campaign.status = "done"
        store.save_campaign(campaign)

        all_c = store.list_candidates(campaign_id=campaign.id)
        passed_n = sum(1 for c in all_c if c.passed_through(through))
        failed_n = sum(1 for c in all_c if c.status == "failed")
        return {
            "campaign_id": campaign.id,
            "problem_id": problem.id,
            "through": through.value,
            "generated": len(unique),
            "passed": passed_n,
            "failed": failed_n,
            "active": len(active),
            "usage": store.usage_totals(campaign.id),
        }
