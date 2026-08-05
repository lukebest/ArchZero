"""Tier 2 — Text→Math→Code→Insight analytic model with verify-repair."""

from __future__ import annotations

import json
import re
from pathlib import Path

from archzero.analytic.sandbox import run_model_sandboxed
from archzero.config import FactoryConfig
from archzero.funnel.provenance import apply_llm_provenance
from archzero.funnel.taxonomy import attach_result
from archzero.llm.client import CursorLLM
from archzero.models import (
    Candidate,
    EvidenceLevel,
    ProblemPackage,
    TaskClass,
    Tier,
    TierResult,
    Verdict,
)
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
            if not model_path.exists():
                model_path.write_text(_extract_code(raw), encoding="utf-8")
        else:
            repair = (
                f"model.py failed:\n{err}\n\nFix model.py so run_model() works. "
                f"You may use archzero.analytic.core helpers."
            )
            await llm.work(CODE_PERSONA, repair, TaskClass.ANALYTIC, cwd=work)
        metrics, err = run_model_sandboxed(
            model_path,
            timeout_s=cfg.funnel.model_exec_timeout_s,
            mem_mb=cfg.funnel.model_exec_mem_mb,
        )
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
            evidence=EvidenceLevel.ANALYTIC,
            clause_refs=candidate.clause_refs,
        )
        apply_llm_provenance(result, llm, prompt=base)
        return attach_result(candidate, result, fail_message=result.summary)

    # Phase 3: insight — no soft override from meets_target self-report
    insight_ctx = (
        base
        + f"\n\nMODEL METRICS:\n{json.dumps(metrics, indent=2)}\n"
        + f"\nSPEC:\n{spec_text[:8000]}"
    )
    disagreement = False
    try:
        data = _parse_json(
            await llm.complete(
                INSIGHT_PERSONA, insight_ctx, TaskClass.ANALYTIC, expect_json=True
            )
        )
    except Exception as exc:  # noqa: BLE001
        # Fail closed on insight errors — do not trust meets_target alone
        data = {
            "verdict": "fail",
            "summary": f"insight error (fail-closed): {exc}",
            "score": float(metrics.get("miss_reduction") or 0),
        }

    insight_pass = str(data.get("verdict", "")).lower() == "pass"
    model_ok = metrics.get("meets_target") is True
    if insight_pass != model_ok:
        disagreement = True
        data["disagreement"] = {
            "insight_pass": insight_pass,
            "meets_target": metrics.get("meets_target"),
        }

    # Majority / agreement: both must agree for PASS; model False always fails
    if metrics.get("meets_target") is False:
        verdict = Verdict.FAIL
    elif insight_pass and model_ok:
        verdict = Verdict.PASS
    elif insight_pass and metrics.get("meets_target") is None:
        # Model omitted meets_target — trust insight but annotate
        verdict = Verdict.PASS
        data["summary"] = str(data.get("summary") or "") + " [meets_target omitted]"
    else:
        verdict = Verdict.FAIL
        if disagreement:
            data["summary"] = (
                str(data.get("summary") or "")
                + " [disagreement: insight vs meets_target — fail]"
            )

    candidate.metrics.update({f"t2_{k}": v for k, v in metrics.items()})
    result = TierResult(
        tier=Tier.T2,
        verdict=verdict,
        score=float(data.get("score") or metrics.get("miss_reduction") or 0.0),
        summary=str(data.get("summary") or ""),
        metrics={
            "model": metrics,
            "magic_gap_notes": data.get("magic_gap_notes"),
            "disagreement": disagreement,
        },
        artifacts=[],
        evidence=EvidenceLevel.ANALYTIC,
        clause_refs=list(data.get("clause_refs") or candidate.clause_refs),
    )
    apply_llm_provenance(result, llm, prompt=insight_ctx)
    return attach_result(candidate, result, fail_message=result.summary)
