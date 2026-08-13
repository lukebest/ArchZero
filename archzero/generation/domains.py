"""Cross-domain source catalog for lateral ideation.

Companion to :mod:`archzero.generation.theories`. Theory lenses supply the
*abstraction* used to reason about a bottleneck; domain sources supply the
*concrete prior art from another field* whose structure can be transferred.

Historical architecture leaps came from exactly this pairing: dataflow came
from lambda calculus, out-of-order from compiler scheduling, systolic arrays
from signal processing, SIMT from graphics pipelines.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DomainSource:
    id: str
    name: str
    classic_result: str
    transfer_hint: str


DOMAIN_SOURCES: tuple[DomainSource, ...] = (
    DomainSource(
        id="compiler_scheduling",
        name="编译器指令调度",
        classic_result="Tomasulo 记分板、软件流水、trace scheduling",
        transfer_hint="把静态编译期的依赖分析与重排搬到运行时硬件，或反向把动态调度决策外提到编译期",
    ),
    DomainSource(
        id="lambda_calculus",
        name="λ 演算与函数式求值",
        classic_result="惰性求值、图规约、纯函数无副作用",
        transfer_hint="用数据可用性而非程序计数器驱动执行；以不可变性换取无锁共享",
    ),
    DomainSource(
        id="dsp_systolic",
        name="数字信号处理",
        classic_result="脉动阵列、FIR 流水、多相分解",
        transfer_hint="把不规则访存改造成节奏固定的数据脉动，用规则性换取带宽与布线确定性",
    ),
    DomainSource(
        id="graphics_pipeline",
        name="图形渲染流水线",
        classic_result="SIMT、tile-based deferred rendering、纹理缓存与 mipmap",
        transfer_hint="按屏幕空间分块以获得局部性；用大规模同构线程掩盖长延迟",
    ),
    DomainSource(
        id="tcp_congestion",
        name="网络拥塞控制",
        classic_result="AIMD、BBR 的带宽时延积估计、ECN 显式拥塞通告",
        transfer_hint="把片上资源竞争视为拥塞，用端到端反馈信号取代静态仲裁阈值",
    ),
    DomainSource(
        id="db_query_optimization",
        name="数据库查询优化",
        classic_result="代价模型、基数估计、火山模型与向量化执行",
        transfer_hint="为硬件决策引入代价模型与统计直方图；批量化处理摊薄每元素开销",
    ),
    DomainSource(
        id="os_scheduling",
        name="操作系统调度",
        classic_result="CFS 虚拟运行时、多级反馈队列、工作窃取",
        transfer_hint="用公平性/亏欠账本替代优先级硬编码；空闲单元主动窃取而非中心分派",
    ),
    DomainSource(
        id="distributed_consensus",
        name="分布式共识",
        classic_result="Paxos/Raft、法定人数、租约与逻辑时钟",
        transfer_hint="把一致性协议的租约与版本号思想用于缓存一致性或多芯粒同步",
    ),
    DomainSource(
        id="cdn_caching",
        name="CDN 与 Web 缓存",
        classic_result="一致性哈希、TTL 与陈旧再验证、边缘预取",
        transfer_hint="按内容而非地址分片；允许短暂陈旧以换取尾延迟",
    ),
    DomainSource(
        id="coding_ecc",
        name="纠错编码工程",
        classic_result="LDPC、RS 码、擦除编码与条带化",
        transfer_hint="用冗余换取重传/重算的省略；对不同重要度数据施加不等保护",
    ),
    DomainSource(
        id="cryptography",
        name="密码学",
        classic_result="Merkle 树、布隆过滤器、同态与承诺方案",
        transfer_hint="用紧凑摘要在昂贵结构前做常数级否定判定；用可验证摘要替代全量比对",
    ),
    DomainSource(
        id="auction_mechanism",
        name="拍卖与机制设计",
        classic_result="VCG、二价拍卖、组合拍卖",
        transfer_hint="给共享资源标价，让请求方按真实紧迫度出价，取代人工 QoS 权重",
    ),
    DomainSource(
        id="supply_chain",
        name="供应链与库存管理",
        classic_result="牛鞭效应、看板拉动、经济订货批量",
        transfer_hint="用拉动式请求抑制上游过量预取；按批量经济性决定搬运粒度",
    ),
    DomainSource(
        id="immunology",
        name="免疫系统",
        classic_result="自体/非自体识别、克隆选择、免疫记忆",
        transfer_hint="对异常访问模式建立记忆并快速二次响应；分层防御而非单点检测",
    ),
    DomainSource(
        id="urban_traffic",
        name="城市交通工程",
        classic_result="绿波带、匝道计量、拥堵定价、Braess 悖论",
        transfer_hint="入口限流优于出口拥塞；增加链路可能降低整体吞吐，需验证",
    ),
    DomainSource(
        id="power_grid",
        name="电力系统调度",
        classic_result="需求响应、旋转备用、区域频率调节",
        transfer_hint="把功耗预算当作可交易可预留的容量，用负荷预测提前调频调压",
    ),
    DomainSource(
        id="statistical_learning",
        name="统计学习",
        classic_result="在线学习后悔界、老虎机探索利用、集成模型",
        transfer_hint="预测器按后悔界而非命中率设计；多预测器集成并按置信度仲裁",
    ),
    DomainSource(
        id="operations_research",
        name="运筹优化",
        classic_result="线性规划对偶、拉格朗日松弛、列生成",
        transfer_hint="用对偶价格指导分布式局部决策，逼近全局最优而无需中心求解",
    ),
    DomainSource(
        id="filesystem_storage",
        name="文件系统与存储引擎",
        classic_result="日志结构写入、LSM 树、写时复制、SSD FTL 与磨损均衡",
        transfer_hint="把随机写聚合成顺序追加，后台压实；用间接映射层解耦逻辑与物理地址",
    ),
    DomainSource(
        id="compiler_gc",
        name="内存管理与垃圾回收",
        classic_result="分代假说、region 推断、引用计数与追踪混合",
        transfer_hint="按生命周期分区管理片上存储；用弱代假说指导替换与下沉策略",
    ),
    DomainSource(
        id="realtime_control",
        name="实时系统与调度理论",
        classic_result="速率单调、最早截止优先、可调度性分析与 WCET",
        transfer_hint="为关键路径请求提供可证明的最坏情况界，而不仅是平均性能",
    ),
    DomainSource(
        id="signal_compression",
        name="有损压缩与感知编码",
        classic_result="变换编码、率失真理论、感知掩蔽",
        transfer_hint="按下游可感知性分配比特；对结果不敏感的数据主动降精度",
    ),
    DomainSource(
        id="biological_neural",
        name="生物神经系统",
        classic_result="事件驱动脉冲、突触可塑性、稀疏编码",
        transfer_hint="仅在状态变化时消耗能量；用稀疏活跃度换取静态功耗下降",
    ),
    DomainSource(
        id="ecology_evolution",
        name="生态与进化动力学",
        classic_result="r/K 选择、生态位分化、捕食者-猎物振荡",
        transfer_hint="让多种策略在同一资源上共存并自然分化生态位，而非全局选定单一策略",
    ),
)


DOMAIN_BY_ID = {d.id: d for d in DOMAIN_SOURCES}


def domain_catalog_markdown() -> str:
    lines = [
        "# Cross-domain sources",
        "",
        "Lateral ideation transfers an abstract structure from another field.",
        "Pair each source with a theory lens to bound the reasoning.",
        "",
    ]
    for d in DOMAIN_SOURCES:
        lines.append(f"## {d.name} (`{d.id}`)")
        lines.append("")
        lines.append(f"- 经典结果: {d.classic_result}")
        lines.append(f"- 迁移提示: {d.transfer_hint}")
        lines.append("")
    return "\n".join(lines)


def select_domains(ids: list[str] | None = None) -> tuple[DomainSource, ...]:
    """Resolve a whitelist of domain ids, falling back to the full catalog."""
    if not ids:
        return DOMAIN_SOURCES
    picked = tuple(DOMAIN_BY_ID[i] for i in ids if i in DOMAIN_BY_ID)
    return picked or DOMAIN_SOURCES
