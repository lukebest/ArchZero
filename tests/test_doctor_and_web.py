import json
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from archzero.config import FactoryConfig
from archzero.doctor import run_doctor
from archzero.models import Campaign, Candidate, Tier, TierResult, Verdict
from archzero.store.db import Store
from archzero.web.app import _funnel_stats, make_handler


def test_doctor_has_corpus_and_worker_checks(tmp_cfg):
    from archzero.doctor import run_doctor

    names = {c.name for c in run_doctor(tmp_cfg)}
    assert "corpus scaffold" in names
    assert "worker pool" in names
    assert "ChampSim optional" in names


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


def test_missing_api_key_is_a_warning_not_a_hard_error(tmp_path, monkeypatch):
    """`doctor` is the first command a new user runs; it must not exit 1."""
    monkeypatch.delenv("CURSOR_API_KEY", raising=False)
    cfg = FactoryConfig(state_dir=tmp_path / "state", cursor_api_key=None)
    cfg.ensure_dirs()
    key_check = next(c for c in run_doctor(cfg) if c.name == "CURSOR_API_KEY")
    assert not key_check.ok
    assert key_check.severity == "warn"
    assert "seed-demo" in key_check.detail


def test_doctor_reports_metric_registry_coverage(tmp_cfg):
    check = next(c for c in run_doctor(tmp_cfg) if c.name == "funnel.strict_acc")
    assert "archzero acc" in check.detail


def test_dashboard_exposes_acc_verdict_for_a_campaign(tmp_path):
    """The refusal must be visible in the UI, not only in the terminal."""
    from archzero.funnel.pipeline import acc_gate_for_campaign
    from archzero.spec.ndf import load_problem_package
    from archzero.web.app import make_handler as _mh

    root = Path(__file__).resolve().parents[1]
    cfg = FactoryConfig(state_dir=tmp_path / "state")
    cfg.ensure_dirs()
    store = Store(cfg.db_path)

    noc = load_problem_package(root / "specs" / "noc_low_tail_collectives.md")
    _, acc_meta = acc_gate_for_campaign(cfg, noc, Tier.T4)
    camp = Campaign(name="noc round", problem_id=noc.id, meta={"acc": acc_meta})
    store.save_campaign(camp)

    reloaded = store.get_campaign(camp.id)
    assert reloaded is not None
    acc = reloaded.meta["acc"]
    assert acc["report_only"] is True
    assert acc["backend"] == "noc"
    assert "clamped_from" not in acc
    assert _mh(cfg) is not None

    index = (root / "archzero" / "web" / "static" / "index.html").read_text("utf-8")
    assert "renderAcc(data.acc)" in index, "banner must be wired into campaign render"
    assert "report_only" in index
    assert "stopCampaign" in index
    assert "deleteCampaign" in index
    assert "schedulePoll" in index


def _http(httpd, method: str, path: str):
    url = f"http://127.0.0.1:{httpd.server_address[1]}{path}"
    req = Request(url, method=method)
    try:
        with urlopen(req, timeout=5) as resp:
            return resp.status, json.loads(resp.read().decode())
    except HTTPError as exc:
        return exc.code, json.loads(exc.read().decode())


def test_store_and_api_stop_then_delete(tmp_path):
    cfg = FactoryConfig(state_dir=tmp_path / "state")
    cfg.ensure_dirs()
    store = Store(cfg.db_path)
    camp = Campaign(name="live", problem_id="pp-x", status="running")
    store.save_campaign(camp)
    cand = Candidate(problem_id="pp-x", title="t", mechanism="m")
    store.save_candidate(cand, campaign_id=camp.id)

    Handler = make_handler(cfg)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        code, body = _http(httpd, "DELETE", f"/api/campaigns/{camp.id}")
        assert code == 409
        assert "stop" in body["error"]

        code, body = _http(httpd, "POST", f"/api/campaigns/{camp.id}/stop")
        assert code == 200
        assert body["status"] == "stopped"
        assert store.get_campaign(camp.id).status == "stopped"

        code, body = _http(httpd, "GET", "/api/campaigns")
        assert code == 200
        row = next(c for c in body if c["id"] == camp.id)
        assert row["n_candidates"] == 1

        code, body = _http(httpd, "DELETE", f"/api/campaigns/{camp.id}")
        assert code == 200
        assert store.get_campaign(camp.id) is None
        assert store.list_candidates(campaign_id=camp.id) == []
    finally:
        httpd.shutdown()
        httpd.server_close()
