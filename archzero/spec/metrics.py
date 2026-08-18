"""Cross-domain acceptance-metric registry.

The factory covers CPU cores, memory hierarchy, interconnect, spatial
accelerators, and wafer-scale fabrics. The funnel used to know exactly four
cache numbers: MPKI reduction, DRAM bandwidth delta, IPC, and area. A NoC or
wafer package then parsed to *those same four defaults*, so interconnect work
was graded as an L2 prefetcher. CPU / memory problems were fine; everything
else was silently recast.

This registry makes the metric vocabulary explicit and, more importantly,
makes it possible to answer two questions honestly:

- which acceptance numbers came from the researcher's spec, and which are
  fallback defaults the tool invented?
- does any configured evaluator actually produce this quantity?

``Evaluator`` names below refer to what can produce a metric, mirroring
``EvidenceLevel``: an ``analytic`` metric can be gated at Tier2, a ``sim``
metric needs Tier3/Tier4, and a metric with no evaluator cannot be graded at
all — which the funnel should report rather than paper over.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

LOWER_IS_BETTER = "lower_is_better"
HIGHER_IS_BETTER = "higher_is_better"

# Problem domains. `generic` metrics apply everywhere (e.g. Magic Gap).
CACHE = "cache"
NOC = "noc"
DATAFLOW = "dataflow"
WAFER = "wafer"
GENERIC = "generic"

DOMAINS: tuple[str, ...] = (CACHE, NOC, DATAFLOW, WAFER, GENERIC)


@dataclass(frozen=True)
class MetricSpec:
    id: str
    name: str
    unit: str
    direction: str
    domain: str
    aliases: tuple[str, ...]
    evaluators: tuple[str, ...]
    note: str = ""

    @property
    def measurable(self) -> bool:
        """False = no tier in this repo can produce the number today."""
        return bool(self.evaluators)

    @property
    def default_op(self) -> str:
        return ">=" if self.direction == HIGHER_IS_BETTER else "<="


# Ordering matters: the parser prefers earlier, more specific aliases, so
# "p99 completion latency" wins over a bare "latency".
METRIC_SPECS: tuple[MetricSpec, ...] = (
    # --- generic ---
    MetricSpec(
        id="magic_gap",
        name="Magic Gap（模型 vs 仿真）",
        unit="x",
        direction=LOWER_IS_BETTER,
        domain=GENERIC,
        aliases=("magic gap", "magic-gap"),
        evaluators=("analytic", "sim"),
        note="Tier3 computes it by comparing the Tier2 prediction to simulation.",
    ),
    MetricSpec(
        id="coverage",
        name="实验矩阵覆盖率",
        unit="frac",
        direction=HIGHER_IS_BETTER,
        domain=GENERIC,
        aliases=("矩阵覆盖率", "coverage", "覆盖率"),
        evaluators=("analytic",),
        note="Fraction of the analytic experiment matrix that this run actually evaluated (NoC: topo × buffer × pattern; dataflow: shapes). Small suite is partial by design.",
    ),
    # --- cache / memory hierarchy ---
    MetricSpec(
        id="miss_reduction",
        name="MPKI 降低",
        unit="frac",
        direction=HIGHER_IS_BETTER,
        domain=CACHE,
        aliases=("mpki reduction", "miss reduction", "mpki", "miss rate", "缺失率"),
        evaluators=("analytic", "sim"),
    ),
    MetricSpec(
        id="bw_delta_frac",
        name="DRAM 带宽变化",
        unit="frac",
        direction=LOWER_IS_BETTER,
        domain=CACHE,
        aliases=("dram bandwidth", "dram bw", "memory bandwidth", "内存带宽"),
        evaluators=("analytic", "sim"),
    ),
    MetricSpec(
        id="ipc_speedup",
        name="IPC 加速比",
        unit="x",
        direction=HIGHER_IS_BETTER,
        domain=CACHE,
        aliases=("ipc speedup", "ipc", "iso-ipc"),
        evaluators=("analytic", "sim"),
    ),
    MetricSpec(
        id="area_mm2",
        name="面积",
        unit="mm2",
        direction=LOWER_IS_BETTER,
        domain=CACHE,
        aliases=("area budget", "area", "面积"),
        evaluators=("analytic", "sim", "rtl"),
    ),
    # --- interconnect / NoC ---
    MetricSpec(
        id="p99_latency",
        name="p99 完成时延",
        unit="cycles",
        direction=LOWER_IS_BETTER,
        domain=NOC,
        aliases=("p99 completion latency", "p99 latency", "p99 时延", "p99 完成时延", "p99"),
        evaluators=("analytic", "sim"),
        note="Produced by the analytic NoC backend (archzero.sim.noc).",
    ),
    MetricSpec(
        id="p95_latency",
        name="p95 完成时延",
        unit="cycles",
        direction=LOWER_IS_BETTER,
        domain=NOC,
        aliases=("p95 completion latency", "p95 latency", "p95 时延", "p95 完成时延", "p95"),
        evaluators=("analytic", "sim"),
        note="Produced by the analytic NoC backend (archzero.sim.noc).",
    ),
    MetricSpec(
        id="completion_latency",
        name="集合通信完成时延",
        unit="cycles",
        direction=LOWER_IS_BETTER,
        domain=NOC,
        aliases=("completion latency", "完成时延", "完成时间", "端到端时延"),
        evaluators=("analytic", "sim"),
        note="Produced by the analytic NoC backend (archzero.sim.noc).",
    ),
    MetricSpec(
        id="goodput",
        name="有效吞吐 goodput",
        unit="frac",
        direction=HIGHER_IS_BETTER,
        domain=NOC,
        aliases=("goodput", "有效吞吐"),
        evaluators=("analytic", "sim"),
        note="Produced by the analytic NoC backend (archzero.sim.noc).",
    ),
    MetricSpec(
        id="link_utilization",
        name="链路 / 对分带宽利用率",
        unit="frac",
        direction=HIGHER_IS_BETTER,
        domain=NOC,
        aliases=("link utilization", "带宽利用率", "利用率", "bisection bandwidth", "对分带宽"),
        evaluators=("analytic", "sim"),
        note="Produced by the analytic NoC backend (archzero.sim.noc).",
    ),
    MetricSpec(
        id="jitter_tolerance",
        name="抖动下尾时延恶化倍数",
        unit="x",
        direction=LOWER_IS_BETTER,
        domain=NOC,
        aliases=("jitter", "抖动"),
        evaluators=("analytic",),
        note="Analytic NoC backend: p99 under a standard arrival-spread injection over clean p99. Family tax, not a flit-level harness.",
    ),
    # --- dataflow / spatial accelerators ---
    MetricSpec(
        id="pe_utilization",
        name="PE 阵列利用率",
        unit="frac",
        direction=HIGHER_IS_BETTER,
        domain=DATAFLOW,
        aliases=("pe utilization", "pe 利用率", "阵列利用率", "mac utilization"),
        evaluators=("analytic", "sim"),
        note="Produced by the analytic dataflow backend (archzero.sim.dataflow).",
    ),
    MetricSpec(
        id="reuse_factor",
        name="数据复用倍数",
        unit="x",
        direction=HIGHER_IS_BETTER,
        domain=DATAFLOW,
        aliases=("data reuse", "reuse factor", "数据复用"),
        evaluators=("analytic", "sim"),
        note="Produced by the analytic dataflow backend (archzero.sim.dataflow).",
    ),
    MetricSpec(
        id="sram_traffic",
        name="片上 SRAM 访存量",
        unit="frac",
        direction=LOWER_IS_BETTER,
        domain=DATAFLOW,
        aliases=("sram traffic", "on-chip traffic", "片上访存"),
        evaluators=("analytic", "sim"),
        note="Produced by the analytic dataflow backend (archzero.sim.dataflow).",
    ),
    # --- wafer-scale / multi-die ---
    MetricSpec(
        id="die_to_die_bw",
        name="裸片间带宽",
        unit="GBps",
        direction=HIGHER_IS_BETTER,
        domain=WAFER,
        aliases=("die-to-die bandwidth", "die to die", "d2d bandwidth", "裸片间带宽", "chiplet bandwidth"),
        evaluators=("analytic", "sim"),
        note="Produced by the analytic wafer backend (archzero.sim.wafer).",
    ),
    MetricSpec(
        id="fabric_hop_latency",
        name="织物跳数时延",
        unit="cycles",
        direction=LOWER_IS_BETTER,
        domain=WAFER,
        aliases=("hop latency", "fabric latency", "跳数时延"),
        evaluators=("analytic", "sim"),
        note="Produced by the analytic wafer backend (archzero.sim.wafer).",
    ),
    MetricSpec(
        id="yield_redundancy",
        name="良率 / 冗余开销",
        unit="frac",
        direction=HIGHER_IS_BETTER,
        domain=WAFER,
        aliases=("yield", "redundancy", "良率", "冗余"),
        evaluators=(),
        note="No defect-map / spare-tile / redundancy-cost model exists. Fabric hop latency and die-to-die BW are measurable and must not be treated as a yield verdict.",
    ),
    MetricSpec(
        id="thermal_density",
        name="功耗密度",
        unit="W/cm2",
        direction=LOWER_IS_BETTER,
        domain=WAFER,
        aliases=("power density", "thermal density", "功耗密度"),
        evaluators=(),
        note="No power-map or thermal-RC model exists. Fabric hop/d2d numbers are not a thermal-density measurement.",
    ),
)


METRIC_BY_ID: dict[str, MetricSpec] = {m.id: m for m in METRIC_SPECS}


def metrics_for_domain(domain: str) -> tuple[MetricSpec, ...]:
    """Domain metrics plus the always-applicable generic ones."""
    return tuple(m for m in METRIC_SPECS if m.domain in (domain, GENERIC))


def measurable_ids() -> frozenset[str]:
    return frozenset(m.id for m in METRIC_SPECS if m.measurable)


def unmeasurable_ids() -> frozenset[str]:
    return frozenset(m.id for m in METRIC_SPECS if not m.measurable)


# Longest alias first so "p99 completion latency" is not eaten by "p99".
_ALIAS_INDEX: tuple[tuple[str, MetricSpec], ...] = tuple(
    sorted(
        ((alias.lower(), m) for m in METRIC_SPECS for alias in m.aliases),
        key=lambda pair: len(pair[0]),
        reverse=True,
    )
)


def detect_metrics(text: str) -> list[MetricSpec]:
    """Which registered metrics does this clause talk about?

    Alias matching is word-boundary-aware for ASCII so ``miss`` inside
    ``admission`` does not register a cache metric — that false positive is
    exactly how NoC specs used to acquire an MPKI threshold.
    """
    low = (text or "").lower()
    found: dict[str, MetricSpec] = {}
    for alias, spec in _ALIAS_INDEX:
        if spec.id in found:
            continue
        if _alias_present(low, alias):
            found[spec.id] = spec
    return list(found.values())


def _alias_present(low_text: str, alias: str) -> bool:
    if alias.isascii():
        return re.search(rf"(?<![a-z0-9]){re.escape(alias)}(?![a-z0-9])", low_text) is not None
    return alias in low_text


def infer_domain(text: str) -> str:
    """Guess the problem domain from detected metrics; ties go to `generic`."""
    hits = [m for m in detect_metrics(text) if m.domain != GENERIC]
    if not hits:
        return GENERIC
    counts: dict[str, int] = {}
    for m in hits:
        counts[m.domain] = counts.get(m.domain, 0) + 1
    best = max(counts.values())
    winners = sorted(d for d, n in counts.items() if n == best)
    return winners[0] if len(winners) == 1 else GENERIC


def registry_markdown() -> str:
    lines = [
        "# Acceptance metric registry",
        "",
        "`evaluators` lists what can produce the number. An empty cell means no",
        "tier in this repo measures it yet, so the funnel will refuse to grade a",
        "spec that depends on it rather than substituting a cache default.",
        "",
        "| id | 名称 | 单位 | 方向 | 领域 | evaluators |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for m in METRIC_SPECS:
        arrow = "越高越好" if m.direction == HIGHER_IS_BETTER else "越低越好"
        lines.append(
            f"| `{m.id}` | {m.name} | {m.unit} | {arrow} | {m.domain} | "
            f"{', '.join(m.evaluators) or '—'} |"
        )
    lines.append("")
    gaps = [m for m in METRIC_SPECS if not m.measurable]
    if gaps:
        lines += ["## 尚无评估器的指标", ""]
        for m in gaps:
            lines.append(f"- `{m.id}` — {m.note}")
        lines.append("")
    return "\n".join(lines)
