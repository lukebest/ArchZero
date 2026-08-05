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
    return {
        "id": c.id,
        "title": c.title,
        "family": c.family,
        "status": c.status,
        "mechanism": c.mechanism[:400],
        "last_tier": lt.tier.value if lt else None,
        "last_verdict": lt.verdict.value if lt else None,
        "score": lt.score if lt else None,
        "failures": len(c.failures),
        "clause_refs": c.clause_refs,
    }


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
                self._json(
                    200,
                    {
                        "campaign": {
                            "id": camp.id,
                            "name": camp.name,
                            "status": camp.status,
                            "through": camp.through_tier.value,
                            "problem_id": camp.problem_id,
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
                cid = path.split("/")[3]
                c = store.get_candidate(cid)
                if not c:
                    self._json(404, {"error": "not found"})
                    return
                self._json(
                    200,
                    {
                        **_serialize_candidate(c),
                        "mechanism_full": c.mechanism,
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
