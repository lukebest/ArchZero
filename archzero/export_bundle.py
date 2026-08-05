"""Export a campaign as a reproducibility bundle (openscience-style artifact pack)."""

from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from archzero.config import FactoryConfig
from archzero.report.weekly import build_report
from archzero.spec.ndf import load_problem_package, render_problem_package
from archzero.store.db import Store


def export_campaign_bundle(
    cfg: FactoryConfig,
    campaign_id: str,
    out_dir: Path,
) -> Path:
    store = Store(cfg.db_path)
    camp = store.get_campaign(campaign_id)
    if camp is None:
        raise ValueError(f"unknown campaign: {campaign_id}")

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    root = out_dir / f"archzero-{campaign_id}-{stamp}"
    if root.exists():
        shutil.rmtree(root)
    (root / "candidates").mkdir(parents=True)
    (root / "artifacts").mkdir(parents=True)

    # Manifest
    manifest = {
        "product": "ArchZero Idea Factory",
        "paper": "https://arxiv.org/abs/2604.03312",
        "campaign_id": camp.id,
        "name": camp.name,
        "through": camp.through_tier.value,
        "status": camp.status,
        "exported_at": stamp,
        "telemetry": "deferred",
        "sim_backend": cfg.sim.backend,
    }
    (root / "manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )

    # Problem package
    pp = store.get_problem(camp.problem_id)
    if pp and pp.source_path and Path(pp.source_path).is_file():
        shutil.copy2(pp.source_path, root / "problem.md")
    elif pp:
        (root / "problem.md").write_text(render_problem_package(pp), encoding="utf-8")
    else:
        # try demo path
        demo = Path(__file__).resolve().parents[1] / "specs" / "demo.md"
        if demo.is_file():
            shutil.copy2(demo, root / "problem.md")

    # Candidates
    index = []
    for c in store.list_candidates(campaign_id=campaign_id):
        entry = {
            "id": c.id,
            "title": c.title,
            "family": c.family,
            "status": c.status,
            "clause_refs": c.clause_refs,
            "tier_history": [
                {
                    "tier": t.tier.value,
                    "verdict": t.verdict.value,
                    "score": t.score,
                    "summary": t.summary,
                }
                for t in c.tier_history
            ],
            "failures": [
                {
                    "tier": f.tier.value,
                    "kind": f.kind.value,
                    "message": f.message,
                }
                for f in c.failures
            ],
        }
        index.append(entry)
        body = (
            f"# {c.title}\n\nFamily: {c.family}\nStatus: {c.status}\n\n"
            f"{c.mechanism}\n\n## Metrics\n\n```json\n"
            f"{json.dumps(c.metrics, indent=2, default=str)}\n```\n"
        )
        (root / "candidates" / f"{c.id}.md").write_text(body, encoding="utf-8")
        # Copy workdir model/spec if present
        if c.workdir and Path(c.workdir).is_dir():
            dest = root / "artifacts" / c.id
            dest.mkdir(parents=True, exist_ok=True)
            for name in ("SPECIFICATION.md", "model.py", "sim_knobs.json", "EQUIV_GATE.md"):
                src = Path(c.workdir) / name
                if src.is_file():
                    shutil.copy2(src, dest / name)

    (root / "candidates.json").write_text(
        json.dumps(index, indent=2), encoding="utf-8"
    )
    (root / "REPORT.md").write_text(
        build_report(cfg, campaign_id=campaign_id), encoding="utf-8"
    )
    (root / "README.md").write_text(
        f"# ArchZero reproducibility bundle\n\n"
        f"Campaign `{camp.id}` — {camp.name}\n\n"
        f"Contents:\n"
        f"- `manifest.json` — run metadata\n"
        f"- `problem.md` — NDF-lite problem package (constitution)\n"
        f"- `candidates/` — mechanism text per candidate\n"
        f"- `candidates.json` — structured tier/failure history\n"
        f"- `artifacts/` — model.py / specs when present\n"
        f"- `REPORT.md` — funnel throughput report\n\n"
        f"Paper target: Generation + Tier0–5 Evaluation "
        f"(telemetry Feedback deferred).\n",
        encoding="utf-8",
    )
    return root
