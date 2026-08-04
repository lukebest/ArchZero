# ArchZero

面向计算机体系结构的 **自动化 Idea Factory** 试验田：对照论文 *Computer Architecture’s AlphaZero Moment*（[arXiv:2604.03312](https://arxiv.org/abs/2604.03312)），拼装理解、出题、评估与落地链路，逼近文中描述的产品最终形态。

论文 PDF 与一页解读：[`docs/2604.03312v1.pdf`](docs/2604.03312v1.pdf) · [`docs/ArchAlphaZero-paper-post.html`](docs/ArchAlphaZero-paper-post.html)

---

## 论文中的产品最终形态：Idea Factory

论文主张：制程缩放放缓后，性能跃迁主要靠**架构**；结构搜索空间远超人力抽样。产品不是「再雇一批架构师」，而是建成可持续运转的 **自动化想法工厂**——人定目标与约束，机器负责广域结构探索与可校准评估。

### 三层闭环（对应论文 Figure 1）

```
┌─────────────┐     ┌──────────────┐     ┌─────────────┐
│ Generation  │ ──► │ Evaluation   │ ──► │ Feedback    │
│ 递归发现引擎 │     │ 分层多智能体  │     │ 部署遥测校准 │
└─────────────┘     └──────────────┘     └─────────────┘
       ▲                                        │
       └──────── 再出题 / 失败回流 ───────────────┘
```

| 层 | 职责 | 最终形态要点 |
|----|------|----------------|
| **Generation** | 从瓶颈与文献抽问题 → 发明多种机制 → 垂直/横向/基础扩问题前沿 | 稀缺的是问题表述，不是单个点子；解法可批量生成 |
| **Evaluation** | Tier0→5 保真度递增漏斗；失败结构化回流生成端 | 周吞吐量级：约 1 万候选 → 落地候选约 1–2 |
| **Feedback** | 现网遥测校准各层模型；负载漂移提前出题 | 护城河是**校准过的评估基建 + 遥测**，不是可逆向的点子 |

### 评估漏斗（Evaluation 内部）

| 档位 | 作用 | 典型周吞吐（论文示例） |
|------|------|------------------------|
| Tier 0 | 第一性原理质性筛 | 10k → 2k |
| Tier 1 | 对抗式多专家评审 | → 500 |
| Tier 2 | 解析模型（如 LIMINAL） | → 100 |
| Tier 3 | 专用 / Agent 构建仿真 | → 20 |
| Tier 4 | ChampSim / gem5 等全仿真集成 | → 5 |
| Tier 5 | 必要时 RTL / FPGA | → 1–2 |

瓶颈从「能否实现」变为「是否问对问题」。

### 最终产品应具备的能力（验收视角）

1. **问题工厂**：结构化问题包（上下文 / 症状 / 约束），可版本化、可复现实验协议（含 clean-room 机制生成评测）。  
2. **周级漏斗**：统一 Candidate 对象，自动过 Tier0–5（或子集），淘汰率与失败模式可观测。  
3. **快速量化**：论文/机制 → 可执行解析或仿真，分钟–小时级而非人月。  
4. **闭环校准**：部署侧遥测持续修正评估误差，并驱动下一轮出题。  
5. **角色上移**：人类定义目标、约束与可行性边界；机器承担广域搜索与实现试错。  
6. **可选落地出口**：高价值候选进入 RTL / 物理实现环，在固定功能裁判下优化 PPA。

作者时间判断（论文）：约两年内，纯人工驱动的架构探索将显著边缘化——**谁先建成工厂，谁定义下一阶段加速器节奏**。

---

## 本仓库如何逼近该形态

| 层 | 组件 | 状态 / 角色 |
|----|------|-------------|
| 规范与裁判 | [normative_language](https://github.com/lukebest/normative_language)（NDF 提案） | 问题、约束、验收、决策的 lifetime 圣经 |
| 理解 / 出题 / 初评 | [Gauntlet](https://github.com/lukebest/Gauntlet)（submodule `Gauntlet/`） | 读论文、对抗评审、初版解析模型（`perf.py`） |
| 可执行搜索 | [openevolve](https://github.com/lukebest/openevolve) | MAP-Elites 进化实现；适合 Tier2–4 后端 |
| 硅落地环 | [agentic_circuit_optimizer](https://github.com/lukebest/agentic_circuit_optimizer)（方法论文档） | ASL→NDF→PyCircuit→RTL→物理；承接漏斗出口 |

**拼法：** NDF 定规矩 → Gauntlet 出题与初筛 → OpenEvolve 规模化搜实现 → Circuit Optimizer 路线接 Tier5/物理（候选已收敛后）。

---

## 仓库分析文档

| 文档 | 内容 |
|------|------|
| [docs/analysis-gauntlet.md](docs/analysis-gauntlet.md) | Gauntlet vs 论文覆盖度与缺口 |
| [docs/analysis-openevolve.md](docs/analysis-openevolve.md) | OpenEvolve 对 Idea Factory 的价值 |
| [docs/analysis-normative-language.md](docs/analysis-normative-language.md) | NDF 对问题/裁判层的价值 |
| [docs/analysis-agentic-circuit-optimizer.md](docs/analysis-agentic-circuit-optimizer.md) | 前端/后端硅环与 Tier5+ 定位 |

---

## 快速入口

```bash
# 论文与一页解读
open docs/ArchAlphaZero-paper-post.html   # 或浏览器打开

# Gauntlet submodule（若尚未初始化）
git submodule update --init --recursive
```

---

## 许可与归属

论文归属原作者（Karthikeyan Sankaralingam / NVIDIA Research）。本仓库文档为内部对照与工程拼装笔记，非正式译文或官方实现声明。各 submodule / 外部仓遵循其自身许可证。
