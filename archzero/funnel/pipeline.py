"""Funnel orchestrator: generate → Tier0..TierN with concurrency, resume, dedupe."""

from __future__ import annotations

import asyncio
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
from archzero.sim.headlines import stored_rank
from archzero.spec.acc_parse import parse_acceptance_thresholds
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

HALTED = frozenset({"stopped", "paused"})


def campaign_halted(store: Store, campaign_id: str) -> bool:
    camp = store.get_campaign(campaign_id)
    return camp is None or camp.status in HALTED


def _sync_progress(store: Store, campaign: Campaign, **fields: Any) -> bool:
    """Write progress without clobbering a dashboard stop. True if halted."""
    fresh = store.get_campaign(campaign.id)
    if fresh is None:
        return True
    if fresh.status in HALTED:
        campaign.status = fresh.status
        campaign.meta = fresh.meta
        return True
    meta = dict(fresh.meta or {})
    progress = dict(meta.get("progress") or {})
    progress.update(fields)
    meta["progress"] = progress
    fresh.meta = meta
    store.save_campaign(fresh)
    campaign.meta = meta
    campaign.status = fresh.status
    return False


def _halted_result(
    store: Store, campaign: Campaign, problem: ProblemPackage, through: Tier
) -> dict[str, Any]:
    campaign.status = "stopped"
    store.save_campaign(campaign)
    all_c = store.list_candidates(campaign_id=campaign.id)
    return {
        "campaign_id": campaign.id,
        "problem_id": problem.id,
        "through": through.value,
        "generated": len(all_c),
        "passed": sum(1 for c in all_c if c.hard_passed(through)),
        "failed": sum(1 for c in all_c if c.status == "failed"),
        "active": sum(1 for c in all_c if c.status in {"new", "active"}),
        "stopped": True,
        "usage": store.usage_totals(campaign.id),
        "acc": (campaign.meta or {}).get("acc"),
        "divergence": (campaign.meta or {}).get("divergence"),
    }


def _content_hash(title: str, mechanism: str) -> str:
    return hashlib.sha256((title + "\n" + mechanism).encode()).hexdigest()[:16]


def acc_gate_for_campaign(
    cfg: FactoryConfig, problem: ProblemPackage, through: Tier
) -> tuple[Tier, dict[str, Any]]:
    """How far can the numeric tiers honestly grade this problem package?

    Tier0/Tier1 read clause text and stay useful in any domain. Tier2+ only
    grades metrics this repo can measure. A spec whose acceptance criteria
    have no evaluator is clamped to Tier1 rather than spending a few hundred
    LLM calls on a verdict that would have been about MPKI.
    """
    th = parse_acceptance_thresholds(problem)
    from archzero.sim.registry import backend_name_for_domain

    resolved_backend, route_reason = backend_name_for_domain(
        cfg.sim.backend or "stub", th.domain
    )
    meta: dict[str, Any] = {
        "domain": th.domain,
        "gradable": th.gradable,
        "report_only": th.report_only,
        "measurable_performance": list(th.measurable_performance),
        "defaulted_gates": sorted(th.defaulted),
        "unmeasurable_metrics": list(th.unmeasurable_metrics),
        "backend": resolved_backend,
    }
    if route_reason:
        meta["backend_route"] = route_reason
    if (
        cfg.funnel.strict_acc
        and not th.gradable
        and TIER_ORDER.index(through) > TIER_ORDER.index(Tier.T1)
    ):
        meta["clamped_from"] = through.value
        meta["reason"] = th.ungradable_reason()
        return Tier.T1, meta
    return through, meta


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



