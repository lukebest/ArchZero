"""OpenEvolve seed programs must follow the problem domain."""

from __future__ import annotations

import pytest

from archzero.evolve.openevolve_adapter import (
    resolve_evolve_domain,
    seed_program_sources,
)


def test_seed_program_sources_noc_uses_score_variant():
    program, evaluator = seed_program_sources("noc", "noc_rg")
    assert "score_variant" in program
    assert "0.12" not in program
    assert "miss_reduction" not in program or "score_variant" in program
    # no hardcoded miss_reduction float in the program
    assert "miss_reduction" not in program
    assert "goodput" in evaluator


def test_generic_domain_uses_family_not_mpki():
    program, evaluator = seed_program_sources("generic", "noc_rg")
    assert "score_variant('noc'" in program or 'score_variant("noc"' in program
    assert "goodput" in evaluator
    assert "miss_reduction" not in evaluator


def test_unknown_domain_refuses_mpki_default():
    with pytest.raises(ValueError, match="miss_reduction"):
        resolve_evolve_domain("quantum")
    assert resolve_evolve_domain("generic", "prefetch") == "cache"
