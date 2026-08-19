"""Cursor OpenAI shim used by vendored OpenEvolve — no live LLM."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from urllib.request import Request, urlopen

import pytest

from archzero.config import FactoryConfig
from archzero.llm.shim import OpenAIShim


def test_shim_models_and_completions_forward_to_cursor(tmp_path, monkeypatch):
    cfg = FactoryConfig(state_dir=tmp_path / "state")
    cfg.ensure_dirs()
    shim = OpenAIShim(cfg, port=0)
    monkeypatch.setattr(shim, "_complete_sync", lambda persona, context: "mutated")
    url = shim.start()
    try:
        assert url.startswith("http://127.0.0.1:")
        assert url.endswith("/v1")
        with urlopen(f"{url}/models", timeout=5) as resp:
            models = json.loads(resp.read().decode())
        assert models["object"] == "list"
        assert any(m["id"] for m in models["data"])

        req = Request(
            f"{url}/chat/completions",
            data=json.dumps(
                {
                    "model": "cursor-test",
                    "messages": [
                        {"role": "system", "content": "evolve"},
                        {"role": "user", "content": "improve this"},
                    ],
                }
            ).encode(),
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        with urlopen(req, timeout=5) as resp:
            body = json.loads(resp.read().decode())
        assert body["choices"][0]["message"]["content"] == "mutated"
        assert body["object"] == "chat.completion"
    finally:
        shim.stop()


@pytest.mark.asyncio
async def test_adapter_runs_vendored_cli_against_shim(tmp_path, monkeypatch):
    from archzero.evolve.openevolve_adapter import OpenEvolveBackend
    from archzero.models import Candidate

    oe = tmp_path / "oe"
    oe.mkdir()
    (oe / "openevolve-run.py").write_text("# stub\n", encoding="utf-8")
    cfg = FactoryConfig(state_dir=tmp_path / "state")
    cfg.evolve.openevolve_root = oe
    cfg.ensure_dirs()

    captured: dict = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["env"] = kwargs.get("env") or {}
        out = Path(cmd[cmd.index("--output") + 1])
        best = out / "best" / "best_program.py"
        best.parent.mkdir(parents=True)
        best.write_text("def run_model():\n    return {'goodput': 0.4}\n", encoding="utf-8")
        return subprocess.CompletedProcess(cmd, 0, stdout="ok\n", stderr="")

    monkeypatch.setattr(
        "archzero.evolve.openevolve_adapter.subprocess.run", fake_run
    )
    monkeypatch.setattr(
        "archzero.llm.shim.OpenAIShim._complete_sync",
        lambda self, persona, context: "unused",
    )

    seed = Candidate(problem_id="pp-x", title="rg", mechanism="m", family="noc_rg")
    result = await OpenEvolveBackend().run(cfg, [seed], generations=2)
    assert result["backend"] == "openevolve"
    assert result["returncode"] == 0
    assert "--api-base" in result["openevolve_cmd"]
    assert captured["env"]["OPENAI_API_KEY"] == "cursor-shim"
    assert result["best_program"]
    assert Path(result["best_program"]).is_file()


@pytest.mark.asyncio
async def test_adapter_falls_back_when_vendor_missing(tmp_path, monkeypatch):
    from archzero.evolve.mapelites import MapElitesBackend
    from archzero.evolve.openevolve_adapter import OpenEvolveBackend
    from archzero.models import Candidate

    cfg = FactoryConfig(state_dir=tmp_path / "state")
    cfg.evolve.openevolve_root = tmp_path / "missing-oe"
    cfg.ensure_dirs()

    async def fake_map(self, cfg, seeds, *, generations, campaign_id=None):
        return {"backend": "mapelites", "generations": generations}

    monkeypatch.setattr(MapElitesBackend, "run", fake_map)
    seed = Candidate(problem_id="pp-x", title="t", mechanism="m")
    result = await OpenEvolveBackend().run(cfg, [seed], generations=1)
    assert result["backend"] == "mapelites"
    assert "openevolve missing" in result["note"]
