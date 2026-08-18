"""Problem package scaffolding for architecture researchers.

ArchZero is a general chip-design Idea Factory: CPU cores, memory hierarchy,
interconnect, spatial accelerators, and wafer-scale fabrics. The cache
template is the default because ChampSim/gem5 already speak MPKI / IPC /
DRAM bandwidth. ``cpu`` and ``memory`` are aliases for that template.

NoC, dataflow, and wafer templates exist so those problems are not silently
re-graded as L2 prefetch. They state their own acceptance metrics.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from archzero.models import Clause, ClauseKind, ProblemPackage
from archzero.spec.metrics import CACHE, DATAFLOW, NOC, WAFER
from archzero.spec.ndf import write_problem_package


def _slug(title: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "-", title.strip().lower()).strip("-")
    return (s or "problem")[:48]


@dataclass(frozen=True)
class DomainTemplate:
    """Domain-specific clause wording for a scaffolded problem package."""

    domain: str
    label: str
    target_metric: str
    budget_clause: str
    budget_req: str
    acc_analytic: str
    acc_sim: str
    non_goals: str
    dof: str
    open_question: str


_CACHE = DomainTemplate(
    domain=CACHE,
    label="CPU 核 / 缓存 / 存储层次",
    target_metric=">=15% MPKI reduction",
    budget_clause="Area budget for new structures <= 0.5 mm^2.",
    budget_req=(
        "The mechanism must not increase DRAM bandwidth demand by more than 5% "
        "at iso-IPC."
    ),
    acc_analytic=(
        "An analytic model (Tier2) shall show predicted MPKI reduction >= 15% "
        "under stated assumptions; Magic Gap vs any available sim <= 2x."
    ),
    acc_sim=(
        "Stub or ChampSim/gem5 simulation shall confirm MPKI reduction and that "
        "DRAM bandwidth does not increase by more than 5% on the stated suite."
    ),
    non_goals="Do not change the ISA or require OS changes.",
    dof="Predictor family, table size, history length.",
    open_question="Which DOF dimensions are worth MAP-Elites features?",
)

_NOC = DomainTemplate(
    domain=NOC,
    label="片上互连 / NoC",
    target_metric="降低 p99 完成时延（tail latency），并报告 goodput 代价",
    budget_clause=(
        "Iso-wire 硬约束：总金属线资源恒定。任何拓扑对比必须在对分带宽一致"
        "（iso-bisection）的点上进行，并在报告中写明每条链路带宽。"
    ),
    budget_req=(
        "在 iso-bisection 预算下，候选机制不得以显著牺牲链路利用率 / goodput "
        "的方式换取尾时延改善；两者须同表报告。"
    ),
    acc_analytic=(
        "解析模型应给出 p99 完成时延相对基线的改善，并陈述流量与服务时间分布假设；"
        "Magic Gap（解析预测 vs 仿真 headline 配置）<= 2x。"
    ),
    acc_sim=(
        "在至少一种拓扑 × 一种缓冲类型下报告 p95/p99 完成时延与链路利用率，"
        "与无控制面的分组交换基线同表对比。"
    ),
    non_goals=(
        "不做全片 RTL 物理签核；不做片外网络或多插座系统；"
        "不以改缓存一致性协议为主。"
    ),
    dof="仲裁粒度、虚通道/信用策略、集合算法相位、时隙长度、QoS 隔离方式。",
    open_question="在 iso-wire 约束下，何种调度范式最能压低尾时延而不牺牲利用率？",
)

_DATAFLOW = DomainTemplate(
    domain=DATAFLOW,
    label="数据流 / 空间加速器",
    target_metric="提升 PE 阵列利用率，并降低片上 SRAM 访存量",
    budget_clause=(
        "片上 SRAM 容量与 PE 数量固定；任何映射对比必须在同一 PE 数与同一 SRAM "
        "预算下进行（iso-resource）。"
    ),
    budget_req=(
        "候选映射 / 机制不得以增加片上 SRAM 访存量为代价换取阵列利用率；"
        "两者须同表报告。"
    ),
    acc_analytic=(
        "解析或映射模型应给出 PE 利用率与数据复用倍数，并陈述 tiling / "
        "循环序假设；Magic Gap <= 2x。"
    ),
    acc_sim=(
        "在至少两种层形状（如 GEMM 瘦长与方阵）下报告阵列利用率与片上访存量，"
        "与朴素映射基线同表对比。"
    ),
    non_goals="不重做算子库；不做训练全流程；不改 host 侧运行时。",
    dof="Tiling 因子、循环序、数据流类型（WS/OS/RS）、片上缓冲划分。",
    open_question="哪些层形状会让当前数据流选择失效？",
)

_WAFER = DomainTemplate(
    domain=WAFER,
    label="晶圆级 / 多裸片",
    target_metric="降低织物跳数时延，并在缺陷冗余开销受控下提升裸片间带宽",
    budget_clause=(
        "晶圆级封装：无片外 DRAM，全部工作集驻留片上 SRAM；功耗密度上限与"
        "冗余（备用行/列/裸片）预算须写明并在对比中固定。"
    ),
    budget_req=(
        "候选机制不得以超出功耗密度上限或增加冗余开销为代价换取带宽 / 时延；"
        "三者须同表报告。"
    ),
    acc_analytic=(
        "解析模型应给出织物跳数时延与裸片间有效带宽，并陈述放置 / 分区假设；"
        "Magic Gap <= 2x。"
    ),
    acc_sim=(
        "在至少一种缺陷注入场景（坏裸片或坏链路）下报告时延与带宽降级路径，"
        "与无冗余基线同表对比。"
    ),
    non_goals="不做完整封装热仿真；不做晶圆制造工艺改动；不做片外网络。",
    dof="分区/放置策略、冗余粒度、路由绕行策略、SRAM 分层与驻留策略。",
    open_question="缺陷分布如何改变最优分区粒度？",
)

TEMPLATES: dict[str, DomainTemplate] = {
    CACHE: _CACHE,
    NOC: _NOC,
    DATAFLOW: _DATAFLOW,
    WAFER: _WAFER,
}

# Researcher-facing names that share the CPU / memory-hierarchy template.
DOMAIN_ALIASES: dict[str, str] = {
    "cpu": CACHE,
    "core": CACHE,
    "memory": CACHE,
    "mem": CACHE,
    "llc": CACHE,
}


def resolve_scaffold_domain(name: str) -> str:
    """Map ``cpu`` / ``memory`` onto the cache template; other names pass through."""
    key = (name or "").strip().lower()
    return DOMAIN_ALIASES.get(key, key)


def scaffold_problem(
    *,
    title: str,
    workload: str,
    symptom: str,
    constraint: str,
    domain: str = CACHE,
    target_metric: str | None = None,
    area_budget: str | None = None,
    bandwidth_slack: str | None = None,
    non_goals: str | None = None,
    dof: str | None = None,
    out_dir: Path,
) -> Path:
    """Create a lint-ready NDF-lite problem package from researcher fields."""
    resolved = resolve_scaffold_domain(domain)
    try:
        tpl = TEMPLATES[resolved]
    except KeyError as e:
        expected = sorted({*TEMPLATES, *DOMAIN_ALIASES})
        raise ValueError(
            f"unknown domain {domain!r}; expected one of {expected}"
        ) from e
    domain = resolved

    goal = target_metric or tpl.target_metric
    budget = area_budget or tpl.budget_clause
    budget_req = bandwidth_slack or tpl.budget_req
    nng = non_goals or tpl.non_goals
    dof_text = dof or tpl.dof

    pid = f"pp-{_slug(title)}"
    clauses = [
        Clause(
            id="CTX-001",
            kind=ClauseKind.CONTEXT,
            text=f"Workload: {workload}\n\nSymptom: {symptom}",
        ),
        Clause(
            id="CTX-002",
            kind=ClauseKind.CONTEXT,
            text=f"Hardware / resource envelope: {constraint}\n{budget}",
            refines=["CTX-001"],
        ),
        Clause(
            id="REQ-001",
            kind=ClauseKind.REQUIREMENT,
            text=f"The mechanism shall achieve: {goal} versus the unmodified baseline.",
            refines=["CTX-001"],
        ),
        Clause(
            id="REQ-002",
            kind=ClauseKind.REQUIREMENT,
            text=budget_req,
            refines=["CTX-002"],
        ),
        Clause(
            id="NNG-001",
            kind=ClauseKind.NON_GOAL,
            text=nng,
        ),
        Clause(
            id="ACC-001",
            kind=ClauseKind.ACCEPTANCE,
            text=tpl.acc_analytic,
            refines=["REQ-001"],
            measurable=True,
        ),
        Clause(
            id="ACC-002",
            kind=ClauseKind.ACCEPTANCE,
            text=tpl.acc_sim,
            refines=["REQ-001", "REQ-002"],
            measurable=True,
        ),
        Clause(
            id="DOF-001",
            kind=ClauseKind.DEGREE_OF_FREEDOM,
            text=f"Open degrees of freedom: {dof_text}",
        ),
    ]
    pp = ProblemPackage(
        id=pid,
        title=title,
        clauses=clauses,
        open_questions=[
            f"What mechanisms attack: {symptom}?",
            tpl.open_question,
        ],
        meta={"workload": workload, "domain": domain, "scaffolded": True},
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{_slug(title)}.md"
    write_problem_package(pp, path)
    return path

def scaffold_unmeasurable_probe(
    *,
    title: str = "WSE yield and thermal probe",
    out_dir: Path,
) -> Path:
    """Write a wafer-domain package whose ACC names only unmeasurable quantities.

    After the default wafer template became report-only (hop latency and
    die-to-die bandwidth now have an evaluator), the honesty demo needs a
    package that still cannot be graded: yield, redundancy, thermal density,
    and power density. ACC/REQ must not mention hop latency or die-to-die
    bandwidth.
    """
    pid = f"pp-{_slug(title)}"
    clauses = [
        Clause(
            id="CTX-001",
            kind=ClauseKind.CONTEXT,
            text=(
                "Workload: tensor-parallel LLM on SRAM-resident wafer.\n\n"
                "Symptom: defective dies and hot spots collapse usable fabric."
            ),
        ),
        Clause(
            id="CTX-002",
            kind=ClauseKind.CONTEXT,
            text=(
                "Hardware / resource envelope: no off-wafer DRAM; "
                "power-density cap and spare-die redundancy budget are fixed."
            ),
            refines=["CTX-001"],
        ),
        Clause(
            id="REQ-001",
            kind=ClauseKind.REQUIREMENT,
            text=(
                "The mechanism shall improve yield / redundancy overhead "
                "and keep thermal density / power density under the envelope."
            ),
            refines=["CTX-001"],
        ),
        Clause(
            id="REQ-002",
            kind=ClauseKind.REQUIREMENT,
            text=(
                "Candidate mechanisms must not exceed the power-density cap "
                "or the redundancy budget; yield and thermal density must be "
                "reported together."
            ),
            refines=["CTX-002"],
        ),
        Clause(
            id="NNG-001",
            kind=ClauseKind.NON_GOAL,
            text=(
                "Do not perform full-package thermal simulation or change "
                "the wafer process."
            ),
        ),
        Clause(
            id="ACC-001",
            kind=ClauseKind.ACCEPTANCE,
            text=(
                "An analytic model shall report yield / redundancy overhead "
                "under a stated defect map; do not substitute an unrelated "
                "cache miss metric for yield."
            ),
            refines=["REQ-001"],
            measurable=True,
        ),
        Clause(
            id="ACC-002",
            kind=ClauseKind.ACCEPTANCE,
            text=(
                "Simulation shall report thermal density and power density "
                "under at least one defect-injection scenario, versus a "
                "no-redundancy baseline."
            ),
            refines=["REQ-001", "REQ-002"],
            measurable=True,
        ),
        Clause(
            id="DOF-001",
            kind=ClauseKind.DEGREE_OF_FREEDOM,
            text=(
                "Open degrees of freedom: spare-die placement, "
                "redundancy granularity."
            ),
        ),
    ]
    pp = ProblemPackage(
        id=pid,
        title=title,
        clauses=clauses,
        open_questions=[
            "What mechanisms improve yield without raising thermal density?",
            "How does the defect map change the spare-die budget?",
        ],
        meta={"domain": WAFER, "scaffolded": True, "unmeasurable_probe": True},
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{_slug(title)}.md"
    write_problem_package(pp, path)
    return path

