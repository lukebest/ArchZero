# ArchZero

面向计算机体系结构的 **自动化 Idea Factory**：对照论文 *Computer Architecture’s AlphaZero Moment*（[arXiv:2604.03312](https://arxiv.org/abs/2604.03312)），实现 Generation + Tier0–5 Evaluation 闭环，并预留 Tier6 物理签核。  
**Feedback / 部署遥测层仅留接口，实现暂缓。Tier6 签核仅预留，不执行 OpenROAD/sky130。**

论文 PDF 与一页解读：[`docs/2604.03312v1.pdf`](docs/2604.03312v1.pdf) · [`docs/ArchAlphaZero-paper-post.html`](docs/ArchAlphaZero-paper-post.html)

---

## 成熟度矩阵

| 层 | 状态 | 说明 |
|----|------|------|
| NDF-lite 规范 | Implemented | CTX/REQ/NNG/ACC/DOF/DEC + lint；ACC 数值解析进 T2–T4 |
| Generation | Implemented | 读论文、clean-room、§5.1 frontier、auto-round |
| Tier0 / Tier1 | Implemented | LLM 硬筛 + 多专家；provenance / evidence |
| Tier2 | Implemented | 沙箱 + ensemble 多数决 + spec/functional verifier；`archzero.paper.toml` 可开 ×3 |
| Tier3 / Tier4 | Implemented / Stub | stub / directed / ChampSim；dedicated_sim 生成+自测；`strict_evidence` |
| Tier5 RTL | Implemented | pyCircuit DSL→Verilog→Verilator；缺工具→UNAVAILABLE |
| Tier6 Signoff | Planned (reserved) | **暂不实现** OpenROAD/sky130；`evaluate_tier6` 恒 UNAVAILABLE |
| Evolution | Implemented | MAP-Elites + reenter；失败消除度量 |
| Corpus | Scaffold | `corpus-add-pdf` / `corpus-eval-offline`；不发明成功率 |
| Scale-out | Prototype | Jaccard 去重 + `LocalWorkerPool`（单机） |
| Feedback 遥测 | Deferred | **暂不实现**；`NullFeedbackSource` only |

```
ProblemPackage (NDF-lite)
        │
        ▼
Comprehension → Clean-room Ideation → Frontier 扩题
        │
        ▼
Tier0 → Tier1 → Tier2 → Tier3 → Tier4 → Tier5 ⇢ Tier6(reserved)
 硬筛    对抗评审  解析模型  ChampSim  全仿真   pyCircuit RTL   物理签核
        │
        └── Evolution (MAP-Elites / OpenEvolve) → 回流漏斗
```

---

## 快速开始

### 1. 依赖与 API Key

需要 Cursor **Pro 及以上**（Start 计划不含 SDK）。

```bash
export CURSOR_API_KEY="cursor_..."   # Dashboard → Integrations
uv sync --extra dev                  # 或: pip install -e ".[dev]"
```

### 可选工具链（真实仿真 / RTL）

```bash
# ChampSim + 合成 demo traces
bash tools/setup_champsim.sh
python benchmarks/fetch_traces.py --synthetic

# pyCircuit (LLVM 19 apt + pycc，建议 JOBS=2)
bash tools/setup_pycircuit.sh
```

在 `archzero.toml` 中：

```toml
[sim]
backend = "champsim"   # 或 stub / gem5
champsim_bin = "tools/champsim/bin/champsim"
traces_dir = "benchmarks/traces"

[funnel]
strict_evidence = true   # 真实后端不可用时 T3+ → UNAVAILABLE，绝不假 PASS

[rtl]
pycircuit_root = "vendor/pycircuit"
pyc_toolchain_root = ".pycircuit_out/toolchain/install"

[sign]
enabled = false          # Tier6 reserved
```

### 2. 自检模型目录与池划分

```bash
uv run archzero models
```

- **默认模型**：全部 Task 默认走池 1 的 `cursor-grok-4.5-high-fast`（可在 `archzero.toml` `[pools].preferred_cursor` 改）
- **池 1 Cursor Models**（含量充裕）：`cursor-grok-4.5-high-fast`、`cursor-grok-4.5`、`composer-2.5`
- **池 2 Other Models**（按 API 计价）：Claude / GPT / Gemini… — 仅在 `routing.routes` 显式指向 `other` 时使用

### 3. 注册问题包并跑漏斗

```bash
uv run archzero spec specs/demo.md
uv run archzero run --spec specs/demo.md --through tier2 --n 8
uv run archzero report --out report.md
```

有论文 PDF 时：

```bash
uv run archzero read path/to/paper.pdf -o insights.md
uv run archzero ideate path/to/paper.pdf --spec specs/demo.md -o candidates/
uv run archzero run --spec specs/demo.md --pdf path/to/paper.pdf --through tier4
```

进化搜索（对已进入 Tier2 的候选）：

```bash
uv run archzero evolve --campaign <campaign_id>
```

### 4. 研究员日常查看

```bash
uv run archzero doctor                 # API key / personas / sim 前置检查
uv run archzero seed-demo              # 离线示例 campaign（无需 LLM，立刻可看漏斗）
uv run archzero campaigns              # 列出 campaign
uv run archzero status <campaign_id>   # 漏斗吞吐快照
uv run archzero show <candidate_id>    # 机制全文 + tier 历史 + 失败归因
uv run archzero ui                     # 本地看板 http://127.0.0.1:8787/
uv run archzero new-spec \
  --title "LLM Decode Bandwidth" \
  --workload "Llama-70B decode" \
  --symptom "L2 MPKI spikes" \
  --constraint "<=0.5mm^2" \
  --out specs/                       # 脚手架生成 NDF-lite 问题包并 lint
uv run archzero export --campaign <id> --out bundles/   # 可复现产物包
uv run archzero compare <campA> <campB>                 # 两轮漏斗 / 失败 taxonomy 对比
uv run archzero next-questions --campaign <id>          # 失败回流成下一轮开放问题（Feedback 替身）
uv run archzero frontier --spec specs/demo.md --offline # §5.1 纵向/横向/基础扩题 + 理论透镜
uv run archzero run --spec specs/demo.md --n 5 \
  --expand-frontier --frontier-offline                  # 漏斗后自动范式扩题
uv run archzero run --resume <campaign_id> --through tier3  # 断点续跑
uv run archzero e2e --spec specs/demo.md --offline          # 离线演示到 Tier5
uv run archzero reproduce bundles/<exported>/               # 校验可复现包 + stub 回放
```

看板只读 Generation + Evaluation 状态（遥测层仍暂缓），便于对照论文漏斗进出量与失败模式。  
中文快速入门：[`docs/researcher-quickstart.html`](docs/researcher-quickstart.html)（或 `archzero ui` 后打开 `/quickstart.html`）。

---

## NDF-lite 问题包编写规则

Idea Factory 的「宪法」是一份 Markdown **ProblemPackage**（NDF-lite）。Generation 按条款探索，Evaluation 按条款裁决；条款 ID 应稳定，便于失败归因与跨轮复用。完整示例见 [`specs/demo.md`](specs/demo.md)；脚手架：`uv run archzero new-spec …`；校验：`uv run archzero spec path/to/spec.md`。

### 文件结构

```markdown
---
id: pp-demo-cache
title: "Demo — reduce L2 miss penalty under LLM decode traffic"
open_questions:
  - Can a small predictor cut MPKI without blowing area?
decisions: []
workload: "LLM decode / token generation"
---

# <与 title 一致的标题>

### CTX-001 — Workload context
…
### REQ-001 — Miss-rate reduction
`refines: CTX-001`
…
```

| 区域 | 规则 |
|------|------|
| YAML frontmatter | 建议含 `id`、`title`；可选 `open_questions`、`decisions`、`workload` 等元数据 |
| 正文标题 | `# …` 一级标题；条款用三级标题 |
| 条款标题格式 | `### <KIND>-<NNN> — <短标题>`（`—` / `-` / `:` 均可） |
| 条款 ID | `CTX\|REQ\|ACC\|DOF\|NNG\|DEC` + `-` + 数字，例如 `REQ-001`；**全局唯一、创建后勿改号** |
| 精化链接 | 正文内一行 `` `refines: REQ-001, REQ-002` ``（逗号分隔多个父条款） |
| 可测标记 | ACC 可写 `` `measurable: true` ``（ACC 默认即视为可测） |

### 条款种类（KIND）

| 前缀 | 全称 | 含义 | 写什么 |
|------|------|------|--------|
| **CTX** | Context | 问题成立的背景与边界条件 | 负载特征、基线症状、硬件信封（工艺/面积/带宽/延迟预算）、假设与场景。**不写**「应当达成什么」 |
| **REQ** | Requirement | 规范性要求（shall / must / must not） | 相对基线的目标与硬约束。用可核对的指标与阈值（如「L2 MPKI ≥15% 下降」「带宽增加 ≤5% @ iso-IPC」） |
| **NNG** | Non-goal | 明确不做 / 不改的范围 | 防止搜索漂移：如「不改 ISA / 不动 NoC / 不要求 OS 改动」。与 REQ 对立面互补 |
| **ACC** | Acceptance | 可执行的验收标准 | 怎样算通过某一 REQ：解析模型阈值、Magic Gap、仿真 workload、对比基线。应 `refines` 到对应 REQ，并尽量可测 |
| **DOF** | Degree of freedom | 合法探索空间 | 允许 Generation / Evolution 搜索的旋钮：表项大小、历史长度、机制族（prefetch vs filter）等。**写开放空间，不写单一解** |
| **DEC** | Decision | 已冻结的设计决策 | 「为什么这样定」的沉淀；也可放在 frontmatter `decisions`。减少重复争论，后续轮次默认遵守 |

### 条款之间的关系

推荐精化树（`refines`）：

```
CTX（场景 / 硬件信封）
 └─ REQ（目标与约束）
     └─ ACC（如何证明 REQ 成立）
NNG、DOF、DEC 通常挂在包级；DOF 可 refines 相关 CTX/REQ
```

- **CTX → REQ**：要求必须锚定在某个场景或资源信封上。  
- **REQ → ACC**：每个重要 REQ 至少一条可测 ACC；一条 ACC 可 refine 多条 REQ。  
- **NNG**：切开「优化空间」与「禁区」，避免工厂把非目标当自由度。  
- **DOF**：告诉进化/出题「可以动哪里」；漏斗失败后扩题常沿着 DOF 或 NNG 边界推进。  
- **DEC**：一旦写入，视为本 campaign 的既定事实，除非显式修订并记新 DEC。

### 写作规范

1. **一条条款一件事**；短标题说明意图，正文写规范内容。  
2. **REQ / ACC 用规范性用语**：`shall` / `must` / `must not`；避免「尽量」「可能更好」。  
3. **数字与基线成对出现**：写清度量、对比对象、工作负载套件（或合成 trace 假设）。  
4. **ACC 必须可判定**：解析模型（Tier2）、stub/ChampSim/gem5（Tier3/4）等能给出 pass/fail；注明 Magic Gap 等容差。  
5. **DOF 写维度与范围**，不写具体获胜配置；具体配置属于 Candidate，不属于问题包。  
6. **ID 稳定**：交叉引用、失败 taxonomy、`next-questions` 都靠 ID；改文可以，改号会断链。  
7. **至少包含**：≥1 条 `REQ-*`、≥1 条 `ACC-*`（lint 强制）；实践上还应有 CTX，并建议有 NNG + DOF。

### Lint 会检查什么

`archzero spec <file>` / `new-spec` 后自动 lint，常见问题：

- 重复条款 ID  
- `refines` 指向不存在的 ID  
- 缺少 `REQ-*` 或 `ACC-*`  
- ACC 正文难以看出可测性（无 measure/shall，且未标 `measurable`）  
- 空 `title`

### 最小可用骨架

```markdown
---
id: pp-my-problem
title: "短标题：瓶颈 + 场景"
open_questions:
  - 最值得先搜的 DOF 是哪一维？
---

# 短标题：瓶颈 + 场景

### CTX-001 — Workload / symptom
<负载与症状>

### CTX-002 — Hardware envelope
`refines: CTX-001`
<面积 / 带宽 / 延迟等信封>

### REQ-001 — Primary objective
`refines: CTX-001`
The mechanism shall <可量化目标> versus the unmodified baseline.

### REQ-002 — Hard constraint
`refines: CTX-002`
The mechanism must not <硬约束>.

### NNG-001 — Non-goals
Do not <明确不做的事>.

### ACC-001 — Analytic acceptance
`refines: REQ-001`
`measurable: true`
Tier2 analytic model shall show <目标>；Magic Gap ≤ 2× if sim available.

### ACC-002 — Simulation acceptance
`refines: REQ-001, REQ-002`
`measurable: true`
Stub or ChampSim/gem5 shall confirm the above on <workload>.

### DOF-001 — Search space
Open degrees of freedom: <可搜索维度列表>.
```

---

## 仓库结构

```
archzero/           # 产品代码
  llm/              # Cursor SDK 客户端、目录、路由、预算、shim
  spec/             # NDF-lite
  generation/       # 理解 / clean-room / frontier
  personas/         # 评审/读论文人设（自 Gauntlet 精选迁入，引擎未使用）
  funnel/           # Tier0–5 + pipeline
  analytic/         # 共享解析核
  sim/              # stub | champsim | gem5
  evolve/           # MAP-Elites + OpenEvolve 适配
  feedback/         # 遥测接口（暂缓）
  report/           # 周级漏斗报告
  store/            # SQLite + 内容寻址产物
  web/              # 本地研究员看板（stdlib HTTP + 单页 UI）
  doctor.py         # 运行前环境自检
specs/demo.md       # 示例问题包
docs/analysis-*.md  # 与外部仓库对照分析
```

状态目录（gitignore）：`.archzero/{factory.db,artifacts,transcripts,scratch}`

---

## 与外部仓库的整合方式

| 来源 | 用法 |
|------|------|
| [Gauntlet](https://github.com/lukebest/Gauntlet) | **已移除 submodule**。引擎（Anthropic/Gemini 脚本）未被调用；核心出题/评审/量化已在 ArchZero 用 Cursor SDK 重写。精选 `personas/` 迁入 `archzero/personas/` |
| [openevolve](https://github.com/lukebest/openevolve) | 可选 vendored 到 `vendor/openevolve`；经 `archzero/llm/shim.py`（OpenAI 兼容）转发到 Cursor；否则用内置 MAP-Elites |
| [normative_language](https://github.com/lukebest/normative_language) | NDF 思想落地为 `archzero/spec`（轻量可运行版） |
| [agentic_circuit_optimizer](https://github.com/lukebest/agentic_circuit_optimizer) | Tier5：提交点等价门 + PPA 钩子（Yosys/OpenSTA 可选） |

分析文档见 [`docs/`](docs/)。

---

## 配置

见 [`archzero.toml`](archzero.toml)。关键项：

- `[pools]` — 模型偏好与池划分
- `[budget]` — 池 2 token/调用上限、并发
- `[quotas]` — 各 tier 保留名额
- `[sim] backend` — `stub`（默认）/ `champsim` / `gem5`
- `[evolve] backend` — `mapelites`（默认）/ `openevolve`

---

## 验收

```bash
uv run pytest
uv run archzero models
uv run archzero run --spec specs/demo.md --through tier2 --n 5
uv run archzero report
```

端到端成功标志：候选写入 SQLite、Tier0–2 有裁决、`report.md` 含吞吐 / 失败分类 / 两池用量。

---

## 许可与归属

论文归属原作者（Karthikeyan Sankaralingam / NVIDIA Research）。本仓库为工程实现与对照笔记。各 submodule / 外部仓遵循其自身许可证。
