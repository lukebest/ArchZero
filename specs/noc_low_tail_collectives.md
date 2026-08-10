---
id: pp-noc-low-tail-collectives
title: "NoC 低尾时延集合通信与动态点对点 — 8×6 mesh/torus"
open_questions:
  - 在 iso-wire（对分带宽一致）约束下，何种调度范式最能压低集合通信尾时延？
  - request-grant 集中式、push-on-pull 分布式、预先排图三者在抖动与故障下的鲁棒性如何权衡？
  - bufferless 织物上实现低尾时延集合通信的可行边界在哪里？
  - 动态点对点流量与集合通信共存时，如何避免互相拉高尾部？
decisions: []
workload: "collectives + dynamic point-to-point on on-chip NoC"
domain: "interconnect / NoC"
---

# NoC 低尾时延集合通信与动态点对点 — 8×6 mesh/torus

### CTX-001 — Research objective

`measurable: false`

考察在片上 **NoC** 中实现 **集合通信的低尾时延（low tail latency）**，并同时覆盖 **非集合、动态点对点（dynamic point-to-point）通信的低动态时延**。候选机制应相对基线分组交换（packet-switched）NoC 给出可论证的改进，并产出研究报告（机制定义、解析边界、实验矩阵、失败模式与威胁效度）。

### CTX-002 — Topology and iso-wire budget

`refines: CTX-001`

在 **8×6** 节点网格上评估两种拓扑：

1. **2D mesh**
2. **Folded 2D torus**

**Iso-wire / 金属线资源恒定（硬约束）：** 总金属线资源不变。因此 **folded 2D torus 的每条链路带宽 = 2D mesh 对应链路带宽的一半**，使二者 **对分带宽（bisection bandwidth）一致**。所有 mesh vs torus 对比必须在此 iso-bisection 点进行；禁止在未减半 torus 链路带宽的情况下宣称 torus 因“更多链路”而获胜。

### CTX-003 — Link bandwidth and timing

`refines: CTX-002`

- **2D mesh 链路带宽：** **64 Bytes/cycle**（每条链路）  
- **Folded 2D torus 链路带宽：** **32 Bytes/cycle**（= mesh 的一半，iso-wire）  
- **链路延迟：** 横向（X）**7** 拍；纵向（Y）**9** 拍  

模型与仿真对 mesh / folded torus 均使用上述延迟；torus 绕回链路继承其所在轴的延迟。

### CTX-004 — Buffering styles

`refines: CTX-002`

织物类型可为（与拓扑正交，结果须分开报告）：

- **bufferable** — 路由器可缓存 flit/packet（credit / VC 或等价）  
- **bufferless** — 数据面基本无（或可忽略）缓冲；偏转 / NACK-重传 / 类电路占用等按候选机制定义  

禁止将 bufferable 与 bufferless 结果简单平均后宣称“总体最优”。

### CTX-005 — Traffic：集合通信

`refines: CTX-001`

至少覆盖以下集合通信模式：

| Pattern | 说明 |
|---------|------|
| **allgather** | 各节点贡献数据，全体收到拼接结果 |
| **allreduce** | 各节点贡献，全体收到归约结果 |
| **gather** | 全体 → 指定 root |
| **reduce** | 全体 → 指定 root（归约） |
| **broadcast** | 指定 root → 全体 |
| **alltoall** | 每节点向每其他节点发送 |

消息大小、分块、多相算法（如 allreduce 的 reduce-scatter + allgather）为 DOF，除非候选以 DEC 冻结。

### CTX-006 — Traffic：动态点对点（非集合）

`refines: CTX-001`

除集合通信外，必须评估 **动态点对点** 流量：源/宿对与注入时刻在线变化（非静态预先排好的流量矩阵）。目标是 **低动态时延**（含中位数与尾部，见 REQ），并考察其与集合通信 **共存 / 交错** 时的干扰。

合成动态模式（如随机置换、热点、突发 ON/OFF）允许作为实验因子，但须在报告中写清生成假设。

### CTX-007 — Mechanism families（合法搜索空间）

`refines: CTX-001`

机制族至少包括以下方向（可组合，须在 DEC/DOF 中声明主范式）：

1. **Request-grant 集中式调度** — 请求汇聚后仲裁，再发放 grant / 授权注入或路径占用（可含同步集合 RG 与异步多播树 grant 等变体）。  
2. **Push-on-pull 分布式调度** — 接收方 pull / 信用驱动与发送方 push 协同，无全局单一调度器，或仅有轻量分层协调。  
3. **预先排图（pre-scheduled / compiled schedules）** — 离线或阶段开始前为集合（及可选静态相位）生成冲突避免的时隙/路径表；动态点对点可走旁路或动态插入空闲时隙。  

基线：**无上述控制面的纯分组交换 NoC**（普通路由与本地仲裁）。

### REQ-001 — Low tail latency (collectives)

`refines: CTX-001, CTX-005`

相对基线分组交换，候选机制在相同拓扑、iso-wire 带宽、链路延迟、缓冲类型与消息大小点上，应显著降低集合通信的 **完成时间尾部**（至少报告 p95 或 p99 completion latency；若单次确定性集合则报告最坏完成时间，并说明分布假设）。不得仅用均值掩盖尾部。

### REQ-002 — Low dynamic latency (point-to-point)

`refines: CTX-001, CTX-006`

对动态点对点流量，候选应降低 **端到端动态时延**（中位数与尾部均需报告）。在与集合通信混合负载下，点对点尾时延不得因集合相位出现不可接受的饿死或长尾尖峰（定量门槛见 ACC / DOF 标定）。

