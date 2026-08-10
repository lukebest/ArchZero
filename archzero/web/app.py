"""Lightweight researcher dashboard for Idea Factory campaigns.

Stdlib-only HTTP server — no extra web framework dependency.
Serves a single-page UI plus JSON APIs over the SQLite store.
"""

from __future__ import annotations

import json
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from archzero.config import FactoryConfig, load_config
from archzero.models import Tier, Verdict
from archzero.store.db import Store

STATIC = Path(__file__).with_name("static")


def _funnel_stats(store: Store, campaign_id: str) -> list[dict[str, Any]]:
    cands = store.list_candidates(campaign_id=campaign_id)
    rows = []
    for tier in Tier:
        entered = passed = failed = 0
        for c in cands:
            for tr in c.tier_history:
                if tr.tier != tier:
                    continue
                entered += 1
                if tr.verdict == Verdict.PASS:
                    passed += 1
                elif tr.verdict == Verdict.FAIL:
                    failed += 1
        rows.append(
            {
                "tier": tier.value,
                "entered": entered,
                "passed": passed,
                "failed": failed,
            }
        )
    return rows


def _serialize_candidate(c) -> dict[str, Any]:
    lt = c.last_tier()
    metrics = c.metrics or {}
    mechanism_zh = metrics.get("mechanism_zh")
    title_zh = metrics.get("title_zh")
    return {
        "id": c.id,
        "title": c.title,
        "title_zh": title_zh,
        "family": c.family,
        "status": c.status,
        "mechanism": c.mechanism[:400],
        "mechanism_zh": (str(mechanism_zh)[:400] if mechanism_zh else None),
        "last_tier": lt.tier.value if lt else None,
        "last_verdict": lt.verdict.value if lt else None,
        "score": lt.score if lt else None,
        "failures": len(c.failures),
        "clause_refs": c.clause_refs,
    }


def _looks_cjk(text: str) -> bool:
    return any("\u4e00" <= ch <= "\u9fff" for ch in (text or ""))


async def _translate_mechanism_zh(cfg: FactoryConfig, candidate) -> dict[str, str]:
    """Translate title/mechanism to Simplified Chinese; cache on candidate.metrics."""
    metrics = dict(candidate.metrics or {})
    if metrics.get("mechanism_zh") and _looks_cjk(str(metrics["mechanism_zh"])):
        return {
            "title_zh": str(metrics.get("title_zh") or candidate.title),
            "mechanism_zh": str(metrics["mechanism_zh"]),
            "cached": True,
        }

    from archzero.llm.client import CursorLLM
    from archzero.models import TaskClass

    prompt = (
        "将下面的体系结构机制候选译为简体中文。"
        "保持技术含义准确，专有名词可保留英文括号。"
        "只返回 JSON：{title_zh, mechanism_zh}。\n\n"
        f"TITLE:\n{candidate.title}\n\n"
        f"MECHANISM:\n{candidate.mechanism}"
    )
    async with CursorLLM(cfg) as llm:
        raw = await llm.complete(
            "你是计算机体系结构技术翻译。输出简体中文 JSON，不要 markdown。",
            prompt,
            TaskClass.ANALYTIC,
            expect_json=True,
        )
    text = raw.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        data = json.loads(text[start : end + 1]) if start >= 0 and end > start else {}
    title_zh = str(data.get("title_zh") or candidate.title)
    mechanism_zh = str(data.get("mechanism_zh") or candidate.mechanism)
    metrics["title_zh"] = title_zh
    metrics["mechanism_zh"] = mechanism_zh
    candidate.metrics = metrics
    return {"title_zh": title_zh, "mechanism_zh": mechanism_zh, "cached": False}


