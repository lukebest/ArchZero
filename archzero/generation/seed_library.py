"""No-LLM mechanism-family × DOF seed library for Tier0 volume.

Divergence spends LLM budget on diversity (~``n_cells * per_cell`` ideas).
This module supplies the rest of a ~1K entry pool by expanding discrete DOF
knobs × mechanism families into distinct candidate markdown/objects — no
ideation calls. Compatible with ``--seed-dir`` loading and pipeline merge.
"""

from __future__ import annotations

import hashlib
import itertools
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

from archzero.models import Candidate, ClauseKind, ProblemPackage
from archzero.sim.families import CACHE, DATAFLOW, NOC, WAFER
from archzero.spec.acc_parse import parse_acceptance_thresholds

# Cache / demo DOF axes (aligned with specs/demo.md DOF-001 + MechanismParams).
_CACHE_FAMILIES: tuple[str, ...] = (
    "prefetch",
    "filter",
    "deadblock",
    "bypass",
    "coalesce",
    "streamer",
    "replacement",
    "hybrid_filter_prefetch",
)
_TABLE_SIZES: tuple[int, ...] = (32, 64, 128, 192, 256, 384, 512, 768, 1024, 1536)
_HISTORY_LENS: tuple[int, ...] = (2, 4, 6, 8, 12, 16, 24, 32)
_DISTANCES: tuple[int, ...] = (1, 2, 3, 4, 6, 8, 12, 16)
_INDEX_MODES: tuple[str, ...] = ("pc_indexed", "set_indexed", "region_sig", "hybrid_index")

_NOC_FAMILIES: tuple[str, ...] = (
    "noc_rg",
    "noc_pop",
    "noc_presched",
    "packet_switched",
)
_DATAFLOW_FAMILIES: tuple[str, ...] = ("os", "ws", "rs", "input_stationary")
_WAFER_FAMILIES: tuple[str, ...] = ("spare_bypass", "compiled_partition", "mesh_xy")


@dataclass(frozen=True)
class SeedKnob:
    family: str
    table_entries: int
    history_len: int
    distance: int
    index_mode: str


def _content_hash(title: str, mechanism: str) -> str:
    return hashlib.sha256((title + "\n" + mechanism).encode()).hexdigest()[:16]


def _domain_for(problem: ProblemPackage) -> str:
    th = parse_acceptance_thresholds(problem)
    return th.domain or CACHE


def _families_for(domain: str) -> tuple[str, ...]:
    if domain == NOC:
        return _NOC_FAMILIES
    if domain == DATAFLOW:
        return _DATAFLOW_FAMILIES
    if domain == WAFER:
        return _WAFER_FAMILIES
    return _CACHE_FAMILIES


def _parse_int_list(text: str, patterns: Sequence[str]) -> list[int]:
    found: list[int] = []
    for pat in patterns:
        for m in re.finditer(pat, text, re.I):
            try:
                found.append(int(m.group(1)))
            except (TypeError, ValueError):
                continue
    out: list[int] = []
    for v in found:
        if v > 0 and v not in out:
            out.append(v)
    return out


def dof_axes_from_problem(problem: ProblemPackage) -> dict[str, list]:
    """Best-effort DOF extraction; falls back to domain defaults."""
    domain = _domain_for(problem)
    dofs = problem.by_kind(ClauseKind.DEGREE_OF_FREEDOM)
    blob = "\n".join(c.text for c in dofs) if dofs else ""

    families = list(_families_for(domain))
    lowered = blob.lower()
    preferred = [f for f in families if f.replace("_", "-") in lowered or f in lowered]
    if preferred:
        families = preferred + [f for f in families if f not in preferred]

    tables = _parse_int_list(
        blob,
        (r"table\s*(?:size|entries?)[^\d]{0,12}(\d+)", r"(\d+)\s*(?:entry|entries)"),
    ) or list(_TABLE_SIZES)
    histories = _parse_int_list(
        blob,
        (r"history[^\d]{0,12}(\d+)", r"(\d+)\s*(?:cycle|token)?\s*history"),
    ) or list(_HISTORY_LENS)
    distances = _parse_int_list(
        blob,
        (
            r"(?:prefetch\s*)?(?:distance|degree)[^\d]{0,12}(\d+)",
            r"(\d+)\s*(?:block|line)\s*(?:ahead|distance)",
        ),
    ) or list(_DISTANCES)

    return {
        "domain": domain,
        "families": families,
        "table_sizes": tables,
        "history_lens": histories,
        "distances": distances,
        "index_modes": list(_INDEX_MODES),
        "dof_text": blob,
    }


def _iter_knobs(axes: dict[str, list], *, target_n: int) -> Iterable[SeedKnob]:
    """Round-robin across families so a prefix of size N stays diverse."""
    families: list[str] = list(axes["families"])
    tables: list[int] = list(axes["table_sizes"])
    histories: list[int] = list(axes["history_lens"])
    distances: list[int] = list(axes["distances"])
    modes: list[str] = list(axes["index_modes"])
    if not families:
        return

    # Per-family Cartesian tails, advanced round-robin so early seeds span families.
    tails = {
        fam: list(itertools.product(tables, histories, distances, modes))
        for fam in families
    }
    for fam in families:
        tails[fam].sort(key=lambda t: (t[0] % 5, t[1], t[2], t[3]))

    emitted = 0
    cursor = {fam: 0 for fam in families}
    while emitted < target_n:
        progressed = False
        for fam in families:
            if emitted >= target_n:
                break
            i = cursor[fam]
            if i >= len(tails[fam]):
                continue
            table, hist, dist, mode = tails[fam][i]
            cursor[fam] = i + 1
            progressed = True
            emitted += 1
            yield SeedKnob(
                family=fam,
                table_entries=table,
                history_len=hist,
                distance=dist,
                index_mode=mode,
            )
        if not progressed:
            break


