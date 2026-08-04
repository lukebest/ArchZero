"""Discover Cursor models and classify them into usage pools."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from archzero.config import FactoryConfig
from archzero.models import TaskClass, UsagePool


@dataclass
class ModelInfo:
    id: str
    raw: dict[str, Any] | None = None


class ModelCatalog:
    def __init__(self, cfg: FactoryConfig) -> None:
        self.cfg = cfg
        self._cache_path = cfg.state_dir / "model_catalog.json"
        self._models: list[ModelInfo] | None = None

    async def list_models(self, refresh: bool = False) -> list[ModelInfo]:
        if self._models is not None and not refresh:
            return self._models
        if self._cache_path.exists() and not refresh:
            data = json.loads(self._cache_path.read_text(encoding="utf-8"))
            self._models = [ModelInfo(id=m["id"], raw=m.get("raw")) for m in data]
            return self._models

        models = await self._fetch_remote()
        self._models = models
        self.cfg.state_dir.mkdir(parents=True, exist_ok=True)
        self._cache_path.write_text(
            json.dumps([{"id": m.id, "raw": m.raw} for m in models], indent=2),
            encoding="utf-8",
        )
        return models

    def _fallback_models(self) -> list[ModelInfo]:
        return [
            ModelInfo(id=mid)
            for mid in (
                list(self.cfg.pools.cursor_models)
                + [self.cfg.pools.preferred_other, "auto", "auto-smart"]
            )
        ]

    async def _fetch_remote(self) -> list[ModelInfo]:
        try:
            api_key = self.cfg.resolved_api_key()
        except RuntimeError:
            return self._fallback_models()

        try:
            from cursor_sdk import Cursor  # type: ignore

            raw_list = Cursor.models.list(api_key=api_key)
        except TypeError:
            # some versions take no kwargs and read env
            import os

            os.environ.setdefault("CURSOR_API_KEY", api_key)
            from cursor_sdk import Cursor  # type: ignore

            raw_list = Cursor.models.list()
        except Exception:  # noqa: BLE001
            # Offline / SDK error — return configured defaults so routing still works
            return self._fallback_models()

        out: list[ModelInfo] = []
        for item in raw_list or []:
            mid = getattr(item, "id", None) or (
                item.get("id") if isinstance(item, dict) else None
            )
            if not mid:
                continue
            raw = item if isinstance(item, dict) else getattr(item, "__dict__", {})
            out.append(ModelInfo(id=str(mid), raw=raw if isinstance(raw, dict) else None))
        if not out:
            out = [ModelInfo(id=m) for m in self.cfg.pools.cursor_models]
        return out

    def classify(self, model_id: str) -> UsagePool:
        if model_id in self.cfg.pools.cursor_models:
            return UsagePool.CURSOR
        if model_id in ("auto", "auto-smart", "composer-2", "composer-2.5", "cursor-grok-4.5"):
            return UsagePool.CURSOR
        for prefix in self.cfg.pools.other_prefixes:
            if model_id.startswith(prefix):
                return UsagePool.OTHER
        # Unknown IDs: treat as other (safer for budget)
        if model_id.startswith("cursor-") or "composer" in model_id or "grok" in model_id:
            return UsagePool.CURSOR
        return UsagePool.OTHER

    def classify_all(self, models: list[ModelInfo]) -> dict[str, UsagePool]:
        return {m.id: self.classify(m.id) for m in models}

    def pick_for_pool(
        self, pool: UsagePool, available: list[ModelInfo] | None = None
    ) -> str:
        ids = {m.id for m in (available or self._models or [])}
        if pool == UsagePool.CURSOR:
            preferred = self.cfg.pools.preferred_cursor
            if not ids or preferred in ids:
                return preferred
            for mid in self.cfg.pools.cursor_models:
                if mid in ids:
                    return mid
            if "auto-smart" in ids:
                return "auto-smart"
            if "auto" in ids:
                return "auto"
            return preferred
        # OTHER
        preferred = self.cfg.pools.preferred_other
        if not ids or preferred in ids:
            return preferred
        for m in available or []:
            if self.classify(m.id) == UsagePool.OTHER:
                return m.id
        if "auto-smart" in ids:
            return "auto-smart"
        return preferred

    def resolved_routes(self) -> dict[str, tuple[UsagePool, str]]:
        models = self._models or [
            ModelInfo(id=m) for m in self.cfg.pools.cursor_models
        ]
        out: dict[str, tuple[UsagePool, str]] = {}
        for task in TaskClass:
            pool = self.cfg.routing.pool_for(task)
            mid = self.pick_for_pool(pool, models)
            out[task.value] = (pool, mid)
        return out
