"""LLM dedicated_sim path falls back / accepts FakeLLM code."""

from __future__ import annotations

import pytest

from archzero.llm.fake import FakeLLM
from archzero.sim.generate import generate_dedicated_sim_llm


@pytest.mark.asyncio
async def test_llm_dedicated_falls_back_without_run_sim(tmp_path):
    llm = FakeLLM(responses={"analytic": "sorry no code"})
    g = await generate_dedicated_sim_llm(
        tmp_path,
        title="Filtered prefetch",
        mechanism="256-entry filter",
        family="prefetch",
        knobs={"miss_reduction": 0.3},
        llm=llm,
        max_repairs=1,
    )
    assert g.selftest_ok  # template fallback
    assert g.path.exists()


@pytest.mark.asyncio
async def test_llm_dedicated_accepts_valid_code(tmp_path):
    code = """
def run_sim(knobs: dict) -> dict:
    r = float(knobs.get("miss_reduction", 0.2))
    return {
        "evidence": "dedicated",
        "backend": "dedicated-llm",
        "family": "prefetch",
        "miss_reduction": min(0.9, r * 0.9),
        "bw_delta_frac": float(knobs.get("extra_bw", 0.02)),
        "area_mm2": 0.25,
    }

if __name__ == "__main__":
    import json, sys
    print(json.dumps(run_sim(json.loads(sys.argv[1]))))
"""
    llm = FakeLLM(responses={"analytic": f"```python\n{code}\n```"})
    g = await generate_dedicated_sim_llm(
        tmp_path,
        title="Filtered prefetch",
        mechanism="filter",
        family="prefetch",
        knobs={"miss_reduction": 0.3, "extra_bw": 0.02},
        llm=llm,
    )
    assert g.selftest_ok
    assert g.metrics.get("backend") == "dedicated-llm"
