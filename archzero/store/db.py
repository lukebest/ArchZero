"""SQLite persistence for campaigns, candidates, failures, and usage."""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from archzero.models import (
    Campaign,
    Candidate,
    FailureRecord,
    ProblemPackage,
    TierResult,
    UsageEvent,
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS problems (
  id TEXT PRIMARY KEY,
  json TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS campaigns (
  id TEXT PRIMARY KEY,
  json TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS candidates (
  id TEXT PRIMARY KEY,
  campaign_id TEXT,
  problem_id TEXT NOT NULL,
  content_hash TEXT,
  status TEXT NOT NULL,
  json TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_cand_campaign ON candidates(campaign_id);
CREATE INDEX IF NOT EXISTS idx_cand_hash ON candidates(content_hash);

CREATE TABLE IF NOT EXISTS failures (
  id TEXT PRIMARY KEY,
  candidate_id TEXT NOT NULL,
  tier TEXT NOT NULL,
  kind TEXT NOT NULL,
  json TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS usage_events (
  id TEXT PRIMARY KEY,
  campaign_id TEXT,
  pool TEXT NOT NULL,
  model_id TEXT NOT NULL,
  total_tokens INTEGER NOT NULL,
  json TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS kv (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS schema_meta (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
"""

SCHEMA_VERSION = "2"


def _dumps(obj: Any) -> str:
    if hasattr(obj, "model_dump"):
        return json.dumps(obj.model_dump(mode="json"), default=str)
    return json.dumps(obj, default=str)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Store:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as conn:
            conn.executescript(SCHEMA)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA busy_timeout=5000")
            conn.execute(
                "INSERT OR REPLACE INTO schema_meta(key, value) VALUES (?, ?)",
                ("schema_version", SCHEMA_VERSION),
            )

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=5000")
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    # --- problems ---
    def save_problem(self, pp: ProblemPackage) -> None:
        with self._conn() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO problems(id, json, created_at) VALUES (?,?,?)",
                (pp.id, _dumps(pp), pp.created_at.isoformat()),
            )

    def get_problem(self, pid: str) -> ProblemPackage | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT json FROM problems WHERE id=?", (pid,)
            ).fetchone()
        return ProblemPackage.model_validate_json(row["json"]) if row else None

    # --- campaigns ---
    def save_campaign(self, c: Campaign) -> None:
        with self._conn() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO campaigns(id, json, created_at) VALUES (?,?,?)",
                (c.id, _dumps(c), c.created_at.isoformat()),
            )

    def get_campaign(self, cid: str) -> Campaign | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT json FROM campaigns WHERE id=?", (cid,)
            ).fetchone()
        return Campaign.model_validate_json(row["json"]) if row else None

    def list_campaigns(self) -> list[Campaign]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT json FROM campaigns ORDER BY created_at DESC"
            ).fetchall()
        return [Campaign.model_validate_json(r["json"]) for r in rows]

    # --- candidates ---
    def save_candidate(self, cand: Candidate, campaign_id: str | None = None) -> None:
        cand.updated_at = datetime.now(timezone.utc)
        with self._conn() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO candidates
                   (id, campaign_id, problem_id, content_hash, status, json, created_at, updated_at)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (
                    cand.id,
                    campaign_id,
                    cand.problem_id,
                    cand.content_hash,
                    cand.status,
                    _dumps(cand),
                    cand.created_at.isoformat(),
                    cand.updated_at.isoformat(),
                ),
            )

    def get_candidate(self, cid: str) -> Candidate | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT json FROM candidates WHERE id=?", (cid,)
            ).fetchone()
        return Candidate.model_validate_json(row["json"]) if row else None

    def list_candidates(
        self, campaign_id: str | None = None, status: str | None = None
    ) -> list[Candidate]:
        q = "SELECT json FROM candidates WHERE 1=1"
        args: list[Any] = []
        if campaign_id:
            q += " AND campaign_id=?"
            args.append(campaign_id)
        if status:
            q += " AND status=?"
            args.append(status)
        q += " ORDER BY created_at"
        with self._conn() as conn:
            rows = conn.execute(q, args).fetchall()
        return [Candidate.model_validate_json(r["json"]) for r in rows]

    def find_by_hash(self, content_hash: str) -> Candidate | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT json FROM candidates WHERE content_hash=? LIMIT 1",
                (content_hash,),
            ).fetchone()
        return Candidate.model_validate_json(row["json"]) if row else None

    # --- failures ---
    def save_failure(self, f: FailureRecord) -> None:
        with self._conn() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO failures
                   (id, candidate_id, tier, kind, json, created_at)
                   VALUES (?,?,?,?,?,?)""",
                (
                    f.id,
                    f.candidate_id,
                    f.tier.value,
                    f.kind.value,
                    _dumps(f),
                    f.created_at.isoformat(),
                ),
            )

    def list_failures(
        self, candidate_id: str | None = None, campaign_id: str | None = None
    ) -> list[FailureRecord]:
        if campaign_id:
            cands = self.list_candidates(campaign_id=campaign_id)
            ids = {c.id for c in cands}
            with self._conn() as conn:
                rows = conn.execute("SELECT json FROM failures").fetchall()
            out = [FailureRecord.model_validate_json(r["json"]) for r in rows]
            return [f for f in out if f.candidate_id in ids]
        if candidate_id:
            with self._conn() as conn:
                rows = conn.execute(
                    "SELECT json FROM failures WHERE candidate_id=?",
                    (candidate_id,),
                ).fetchall()
            return [FailureRecord.model_validate_json(r["json"]) for r in rows]
        with self._conn() as conn:
            rows = conn.execute("SELECT json FROM failures").fetchall()
        return [FailureRecord.model_validate_json(r["json"]) for r in rows]

    # --- usage ---
    def save_usage(self, ev: UsageEvent) -> None:
        with self._conn() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO usage_events
                   (id, campaign_id, pool, model_id, total_tokens, json, created_at)
                   VALUES (?,?,?,?,?,?,?)""",
                (
                    ev.id,
                    ev.campaign_id,
                    ev.pool.value,
                    ev.model_id,
                    ev.total_tokens,
                    _dumps(ev),
                    ev.created_at.isoformat(),
                ),
            )

    def list_usage(self, campaign_id: str | None = None) -> list[UsageEvent]:
        if campaign_id:
            with self._conn() as conn:
                rows = conn.execute(
                    "SELECT json FROM usage_events WHERE campaign_id=?",
                    (campaign_id,),
                ).fetchall()
        else:
            with self._conn() as conn:
                rows = conn.execute("SELECT json FROM usage_events").fetchall()
        return [UsageEvent.model_validate_json(r["json"]) for r in rows]

    def usage_totals(self, campaign_id: str | None = None) -> dict[str, Any]:
        events = self.list_usage(campaign_id)
        by_pool: dict[str, dict[str, int]] = {}
        for e in events:
            bucket = by_pool.setdefault(
                e.pool.value, {"calls": 0, "tokens": 0}
            )
            bucket["calls"] += 1
            bucket["tokens"] += e.total_tokens
        return by_pool

    # --- kv ---
    def set_kv(self, key: str, value: str) -> None:
        with self._conn() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO kv(key, value) VALUES (?,?)",
                (key, value),
            )

    def get_kv(self, key: str) -> str | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT value FROM kv WHERE key=?", (key,)
            ).fetchone()
        return row["value"] if row else None

    def append_tier_result(
        self, candidate_id: str, result: TierResult, campaign_id: str | None = None
    ) -> Candidate | None:
        cand = self.get_candidate(candidate_id)
        if cand is None:
            return None
        cand.tier_history.append(result)
        if result.verdict.value == "fail":
            cand.status = "failed"
        elif result.verdict.value == "pass":
            cand.status = "active"
        self.save_candidate(cand, campaign_id=campaign_id)
        return cand
