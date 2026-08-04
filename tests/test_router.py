from archzero.config import FactoryConfig
from archzero.llm.budget import BudgetGuard
from archzero.llm.catalog import ModelCatalog, ModelInfo
from archzero.llm.router import ModelRouter
from archzero.models import TaskClass, UsagePool
from archzero.store.db import Store


def test_router_bulk_uses_cursor_pool(tmp_path):
    cfg = FactoryConfig(state_dir=tmp_path / "state")
    cfg.ensure_dirs()
    store = Store(cfg.db_path)
    catalog = ModelCatalog(cfg)
    catalog._models = [
        ModelInfo(id="composer-2.5"),
        ModelInfo(id="claude-4.6-sonnet"),
    ]
    budget = BudgetGuard(cfg.budget, store)
    router = ModelRouter(cfg, catalog, budget)
    routed = router.pick(TaskClass.BULK_SCREEN)
    assert routed.pool == UsagePool.CURSOR
    assert "composer" in routed.model_id or routed.model_id == "composer-2.5"


def test_budget_downgrade(tmp_path):
    cfg = FactoryConfig(state_dir=tmp_path / "state")
    cfg.budget.other_pool_max_calls = 0
    cfg.ensure_dirs()
    store = Store(cfg.db_path)
    catalog = ModelCatalog(cfg)
    catalog._models = [
        ModelInfo(id="composer-2.5"),
        ModelInfo(id="claude-4.6-sonnet"),
    ]
    budget = BudgetGuard(cfg.budget, store)
    router = ModelRouter(cfg, catalog, budget)
    routed = router.pick(TaskClass.SYNTHESIZE)
    assert routed.pool == UsagePool.CURSOR
    assert routed.downgraded is True
