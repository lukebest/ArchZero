"""Pick UI / report headline numbers from a candidate metrics dict."""

from __future__ import annotations

from archzero.sim.families import CACHE, family_domain

_KEYS = (
    ("p99_latency", "p99", "cyc"),
    ("goodput", "goodput", "frac"),
    ("jitter_tolerance", "jitter", "x"),
    ("pe_utilization", "PE util", "frac"),
    ("reuse_factor", "reuse", "x"),
    ("sram_traffic", "SRAM", "frac"),
    ("die_to_die_bw", "d2d", "gbps"),
    ("fabric_hop_latency", "hop", "cyc"),
    ("coverage", "cover", "frac"),
    ("miss_reduction", "MPKI↓", "frac"),
)


def metrics_domain(metrics: dict, family: str | None = None) -> str:
    kind = family_domain(family)
    if kind != CACHE:
        return kind
    blob = metrics or {}
    if any(
        blob.get(p + k) is not None
        for p in ("t3_", "t2_", "t4_", "")
        for k in ("p99_latency", "goodput", "completion_latency")
    ):
        return "noc"
    if any(
        blob.get(p + k) is not None
        for p in ("t3_", "t2_", "t4_", "")
        for k in ("pe_utilization", "sram_traffic")
    ):
        return "dataflow"
    if any(
        blob.get(p + k) is not None
        for p in ("t3_", "t2_", "t4_", "")
        for k in ("die_to_die_bw", "fabric_hop_latency")
    ):
        return "wafer"
    return CACHE


def format_value(kind: str, value: float) -> str:
    if kind == "cyc":
        return f"{value:.0f}cyc"
    if kind == "gbps":
        return f"{value:.1f}GB/s"
    if kind == "x":
        return f"{value:.2f}×"
    if kind == "frac":
        return f"{value*100:.1f}%"
    return f"{value:.3f}"


def candidate_headlines(
    metrics: dict | None, *, family: str | None = None, limit: int = 3
) -> list[dict]:
    """Return [{key,label,value,kind,display}, ...]. Skip MPKI on off-cache domains."""
    metrics = metrics or {}
    domain = metrics_domain(metrics, family)
    out = []
    for key, label, kind in _KEYS:
        if domain != CACHE and key == "miss_reduction":
            continue
        raw = None
        for prefix in ("t3_", "t2_", "t4_", ""):
            if metrics.get(prefix + key) is not None:
                raw = metrics[prefix + key]
                break
        if raw is None:
            continue
        try:
            val = float(raw)
        except (TypeError, ValueError):
            continue
        out.append({
            "key": key,
            "label": label,
            "value": val,
            "kind": kind,
            "display": format_value(kind, val),
        })
        if len(out) >= limit:
            break
    return out


def headlines_text(metrics, *, family=None) -> str:
    return " ".join(
        f"{h['label']}={h['display']}"
        for h in candidate_headlines(metrics, family=family)
    )


# Higher-is-better keys used to rank / score a candidate. Latency is reported
# in headlines but must not be the sort key (larger p99 is worse).
_RANK_KEYS = {
    "noc": ("goodput",),
    "dataflow": ("pe_utilization",),
    "wafer": ("die_to_die_bw",),
    "cache": ("miss_reduction",),
}


def _lookup_metric(metrics: dict, key: str) -> float | None:
    for prefix in ("t3_", "t2_", "t4_", ""):
        raw = metrics.get(prefix + key)
        if raw is None:
            continue
        try:
            return float(raw)
        except (TypeError, ValueError):
            continue
    return None


def ranking_score(
    metrics: dict | None, *, family: str | None = None, domain: str | None = None
) -> float | None:
    """Higher-is-better sort key, or None when we have no honest number.

    Off-cache results must not collapse to ``miss_reduction=0`` — that is how a
    NoC campaign used to look like an L2 prefetcher that missed its MPKI gate.
    """
    metrics = metrics or {}
    if not domain or domain == "generic":
        kind = metrics_domain(metrics, family)
    else:
        kind = domain
    if kind != CACHE and kind in _RANK_KEYS:
        for key in _RANK_KEYS[kind]:
            val = _lookup_metric(metrics, key)
            if val is not None:
                return val
        return None
    return _lookup_metric(metrics, "miss_reduction")


def stored_rank(
    metrics: dict | None,
    *,
    family: str | None = None,
    stored_score: float | None = None,
) -> float:
    """Keep-N / report sort key. Heal collapsed 0.0 and latency-shaped scores."""
    ranked = ranking_score(metrics, family=family)
    if stored_score is None:
        return ranked or 0.0
    stored = float(stored_score)
    if ranked is not None and (
        stored == 0.0 or (stored > 1.5 and 0.0 < ranked <= 1.5)
    ):
        return ranked
    return stored
