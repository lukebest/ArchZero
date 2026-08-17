"""Generate a mechanism-specific dedicated small simulator (source + self-test).

This is a template/codegen path toward the paper's Tier3 "dedicated simulator
per mechanism" — not cycle-accurate ChampSim, but real generated Python source
that can be audited and self-tested offline.
"""

from __future__ import annotations

import json
import math
import subprocess
import sys
import textwrap
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from archzero.sim.families import CACHE, DATAFLOW, NOC, WAFER, family_domain
from archzero.sim.mechanism_model import MechanismParams, infer_params


@dataclass
class GeneratedSim:
    family: str
    path: Path
    selftest_ok: bool
    metrics: dict[str, Any]
    log: str = ""


_PREFETCH_BODY = '''
def run_sim( knobs: dict ) -> dict:
    """Prefetch/filter event-model simulator (generated)."""
    entries = int(knobs.get("table_entries", {entries}))
    degree = int(knobs.get("prefetch_degree", {degree}))
    acc = float(knobs.get("filter_accuracy", {acc}))
    base = float(knobs.get("miss_reduction", {base}))
    extra_bw = float(knobs.get("extra_bw", {bw}))
    pollution = min(0.35, 0.04 * max(0, degree - 1))
    capacity = min(1.0, (entries.bit_length() - 1) / 10.0) if entries > 1 else 0.1
    reduction = max(0.0, min(0.9, base * acc * (1.0 - pollution) * (0.7 + 0.3 * capacity)))
    bw = max(0.0, extra_bw + 0.01 * max(0, degree - 2))
    return {{
        "evidence": "dedicated",
        "backend": "dedicated-prefetch",
        "family": "prefetch",
        "miss_reduction": reduction,
        "bw_delta_frac": bw,
        "area_mm2": float(knobs.get("area", 0.25)),
        "note": "generated dedicated prefetch/filter event model",
    }}
'''

_REPLACEMENT_BODY = '''
def run_sim( knobs: dict ) -> dict:
    """Replacement event-model simulator (generated)."""
    entries = int(knobs.get("table_entries", {entries}))
    hist = int(knobs.get("history_len", {hist}))
    base = float(knobs.get("miss_reduction", {base}))
    extra_bw = float(knobs.get("extra_bw", {bw}))
    hist_factor = min(1.0, hist / 16.0)
    table_factor = min(1.0, entries / 512.0)
    reduction = max(0.0, min(0.9, base * (0.55 + 0.45 * hist_factor * table_factor)))
    return {{
        "evidence": "dedicated",
        "backend": "dedicated-replacement",
        "family": "replacement",
        "miss_reduction": reduction,
        "bw_delta_frac": max(0.0, extra_bw * 0.5),
        "area_mm2": float(knobs.get("area", 0.25)),
        "note": "generated dedicated replacement event model",
    }}
'''

_BYPASS_BODY = '''
def run_sim( knobs: dict ) -> dict:
    """Bypass/writeback event-model simulator (generated)."""
    thr = float(knobs.get("bypass_threshold", {thr}))
    base = float(knobs.get("miss_reduction", {base}))
    extra_bw = float(knobs.get("extra_bw", {bw}))
    useful = min(1.0, max(0.0, thr))
    reduction = max(0.0, min(0.9, base * (0.4 + 0.6 * useful)))
    bw = max(0.0, extra_bw - 0.01 * useful)
    return {{
        "evidence": "dedicated",
        "backend": "dedicated-bypass",
        "family": "bypass",
        "miss_reduction": reduction,
        "bw_delta_frac": bw,
        "area_mm2": float(knobs.get("area", 0.25)),
        "note": "generated dedicated bypass event model",
    }}
'''

_GENERIC_BODY = '''
def run_sim( knobs: dict ) -> dict:
    """Generic mechanism event-model simulator (generated)."""
    base = float(knobs.get("miss_reduction", {base}))
    extra_bw = float(knobs.get("extra_bw", {bw}))
    reduction = max(0.0, min(0.9, base * 0.75))
    return {{
        "evidence": "dedicated",
        "backend": "dedicated-generic",
        "family": "{family}",
        "miss_reduction": reduction,
        "bw_delta_frac": extra_bw,
        "area_mm2": float(knobs.get("area", 0.25)),
        "note": "generated dedicated generic event model",
    }}
'''

