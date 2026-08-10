"""Cursor SDK wiring — keep ArchZero aligned with cursor-sdk launch/create APIs."""

from __future__ import annotations

import inspect
from unittest.mock import AsyncMock, MagicMock

import pytest

from archzero.config import FactoryConfig
from archzero.llm.client import CursorLLM
from archzero.llm.router import RoutedModel
from archzero.models import TaskClass, UsagePool


def test_launch_bridge_signature_has_no_api_key():
    from cursor_sdk import AsyncClient

    params = inspect.signature(AsyncClient.launch_bridge).parameters
    assert "api_key" not in params
    assert "allow_api_key_env_fallback" in params
    assert hasattr(AsyncClient, "create_agent")


@pytest.mark.asyncio
async def test_ensure_client_does_not_pass_api_key(tmp_path, monkeypatch):
    cfg = FactoryConfig(state_dir=tmp_path / "state", cursor_api_key="cursor_test_key")
    cfg.ensure_dirs()
    llm = CursorLLM(cfg)

    fake_client = MagicMock()
    fake_client.__aenter__ = AsyncMock(return_value=fake_client)
    fake_client.aclose = AsyncMock()

    captured: dict = {}

    async def fake_launch_bridge(**kwargs):
        captured.update(kwargs)
        return fake_client

    monkeypatch.setattr(
        "cursor_sdk.AsyncClient.launch_bridge",
        fake_launch_bridge,
        raising=True,
    )
    client = await llm._ensure_client()
    assert client is fake_client
    assert "api_key" not in captured
    assert captured.get("allow_api_key_env_fallback") is True
    await llm.aclose()


@pytest.mark.asyncio
async def test_run_once_uses_create_agent(tmp_path, monkeypatch):
    cfg = FactoryConfig(state_dir=tmp_path / "state", cursor_api_key="cursor_test_key")
    cfg.ensure_dirs()
    llm = CursorLLM(cfg)

    run = MagicMock()
    run.id = "run-1"
    run.wait = AsyncMock(return_value=MagicMock(status="finished", usage=None, result="ok"))
    run.text = MagicMock(return_value="ok")
    run.usage = None

    agent = MagicMock()
    agent.agent_id = "agent-1"
    agent.send = AsyncMock(return_value=run)
    agent.__aenter__ = AsyncMock(return_value=agent)
    agent.__aexit__ = AsyncMock(return_value=None)

    client = MagicMock()
    client.create_agent = AsyncMock(return_value=agent)
    client.aclose = AsyncMock()

    async def fake_ensure():
        llm._client = client
        return client

    monkeypatch.setattr(llm, "_ensure_client", fake_ensure)
    routed = RoutedModel(
        model_id="cursor-grok-4.5-high-fast",
        pool=UsagePool.CURSOR,
        task=TaskClass.IDEATE,
    )
    text = await llm._run_once("hello", routed, cwd=llm.scratch(), work=False)
    assert text == "ok"
    client.create_agent.assert_awaited()
    kwargs = client.create_agent.await_args.kwargs
    assert kwargs["api_key"] == "cursor_test_key"
    assert "local" in kwargs
    model = kwargs["model"]
    assert model.id == "grok-4.5"
    assert {p.id: p.value for p in model.params} == {
        "effort": "high",
        "fast": "true",
    }
    local = kwargs["local"]
    assert local.sandbox_options is not None
    assert local.sandbox_options.enabled is False
