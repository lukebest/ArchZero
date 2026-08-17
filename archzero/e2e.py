"""Offline-friendly end-to-end demo through Tier5."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from archzero.config import FactoryConfig
from archzero.llm.fake import FakeLLM
from archzero.models import Candidate, Tier
from archzero.offline import (
    default_family,
    fake_llm_responses,
    knobs_for,
    problem_domain,
    scaffold_mechanism,
    scaffold_title,
)
from archzero.sim.headlines import headlines_text
from archzero.spec.ndf import load_problem_package
from archzero.store.db import Store


async def run_e2e(
    cfg: FactoryConfig,
    *,
    spec_path: Path,
    through: Tier = Tier.T5,
    offline: bool = True,
) -> dict[str, Any]:
    """Run a minimal campaign. Offline mode uses FakeLLM + stub/rtl unavailable path."""
    from archzero.funnel.pipeline import run_campaign

    if not offline:
        return await run_campaign(
            cfg,
            spec_path=spec_path,
            through=through,
            n_generate=1,
            name="e2e-online",
        )

    pp = load_problem_package(spec_path)
    domain = problem_domain(pp)
    family = default_family(domain)
    store = Store(cfg.db_path)
    store.save_problem(pp)
    work = cfg.scratch_dir / "e2e" / "cand"
    work.mkdir(parents=True, exist_ok=True)
    cand = Candidate(
        problem_id=pp.id,
        title=scaffold_title(domain),
        mechanism=scaffold_mechanism(domain),
        family=family,
        workdir=str(work),
    )
    (work / "sim_knobs.json").write_text(
        json.dumps(knobs_for(domain, family)),
        encoding="utf-8",
    )
    (work / "design.py").write_text(
        "# offline stub design — pyCircuit not invoked in offline e2e\n",
        encoding="utf-8",
    )
    (work / "EQUIV_GATE.md").write_text(
        "# Equivalence gate\nCommit-point only.\n", encoding="utf-8"
    )

    llm = FakeLLM(
        responses=fake_llm_responses(domain),
        sequence=[
            '{"verdict":"pass","score":0.8,"summary":"insight ok","magic_gap_notes":"","clause_refs":[]}',
        ],
    )

    from archzero.funnel import tier0, tier1, tier2, tier3, tier4, tier5, tier6

    steps = {
        Tier.T0: tier0.evaluate_tier0,
        Tier.T1: tier1.evaluate_tier1,
        Tier.T2: tier2.evaluate_tier2,
        Tier.T3: tier3.evaluate_tier3,
        Tier.T4: tier4.evaluate_tier4,
        Tier.T5: tier5.evaluate_tier5,
        Tier.T6: tier6.evaluate_tier6,
    }
    order = [
        Tier.T0,
        Tier.T1,
        Tier.T2,
        Tier.T3,
        Tier.T4,
        Tier.T5,
        Tier.T6,
    ]
    stop = order.index(through)
    for t in order[: stop + 1]:
        cand = await steps[t](cfg, cand, pp, llm)  # type: ignore[arg-type]

    store.save_candidate(cand, campaign_id=None)
    return {
        "offline": True,
        "candidate_id": cand.id,
        "through": through.value,
        "domain": domain,
        "family": cand.family,
        "headlines": headlines_text(cand.metrics, family=cand.family),
        "tier_history": [
            {
                "tier": tr.tier.value,
                "verdict": tr.verdict.value,
                "evidence": tr.evidence.value,
                "summary": tr.summary[:160],
            }
            for tr in cand.tier_history
        ],
        "note": "Tier6 remains Planned/reserved",
    }
