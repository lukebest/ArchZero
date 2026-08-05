from archzero.config import FactoryConfig
from archzero.models import Campaign, Candidate, FailureKind, FailureRecord, Tier
from archzero.store.db import Store


def test_store_roundtrip(tmp_path):
    cfg = FactoryConfig(state_dir=tmp_path / "state")
    cfg.ensure_dirs()
    store = Store(cfg.db_path)
    camp = Campaign(name="t", problem_id="pp-x")
    store.save_campaign(camp)
    cand = Candidate(
        problem_id="pp-x",
        title="A",
        mechanism="do thing",
        content_hash="abc123",
    )
    store.save_candidate(cand, campaign_id=camp.id)
    got = store.get_candidate(cand.id)
    assert got is not None
    assert got.title == "A"
    store.save_failure(
        FailureRecord(
            candidate_id=cand.id,
            tier=Tier.T0,
            kind=FailureKind.PHYSICS,
            message="bandwidth",
        )
    )
    fails = store.list_failures(campaign_id=camp.id)
    assert len(fails) == 1
