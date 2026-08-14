"""Tier 2 — Text→Math→Code→Insight analytic model with verify-repair + ensemble."""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field
from pathlib import Path

from archzero.analytic.sandbox import run_model_sandboxed
from archzero.config import FactoryConfig
from archzero.funnel.provenance import apply_llm_provenance
from archzero.funnel.taxonomy import attach_result
from archzero.funnel.verifiers import (
    VerifierResult,
    run_functional_verifier,
    run_spec_verifier,
)
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
from archzero.spec.acc_parse import AcceptanceThresholds, parse_acceptance_thresholds
from archzero.store.artifacts import ArtifactStore

SPEC_PERSONA = """You write analytic performance specifications for architecture mechanisms.
Return markdown SPEC with: Assumptions, Equations, Parameters, Predicted metrics, Falsifiers."""

CODE_PERSONA_CACHE = """You implement a Python analytic model for a cache / memory-hierarchy mechanism.
Write a complete model.py that:
- may import from archzero.analytic.core import *
- defines run_model() -> dict with keys predicted_mpki, miss_reduction, ipc_speedup, meets_target
- is deterministic and has no network I/O
Return ONLY the Python source."""

CODE_PERSONA_NOC = """You implement a Python analytic model for an on-chip interconnect / collective mechanism.
Write a complete model.py that:
- SHOULD import from archzero.analytic.domains import noc_model
- defines run_model() -> dict by calling noc_model("<family>")
  family is one of: packet_switched, request_grant, push_on_pull, presched
- returned keys MUST include completion_latency, p95_latency, p99_latency, goodput, link_utilization
- do NOT invent predicted_mpki, miss_reduction, or ipc_speedup — those are cache metrics
- meets_target must be None unless the spec stated a numeric gate
- is deterministic and has no network I/O
Return ONLY the Python source."""

CODE_PERSONA_DATAFLOW = """You implement a Python analytic model for a spatial-accelerator / dataflow mechanism.
Write a complete model.py that:
- SHOULD import from archzero.analytic.domains import dataflow_model
- defines run_model() -> dict by calling dataflow_model("<family>")
  family is one of: output_stationary, weight_stationary, input_stationary, row_stationary
- returned keys MUST include pe_utilization, reuse_factor, sram_traffic
- do NOT invent predicted_mpki, miss_reduction, or ipc_speedup — those are cache metrics
- meets_target must be None unless the spec stated a numeric gate
- is deterministic and has no network I/O
Return ONLY the Python source."""

CODE_PERSONA_WAFER = """You implement a Python analytic model for a wafer-scale / multi-die fabric mechanism.
Write a complete model.py that:
- SHOULD import from archzero.analytic.domains import wafer_model
- defines run_model() -> dict by calling wafer_model("<family>")
  family is one of: mesh_xy, spare_bypass, compiled_partition
- returned keys MUST include fabric_hop_latency, die_to_die_bw
- do NOT invent predicted_mpki, miss_reduction, or ipc_speedup — those are cache metrics
- do NOT invent yield_redundancy or thermal_density — this backend does not measure them
- meets_target must be None unless the spec stated a numeric gate
- is deterministic and has no network I/O
Return ONLY the Python source."""

CODE_PERSONA_GENERIC = """You implement a Python analytic model for an architecture mechanism.
Write a complete model.py that:
- may import from archzero.analytic.core import * or archzero.analytic.domains
- defines run_model() -> dict whose keys match the problem's declared metrics
- do not invent cache MPKI numbers unless the spec is about a cache
- is deterministic and has no network I/O
Return ONLY the Python source."""

# Back-compat alias: cache tests and FakeLLM paths still import CODE_PERSONA.
CODE_PERSONA = CODE_PERSONA_CACHE

INSIGHT_PERSONA = """You interpret analytic model results vs problem acceptance criteria.
Return JSON: {verdict: pass|fail, score:0-1, summary, magic_gap_notes, clause_refs:[]}
If the thresholds mark report_only, do not invent a numeric pass/fail; summarise the measured numbers."""

_CACHE_METRIC_KEYS = ("predicted_mpki", "miss_reduction", "ipc_speedup")
_DOMAIN_HEADLINE = {
    "noc": ("p99_latency", "goodput", "completion_latency"),
    "dataflow": ("pe_utilization", "reuse_factor", "sram_traffic"),
    "wafer": ("die_to_die_bw", "fabric_hop_latency"),
    "cache": ("miss_reduction", "predicted_mpki", "ipc_speedup"),
}


