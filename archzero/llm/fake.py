"""Deterministic FakeLLM for offline tests and e2e demos."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from archzero.llm.router import RoutedModel
from archzero.models import TaskClass, UsagePool


@dataclass
class FakeLLM:
    """Drop-in stand-in for CursorLLM in unit tests / offline e2e."""

    responses: dict[str, str] = field(default_factory=dict)
    sequence: list[str] = field(default_factory=list)
    calls: list[dict[str, Any]] = field(default_factory=list)
    last_routed: RoutedModel | None = None
    model_id: str = "fake-model"
    pool: UsagePool = UsagePool.CURSOR

    def _next(self, task: TaskClass, default: str = "{}") -> str:
        # Do not consume `sequence` here — reserved for expect_json completions
        return self.responses.get(task.value, default)

    async def complete(
        self,
        persona: str,
        context: str,
        task: TaskClass,
        *,
        expect_json: bool = False,
    ) -> str:
        self.last_routed = RoutedModel(
            model_id=self.model_id, pool=self.pool, task=task
        )
        if expect_json and f"{task.value}_json" in self.responses:
            text = self._next_named(f"{task.value}_json")
        elif expect_json and self.sequence:
            text = self.sequence.pop(0)
        elif expect_json:
            text = self.responses.get(
                task.value + "_json",
                self.responses.get(
                    task.value,
                    '{"verdict":"pass","score":0.5,"summary":"fake"}',
                ),
            )
            # If stored analytic response is Python, fall back to pass JSON
            if expect_json and ("def run_model" in text or text.strip().startswith("```")):
                text = '{"verdict":"pass","score":0.8,"summary":"fake insight","clause_refs":[]}'
        else:
            text = self._next(
                task, default='{"verdict":"pass","score":0.5,"summary":"fake"}'
            )
        self.calls.append({"op": "complete", "task": task.value, "expect_json": expect_json})
        return text

    def _next_named(self, key: str) -> str:
        if self.sequence:
            return self.sequence.pop(0)
        return self.responses.get(key, "{}")

    async def work(
        self,
        persona: str,
        instruction: str,
        task: TaskClass,
        *,
        cwd: Path,
    ) -> str:
        self.last_routed = RoutedModel(
            model_id=self.model_id, pool=self.pool, task=task
        )
        cwd.mkdir(parents=True, exist_ok=True)
        text = self._next(task, default="")
        # Heuristic: if analytic code, write model.py
        if "model.py" in instruction.lower() or task == TaskClass.ANALYTIC:
            if "def run_model" in text or "```" in text:
                from archzero.funnel.tier2 import _extract_code

                code = _extract_code(text) if "```" in text else text
                if "def run_model" in code:
                    (cwd / "model.py").write_text(code, encoding="utf-8")
        if "sim_knobs" in instruction.lower() and not (cwd / "sim_knobs.json").exists():
            persona_l = persona.lower()
            instr_l = instruction.lower()
            if (
                "do not invent miss_reduction" in persona_l
                or "off-cache" in persona_l
            ):
                if "dataflow" in instr_l:
                    knobs_blob = '{"family": "output_stationary", "domain": "dataflow"}'
                elif "wafer" in instr_l:
                    knobs_blob = '{"family": "mesh_xy", "domain": "wafer"}'
                else:
                    knobs_blob = '{"family": "request_grant", "domain": "noc"}'
                (cwd / "sim_knobs.json").write_text(knobs_blob, encoding="utf-8")
            else:
                (cwd / "sim_knobs.json").write_text(
                    '{"family": "prefetch", "domain": "cache"}',
                    encoding="utf-8",
                )
        if "design.py" in instruction.lower() and not (cwd / "design.py").exists():
            (cwd / "design.py").write_text(
                "# fake design\n", encoding="utf-8"
            )
            (cwd / "EQUIV_GATE.md").write_text(
                "# Equivalence gate\nCommit-point only.\n", encoding="utf-8"
            )
            (cwd / "DECISION.md").write_text("# Decision\n", encoding="utf-8")
        self.calls.append({"op": "work", "task": task.value, "cwd": str(cwd)})
        return text or "ok"