_NOC_BODY = '''
def run_sim( knobs: dict ) -> dict:
    """NoC event-model simulator (generated)."""
    from archzero.analytic.domains import noc_model
    family = str(knobs.get("family") or "{family}")
    out = dict(noc_model(family))
    out["evidence"] = "dedicated"
    out["backend"] = "dedicated-noc"
    out["family"] = family
    return out
'''

_DATAFLOW_BODY = '''
def run_sim( knobs: dict ) -> dict:
    """Dataflow event-model simulator (generated)."""
    from archzero.analytic.domains import dataflow_model
    family = str(knobs.get("family") or "{family}")
    out = dict(dataflow_model(family))
    out["evidence"] = "dedicated"
    out["backend"] = "dedicated-dataflow"
    out["family"] = family
    return out
'''

_WAFER_BODY = '''
def run_sim( knobs: dict ) -> dict:
    """Wafer-scale fabric event-model simulator (generated)."""
    from archzero.analytic.domains import wafer_model
    family = str(knobs.get("family") or "{family}")
    out = dict(wafer_model(family))
    out["evidence"] = "dedicated"
    out["backend"] = "dedicated-wafer"
    out["family"] = family
    return out
'''


def _body_for(params: MechanismParams) -> str:
    kind = family_domain(params.family)
    if kind == NOC:
        return _NOC_BODY.format(family=params.family)
    if kind == DATAFLOW:
        return _DATAFLOW_BODY.format(family=params.family)
    if kind == WAFER:
        return _WAFER_BODY.format(family=params.family)
    fam = params.family
    if fam in {"prefetch", "filter", "streamer"}:
        return _PREFETCH_BODY.format(
            entries=params.table_entries,
            degree=params.prefetch_degree,
            acc=params.filter_accuracy,
            base=params.base_reduction,
            bw=params.extra_bw,
        )
    if fam == "replacement":
        return _REPLACEMENT_BODY.format(
            entries=params.table_entries,
            hist=params.history_len,
            base=params.base_reduction,
            bw=params.extra_bw,
        )
    if fam == "bypass":
        return _BYPASS_BODY.format(
            thr=params.bypass_threshold,
            base=params.base_reduction,
            bw=params.extra_bw,
        )
    return _GENERIC_BODY.format(
        family=fam,
        base=params.base_reduction,
        bw=params.extra_bw,
    )


def _selftest_ok(metrics: dict[str, Any]) -> bool:
    """Accept cache miss_reduction *or* a domain-native metric."""
    if "miss_reduction" in metrics:
        try:
            if 0.0 <= float(metrics["miss_reduction"]) <= 1.0:
                return True
        except (TypeError, ValueError):
            pass
    if metrics.get("goodput") is not None or metrics.get("p99_latency") is not None:
        return True
    try:
        jt = metrics.get("jitter_tolerance")
        if jt is not None:
            val = float(jt)
            if math.isfinite(val) and val > 0:
                return True
    except (TypeError, ValueError):
        pass
    if "pe_utilization" in metrics:
        try:
            if 0.0 <= float(metrics["pe_utilization"]) <= 1.0:
                return True
        except (TypeError, ValueError):
            pass
    if (
        metrics.get("die_to_die_bw") is not None
        or metrics.get("fabric_hop_latency") is not None
    ):
        return True
    if "coverage" in metrics:
        try:
            val = float(metrics["coverage"])
            if math.isfinite(val) and 0.0 <= val <= 1.0:
                return True
        except (TypeError, ValueError):
            pass
    return False


def render_dedicated_sim(params: MechanismParams) -> str:
    body = textwrap.dedent(_body_for(params)).strip()
    return (
        '"""Auto-generated dedicated Tier3 simulator — do not edit by hand."""\n'
        "from __future__ import annotations\n\n"
        f"{body}\n\n"
        "if __name__ == '__main__':\n"
        "    import json, sys\n"
        "    knobs = json.loads(sys.argv[1]) if len(sys.argv) > 1 else {}\n"
        "    print(json.dumps(run_sim(knobs)))\n"
    )