def code_persona_for(domain: str) -> str:
    if domain == "noc":
        return CODE_PERSONA_NOC
    if domain == "dataflow":
        return CODE_PERSONA_DATAFLOW
    if domain == "wafer":
        return CODE_PERSONA_WAFER
    if domain == "cache":
        return CODE_PERSONA_CACHE
    return CODE_PERSONA_GENERIC


def _headline_score(metrics: dict, th: AcceptanceThresholds) -> float:
    for key in _DOMAIN_HEADLINE.get(th.domain, ("miss_reduction",)):
        val = metrics.get(key)
        if val is not None:
            try:
                return float(val)
            except (TypeError, ValueError):
                continue
    return float(metrics.get("miss_reduction") or 0.0)


def _sanitize_domain_metrics(
    metrics: dict, th: AcceptanceThresholds, *, strict: bool
) -> dict:
    """Drop leaked cache keys on off-domain specs when strict_acc is on."""
    out = dict(metrics)
    if not strict or th.domain in ("cache", "generic"):
        return out
    leaked = [k for k in _CACHE_METRIC_KEYS if k in out]
    if leaked:
        out["_stripped_cache_keys"] = leaked
        for k in leaked:
            out.pop(k, None)
    if th.report_only:
        out["meets_target"] = None
    return out


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


@dataclass
class Tier2RunResult:
    verdict: Verdict
    score: float
    summary: str
    metrics: dict
    insight: dict
    verifiers: list[VerifierResult] = field(default_factory=list)
    disagreement: bool = False
    thresholds: dict = field(default_factory=dict)


def _threshold_gate(metrics: dict, th: AcceptanceThresholds) -> tuple[bool, str]:
    """Numeric ACC gate independent of model self-report.

    Only spec-declared performance gates are applied. A NoC package that never
    mentioned MPKI must not fail ``>=15% miss_reduction``.
    """
    if not th.has_spec_performance_gate:
        return True, "report-only: no spec-declared performance gate"
    reduction = float(metrics.get("miss_reduction") or 0.0)
    if th.from_spec("min_miss_reduction") and reduction < th.min_miss_reduction:
        return False, (
            f"miss_reduction {reduction:.3f} < ACC min {th.min_miss_reduction:.3f}"
        )
    # BW: accept bw_delta_frac, extra_bw, or bw_overhead aliases from models
    bw = metrics.get("bw_delta_frac")
    if bw is None:
        bw = metrics.get("extra_bw")
    if bw is None:
        bw = metrics.get("bw_overhead")
    if th.from_spec("max_bw_delta_frac") and bw is not None and float(bw) > th.max_bw_delta_frac:
        return False, (
            f"bw_delta_frac {float(bw):.3f} > ACC max {th.max_bw_delta_frac:.3f}"
        )
    if th.from_spec("area_budget_mm2") and th.area_budget_mm2 is not None:
        area = metrics.get("area_mm2")
        if area is None:
            area = metrics.get("area")
        if area is not None and float(area) > float(th.area_budget_mm2):
            return False, (
                f"area_mm2 {float(area):.3f} > ACC budget {th.area_budget_mm2:.3f}"
            )
    return True, "acc numeric ok"


