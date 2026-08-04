"""Pool-aware model router with budget downgrade."""

from __future__ import annotations

from dataclasses import dataclass

from archzero.config import FactoryConfig
from archzero.llm.budget import BudgetGuard
from archzero.llm.catalog import ModelCatalog
from archzero.models import TaskClass, UsagePool


@dataclass
class RoutedModel:
    model_id: str
    pool: UsagePool
    task: TaskClass
    downgraded: bool = False
    optimize_for: str | None = None


class ModelRouter:
    def __init__(
        self,
        cfg: FactoryConfig,
        catalog: ModelCatalog,
        budget: BudgetGuard | None = None,
    ) -> None:
        self.cfg = cfg
        self.catalog = catalog
        self.budget = budget

    def pick(self, task: TaskClass) -> RoutedModel:
        desired = self.cfg.routing.pool_for(task)
        available = self.catalog._models
        model_id = self.catalog.pick_for_pool(desired, available)
        pool = self.catalog.classify(model_id)
        downgraded = False

        if pool == UsagePool.OTHER and self.budget and not self.budget.allow(pool):
            # Downgrade to cursor pool
            model_id = self.catalog.pick_for_pool(UsagePool.CURSOR, available)
            pool = UsagePool.CURSOR
            downgraded = True

        optimize_for = None
        if model_id == "auto-smart":
            optimize_for = self.cfg.pools.optimize_for

        return RoutedModel(
            model_id=model_id,
            pool=pool,
            task=task,
            downgraded=downgraded,
            optimize_for=optimize_for,
        )
