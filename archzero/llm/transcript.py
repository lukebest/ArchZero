"""Transcript logging for agent/run IDs."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class TranscriptLog:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / "transcripts.jsonl"

    def log(
        self,
        *,
        agent_id: str | None,
        run_id: str | None,
        model: str,
        task: str,
        pool: str,
        status: str,
        extra: dict[str, Any] | None = None,
    ) -> None:
        rec = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "agent_id": agent_id,
            "run_id": run_id,
            "model": model,
            "task": task,
            "pool": pool,
            "status": status,
            **(extra or {}),
        }
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec) + "\n")
