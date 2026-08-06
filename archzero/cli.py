"""ArchZero CLI — models | spec | new-spec | read | ideate | run | evolve | report | export."""

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
    help="Idea Factory for computer architecture (telemetry deferred).",
    no_args_is_help=True,
)
console = Console()


def _cfg(config: Optional[Path] = None):
    return load_config(config)


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
    from archzero.spec.lint import lint_package
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
    if register:
        store = Store(cfg.db_path)
        store.save_problem(pp)
        console.print(f"[green]registered[/green] problem {pp.id} — {pp.title}")
    else:
        console.print(f"parsed {pp.title} ({len(pp.clauses)} clauses)")


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
        )
    )
    console.print(
        f"[green]campaign[/green] {result['campaign_id']} "
        f"passed={result['passed']} failed={result['failed']} "
        f"through={through}"
    )
    if result.get("frontier"):
        fr = result["frontier"]
        console.print(
            f"[green]frontier[/green] paradigms={fr.get('n_paradigm_candidates')} "
            f"kinds={fr.get('kinds')} report={fr.get('report_path')}"
        )
    if result.get("auto_rounds"):
        console.print(f"[green]auto-rounds[/green] {len(result['auto_rounds'])}")


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
    """Seed an offline demo campaign (no LLM) so the funnel UI has sample data."""
    from archzero.demo_seed import seed_demo_campaign

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
    usage = store.usage_totals(campaign)
    if usage:
        console.print(f"usage pools: {usage}")


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
    console.print("\n[bold]Mechanism[/bold]\n")
    console.print(c.mechanism[:4000] + ("…" if len(c.mechanism) > 4000 else ""))
    if c.tier_history:
        table = Table(title="Tier history")
        table.add_column("tier")
        table.add_column("verdict")
        table.add_column("score")
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
    out: Path = typer.Option(Path("specs"), "--out", "-o", help="Output directory"),
) -> None:
    """Scaffold an NDF-lite problem package from researcher fields, then lint."""
    from archzero.spec.lint import lint_package
    from archzero.spec.ndf import load_problem_package
    from archzero.spec.wizard import scaffold_problem

    path = scaffold_problem(
        title=title,
        workload=workload,
        symptom=symptom,
        constraint=constraint,
        out_dir=out,
    )
    pp = load_problem_package(path)
    issues = lint_package(pp)
    console.print(f"[green]wrote[/green] {path}")
    if issues:
        for i in issues:
            console.print(f"[yellow]lint[/yellow] {i}")
        raise typer.Exit(code=1)
    console.print(f"[green]lint ok[/green] ({len(pp.clauses)} clauses) — {pp.id}")


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
