"""Domain-shaped offline scaffolds for e2e / corpus / FakeLLM.

These paths used to hard-code a prefetch candidate and
``{miss_reduction, extra_bw, area}`` knobs. A NoC spec then replayed as an
L2 miss-rate study. Domain comes from the problem package; knobs and the
analytic snippet follow it.
"""

from __future__ import annotations

from typing import Any

from archzero.models import ProblemPackage
from archzero.sim.families import CACHE, DATAFLOW, NOC, WAFER, family_domain
from archzero.spec.acc_parse import parse_acceptance_thresholds

_ANALYTIC = {
    CACHE: (
        "```python\ndef run_model():\n"
        "    return {'predicted_mpki':6.0,'miss_reduction':0.18,"
        "'ipc_speedup':1.05,'meets_target':True}\n```"
    ),
    NOC: (
        "```python\n"
        "from archzero.analytic.domains import noc_model\n"
        "def run_model():\n"
        "    return noc_model('request_grant')\n"
        "```"
    ),
    DATAFLOW: (
        "```python\n"
        "from archzero.analytic.domains import dataflow_model\n"
        "def run_model():\n"
        "    return dataflow_model('output_stationary')\n"
        "```"
    ),
    WAFER: (
        "```python\n"
        "from archzero.analytic.domains import wafer_model\n"
        "def run_model():\n"
        "    return wafer_model('mesh_xy')\n"
        "```"
    ),
}

_DEFAULT_FAMILY = {
    CACHE: "prefetch",
    NOC: "request_grant",
    DATAFLOW: "output_stationary",
    WAFER: "mesh_xy",
}

_MECHANISM = {
    CACHE: (
        "A small dead-block predictor filters L2 prefetch requests under "
        "LLM decode traffic to cut MPKI without large area."
    ),
    NOC: (
        "A per-quadrant request-grant arbiter issues collective grants on a "
        "coarse slot boundary; dynamic point-to-point fills idle slots."
    ),
    DATAFLOW: (
        "Iso-resource GEMM mapper choosing an output-stationary PE schedule "
        "to raise utilization without inventing a cache miss rate."
    ),
    WAFER: (
        "Mesh XY die-to-die fabric with compiled partitions; report hop "
        "latency and d2d bandwidth only — not wafer yield or thermal density."
    ),
}

_TITLE = {
    CACHE: "E2E demo prefetch filter",
    NOC: "E2E demo request-grant NoC",
    DATAFLOW: "E2E demo output-stationary mapper",
    WAFER: "E2E demo mesh-XY wafer fabric",
}


def problem_domain(problem: ProblemPackage, family: str | None = None) -> str:
    """Spec domain wins; a known off-cache family can rescue a generic spec."""
    domain = parse_acceptance_thresholds(problem).domain
    if domain in {NOC, DATAFLOW, WAFER, CACHE}:
        return domain
    fam = family_domain(family)
    if fam != CACHE:
        return fam
    return domain


def default_family(domain: str) -> str:
    return _DEFAULT_FAMILY.get(domain, "unclassified")


def scaffold_title(domain: str) -> str:
    return _TITLE.get(domain, "E2E demo candidate")


def scaffold_mechanism(domain: str) -> str:
    return _MECHANISM.get(domain, "Offline scaffold candidate.")


def knobs_for(domain: str, family: str | None = None) -> dict[str, Any]:
    """Cache knobs stay cache-shaped; off-cache knobs must not invent MPKI."""
    fam = family or default_family(domain)
    if domain in {NOC, DATAFLOW, WAFER}:
        return {"family": fam, "domain": domain}
    out: dict[str, Any] = {
        "miss_reduction": 0.18,
        "extra_bw": 0.02,
        "area": 0.25,
    }
    if fam:
        out["family"] = fam
    return out


def analytic_snippet(domain: str) -> str:
    return _ANALYTIC.get(domain, _ANALYTIC[CACHE])


def fake_llm_responses(domain: str) -> dict[str, str]:
    """Shared FakeLLM map for offline e2e / corpus. Analytic follows domain."""
    return {
        "bulk_screen": (
            '{"verdict":"pass","score":0.8,"summary":"ok",'
            '"physics_flags":[],"clause_refs":[]}'
        ),
        "comprehend": "**Status:** PASS\nCritique:\n- ok\n",
        "synthesize": (
            '{"verdict":"pass","score":0.7,"summary":"ok",'
            '"failure_modes":[],"clause_refs":[]}'
        ),
        "spec_gen": "# Spec\nAssumptions...\n",
        "analytic": analytic_snippet(domain),
        "final_judge": '{"verdict":"pass","score":0.8,"summary":"ok","clause_refs":[]}',
    }
