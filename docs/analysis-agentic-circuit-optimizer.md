# agentic_circuit_optimizer 对照论文分析

- **仓库：** [github.com/lukebest/agentic_circuit_optimizer](https://github.com/lukebest/agentic_circuit_optimizer)
- **形态：** 方法论文档 v0.1（无实现代码）
  - `agentic_circuit_optimizer.md` — 前端环
  - `agentic_tao_physical_design_flow.md` — 后端 TAO 物理环
- **关联：** 依赖 [normative_language](https://github.com/lukebest/normative_language)（NDF）与外部 PyCircuit（周期感知 DSL）
- **对照论文：** [arXiv:2604.03312](https://arxiv.org/abs/2604.03312)
- **结论：** **强补 Tier5+（落到硅 / PPA）**；对周级结构探索（Tier0–4）帮助有限。探索旋钮是微架构实现参数，不是加速器新结构。

---

## 1. 仓库是什么

### 1.1 前端环：微架构 → 可测 RTL

设计表示链：

```
ARM ASL（行为级规范）
   → NDF（设计圣经：条款、约束、决策）
   → PyCircuit（周期感知，含流水线结构）
   → RTL（可综合，PPA 可测）
```

循环形态：变异 PyCircuit（流水切分、旁路、预测器、发射宽度等）→ **提交点架构轨迹等价门** → 综合/STA 测 PPA → 决策写回 NDF。

关键方法点：

- 等价定义在**指令提交点**（非逐周期对比 ASL vs 流水线）  
- 判据固定、不随微架构优化漂移（裁判稳定）  
- PyCircuit 自动周期平衡使「移动流水边界」diff 局部化，利于 agent 变异  

### 1.2 后端 TAO 环：物理实现自优化

```
Verilog RTL
   → 门级网表
   → 路径感知网表分割（细粒度 3D 折叠，新 EDA 步骤）
   → 多层布图 / 布局 / 键合 / CTS / 布线
   → 签核（时序、热、IR、DRC/LVS）
```

等价门：LEC（逻辑等价）。目标：单位面积密度与关键路径线长（垂直邻接替代长绕线）。超出 ArchAlphaZero 正文范围，属于硅实现闭环。

---

## 2. 与论文模块映射

| 论文模块 | Circuit Optimizer 作用 | 判断 |
|---------|------------------------|------|
| Tier0–2 想法 / 解析漏斗 | 基本不覆盖 | 弱 |
| Tier3–4 仿真扩展 | 间接（可用仿真作前级；正文重心在 RTL/PPA） | 弱–中 |
| Tier5 RTL / FPGA | 方法论核心：等价门 + PPA 环 | **强** |
| Generation 结构探索 | 旋钮是微架构实现参数，非新加速器结构 | 错位但可借鉴 |
| 失败结构化回流 | 决策记录 + 条款写回 | **强（方法）** |
| 部署遥测 Feedback | 不涉及现网负载遥测 | 弱 |

对「从想法到 tapeout」叙事有帮助；对「每周扫 1 万结构候选」帮助有限（物理环周期太重）。

---

## 3. 与其他仓库的关系

| 层 | 仓库 | 关系 |
|----|------|------|
| 规范 / 裁判 | normative_language | 前端环硬依赖 NDF 作真理来源 |
| 理解 / 出题 | Gauntlet | 上游可供给问题与机制草稿；本仓不替代 |
| 可执行搜索 | OpenEvolve | 可在 PyCircuit/模型代码层做进化；本仓描述的是等价+PPA 环形态 |
| 物理后端 | 本仓 TAO 文档 | 前端 RTL 之后的独立或端到端大环 |

---

## 4. 可借鉴给 Idea Factory 的思想

1. **固定等价裁判** —— 与评估漏斗「失败原因结构化、裁判不漂移」同构。  
2. **动作空间结构化** —— 布尔切分点 / 局部 diff，利于规模化搜索（可与 OpenEvolve 的 candidate 表示结合）。  
3. **测量归因回源** —— PPA 数字归因到流水级 / 条款 ID，对应论文「失败回流生成端」。  
4. **阶段切换** —— 早期轻代理、中期端到端、后期冻结网表只做后端；对应漏斗越往后越贵。

---

## 5. 对 ArchZero 产品的建议

| 优先级 | 动作 |
|--------|------|
| P0–P1 | 仍以 Gauntlet + OpenEvolve 做周级结构探索 |
| P2 | 候选收敛后，按本文前端环接 Tier5（RTL/PPA） |
| P3 | 需要 3D/密度叙事时再评估 TAO 后端环 |
| 勿做 | 用 RTL/3D 环替代想法漏斗 |

---

## 6. 一句话

**agentic_circuit_optimizer =「机制已选定之后」如何在保持功能正确的前提下把实现推到可测 PPA / 物理签核；它承接 Idea Factory 漏斗出口，而不是替代漏斗本身。**
