"""OpenEvolve seed programs must follow the problem domain."""

from __future__ import annotations

import pytest
import yaml

from archzero.config import ROOT
from archzero.evolve.openevolve_adapter import (
    oe_command,
    openevolve_available,
    resolve_evolve_domain,
    seed_program_sources,
    write_oe_config,
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
    program, _ = seed_program_sources("noc", "noc_rg")
    assert "EVOLVE-BLOCK-START" in program


def test_write_oe_config_points_at_cursor_shim(tmp_path):
    path = tmp_path / "config.yaml"
    write_oe_config(
        path,
        api_base="http://127.0.0.1:8765/v1",
        model="cursor-grok-4.6-high-fast",
        iterations=3,
    )
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert data["llm"]["api_base"] == "http://127.0.0.1:8765/v1"
    assert data["llm"]["api_key"] == "cursor-shim"
    assert data["llm"]["models"][0]["name"] == "cursor-grok-4.6-high-fast"
    assert data["max_iterations"] == 3


def test_oe_command_uses_vendored_runner_and_shim_url(tmp_path):
    oe = tmp_path / "oe"
    oe.mkdir()
    (oe / "openevolve-run.py").write_text("# stub\n", encoding="utf-8")
    cmd = oe_command(
        oe_root=oe,
        program=tmp_path / "p.py",
        evaluator=tmp_path / "e.py",
        config=tmp_path / "c.yaml",
        output=tmp_path / "out",
        api_base="http://127.0.0.1:9/v1",
        model="cursor-test",
        iterations=2,
    )
    assert cmd[1] == str(oe / "openevolve-run.py")
    assert "--api-base" in cmd
    assert cmd[cmd.index("--api-base") + 1] == "http://127.0.0.1:9/v1"
    assert cmd[cmd.index("--primary-model") + 1] == "cursor-test"


def test_vendored_openevolve_tree_has_cli():
    if not openevolve_available():
        pytest.skip("vendor/openevolve not checked out")
    root = ROOT / "vendor" / "openevolve"
    assert (root / "openevolve" / "cli.py").is_file()
    assert (root / "openevolve" / "llm" / "openai.py").is_file()
