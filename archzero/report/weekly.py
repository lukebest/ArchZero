"""Weekly-style funnel report."""

from __future__ import annotations

from pathlib import Path

from archzero.config import FactoryConfig
from archzero.funnel.taxonomy import summarize_failures
from archzero.models import Tier, Verdict
from archzero.store.db import Store


def build_report(cfg: FactoryConfig, campaign_id: str | None = None) -> str:
    store = Store(cfg.db_path)
    campaigns = store.list_campaigns()
    if campaign_id:
        campaigns = [c for c in campaigns if c.id == campaign_id]
    if not campaigns:
        return "# ArchZero report\n\nNo campaigns found.\n"

    lines: list[str] = ["# ArchZero Idea Factory — Funnel Report", ""]
    for camp in campaigns:
        lines.append(f"## Campaign `{camp.id}` — {camp.name}")
        lines.append("")
        lines.append(f"- status: **{camp.status}**")
        lines.append(f"- through: `{camp.through_tier.value}`")
        lines.append(f"- problem: `{camp.problem_id}`")
        lines.append("")

        cands = store.list_candidates(campaign_id=camp.id)
        lines.append(f"### Throughput ({len(cands)} candidates)")
        lines.append("")
        lines.append("| Tier | Entered | Passed | Failed | Pass rate |")
        lines.append("|------|---------|--------|--------|-----------|")
        for tier in Tier:
            entered = 0
            passed = 0
            failed = 0
            for c in cands:
                for tr in c.tier_history:
                    if tr.tier != tier:
                        continue
                    entered += 1
                    if tr.verdict == Verdict.PASS:
                        passed += 1
                    elif tr.verdict == Verdict.FAIL:
                        failed += 1
            rate = f"{(passed / entered):.0%}" if entered else "—"
            lines.append(
                f"| {tier.value} | {entered} | {passed} | {failed} | {rate} |"
            )
        lines.append("")

        fails = store.list_failures(campaign_id=camp.id)
        summary = summarize_failures(fails)
        elim = (camp.meta or {}).get("elimination")
        if elim:
            lines.append("### Failure elimination (causal)")
            lines.append("")
            parent = elim.get("source_campaign_id") or (camp.meta or {}).get(
                "parent_campaign_id"
            )
            if parent:
                lines.append(f"- source campaign: `{parent}`")
            lines.append(
                f"- kinds eliminated: {', '.join(elim.get('kinds_eliminated') or []) or '—'}"
            )
            lines.append(
                f"- kinds reduced: {', '.join(elim.get('kinds_reduced') or []) or '—'}"
            )
            lines.append(
                f"- kind_elimination_rate: {elim.get('kind_elimination_rate')}"
            )
            lines.append(
                f"- fingerprints eliminated/persisted: "
                f"{elim.get('fingerprints_eliminated')}/"
                f"{elim.get('fingerprints_persisted')}"
            )
            lines.append("")
        lines.append("### Failure taxonomy")
        lines.append("")
        if summary:
            for k, v in sorted(summary.items(), key=lambda kv: -kv[1]):
                lines.append(f"- `{k}`: {v}")
        else:
            lines.append("- (none)")
        lines.append("")

        usage = store.usage_totals(camp.id)
        lines.append("### Usage pools")
        lines.append("")
        lines.append("| Pool | Calls | Tokens |")
        lines.append("|------|------:|-------:|")
        for pool in ("cursor", "other"):
            bucket = usage.get(pool, {"calls": 0, "tokens": 0})
            lines.append(
                f"| {pool} | {bucket.get('calls', 0)} | {bucket.get('tokens', 0)} |"
            )
        lines.append("")

        # Top survivors
        survivors = [c for c in cands if c.status == "active"]
        survivors.sort(
            key=lambda c: (c.last_tier().score if c.last_tier() and c.last_tier().score else 0),
            reverse=True,
        )
        lines.append("### Active / surviving candidates")
        lines.append("")
        for c in survivors[:10]:
            lt = c.last_tier()
            lines.append(
                f"- `{c.id}` **{c.title}** ({c.family}) "
                f"last={lt.tier.value if lt else '—'} "
                f"score={lt.score if lt else '—'}"
            )
        if not survivors:
            lines.append("- (none)")
        lines.append("")

    lines.append("---")
    lines.append("")
    lines.append(
        "_Feedback/telemetry calibration is deferred; numbers above reflect "
        "Generation + Evaluation only._"
    )
    lines.append("")
    return "\n".join(lines)


def write_report(
    cfg: FactoryConfig,
    *,
    campaign_id: str | None = None,
    out: Path,
) -> Path:
    text = build_report(cfg, campaign_id=campaign_id)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    return out
