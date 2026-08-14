"""Export a campaign as a reproducibility bundle."""

from __future__ import annotations

import json
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from archzero.config import ROOT, FactoryConfig
from archzero.report.weekly import build_report
from archzero.sim.headlines import candidate_headlines, headlines_text
from archzero.spec.ndf import render_problem_package
from archzero.store.db import Store


def _git_sha() -> str | None:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        if out.returncode == 0:
            return out.stdout.strip()
    except Exception:  # noqa: BLE001
        return None
    return None


def _tool_versions() -> dict[str, str]:
    import shutil as sh

    vers: dict[str, str] = {}
    for tool in ("verilator", "iverilog", "yosys", "pycc"):
        path = sh.which(tool)
        if not path:
            continue
        try:
            out = subprocess.run(
                [path, "--version"],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
            vers[tool] = (out.stdout or out.stderr).splitlines()[0][:120]
        except Exception:  # noqa: BLE001
            vers[tool] = path
    return vers


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
        "strict_evidence": cfg.funnel.strict_evidence,
        "git_sha": _git_sha(),
        "tool_versions": _tool_versions(),
        "preferred_cursor": cfg.pools.preferred_cursor,
        "tier6": "reserved",
    }
    (root / "manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )

    # Config + lockfile snapshots
    cfg_src = ROOT / "archzero.toml"
    if cfg_src.is_file():
        shutil.copy2(cfg_src, root / "archzero.toml")
    lock = ROOT / "uv.lock"
    if lock.is_file():
        shutil.copy2(lock, root / "uv.lock")
    catalog = cfg.state_dir / "model_catalog.json"
    if catalog.is_file():
        shutil.copy2(catalog, root / "model_catalog.json")

    pp = store.get_problem(camp.problem_id)
    if pp and pp.source_path and Path(pp.source_path).is_file():
        shutil.copy2(pp.source_path, root / "problem.md")
    elif pp:
        (root / "problem.md").write_text(render_problem_package(pp), encoding="utf-8")
    else:
        demo = ROOT / "specs" / "demo.md"
        if demo.is_file():
            shutil.copy2(demo, root / "problem.md")

    index = []
    for c in store.list_candidates(campaign_id=campaign_id):
        entry = {
            "id": c.id,
            "title": c.title,
            "family": c.family,
            "headlines": candidate_headlines(c.metrics, family=c.family),
            "status": c.status,
            "parent_id": c.parent_id,
            "clause_refs": c.clause_refs,
            "tier_history": [
                {
                    "tier": t.tier.value,
                    "verdict": t.verdict.value,
                    "score": t.score,
                    "summary": t.summary,
                    "evidence": t.evidence.value,
                    "model_id": t.model_id,
                    "pool": t.pool.value if t.pool else None,
                    "prompt_hash": t.prompt_hash,
                    "downgraded": t.downgraded,
                    "tool_versions": t.tool_versions,
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
        hl = headlines_text(c.metrics, family=c.family)
        body = (
            f"# {c.title}\n\nFamily: {c.family}\nStatus: {c.status}\n\n"
            f"{c.mechanism}\n\n## Metrics\n\n"
            f"Headlines: {hl}\n\n```json\n"
            f"{json.dumps(c.metrics, indent=2, default=str)}\n```\n"
        )
        (root / "candidates" / f"{c.id}.md").write_text(body, encoding="utf-8")
        if c.workdir and Path(c.workdir).is_dir():
            dest = root / "artifacts" / c.id
            dest.mkdir(parents=True, exist_ok=True)
            for name in (
                "SPECIFICATION.md",
                "model.py",
                "sim_knobs.json",
                "EQUIV_GATE.md",
                "design.py",
                "tb_design.py",
                "DECISION.md",
                "SIGNOFF.md",
            ):
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
        f"- `manifest.json` — run metadata (git sha, tools, models)\n"
        f"- `archzero.toml` / `uv.lock` — config snapshots when present\n"
        f"- `problem.md` — NDF-lite problem package\n"
        f"- `candidates/` + `candidates.json` — mechanisms + tier provenance\n"
        f"- `artifacts/` — model.py / DSL / knobs when present\n"
        f"- `REPORT.md` — funnel throughput report\n\n"
        f"Replay stub gates: `archzero reproduce {root}`\n"
        f"Tier6 signoff: reserved / not implemented.\n"
        f"Telemetry Feedback: deferred.\n",
        encoding="utf-8",
    )
    return root
