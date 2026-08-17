"""CLI status/show must print domain headlines, not treat score as MPKI."""

from __future__ import annotations

from typer.testing import CliRunner

from archzero.cli import app
from archzero.config import FactoryConfig
from archzero.demo_seed import seed_noc_report_campaign
from archzero.store.db import Store


def _cfg_toml(tmp_path) -> tuple[FactoryConfig, str]:
    cfg = FactoryConfig(
        state_dir=tmp_path / "state",
        gauntlet_personas=tmp_path / "personas",
    )
    cfg.ensure_dirs()
    cfg.gauntlet_personas.mkdir(parents=True, exist_ok=True)
    toml = tmp_path / "archzero.toml"
    toml.write_text(f'state_dir = "{cfg.state_dir}"\n', encoding="utf-8")
    return cfg, str(toml)


def test_status_noc_campaign_shows_headlines_not_mpki(tmp_path):
    cfg, toml = _cfg_toml(tmp_path)
    seeded = seed_noc_report_campaign(cfg)
    runner = CliRunner()
    result = runner.invoke(app, ["-c", toml, "status", seeded["campaign_id"]])
    assert result.exit_code == 0, result.output
    out = result.output
    assert "headlines" in out.lower() or "p99" in out or "goodput" in out
    assert "MPKI" not in out
    assert "miss_reduction" not in out
    # funnel table still present
    assert "Funnel" in out or "tier0" in out


def test_show_noc_candidate_headlines(tmp_path):
    cfg, toml = _cfg_toml(tmp_path)
    seeded = seed_noc_report_campaign(cfg)
    store = Store(cfg.db_path)
    cand = store.list_candidates(campaign_id=seeded["campaign_id"])[0]
    runner = CliRunner()
    result = runner.invoke(app, ["-c", toml, "show", cand.id])
    assert result.exit_code == 0, result.output
    assert "domain=noc" in result.output
    assert "headlines:" in result.output
    assert "MPKI" not in result.output
    assert "tier score" in result.output
