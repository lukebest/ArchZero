# ArchZero

面向计算机体系结构的 **自动化 Idea Factory**：对照论文 *Computer Architecture’s AlphaZero Moment*（[arXiv:2604.03312](https://arxiv.org/abs/2604.03312)），实现 Generation + Tier0–5 Evaluation 闭环。  
**Feedback / 部署遥测层仅留接口，实现暂缓。**

论文 PDF 与一页解读：[`docs/2604.03312v1.pdf`](docs/2604.03312v1.pdf) · [`docs/ArchAlphaZero-paper-post.html`](docs/ArchAlphaZero-paper-post.html)

---

## 产品形态（已实现范围）

```
ProblemPackage (NDF-lite)
        │
        ▼
Comprehension → Clean-room Ideation → Frontier 扩题
        │
        ▼
Tier0 → Tier1 → Tier2 → Tier3 → Tier4 → Tier5
 硬筛    对抗评审  解析模型  定向仿真  全仿真   RTL/PPA
        │
        └── Evolution (MAP-Elites / OpenEvolve 适配)
```

| 层 | 状态 |
|----|------|
| 规范 NDF-lite | ✅ 条款 ID / lint / 决策日志 |
| Generation | ✅ 读论文、clean-room 四阶段、三向扩题 |
| Evaluation Tier0–5 | ✅（Tier3/4 默认 stub 仿真；ChampSim/gem5 即插） |
| Evolution | ✅ 内置 MAP-Elites；OpenEvolve 经 OpenAI shim → Cursor SDK |
| LLM | ✅ **仅 Cursor SDK**；池感知路由（Cursor Models 池优先） |
| Feedback 遥测 | ⏸️ 接口 `archzero/feedback/source.py`，未实现 |

---

## 快速开始

### 1. 依赖与 API Key

需要 Cursor **Pro 及以上**（Start 计划不含 SDK）。

```bash
export CURSOR_API_KEY="cursor_..."   # Dashboard → Integrations
uv sync                              # 或: pip install -e ".[dev]"
```

### 2. 自检模型目录与池划分

```bash
uv run archzero models
```

- **池 1 Cursor Models**（含量充裕）：`composer-2.5`、`cursor-grok-4.5` — 高吞吐（Tier0、进化、解析修复…）
- **池 2 Other Models**（按 API 计价）：Claude / GPT / Gemini… — 低频高价值（Tier1 合成、规格、终审）

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
```

看板只读 Generation + Evaluation 状态（遥测层仍暂缓），便于对照论文漏斗进出量与失败模式。  
中文快速入门：[`docs/researcher-quickstart.html`](docs/researcher-quickstart.html)（或 `archzero ui` 后打开 `/quickstart.html`）。

---

## 仓库结构

```
archzero/           # 产品代码
  llm/              # Cursor SDK 客户端、目录、路由、预算、shim
  spec/             # NDF-lite
  generation/       # 理解 / clean-room / frontier（复用 Gauntlet personas）
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
Gauntlet/           # submodule：只读复用人设与协议
docs/analysis-*.md  # 与外部仓库对照分析
```

状态目录（gitignore）：`.archzero/{factory.db,artifacts,transcripts,scratch}`

---

## 与外部仓库的整合方式

| 来源 | 用法 |
|------|------|
| [Gauntlet](https://github.com/lukebest/Gauntlet) | **只读** submodule；复用 `personas/**` 与发散-收敛 / verify-repair 协议；LLM 调用全部改走 Cursor SDK |
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
