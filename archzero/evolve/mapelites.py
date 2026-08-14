"""Built-in MAP-Elites + island evolution using Cursor SDK."""

from __future__ import annotations

import asyncio
import json
import random
import re
from typing import Any

from archzero.config import FactoryConfig
from archzero.evolve.backend import EvolutionBackend
from archzero.evolve.domains import MUTATE_PERSONA as MUTATE_PERSONA  # noqa: F401
from archzero.evolve.domains import mutate_persona_for, score_variant
from archzero.llm.client import CursorLLM
from archzero.models import Candidate, TaskClass
from archzero.store.db import Store


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
            try:
                return json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                pass
        return {}


def _headline_metric(c: Candidate) -> float:
    """Domain-aware archive coordinate — do not score a NoC child on MPKI=0."""
    for key in (
        "t2_miss_reduction",
        "t3_miss_reduction",
        "miss_reduction",
        "t2_goodput",
        "t3_goodput",
        "goodput",
        "t2_pe_utilization",
        "t3_pe_utilization",
        "pe_utilization",
        "t2_die_to_die_bw",
        "t3_die_to_die_bw",
        "die_to_die_bw",
        "t2_fabric_hop_latency",
        "t3_fabric_hop_latency",
        "fabric_hop_latency",
    ):
        val = c.metrics.get(key)
        if val is not None:
            return float(val)
    return 0.0


def _features(c: Candidate) -> tuple:
    family = c.family or "unclassified"
    err = _headline_metric(c)
    # bin error into coarse cells
    err_bin = int(min(9, max(0, err * 10)))
    speedup = float(c.metrics.get("t2_ipc_speedup") or c.metrics.get("ipc") or 1.0)
    speed_bin = int(min(9, max(0, (speedup - 1.0) * 20)))
    area = float(c.metrics.get("t3_area_mm2") or c.metrics.get("area") or 0.3)
    area_bin = int(min(9, max(0, area * 10)))
    return (family, err_bin, speed_bin, area_bin)


def _fitness(c: Candidate) -> float:
    score = _headline_metric(c)
    if c.metrics.get("t2_meets_target"):
        score += 0.2
    # Penalize failures
    score -= 0.05 * len(c.failures)
    return score


