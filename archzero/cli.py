"""ArchZero CLI.

Offline (no API key): init | spec | acc | new-spec | seed-demo | ui | status |
show | report | export | compare | reproduce | e2e --offline.
Live (needs CURSOR_API_KEY): read | ideate | diverge | run | flow | frontier |
evolve | patent.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from archzero import __version__
from archzero.config import load_config, write_default_config
from archzero.models import Tier

app = typer.Typer(
    name="archzero",
    help="Idea Factory for computer architecture — CPU, memory, NoC, and other chip design.",
    no_args_is_help=True,
)
console = Console()


def _cfg(config: Optional[Path] = None):
    return load_config(config)


def _print_acc_notice(result: dict) -> None:
    """Tell the researcher when the funnel declined to grade their spec."""
    acc = result.get("acc") or {}
    if acc.get("clamped_from"):
        console.print(
            f"[red]漏斗封顶在 Tier1[/red]（原请求 {acc['clamped_from']}）"
            f"— {acc.get('reason', '')}"
        )
        return
    gaps = acc.get("unmeasurable_metrics") or []
    if gaps:
        console.print(
            f"[yellow]评估盲区[/yellow] 以下声明指标无评估器，未被检查："
            f"{', '.join(gaps)}"
        )


@app.callback()
def main(
    ctx: typer.Context,
    config: Optional[Path] = typer.Option(
        None, "--config", "-c", help="Path to archzero.toml"
    ),
) -> None:
    ctx.ensure_object(dict)
    ctx.obj["config_path"] = config


@app.command("init")
def init_cmd(
    ctx: typer.Context,
) -> None:
    """Write default archzero.toml and ensure .archzero/ dirs."""
    cfg = _cfg(ctx.obj.get("config_path"))
    path = write_default_config()
    cfg.ensure_dirs()
    console.print(f"[green]Wrote[/green] {path}")
    console.print(f"[green]State dir[/green] {cfg.state_dir}")


@app.command("models")
def models_cmd(
    ctx: typer.Context,
    refresh: bool = typer.Option(False, "--refresh", help="Bypass catalog cache"),
) -> None:
    """List Cursor models available to CURSOR_API_KEY and show pool routing."""
    from archzero.llm.catalog import ModelCatalog

    cfg = _cfg(ctx.obj.get("config_path"))
    catalog = ModelCatalog(cfg)
    models = asyncio.run(catalog.list_models(refresh=refresh))
    table = Table(title="Cursor model catalog")
    table.add_column("id")
    table.add_column("pool")
    table.add_column("in catalog")
    for mid, pool in catalog.classify_all(models).items():
        table.add_row(mid, pool.value, "yes")
    for mid in cfg.pools.cursor_models:
        if mid not in {m.id for m in models}:
            table.add_row(mid, "cursor", "[dim]missing[/dim]")
    console.print(table)
    routes = catalog.resolved_routes()
    rtable = Table(title="Task → model routing")
    rtable.add_column("task")
    rtable.add_column("pool")
    rtable.add_column("model")
    for task, (pool, model) in routes.items():
        rtable.add_row(task, pool.value, model)
    console.print(rtable)


@app.command("spec")
def spec_cmd(
    ctx: typer.Context,
    path: Path = typer.Argument(..., help="Problem package markdown path"),
    lint: bool = typer.Option(True, "--lint/--no-lint"),
    register: bool = typer.Option(True, "--register/--no-register"),
) -> None:
    """Lint and optionally register an NDF-lite problem package."""
    from archzero.spec.lint import lint_acceptance, lint_package
    from archzero.spec.ndf import load_problem_package
    from archzero.store.db import Store

    cfg = _cfg(ctx.obj.get("config_path"))
    pp = load_problem_package(path)
    if lint:
        issues = lint_package(pp)
        if issues:
            for i in issues:
                console.print(f"[yellow]lint[/yellow] {i}")
            raise typer.Exit(code=1)
        console.print("[green]lint ok[/green]")
        # Structurally valid specs can still be ungradable. Warn, do not fail —
        # registering an interconnect or wafer-scale problem is legitimate.
        acc_issues = lint_acceptance(pp)
        for i in acc_issues:
            console.print(f"[yellow]acc[/yellow] {i}")
        if acc_issues:
            console.print("[dim]详情：archzero acc " + str(path) + "[/dim]")
    if register:
        store = Store(cfg.db_path)
        store.save_problem(pp)
        console.print(f"[green]registered[/green] problem {pp.id} — {pp.title}")
    else:
        console.print(f"parsed {pp.title} ({len(pp.clauses)} clauses)")


@app.command("acc")
def acc_cmd(
    ctx: typer.Context,
    path: Path = typer.Argument(..., help="Problem package markdown path"),
    registry: bool = typer.Option(
        False, "--registry", help="Also print the full cross-domain metric registry"
    ),
) -> None:
    """Show exactly which thresholds the funnel will grade this spec on.

    Every gate number is labelled as read from a clause or as a tool default,
    so a NoC / wafer-scale spec can no longer be graded against cache numbers
    without saying so.
    """
    from archzero.spec.acc_parse import parse_acceptance_thresholds
    from archzero.spec.metrics import METRIC_BY_ID, registry_markdown
    from archzero.spec.ndf import load_problem_package

    cfg = _cfg(ctx.obj.get("config_path"))
    pp = load_problem_package(path)
    th = parse_acceptance_thresholds(pp)

    console.print(f"[bold]{pp.title}[/bold]")
    console.print(f"领域推断: [cyan]{th.domain}[/cyan]  ·  条款数: {len(pp.clauses)}\n")

    table = Table(title="漏斗将使用的数值门限", show_lines=False)
    table.add_column("gate")
    table.add_column("值")
    table.add_column("来源")
    table.add_column("条款")
    for gate_field, value, origin, clause in th.provenance_rows():
        from_spec = origin == "规范声明"
        table.add_row(
            gate_field,
            str(value),
            f"[green]{origin}[/green]" if from_spec else f"[yellow]{origin}[/yellow]",
            clause,
        )
    console.print(table)

    if th.declared_metrics:
        dtable = Table(title="ACC/REQ 中识别到的指标")
        dtable.add_column("metric")
        dtable.add_column("名称")
        dtable.add_column("评估器")
        for mid in th.declared_metrics:
            spec = METRIC_BY_ID.get(mid)
            if spec is None:
                continue
            evals = ", ".join(spec.evaluators)
            dtable.add_row(
                mid,
                spec.name,
                f"[green]{evals}[/green]" if evals else "[red]无（不会被检查）[/red]",
            )
        console.print(dtable)

    if not th.gradable:
        console.print(
            f"\n[red]不可评判[/red] {th.ungradable_reason()}\n"
            f"[dim]strict_acc={cfg.funnel.strict_acc}；为真时漏斗封顶在 Tier1，"
            f"Tier2+ 报 UNAVAILABLE 而不给出缓存门限下的假结论。[/dim]"
        )
    elif th.report_only:
        console.print(
            f"\n[cyan]可测量 / 不裁决[/cyan] 将报告 "
            f"{', '.join(th.measurable_performance)}，"
            f"但规范未给出数值门限，漏斗不会据此 PASS/FAIL。"
        )
        if th.unmeasurable_note():
            console.print(f"[yellow]部分盲区[/yellow] {th.unmeasurable_note()}")
    elif th.unmeasurable_note():
        console.print(f"\n[yellow]部分盲区[/yellow] {th.unmeasurable_note()}")
    else:
        console.print("\n[green]可评判[/green] 所有声明指标均有评估器支撑。")

    if registry:
        console.print()
        console.print(registry_markdown())


@app.command("read")
def read_cmd(
    ctx: typer.Context,
    pdf: Path = typer.Argument(..., exists=True, help="Paper PDF"),
    out: Path = typer.Option(Path("insights.md"), "--out", "-o"),
    personas: Optional[str] = typer.Option(
        None, "--personas", help="Comma-separated persona stems under archzero/personas"
    ),
) -> None:
    """Comprehension: multi-persona paper distillation."""
    from archzero.generation.comprehension import comprehend_paper

    cfg = _cfg(ctx.obj.get("config_path"))
    persona_list = (
        [p.strip() for p in personas.split(",") if p.strip()] if personas else None
    )
    text = asyncio.run(comprehend_paper(cfg, pdf, persona_names=persona_list))
    out.write_text(text, encoding="utf-8")
    console.print(f"[green]wrote[/green] {out}")


@app.command("ideate")
def ideate_cmd(
    ctx: typer.Context,
    pdf: Path = typer.Argument(..., exists=True, help="Paper PDF"),
    spec: Optional[Path] = typer.Option(None, "--spec", help="Problem package"),
    out: Path = typer.Option(Path("candidates"), "--out", "-o"),
    n: Optional[int] = typer.Option(None, "--n", help="Independent generations"),
) -> None:
    """Clean-room ideation: produce N mechanism candidates."""
    from archzero.generation.cleanroom import cleanroom_ideate
    from archzero.spec.ndf import load_problem_package

    cfg = _cfg(ctx.obj.get("config_path"))
    pp = load_problem_package(spec) if spec else None
    cands = asyncio.run(cleanroom_ideate(cfg, pdf, problem=pp, n=n or cfg.cleanroom_n))
    out.mkdir(parents=True, exist_ok=True)
    for i, c in enumerate(cands):
        p = out / f"candidate_{i:03d}.md"
        p.write_text(
            f"# {c.title}\n\nFamily: {c.family}\n\n{c.mechanism}\n",
            encoding="utf-8",
        )
    console.print(f"[green]wrote[/green] {len(cands)} candidates → {out}")


@app.command("run")
def run_cmd(
    ctx: typer.Context,
    spec: Optional[Path] = typer.Option(
        None, "--spec", exists=True, help="Problem package (required unless --resume)"
    ),
    pdf: Optional[Path] = typer.Option(None, "--pdf", exists=True),
    through: str = typer.Option("tier2", "--through", help="Stop after this tier (tier6=reserved)"),
    name: Optional[str] = typer.Option(None, "--name"),
    seed_dir: Optional[Path] = typer.Option(
        None, "--seed-dir", help="Directory of candidate markdown files"
    ),
    n_generate: int = typer.Option(10, "--n", help="Candidates to generate if no seed"),
    expand_frontier: bool = typer.Option(
        False,
        "--expand-frontier/--no-expand-frontier",
        help="After funnel: §5.1 vertical/lateral/foundational expansion from failures",
    ),
    frontier_offline: bool = typer.Option(
        False,
        "--frontier-offline",
        help="Use deterministic theory scaffolds (no LLM) for frontier expansion",
    ),
    resume: Optional[str] = typer.Option(
        None, "--resume", help="Resume an existing campaign id"
    ),
    auto_round: int = typer.Option(
        0, "--auto-round", help="After frontier: re-run funnel on expanded packages N times"
    ),
    max_tokens: Optional[int] = typer.Option(
        None, "--max-tokens", help="Optional Cursor pool token ceiling for this process"
    ),
    diverge: Optional[bool] = typer.Option(
        None,
        "--diverge/--no-diverge",
        help="Generate via the cross-domain matrix instead of repeated ideation",
    ),
    diverge_cells: Optional[int] = typer.Option(
        None, "--diverge-cells", help="Matrix cells = LLM calls (default 24)"
    ),
    diverge_per_cell: Optional[int] = typer.Option(
        None, "--diverge-per-cell", help="Ideas requested per cell (default 8)"
    ),
) -> None:
    """Run the evaluation funnel on generated or seeded candidates."""
    from archzero.funnel.pipeline import run_campaign
    from archzero.logging_util import setup_logging

    setup_logging()
    cfg = _cfg(ctx.obj.get("config_path"))
    if max_tokens is not None:
        cfg.budget.cursor_pool_max_tokens = max_tokens
    try:
        through_tier = Tier(through)
    except ValueError as e:
        raise typer.BadParameter(f"unknown tier {through}") from e
    if through_tier == Tier.T6:
        console.print(
            "[yellow]note[/yellow] Tier6 is reserved — candidates will get UNAVAILABLE"
        )
    if resume is None and spec is None:
        raise typer.BadParameter("--spec is required unless --resume is set")
    result = asyncio.run(
        run_campaign(
            cfg,
            spec_path=spec,
            pdf=pdf,
            through=through_tier,
            name=name,
            seed_dir=seed_dir,
            n_generate=n_generate,
            expand_frontier=expand_frontier,
            frontier_offline=frontier_offline,
            resume_campaign_id=resume,
            auto_round=auto_round,
            use_divergence=diverge,
            diverge_cells=diverge_cells,
            diverge_per_cell=diverge_per_cell,
        )
    )
    _print_acc_notice(result)
    console.print(
        f"[green]campaign[/green] {result['campaign_id']} "
        f"passed={result['passed']} failed={result['failed']} "
        f"through={result.get('through', through)}"
    )
    if result.get("divergence"):
        dv = result["divergence"]
        console.print(
            f"[green]divergence[/green] cells={dv.get('n_cells')} "
            f"ideas={dv.get('generated')}"
        )
    if result.get("frontier"):
        fr = result["frontier"]
        console.print(
            f"[green]frontier[/green] paradigms={fr.get('n_paradigm_candidates')} "
            f"kinds={fr.get('kinds')} report={fr.get('report_path')}"
        )
    if result.get("auto_rounds"):
        console.print(f"[green]auto-rounds[/green] {len(result['auto_rounds'])}")


@app.command("diverge")
def diverge_cmd(
    ctx: typer.Context,
    spec: Path = typer.Option(..., "--spec", exists=True, help="Problem package"),
    out: Path = typer.Option(Path("divergence"), "--out", "-o"),
    cells: Optional[int] = typer.Option(
        None, "--cells", help="Matrix cells = LLM calls (default 24)"
    ),
    per_cell: Optional[int] = typer.Option(
        None, "--per-cell", help="Ideas requested per cell (default 8)"
    ),
    lens: Optional[str] = typer.Option(
        None, "--lens", help="Comma-separated theory lens whitelist"
    ),
    domain: Optional[str] = typer.Option(
        None, "--domain", help="Comma-separated cross-domain source whitelist"
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Show matrix coverage without calling the LLM"
    ),
) -> None:
    """Cross-domain mass ideation: theory lens x domain source x expansion mode."""
    from archzero.generation.divergence import (
        build_matrix,
        coverage_summary,
        diverge,
        divergence_markdown,
        dumps_pool,
    )
    from archzero.generation.domains import domain_catalog_markdown
    from archzero.generation.theories import theory_catalog_markdown
    from archzero.spec.ndf import load_problem_package

    cfg = _cfg(ctx.obj.get("config_path"))
    pp = load_problem_package(spec)
    n_cells = cells or cfg.divergence.n_cells
    n_per = per_cell or cfg.divergence.per_cell
    lens_ids = [s.strip() for s in lens.split(",") if s.strip()] if lens else None
    domain_ids = [s.strip() for s in domain.split(",") if s.strip()] if domain else None

    matrix = build_matrix(
        pp, n_cells=n_cells, lens_ids=lens_ids, domain_ids=domain_ids
    )
    cov = coverage_summary(matrix)

    table = Table(title=f"Divergence matrix ({len(matrix)} cells)")
    table.add_column("mode")
    table.add_column("theory lens")
    table.add_column("cross-domain source")
    for cell in matrix:
        table.add_row(cell.mode, cell.lens.name, cell.domain.name)
    console.print(table)
    console.print(
        f"coverage: {len(cov['lens'])} lenses / {len(cov['domain'])} domains "
        f"/ {len(cov['mode'])} modes"
    )
    if dry_run:
        console.print(f"[yellow]dry-run[/yellow] would issue {len(matrix)} LLM calls")
        return

    cands = asyncio.run(
        diverge(
            cfg,
            pp,
            n_cells=n_cells,
            per_cell=n_per,
            lens_ids=lens_ids,
            domain_ids=domain_ids,
        )
    )
    out.mkdir(parents=True, exist_ok=True)
    (out / "THEORY_LENSES.md").write_text(theory_catalog_markdown(), encoding="utf-8")
    (out / "DOMAIN_SOURCES.md").write_text(domain_catalog_markdown(), encoding="utf-8")
    (out / "DIVERGENCE.md").write_text(
        divergence_markdown(pp, matrix, cands), encoding="utf-8"
    )
    (out / "ideas.json").write_text(dumps_pool(cands), encoding="utf-8")
    console.print(
        f"[green]diverged[/green] {len(cands)} ideas from {len(matrix)} cells → {out}"
    )


@app.command("frontier")
def frontier_cmd(
    ctx: typer.Context,
    spec: Path = typer.Option(..., "--spec", exists=True, help="Problem package"),
    campaign: Optional[str] = typer.Option(
        None, "--campaign", help="Optional campaign whose failures become signals"
    ),
    out: Path = typer.Option(Path("frontiers"), "--out", "-o"),
    offline: bool = typer.Option(
        False, "--offline", help="Deterministic theory scaffolds (no LLM)"
    ),
) -> None:
    """§5.1 paradigm expansion: vertical / lateral / foundational + theory lenses."""
    from archzero.funnel.taxonomy import failures_as_signals
    from archzero.generation.frontier import expand_frontier
    from archzero.generation.theories import theory_catalog_markdown
    from archzero.spec.ndf import load_problem_package
    from archzero.store.db import Store

    cfg = _cfg(ctx.obj.get("config_path"))
    pp = load_problem_package(spec)
    signals: list[str] = []
    if campaign:
        store = Store(cfg.db_path)
        signals = failures_as_signals(store.list_failures(campaign_id=campaign))
    out.mkdir(parents=True, exist_ok=True)
    (out / "THEORY_LENSES.md").write_text(theory_catalog_markdown(), encoding="utf-8")
    result = asyncio.run(
        expand_frontier(
            cfg,
            pp,
            signals=signals,
            out_dir=out,
            offline=offline,
        )
    )
    store = Store(cfg.db_path)
    store.save_problem(pp)
    for pkg in result["packages"]:
        store.save_problem(pkg)
    console.print(
        f"[green]frontier[/green] wrote {len(result['packages'])} problem packages + "
        f"{len(result['candidates'])} paradigm candidates → {out}"
    )
    for c in result["candidates"]:
        console.print(
            f"  • [{c.kind}] {c.title}  theories={','.join(c.theory_lenses) or '—'} "
            f"novelty={c.score_novelty}"
        )
    if result.get("report_path"):
        console.print(f"  report: {result['report_path']}")


@app.command("evolve")
def evolve_cmd(
    ctx: typer.Context,
    campaign: str = typer.Option(..., "--campaign", help="Campaign id"),
    generations: Optional[int] = typer.Option(None, "--generations"),
    reenter: bool = typer.Option(
        True,
        "--reenter/--no-reenter",
        help="Re-enter evolved children through Tier0..reenter_through",
    ),
) -> None:
    """Run evolutionary search on candidates that reached Tier2+."""
    from archzero.evolve.mapelites import run_evolution

    cfg = _cfg(ctx.obj.get("config_path"))
    gens = generations or cfg.evolve.generations
    summary = asyncio.run(
        run_evolution(
            cfg,
            campaign_id=campaign,
            generations=gens,
            reenter=reenter,
        )
    )
    console.print(f"[green]evolve[/green] {summary}")


@app.command("flow")
def flow_cmd(
    ctx: typer.Context,
    spec: Path = typer.Option(..., "--spec", exists=True, help="Problem package"),
    through: str = typer.Option("tier2", "--through", help="Stop after this tier"),
    cells: Optional[int] = typer.Option(
        None, "--cells", help="Divergence matrix cells (default 24)"
    ),
    per_cell: Optional[int] = typer.Option(
        None, "--per-cell", help="Ideas per cell (default 8)"
    ),
    out: Path = typer.Option(Path("flow"), "--out", "-o", help="Output directory"),
    patent: bool = typer.Option(
        False, "--patent", help="Also draft the optional disclosure + review deck"
    ),
    patent_top: int = typer.Option(
        1, "--patent-top", help="How many survivors to draft patents for"
    ),
) -> None:
    """One shot: diverge → funnel → report (→ optional patent deck)."""
    from archzero.funnel.pipeline import run_campaign
    from archzero.logging_util import setup_logging
    from archzero.report.weekly import write_report
    from archzero.spec.lint import lint_package
    from archzero.spec.ndf import load_problem_package

    setup_logging()
    cfg = _cfg(ctx.obj.get("config_path"))
    try:
        through_tier = Tier(through)
    except ValueError as e:
        raise typer.BadParameter(f"unknown tier {through}") from e

    pp = load_problem_package(spec)
    issues = lint_package(pp)
    for issue in issues:
        console.print(f"[yellow]lint[/yellow] {issue}")
    console.print(f"[green]spec[/green] {pp.id} — {len(pp.clauses)} clauses")

    try:
        result = asyncio.run(
            run_campaign(
                cfg,
                spec_path=spec,
                through=through_tier,
                use_divergence=True,
                diverge_cells=cells,
                diverge_per_cell=per_cell,
            )
        )
    except KeyboardInterrupt:
        console.print("[yellow]interrupted[/yellow] 进行中的轮次可在看板点「停止」后删除")
        raise typer.Exit(code=130) from None
    campaign_id = result["campaign_id"]
    dv = result.get("divergence") or {}
    console.print(
        f"[green]diverge[/green] {dv.get('n_cells', '?')} cells → "
        f"{dv.get('generated', '?')} ideas → {result['generated']} after dedup"
    )
    if result.get("stopped"):
        console.print(
            f"[yellow]stopped[/yellow] campaign {campaign_id} — 看板可删除该轮"
        )
        return
    _print_acc_notice(result)
    console.print(
        f"[green]funnel[/green] {campaign_id} passed={result['passed']} "
        f"failed={result['failed']} active={result['active']} "
        f"through={result.get('through', through)}"
    )

    out.mkdir(parents=True, exist_ok=True)
    report = write_report(cfg, campaign_id=campaign_id, out=out / f"REPORT-{campaign_id}.md")
    console.print(f"[green]report[/green] {report}")

    if not patent:
        return

    from archzero.patent import PatentDepsMissing
    from archzero.patent.disclosure import build_disclosure, disclosure_markdown
    from archzero.store.db import Store

    store = Store(cfg.db_path)
    pool = store.list_candidates(campaign_id=campaign_id)
    survivors = [c for c in pool if c.hard_passed(through_tier)] or pool
    for cand in survivors[:patent_top]:
        disc = asyncio.run(build_disclosure(cfg, cand, problem=pp))
        stem = out / f"patent-{cand.id}"
        stem.with_suffix(".md").write_text(
            disclosure_markdown(disc), encoding="utf-8"
        )
        stem.with_suffix(".json").write_text(disc.to_json(), encoding="utf-8")
        console.print(f"[green]disclosure[/green] {stem.with_suffix('.md')}")
        from archzero.patent.pptx_render import render_deck

        try:
            console.print(
                f"[green]deck[/green] {render_deck(cfg, disc, stem.with_suffix('.pptx'))}"
            )
        except PatentDepsMissing as exc:
            console.print(f"[yellow]skipped pptx[/yellow] {exc}")


@app.command("reproduce")
def reproduce_cmd(
    ctx: typer.Context,
    bundle: Path = typer.Argument(..., exists=True, help="Exported bundle directory"),
) -> None:
    """Verify a reproducibility bundle and replay stub tier gates offline."""
    from archzero.reproduce import reproduce_bundle

    cfg = _cfg(ctx.obj.get("config_path"))
    result = reproduce_bundle(cfg, bundle)
    console.print(f"[green]reproduce[/green] {result}")


@app.command("e2e")
def e2e_cmd(
    ctx: typer.Context,
    spec: Path = typer.Option(
        Path("specs/demo.md"), "--spec", exists=True, help="Problem package"
    ),
    through: str = typer.Option(
        "tier5", "--through", help="End tier (default tier5; tier6 reserved)"
    ),
    offline: bool = typer.Option(
        True, "--offline/--online", help="Use seed-demo style offline path when possible"
    ),
) -> None:
    """End-to-end demo: one candidate from spec through Tier5 (Tier6 Planned)."""
    from archzero.e2e import run_e2e

    cfg = _cfg(ctx.obj.get("config_path"))
    try:
        through_tier = Tier(through)
    except ValueError as e:
        raise typer.BadParameter(f"unknown tier {through}") from e
    result = asyncio.run(run_e2e(cfg, spec_path=spec, through=through_tier, offline=offline))
    console.print(f"[green]e2e[/green] {result}")


@app.command("report")
def report_cmd(
    ctx: typer.Context,
    campaign: Optional[str] = typer.Option(None, "--campaign"),
    out: Path = typer.Option(Path("report.md"), "--out", "-o"),
) -> None:
    """Emit weekly-style funnel report (throughput, failures, usage pools)."""
    from archzero.report.weekly import write_report

    cfg = _cfg(ctx.obj.get("config_path"))
    path = write_report(cfg, campaign_id=campaign, out=out)
    console.print(f"[green]wrote[/green] {path}")


@app.command("seed-demo")
def seed_demo_cmd(
    ctx: typer.Context,
    force: bool = typer.Option(
        False, "--force", help="Create another demo campaign even if one exists"
    ),
) -> None:
    """Seed offline demo campaigns (no LLM) so the funnel UI has sample data.

    Cache (gradable), NoC and dataflow (measurable, report-only), and wafer
    yield/thermal (still refused). Hop latency and die-to-die bandwidth are
    now report-only — the honesty contract is visible before an API key.
    """
    from archzero.demo_seed import (
        seed_acc_refusal_campaign,
        seed_dataflow_report_campaign,
        seed_demo_campaign,
        seed_noc_report_campaign,
    )

    cfg = _cfg(ctx.obj.get("config_path"))
    result = seed_demo_campaign(cfg, force=force)
    if result["created"]:
        console.print(
            f"[green]seeded[/green] campaign {result['campaign_id']} "
            f"({result['n_candidates']} candidates)"
        )
    else:
        console.print(
            f"[yellow]exists[/yellow] campaign {result['campaign_id']} — {result['note']}"
        )

    noc = seed_noc_report_campaign(cfg, force=force)
    if noc.get("campaign_id"):
        if noc["created"]:
            console.print(
                f"[green]seeded[/green] campaign {noc['campaign_id']} "
                f"({noc['n_candidates']} NoC candidates, report-only) — "
                f"解析模型给出 p99/goodput，规范未给门限故不裁决"
            )
        else:
            console.print(
                f"[yellow]exists[/yellow] campaign {noc['campaign_id']} — {noc['note']}"
            )

    dataflow = seed_dataflow_report_campaign(cfg, force=force)
    if dataflow.get("campaign_id"):
        if dataflow["created"]:
            console.print(
                f"[green]seeded[/green] campaign {dataflow['campaign_id']} "
                f"({dataflow['n_candidates']} dataflow candidates, report-only) — "
                f"解析模型给出 PE 利用率 / SRAM 访存，规范未给门限故不裁决"
            )
        else:
            console.print(
                f"[yellow]exists[/yellow] campaign {dataflow['campaign_id']} — "
                f"{dataflow['note']}"
            )

    refusal = seed_acc_refusal_campaign(cfg, force=force)
    if refusal.get("campaign_id"):
        if refusal["created"]:
            console.print(
                f"[green]seeded[/green] campaign {refusal['campaign_id']} "
                f"（晶圆级良率/热密度，封顶 {refusal.get('through')}）— "
                f"演示漏斗如何拒判仍无评估器的指标"
            )
        else:
            console.print(
                f"[yellow]exists[/yellow] campaign {refusal['campaign_id']} — "
                f"{refusal['note']}"
            )

    console.print(
        f"Inspect: [bold]archzero status {result['campaign_id']}[/bold]  ·  "
        f"[bold]archzero ui[/bold]"
    )


@app.command("doctor")
def doctor_cmd(
    ctx: typer.Context,
) -> None:
    """Check API key, personas, sim backend, and other run prerequisites."""
    from archzero.doctor import run_doctor

    cfg = _cfg(ctx.obj.get("config_path"))
    checks = run_doctor(cfg)
    table = Table(title="ArchZero doctor")
    table.add_column("check")
    table.add_column("ok")
    table.add_column("detail")
    hard_fail = False
    for c in checks:
        mark = "[green]yes[/green]" if c.ok else "[red]no[/red]"
        if not c.ok and c.severity == "error":
            hard_fail = True
        table.add_row(c.name, mark, c.detail)
    console.print(table)
    if not any(c.name == "CURSOR_API_KEY" and c.ok for c in checks):
        console.print(
            "[yellow]No API key[/yellow] — live LLM runs are blocked, but you can "
            "explore now:\n"
            "  [bold]archzero seed-demo && archzero ui[/bold]   离线看板\n"
            "  [bold]archzero acc specs/demo.md[/bold]           漏斗会按什么门限评判\n"
            "  [bold]archzero e2e --offline[/bold]               FakeLLM 走完 Tier0–5"
        )
    if hard_fail:
        console.print(
            "[yellow]Fix errors above before running a live campaign "
            "(stub-only / offline inspect commands still work).[/yellow]"
        )
        raise typer.Exit(code=1)


@app.command("campaigns")
def campaigns_cmd(
    ctx: typer.Context,
) -> None:
    """List Idea Factory campaigns and candidate counts."""
    from archzero.store.db import Store

    cfg = _cfg(ctx.obj.get("config_path"))
    store = Store(cfg.db_path)
    camps = store.list_campaigns()
    if not camps:
        console.print("[dim]No campaigns yet. Try:[/dim] archzero run --spec specs/demo.md")
        return
    table = Table(title="Campaigns")
    table.add_column("id")
    table.add_column("name")
    table.add_column("status")
    table.add_column("through")
    table.add_column("candidates")
    for c in camps:
        n = len(store.list_candidates(campaign_id=c.id))
        table.add_row(c.id, c.name, c.status, c.through_tier.value, str(n))
    console.print(table)


@app.command("status")
def status_cmd(
    ctx: typer.Context,
    campaign: str = typer.Argument(..., help="Campaign id"),
) -> None:
    """Show funnel throughput for one campaign (researcher snapshot)."""
    from archzero.models import Tier, Verdict
    from archzero.store.db import Store

    cfg = _cfg(ctx.obj.get("config_path"))
    store = Store(cfg.db_path)
    camp = store.get_campaign(campaign)
    if not camp:
        console.print(f"[red]unknown campaign[/red] {campaign}")
        raise typer.Exit(code=1)
    cands = store.list_candidates(campaign_id=campaign)
    console.print(
        f"[bold]{camp.name}[/bold]  id={camp.id}  status={camp.status}  "
        f"through={camp.through_tier.value}  candidates={len(cands)}"
    )
    table = Table(title="Funnel")
    table.add_column("tier")
    table.add_column("entered", justify="right")
    table.add_column("passed", justify="right")
    table.add_column("failed", justify="right")
    for tier in Tier:
        entered = passed = failed = 0
        for c in cands:
            for tr in c.tier_history:
                if tr.tier != tier:
                    continue
                entered += 1
                if tr.verdict == Verdict.PASS:
                    passed += 1
                elif tr.verdict == Verdict.FAIL:
                    failed += 1
        table.add_row(tier.value, str(entered), str(passed), str(failed))
    console.print(table)
    from archzero.sim.headlines import headlines_text, metrics_domain

    if cands:
        ctable = Table(title="Candidates")
        ctable.add_column("id")
        ctable.add_column("title")
        ctable.add_column("family")
        ctable.add_column("domain")
        ctable.add_column("headlines")
        ctable.add_column("status")
        for c in cands:
            ctable.add_row(
                c.id,
                (c.title or "")[:40],
                c.family or "",
                metrics_domain(c.metrics, c.family),
                headlines_text(c.metrics, family=c.family) or "—",
                c.status,
            )
        console.print(ctable)
    usage = store.usage_totals(campaign)
    if usage:
        console.print(f"usage pools: {usage}")


@app.command("stop")
def stop_cmd(
    ctx: typer.Context,
    campaign: str = typer.Argument(..., help="Campaign id"),
) -> None:
    """Ask a running campaign to halt; the funnel exits at the next checkpoint."""
    from archzero.store.db import Store

    cfg = _cfg(ctx.obj.get("config_path"))
    store = Store(cfg.db_path)
    camp = store.stop_campaign(campaign)
    if camp is None:
        console.print(f"[red]unknown campaign[/red] {campaign}")
        raise typer.Exit(code=1)
    console.print(f"[yellow]stop[/yellow] {camp.id}  status={camp.status}")


@app.command("rm-campaign")
def rm_campaign_cmd(
    ctx: typer.Context,
    campaign: str = typer.Argument(..., help="Campaign id"),
) -> None:
    """Delete a stopped / done / failed campaign and its candidates."""
    from archzero.store.db import Store

    cfg = _cfg(ctx.obj.get("config_path"))
    store = Store(cfg.db_path)
    try:
        store.delete_campaign(campaign)
    except KeyError:
        console.print(f"[red]unknown campaign[/red] {campaign}")
        raise typer.Exit(code=1)
    except ValueError as exc:
        console.print(f"[red]cannot delete[/red] {exc}")
        raise typer.Exit(code=1)
    console.print(f"[green]deleted[/green] campaign {campaign}")


@app.command("show")
def show_cmd(
    ctx: typer.Context,
    candidate_id: str = typer.Argument(..., help="Candidate id"),
) -> None:
    """Show one candidate: mechanism, tier history, failures, clause refs."""
    from archzero.store.db import Store

    cfg = _cfg(ctx.obj.get("config_path"))
    store = Store(cfg.db_path)
    c = store.get_candidate(candidate_id)
    if not c:
        console.print(f"[red]unknown candidate[/red] {candidate_id}")
        raise typer.Exit(code=1)
    console.print(f"[bold]{c.title}[/bold]  ({c.family})  status={c.status}")
    console.print(f"id={c.id}  problem={c.problem_id}")
    if c.clause_refs:
        console.print("clauses: " + ", ".join(c.clause_refs))
    from archzero.sim.headlines import headlines_text, metrics_domain

    domain = metrics_domain(c.metrics, c.family)
    hl = headlines_text(c.metrics, family=c.family)
    console.print(f"domain={domain}")
    if hl:
        console.print(f"headlines: {hl}")
    console.print("\n[bold]Mechanism[/bold]\n")
    console.print(c.mechanism[:4000] + ("…" if len(c.mechanism) > 4000 else ""))
    if c.tier_history:
        table = Table(title="Tier history")
        table.add_column("tier")
        table.add_column("verdict")
        table.add_column("tier score")
        table.add_column("summary")
        for t in c.tier_history:
            table.add_row(
                t.tier.value,
                t.verdict.value,
                "" if t.score is None else f"{t.score:.3f}",
                (t.summary or "")[:120],
            )
        console.print(table)
    if c.failures:
        console.print("\n[bold]Failures[/bold]")
        for f in c.failures:
            console.print(f"  [{f.tier.value}/{f.kind.value}] {f.message}")


@app.command("ui")
def ui_cmd(
    ctx: typer.Context,
    host: str = typer.Option("127.0.0.1", "--host"),
    port: int = typer.Option(8787, "--port"),
) -> None:
    """Open the local researcher dashboard (funnel / campaigns / candidates)."""
    from archzero.web.app import serve

    cfg_path = ctx.obj.get("config_path")
    serve(host=host, port=port, config=cfg_path)


@app.command("new-spec")
def new_spec_cmd(
    ctx: typer.Context,
    title: str = typer.Option(..., "--title", help="Problem title"),
    workload: str = typer.Option(..., "--workload", help="Workload / suite description"),
    symptom: str = typer.Option(..., "--symptom", help="Observed bottleneck / symptom"),
    constraint: str = typer.Option(..., "--constraint", help="Hardware / resource constraint"),
    domain: str = typer.Option(
        "cache",
        "--domain",
        help="Clause template: cache | cpu | memory | noc | dataflow | wafer",
    ),
    out: Path = typer.Option(Path("specs"), "--out", "-o", help="Output directory"),
) -> None:
    """Scaffold an NDF-lite problem package from researcher fields, then lint."""
    from archzero.spec.lint import lint_acceptance, lint_package
    from archzero.spec.ndf import load_problem_package
    from archzero.spec.wizard import (
        DOMAIN_ALIASES,
        TEMPLATES,
        resolve_scaffold_domain,
        scaffold_problem,
    )

    resolved = resolve_scaffold_domain(domain)
    if resolved not in TEMPLATES:
        expected = ", ".join(sorted({*TEMPLATES, *DOMAIN_ALIASES}))
        raise typer.BadParameter(
            f"unknown domain {domain!r}; expected one of {expected}"
        )
    domain = resolved
    path = scaffold_problem(
        title=title,
        workload=workload,
        symptom=symptom,
        constraint=constraint,
        domain=domain,
        out_dir=out,
    )
    pp = load_problem_package(path)
    issues = lint_package(pp)
    console.print(f"[green]wrote[/green] {path} [dim](domain={domain})[/dim]")
    if issues:
        for i in issues:
            console.print(f"[yellow]lint[/yellow] {i}")
        raise typer.Exit(code=1)
    console.print(f"[green]lint ok[/green] ({len(pp.clauses)} clauses) — {pp.id}")
    for i in lint_acceptance(pp):
        console.print(f"[yellow]acc[/yellow] {i}")
    console.print(f"[dim]漏斗将按什么门限评判：archzero acc {path}[/dim]")


@app.command("patent")
def patent_cmd(
    ctx: typer.Context,
    candidate: Optional[str] = typer.Option(
        None, "--candidate", help="Candidate id (or use --campaign --top)"
    ),
    campaign: Optional[str] = typer.Option(
        None, "--campaign", help="Draft for the top survivors of a campaign"
    ),
    top: int = typer.Option(1, "--top", help="How many campaign survivors to draft"),
    out: Path = typer.Option(Path("patents"), "--out", "-o", help="Output directory"),
    search: bool = typer.Option(
        True, "--search/--no-search", help="Query arXiv / Semantic Scholar for prior art"
    ),
    md_only: bool = typer.Option(
        False, "--md-only", help="Markdown disclosure only (no python-pptx needed)"
    ),
) -> None:
    """Optional: draft a six-section disclosure and Huawei review deck.

    PPTX rendering needs the patent extra: uv sync --extra patent
    """
    from archzero.patent import PatentDepsMissing
    from archzero.patent.disclosure import build_disclosure, disclosure_markdown
    from archzero.store.db import Store

    cfg = _cfg(ctx.obj.get("config_path"))
    store = Store(cfg.db_path)

    targets: list = []
    if candidate:
        found = store.get_candidate(candidate)
        if found is None:
            raise typer.BadParameter(f"unknown candidate {candidate}")
        targets = [found]
    elif campaign:
        pool = store.list_candidates(campaign_id=campaign)
        survivors = [c for c in pool if c.status not in ("killed", "rejected")]
        targets = (survivors or pool)[:top]
        if not targets:
            raise typer.BadParameter(f"campaign {campaign} has no candidates")
    else:
        raise typer.BadParameter("one of --candidate or --campaign is required")

    out.mkdir(parents=True, exist_ok=True)
    for cand in targets:
        problem = store.get_problem(cand.problem_id)
        disc = asyncio.run(
            build_disclosure(cfg, cand, problem=problem, search=search)
        )
        stem = out / f"patent-{cand.id}"
        md_path = stem.with_suffix(".md")
        md_path.write_text(disclosure_markdown(disc), encoding="utf-8")
        stem.with_suffix(".json").write_text(disc.to_json(), encoding="utf-8")
        console.print(f"[green]disclosure[/green] {md_path}")

        if md_only:
            continue
        from archzero.patent.pptx_render import render_deck

        try:
            deck = render_deck(cfg, disc, stem.with_suffix(".pptx"))
        except PatentDepsMissing as exc:
            console.print(f"[yellow]skipped pptx[/yellow] {exc}")
            continue
        console.print(f"[green]deck[/green] {deck}")

        if disc.warnings:
            for w in disc.warnings:
                console.print(f"[yellow]warn[/yellow] {w}")
        if not disc.prior_art.verified:
            console.print(
                f"[yellow]prior-art[/yellow] {disc.prior_art.retrieval_status} — "
                "检索结果未经核实，评审前请人工补检索"
            )


@app.command("export")
def export_cmd(
    ctx: typer.Context,
    campaign: str = typer.Option(..., "--campaign", help="Campaign id"),
    out: Path = typer.Option(Path("bundles"), "--out", "-o", help="Bundle parent directory"),
) -> None:
    """Export a campaign as a reproducibility bundle (manifest, problem, candidates, report)."""
    from archzero.export_bundle import export_campaign_bundle

    cfg = _cfg(ctx.obj.get("config_path"))
    root = export_campaign_bundle(cfg, campaign, out)
    console.print(f"[green]exported[/green] {root}")


@app.command("compare")
def compare_cmd(
    ctx: typer.Context,
    a: str = typer.Argument(..., help="Campaign A id"),
    b: str = typer.Argument(..., help="Campaign B id"),
    out: Optional[Path] = typer.Option(None, "--out", "-o", help="Write markdown report"),
) -> None:
    """Compare funnel throughput and failure taxonomy of two campaigns."""
    from archzero.compare import compare_campaigns, format_compare_text

    cfg = _cfg(ctx.obj.get("config_path"))
    data = compare_campaigns(cfg, a, b)
    text = format_compare_text(data)
    if out:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
        console.print(f"[green]wrote[/green] {out}")
    else:
        console.print(text)


@app.command("next-questions")
def next_questions_cmd(
    ctx: typer.Context,
    campaign: str = typer.Option(..., "--campaign", help="Campaign id"),
    out: Path = typer.Option(
        Path("next_questions.md"), "--out", "-o", help="Markdown output path"
    ),
) -> None:
    """Derive next Generation open questions from structured failures (offline Feedback stand-in)."""
    from archzero.next_questions import questions_from_campaign, write_questions_markdown

    cfg = _cfg(ctx.obj.get("config_path"))
    payload = questions_from_campaign(cfg, campaign)
    path = write_questions_markdown(payload, out)
    console.print(
        f"[green]wrote[/green] {path}  ({len(payload['open_questions'])} questions "
        f"from {payload['n_failures']} failures)"
    )
    for q in payload["open_questions"][:5]:
        console.print(f"  • {q}")


@app.command("version")
def version_cmd() -> None:
    console.print(__version__)



@app.command("corpus")
def corpus_status_cmd(
    ctx: typer.Context,
    path: Optional[Path] = typer.Option(
        None, "--path", help="Corpus root (default: ./corpus)"
    ),
) -> None:
    """Show clean-room corpus scaffold status (no invented success rates)."""
    from archzero.corpus.status import corpus_status

    st = corpus_status(path)
    if not st.get("ok"):
        console.print(f"[red]{st.get('message')}[/red]")
        raise typer.Exit(1)
    console.print(f"[bold]Corpus[/bold] {st['path']}")
    console.print(f"status: {st['status']}  coverage: {st['coverage']}")
    console.print(f"evaluated: {st['evaluated']}  success_rate: {st['success_rate']}")
    console.print(f"[dim]{st['disclaimer']}[/dim]")
    if st.get("entry_ids"):
        console.print("entries: " + ", ".join(str(x) for x in st["entry_ids"]))



@app.command("corpus-add-pdf")
def corpus_add_pdf_cmd(
    ctx: typer.Context,
    entry_id: str = typer.Argument(..., help="Corpus entry id"),
    pdf: Path = typer.Argument(..., exists=True, readable=True, help="Path to PDF"),
    title: Optional[str] = typer.Option(None, "--title"),
    family: str = typer.Option("unclassified", "--family"),
    label: Optional[str] = typer.Option(
        None, "--label", help="cleanroom label: reproduce|equivalent|alternative|defective"
    ),
    corpus_path: Optional[Path] = typer.Option(None, "--corpus", help="Corpus root"),
) -> None:
    """Register a real paper PDF into the corpus scaffold (does not invent success rates)."""
    from archzero.corpus.ingest import add_paper_pdf

    try:
        st = add_paper_pdf(
            entry_id=entry_id,
            pdf_path=pdf,
            title=title,
            family=family,
            cleanroom_label=label,
            corpus_root=corpus_path,
        )
    except Exception as exc:  # noqa: BLE001
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1) from exc
    console.print(f"[green]ok[/green] entry={st['entry_id']} pdf={st['pdf']}")
    console.print(f"status={st['status']} label={st.get('cleanroom_label')}")
    console.print(f"[dim]{st['message']}[/dim]")



@app.command("corpus-import-wiki")
def corpus_import_wiki_cmd(
    ctx: typer.Context,
    wiki: Path = typer.Argument(..., exists=True, file_okay=False, help="Wiki repo root"),
    corpus_path: Optional[Path] = typer.Option(None, "--corpus"),
    limit: Optional[int] = typer.Option(None, "--limit"),
    family: str = typer.Option("unclassified", "--family"),
    dry_run: bool = typer.Option(False, "--dry-run"),
) -> None:
    """Import raw PDFs from an OKF/LLM wiki into the corpus (summaries skipped)."""
    from archzero.corpus.wiki_import import import_wiki_pdfs

    data = import_wiki_pdfs(
        wiki,
        corpus_root=corpus_path,
        limit=limit,
        family=family,
        dry_run=dry_run,
    )
    console.print(
        f"[bold]Wiki→corpus[/bold] found={data['n_found']} imported={data['n_imported']} "
        f"dry_run={data['dry_run']}"
    )
    console.print(f"[dim]{data['disclaimer']}[/dim]")
    for r in data.get("results") or []:
        if r.get("ok"):
            console.print(f"  [green]{r.get('entry_id')}[/green] {r.get('pdf') or r.get('source')}")
        else:
            console.print(f"  [red]{r.get('entry_id')}[/red] {r.get('error')}")


@app.command("corpus-eval-offline")
def corpus_eval_offline_cmd(
    ctx: typer.Context,
    corpus_path: Optional[Path] = typer.Option(None, "--corpus"),
    through: str = typer.Option("tier2", "--through"),
    limit: Optional[int] = typer.Option(None, "--limit"),
    only_pdf: bool = typer.Option(False, "--only-pdf"),
) -> None:
    """Batch-evaluate corpus entries offline with FakeLLM (no invented success rates)."""
    cfg = _cfg(ctx.obj.get("config_path"))
    from archzero.corpus.batch_eval import evaluate_corpus_batch
    from archzero.models import Tier

    try:
        th = Tier(through)
    except ValueError as exc:
        console.print(f"[red]bad --through[/red]: {through}")
        raise typer.Exit(1) from exc

    async def _run():
        return await evaluate_corpus_batch(
            cfg,
            corpus_root=corpus_path,
            through=th,
            limit=limit,
            only_with_pdf=only_pdf,
        )

    data = asyncio.run(_run())
    if not data.get("ok"):
        console.print(f"[red]{data.get('error')}[/red]")
        raise typer.Exit(1)
    console.print(
        f"[bold]Corpus offline batch[/bold] entries={data['n_entries']} "
        f"pass={data['n_pass_offline']} success_rate={data['success_rate']}"
    )
    console.print(f"[dim]{data['disclaimer']}[/dim]")
    for r in data.get("results") or []:
        tone = "green" if r.get("last_verdict") == "pass" else "yellow"
        console.print(
            f"  [{tone}]{r.get('entry_id')}[/{tone}] "
            f"{r.get('last_tier')}/{r.get('last_verdict')} "
            f"pdf_real={r.get('pdf_real')}"
        )


if __name__ == "__main__":
    app()
