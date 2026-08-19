"""OpenEvolve adapter: vendored tree + OpenAI-compatible Cursor shim."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml

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

OE_RUNNER = "openevolve-run.py"


def openevolve_root(cfg: FactoryConfig | None = None) -> Path:
    if cfg is not None and cfg.evolve.openevolve_root:
        return Path(cfg.evolve.openevolve_root)
    return ROOT / "vendor" / "openevolve"


def openevolve_available(cfg: FactoryConfig | None = None) -> bool:
    root = openevolve_root(cfg)
    return (root / OE_RUNNER).is_file()


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
        "# EVOLVE-BLOCK-START\n"
        "from archzero.evolve.domains import score_variant\n"
        "\n"
        "def run_model():\n"
        f"    return score_variant({resolved!r}, {family!r}, {{}})\n"
        "# EVOLVE-BLOCK-END\n"
    )
    evaluator = (
        "def evaluate(program_path):\n"
        "    import runpy\n"
        "    ns = runpy.run_path(program_path)\n"
        "    m = ns['run_model']()\n"
        f"    score = float(m.get({key!r}) or 0)\n"
        f"    return {{'combined_score': score, {key!r}: score}}\n"
    )
    return program, evaluator


def write_oe_config(
    path: Path, *, api_base: str, model: str, iterations: int
) -> None:
    """Point OpenEvolve's OpenAI client at the Cursor shim."""
    data = {
        "max_iterations": max(1, iterations),
        "checkpoint_interval": max(1, iterations),
        "log_level": "INFO",
        "diff_based_evolution": True,
        "llm": {
            "models": [{"name": model, "weight": 1.0}],
            "evaluator_models": [{"name": model, "weight": 1.0}],
            "api_base": api_base,
            "api_key": "cursor-shim",
            "timeout": 180,
            "retries": 1,
            "retry_delay": 2,
        },
    }
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


def oe_command(
    *,
    oe_root: Path,
    program: Path,
    evaluator: Path,
    config: Path,
    output: Path,
    api_base: str,
    model: str,
    iterations: int,
) -> list[str]:
    return [
        sys.executable,
        str(oe_root / OE_RUNNER),
        str(program),
        str(evaluator),
        "--config",
        str(config),
        "--iterations",
        str(max(1, iterations)),
        "--api-base",
        api_base,
        "--primary-model",
        model,
        "--output",
        str(output),
    ]


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
        oe_root = openevolve_root(cfg)
        if not openevolve_available(cfg):
            alt = MapElitesBackend()
            result = await alt.run(
                cfg, seeds, generations=generations, campaign_id=campaign_id
            )
            result["note"] = "openevolve missing; used mapelites"
            return result

        if not seeds:
            return {"error": "no candidates to evolve", "backend": self.name}

        shim = OpenAIShim(cfg)
        base_url = shim.start()
        try:
            seed = seeds[0]
            domain = evolve_domain(cfg, campaign_id, seeds)
            work = cfg.scratch_dir / f"oe_{campaign_id or 'adhoc'}"
            work.mkdir(parents=True, exist_ok=True)
            prog = work / "initial_program.py"
            evaluator = work / "evaluator.py"
            cfg_path = work / "config.yaml"
            out_dir = work / "oe_out"
            program_src, evaluator_src = seed_program_sources(domain, seed.family or "")
            prog.write_text(program_src, encoding="utf-8")
            evaluator.write_text(evaluator_src, encoding="utf-8")
            model = cfg.pools.preferred_cursor
            write_oe_config(
                cfg_path, api_base=base_url, model=model, iterations=generations
            )
            env = os.environ.copy()
            env["OPENAI_API_BASE"] = base_url
            env["OPENAI_BASE_URL"] = base_url
            env["OPENAI_API_KEY"] = "cursor-shim"
            env["PYTHONPATH"] = os.pathsep.join(
                [str(oe_root), str(ROOT), env.get("PYTHONPATH", "")]
            )
            cmd = oe_command(
                oe_root=oe_root,
                program=prog,
                evaluator=evaluator,
                config=cfg_path,
                output=out_dir,
                api_base=base_url,
                model=model,
                iterations=generations,
            )
            timeout_s = max(180, int(generations) * 90)
            proc = subprocess.run(
                cmd,
                cwd=str(work),
                env=env,
                capture_output=True,
                text=True,
                timeout=timeout_s,
            )
            best = out_dir / "best" / "best_program.py"
            result: dict[str, Any] = {
                "backend": self.name,
                "evolve_domain": domain,
                "openevolve_shim": base_url,
                "openevolve_cmd": cmd,
                "returncode": proc.returncode,
                "openevolve_stdout": (proc.stdout or "")[-4000:],
                "openevolve_stderr": (proc.stderr or "")[-4000:],
                "best_program": str(best) if best.is_file() else None,
            }
            if proc.returncode != 0:
                result["note"] = "openevolve exited non-zero; see openevolve_stderr"
            if campaign_id and best.is_file():
                result["child_id"] = _save_best_child(
                    cfg, campaign_id, seed, best, generations
                )
            return result
        except subprocess.TimeoutExpired as exc:
            return {
                "backend": self.name,
                "error": f"openevolve timed out: {exc}",
                "openevolve_shim": base_url,
            }
        finally:
            shim.stop()


def _save_best_child(
    cfg: FactoryConfig,
    campaign_id: str,
    parent: Candidate,
    best: Path,
    generations: int,
) -> str:
    from archzero.store.db import Store

    code = best.read_text(encoding="utf-8")
    child = Candidate(
        problem_id=parent.problem_id,
        title=f"{parent.title} oe",
        mechanism=code[:8000],
        family=parent.family,
        parent_id=parent.id,
        clause_refs=list(parent.clause_refs),
        metrics={"evolved_gen": generations, "openevolve": True},
    )
    store = Store(cfg.db_path)
    store.save_candidate(child, campaign_id=campaign_id)
    info = best.with_name("best_program_info.json")
    if info.is_file():
        try:
            child.metrics["openevolve_info"] = json.loads(info.read_text(encoding="utf-8"))
            store.save_candidate(child, campaign_id=campaign_id)
        except json.JSONDecodeError:
            pass
    return child.id
