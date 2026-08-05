from pathlib import Path

from archzero.config import FactoryConfig
from archzero.demo_seed import seed_demo_campaign
from archzero.export_bundle import export_campaign_bundle
from archzero.spec.lint import lint_package
from archzero.spec.ndf import load_problem_package
from archzero.spec.wizard import scaffold_problem


def test_scaffold_problem_lints_clean(tmp_path):
    path = scaffold_problem(
        title="LLM Decode Bandwidth Wall",
        workload="Llama-70B decode batch=8 on HBM3e",
        symptom="L2 MPKI spikes during speculative decode windows",
        constraint="Area <= 0.5 mm^2; no ISA changes",
        out_dir=tmp_path / "specs",
    )
    assert path.is_file()
    pp = load_problem_package(path)
    issues = lint_package(pp)
    assert issues == [], issues
    assert any(c.id.startswith("REQ") for c in pp.clauses)
    assert any(c.id.startswith("ACC") for c in pp.clauses)


def test_export_seed_demo_campaign(tmp_path):
    cfg = FactoryConfig(
        state_dir=tmp_path / "state",
        gauntlet_personas=tmp_path / "personas",
    )
    cfg.ensure_dirs()
    cfg.gauntlet_personas.mkdir(parents=True, exist_ok=True)
    result = seed_demo_campaign(cfg)
    root = export_campaign_bundle(cfg, result["campaign_id"], tmp_path / "bundles")
    assert (root / "manifest.json").is_file()
    assert (root / "problem.md").is_file()
    assert (root / "candidates.json").is_file()
    assert (root / "REPORT.md").is_file()
    assert (root / "README.md").is_file()
    cand_mds = list((root / "candidates").glob("*.md"))
    assert len(cand_mds) >= 1
