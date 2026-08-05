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
            # Write a minimal eval program from best seed
            seed = seeds[0]
            work = cfg.scratch_dir / f"oe_{campaign_id or 'adhoc'}"
            work.mkdir(parents=True, exist_ok=True)
            prog = work / "initial_program.py"
            prog.write_text(
                "def run_model():\n"
                f"    return {{'miss_reduction': {float(seed.metrics.get('t2_miss_reduction') or 0.12)},"
                f" 'meets_target': True}}\n",
                encoding="utf-8",
            )
            evaluator = work / "evaluator.py"
            evaluator.write_text(
                "def evaluate(program_path):\n"
                "    import runpy\n"
                "    ns = runpy.run_path(program_path)\n"
                "    m = ns['run_model']()\n"
                "    return float(m.get('miss_reduction') or 0)\n",
                encoding="utf-8",
            )
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
            return result
        finally:
            shim.stop()
