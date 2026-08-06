"""Funnel orchestrator: generate → Tier0..TierN with concurrency, resume, dedupe."""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from typing import Any, Awaitable, Callable

from archzero.config import FactoryConfig
from archzero.feedback.source import FeedbackSource, NullFeedbackSource
from archzero.funnel.dedup import dedup_candidates
from archzero.funnel.tier0 import evaluate_tier0
from archzero.funnel.tier1 import evaluate_tier1
from archzero.funnel.tier2 import evaluate_tier2
from archzero.funnel.tier3 import evaluate_tier3
from archzero.funnel.tier4 import evaluate_tier4
from archzero.funnel.tier5 import evaluate_tier5
from archzero.funnel.tier6 import evaluate_tier6
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

log = logging.getLogger("archzero.funnel")

TierFn = Callable[
    [FactoryConfig, Candidate, ProblemPackage, CursorLLM],
    Awaitable[Candidate],
]

TIER_ORDER = [Tier.T0, Tier.T1, Tier.T2, Tier.T3, Tier.T4, Tier.T5, Tier.T6]

TIER_FNS: dict[Tier, TierFn] = {
    Tier.T0: evaluate_tier0,
    Tier.T1: evaluate_tier1,
    Tier.T2: evaluate_tier2,
    Tier.T3: evaluate_tier3,
    Tier.T4: evaluate_tier4,
    Tier.T5: evaluate_tier5,
    Tier.T6: evaluate_tier6,
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


async def _run_tiers(
    cfg: FactoryConfig,
    store: Store,
    campaign: Campaign,
    problem: ProblemPackage,
    llm: CursorLLM,
    active: list[Candidate],
    through: Tier,
) -> list[Candidate]:
    stop_idx = TIER_ORDER.index(through)
    for tier in TIER_ORDER[: stop_idx + 1]:
        keep = cfg.quotas.keep_for(tier)
        fn = TIER_FNS[tier]

        async def run_one(cand: Candidate, _fn=fn, _tier=tier) -> Candidate:
            if cand.passed_through(_tier):
                return cand
            try:
                out = await _fn(cfg, cand, problem, llm)
                log.info(
                    "tier_done",
                    extra={
                        "campaign_id": campaign.id,
                        "candidate_id": cand.id,
                        "tier": _tier.value,
                        "status": out.status,
                    },
                )
                return out
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

        # Local worker pool (single-machine bounded concurrency)
        from archzero.worker.queue import LocalWorkerPool, WorkerJob

        pool = LocalWorkerPool(concurrency=cfg.budget.concurrency)

        async def _handle(job: WorkerJob[Candidate]) -> Candidate:
            out = await run_one(job.payload)
            store.save_candidate(out, campaign_id=campaign.id)
            for f in out.failures:
                store.save_failure(f)
            return out

        jobs = [WorkerJob(id=c.id, payload=c) for c in active]
        results = await pool.map(jobs, _handle)
        by_id = {r.job_id: r for r in results}
        next_active: list[Candidate] = []
        for c in active:
            r = by_id.get(c.id)
            if r is None or not r.ok or r.value is None:
                from archzero.funnel.taxonomy import attach_result
                from archzero.models import TierResult

                failed = attach_result(
                    c,
                    TierResult(
                        tier=tier,
                        verdict=Verdict.FAIL,
                        summary=f"worker error: {getattr(r, 'error', 'missing')}",
                        score=0.0,
                    ),
                    fail_message=getattr(r, "error", None) or "worker missing",
                )
                store.save_candidate(failed, campaign_id=campaign.id)
                next_active.append(failed)
            else:
                next_active.append(r.value)
        active = next_active

        def _passed_tier(c: Candidate, t: Tier = tier) -> bool:
            return c.passed_through(t)

        passed = [c for c in active if _passed_tier(c)]

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
    return active


async def run_campaign(
    cfg: FactoryConfig,
    *,
    spec_path: Path | None = None,
    pdf: Path | None = None,
    through: Tier = Tier.T2,
    name: str | None = None,
    seed_dir: Path | None = None,
    n_generate: int = 10,
    feedback: FeedbackSource | None = None,
    expand_frontier: bool = False,
    frontier_offline: bool = False,
    resume_campaign_id: str | None = None,
    auto_round: int = 0,
    problem: ProblemPackage | None = None,
    candidates_override: list[Candidate] | None = None,
) -> dict[str, Any]:
    cfg.ensure_dirs()
    store = Store(cfg.db_path)

    if resume_campaign_id:
        campaign = store.get_campaign(resume_campaign_id)
        if campaign is None:
            raise ValueError(f"unknown campaign: {resume_campaign_id}")
        problem = store.get_problem(campaign.problem_id)
        if problem is None:
            raise ValueError(f"missing problem for campaign {resume_campaign_id}")
        unique = store.list_candidates(campaign_id=campaign.id)
        # Resume incomplete candidates (not hard-failed past through)
        active_seed = [
            c
            for c in unique
            if c.status in {"new", "active"} or not c.hard_passed(through)
        ]
        if not active_seed:
            active_seed = unique
        campaign.status = "running"
        campaign.through_tier = through
        store.save_campaign(campaign)
        frontier_result: dict[str, Any] | None = None
        async with CursorLLM(cfg, store=store, campaign_id=campaign.id) as llm:
            active = await _run_tiers(
                cfg, store, campaign, problem, llm, active_seed, through
            )
            campaign.status = "done"
            store.save_campaign(campaign)
            all_c = store.list_candidates(campaign_id=campaign.id)
            return {
                "campaign_id": campaign.id,
                "problem_id": problem.id,
                "through": through.value,
                "generated": len(unique),
                "passed": sum(1 for c in all_c if c.hard_passed(through)),
                "failed": sum(1 for c in all_c if c.status == "failed"),
                "active": len(active),
                "resumed": True,
                "usage": store.usage_totals(campaign.id),
            }

    if problem is None:
        if spec_path is None:
            raise ValueError("spec_path or problem required")
        problem = load_problem_package(spec_path)
    store.save_problem(problem)

    feedback = feedback or NullFeedbackSource()
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
        meta={"expand_frontier": expand_frontier, "auto_round": auto_round},
    )
    store.save_campaign(campaign)

    frontier_result = None
    rounds_meta: list[dict[str, Any]] = []

    async with CursorLLM(cfg, store=store, campaign_id=campaign.id) as llm:
        if candidates_override is not None:
            candidates = candidates_override
        elif seed_dir and seed_dir.is_dir():
            candidates = _load_seeds(seed_dir, problem)
        elif pdf is not None:
            candidates = await cleanroom_ideate(
                cfg, pdf, problem=problem, n=n_generate, llm=llm
            )
        else:
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

        unique: list[Candidate] = []
        seen: set[str] = set()
        allow_existing = candidates_override is not None
        for c in candidates:
            h = c.content_hash or _content_hash(c.title, c.mechanism)
            c.content_hash = h
            if h in seen:
                continue
            if not allow_existing and store.find_by_hash(h):
                continue
            seen.add(h)
            if not c.workdir:
                work = cfg.scratch_dir / "campaigns" / campaign.id / c.id
                work.mkdir(parents=True, exist_ok=True)
                c.workdir = str(work)
            store.save_candidate(c, campaign_id=campaign.id)
            unique.append(c)

        # Semantic near-duplicate drop (token Jaccard) beyond exact content_hash
        deduped = dedup_candidates(unique, threshold=0.85)
        if deduped.dropped:
            campaign.meta["dedup_dropped"] = [
                {
                    "dropped": d.id,
                    "near": n.id,
                    "score": round(score, 3),
                }
                for d, n, score in deduped.dropped
            ]
            unique = deduped.kept

        active = await _run_tiers(cfg, store, campaign, problem, llm, unique, through)

        async def _do_frontier(pp: ProblemPackage) -> dict[str, Any]:
            from archzero.funnel.taxonomy import failures_as_signals
            from archzero.generation.frontier import expand_frontier as do_expand

            fails = store.list_failures(campaign_id=campaign.id)
            signals = failures_as_signals(fails)
            out_dir = cfg.scratch_dir / "campaigns" / campaign.id / "frontier"
            return await do_expand(
                cfg,
                pp,
                signals=signals,
                out_dir=out_dir,
                llm=None if frontier_offline else llm,
                offline=frontier_offline,
            )

        if expand_frontier:
            frontier_result = await _do_frontier(problem)
            for pp in frontier_result.get("packages") or []:
                store.save_problem(pp)
            campaign.meta["frontier_report"] = frontier_result.get("report_path")
            campaign.meta["paradigm_candidates"] = [
                c.id for c in (frontier_result.get("candidates") or [])
            ]

            # Auto rounds: run funnel on expanded problem packages
            from archzero.metrics.elimination import compute_elimination, snapshot_failures

            for r in range(max(0, auto_round)):
                packages = list(frontier_result.get("packages") or [])
                if not packages:
                    break
                pp = packages[min(r, len(packages) - 1)]
                round_name = f"{campaign.name} · frontier-round-{r + 1}"
                baseline_snap = snapshot_failures(store.list_failures(campaign_id=campaign.id))
                sub = await run_campaign(
                    cfg,
                    problem=pp,
                    through=through,
                    name=round_name,
                    n_generate=max(3, n_generate // 2),
                    expand_frontier=False,
                    auto_round=0,
                )
                follow_id = sub.get("campaign_id")
                if follow_id:
                    elim = compute_elimination(
                        store,
                        source_campaign_id=campaign.id,
                        followup_campaign_id=follow_id,
                    )
                    sub["elimination"] = elim
                    sub["source_failures"] = baseline_snap
                    sub["parent_campaign_id"] = campaign.id
                    follow_camp = store.get_campaign(follow_id)
                    if follow_camp is not None:
                        follow_camp.meta["parent_campaign_id"] = campaign.id
                        follow_camp.meta["source_failures"] = baseline_snap
                        follow_camp.meta["elimination"] = elim
                        store.save_campaign(follow_camp)
                rounds_meta.append(sub)
                # Expand again from latest
                if r + 1 < auto_round:
                    frontier_result = await _do_frontier(pp)
                    for npp in frontier_result.get("packages") or []:
                        store.save_problem(npp)

        campaign.status = "done"
        store.save_campaign(campaign)

        all_c = store.list_candidates(campaign_id=campaign.id)
        passed_n = sum(1 for c in all_c if c.hard_passed(through))
        failed_n = sum(1 for c in all_c if c.status == "failed")
        result: dict[str, Any] = {
            "campaign_id": campaign.id,
            "problem_id": problem.id,
            "through": through.value,
            "generated": len(unique),
            "passed": passed_n,
            "failed": failed_n,
            "active": len(active),
            "usage": store.usage_totals(campaign.id),
        }
        if frontier_result is not None:
            result["frontier"] = {
                "report_path": frontier_result.get("report_path"),
                "n_packages": len(frontier_result.get("packages") or []),
                "n_paradigm_candidates": len(frontier_result.get("candidates") or []),
                "offline": frontier_result.get("offline"),
                "kinds": [c.kind for c in (frontier_result.get("candidates") or [])],
            }
        if rounds_meta:
            result["auto_rounds"] = rounds_meta
        return result
