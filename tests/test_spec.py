from pathlib import Path

from archzero.spec.lint import lint_package
from archzero.spec.ndf import load_problem_package


def test_demo_spec_lints_clean():
    path = Path(__file__).resolve().parents[1] / "specs" / "demo.md"
    pp = load_problem_package(path)
    assert pp.title
    assert any(c.id.startswith("REQ") for c in pp.clauses)
    assert any(c.id.startswith("ACC") for c in pp.clauses)
    issues = lint_package(pp)
    assert issues == [], issues


def test_refines_resolved():
    path = Path(__file__).resolve().parents[1] / "specs" / "demo.md"
    pp = load_problem_package(path)
    ids = pp.clause_ids()
    for c in pp.clauses:
        for r in c.refines:
            assert r in ids
