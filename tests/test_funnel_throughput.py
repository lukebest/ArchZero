"""Defaults + optional seed-library volume (capability, not default intake)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from archzero.config import FactoryConfig, load_config
from archzero.funnel.dedup import dedup_candidates
from archzero.generation.seed_library import (
    generate_seed_library,
    write_seed_dir,
)
from archzero.llm.fake import FakeLLM
from archzero.models import Tier


def test_repo_toml_matches_target_funnel_defaults():
    root = Path(__file__).resolve().parents[1]
    cfg = load_config(root / "archzero.toml")
    assert cfg.funnel.strict_evidence is True
    assert cfg.funnel.tier1_advisory is False
    assert cfg.funnel.tier0_batch_size == 10
    assert cfg.divergence.enabled is True
    assert cfg.divergence.n_cells == 12
    assert cfg.divergence.per_cell == 6
    assert cfg.quotas.tier0_keep == 80
    assert cfg.quotas.tier1_keep == 40
    assert cfg.quotas.tier2_keep == 10
    assert cfg.seed_library.enabled is False
    assert cfg.seed_library.target_n == 80


def test_factory_config_defaults_match_target_shape():
    cfg = FactoryConfig()
    assert cfg.funnel.tier1_advisory is False
    assert cfg.funnel.tier0_batch_size == 10
    assert cfg.divergence.enabled is True
    assert cfg.quotas.tier0_keep == 80
    assert cfg.quotas.tier1_keep == 40
    assert cfg.quotas.tier2_keep == 10
    assert cfg.seed_library.enabled is False
    assert cfg.seed_library.target_n == 80


def test_seed_library_hits_1k_with_low_jaccard_collapse(demo_problem):
    cands = generate_seed_library(demo_problem, target_n=1000)
    assert len(cands) == 1000
    assert len({c.content_hash for c in cands}) == 1000
    kept = dedup_candidates(cands, threshold=0.85).kept
    # Lexical diversity must keep the bulk of the grid; collapse is expected
    # but must not be the dominant failure mode.
    assert len(kept) >= 900, f"Jaccard collapse too severe: {1000 - len(kept)}"
    families = {c.family for c in cands}
    assert len(families) >= 4


def test_seed_library_writes_seed_dir(tmp_path, demo_problem):
    cands = generate_seed_library(demo_problem, target_n=25)
    out = tmp_path / "seeds"
    n = write_seed_dir(cands, out)
    assert n == 25
    assert len(list(out.glob("*.md"))) == 25
    text = next(out.glob("*.md")).read_text(encoding="utf-8")
    assert text.startswith("# ")
    assert "Family:" in text


class _CtxFakeLLM(FakeLLM):
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc) -> bool:
        return False


def _batch_screen_json(n: int, *, fail_every: int = 0) -> str:
    rows = []
    for i in range(1, n + 1):
        ok = fail_every <= 0 or (i % fail_every) != 0
        rows.append(
            {
                "index": i,
                "verdict": "pass" if ok else "fail",
                "score": 0.9 if ok else 0.1,
                "summary": "physics ok" if ok else "conservation fail",
                "physics_flags": [],
                "clause_refs": ["REQ-001"],
            }
        )
    return json.dumps({"results": rows})


@pytest.mark.asyncio
async def test_seed_library_campaign_admits_1k_into_t0_offline(
    tmp_cfg, demo_problem, monkeypatch
):
    """Prove 1K-into-T0 shape without 1000 live ideation calls."""
    from archzero.funnel import pipeline

    tmp_cfg.quotas.tier0_keep = 1000
    tmp_cfg.funnel.tier1_advisory = False
    tmp_cfg.funnel.tier0_batch_size = 10
    tmp_cfg.seed_library.enabled = True
    tmp_cfg.seed_library.target_n = 1000
    tmp_cfg.divergence.enabled = False
    tmp_cfg.budget.concurrency = 8

    sequence = [_batch_screen_json(10) for _ in range(100)]
    llm = _CtxFakeLLM(
        sequence=sequence,
        responses={
            "bulk_screen": (
                '{"verdict":"pass","score":0.9,"summary":"physics ok",'
                '"physics_flags":[],"clause_refs":["REQ-001"]}'
            ),
        },
    )
    monkeypatch.setattr(pipeline, "CursorLLM", lambda *a, **kw: llm)

    result = await pipeline.run_campaign(
        tmp_cfg,
        problem=demo_problem,
        through=Tier.T0,
        use_divergence=False,
        use_seed_library=True,
        name="seed-library-1k-t0",
    )

    intake = result["intake"]
    assert intake["seed_library"] == 1000
    assert intake["divergence"] == 0
    assert intake["after_jaccard"] >= 900
    assert result["generated"] == intake["after_jaccard"]
    assert result["funnel"]["entered_t0"] >= 900
    assert result["funnel"]["after_tier0"] <= 1000
    assert result["funnel"]["after_tier0"] >= 900
    # Batch screening: ~100 bulk_screen calls, not 1000.
    bulk_calls = [c for c in llm.calls if c["task"] == "bulk_screen"]
    assert len(bulk_calls) <= 120
    assert len(bulk_calls) >= 90


@pytest.mark.asyncio
async def test_quota_shape_after_real_t1_veto(tmp_cfg, demo_problem, monkeypatch):
    """With advisory off + quotas, survivors compress toward 100 / 10."""
    from archzero.funnel import pipeline

    tmp_cfg.quotas.tier0_keep = 1000
    tmp_cfg.quotas.tier1_keep = 100
    tmp_cfg.quotas.tier2_keep = 10
    tmp_cfg.funnel.tier1_advisory = False
    tmp_cfg.funnel.tier0_batch_size = 10
    tmp_cfg.seed_library.target_n = 250
    tmp_cfg.divergence.enabled = False
    tmp_cfg.budget.concurrency = 8

    llm = _CtxFakeLLM(
        responses={
            "bulk_screen": json.dumps(
                {
                    "results": [
                        {
                            "index": i,
                            "verdict": "pass",
                            "score": 0.9,
                            "summary": "ok",
                            "physics_flags": [],
                            "clause_refs": ["REQ-001"],
                        }
                        for i in range(1, 11)
                    ]
                }
            ),
            "comprehend": "**Status:** PASS\n",
            "synthesize": (
                '{"verdict":"pass","score":0.8,"summary":"consensus pass",'
                '"failure_modes":[],"clause_refs":["REQ-001"]}'
            ),
            "spec_gen": "# Analytic Spec\n",
            "analytic": (
                "```python\ndef run_model():\n"
                "    return {'predicted_mpki': 6.5, 'miss_reduction': 0.2, "
                "'ipc_speedup': 1.08, 'meets_target': True}\n```"
            ),
            "final_judge": (
                '{"verdict":"pass","score":0.85,"summary":"meets ACC",'
                '"clause_refs":["ACC-001"]}'
            ),
        },
    )
    monkeypatch.setattr(pipeline, "CursorLLM", lambda *a, **kw: llm)

    result = await pipeline.run_campaign(
        tmp_cfg,
        problem=demo_problem,
        through=Tier.T2,
        use_divergence=False,
        use_seed_library=True,
        name="quota-shape",
    )
    funnel = result["funnel"]
    assert funnel["entered_t0"] >= 200
    assert funnel["after_tier0"] <= 1000
    assert funnel["after_tier1"] <= 100
    assert funnel["after_tier2"] <= 10
    assert funnel["after_tier1"] >= 1
    assert funnel["after_tier2"] >= 1
    # T1 ran (not advisory pass-through): survivors have T1 history before T2.
    assert funnel["after_tier1"] < funnel["entered_t0"] or funnel["after_tier0"] <= 100


@pytest.mark.asyncio
async def test_seed_plus_diverge_merge_and_dedup(
    tmp_cfg, demo_problem, monkeypatch
):
    from archzero.funnel import pipeline

    tmp_cfg.seed_library.target_n = 50
    tmp_cfg.funnel.tier0_batch_size = 10
    tmp_cfg.funnel.tier1_advisory = False
    tmp_cfg.quotas.tier0_keep = 1000
    tmp_cfg.quotas.tier1_keep = 100
    tmp_cfg.quotas.tier2_keep = 10

    ideas = json.dumps(
        {
            "ideas": [
                {
                    "title": f"发散机制 {i}",
                    "family": "prefetch",
                    "mechanism": f"跨域结构 {i} 映射到预取过滤器，距离={i + 1}。",
                    "isomorphism": "拥塞窗口 → 预取深度",
                    "expected_effect": "MPKI 下降",
                    "risks": "面积",
                    "clause_refs": ["REQ-001"],
                }
                for i in range(3)
            ]
        },
        ensure_ascii=False,
    )
    llm = _CtxFakeLLM(
        responses={
            "ideate": ideas,
            "bulk_screen": (
                '{"verdict":"pass","score":0.9,"summary":"physics ok",'
                '"physics_flags":[],"clause_refs":["REQ-001"]}'
            ),
        }
    )
    monkeypatch.setattr(pipeline, "CursorLLM", lambda *a, **kw: llm)

    result = await pipeline.run_campaign(
        tmp_cfg,
        problem=demo_problem,
        through=Tier.T0,
        use_divergence=True,
        diverge_cells=2,
        diverge_per_cell=3,
        use_seed_library=True,
    )
    intake = result["intake"]
    assert intake["seed_library"] == 50
    assert intake["divergence"] == 6
    assert intake["raw_generated"] == 56
    assert result["generated"] >= 50
    assert "dedup_collapse" in intake


@pytest.mark.asyncio
async def test_tier1_veto_blocks_advance_under_new_default(
    tmp_cfg, demo_problem, monkeypatch
):
    """tier1_advisory=false must actually cut; advisory pass-through is gone."""
    from archzero.funnel import pipeline
    from archzero.funnel.errors import advances_after_tier
    from archzero.models import Candidate, Verdict
    from archzero.store.db import Store

    tmp_cfg.funnel.tier1_advisory = False
    tmp_cfg.seed_library.enabled = False
    tmp_cfg.divergence.enabled = False

    llm = _CtxFakeLLM(
        responses={
            "bulk_screen": (
                '{"verdict":"pass","score":0.9,"summary":"physics ok",'
                '"physics_flags":[],"clause_refs":["REQ-001"]}'
            ),
            "comprehend": "FAIL lean\n",
            "synthesize": (
                '{"verdict":"fail","score":0.1,"summary":"不可实现",'
                '"failure_modes":["deadlock"],"clause_refs":["REQ-001"]}'
            ),
        }
    )
    monkeypatch.setattr(pipeline, "CursorLLM", lambda *a, **kw: llm)

    cand = Candidate(
        problem_id=demo_problem.id,
        title="坏机制",
        mechanism="违反守恒的魔术缓存。",
        family="prefetch",
    )
    result = await pipeline.run_campaign(
        tmp_cfg,
        problem=demo_problem,
        through=Tier.T2,
        candidates_override=[cand],
        use_divergence=False,
        use_seed_library=False,
    )
    store = Store(tmp_cfg.db_path)
    got = store.list_candidates(campaign_id=result["campaign_id"])[0]
    t1 = next(t for t in got.tier_history if t.tier == Tier.T1)
    assert t1.verdict == Verdict.FAIL
    assert advances_after_tier(got, Tier.T1, tier1_advisory=False) is False
    assert not any(t.tier == Tier.T2 for t in got.tier_history)


@pytest.mark.asyncio
async def test_strict_evidence_still_fail_closed(tmp_cfg, demo_problem, fake_llm):
    from archzero.funnel.tier3 import evaluate_tier3
    from archzero.models import Candidate, Verdict

    tmp_cfg.funnel.strict_evidence = True
    tmp_cfg.sim.backend = "champsim"
    tmp_cfg.sim.champsim_bin = "/nonexistent/champsim"
    work = tmp_cfg.scratch_dir / "strict"
    work.mkdir(parents=True)
    c = Candidate(
        problem_id=demo_problem.id,
        title="prefetch",
        mechanism="filtered prefetch",
        family="prefetch",
        workdir=str(work),
        metrics={"t2_miss_reduction": 0.2},
    )
    out = await evaluate_tier3(tmp_cfg, c, demo_problem, fake_llm)
    last = out.tier_history[-1]
    assert last.verdict == Verdict.UNAVAILABLE
    assert "UNAVAILABLE" in last.summary or "unavailable" in last.summary.lower()
