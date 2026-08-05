"""Tier 5 — RTL via pyCircuit DSL → Verilog → Verilator equivalence.

Fail-closed: missing toolchain → UNAVAILABLE, never proxy PASS.
"""

from __future__ import annotations

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
from archzero.rtl.backend import RtlRequest, get_rtl_backend
from archzero.rtl.codegen import DSL_PERSONA, api_digest, dof_prompt, ensure_baseline_link
from archzero.rtl.equivalence import compare_commit_traces, optional_yosys_lec


async def evaluate_tier5(
    cfg: FactoryConfig,
    candidate: Candidate,
    problem: ProblemPackage,
    llm: CursorLLM,
) -> Candidate:
    work = Path(candidate.workdir or (cfg.scratch_dir / candidate.id))
    work.mkdir(parents=True, exist_ok=True)
    candidate.workdir = str(work)

    ensure_baseline_link(cfg, work)
    digest = api_digest(cfg)
    instruction = (
        f"Mechanism: {candidate.title}\n{candidate.mechanism}\n\n"
        f"Problem: {problem.title}\n"
        + "\n".join(f"{c.id}: {c.text}" for c in problem.clauses)
        + f"\n\n{dof_prompt(problem)}\n\n"
        f"API DIGEST:\n{digest}\n\n"
        "Write design.py, tb_design.py, EQUIV_GATE.md, DECISION.md."
    )
    try:
        await llm.work(DSL_PERSONA, instruction, TaskClass.FINAL_JUDGE, cwd=work)
    except Exception as exc:  # noqa: BLE001
        (work / "EQUIV_GATE.md").write_text(
            "# Equivalence gate (fixed)\n\n"
            "Equivalence is defined at instruction **commit points** only.\n"
            f"Agent error while drafting: {exc}\n",
            encoding="utf-8",
        )
        (work / "DECISION.md").write_text(
            f"# Decision log\n\nCandidate {candidate.id} — agent error, no DSL.\n",
            encoding="utf-8",
        )

    design = work / "design.py"
    tb = work / "tb_design.py"
    entry = tb if tb.is_file() else design

    rtl = get_rtl_backend(cfg)
    tools: dict[str, str] = {}

    if not entry.is_file():
        result = TierResult(
            tier=Tier.T5,
            verdict=Verdict.FAIL,
            score=0.0,
            summary="Tier5: missing design.py / tb_design.py",
            evidence=EvidenceLevel.RTL,
            metrics={"error": "no DSL entry"},
            clause_refs=candidate.clause_refs,
        )
        apply_llm_provenance(result, llm, prompt=instruction)
        return attach_result(candidate, result, fail_message=result.summary)

    if not rtl.available():
        result = TierResult(
            tier=Tier.T5,
            verdict=Verdict.UNAVAILABLE,
            score=0.0,
            summary="Tier5: pyCircuit unavailable — run tools/setup_pycircuit.sh",
            evidence=EvidenceLevel.RTL,
            metrics={"rtl": "unavailable"},
            tool_versions=tools,
            clause_refs=candidate.clause_refs,
        )
        apply_llm_provenance(result, llm)
        candidate.tier_history.append(result)
        candidate.status = "active"
        return candidate

    build = rtl.build(
        RtlRequest(candidate_id=candidate.id, workdir=work, design_entry=entry)
    )
    tools.update(build.tool_versions)

    if build.unavailable:
        result = TierResult(
            tier=Tier.T5,
            verdict=Verdict.UNAVAILABLE,
            score=0.0,
            summary=f"Tier5: RTL build unavailable — {build.log[:300]}",
            evidence=EvidenceLevel.RTL,
            metrics={
                "build_ok": False,
                "unavailable": True,
                "log_tail": build.log[-1500:],
            },
            tool_versions=tools,
            clause_refs=candidate.clause_refs,
        )
        apply_llm_provenance(result, llm)
        candidate.tier_history.append(result)
        candidate.status = "active"
        return candidate

    if not build.ok:
        result = TierResult(
            tier=Tier.T5,
            verdict=Verdict.FAIL,
            score=0.0,
            summary="Tier5: pyCircuit build failed",
            evidence=EvidenceLevel.RTL,
            metrics={
                "build_ok": False,
                "log_tail": build.log[-1500:],
                "compile_stats": build.compile_stats,
            },
            tool_versions=tools,
            clause_refs=candidate.clause_refs,
        )
        apply_llm_provenance(result, llm)
        return attach_result(candidate, result, fail_message=result.summary)

    # Equivalence: commit-point traces (primary)
    equiv = compare_commit_traces(work)
    tools.update(equiv.tool_versions)

    lec = None
    if cfg.rtl.optional_yosys_lec and build.verilog_files:
        gold = work / "baseline_rtl"
        gate = work / build.verilog_files[0]
        # If baseline is a directory, skip LEC
        if gold.is_file():
            lec = optional_yosys_lec(work, gold, gate, enabled=True)
            tools.update(lec.tool_versions)

    if equiv.unavailable and (lec is None or lec.unavailable):
        # Build succeeded but no equivalence evidence → UNAVAILABLE (not PASS)
        verdict = Verdict.UNAVAILABLE
        summary = (
            "Tier5: build ok but equivalence evidence missing "
            "(no commit traces; yosys LEC skipped/unavailable)"
        )
        result = TierResult(
            tier=Tier.T5,
            verdict=verdict,
            score=0.5,
            summary=summary,
            evidence=EvidenceLevel.RTL,
            metrics={
                "build_ok": True,
                "verilog": build.verilog_files,
                "compile_stats": build.compile_stats,
                "equiv": equiv.__dict__,
                "lec": lec.__dict__ if lec else None,
            },
            tool_versions=tools,
            clause_refs=candidate.clause_refs,
        )
        apply_llm_provenance(result, llm)
        candidate.tier_history.append(result)
        candidate.status = "active"
        candidate.metrics["t5_rtl"] = result.metrics
        return candidate

    ok = equiv.ok if not equiv.unavailable else bool(lec and lec.ok)
    if lec is not None and not lec.unavailable:
        ok = ok and lec.ok

    verdict = Verdict.PASS if ok else Verdict.FAIL
    summary = f"Tier5: build_ok equiv={equiv.summary}"
    if lec and not lec.unavailable:
        summary += f" lec={lec.summary}"

    decision_path = work / "DECISION.md"
    if decision_path.exists():
        with decision_path.open("a", encoding="utf-8") as f:
            f.write(f"\n\n## Tier5 result\n\nverdict={verdict.value}\n{summary}\n")

    metrics = {
        "build_ok": True,
        "verilog": build.verilog_files,
        "compile_stats": build.compile_stats,
        "manifest": build.manifest,
        "equiv": {
            "ok": equiv.ok,
            "unavailable": equiv.unavailable,
            "method": equiv.method,
            "summary": equiv.summary,
            "details": equiv.details,
        },
        "lec": (
            {
                "ok": lec.ok,
                "unavailable": lec.unavailable,
                "summary": lec.summary,
            }
            if lec
            else None
        ),
    }
    candidate.metrics["t5_rtl"] = metrics
    result = TierResult(
        tier=Tier.T5,
        verdict=verdict,
        score=1.0 if verdict == Verdict.PASS else 0.0,
        summary=summary,
        evidence=EvidenceLevel.RTL,
        metrics=metrics,
        tool_versions=tools,
        clause_refs=candidate.clause_refs,
    )
    apply_llm_provenance(result, llm, prompt=instruction)
    if verdict == Verdict.UNAVAILABLE:
        candidate.tier_history.append(result)
        candidate.status = "active"
        return candidate
    return attach_result(candidate, result, fail_message=summary)
