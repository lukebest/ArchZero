"""OpenAI-compatible /v1/chat/completions shim that forwards to Cursor SDK.

Lets OpenEvolve (and similar) talk to Cursor models without their own API keys.
"""

from __future__ import annotations

import asyncio
import json
import threading
import time
import uuid
from typing import Any

from archzero.config import FactoryConfig
from archzero.llm.client import CursorLLM
from archzero.models import TaskClass


class OpenAIShim:
    """Minimal HTTP server implementing chat completions → CursorLLM.complete."""

    def __init__(self, cfg: FactoryConfig, host: str = "127.0.0.1", port: int = 8765):
        self.cfg = cfg
        self.host = host
        self.port = port
        self._server: Any = None
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}/v1"

    def start(self) -> str:
        """Start background server; return base_url."""
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, fmt: str, *args: Any) -> None:  # noqa: A003
                return

            def do_GET(self) -> None:  # noqa: N802
                if self.path in ("/health", "/v1/models"):
                    body = json.dumps(
                        {
                            "object": "list",
                            "data": [
                                {"id": m, "object": "model"}
                                for m in outer.cfg.pools.cursor_models
                            ],
                        }
                    ).encode()
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                else:
                    self.send_error(404)

            def do_POST(self) -> None:  # noqa: N802
                if self.path not in ("/v1/chat/completions", "/chat/completions"):
                    self.send_error(404)
                    return
                length = int(self.headers.get("Content-Length", "0"))
                raw = self.rfile.read(length)
                try:
                    payload = json.loads(raw.decode("utf-8"))
                except json.JSONDecodeError:
                    self.send_error(400, "invalid json")
                    return
                messages = payload.get("messages") or []
                parts = []
                system = ""
                for m in messages:
                    role = m.get("role", "user")
                    content = m.get("content") or ""
                    if role == "system":
                        system = content
                    else:
                        parts.append(f"[{role}]\n{content}")
                context = "\n\n".join(parts)
                text = outer._complete_sync(system or "You are a helpful coding agent.", context)
                resp = {
                    "id": f"chatcmpl-{uuid.uuid4().hex[:10]}",
                    "object": "chat.completion",
                    "created": int(time.time()),
                    "model": payload.get("model") or outer.cfg.pools.preferred_cursor,
                    "choices": [
                        {
                            "index": 0,
                            "message": {"role": "assistant", "content": text},
                            "finish_reason": "stop",
                        }
                    ],
                    "usage": {
                        "prompt_tokens": 0,
                        "completion_tokens": 0,
                        "total_tokens": 0,
                    },
                }
                body = json.dumps(resp).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        server = ThreadingHTTPServer((self.host, self.port), Handler)
        self._server = server
        t = threading.Thread(target=server.serve_forever, daemon=True)
        t.start()
        self._thread = t
        return self.base_url

    def stop(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server = None

    def _complete_sync(self, persona: str, context: str) -> str:
        async def _go() -> str:
            async with CursorLLM(self.cfg) as llm:
                return await llm.complete(persona, context, TaskClass.EVOLVE)

        try:
            return asyncio.run(_go())
        except RuntimeError:
            # nested loop
            loop = asyncio.new_event_loop()
            try:
                return loop.run_until_complete(_go())
            finally:
                loop.close()