def _mechanism_text(
    knob: SeedKnob, domain: str, problem: ProblemPackage, *, serial: int
) -> tuple[str, str]:
    """Return (title, mechanism) sparse enough to survive ASCII Jaccard 0.85.

    ``dedup_candidates`` only keeps ``[a-z0-9]+`` tokens with length > 2, so
    Chinese prose does not diversify the pool. Each seed carries a unique
    English identity; shared boilerplate is intentionally minimal.
    """
    fam = knob.family
    t, h, d, mode = knob.table_entries, knob.history_len, knob.distance, knob.index_mode
    clause = next(
        (c.id for c in problem.clauses if c.kind == ClauseKind.DEGREE_OF_FREEDOM),
        "DOF-001",
    )
    uid = f"seedid{serial:04d}"
    # Stable fingerprint (avoid randomized ``hash()``) with many unique tokens.
    fingerprint = (
        abs(
            int(
                hashlib.sha256(
                    f"{fam}|{t}|{h}|{d}|{mode}|{serial}".encode()
                ).hexdigest()[:8],
                16,
            )
        )
        % 100000
    )
    uniq = (
        f"{uid} fam{fam} tbl{t} hist{h} deg{d} mode{mode} "
        f"slot{serial} grid{serial * 17 + t} node{serial * 13 + h} "
        f"path{serial * 11 + d} mark{fingerprint}"
    )

    if domain == NOC:
        title = f"{fam} {uid}"
        mechanism = (
            f"{uniq} noc {fam} arbiter credits{h} slots{d} routes{t} "
            f"index {mode} vs static schedule p99 {clause}"
        )
        return title, mechanism

    if domain == DATAFLOW:
        title = f"{fam} {uid}"
        mechanism = (
            f"{uniq} dataflow {fam} sram{t} rf{h} unroll{d} "
            f"schedule {mode} pe util {clause}"
        )
        return title, mechanism

    if domain == WAFER:
        title = f"{fam} {uid}"
        mechanism = (
            f"{uniq} wafer {fam} parts{t} spare{d} reroute {mode} "
            f"hist{h} fabric {clause}"
        )
        return title, mechanism

    family_action = {
        "prefetch": "filtered prefetch fills",
        "filter": "deadblock filter gate",
        "deadblock": "deadblock eviction hints",
        "bypass": "writeback throttle bypass",
        "coalesce": "miss coalesce merge",
        "streamer": "stream length adapt",
        "replacement": "utility replacement assist",
        "hybrid_filter_prefetch": "filter then prefetch chain",
    }.get(fam, f"{fam} cache policy")

    title = f"{fam} {uid}"
    mechanism = (
        f"{uniq} cache {family_action} degree{d} index {mode} "
        f"table{t} history{h} mpki cut bandwidth cap {clause}"
    )
    return title, mechanism


def generate_seed_library(
    problem: ProblemPackage,
    *,
    target_n: int = 1000,
    domain: str | None = None,
) -> list[Candidate]:
    """Build up to ``target_n`` distinct no-LLM seed candidates for ``problem``."""
    if target_n <= 0:
        return []
    axes = dof_axes_from_problem(problem)
    if domain:
        axes["domain"] = domain
        axes["families"] = list(_families_for(domain))
    dom = str(axes["domain"])
    out: list[Candidate] = []
    seen: set[str] = set()
    for serial, knob in enumerate(_iter_knobs(axes, target_n=target_n * 2)):
        if len(out) >= target_n:
            break
        title, mechanism = _mechanism_text(knob, dom, problem, serial=serial)
        h = _content_hash(title, mechanism)
        if h in seen:
            continue
        seen.add(h)
        out.append(
            Candidate(
                problem_id=problem.id,
                title=title,
                mechanism=mechanism,
                family=knob.family,
                clause_refs=[
                    c.id
                    for c in problem.clauses
                    if c.kind
                    in {
                        ClauseKind.REQUIREMENT,
                        ClauseKind.DEGREE_OF_FREEDOM,
                        ClauseKind.ACCEPTANCE,
                    }
                ][:4],
                content_hash=h,
                metrics={
                    "seed_library": True,
                    "seed_table_entries": knob.table_entries,
                    "seed_history_len": knob.history_len,
                    "seed_distance": knob.distance,
                    "seed_index_mode": knob.index_mode,
                    "seed_domain": dom,
                    "seed_serial": serial,
                },
            )
        )
    return out


def write_seed_dir(candidates: Sequence[Candidate], out_dir: Path) -> int:
    """Write candidate markdown files loadable by ``pipeline._load_seeds``."""
    out_dir.mkdir(parents=True, exist_ok=True)
    for i, c in enumerate(candidates):
        path = out_dir / f"seed_{i:04d}_{c.family}.md"
        path.write_text(
            f"# {c.title}\n\nFamily: {c.family}\n\n{c.mechanism}\n",
            encoding="utf-8",
        )
    return len(candidates)


def seed_library_stats(
    generated: int,
    after_hash: int,
    after_jaccard: int,
    *,
    target_n: int,
) -> dict:
    return {
        "target_n": target_n,
        "generated": generated,
        "after_content_hash": after_hash,
        "after_jaccard": after_jaccard,
        "dedup_collapse": generated - after_jaccard,
        "hit_target": after_jaccard >= min(target_n, generated),
    }
