from pathlib import Path

from archzero.config import FactoryConfig
from archzero.doctor import run_doctor
from archzero.models import Campaign, Candidate, Tier, TierResult, Verdict
from archzero.store.db import Store
from archzero.web.app import _funnel_stats, make_handler


def test_doctor_reports_checks(tmp_path):
    cfg = FactoryConfig(
        state_dir=tmp_path / "state",
        gauntlet_personas=tmp_path / "missing_personas",
    )
    cfg.ensure_dirs()
    checks = run_doctor(cfg)
    names = {c.name for c in checks}
    assert "CURSOR_API_KEY" in names
    assert "sim backend (stub)" in names


def test_funnel_stats(tmp_path):
    cfg = FactoryConfig(state_dir=tmp_path / "state")
    cfg.ensure_dirs()
    store = Store(cfg.db_path)
    camp = Campaign(name="demo", problem_id="pp-x")
    store.save_campaign(camp)
    cand = Candidate(problem_id="pp-x", title="t", mechanism="m")
    cand.tier_history.append(
        TierResult(tier=Tier.T0, verdict=Verdict.PASS, score=0.8, summary="ok")
    )
    store.save_candidate(cand, campaign_id=camp.id)
    rows = _funnel_stats(store, camp.id)
    t0 = next(r for r in rows if r["tier"] == "tier0")
    assert t0["entered"] == 1
    assert t0["passed"] == 1


def test_web_handler_health(tmp_path):
    cfg = FactoryConfig(state_dir=tmp_path / "state")
    cfg.ensure_dirs()
    Handler = make_handler(cfg)
    assert Handler is not None
    assert (Path(__file__).resolve().parents[1] / "archzero" / "web" / "static" / "index.html").is_file()
