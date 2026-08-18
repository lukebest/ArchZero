"""Offline e2e / reproduce / corpus must not invent MPKI on NoC specs."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from archzero.config import FactoryConfig
from archzero.demo_seed import seed_noc_report_campaign
from archzero.e2e import run_e2e
from archzero.export_bundle import export_campaign_bundle
from archzero.models import Tier
from archzero.offline import knobs_for, problem_domain
from archzero.reproduce import reproduce_bundle
from archzero.spec.ndf import load_problem_package
from archzero.spec.wizard import scaffold_problem

ROOT = Path(__file__).resolve().parents[1]
NOC_SPEC = ROOT / "specs" / "noc_low_tail_collectives.md"


def test_cache_demo_miss_reduction_is_a_named_fixture():
    from archzero.offline import CACHE_DEMO_MISS_REDUCTION, analytic_snippet

    assert CACHE_DEMO_MISS_REDUCTION == pytest.approx(0.18)
    snippet = analytic_snippet("cache")
    assert "miss_reduction" in snippet
    assert "0.18" in snippet


def test_knobs_for_noc_have_no_miss_reduction():
    knobs = knobs_for("noc", "request_grant")
    assert knobs["domain"] == "noc"
    assert knobs["family"] == "request_grant"
    assert "miss_reduction" not in knobs
    assert "extra_bw" not in knobs
    cache = knobs_for("cache", "prefetch")
    assert "miss_reduction" not in cache
    assert cache.get("family") == "prefetch"


def test_problem_domain_reads_noc_spec():
    pp = load_problem_package(NOC_SPEC)
    assert problem_domain(pp) == "noc"


@pytest.mark.asyncio
async def test_e2e_offline_noc_does_not_write_mpki_knobs(tmp_cfg):
    tmp_cfg.funnel.use_verifiers = False
    result = await run_e2e(
        tmp_cfg, spec_path=NOC_SPEC, through=Tier.T2, offline=True
    )
    assert result["domain"] == "noc"
    assert result["family"] == "request_grant"
    assert "MPKI" not in (result.get("headlines") or "")
    knobs = json.loads(
        (tmp_cfg.scratch_dir / "e2e" / "cand" / "sim_knobs.json").read_text(
            encoding="utf-8"
        )
    )
    assert "miss_reduction" not in knobs
    assert knobs.get("domain") == "noc"
    history = {row["tier"]: row for row in result["tier_history"]}
    assert history["tier2"]["verdict"] == "pass"
    model_py = (tmp_cfg.scratch_dir / "e2e" / "cand" / "model.py").read_text(
        encoding="utf-8"
    )
    assert "noc_model" in model_py
    assert "miss_reduction" not in model_py


@pytest.mark.asyncio
async def test_corpus_batch_noc_entry_no_mpki(tmp_cfg, tmp_path):
    from archzero.corpus.batch_eval import evaluate_corpus_batch

    root = tmp_path / "corpus"
    paper = root / "papers" / "noc-a"
    paper.mkdir(parents=True)
    src = NOC_SPEC.read_text(encoding="utf-8")
    (paper / "problem.md").write_text(src, encoding="utf-8")
    (root / "manifest.json").write_text(
        json.dumps(
            {
                "status": "scaffold",
                "target_size": 95,
                "entries": [
                    {
                        "id": "noc-a",
                        "title": "NoC tail",
                        "spec": "papers/noc-a/problem.md",
                        "family": "request_grant",
                        "pdf": None,
                        "evaluated": False,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    tmp_cfg.funnel.use_verifiers = False
    data = await evaluate_corpus_batch(
        tmp_cfg, corpus_root=root, through=Tier.T2, limit=1
    )
    assert data["ok"]
    assert data["results"][0]["domain"] == "noc"
    knobs = json.loads(
        (tmp_cfg.scratch_dir / "corpus" / "noc-a" / "sim_knobs.json").read_text(
            encoding="utf-8"
        )
    )
    assert "miss_reduction" not in knobs
    model = tmp_cfg.scratch_dir / "corpus" / "noc-a" / "model.py"
    if model.is_file():
        text = model.read_text(encoding="utf-8")
        assert "miss_reduction" not in text
        assert "noc_model" in text


def test_reproduce_noc_bundle_has_headlines_not_mpki(tmp_path):
    cfg = FactoryConfig(
        state_dir=tmp_path / "state",
        gauntlet_personas=tmp_path / "personas",
    )
    cfg.ensure_dirs()
    cfg.gauntlet_personas.mkdir(parents=True, exist_ok=True)
    seeded = seed_noc_report_campaign(cfg)
    # Write knobs so stub replay actually runs
    from archzero.store.db import Store

    store = Store(cfg.db_path)
    for c in store.list_candidates(campaign_id=seeded["campaign_id"]):
        work = Path(c.workdir)
        work.mkdir(parents=True, exist_ok=True)
        (work / "sim_knobs.json").write_text(
            json.dumps({"family": c.family, "domain": "noc"}),
            encoding="utf-8",
        )
    root = export_campaign_bundle(cfg, seeded["campaign_id"], tmp_path / "bundles")
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    assert manifest.get("domain") == "noc"
    checks = reproduce_bundle(cfg, root)
    assert checks["domain"] == "noc"
    assert checks["stub_replays"]
    for row in checks["stub_replays"]:
        assert "miss_reduction" not in row
        assert row["domain"] == "noc"
        keys = [h["key"] for h in row.get("headlines") or []]
        assert "miss_reduction" not in keys


def test_reproduce_legacy_cache_still_reports_miss_reduction(tmp_path):
    cfg = FactoryConfig(state_dir=tmp_path / "state")
    cfg.ensure_dirs()
    root = tmp_path / "bundle"
    arts = root / "artifacts" / "c1"
    arts.mkdir(parents=True)
    (root / "manifest.json").write_text(
        json.dumps({"domain": "cache", "git_sha": None, "sim_backend": "stub"}),
        encoding="utf-8",
    )
    (root / "problem.md").write_text("# cache\n", encoding="utf-8")
    (root / "candidates.json").write_text(
        json.dumps([{"id": "c1", "family": "prefetch"}]), encoding="utf-8"
    )
    (root / "REPORT.md").write_text("ok\n", encoding="utf-8")
    (arts / "sim_knobs.json").write_text(
        json.dumps({"miss_reduction": 0.2, "extra_bw": 0.01, "area": 0.2}),
        encoding="utf-8",
    )
    checks = reproduce_bundle(cfg, root)
    assert checks["stub_replays"]
    assert "miss_reduction" in checks["stub_replays"][0]


def test_scaffold_dataflow_domain():
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        path = scaffold_problem(
            title="df",
            workload="w",
            symptom="s",
            constraint="c",
            domain="dataflow",
            out_dir=Path(td),
        )
        assert problem_domain(load_problem_package(path)) == "dataflow"
