"""Tier 4 — fuller simulation suite + final-judge adjudication."""

from __future__ import annotations

import json
import re
from pathlib import Path

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
from archzero.sim.backend import SimRequest
from archzero.sim.headlines import ranking_score
from archzero.sim.mechanism_model import domain_magic_gap
from archzero.sim.metrics import SimMetrics
from archzero.sim.registry import resolve_backend_for_domain
from archzero.spec.acc_parse import parse_acceptance_thresholds

_SOFT_FALLBACK_BACKENDS = frozenset({"stub", "directed", "noc", "dataflow", "wafer"})

JUDGE_PERSONA = """你是体系结构漏斗的仿真终审。
根据验收条款与仿真指标裁定 pass/fail。
只返回 JSON：{verdict: pass|fail, score:0-1, summary, clause_refs:[]}
summary 必须原生简体中文；verdict 保持英文枚举。"""


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


def _tier4_score(
    sim_metrics: dict,
    data: dict | None,
    *,
    family: str | None,
    domain: str,
) -> float | None:
    if data is not None and data.get("score") is not None:
        try:
            return float(data["score"])
        except (TypeError, ValueError):
            pass
    return ranking_score(sim_metrics, family=family, domain=domain)


async def evaluate_tier4(
    cfg: FactoryConfig,
    candidate: Candidate,
    problem: ProblemPackage,
    llm: CursorLLM,
) -> Candidate:
    work = Path(candidate.workdir or (cfg.scratch_dir / candidate.id))
    work.mkdir(parents=True, exist_ok=True)
    candidate.workdir = str(work)
    th = parse_acceptance_thresholds(problem)

    backend, backend_name, route_reason = resolve_backend_for_domain(cfg, th.domain)
    if route_reason:
        candidate.metrics["t4_backend_route"] = route_reason
    sim = backend.run(
        SimRequest(
            candidate_id=candidate.id,
            workdir=work,
            patch_hint=candidate.mechanism[:500],
            suite="full",
            meta={
                "title": candidate.title,
                "mechanism": candidate.mechanism,
                "family": candidate.family,
                "min_miss_reduction": th.min_miss_reduction,
                "max_bw_delta_frac": th.max_bw_delta_frac,
                "area_budget_mm2": th.area_budget_mm2,
                "domain": th.domain,
            },
        )
    )
    candidate.metrics.update({f"t4_{k}": v for k, v in sim.metrics.items()})
    gap, gap_metric = domain_magic_gap(
        candidate.metrics, sim.metrics, th.domain
    )
    if gap is not None:
        candidate.metrics["t4_magic_gap"] = gap
        candidate.metrics["t4_magic_gap_metric"] = gap_metric

    evidence = EvidenceLevel.STUB
    ev = str(sim.metrics.get("evidence") or "")
    if not sim.unavailable and backend_name not in {"stub"}:
        evidence = EvidenceLevel.SIM
    if ev == "analytic":
        evidence = EvidenceLevel.ANALYTIC
    if ev == "stub":
        evidence = EvidenceLevel.STUB
    if ev == "directed":
        evidence = EvidenceLevel.SIM

    if sim.unavailable and cfg.funnel.strict_evidence and backend_name not in _SOFT_FALLBACK_BACKENDS:
        result = TierResult(
            tier=Tier.T4,
            verdict=Verdict.UNAVAILABLE,
            score=_tier4_score(sim.metrics, None, family=candidate.family, domain=th.domain),
            summary=f"{sim.backend}: UNAVAILABLE under strict_evidence",
            metrics={
                **sim.metrics,
                "thresholds": th.as_dict(),
                "magic_gap": gap,
                "magic_gap_metric": gap_metric,
            },
            evidence=EvidenceLevel.STUB,
            clause_refs=candidate.clause_refs,
        )
        apply_llm_provenance(result, llm)
        candidate.tier_history.append(result)
        candidate.status = "active"
        return candidate

    acc = "\n".join(
        f"{c.id}: {c.text}" for c in problem.clauses if c.id.startswith("ACC")
    )
    gap_line = ""
    if gap is not None:
        gap_line = f"\nMAGIC GAP (T2 vs this suite, metric={gap_metric}): {gap}\n"
    ctx = (
        f"PROBLEM: {problem.title}\nACCEPTANCE:\n{acc}\n\n"
        f"PARSED THRESHOLDS:\n{json.dumps(th.as_dict(), indent=2)}\n\n"
        f"CANDIDATE: {candidate.title}\n"
        f"SIM METRICS:\n{json.dumps(sim.metrics, indent=2)}\n"
        f"{gap_line}"
        f"backend={sim.backend} unavailable_flag={sim.unavailable} evidence={evidence.value}"
    )
    try:
        data = _parse_json(
            await llm.complete(JUDGE_PERSONA, ctx, TaskClass.FINAL_JUDGE, expect_json=True)
        )
    except Exception as exc:  # noqa: BLE001
        # Fail closed on judge error when not stub; stub/directed uses ACC heuristic
        known = set(SimMetrics.model_fields)
        metrics_obj = SimMetrics.model_validate(
            {k: v for k, v in sim.metrics.items() if k in known}
        )
        outcome = metrics_obj.apply_gates(th.spec_gates())
        scored = ranking_score(
            sim.metrics, family=candidate.family, domain=th.domain
        )
        if backend_name in _SOFT_FALLBACK_BACKENDS:
            ok = sim.ok and outcome.ok
            data = {
                "verdict": "pass" if ok else "fail",
                "summary": (
                    f"judge fallback ({backend_name}): {exc}"
                    + ("" if outcome.adjudicated else " [report-only]")
                ),
                "score": scored,
            }
        else:
            data = {
                "verdict": "fail",
                "summary": f"judge error (fail-closed): {exc}",
                "score": scored,
            }

    gap_fail = (
        gap is not None
        and th.from_spec("max_magic_gap")
        and gap > th.max_magic_gap
    )
    verdict = Verdict.PASS if str(data.get("verdict")).lower() == "pass" else Verdict.FAIL
    summary = str(data.get("summary") or "")
    if gap_fail:
        verdict = Verdict.FAIL
        summary = (
            f"magic_gap {gap:.3f} ({gap_metric}) > ACC max {th.max_magic_gap:.3f}"
            + (f"; {summary}" if summary else "")
        )
    result = TierResult(
        tier=Tier.T4,
        verdict=verdict,
        score=_tier4_score(sim.metrics, data, family=candidate.family, domain=th.domain),
        summary=summary,
        metrics={
            **sim.metrics,
            "magic_gap": gap,
            "magic_gap_metric": gap_metric,
            "thresholds": th.as_dict(),
        },
        evidence=evidence,
        clause_refs=list(data.get("clause_refs") or candidate.clause_refs),
    )
    apply_llm_provenance(result, llm, prompt=ctx)
    return attach_result(candidate, result, fail_message=result.summary)