### REQ-003 — High NoC bandwidth utilization

`refines: CTX-002, CTX-003`

在 iso-bisection 预算下，候选应提高（或至少不显著牺牲）**有效 NoC 带宽利用率** / goodput（相对基线）。禁止以大幅闲置链路换取尾时延而不报告利用率代价。

### REQ-004 — Robustness under system jitter

`refines: CTX-001, CTX-007`

方案须具备 **高健壮性**：注入抖动、时钟/相位噪声代理、控制消息延迟抖动、集合参与者到达时间参差等 **不得破坏正确性**，且尾时延恶化应有界、可解释。预先排图类机制须说明抖动下的重排 / 空隙 / 回退策略；纯静态排表若遇抖动即死锁或错误，视为不满足本 REQ。

### REQ-005 — Fault tolerance friendliness

`refines: CTX-001, CTX-007`

机制应 **容错友好**：单链路/单节点短暂故障或隔离时，应有明确降级路径（绕路、重调度、局部重建排图、失败通知），且故障模型与开销须在报告中写清。不要求完整 ECC/重传协议实现，但须说明与故障模型的接口与最坏额外时延量级。

### REQ-006 — Fair comparison protocol

`refines: CTX-002, CTX-003, CTX-004`

所有 headline 对比固定：8×6、X=7 / Y=9、mesh 64 B/cycle 与 torus 32 B/cycle（iso-wire）、相同流量点与缓冲类型。一次命名对比中最多改变机制族与已声明 DOF；拓扑与 bufferable/bufferless 作为实验因子单独消融。

### REQ-007 — Research report deliverable

`refines: CTX-001, REQ-001, REQ-002, REQ-003, REQ-004, REQ-005`

交付研究报告，至少包含：问题与 iso-wire 设定；基线与三类机制族定义；尾时延 / 利用率 / 抖动 / 故障场景；实验矩阵与结果；何时何种机制占优；威胁效度。

### NNG-001 — Non-goals

`refines: CTX-001`

除非新 DEC/DOF 显式纳入，否则不做：

- 全片 RTL 物理签核 / OpenROAD  
- 片外网络或多插座系统  
- 以改缓存一致性协议为主的研究（可用集体流量作为负载，但不重做目录协议）  
- 擅自改变 8×6、X=7/Y=9，或 mesh 64 B/cycle 而未对 torus 施以一半带宽的 iso-wire 规则  
- 仅优化平均时延而忽略尾部与利用率

### ACC-001 — Collective tail-latency evidence

`refines: REQ-001, REQ-006`
`measurable: true`

对 CTX-005 全部六种集合模式，在至少一种拓扑 × 一种缓冲类型配置下，报告相对基线的 **p95 或 p99（或确定性最坏）完成时延** 及加速比/恶化比。矩阵覆盖率（模式 × 拓扑 × 缓冲 × 主机制族）≥ 0.80。Magic Gap：解析预测与仿真 headline 配置时延 ≤ 2×，并陈述假设。

### ACC-002 — Dynamic P2P latency evidence

`refines: REQ-002, CTX-006`
`measurable: true`

至少一种动态点对点负载 + 一种“集合与动态点对点混合”负载下，报告中位与尾部（p95/p99）端到端时延，并相对基线对比。须说明流量生成器假设。

### ACC-003 — Bandwidth utilization

`refines: REQ-003`
`measurable: true`

对 headline 配置报告链路或对分截面的 **有效利用率 / goodput**（或等价指标），并与基线同表对比。若尾时延改善伴随利用率下降，须在报告中量化该代价。

### ACC-004 — Jitter robustness

`refines: REQ-004`
`measurable: true`

至少一组受控抖动实验（例如请求/消息到达时间加噪声，或控制面延迟抖动）。验收：无死锁/协议破坏；尾时延相对无抖动基线的恶化倍数有记录且机制有解释。预先排图类必须展示抖动下的安全行为（空隙、重排或回退），而非静默错误。

### ACC-005 — Fault-tolerance friendliness check

`refines: REQ-005`
`measurable: true`

至少一种单点故障注入（链路或节点不可用）场景：方案给出可描述的降级/恢复路径，并报告完成时延或失败检测时延上界（解析或仿真均可）。仅写“可扩展容错”而无路径说明 → FAIL。

### ACC-006 — Iso-wire honesty

`refines: CTX-002, CTX-003, REQ-006`
`measurable: true`

任何 mesh vs torus 对比必须写明：mesh **64 B/cycle**、torus **32 B/cycle**、对分带宽一致。未减半 torus 带宽的对比视为本 ACC 失败。

### DOF-001 — Scheduling and algorithm knobs

`refines: CTX-007`

开放探索（结果写入 DEC-*）：

- RG：集中 / 分层仲裁、同步集合 vs 异步多播树 grant、控制网络 in-band vs sideband  
- Push-on-pull：pull 窗口、信用粒度、发送方推送策略、反压  
- 预先排图：时隙长度、树/环/递归加倍嵌入、动态点对点插入空闲时隙的策略  
- 集合算法相位（rabenseifner、二叉树、单向环等）  
- 与动态点对点的 QoS / 优先级 / 隔离（VC、配额、时段隔离）

### DOF-002 — Workload and modeling fidelity

`refines: CTX-005, CTX-006`

消息大小与分块、动态流量生成器参数、混合负载占空比；周期精确 / flit 级 / 粗粒度解析模型均可，但须报告 Magic Gap。优先 directed / dedicated collective+P2P 模型，再视需要上全系统仿真。
