from pathlib import Path

from archzero.config import FactoryConfig
from archzero.generation.frontier import expand_frontier, offline_expand
from archzero.generation.theories import THEORY_LENSES, theory_catalog_markdown
from archzero.spec.ndf import load_problem_package


def test_theory_catalog_has_paper_lenses():
    ids = {t.id for t in THEORY_LENSES}
    assert "information_theory" in ids
    assert "queueing_theory" in ids
    assert "category_theory" in ids
    assert "coding_theory" in ids
    assert len(THEORY_LENSES) == 8
    md = theory_catalog_markdown()
    assert "§5.1" in md or "5.1" in md


def test_offline_expand_three_modes(tmp_path):
    demo = Path(__file__).resolve().parents[1] / "specs" / "demo.md"
    pp = load_problem_package(demo)
    packages, candidates = offline_expand(pp)
    kinds = {c.kind for c in candidates}
    assert kinds == {"vertical", "lateral", "foundational"}
    assert any(c.theory_lenses for c in candidates if c.kind != "vertical")
    assert any("paradigm" in (c.paradigm_shift_claim or "").lower()
               or c.kind == "foundational" for c in candidates)
    assert len(packages) == 3


async def test_expand_frontier_offline_writes(tmp_path):
    cfg = FactoryConfig(state_dir=tmp_path / "state")
    cfg.ensure_dirs()
    demo = Path(__file__).resolve().parents[1] / "specs" / "demo.md"
    pp = load_problem_package(demo)
    out = tmp_path / "frontiers"
    result = await expand_frontier(cfg, pp, out_dir=out, offline=True)
    assert result["offline"] is True
    assert (out / "PARADIGM_REPORT.md").is_file()
    assert (out / "paradigm_candidates.json").is_file()
    assert (out / "THEORY_LENSES.md").is_file()
    assert len(result["candidates"]) == 3
    assert any(c.kind == "lateral" for c in result["candidates"])