def candidate_keep_score(candidate: Candidate, tier: Tier) -> float:
    """Sort key for the keep-N cut. Never invent MPKI=0 for off-cache work."""
    stored = None
    for t in reversed(candidate.tier_history):
        if t.tier == tier and t.score is not None:
            stored = float(t.score)
            break
    return stored_rank(
        candidate.metrics, family=candidate.family, stored_score=stored
    )


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
        if campaign_halted(store, campaign.id):
            return active
        if _sync_progress(store, campaign, phase="funnel", tier=tier.value):
            return active
        keep = cfg.quotas.keep_for(tier)
        fn = TIER_FNS[tier]

        async def run_one(cand: Candidate, _fn=fn, _tier=tier) -> Candidate:
            if campaign_halted(store, campaign.id):
                return cand
            from archzero.funnel.errors import (
                infra_result,
                is_infra_error,
                strip_retryable_for_tier,
                tier_settled,
            )

            if tier_settled(cand, _tier):
                return cand

            strip_retryable_for_tier(cand, _tier)
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

                if is_infra_error(str(exc), exc):
                    return attach_result(cand, infra_result(_tier, f"exception: {exc}"))
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

        def _persist(out: Candidate) -> Candidate:
            store.save_candidate(out, campaign_id=campaign.id)
            for f in out.failures:
                store.save_failure(f)
            return out

        batch_size = cfg.funnel.tier0_batch_size if tier is Tier.T0 else 0
        done_by_id: dict[str, Candidate] = {}
        errors: dict[str, str] = {}

        if batch_size > 0:
            from archzero.funnel.tier0 import evaluate_tier0_batch

            chunks = [
                active[i : i + batch_size] for i in range(0, len(active), batch_size)
            ]

            async def _handle_batch(job: WorkerJob[list[Candidate]]) -> list[Candidate]:
                todo = [c for c in job.payload if not c.passed_through(Tier.T0)]
                skipped = [c for c in job.payload if c.passed_through(Tier.T0)]
                screened = await evaluate_tier0_batch(cfg, todo, problem, llm)
                return skipped + [_persist(c) for c in screened]

            batch_jobs = [
                WorkerJob(id=f"batch-{i}", payload=chunk)
                for i, chunk in enumerate(chunks)
            ]
            for i, res in enumerate(
                await pool.map(
                    batch_jobs,
                    _handle_batch,
                    should_stop=lambda: campaign_halted(store, campaign.id),
                )
            ):
                if res.ok and res.value is not None:
                    for out in res.value:
                        done_by_id[out.id] = out
                else:
                    for c in chunks[i]:
                        errors[c.id] = res.error or "batch worker missing"
        else:

            async def _handle(job: WorkerJob[Candidate]) -> Candidate:
                return _persist(await run_one(job.payload))

            jobs = [WorkerJob(id=c.id, payload=c) for c in active]
            for res in await pool.map(
                jobs,
                _handle,
                should_stop=lambda: campaign_halted(store, campaign.id),
            ):
                if res.ok and res.value is not None:
                    done_by_id[res.job_id] = res.value
                else:
                    errors[res.job_id] = res.error or "worker missing"

        next_active: list[Candidate] = []
        for c in active:
            out = done_by_id.get(c.id)
            if out is None:
                from archzero.funnel.taxonomy import attach_result
                from archzero.models import TierResult

                reason = errors.get(c.id, "worker missing")
                out = attach_result(
                    c,
                    TierResult(
                        tier=tier,
                        verdict=Verdict.FAIL,
                        summary=f"worker error: {reason}",
                        score=0.0,
                    ),
                    fail_message=reason,
                )
                store.save_candidate(out, campaign_id=campaign.id)
            next_active.append(out)
        active = next_active

        def _passed_tier(c: Candidate, t: Tier = tier) -> bool:
            from archzero.funnel.errors import advances_after_tier

            return advances_after_tier(
                c, t, tier1_advisory=cfg.funnel.tier1_advisory
            )

        passed = [c for c in active if _passed_tier(c)]

        passed.sort(key=lambda c: candidate_keep_score(c, tier), reverse=True)
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
    use_divergence: bool | None = None,
    diverge_cells: int | None = None,
    diverge_per_cell: int | None = None,
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
        from archzero.funnel.errors import needs_resume, soften_infra_failures

        active_seed: list[Candidate] = []
        for c in unique:
            if soften_infra_failures(c):
                store.save_candidate(c, campaign_id=campaign.id)
            if needs_resume(
                c, through, tier1_advisory=cfg.funnel.tier1_advisory
            ):
                active_seed.append(c)
        campaign.status = "running"
        campaign.through_tier = through
        store.save_campaign(campaign)
        try:
            async with CursorLLM(cfg, store=store, campaign_id=campaign.id) as llm:
                if campaign_halted(store, campaign.id):
                    return _halted_result(store, campaign, problem, through)
                active = await _run_tiers(
                    cfg, store, campaign, problem, llm, active_seed, through
                )
                if campaign_halted(store, campaign.id):
                    return _halted_result(store, campaign, problem, through)
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
                    "retried": len(active_seed),
                    "usage": store.usage_totals(campaign.id),
                }
        except asyncio.CancelledError:
            return _halted_result(store, campaign, problem, through)
        except Exception:
            campaign.status = "failed"
            store.save_campaign(campaign)
            raise

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

    through, acc_meta = acc_gate_for_campaign(cfg, problem, through)

    campaign = Campaign(
        name=name or f"{problem.title} → {through.value}",
        problem_id=problem.id,
        through_tier=through,
        status="running",
        meta={
            "expand_frontier": expand_frontier,
            "auto_round": auto_round,
            "acc": acc_meta,
            "progress": {"phase": "start", "generated": 0},
        },
    )
    store.save_campaign(campaign)

    frontier_result = None
    rounds_meta: list[dict[str, Any]] = []

    want_diverge = cfg.divergence.enabled if use_divergence is None else use_divergence

    def _persist_idea(c: Candidate) -> None:
        if not c.workdir:
            work = cfg.scratch_dir / "campaigns" / campaign.id / c.id
            work.mkdir(parents=True, exist_ok=True)
            c.workdir = str(work)
        store.save_candidate(c, campaign_id=campaign.id)

    def _on_diverge_cell(cands: list[Candidate]) -> None:
        for c in cands:
            h = c.content_hash or _content_hash(c.title, c.mechanism)
            c.content_hash = h
            prior = store.find_by_hash(h)
            if prior is not None and prior.id != c.id:
                continue
            _persist_idea(c)
        n = len(store.list_candidates(campaign_id=campaign.id))
        _sync_progress(
            store,
            campaign,
            phase="diverge",
            generated=n,
            n_cells=diverge_cells or cfg.divergence.n_cells,
            per_cell=diverge_per_cell or cfg.divergence.per_cell,
        )

    try:
        async with CursorLLM(cfg, store=store, campaign_id=campaign.id) as llm:
            if campaign_halted(store, campaign.id):
                return _halted_result(store, campaign, problem, through)
            if candidates_override is not None:
                candidates = candidates_override
            elif want_diverge:
                from archzero.generation.divergence import diverge, pool_stats

                n_cells = diverge_cells or cfg.divergence.n_cells
                per_cell = diverge_per_cell or cfg.divergence.per_cell
                _sync_progress(
                    store,
                    campaign,
                    phase="diverge",
                    generated=0,
                    n_cells=n_cells,
                    per_cell=per_cell,
                )
                candidates = await diverge(
                    cfg,
                    problem,
                    n_cells=n_cells,
                    per_cell=per_cell,
                    lens_ids=cfg.divergence.lens_whitelist or None,
                    domain_ids=cfg.divergence.domain_whitelist or None,
                    llm=llm,
                    on_candidates=_on_diverge_cell,
                    should_stop=lambda: campaign_halted(store, campaign.id),
                )
                fresh = store.get_campaign(campaign.id)
                if fresh is None or fresh.status in HALTED:
                    return _halted_result(store, fresh or campaign, problem, through)
                fresh.meta = dict(fresh.meta or {})
                fresh.meta["divergence"] = {
                    "n_cells": n_cells,
                    "per_cell": per_cell,
                    "generated": len(candidates),
                    "by_axis": pool_stats(candidates),
                }
                store.save_campaign(fresh)
                campaign.meta = fresh.meta
                campaign.status = fresh.status
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
                    if campaign_halted(store, campaign.id):
                        return _halted_result(store, campaign, problem, through)
                    prompt = (
                        f"Independent generation #{i + 1}. Explore DOF in the problem.\n"
                        f"Write title/mechanism/expected_effect/risks in Simplified Chinese.\n"
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
                            "title": f"启发式候选 {i + 1}",
                            "family": "prefetch",
                            "mechanism": (
                                f"生成失败，使用回退机制说明：{exc}。"
                                "建议采用死块预测器（dead-block predictor）"
                                "并配合过滤式预取（filtered prefetch）。"
                            ),
                        }
                    title = str(data.get("title") or f"候选 {i + 1}")
                    mechanism = str(data.get("mechanism") or "")
                    cand = Candidate(
                        problem_id=problem.id,
                        title=title,
                        mechanism=mechanism,
                        family=str(data.get("family") or "unclassified"),
                        clause_refs=list(data.get("clause_refs") or []),
                        content_hash=_content_hash(title, mechanism),
                    )
                    candidates.append(cand)
                    _persist_idea(cand)
                    _sync_progress(
                        store, campaign, phase="ideate", generated=len(candidates)
                    )

            unique: list[Candidate] = []
            seen: set[str] = set()
            allow_existing = candidates_override is not None
            for c in candidates:
                h = c.content_hash or _content_hash(c.title, c.mechanism)
                c.content_hash = h
                if h in seen:
                    continue
                prior = store.find_by_hash(h)
                if not allow_existing and prior is not None and prior.id != c.id:
                    continue
                seen.add(h)
                _persist_idea(c)
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

            if campaign_halted(store, campaign.id):
                return _halted_result(store, campaign, problem, through)

            active = await _run_tiers(cfg, store, campaign, problem, llm, unique, through)
            if campaign_halted(store, campaign.id):
                return _halted_result(store, campaign, problem, through)

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
                    if r + 1 < auto_round:
                        frontier_result = await _do_frontier(pp)
                        for npp in frontier_result.get("packages") or []:
                            store.save_problem(npp)

            if campaign_halted(store, campaign.id):
                return _halted_result(store, campaign, problem, through)
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
                "acc": acc_meta,
                "usage": store.usage_totals(campaign.id),
            }
            if campaign.meta.get("divergence"):
                result["divergence"] = campaign.meta["divergence"]
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
    except asyncio.CancelledError:
        return _halted_result(store, campaign, problem, through)
    except Exception:
        if campaign.status == "running":
            campaign.status = "failed"
            store.save_campaign(campaign)
        raise
