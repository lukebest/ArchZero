"""Optional OpenEvolve adapter via OpenAI-compatible Cursor shim."""

from __future__ import annotations

import os
import subprocess
import sys
from typing import Any

from archzero.config import ROOT, FactoryConfig
from archzero.evolve.backend import EvolutionBackend
from archzero.evolve.mapelites import MapElitesBackend
from archzero.llm.shim import OpenAIShim
from archzero.models import Candidate
from archzero.sim.families import CACHE, DATAFLOW, NOC, WAFER, family_domain

EVAL_KEY = {
    NOC: "goodput",
    DATAFLOW: "pe_utilization",
    WAFER: "die_to_die_bw",
    CACHE: "miss_reduction",
}

_KNOWN_DOMAINS = {CACHE, NOC, DATAFLOW, WAFER, "generic"}


def resolve_evolve_domain(domain: str, family: str | None = None) -> str:
    """Map a possibly-generic domain onto a score key's domain.

    Unknown names must not silently become ``miss_reduction``.
    """
    if domain in EVAL_KEY:
        return domain
    resolved = family_domain(family)
    if domain and domain not in _KNOWN_DOMAINS and resolved == CACHE:
        raise ValueError(
            f"unknown evolve domain {domain!r}; refusing to default to miss_reduction"
        )
    return resolved


def evolve_domain(
    cfg: FactoryConfig, campaign_id: str | None, seeds: list[Candidate]
) -> str:
    """Parse problem ACC domain if campaign exists; else family; else cache."""
    if campaign_id:
        from archzero.spec.acc_parse import parse_acceptance_thresholds
        from archzero.store.db import Store

        store = Store(cfg.db_path)
        camp = store.get_campaign(campaign_id)
        if camp:
            problem = store.get_problem(camp.problem_id)
            if problem is not None:
                domain = parse_acceptance_thresholds(problem).domain
                if domain in {NOC, DATAFLOW, WAFER, CACHE}:
                    return domain
    if seeds:
        return family_domain(seeds[0].family)
    return CACHE


def seed_program_sources(domain: str, family: str) -> tuple[str, str]:
    """Return (initial_program.py, evaluator.py) text shaped for the domain."""
    resolved = resolve_evolve_domain(domain, family)
    key = EVAL_KEY[resolved]
    program = (
        "from archzero.evolve.domains import score_variant\n"
        "\n"
        "def run_model():\n"
        f"    return score_variant({resolved!r}, {family!r}, {{}})\n"
    )
    evaluator = (
        "def evaluate(program_path):\n"
        "    import runpy\n"
        "    ns = runpy.run_path(program_path)\n"
        "    m = ns['run_model']()\n"
        f"    return float(m.get({key!r}) or 0)\n"
    )
    return program, evaluator


class OpenEvolveBackend(EvolutionBackend):
    name = "openevolve"

    async def run(
        self,
        cfg: FactoryConfig,
        seeds: list[Candidate],
        *,
        generations: int,
        campaign_id: str | None = None,
    ) -> dict[str, Any]:
        oe_root = ROOT / "vendor" / "openevolve"
        if not oe_root.is_dir():
            # Fallback to built-in MAP-Elites if submodule not present
            alt = MapElitesBackend()
            result = await alt.run(
                cfg, seeds, generations=generations, campaign_id=campaign_id
            )
            result["note"] = "openevolve missing; used mapelites"
            return result

        shim = OpenAIShim(cfg)
        base_url = shim.start()
        try:
            seed = seeds[0]
            domain = evolve_domain(cfg, campaign_id, seeds)
            work = cfg.scratch_dir / f"oe_{campaign_id or 'adhoc'}"
            work.mkdir(parents=True, exist_ok=True)
            prog = work / "initial_program.py"
            eval_prog, evaluator_src = seed_program_sources(domain, seed.family or "")
            prog.write_text(eval_prog, encoding="utf-8")
            evaluator = work / "evaluator.py"
            evaluator.write_text(evaluator_src, encoding="utf-8")
            env = os.environ.copy()
            env["OPENAI_API_BASE"] = base_url
            env["OPENAI_BASE_URL"] = base_url
            env["OPENAI_API_KEY"] = "cursor-shim"
            # Best-effort: many OE entrypoints differ; record attempt
            cmd = [
                sys.executable,
                "-c",
                (
                    "print('openevolve adapter: shim live at ' + "
                    f"'{base_url}; integrate OE CLI when vendored')"
                ),
            ]
            proc = subprocess.run(
                cmd, cwd=str(oe_root), env=env, capture_output=True, text=True
            )
            # Also run mapelites as the real search until OE wiring is complete
            alt = MapElitesBackend()
            result = await alt.run(
                cfg, seeds, generations=generations, campaign_id=campaign_id
            )
            result["openevolve_shim"] = base_url
            result["openevolve_stdout"] = proc.stdout
            result["backend"] = "openevolve+mapelites-bridge"
            result["evolve_domain"] = domain
            return result
        finally:
            shim.stop()
