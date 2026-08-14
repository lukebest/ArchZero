"""Pick UI / report headline numbers from a candidate metrics dict."""

from __future__ import annotations

from archzero.sim.families import CACHE, family_domain

_KEYS = (
    ("p99_latency", "p99", "cyc"),
    ("goodput", "goodput", "frac"),
    ("pe_utilization", "PE util", "frac"),
    ("reuse_factor", "reuse", "x"),
    ("sram_traffic", "SRAM", "frac"),
    ("die_to_die_bw", "d2d", "gbps"),
    ("fabric_hop_latency", "hop", "cyc"),
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