async def _run_single_tier2_attempt(
    cfg: FactoryConfig,
    candidate: Candidate,
    problem: ProblemPackage,
    llm: CursorLLM,
    *,
    work: Path,
    arts: ArtifactStore,
    constraints: str,
    base: str,
    th: AcceptanceThresholds,
    attempt_idx: int,
    max_repairs: int,
) -> Tier2RunResult:
    run_dir = work if attempt_idx == 0 else work / f"ensemble_{attempt_idx}"
    run_dir.mkdir(parents=True, exist_ok=True)

    # Phase 1: spec
    spec_text = await llm.complete(SPEC_PERSONA, base, TaskClass.SPEC_GEN)
    spec_path = run_dir / "SPECIFICATION.md"
    spec_path.write_text(spec_text, encoding="utf-8")
    if attempt_idx == 0:
        candidate.spec_path = str(spec_path)
        arts.put_text(spec_text, suffix=".md")

    # Phase 2: code + repair loop
    persona = code_persona_for(th.domain)
    code_ctx = base + f"\n\nSPECIFICATION:\n{spec_text}\n"
    model_path = run_dir / "model.py"
    metrics: dict | None = None
    err: str | None = None
    for attempt in range(max_repairs):
        if attempt == 0:
            raw = await llm.work(
                persona,
                code_ctx + "\nWrite model.py implementing run_model().",
                TaskClass.ANALYTIC,
                cwd=run_dir,
            )
            if not model_path.exists():
                model_path.write_text(_extract_code(raw), encoding="utf-8")
        else:
            repair = (
                f"model.py failed:\n{err}\n\nFix model.py so run_model() works. "
                f"Use the domain helpers named in the system persona; "
                f"do not invent cache MPKI numbers for a {th.domain} problem."
            )
            await llm.work(persona, repair, TaskClass.ANALYTIC, cwd=run_dir)
        metrics, err = run_model_sandboxed(
            model_path,
            timeout_s=cfg.funnel.model_exec_timeout_s,
            mem_mb=cfg.funnel.model_exec_mem_mb,
        )
        if metrics is not None:
            break

    if attempt_idx == 0:
        candidate.code_path = str(model_path) if model_path.exists() else None
        if model_path.exists():
            arts.put_file(model_path)

    if metrics is None:
        return Tier2RunResult(
            verdict=Verdict.FAIL,
            score=0.0,
            summary=f"analytic model failed after repairs: {err}",
            metrics={"error": err},
            insight={},
            thresholds=th.as_dict(),
        )

    metrics = _sanitize_domain_metrics(
        metrics, th, strict=cfg.funnel.strict_acc
    )
    needed = _DOMAIN_HEADLINE.get(th.domain)
    if (
        cfg.funnel.strict_acc
        and needed
        and th.domain not in ("cache", "generic")
        and not any(metrics.get(k) is not None for k in needed)
    ):
        return Tier2RunResult(
            verdict=Verdict.FAIL,
            score=0.0,
            summary=(
                f"analytic model emitted no {th.domain} metrics "
                f"({', '.join(needed)}); "
                f"stripped cache keys={metrics.get('_stripped_cache_keys')}"
            ),
            metrics={"model": metrics},
            insight={},
            thresholds=th.as_dict(),
        )

    # Phase 2b: verifiers
    verifiers: list[VerifierResult] = []
    if cfg.funnel.use_verifiers:
        verifiers.append(
            await run_spec_verifier(
                cfg,
                llm,
                spec_text=spec_text,
                problem_title=problem.title,
                constraints=constraints,
            )
        )
        verifiers.append(
            await run_functional_verifier(
                cfg, llm, spec_text=spec_text, model_path=model_path
            )
        )
        if any(not v.ok for v in verifiers):
            failed = [v.name for v in verifiers if not v.ok]
            return Tier2RunResult(
                verdict=Verdict.FAIL,
                score=_headline_score(metrics, th),
                summary=f"verifier FAIL: {', '.join(failed)}",
                metrics={"model": metrics, "verifiers": [v.name for v in verifiers]},
                insight={},
                verifiers=verifiers,
                thresholds=th.as_dict(),
            )

    # Phase 2c: ACC numeric gate
    acc_ok, acc_note = _threshold_gate(metrics, th)
    if not acc_ok:
        return Tier2RunResult(
            verdict=Verdict.FAIL,
            score=_headline_score(metrics, th),
            summary=acc_note,
            metrics={"model": metrics},
            insight={},
            verifiers=verifiers,
            thresholds=th.as_dict(),
        )

    # Phase 3: insight
    insight_ctx = (
        base
        + f"\n\nACCEPTANCE THRESHOLDS:\n{json.dumps(th.as_dict(), indent=2)}\n"
        + f"\nMODEL METRICS:\n{json.dumps(metrics, indent=2)}\n"
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
        data = {
            "verdict": "fail",
            "summary": f"insight error (fail-closed): {exc}",
            "score": _headline_score(metrics, th),
        }

    insight_pass = str(data.get("verdict", "")).lower() == "pass"
    model_ok = metrics.get("meets_target") is True
    if insight_pass != model_ok:
        disagreement = True
        data["disagreement"] = {
            "insight_pass": insight_pass,
            "meets_target": metrics.get("meets_target"),
        }

    if metrics.get("meets_target") is False:
        verdict = Verdict.FAIL
    elif insight_pass and model_ok:
        verdict = Verdict.PASS
    elif insight_pass and metrics.get("meets_target") is None:
        verdict = Verdict.PASS
        data["summary"] = str(data.get("summary") or "") + " [meets_target omitted]"
    else:
        verdict = Verdict.FAIL
        if disagreement:
            data["summary"] = (
                str(data.get("summary") or "")
                + " [disagreement: insight vs meets_target — fail]"
            )

    return Tier2RunResult(
        verdict=verdict,
        score=float(data.get("score") or _headline_score(metrics, th)),
        summary=str(data.get("summary") or ""),
        metrics={"model": metrics},
        insight=data,
        verifiers=verifiers,
        disagreement=disagreement,
        thresholds=th.as_dict(),
    )


def _majority_verdict(runs: list[Tier2RunResult]) -> Verdict:
    if not runs:
        return Verdict.FAIL
    passes = sum(1 for r in runs if r.verdict == Verdict.PASS)
    need = math.ceil(len(runs) / 2)
    return Verdict.PASS if passes >= need else Verdict.FAIL


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

    th = parse_acceptance_thresholds(problem)
    if cfg.funnel.strict_acc and not th.gradable:
        # The candidate is not bad — the spec cannot be graded. Same stance as
        # Tier3/Tier5 when a backend is missing: record UNAVAILABLE, do not
        # invent a numeric verdict, and do not mark the candidate failed.
        result = TierResult(
            tier=Tier.T2,
            verdict=Verdict.UNAVAILABLE,
            score=0.0,
            summary=f"Tier2 拒判（strict_acc）：{th.ungradable_reason()}",
            metrics={"thresholds": th.as_dict(), "acc_gradable": False},
            artifacts=[],
            evidence=EvidenceLevel.ANALYTIC,
            clause_refs=candidate.clause_refs,
        )
        candidate.tier_history.append(result)
        candidate.status = "active"
        return candidate

    constraints = "\n".join(f"{c.id}: {c.text}" for c in problem.clauses)
    base = (
        f"PROBLEM:\n{problem.title}\n{constraints}\n\n"
        f"MECHANISM: {candidate.title}\n{candidate.mechanism}\n"
    )

    n = max(1, int(cfg.funnel.ensemble_n or 1))
    runs: list[Tier2RunResult] = []
    for i in range(n):
        runs.append(
            await _run_single_tier2_attempt(
                cfg,
                candidate,
                problem,
                llm,
                work=work,
                arts=arts,
                constraints=constraints,
                base=base,
                th=th,
                attempt_idx=i,
                max_repairs=max_repairs,
            )
        )

    verdict = _majority_verdict(runs)
    primary = runs[0]
    model_metrics = primary.metrics.get("model") or {}
    if isinstance(model_metrics, dict):
        candidate.metrics.update({f"t2_{k}": v for k, v in model_metrics.items()})
    candidate.metrics["t2_ensemble_n"] = n
    candidate.metrics["t2_ensemble_passes"] = sum(
        1 for r in runs if r.verdict == Verdict.PASS
    )

    if n == 1 and primary.verdict == Verdict.FAIL and "analytic model failed" in primary.summary:
        result = TierResult(
            tier=Tier.T2,
            verdict=Verdict.FAIL,
            score=0.0,
            summary=primary.summary,
            metrics={"error": primary.metrics.get("error"), "thresholds": th.as_dict()},
            artifacts=[],
            evidence=EvidenceLevel.ANALYTIC,
            clause_refs=candidate.clause_refs,
        )
        apply_llm_provenance(result, llm, prompt=base)
        return attach_result(candidate, result, fail_message=result.summary)

    summary = primary.summary
    if n > 1:
        summary = (
            f"ensemble {candidate.metrics['t2_ensemble_passes']}/{n} pass → "
            f"{verdict.value}; {primary.summary}"
        )

    result = TierResult(
        tier=Tier.T2,
        verdict=verdict,
        score=primary.score,
        summary=summary,
        metrics={
            "model": model_metrics,
            "magic_gap_notes": primary.insight.get("magic_gap_notes"),
            "disagreement": primary.disagreement,
            "ensemble": {
                "n": n,
                "passes": candidate.metrics["t2_ensemble_passes"],
                "verdicts": [r.verdict.value for r in runs],
            },
            "verifiers": [
                {"name": v.name, "ok": v.ok, "critique": v.critique[:200]}
                for v in primary.verifiers
            ],
            "thresholds": th.as_dict(),
        },
        artifacts=[],
        evidence=EvidenceLevel.ANALYTIC,
        clause_refs=list(
            primary.insight.get("clause_refs") or candidate.clause_refs
        ),
    )
    apply_llm_provenance(result, llm, prompt=base)
    return attach_result(candidate, result, fail_message=result.summary)
