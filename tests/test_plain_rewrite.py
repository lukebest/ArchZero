"""Engineer-readable rewrite cache — no live LLM."""

from __future__ import annotations

import json
import threading
from http.server import ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from archzero.config import FactoryConfig
from archzero.generation.plain import has_plain_rewrite, rewrite_mechanism_plain
from archzero.models import Campaign, Candidate
from archzero.store.db import Store
from archzero.web.app import _serialize_candidate, make_handler


PLAIN = (
    "决策：两环冲突时固定让内环先走。\n"
    "状态：每节点 1bit 当前面。\n"
    "冲突：口忙则推迟一拍。\n"
    "相对基线：只多了固定面优先级。"
)


def _cand(**metrics) -> Candidate:
    return Candidate(
        problem_id="pp-x",
        title="八十环段率失真瓦尔拉斯槽位市",
        mechanism="用瓦尔拉斯拍卖给 flit 定价。",
        family="request_grant",
        metrics=metrics,
    )


def test_has_plain_rewrite_requires_hardware_sections():
    assert not has_plain_rewrite(_cand())
    assert not has_plain_rewrite(_cand(mechanism_plain="   "))
    assert has_plain_rewrite(_cand(mechanism_plain=PLAIN))
    assert has_plain_rewrite(_cand(mechanism_plain="决策：选内环。" + "x" * 40))


@pytest.mark.asyncio
async def test_rewrite_returns_cache_without_llm(tmp_path):
    cfg = FactoryConfig(state_dir=tmp_path / "state")
    cfg.ensure_dirs()
    c = _cand(title_plain="双环固定面优先", mechanism_plain=PLAIN)
    out = await rewrite_mechanism_plain(cfg, c)
    assert out["cached"] is True
    assert out["title_plain"] == "双环固定面优先"
    assert "决策：" in out["mechanism_plain"]


def test_serialize_prefers_plain_fields():
    c = _cand(title_plain="双环固定面优先", mechanism_plain=PLAIN)
    blob = _serialize_candidate(c)
    assert blob["title_plain"] == "双环固定面优先"
    assert blob["has_plain"] is True
    assert blob["mechanism_plain"].startswith("决策：")


def test_persist_plain_keeps_campaign_link(tmp_path):
    cfg = FactoryConfig(state_dir=tmp_path / "state")
    cfg.ensure_dirs()
    store = Store(cfg.db_path)
    camp = Campaign(name="live", problem_id="pp-x")
    store.save_campaign(camp)
    c = _cand()
    store.save_candidate(c, campaign_id=camp.id)
    c.metrics = {"title_plain": "双环固定面优先", "mechanism_plain": PLAIN}
    store.save_candidate(c, campaign_id=store.candidate_campaign_id(c.id))
    assert store.candidate_campaign_id(c.id) == camp.id
    assert store.list_candidates(campaign_id=camp.id)[0].metrics["title_plain"]


def _http(httpd, method: str, path: str):
    url = f"http://127.0.0.1:{httpd.server_address[1]}{path}"
    req = Request(url, method=method)
    try:
        with urlopen(req, timeout=5) as resp:
            return resp.status, json.loads(resp.read().decode())
    except HTTPError as exc:
        return exc.code, json.loads(exc.read().decode())


def test_plain_apis_use_cache_and_keep_campaign(tmp_path):
    cfg = FactoryConfig(state_dir=tmp_path / "state")
    cfg.ensure_dirs()
    store = Store(cfg.db_path)
    camp = Campaign(name="live", problem_id="pp-x")
    store.save_campaign(camp)
    cached = _cand(title_plain="双环固定面优先", mechanism_plain=PLAIN)
    store.save_candidate(cached, campaign_id=camp.id)

    Handler = make_handler(cfg)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        code, body = _http(httpd, "GET", f"/api/candidates/{cached.id}/plain")
        assert code == 200
        assert body["cached"] is True
        assert body["title_plain"] == "双环固定面优先"
        assert store.candidate_campaign_id(cached.id) == camp.id

        code, body = _http(httpd, "GET", f"/api/campaigns/{camp.id}")
        assert code == 200
        row = next(x for x in body["candidates"] if x["id"] == cached.id)
        assert row["has_plain"] is True
        assert row["title_plain"] == "双环固定面优先"

        code, body = _http(httpd, "POST", f"/api/campaigns/{camp.id}/plain?limit=8")
        assert code == 200
        assert body["limit"] == 8
        assert body["remaining"] == 0
        assert body["rewritten"] == []
        assert store.candidate_campaign_id(cached.id) == camp.id
    finally:
        httpd.shutdown()
        httpd.server_close()