class MapElitesBackend(EvolutionBackend):
    name = "mapelites"

    async def run(
        self,
        cfg: FactoryConfig,
        seeds: list[Candidate],
        *,
        generations: int,
        campaign_id: str | None = None,
    ) -> dict[str, Any]:
        store = Store(cfg.db_path)
        domain = "cache"
        if campaign_id:
            camp = store.get_campaign(campaign_id)
            if camp:
                problem = store.get_problem(camp.problem_id)
                if problem is not None:
                    from archzero.spec.acc_parse import parse_acceptance_thresholds

                    domain = parse_acceptance_thresholds(problem).domain
        async with CursorLLM(cfg, store=store, campaign_id=campaign_id) as llm:
            islands: list[dict[tuple, Candidate]] = [
                {} for _ in range(cfg.evolve.islands)
            ]
            # Seed archives
            for i, s in enumerate(seeds):
                islands[i % len(islands)][_features(s)] = s

            history: list[dict[str, Any]] = []
            for gen in range(generations):
                new_children: list[Candidate] = []

                async def mutate(parent: Candidate, island_idx: int) -> Candidate | None:
                    artifact = ""
                    if parent.failures:
                        artifact = parent.failures[-1].message
                    ctx = (
                        f"Generation {gen} island {island_idx}\n"
                        f"PARENT: {parent.title} ({parent.family})\n{parent.mechanism}\n"
                        f"METRICS: {json.dumps({k: parent.metrics[k] for k in list(parent.metrics)[:12]}, default=str)}\n"
                        f"ARTIFACTS/ERRORS: {artifact}\n"
                        "Produce a diverse variant."
                    )
                    try:
                        data = _parse_json(
                            await llm.complete(
                                mutate_persona_for(domain),
                                ctx,
                                TaskClass.EVOLVE,
                                expect_json=True,
                            )
                        )
                    except Exception:  # noqa: BLE001
                        return None
                    if not data.get("mechanism"):
                        return None
                    knobs = data.get("knobs") or {}
                    metrics: dict[str, Any] = {
                        "evolved_gen": gen,
                        "source_failure_ids": [f.id for f in parent.failures],
                    }
                    if domain == "cache":
                        metrics["miss_reduction"] = knobs.get("miss_reduction", 0.12)
                        metrics["area"] = knobs.get("area", 0.3)
                    child = Candidate(
                        problem_id=parent.problem_id,
                        title=str(data.get("title") or f"{parent.title} mut{gen}"),
                        mechanism=str(data["mechanism"]),
                        family=str(data.get("family") or parent.family),
                        parent_id=parent.id,
                        clause_refs=list(parent.clause_refs),
                        metrics=metrics,
                    )
                    # Cheap analytic eval (not stub-only)
                    work = cfg.scratch_dir / child.id
                    work.mkdir(parents=True, exist_ok=True)
                    child.workdir = str(work)
                    (work / "sim_knobs.json").write_text(
                        json.dumps(knobs, indent=2), encoding="utf-8"
                    )
                    try:
                        scored = score_variant(domain, child.family, knobs)
                    except Exception:  # noqa: BLE001
                        scored = {}
                    child.metrics.update({f"t2_{k}": v for k, v in scored.items()})
                    if domain == "cache":
                        child.metrics["t2_miss_reduction"] = float(
                            scored.get("miss_reduction")
                            or knobs.get("miss_reduction")
                            or 0
                        )
                    child.metrics["evolved_gen"] = gen
                    return child

                # Pick parents from each island
                tasks = []
                for ii, archive in enumerate(islands):
                    if not archive:
                        continue
                    parents = list(archive.values())
                    random.shuffle(parents)
                    for p in parents[: max(1, cfg.evolve.population_per_island // 4)]:
                        tasks.append(mutate(p, ii))

                children = [c for c in await asyncio.gather(*tasks) if c]
                # Insert into archives (MAP-Elites replacement)
                inserted = 0
                for child in children:
                    ii = hash(child.family) % len(islands)
                    feat = _features(child)
                    archive = islands[ii]
                    if feat not in archive or _fitness(child) > _fitness(archive[feat]):
                        archive[feat] = child
                        inserted += 1
                        store.save_candidate(child, campaign_id=campaign_id)
                        new_children.append(child)

                # Periodic migration
                if gen % 3 == 2 and len(islands) > 1:
                    for i in range(len(islands)):
                        src = islands[i]
                        dst = islands[(i + 1) % len(islands)]
                        if src:
                            migrant = max(src.values(), key=_fitness)
                            feat = _features(migrant)
                            if feat not in dst or _fitness(migrant) > _fitness(dst[feat]):
                                dst[feat] = migrant

                history.append(
                    {
                        "generation": gen,
                        "children": len(children),
                        "inserted": inserted,
                        "archive_sizes": [len(a) for a in islands],
                        "best_fitness": max(
                            (_fitness(c) for a in islands for c in a.values()),
                            default=0.0,
                        ),
                    }
                )

            elites = [c for a in islands for c in a.values()]
            elites.sort(key=_fitness, reverse=True)
            return {
                "backend": self.name,
                "generations": generations,
                "elites": len(elites),
                "best": elites[0].id if elites else None,
                "best_fitness": _fitness(elites[0]) if elites else 0.0,
                "history": history,
            }


async def run_evolution(
    cfg: FactoryConfig,
    *,
    campaign_id: str,
    generations: int,
    reenter: bool = True,
) -> dict[str, Any]:
    from archzero.models import Tier

    store = Store(cfg.db_path)
    all_c = store.list_candidates(campaign_id=campaign_id)
    t2 = [c for c in all_c if c.hard_passed(Tier.T2) or c.passed_through(Tier.T2)]
    seeds = t2 or [c for c in all_c if c.status in {"active", "passed", "new"}] or all_c
    if not seeds:
        return {"error": "no candidates to evolve", "campaign_id": campaign_id}

    from archzero.evolve.registry import resolve_evolve_backend

    backend = resolve_evolve_backend(cfg)
    summary = await backend.run(
        cfg, seeds, generations=generations, campaign_id=campaign_id
    )

    if reenter:
        from archzero.funnel.pipeline import run_campaign

        children = [
            c
            for c in store.list_candidates(campaign_id=campaign_id)
            if c.parent_id and not c.tier_history
        ]
        if children:
            camp = store.get_campaign(campaign_id)
            problem = store.get_problem(camp.problem_id) if camp else None
            if problem is not None:
                reenter_through = cfg.evolve.reenter_through
                from archzero.metrics.elimination import compute_elimination, snapshot_failures

                baseline_snap = snapshot_failures(
                    store.list_failures(campaign_id=campaign_id)
                )
                re = await run_campaign(
                    cfg,
                    problem=problem,
                    through=reenter_through,
                    name=f"evolve-reenter:{campaign_id}",
                    candidates_override=children[: max(1, len(children))],
                    n_generate=0,
                )
                follow_id = re.get("campaign_id")
                if follow_id:
                    elim = compute_elimination(
                        store,
                        source_campaign_id=campaign_id,
                        followup_campaign_id=follow_id,
                    )
                    re["elimination"] = elim
                    re["source_failures"] = baseline_snap
                    re["parent_campaign_id"] = campaign_id
                summary["reenter"] = re
    return summary
