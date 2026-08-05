"""Offline-friendly end-to-end demo through Tier5."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from archzero.config import FactoryConfig
from archzero.models import Candidate, Tier
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

    from archzero.llm.fake import FakeLLM

    pp = load_problem_package(spec_path)
    store = Store(cfg.db_path)
    store.save_problem(pp)
    work = cfg.scratch_dir / "e2e" / "cand"
    work.mkdir(parents=True, exist_ok=True)
    cand = Candidate(
        problem_id=pp.id,
        title="E2E demo prefetch filter",
        mechanism=(
            "A small dead-block predictor filters L2 prefetch requests under "
            "LLM decode traffic to cut MPKI without large area."
        ),
        family="prefetch",
        workdir=str(work),
    )
    # Pre-write knobs / minimal DSL stubs for offline path
    (work / "sim_knobs.json").write_text(
        json.dumps({"miss_reduction": 0.18, "extra_bw": 0.02, "area": 0.25}),
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
        responses={
            "bulk_screen": '{"verdict":"pass","score":0.8,"summary":"ok","physics_flags":[],"clause_refs":[]}',
            "comprehend": "## review\nLooks plausible.",
            "synthesize": '{"verdict":"pass","score":0.7,"summary":"ok","failure_modes":[],"clause_refs":[]}',
            "spec_gen": "# Spec\nAssumptions...\n",
            "analytic": (
                "```python\ndef run_model():\n"
                "    return {'predicted_mpki':6.0,'miss_reduction':0.18,"
                "'ipc_speedup':1.05,'meets_target':True}\n```"
            ),
            "final_judge": '{"verdict":"pass","score":0.8,"summary":"ok","clause_refs":[]}',
        }
    )
    # Also handle insight JSON on second analytic call via sequence
    llm.sequence = [
        '{"verdict":"pass","score":0.8,"summary":"insight ok","magic_gap_notes":"","clause_refs":[]}',
    ]

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