def make_handler(cfg: FactoryConfig):
    store = Store(cfg.db_path)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt: str, *args: Any) -> None:  # noqa: A003
            return

        def _json(self, code: int, obj: Any) -> None:
            body = json.dumps(obj, indent=2, default=str).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _html(self, path: Path) -> None:
            data = path.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self) -> None:  # noqa: N802
            parsed = urllib.parse.urlparse(self.path)
            path = parsed.path
            qs = urllib.parse.parse_qs(parsed.query)

            if path in ("/", "/index.html"):
                self._html(STATIC / "index.html")
                return
            if path == "/api/health":
                self._json(200, {"ok": True, "state_dir": str(cfg.state_dir)})
                return
            if path == "/api/campaigns":
                camps = store.list_campaigns()
                self._json(
                    200,
                    [
                        {
                            "id": c.id,
                            "name": c.name,
                            "status": c.status,
                            "through": c.through_tier.value,
                            "problem_id": c.problem_id,
                            "created_at": c.created_at.isoformat(),
                            "n_candidates": len(
                                store.list_candidates(campaign_id=c.id)
                            ),
                        }
                        for c in camps
                    ],
                )
                return
            if path.startswith("/api/campaigns/"):
                cid = path.split("/")[3]
                camp = store.get_campaign(cid)
                if not camp:
                    self._json(404, {"error": "not found"})
                    return
                cands = store.list_candidates(campaign_id=cid)
                through = camp.through_tier
                survivors = sum(1 for c in cands if c.hard_passed(through))
                active = sum(1 for c in cands if c.status in {"new", "active"})
                failed_n = sum(1 for c in cands if c.status == "failed" or (
                    c.last_tier() and c.last_tier().verdict == Verdict.FAIL
                ))
                fail_kinds: dict[str, int] = {}
                for f in store.list_failures(campaign_id=cid):
                    fail_kinds[f.kind.value] = fail_kinds.get(f.kind.value, 0) + 1
                top_fail = max(fail_kinds.items(), key=lambda kv: kv[1])[0] if fail_kinds else None
                self._json(
                    200,
                    {
                        "campaign": {
                            "id": camp.id,
                            "name": camp.name,
                            "status": camp.status,
                            "through": camp.through_tier.value,
                            "problem_id": camp.problem_id,
                            "created_at": camp.created_at.isoformat(),
                        },
                        "summary": {
                            "n_candidates": len(cands),
                            "survivors": survivors,
                            "active": active,
                            "failed": failed_n,
                            "through": through.value,
                            "top_failure_kind": top_fail,
                            "failure_kinds": fail_kinds,
                        },
                        "funnel": _funnel_stats(store, cid),
                        "elimination": (camp.meta or {}).get("elimination"),
                        "usage": store.usage_totals(cid),
                        "candidates": [_serialize_candidate(c) for c in cands],
                        "failures": [
                            {
                                "id": f.id,
                                "candidate_id": f.candidate_id,
                                "tier": f.tier.value,
                                "kind": f.kind.value,
                                "message": f.message,
                            }
                            for f in store.list_failures(campaign_id=cid)
                        ],
                    },
                )
                return
            if path.startswith("/api/candidates/"):
                parts = [p for p in path.split("/") if p]
                # /api/candidates/<id> or /api/candidates/<id>/zh
                if len(parts) < 3:
                    self._json(404, {"error": "not found"})
                    return
                cid = parts[2]
                c = store.get_candidate(cid)
                if not c:
                    self._json(404, {"error": "not found"})
                    return
                if len(parts) >= 4 and parts[3] == "zh":
                    import asyncio

                    try:
                        zh = asyncio.run(_translate_mechanism_zh(cfg, c))
                    except Exception as exc:  # noqa: BLE001
                        self._json(500, {"error": f"translate failed: {exc}"})
                        return
                    store.save_candidate(c)
                    self._json(
                        200,
                        {
                            "id": c.id,
                            "title_zh": zh["title_zh"],
                            "mechanism_zh": zh["mechanism_zh"],
                            "cached": bool(zh.get("cached")),
                        },
                    )
                    return
                metrics = c.metrics or {}
                self._json(
                    200,
                    {
                        **_serialize_candidate(c),
                        "mechanism_full": c.mechanism,
                        "mechanism_zh_full": metrics.get("mechanism_zh"),
                        "title_zh": metrics.get("title_zh"),
                        "metrics": c.metrics,
                        "tier_history": [
                            {
                                "tier": t.tier.value,
                                "verdict": t.verdict.value,
                                "score": t.score,
                                "summary": t.summary,
                            }
                            for t in c.tier_history
                        ],
                        "failures": [
                            {
                                "tier": f.tier.value,
                                "kind": f.kind.value,
                                "message": f.message,
                            }
                            for f in c.failures
                        ],
                    },
                )
                return
            if path == "/api/compare":
                ids = qs.get("ids") or []
                if len(ids) == 1 and "," in ids[0]:
                    ids = [x.strip() for x in ids[0].split(",") if x.strip()]
                if len(ids) < 2:
                    a = (qs.get("a") or [None])[0]
                    b = (qs.get("b") or [None])[0]
                    if a and b:
                        ids = [a, b]
                if len(ids) < 2:
                    self._json(400, {"error": "need two campaign ids: ?a=&b= or ?ids=a,b"})
                    return
                from archzero.compare import compare_campaigns

                try:
                    self._json(200, compare_campaigns(cfg, ids[0], ids[1]))
                except ValueError as exc:
                    self._json(404, {"error": str(exc)})
                return
            if path == "/api/meta":
                self._json(
                    200,
                    {
                        "product": "ArchZero Idea Factory",
                        "paper": "https://arxiv.org/abs/2604.03312",
                        "sim_backend": cfg.sim.backend,
                        "strict_evidence": cfg.funnel.strict_evidence,
                        "telemetry": "deferred",
                        "tier6": "planned_reserved",
                        "evidence_levels": [
                            "stub",
                            "analytic",
                            "sim",
                            "rtl",
                            "signoff",
                        ],
                        "quickstart": "/quickstart.html",
                    },
                )
                return
            if path == "/quickstart.html":
                self._html(STATIC / "quickstart.html")
                return
            self._json(404, {"error": "not found", "path": path, "q": qs})

    return Handler


def serve(host: str = "127.0.0.1", port: int = 8787, config: Path | None = None) -> None:
    cfg = load_config(config)
    cfg.ensure_dirs()
    handler = make_handler(cfg)
    httpd = ThreadingHTTPServer((host, port), handler)
    print(f"ArchZero dashboard → http://{host}:{port}/")
    print("Ctrl+C to stop. Telemetry layer deferred; this UI shows Generation+Evaluation.")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
        httpd.server_close()
