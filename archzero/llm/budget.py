"""Usage-pool budget guardrails."""

from __future__ import annotations

from dataclasses import dataclass, field

from archzero.config import BudgetConfig
from archzero.models import UsagePool
from archzero.store.db import Store


@dataclass
class BudgetGuard:
    cfg: BudgetConfig
    store: Store
    campaign_id: str | None = None
    _local_other_tokens: int = 0
    _local_other_calls: int = 0
    _local_cursor_tokens: int = 0
    _local_cursor_calls: int = 0
    denied: list[str] = field(default_factory=list)

    def refresh_from_store(self) -> None:
        totals = self.store.usage_totals(self.campaign_id)
        other = totals.get(UsagePool.OTHER.value, {"tokens": 0, "calls": 0})
        cursor = totals.get(UsagePool.CURSOR.value, {"tokens": 0, "calls": 0})
        self._local_other_tokens = other["tokens"]
        self._local_other_calls = other["calls"]
        self._local_cursor_tokens = cursor["tokens"]
        self._local_cursor_calls = cursor["calls"]

    def allow(self, pool: UsagePool) -> bool:
        if pool == UsagePool.CURSOR:
            return True
        if self._local_other_tokens >= self.cfg.other_pool_max_tokens:
            self.denied.append("other_pool_max_tokens")
            return False
        if self._local_other_calls >= self.cfg.other_pool_max_calls:
            self.denied.append("other_pool_max_calls")
            return False
        return True

    def record(self, pool: UsagePool, tokens: int) -> None:
        if pool == UsagePool.OTHER:
            self._local_other_tokens += tokens
            self._local_other_calls += 1
        else:
            self._local_cursor_tokens += tokens
            self._local_cursor_calls += 1

    def snapshot(self) -> dict[str, int]:
        return {
            "cursor_tokens": self._local_cursor_tokens,
            "cursor_calls": self._local_cursor_calls,
            "other_tokens": self._local_other_tokens,
            "other_calls": self._local_other_calls,
        }
