"""Shared pytest fixtures."""

from __future__ import annotations

from pathlib import Path

import pytest

from archzero.config import FactoryConfig
from archzero.llm.fake import FakeLLM
from archzero.spec.ndf import load_problem_package


@pytest.fixture
def tmp_cfg(tmp_path: Path) -> FactoryConfig:
    cfg = FactoryConfig(state_dir=tmp_path / "state")
    cfg.ensure_dirs()
    cfg.funnel.strict_evidence = True
    cfg.sim.backend = "stub"
    return cfg


@pytest.fixture
def demo_problem():
    demo = Path(__file__).resolve().parents[1] / "specs" / "demo.md"
    return load_problem_package(demo)


@pytest.fixture
def fake_llm() -> FakeLLM:
    return FakeLLM(
        responses={
            "bulk_screen": (
                '{"verdict":"pass","score":0.9,"summary":"physics ok",'
                '"physics_flags":[],"clause_refs":["REQ-001"]}'
            ),
            "comprehend": "## Review\nPlausible mechanism.",
            "synthesize": (
                '{"verdict":"pass","score":0.8,"summary":"consensus pass",'
                '"failure_modes":[],"clause_refs":["REQ-001"]}'
            ),
            "spec_gen": "# Analytic Spec\n\nAssumptions: ...\n",
            "analytic": (
                "```python\ndef run_model():\n"
                "    return {'predicted_mpki': 6.5, 'miss_reduction': 0.2, "
                "'ipc_speedup': 1.08, 'meets_target': True}\n```"
            ),
            "final_judge": (
                '{"verdict":"pass","score":0.85,"summary":"meets ACC",'
                '"clause_refs":["ACC-001"]}'
            ),
            "ideate": (
                '{"title":"Filtered prefetch","family":"prefetch",'
                '"mechanism":"Dead-block filtered L2 prefetch.","clause_refs":[]}'
            ),
        }
    )
