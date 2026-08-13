from archzero.config import FactoryConfig
from archzero.llm.budget import BudgetGuard
from archzero.llm.catalog import ModelCatalog, ModelInfo
from archzero.llm.router import ModelRouter
from archzero.models import TaskClass, UsagePool
from archzero.store.db import Store


def test_all_tasks_default_to_grok_high_fast(tmp_path):
    cfg = FactoryConfig(state_dir=tmp_path / "state")
    cfg.ensure_dirs()
    store = Store(cfg.db_path)
    catalog = ModelCatalog(cfg)
    catalog._models = [
        ModelInfo(id="cursor-grok-4.6-high-fast"),
        ModelInfo(id="composer-2.5"),
        ModelInfo(id="claude-4.6-sonnet"),
    ]
    budget = BudgetGuard(cfg.budget, store)
    router = ModelRouter(cfg, catalog, budget)
    for task in TaskClass:
        routed = router.pick(task)
        assert routed.pool == UsagePool.CURSOR
        assert routed.model_id == "cursor-grok-4.6-high-fast"


def test_preferred_cursor_used_even_if_missing_from_catalog(tmp_path):
    cfg = FactoryConfig(state_dir=tmp_path / "state")
    cfg.ensure_dirs()
    store = Store(cfg.db_path)
    catalog = ModelCatalog(cfg)
    # Remote catalog may only expose grok-4.5 / composer; still honor preferred.
    catalog._models = [
        ModelInfo(id="grok-4.6"),
        ModelInfo(id="composer-2.5"),
    ]
    budget = BudgetGuard(cfg.budget, store)
    router = ModelRouter(cfg, catalog, budget)
    routed = router.pick(TaskClass.BULK_SCREEN)
    assert routed.model_id == "cursor-grok-4.6-high-fast"


def test_budget_downgrade(tmp_path):
    cfg = FactoryConfig(state_dir=tmp_path / "state")
    cfg.budget.other_pool_max_calls = 0
    cfg.pools.preferred_other = "claude-4.6-sonnet"
    # Force OTHER for this task so budget guard can downgrade
    cfg.routing.routes[TaskClass.SYNTHESIZE.value] = UsagePool.OTHER.value
    cfg.ensure_dirs()
    store = Store(cfg.db_path)
    catalog = ModelCatalog(cfg)
    catalog._models = [
        ModelInfo(id="cursor-grok-4.6-high-fast"),
        ModelInfo(id="claude-4.6-sonnet"),
    ]
    budget = BudgetGuard(cfg.budget, store)
    router = ModelRouter(cfg, catalog, budget)
    routed = router.pick(TaskClass.SYNTHESIZE)
    assert routed.pool == UsagePool.CURSOR
    assert routed.downgraded is True
    assert routed.model_id == "cursor-grok-4.6-high-fast"
