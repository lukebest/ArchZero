"""Which mechanism family belongs to which problem domain.

ChampSim, the directed event model, and dedicated_sim.py used to treat every
unknown family as a cache prefetcher. A ``noc_rg`` candidate then got an L2
filter module and an MPKI number. This table is the single place that says
otherwise.
"""

from __future__ import annotations

CACHE = "cache"
NOC = "noc"
DATAFLOW = "dataflow"
WAFER = "wafer"

_NOC_FAMILIES: frozenset[str] = frozenset(
    {
        "packet_switched",
        "request_grant",
        "push_on_pull",
        "presched",
        "noc_rg",
        "noc_pop",
        "noc_presched",
        "noc",
    }
)
_DATAFLOW_FAMILIES: frozenset[str] = frozenset(
    {
        "output_stationary",
        "weight_stationary",
        "input_stationary",
        "row_stationary",
        "os",
        "ws",
        "rs",
    }
)
_WAFER_FAMILIES: frozenset[str] = frozenset(
    {
        "mesh_xy",
        "spare_bypass",
        "compiled_partition",
        "wse_fabric",
    }
)


def family_domain(family: str | None) -> str:
    """``cache`` unless the family id is a known off-cache mechanism."""
    fam = (family or "").strip().lower().replace("-", "_")
    if fam in _NOC_FAMILIES:
        return NOC
    if fam in _DATAFLOW_FAMILIES:
        return DATAFLOW
    if fam in _WAFER_FAMILIES:
        return WAFER
    return CACHE


def champsim_hosts(family: str | None) -> bool:
    """ChampSim is a CPU / cache simulator. It cannot host a NoC family."""
    return family_domain(family) == CACHE


def request_domain(meta: dict | None = None, knobs: dict | None = None) -> str:
    """Domain from request meta/knobs, else from family id."""
    meta = meta or {}
    knobs = knobs or {}
    raw = str(meta.get("domain") or knobs.get("domain") or "").strip().lower()
    if raw in {NOC, DATAFLOW, WAFER, CACHE}:
        return raw
    return family_domain(str(meta.get("family") or knobs.get("family") or ""))

