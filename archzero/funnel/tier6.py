"""Tier 6 — physical signoff (RESERVED).

Always returns UNAVAILABLE until SignBackend is implemented.
"""

from __future__ import annotations

from pathlib import Path

from archzero.config import FactoryConfig
from archzero.llm.client import CursorLLM
from archzero.models import (
    Candidate,
    EvidenceLevel,
    ProblemPackage,
    Tier,
    TierResult,
    Verdict,
)
from archzero.sign.backend import SignRequest, get_sign_backend


async def evaluate_tier6(
    cfg: FactoryConfig,
    candidate: Candidate,
    problem: ProblemPackage,
    llm: CursorLLM,
) -> Candidate:
    work = Path(candidate.workdir or (cfg.scratch_dir / candidate.id))
    work.mkdir(parents=True, exist_ok=True)
    candidate.workdir = str(work)

    backend = get_sign_backend(cfg)
    verilog: list[str] = []
    t5 = candidate.metrics.get("t5_rtl") or {}
    if isinstance(t5, dict):
        verilog = list(t5.get("verilog") or [])

    sign = backend.run(
        SignRequest(
            candidate_id=candidate.id,
            workdir=work,
            verilog_files=verilog,
            meta={"problem": problem.title, "sign_enabled": cfg.sign.enabled},
        )
    )

    result = TierResult(
        tier=Tier.T6,
        verdict=Verdict.UNAVAILABLE,
        score=0.0,
        summary="Tier6 signoff reserved; not implemented",
        evidence=EvidenceLevel.SIGNOFF,
        metrics={
            "backend": sign.backend,
            "unavailable": True,
            "planned": True,
            "log": sign.log,
        },
        clause_refs=candidate.clause_refs,
    )
    # Never mark failed for reserved tier
    candidate.tier_history.append(result)
    candidate.status = "active"
    candidate.metrics["t6_signoff"] = result.metrics
    (work / "SIGNOFF.md").write_text(
        "# Tier6 Signoff — Planned\n\n"
        "Physical signoff (yosys + OpenROAD + sky130) is reserved.\n"
        "This candidate reached Tier6 registration only.\n",
        encoding="utf-8",
    )
    return candidate
