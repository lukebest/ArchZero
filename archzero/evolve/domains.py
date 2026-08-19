"""Domain-shaped mutation personas and cheap analytic scoring for MAP-Elites.

The built-in evolver used to ask every parent for ``{miss_reduction, extra_bw,
area}`` and then score the child with a cache Amdahl helper. A NoC campaign
therefore evolved prefetch knobs. Personas and scoring now follow the problem
domain; off-domain knobs are ignored rather than becoming an MPKI verdict.
"""

from __future__ import annotations

from typing import Any

MUTATE_PERSONA_CACHE = """你在做体系结构机制的多样性变异搜索。
根据父代机制与错误/产物，产出一个变体 JSON：
{title, family, mechanism, knobs: {miss_reduction, extra_bw, area}}
title 与 mechanism 必须原生简体中文；family 用英文短标识；knobs 数值保持英文键名。
mechanism 按决策/状态/冲突/相对基线四段写，不要用跨学科隐喻当标题。
保持可行，必要时探索不同 family。"""

MUTATE_PERSONA_NOC = """你在做片上互连 / 集合通信机制的多样性变异搜索。
根据父代机制与错误/产物，产出一个变体 JSON：
{title, family, mechanism, knobs: {family, message_b}}
family 必须是 packet_switched | request_grant | push_on_pull | presched 之一。
title 与 mechanism 必须原生简体中文；不要发明 miss_reduction / extra_bw / area。
mechanism 按决策/状态/冲突/相对基线四段写，不要用跨学科隐喻当标题。
保持可行，必要时探索不同 family。"""

MUTATE_PERSONA_DATAFLOW = """你在做空间加速器 / 数据流映射的多样性变异搜索。
根据父代机制与错误/产物，产出一个变体 JSON：
{title, family, mechanism, knobs: {family}}
family 必须是 output_stationary | weight_stationary | input_stationary | row_stationary 之一。
title 与 mechanism 必须原生简体中文；不要发明 miss_reduction / extra_bw / area。
mechanism 按决策/状态/冲突/相对基线四段写，不要用跨学科隐喻当标题。
保持可行，必要时探索不同 family。"""

MUTATE_PERSONA_WAFER = """你在做晶圆级 / 多裸片织物机制的多样性变异搜索。
根据父代机制与错误/产物，产出一个变体 JSON：
{title, family, mechanism, knobs: {family}}
family 必须是 mesh_xy | spare_bypass | compiled_partition 之一。
title 与 mechanism 必须原生简体中文；不要发明 miss_reduction / extra_bw / area。
mechanism 按决策/状态/冲突/相对基线四段写，不要用跨学科隐喻当标题。
不要声称已测量良率或功耗密度。
保持可行，必要时探索不同 family。"""

MUTATE_PERSONA_GENERIC = """你在做体系结构机制的多样性变异搜索。
根据父代机制与错误/产物，产出一个变体 JSON：
{title, family, mechanism, knobs: {}}
title 与 mechanism 必须原生简体中文；family 用英文短标识。
mechanism 按决策/状态/冲突/相对基线四段写，不要用跨学科隐喻当标题。
knobs 的键必须是该问题声明的指标，不要发明缓存 MPKI。"""

# Back-compat alias used by older tests / docs.
MUTATE_PERSONA = MUTATE_PERSONA_CACHE


def mutate_persona_for(domain: str) -> str:
    if domain == "noc":
        return MUTATE_PERSONA_NOC
    if domain == "dataflow":
        return MUTATE_PERSONA_DATAFLOW
    if domain == "wafer":
        return MUTATE_PERSONA_WAFER
    if domain == "cache":
        return MUTATE_PERSONA_CACHE
    return MUTATE_PERSONA_GENERIC


def score_variant(domain: str, family: str, knobs: dict[str, Any]) -> dict[str, Any]:
    """Produce Tier2-shaped metrics from domain helpers, not from invented MPKI."""
    knobs = knobs or {}
    if domain == "noc":
        from archzero.analytic.domains import noc_model
        from archzero.sim.noc import infer_noc_family

        fam = str(knobs.get("family") or family or "")
        fam = infer_noc_family("", "", fam)
        message_b = float(knobs.get("message_b") or knobs.get("message_bytes") or 4096.0)
        return noc_model(fam, message_b=message_b)
    if domain == "dataflow":
        from archzero.analytic.domains import dataflow_model
        from archzero.sim.dataflow import infer_dataflow_family

        fam = infer_dataflow_family("", "", str(knobs.get("family") or family or ""))
        return dataflow_model(fam)
    if domain == "wafer":
        from archzero.analytic.domains import wafer_model
        from archzero.sim.wafer import infer_wafer_family

        fam = infer_wafer_family("", "", str(knobs.get("family") or family or ""))
        return wafer_model(fam)

    from archzero.analytic.core import MechanismEffect, Workload, score_mechanism

    raw = knobs.get("miss_reduction")
    if raw is None:
        return {
            "note": "cache evolve: no miss_reduction in knobs; not a 12% default",
        }
    extra = knobs.get("extra_bw")
    area = knobs.get("area")
    return score_mechanism(
        Workload(
            name="evolve-proxy",
            baseline_mpki=8.0,
            baseline_ipc=1.4,
            mem_bandwidth_gbps=40.0,
            peak_bandwidth_gbps=50.0,
        ),
        MechanismEffect(
            miss_reduction_frac=float(raw),
            extra_bw_frac=float(extra) if extra is not None else 0.0,
            area_mm2=float(area) if area is not None else 0.0,
        ),
    )
