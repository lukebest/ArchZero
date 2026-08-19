"""Infrastructure errors are retryable, not mechanism FAILs."""

from __future__ import annotations

from pathlib import Path

import pytest

from archzero.funnel.errors import (
    infra_result,
    is_infra_error,
    needs_resume,
    soften_infra_failures,
    strip_retryable_for_tier,
)
from archzero.llm.fake import FakeLLM
from archzero.models import Candidate, TaskClass, Tier, TierResult, Verdict
from archzero.store.db import Store


def test_connecterror_is_infra_not_physics():
    msg = "tier1 synth error: Bridge request failed: ConnectError: All connection attempts failed"
    assert is_infra_error(msg)
    assert not is_infra_error("否决。无缓冲双环上占用不守恒。")


def test_soften_rewrites_recorded_infra_fail():
    c = Candidate(problem_id="pp-x", title="t", mechanism="m")
    c.tier_history.append(
        TierResult(tier=Tier.T0, verdict=Verdict.PASS, summary="ok", score=0.8)
    )
    c.tier_history.append(
        TierResult(
            tier=Tier.T1,
            verdict=Verdict.FAIL,
            summary="tier1 synth error: Bridge request failed: ConnectError: All connection attempts failed",
            score=0.0,
        )
    )
    c.status = "failed"
    assert soften_infra_failures(c)
    assert c.status == "active"
    last = c.last_tier()
    assert last is not None
    assert last.verdict == Verdict.UNAVAILABLE
    assert last.metrics.get("retryable") is True
    assert not c.passed_through(Tier.T1)
    assert c.passed_through(Tier.T0)
    assert needs_resume(c, Tier.T2)


def test_resume_skips_hard_fails_and_dedup_leftovers():
    leftover = Candidate(problem_id="pp-x", title="dup", mechanism="m")
    hard = Candidate(problem_id="pp-x", title="phys", mechanism="m")
    hard.tier_history.append(
        TierResult(tier=Tier.T0, verdict=Verdict.FAIL, summary="违反带宽上限", score=0.0)
    )
    mid = Candidate(problem_id="pp-x", title="mid", mechanism="m")
    mid.tier_history.append(
        TierResult(tier=Tier.T0, verdict=Verdict.PASS, summary="ok", score=0.9)
    )
    done = Candidate(problem_id="pp-x", title="done", mechanism="m")
    done.tier_history.append(
        TierResult(tier=Tier.T2, verdict=Verdict.PASS, summary="ok", score=0.9)
    )
    assert not needs_resume(leftover, Tier.T2)
    assert not needs_resume(hard, Tier.T2)
    assert needs_resume(mid, Tier.T2)
    assert not needs_resume(done, Tier.T2)


@pytest.mark.asyncio
async def test_tier1_connecterror_is_unavailable(tmp_cfg, demo_problem):
    from archzero.funnel.tier1 import evaluate_tier1

    class BoomLLM(FakeLLM):
        async def complete(self, persona, context, task, *, expect_json=False):
            if task is TaskClass.SYNTHESIZE:
                raise ConnectionError(
                    "Bridge request failed: ConnectError: All connection attempts failed"
                )
            return await super().complete(
                persona, context, task, expect_json=expect_json
            )

    c = Candidate(
        problem_id=demo_problem.id,
        title="rg",
        mechanism="Random plane then shortest path.",
        workdir=str(tmp_cfg.scratch_dir / "t1-infra"),
    )
    Path(c.workdir).mkdir(parents=True)
    out = await evaluate_tier1(tmp_cfg, c, demo_problem, BoomLLM())
    last = out.tier_history[-1]
    assert last.verdict is Verdict.UNAVAILABLE
    assert last.metrics.get("retryable") is True
    assert out.status == "active"
    assert not out.passed_through(Tier.T1)


@pytest.mark.asyncio
async def test_resume_only_retries_softened_infra(tmp_cfg, demo_problem, monkeypatch):
    from archzero.funnel import pipeline
    from archzero.models import Campaign

    store = Store(tmp_cfg.db_path)
    store.save_problem(demo_problem)
    camp = Campaign(
        name="resume infra",
        problem_id=demo_problem.id,
        through_tier=Tier.T2,
        status="done",
    )
    store.save_campaign(camp)

    infra = Candidate(problem_id=demo_problem.id, title="infra", mechanism="m")
    infra.tier_history = [
        TierResult(tier=Tier.T0, verdict=Verdict.PASS, summary="ok", score=0.8),
        TierResult(
            tier=Tier.T1,
            verdict=Verdict.FAIL,
            summary="tier1 synth error: Bridge request failed: ConnectError: All connection attempts failed",
        ),
    ]
    infra.status = "failed"
    store.save_candidate(infra, campaign_id=camp.id)

    phys = Candidate(problem_id=demo_problem.id, title="phys", mechanism="m")
    phys.tier_history = [
        TierResult(tier=Tier.T0, verdict=Verdict.FAIL, summary="违反守恒", score=0.0)
    ]
    phys.status = "failed"
    store.save_candidate(phys, campaign_id=camp.id)

    leftover = Candidate(problem_id=demo_problem.id, title="dup", mechanism="near-dup")
    store.save_candidate(leftover, campaign_id=camp.id)

    seen: list[str] = []

    async def fake_t1(cfg, cand, problem, llm):
        seen.append(cand.title)
        cand.tier_history.append(
            TierResult(tier=Tier.T1, verdict=Verdict.PASS, summary="retried ok", score=0.7)
        )
        cand.status = "active"
        return cand

    async def fake_t2(cfg, cand, problem, llm):
        cand.tier_history.append(
            TierResult(tier=Tier.T2, verdict=Verdict.PASS, summary="t2 ok", score=0.6)
        )
        cand.status = "active"
        return cand

    monkeypatch.setattr(pipeline, "CursorLLM", lambda *a, **kw: _NullLLM())
    monkeypatch.setitem(pipeline.TIER_FNS, Tier.T1, fake_t1)
    monkeypatch.setitem(pipeline.TIER_FNS, Tier.T2, fake_t2)

    result = await pipeline.run_campaign(
        tmp_cfg, resume_campaign_id=camp.id, through=Tier.T2
    )
    assert result["resumed"] is True
    assert result["retried"] == 1
    assert seen == ["infra"]
    reloaded = store.get_candidate(infra.id)
    assert reloaded is not None
    assert reloaded.hard_passed(Tier.T1)
    assert reloaded.hard_passed(Tier.T2)
    assert store.get_candidate(phys.id).status == "failed"
    assert store.get_candidate(leftover.id).tier_history == []


class _NullLLM:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc) -> bool:
        return False


def test_strip_retryable_lets_a_new_attempt_replace_the_old():
    c = Candidate(problem_id="pp-x", title="t", mechanism="m")
    c.tier_history.append(infra_result(Tier.T1, "bridge down"))
    strip_retryable_for_tier(c, Tier.T1)
    assert c.tier_history == []
