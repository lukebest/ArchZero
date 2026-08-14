"""Shared inapplicable result for CPU/cache simulators on off-cache domains."""

from __future__ import annotations

from archzero.sim.backend import SimResult


def off_cache_sim_result(backend: str, domain: str) -> SimResult:
    return SimResult(
        ok=True,
        unavailable=True,
        backend=backend,
        metrics={
            "evidence": "none",
            "backend": backend,
            "domain": domain,
            "inapplicable": True,
            "note": (
                f"{backend} is a CPU/cache simulator; domain={domain} "
                "cannot be measured here. Use the domain analytic backend."
            ),
        },
        log=f"{backend} inapplicable for domain={domain}",
    )
