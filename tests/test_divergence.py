"""Cross-domain divergence: matrix coverage + FakeLLM candidate construction."""

from __future__ import annotations

import json

import pytest

from archzero.generation.divergence import (
    EXPANSION_MODES,
    build_matrix,
    coverage_summary,
    diverge,
    divergence_markdown,
    pool_stats,
    select_lenses,
)
from archzero.generation.domains import DOMAIN_SOURCES, select_domains
from archzero.generation.theories import THEORY_LENSES
from archzero.llm.fake import FakeLLM

FULL_MATRIX = len(THEORY_LENSES) * len(DOMAIN_SOURCES) * len(EXPANSION_MODES)


def _ideas_json(n: int) -> str:
    return json.dumps(
        {
            "ideas": [
                {
                    "title": f"机制 {i}",
                    "family": "prefetch",
                    "mechanism": f"用跨域结构 {i} 改造预取过滤器。",
                    "isomorphism": "拥塞窗口 → 预取深度",
                    "expected_effect": "MPKI 下降",
                    "risks": "面积增加",
                    "clause_refs": ["REQ-001"],
                }
                for i in range(n)
            ]
        },
        ensure_ascii=False,
    )


def test_domain_catalog_is_unique_and_populated():
    assert len(DOMAIN_SOURCES) >= 20
    assert len({d.id for d in DOMAIN_SOURCES}) == len(DOMAIN_SOURCES)
    for d in DOMAIN_SOURCES:
        assert d.classic_result and d.transfer_hint


def test_matrix_is_balanced_and_duplicate_free(demo_problem):
    cells = build_matrix(demo_problem, n_cells=24)
    assert len(cells) == 24
    assert len({c.id for c in cells}) == 24

    cov = coverage_summary(cells)
    # 24 cells over 8 lenses / 24 domains: every axis value used at most once more
    # than the least-used one.
    assert max(cov["lens"].values()) - min(cov["lens"].values()) <= 1
    assert len(cov["domain"]) == 24
    assert set(cov["mode"]) == set(EXPANSION_MODES)


def test_matrix_is_deterministic_per_problem(demo_problem):
    a = [c.id for c in build_matrix(demo_problem, n_cells=30)]
    b = [c.id for c in build_matrix(demo_problem, n_cells=30)]
    assert a == b


def test_matrix_caps_at_full_product(demo_problem):
    cells = build_matrix(demo_problem, n_cells=FULL_MATRIX + 100)
    assert len(cells) == FULL_MATRIX
    assert len({c.id for c in cells}) == FULL_MATRIX


def test_whitelists_narrow_the_axes(demo_problem):
    cells = build_matrix(
        demo_problem,
        n_cells=6,
        lens_ids=["queueing_theory"],
        domain_ids=["tcp_congestion", "db_query_optimization"],
    )
    assert {c.lens.id for c in cells} == {"queueing_theory"}
    assert {c.domain.id for c in cells} <= {"tcp_congestion", "db_query_optimization"}


def test_unknown_whitelist_ids_fall_back_to_full_catalog():
    assert select_lenses(["nope"]) == THEORY_LENSES
    assert select_domains(["nope"]) == DOMAIN_SOURCES
    assert select_lenses([]) == THEORY_LENSES


@pytest.mark.asyncio
async def test_diverge_builds_candidates_with_provenance(tmp_cfg, demo_problem):
    llm = FakeLLM(responses={"ideate": _ideas_json(3)})
    cands = await diverge(tmp_cfg, demo_problem, n_cells=4, per_cell=3, llm=llm)

    assert len(cands) == 12
    assert len([c for c in llm.calls if c["op"] == "complete"]) == 4
    for c in cands:
        assert c.problem_id == demo_problem.id
        assert c.metrics["diverge_lens"]
        assert c.metrics["diverge_domain"]
        assert c.metrics["diverge_mode"] in EXPANSION_MODES

    stats = pool_stats(cands)
    assert sum(stats["mode"].values()) == 12
    assert len(stats["domain"]) == 4


@pytest.mark.asyncio
async def test_diverge_survives_malformed_cells(tmp_cfg, demo_problem):
    llm = FakeLLM(sequence=[_ideas_json(2), "not json at all", _ideas_json(2)])
    cands = await diverge(tmp_cfg, demo_problem, n_cells=3, per_cell=2, llm=llm)
    assert len(cands) == 4


@pytest.mark.asyncio
async def test_divergence_markdown_covers_empty_cells(tmp_cfg, demo_problem):
    llm = FakeLLM(sequence=[_ideas_json(1), "{}"])
    cells = build_matrix(demo_problem, n_cells=2)
    cands = await diverge(tmp_cfg, demo_problem, n_cells=2, per_cell=1, llm=llm)
    md = divergence_markdown(demo_problem, cells, cands)
    assert "idea 总数: 1" in md
    assert "该 cell 未产出可用 idea" in md


class _CtxFakeLLM(FakeLLM):
    """FakeLLM usable as the ``async with CursorLLM(...)`` the pipeline opens."""

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc) -> bool:
        return False


@pytest.mark.asyncio
async def test_run_campaign_feeds_the_funnel_from_the_matrix(
    tmp_cfg, demo_problem, monkeypatch
):
    from archzero.funnel import pipeline
    from archzero.models import Tier

    llm = _CtxFakeLLM(
        responses={
            "ideate": _ideas_json(2),
            "bulk_screen": (
                '{"verdict":"pass","score":0.9,"summary":"physics ok",'
                '"physics_flags":[],"clause_refs":[]}'
            ),
        }
    )
    monkeypatch.setattr(pipeline, "CursorLLM", lambda *a, **kw: llm)

    result = await pipeline.run_campaign(
        tmp_cfg,
        problem=demo_problem,
        through=Tier.T0,
        use_divergence=True,
        diverge_cells=3,
        diverge_per_cell=2,
    )

    dv = result["divergence"]
    assert dv["n_cells"] == 3
    assert dv["generated"] == 6
    assert sum(dv["by_axis"]["mode"].values()) == 6
    # Titles repeat across cells, so dedup collapses them before Tier0.
    assert result["generated"] >= 1
    assert result["passed"] >= 1
    assert not result.get("stopped")


@pytest.mark.asyncio
async def test_stop_during_diverge_skips_the_funnel(
    tmp_cfg, demo_problem, monkeypatch
):
    from archzero.funnel import pipeline
    from archzero.generation import divergence as divmod
    from archzero.models import Tier
    from archzero.store.db import Store

    llm = _CtxFakeLLM(responses={"ideate": _ideas_json(2)})
    monkeypatch.setattr(pipeline, "CursorLLM", lambda *a, **kw: llm)

    real = divmod.diverge

    async def diverge_then_stop(*args, **kwargs):
        out = await real(*args, **kwargs)
        store = Store(tmp_cfg.db_path)
        for camp in store.list_campaigns():
            if camp.status == "running":
                store.stop_campaign(camp.id)
        return out

    monkeypatch.setattr(divmod, "diverge", diverge_then_stop)

    result = await pipeline.run_campaign(
        tmp_cfg,
        problem=demo_problem,
        through=Tier.T2,
        use_divergence=True,
        diverge_cells=2,
        diverge_per_cell=2,
    )
    assert result["stopped"] is True
    store = Store(tmp_cfg.db_path)
    camp = store.get_campaign(result["campaign_id"])
    assert camp is not None
    assert camp.status == "stopped"
    assert store.list_candidates(campaign_id=camp.id)
