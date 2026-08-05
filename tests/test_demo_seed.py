from archzero.config import FactoryConfig
from archzero.demo_seed import seed_demo_campaign
from archzero.models import Tier
from archzero.store.db import Store


def test_seed_demo_creates_funnel(tmp_path):
    cfg = FactoryConfig(
        state_dir=tmp_path / "state",
        gauntlet_personas=tmp_path / "personas",
    )
    cfg.ensure_dirs()
    cfg.gauntlet_personas.mkdir(parents=True, exist_ok=True)
    result = seed_demo_campaign(cfg)
    assert result["created"] is True
    store = Store(cfg.db_path)
    cands = store.list_candidates(campaign_id=result["campaign_id"])
    assert len(cands) == 5
    assert any(c.passed_through(Tier.T3) for c in cands)
    assert any(c.status == "failed" for c in cands)
    assert any(c.status == "active" for c in cands)
    again = seed_demo_campaign(cfg)
    assert again["created"] is False
