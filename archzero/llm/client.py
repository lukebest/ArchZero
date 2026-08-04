"""Cursor SDK async client wrappers: complete() and work()."""

from __future__ import annotations

import asyncio
import shutil
import uuid
from pathlib import Path
from typing import Any

from archzero.config import FactoryConfig
from archzero.llm.budget import BudgetGuard
from archzero.llm.catalog import ModelCatalog
from archzero.llm.router import ModelRouter, RoutedModel
from archzero.llm.transcript import TranscriptLog
from archzero.models import TaskClass, UsageEvent, UsagePool
from archzero.store.db import Store


class LLMError(RuntimeError):
    def __init__(self, message: str, *, startup: bool = False, retryable: bool = False):
        super().__init__(message)
        self.startup = startup
        self.retryable = retryable


class CursorLLM:
    """Single choke-point for all LLM traffic via Cursor SDK."""

    def __init__(
        self,
        cfg: FactoryConfig,
        store: Store | None = None,
        campaign_id: str | None = None,
    ) -> None:
        self.cfg = cfg
        self.cfg.ensure_dirs()
        self.store = store or Store(cfg.db_path)
        self.campaign_id = campaign_id
        self.catalog = ModelCatalog(cfg)
        self.budget = BudgetGuard(cfg.budget, self.store, campaign_id=campaign_id)
        self.router = ModelRouter(cfg, self.catalog, self.budget)
        self.transcript = TranscriptLog(cfg.transcripts_dir)
        self._client: Any = None
        self._sem = asyncio.Semaphore(cfg.budget.concurrency)

    async def setup(self) -> None:
        await self.catalog.list_models()
        self.budget.refresh_from_store()

    def scratch(self) -> Path:
        path = self.cfg.scratch_dir / uuid.uuid4().hex[:10]
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _model_selection(self, routed: RoutedModel) -> Any:
        try:
            from cursor_sdk import ModelParameterValue, ModelSelection  # type: ignore
        except ImportError:
            return routed.model_id

        params = []
        if routed.optimize_for:
            params.append(
                ModelParameterValue(id="optimize_for", value=routed.optimize_for)
            )
        if params:
            return ModelSelection(id=routed.model_id, params=params)
        return ModelSelection(id=routed.model_id)

    async def _ensure_client(self) -> Any:
        if self._client is not None:
            return self._client
        from cursor_sdk import AsyncClient  # type: ignore

        api_key = self.cfg.resolved_api_key()
        # launch_bridge returns an async context manager in current SDK
        self._bridge_cm = await AsyncClient.launch_bridge(
            workspace=str(self.cfg.state_dir),
            api_key=api_key,
        )
        self._client = await self._bridge_cm.__aenter__()
        return self._client

    async def aclose(self) -> None:
        if self._client is not None and hasattr(self, "_bridge_cm"):
            await self._bridge_cm.__aexit__(None, None, None)
            self._client = None

    async def __aenter__(self) -> "CursorLLM":
        await self.setup()
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.aclose()

    def _write_persona_rule(self, cwd: Path, persona: str) -> None:
        rules = cwd / ".cursor" / "rules"
        rules.mkdir(parents=True, exist_ok=True)
        (rules / "persona.mdc").write_text(
            "---\ndescription: Active persona for this ArchZero agent run\n"
            "globs:\n  - \"**/*\"\nalwaysApply: true\n---\n\n"
            + persona.strip()
            + "\n",
            encoding="utf-8",
        )

    async def complete(
        self,
        persona: str,
        context: str,
        task: TaskClass,
        *,
        expect_json: bool = False,
    ) -> str:
        """One-shot text completion: persona + context, no durable workspace edits."""
        routed = self.router.pick(task)
        prompt = (
            f"You are operating under the following persona / system instructions:\n\n"
            f"{persona.strip()}\n\n---\n\n{context.strip()}"
        )
        if expect_json:
            prompt += (
                "\n\nRespond with a single valid JSON object only. "
                "No markdown fences."
            )
        return await self._run(prompt, routed, cwd=self.scratch(), work=False)

    async def work(
        self,
        persona: str,
        instruction: str,
        task: TaskClass,
        *,
        cwd: Path,
    ) -> str:
        """Agentic work in a real cwd (write code, run commands)."""
        routed = self.router.pick(task)
        cwd.mkdir(parents=True, exist_ok=True)
        self._write_persona_rule(cwd, persona)
        prompt = (
            f"Persona / standing orders:\n{persona.strip()}\n\n"
            f"---\n\nTask:\n{instruction.strip()}\n\n"
            "Make the necessary file edits in the current workspace. "
            "When done, summarize what you changed and any metrics."
        )
        return await self._run(prompt, routed, cwd=cwd, work=True)

    async def _run(
        self,
        prompt: str,
        routed: RoutedModel,
        *,
        cwd: Path,
        work: bool,
    ) -> str:
        async with self._sem:
            return await self._run_with_retries(prompt, routed, cwd=cwd, work=work)

    async def _run_with_retries(
        self,
        prompt: str,
        routed: RoutedModel,
        *,
        cwd: Path,
        work: bool,
    ) -> str:
        last_err: Exception | None = None
        for attempt in range(self.cfg.budget.max_retries):
            try:
                return await self._run_once(prompt, routed, cwd=cwd, work=work)
            except LLMError as exc:
                last_err = exc
                if not exc.retryable or attempt + 1 >= self.cfg.budget.max_retries:
                    raise
                await asyncio.sleep(2**attempt)
            except Exception as exc:  # noqa: BLE001
                last_err = exc
                await asyncio.sleep(2**attempt)
        raise LLMError(str(last_err), startup=True, retryable=False)

    async def _run_once(
        self,
        prompt: str,
        routed: RoutedModel,
        *,
        cwd: Path,
        work: bool,
    ) -> str:
        api_key = self.cfg.resolved_api_key()
        model = self._model_selection(routed)

        try:
            from cursor_sdk import (  # type: ignore
                CursorAgentError,
                LocalAgentOptions,
            )
        except ImportError as exc:
            raise LLMError(
                "cursor-sdk is not installed. Run: uv sync",
                startup=True,
            ) from exc

        setting_sources = ["project"] if work else None
        agent_id = None
        run_id = None
        status = "unknown"
        total_tokens = 0

        try:
            client = await self._ensure_client()
            create_kwargs: dict[str, Any] = {
                "model": model,
                "api_key": api_key,
                "local": LocalAgentOptions(
                    cwd=str(cwd),
                    setting_sources=setting_sources,
                ),
            }
            async with await client.agents.create(**create_kwargs) as agent:
                agent_id = getattr(agent, "agent_id", None) or getattr(
                    agent, "agentId", None
                )
                run = await agent.send(prompt)
                run_id = getattr(run, "id", None)
                result = await run.wait()
                status = getattr(result, "status", None) or "finished"
                usage = getattr(result, "usage", None) or getattr(run, "usage", None)
                if usage is not None:
                    total_tokens = int(
                        getattr(usage, "total_tokens", None)
                        or getattr(usage, "totalTokens", None)
                        or 0
                    )
                    if total_tokens == 0:
                        inp = int(getattr(usage, "input_tokens", 0) or 0)
                        out = int(getattr(usage, "output_tokens", 0) or 0)
                        total_tokens = inp + out

                if status == "error":
                    self.transcript.log(
                        agent_id=agent_id,
                        run_id=run_id,
                        model=routed.model_id,
                        task=routed.task.value,
                        pool=routed.pool.value,
                        status=status,
                    )
                    raise LLMError(
                        f"run failed: {run_id}",
                        startup=False,
                        retryable=False,
                    )

                text = ""
                if hasattr(run, "text"):
                    maybe = run.text()
                    text = await maybe if asyncio.iscoroutine(maybe) else maybe
                elif hasattr(result, "result"):
                    text = str(result.result or "")
                else:
                    text = str(result)

        except Exception as exc:  # noqa: BLE001
            # CursorAgentError path
            name = type(exc).__name__
            if "CursorAgentError" in name or name == "CursorAgentError":
                retryable = bool(getattr(exc, "is_retryable", False) or getattr(exc, "isRetryable", False))
                self.transcript.log(
                    agent_id=agent_id,
                    run_id=run_id,
                    model=routed.model_id,
                    task=routed.task.value,
                    pool=routed.pool.value,
                    status="startup_error",
                    extra={"error": str(exc)},
                )
                raise LLMError(str(exc), startup=True, retryable=retryable) from exc
            if isinstance(exc, LLMError):
                raise
            raise LLMError(str(exc), startup=True, retryable=True) from exc

        self.transcript.log(
            agent_id=str(agent_id) if agent_id else None,
            run_id=str(run_id) if run_id else None,
            model=routed.model_id,
            task=routed.task.value,
            pool=routed.pool.value,
            status=str(status),
            extra={"tokens": total_tokens, "downgraded": routed.downgraded},
        )
        self.budget.record(routed.pool, total_tokens)
        self.store.save_usage(
            UsageEvent(
                campaign_id=self.campaign_id,
                task=routed.task,
                model_id=routed.model_id,
                pool=routed.pool,
                agent_id=str(agent_id) if agent_id else None,
                run_id=str(run_id) if run_id else None,
                total_tokens=total_tokens,
            )
        )
        # Clean ephemeral scratch when not a durable workdir under candidates
        if not work and cwd.is_dir() and cwd.parent == self.cfg.scratch_dir:
            shutil.rmtree(cwd, ignore_errors=True)
        return text or ""
