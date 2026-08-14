"""OpenEvolve seed programs must follow the problem domain."""

from __future__ import annotations

from archzero.evolve.openevolve_adapter import seed_program_sources


def test_seed_program_sources_noc_uses_score_variant():
    program, evaluator = seed_program_sources("noc", "noc_rg")
    assert "score_variant" in program
    assert "0.12" not in program
    assert "miss_reduction" not in program or "score_variant" in program
    # no hardcoded miss_reduction float in the program
    assert "miss_reduction" not in program
    assert "goodput" in evaluator
