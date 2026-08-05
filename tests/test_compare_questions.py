from pathlib import Path

from archzero.compare import compare_campaigns, format_compare_text
from archzero.config import FactoryConfig
from archzero.demo_seed import seed_demo_campaign
from archzero.next_questions import questions_from_campaign, write_questions_markdown


def _cfg(tmp_path: Path) -> FactoryConfig:
    cfg = FactoryConfig(
        state_dir=tmp_path / "state",
        gauntlet_personas=tmp_path / "personas",
    )
    cfg.ensure_dirs()
    cfg.gauntlet_personas.mkdir(parents=True, exist_ok=True)
    return cfg


def test_compare_and_next_questions(tmp_path):
    cfg = _cfg(tmp_path)
    a = seed_demo_campaign(cfg)
    b = seed_demo_campaign(cfg, force=True)
    data = compare_campaigns(cfg, a["campaign_id"], b["campaign_id"])
    assert data["a"]["n_candidates"] == 5
    assert data["b"]["n_candidates"] == 5
    assert len(data["funnel"]) == 6
    text = format_compare_text(data)
    assert "Compare campaigns" in text

    q = questions_from_campaign(cfg, a["campaign_id"])
    assert q["n_failures"] >= 1
    assert q["open_questions"]
    out = write_questions_markdown(q, tmp_path / "nq.md")
    assert out.is_file()
    assert "open questions" in out.read_text(encoding="utf-8").lower() or "Questions" in out.read_text(
        encoding="utf-8"
    )
