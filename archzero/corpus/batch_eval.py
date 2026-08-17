"""Batch offline corpus evaluation scaffold (FakeLLM; no success-rate invention)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from archzero.config import FactoryConfig
from archzero.corpus.status import corpus_status, default_corpus_root
from archzero.llm.fake import FakeLLM
from archzero.models import Candidate, Tier
from archzero.offline import fake_llm_responses, knobs_for, problem_domain
from archzero.spec.ndf import load_problem_package
from archzero.store.db import Store


def _fake_llm(domain: str) -> FakeLLM:
    return FakeLLM(
        responses=fake_llm_responses(domain),
        sequence=[
            '{"verdict":"pass","score":0.8,"summary":"insight ok",'
            '"magic_gap_notes":"","clause_refs":[]}'
        ],
    )


async def evaluate_corpus_entry(
    cfg: FactoryConfig,
    entry: dict[str, Any],
    *,
    corpus_root: Path,
    through: Tier = Tier.T2,
) -> dict[str, Any]:
    """Offline-evaluate one corpus entry through cheap tiers (default Tier2)."""
    spec_rel = entry.get("spec")
    if not spec_rel:
        return {
            "entry_id": entry.get("id"),
            "ok": False,
            "error": "missing spec path",
        }
    spec_path = corpus_root / spec_rel
    if not spec_path.is_file():
        return {
            "entry_id": entry.get("id"),
            "ok": False,
            "error": f"spec not found: {spec_path}",
        }

    pp = load_problem_package(spec_path)
    family = str(entry.get("family") or "unclassified")
    domain = problem_domain(pp, family)
    store = Store(cfg.db_path)
    store.save_problem(pp)
    work = cfg.scratch_dir / "corpus" / str(entry.get("id") or "anon")
    work.mkdir(parents=True, exist_ok=True)
    (work / "sim_knobs.json").write_text(
        json.dumps(knobs_for(domain, family)),
        encoding="utf-8",
    )
    cand = Candidate(
        problem_id=pp.id,
        title=str(entry.get("title") or entry.get("id")),
        mechanism=(
            f"Corpus scaffold candidate for {entry.get('id')} "
            f"({family}, domain={domain}). Offline FakeLLM evaluation only."
        ),
        family=family,
        workdir=str(work),
        metrics={"corpus_entry_id": entry.get("id"), "domain": domain},
    )

    from archzero.funnel.tier0 import evaluate_tier0
    from archzero.funnel.tier1 import evaluate_tier1
    from archzero.funnel.tier2 import evaluate_tier2

    llm = _fake_llm(domain)
    cfg.funnel.use_verifiers = True
    cfg.funnel.ensemble_n = 1
    cfg.sim.backend = "stub"
    out = cand
    tiers = [Tier.T0, Tier.T1, Tier.T2]
    stop = tiers.index(through) if through in tiers else 2
    fns = {
        Tier.T0: evaluate_tier0,
        Tier.T1: evaluate_tier1,
        Tier.T2: evaluate_tier2,
    }
    for t in tiers[: stop + 1]:
        out = await fns[t](cfg, out, pp, llm)
        store.save_candidate(out, campaign_id=None)

    last = out.tier_history[-1] if out.tier_history else None
    return {
        "entry_id": entry.get("id"),
        "ok": True,
        "domain": domain,
        "through": through.value,
        "last_verdict": last.verdict.value if last else None,
        "last_tier": last.tier.value if last else None,
        "pdf": entry.get("pdf"),
        "pdf_real": bool(entry.get("pdf_real")),
        "cleanroom_label": entry.get("cleanroom_label"),
        "note": "offline FakeLLM scaffold — not a paper success-rate claim",
    }


async def evaluate_corpus_batch(
    cfg: FactoryConfig,
    *,
    corpus_root: Path | None = None,
    through: Tier = Tier.T2,
    limit: int | None = None,
    only_with_pdf: bool = False,
) -> dict[str, Any]:
    """Evaluate corpus entries offline; never invent aggregate success_rate."""
    root = corpus_root or default_corpus_root()
    st = corpus_status(root)
    if not st.get("ok"):
        return {"ok": False, "error": st.get("message"), "results": []}

    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    entries = list(manifest.get("entries") or [])
    if only_with_pdf:
        entries = [e for e in entries if e.get("pdf")]
    if limit is not None:
        entries = entries[: max(0, limit)]

    results = []
    by_id = {str(e.get("id")): e for e in (manifest.get("entries") or [])}
    for entry in entries:
        row = await evaluate_corpus_entry(
            cfg, entry, corpus_root=root, through=through
        )
        results.append(row)
        eid = str(entry.get("id") or "")
        target = by_id.get(eid)
        if target is not None and row.get("ok"):
            target["evaluated"] = True
            target["last_offline_verdict"] = row.get("last_verdict")
            target["last_offline_tier"] = row.get("last_tier")
            target["domain"] = row.get("domain")

    manifest_path = root / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    n_ok = sum(1 for r in results if r.get("ok") and r.get("last_verdict") == "pass")
    return {
        "ok": True,
        "status": st.get("status"),
        "corpus": str(root),
        "n_entries": len(results),
        "n_pass_offline": n_ok,
        "success_rate": None,
        "disclaimer": (
            "Offline FakeLLM batch only. success_rate remains null while "
            "manifest.status != complete / real papers unevaluated."
        ),
        "results": results,
    }
