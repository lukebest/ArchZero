"""ArchZero CLI — models | spec | read | ideate | run | evolve | report."""

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
        None, "--personas", help="Comma-separated persona stems under Gauntlet/personas"
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
    spec: Path = typer.Option(..., "--spec", exists=True, help="Problem package"),
    pdf: Optional[Path] = typer.Option(None, "--pdf", exists=True),
    through: str = typer.Option("tier2", "--through", help="Stop after this tier"),
    name: Optional[str] = typer.Option(None, "--name"),
    seed_dir: Optional[Path] = typer.Option(
        None, "--seed-dir", help="Directory of candidate markdown files"
    ),
    n_generate: int = typer.Option(10, "--n", help="Candidates to generate if no seed"),
) -> None:
    """Run the evaluation funnel on generated or seeded candidates."""
    from archzero.funnel.pipeline import run_campaign

    cfg = _cfg(ctx.obj.get("config_path"))
    try:
        through_tier = Tier(through)
    except ValueError as e:
        raise typer.BadParameter(f"unknown tier {through}") from e
    result = asyncio.run(
        run_campaign(
            cfg,
            spec_path=spec,
            pdf=pdf,
            through=through_tier,
            name=name,
            seed_dir=seed_dir,
            n_generate=n_generate,
        )
    )
    console.print(
        f"[green]campaign[/green] {result['campaign_id']} "
        f"passed={result['passed']} failed={result['failed']} "
        f"through={through}"
    )


@app.command("evolve")
def evolve_cmd(
    ctx: typer.Context,
    campaign: str = typer.Option(..., "--campaign", help="Campaign id"),
    generations: Optional[int] = typer.Option(None, "--generations"),
) -> None:
    """Run evolutionary search on candidates that reached Tier2+."""
    from archzero.evolve.mapelites import run_evolution

    cfg = _cfg(ctx.obj.get("config_path"))
    gens = generations or cfg.evolve.generations
    summary = asyncio.run(run_evolution(cfg, campaign_id=campaign, generations=gens))
    console.print(f"[green]evolve[/green] {summary}")


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


@app.command("version")
def version_cmd() -> None:
    console.print(__version__)


if __name__ == "__main__":
    app()
