"""Tier 2 — Text→Math→Code→Insight analytic model with verify-repair."""

from __future__ import annotations

import json
import re
import runpy
import traceback
from pathlib import Path

from archzero.config import FactoryConfig
from archzero.funnel.taxonomy import attach_result
from archzero.llm.client import CursorLLM
from archzero.models import Candidate, ProblemPackage, TaskClass, Tier, TierResult, Verdict
from archzero.store.artifacts import ArtifactStore

SPEC_PERSONA = """You write analytic performance specifications for architecture mechanisms.
Return markdown SPEC with: Assumptions, Equations, Parameters, Predicted metrics, Falsifiers."""

CODE_PERSONA = """You implement a Python analytic model for an architecture mechanism.
Write a complete model.py that:
- may import from archzero.analytic.core import *
- defines run_model() -> dict with keys predicted_mpki, miss_reduction, ipc_speedup, meets_target
- is deterministic and has no network I/O
Return ONLY the Python source."""

INSIGHT_PERSONA = """You interpret analytic model results vs problem acceptance criteria.
Return JSON: {verdict: pass|fail, score:0-1, summary, magic_gap_notes, clause_refs:[]}"""


def _extract_code(text: str) -> str:
    fence = re.search(r"```(?:python)?\s*([\s\S]*?)```", text)
    if fence:
        return fence.group(1).strip()
    return text.strip()


def _parse_json(text: str) -> dict:
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if fence:
        text = fence.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            try:
                return json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                pass
        return {"verdict": "fail", "summary": text[:500], "score": 0.0}


def _exec_model(path: Path) -> tuple[dict | None, str | None]:
    try:
        ns = runpy.run_path(str(path))
        if "run_model" not in ns:
            return None, "model.py missing run_model()"
        result = ns["run_model"]()
        if not isinstance(result, dict):
            return None, "run_model() did not return dict"
        return result, None
    except Exception:  # noqa: BLE001
        return None, traceback.format_exc()


async def evaluate_tier2(
    cfg: FactoryConfig,
    candidate: Candidate,
    problem: ProblemPackage,
    llm: CursorLLM,
    *,
    max_repairs: int = 3,
) -> Candidate:
    work = Path(candidate.workdir or (cfg.scratch_dir / candidate.id))
    work.mkdir(parents=True, exist_ok=True)
    candidate.workdir = str(work)
    arts = ArtifactStore(cfg.artifacts_dir)

    constraints = "\n".join(f"{c.id}: {c.text}" for c in problem.clauses)
    base = (
        f"PROBLEM:\n{problem.title}\n{constraints}\n\n"
        f"MECHANISM: {candidate.title}\n{candidate.mechanism}\n"
    )

    # Phase 1: spec
    spec_text = await llm.complete(SPEC_PERSONA, base, TaskClass.SPEC_GEN)
    spec_path = work / "SPECIFICATION.md"
    spec_path.write_text(spec_text, encoding="utf-8")
    candidate.spec_path = str(spec_path)
    arts.put_text(spec_text, suffix=".md")

    # Phase 2: code + repair loop
    code_ctx = base + f"\n\nSPECIFICATION:\n{spec_text}\n"
    model_path = work / "model.py"
    metrics: dict | None = None
    err: str | None = None
    for attempt in range(max_repairs):
        if attempt == 0:
            raw = await llm.work(
                CODE_PERSONA,
                code_ctx + "\nWrite model.py implementing run_model().",
                TaskClass.ANALYTIC,
                cwd=work,
            )
            # Prefer file written by agent; else extract from response
            if not model_path.exists():
                model_path.write_text(_extract_code(raw), encoding="utf-8")
        else:
            repair = (
                f"model.py failed:\n{err}\n\nFix model.py so run_model() works. "
                f"You may use archzero.analytic.core helpers."
            )
            await llm.work(CODE_PERSONA, repair, TaskClass.ANALYTIC, cwd=work)
        metrics, err = _exec_model(model_path)
        if metrics is not None:
            break

    candidate.code_path = str(model_path) if model_path.exists() else None
    if model_path.exists():
        arts.put_file(model_path)

    if metrics is None:
        result = TierResult(
            tier=Tier.T2,
            verdict=Verdict.FAIL,
            score=0.0,
            summary=f"analytic model failed after repairs: {err}",
            metrics={"error": err},
            artifacts=[],
            clause_refs=candidate.clause_refs,
        )
        return attach_result(candidate, result, fail_message=result.summary)

    # Phase 3: insight
    insight_ctx = (
        base
        + f"\n\nMODEL METRICS:\n{json.dumps(metrics, indent=2)}\n"
        + f"\nSPEC:\n{spec_text[:8000]}"
    )
    try:
        data = _parse_json(
            await llm.complete(
                INSIGHT_PERSONA, insight_ctx, TaskClass.ANALYTIC, expect_json=True
            )
        )
    except Exception as exc:  # noqa: BLE001
        data = {
            "verdict": "pass" if metrics.get("meets_target") else "fail",
            "summary": f"insight fallback: {exc}",
            "score": float(metrics.get("miss_reduction") or 0),
        }

    # Prefer executable truth if model reports meets_target
    if metrics.get("meets_target") is True and str(data.get("verdict")).lower() != "pass":
        # soft override toward pass if model says ok and score decent
        if float(data.get("score") or 0) >= 0.4:
            data["verdict"] = "pass"

    verdict = Verdict.PASS if str(data.get("verdict", "")).lower() == "pass" else Verdict.FAIL
    # Also fail hard if model says not meeting target
    if metrics.get("meets_target") is False:
        verdict = Verdict.FAIL

    candidate.metrics.update({f"t2_{k}": v for k, v in metrics.items()})
    result = TierResult(
        tier=Tier.T2,
        verdict=verdict,
        score=float(data.get("score") or metrics.get("miss_reduction") or 0.0),
        summary=str(data.get("summary") or ""),
        metrics={"model": metrics, "magic_gap_notes": data.get("magic_gap_notes")},
        artifacts=[],
        clause_refs=list(data.get("clause_refs") or candidate.clause_refs),
    )
    return attach_result(candidate, result, fail_message=result.summary)