def generate_dedicated_sim(
    workdir: Path,
    *,
    title: str,
    mechanism: str,
    knobs: dict[str, Any] | None = None,
    family: str | None = None,
) -> GeneratedSim:
    """Write dedicated_sim.py under workdir and run a self-test."""
    workdir.mkdir(parents=True, exist_ok=True)
    knobs = dict(knobs or {})
    params = infer_params(
        title=title, mechanism=mechanism, knobs=knobs, family=family
    )
    path = workdir / "dedicated_sim.py"
    path.write_text(render_dedicated_sim(params), encoding="utf-8")

    payload = {
        "table_entries": params.table_entries,
        "prefetch_degree": params.prefetch_degree,
        "filter_accuracy": params.filter_accuracy,
        "history_len": params.history_len,
        "bypass_threshold": params.bypass_threshold,
        "miss_reduction": params.base_reduction,
        "extra_bw": params.extra_bw,
        "area": params.area_mm2,
        "family": params.family,
        "domain": family_domain(params.family),
    }
    proc = subprocess.run(
        [sys.executable, str(path), json.dumps(payload)],
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    metrics: dict[str, Any] = {}
    ok = False
    log = (proc.stdout or "") + (proc.stderr or "")
    if proc.returncode == 0:
        try:
            metrics = json.loads(proc.stdout.strip().splitlines()[-1])
            ok = _selftest_ok(metrics)
        except (json.JSONDecodeError, ValueError, IndexError):
            ok = False
    (workdir / "DEDICATED_SIM.md").write_text(
        f"# Dedicated simulator\n\n"
        f"- family: `{params.family}`\n"
        f"- domain: `{family_domain(params.family)}`\n"
        f"- path: `{path.name}`\n"
        f"- selftest_ok: `{ok}`\n"
        f"- miss_reduction: `{metrics.get('miss_reduction')}`\n"
        f"- p99_latency: `{metrics.get('p99_latency')}`\n"
        f"- goodput: `{metrics.get('goodput')}`\n"
        f"- pe_utilization: `{metrics.get('pe_utilization')}`\n"
        f"- die_to_die_bw: `{metrics.get('die_to_die_bw')}`\n",
        encoding="utf-8",
    )
    return GeneratedSim(
        family=params.family,
        path=path,
        selftest_ok=ok,
        metrics=metrics,
        log=log[-2000:],
    )


def _selftest_path(path: Path, payload: dict[str, Any]) -> tuple[bool, dict[str, Any], str]:
    proc = subprocess.run(
        [sys.executable, str(path), json.dumps(payload)],
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    log = (proc.stdout or "") + (proc.stderr or "")
    if proc.returncode != 0:
        return False, {}, log
    try:
        metrics = json.loads(proc.stdout.strip().splitlines()[-1])
        ok = _selftest_ok(metrics)
        return ok, metrics if ok else {}, log
    except (json.JSONDecodeError, ValueError, IndexError):
        return False, {}, log


def _llm_persona(family: str) -> str:
    kind = family_domain(family)
    if kind == NOC:
        return (
            "You write a small dedicated Python event-model simulator for a NoC "
            "mechanism family. Return ONLY a complete dedicated_sim.py that defines "
            "run_sim(knobs: dict) -> dict with keys p99_latency and/or goodput, "
            "plus evidence, backend, family. Do NOT invent miss_reduction — this "
            "is not a cache prefetcher. No network I/O. Deterministic."
        )
    if kind == DATAFLOW:
        return (
            "You write a small dedicated Python event-model simulator for a "
            "dataflow / PE-array mechanism. Return ONLY a complete dedicated_sim.py "
            "that defines run_sim(knobs: dict) -> dict with keys pe_utilization "
            "(0..1) and optionally sram_traffic, plus evidence, backend, family. "
            "Do NOT invent miss_reduction. No network I/O. Deterministic."
        )
    if kind == WAFER:
        return (
            "You write a small dedicated Python event-model simulator for a "
            "wafer-scale fabric mechanism. Return ONLY a complete dedicated_sim.py "
            "that defines run_sim(knobs: dict) -> dict with keys die_to_die_bw "
            "and/or fabric_hop_latency, plus evidence, backend, family. "
            "Do NOT invent miss_reduction. No network I/O. Deterministic."
        )
    return (
        "You write a small dedicated Python event-model simulator for one cache "
        "mechanism family. Return ONLY a complete dedicated_sim.py that defines "
        "run_sim(knobs: dict) -> dict with keys miss_reduction, bw_delta_frac, "
        "area_mm2, evidence, backend, family. No network I/O. Deterministic."
    )


async def generate_dedicated_sim_llm(
    workdir: Path,
    *,
    title: str,
    mechanism: str,
    knobs: dict[str, Any] | None = None,
    family: str | None = None,
    llm: Any | None = None,
    max_repairs: int = 2,
) -> GeneratedSim:
    """LLM-authored dedicated_sim.py with verify-repair; falls back to template.

    Offline / missing LLM → template codegen. On selftest failure, ask LLM to
    repair up to max_repairs times, then fall back to deterministic template.
    Tier6 / telemetry are out of scope here.
    """
    import re

    from archzero.models import TaskClass

    baseline = generate_dedicated_sim(
        workdir,
        title=title,
        mechanism=mechanism,
        knobs=knobs,
        family=family,
    )
    if llm is None:
        baseline.log = (baseline.log or "") + "\n[llm skipped → template]"
        return baseline

    params = infer_params(
        title=title, mechanism=mechanism, knobs=knobs or {}, family=family
    )
    persona = _llm_persona(params.family)
    kind = family_domain(params.family)
    ctx = (
        f"TITLE: {title}\nFAMILY: {params.family}\nDOMAIN: {kind}\n"
        f"MECHANISM:\n{mechanism}\n"
        f"KNOBS: {json.dumps(knobs or {})}\n"
        "Write dedicated_sim.py with run_sim()."
    )

    def _extract(text: str) -> str:
        fence = re.search(r"```(?:python)?\s*([\s\S]*?)```", text or "")
        if fence:
            return fence.group(1).strip()
        return (text or "").strip()

    path = workdir / "dedicated_sim.py"
    payload = {
        "table_entries": params.table_entries,
        "prefetch_degree": params.prefetch_degree,
        "filter_accuracy": params.filter_accuracy,
        "history_len": params.history_len,
        "bypass_threshold": params.bypass_threshold,
        "miss_reduction": params.base_reduction,
        "extra_bw": params.extra_bw,
        "area": params.area_mm2,
        "family": params.family,
        "domain": kind,
    }
    last_err = ""
    metric_hint = (
        "0<=miss_reduction<=1"
        if kind == CACHE
        else "domain keys (p99_latency/goodput or pe_utilization or "
        "die_to_die_bw/fabric_hop_latency) — do not invent miss_reduction"
    )
    for attempt in range(max_repairs + 1):
        if attempt == 0:
            raw = await llm.complete(persona, ctx, TaskClass.ANALYTIC)
            code = _extract(raw)
        else:
            repair = (
                f"dedicated_sim.py selftest failed:\n{last_err}\n\n"
                f"Current source:\n{path.read_text(encoding='utf-8')[:6000]}\n\n"
                f"Fix run_sim so it returns valid metrics JSON keys and "
                f"{metric_hint}. Return full file only."
            )
            raw = await llm.complete(persona, repair, TaskClass.ANALYTIC)
            code = _extract(raw)
        if "def run_sim" not in code:
            last_err = "no run_sim in LLM output"
            continue
        if "if __name__" not in code:
            code += (
                "\n\nif __name__ == '__main__':\n"
                "    import json, sys\n"
                "    knobs = json.loads(sys.argv[1]) if len(sys.argv) > 1 else {}\n"
                "    print(json.dumps(run_sim(knobs)))\n"
            )
        path.write_text(code, encoding="utf-8")
        ok, metrics, log = _selftest_path(path, payload)
        if ok:
            (workdir / "DEDICATED_SIM.md").write_text(
                f"# Dedicated simulator (LLM)\n\n"
                f"- family: `{params.family}`\n"
                f"- domain: `{kind}`\n"
                f"- attempts: `{attempt + 1}`\n"
                f"- selftest_ok: `True`\n"
                f"- miss_reduction: `{metrics.get('miss_reduction')}`\n"
                f"- p99_latency: `{metrics.get('p99_latency')}`\n"
                f"- pe_utilization: `{metrics.get('pe_utilization')}`\n"
                f"- die_to_die_bw: `{metrics.get('die_to_die_bw')}`\n",
                encoding="utf-8",
            )
            return GeneratedSim(
                family=params.family,
                path=path,
                selftest_ok=True,
                metrics=metrics,
                log=log[-2000:],
            )
        last_err = log[:500] or "selftest failed"

    baseline = generate_dedicated_sim(
        workdir,
        title=title,
        mechanism=mechanism,
        knobs=knobs,
        family=family,
    )
    baseline.log = (baseline.log or "") + f"\n[llm failed → template] {last_err}"
    return baseline
