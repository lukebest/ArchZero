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
| Tier2 | Implemented | 沙箱 + ensemble 多数决 + spec/functional verifier；`-c archzero.paper.toml` 可开 ×3 |
| Tier3 directed / dedicated | Implemented | directed 机制模型；`-c archzero.paper.toml` 开 `llm_dedicated_sim`（自测参与裁决）；ACC（miss/BW/area/Magic Gap） |
| Tier3/4 ChampSim | Optional | 二进制缺省→`UNAVAILABLE`（`strict_evidence`）；见 `tools/CHAMPSIM.md` |
| Tier3/4 gem5 | Scaffold | 需本机 gem5 + agent harness |
| Tier5 RTL | Implemented | pyCircuit DSL→Verilog→Verilator；缺工具→UNAVAILABLE |
| Tier6 Signoff | Deferred | **暂不实现** OpenROAD/sky130；`evaluate_tier6` 恒 UNAVAILABLE |
| Evolution | Implemented | MAP-Elites + reenter；失败消除度量（OpenEvolve 仍为桥接） |
| Corpus | Scaffold | 4 条目（含 1 条真实 PDF 示例）；`corpus` / `corpus-add-pdf` / `corpus-import-wiki` / `corpus-eval-offline`；不发明成功率 |
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

需要 Cursor **Pro 及以上**（Start 计划不含 SDK）。Python **≥ 3.11**，推荐 [`uv`](https://github.com/astral-sh/uv)。

```bash
export CURSOR_API_KEY="cursor_..."   # Dashboard → Integrations
uv sync --extra dev                  # 或: pip install -e ".[dev]"
uv run archzero doctor               # 检查 API key / personas / sim / corpus
```

可选：`uv run archzero init` 写入默认 `archzero.toml` 并创建 `.archzero/` 状态目录。

#### 环境依赖一览

| 层 | 必需？ | 依赖 | 安装 |
|----|--------|------|------|
| 核心 Python | 是 | `cursor-sdk`、`pydantic`、`typer`…（见 `pyproject.toml`） | `uv sync --extra dev` |
| ChampSim（T3/T4 实证） | 可选 | 主机：`g++`/`cmake`/`git`/`curl`/`zip`/`unzip`；**vcpkg**：`fmt`、`cli11`、`nlohmann-json`、`bzip2`、`liblzma`、`zlib`、`catch2` | `JOBS=2 bash tools/setup_champsim.sh`（详 [`tools/CHAMPSIM.md`](tools/CHAMPSIM.md)） |
| Traces | ChampSim 用 | 合成或 DPC 轨迹 | `uv run python benchmarks/fetch_traces.py --synthetic` |
| pyCircuit / RTL（T5） | 可选 | LLVM/MLIR 19、`cmake`、`ninja`、`verilator`、`iverilog` | `bash tools/setup_pycircuit.sh`（需 sudo） |
| gem5 | 可选 / scaffold | 本机 `gem5` 二进制 + `run_gem5.py` harness | 自行安装；缺省 fail-closed |
| Tier6 / Feedback | 延期 | — | 不安装 |

ChampSim 主机包（Ubuntu/Debian）示例：

```bash
sudo apt-get install -y \
  build-essential cmake ninja-build git curl zip unzip pkg-config tar ca-certificates
JOBS=2 bash tools/setup_champsim.sh
```

若出现 `fmt/core.h: No such file`，说明 vcpkg 未装好或 `absolute.options` 过期——重新跑上述脚本即可（勿只装系统 `libfmt9`）。

### 可选工具链（真实仿真 / RTL）

```bash
# ChampSim + 合成 demo traces（完整依赖见 tools/CHAMPSIM.md）
JOBS=2 bash tools/setup_champsim.sh
uv run python benchmarks/fetch_traces.py --synthetic

# pyCircuit (LLVM 19 apt + pycc，建议 JOBS=2，需 sudo)
bash tools/setup_pycircuit.sh
```

在 `archzero.toml` 中：

```toml
[sim]
backend = "champsim"   # stub（默认）| directed | champsim | gem5
champsim_bin = "tools/champsim/bin/champsim"
traces_dir = "benchmarks/traces"

[funnel]
strict_evidence = true   # 真实后端不可用时 T3+ → UNAVAILABLE，绝不假 PASS
ensemble_n = 1
use_verifiers = true
llm_dedicated_sim = false

[rtl]
pycircuit_root = "vendor/pycircuit"
pyc_toolchain_root = ".pycircuit_out/toolchain/install"

[sign]
enabled = false          # Tier6 reserved
```

论文协议更密的漏斗（ensemble×3 + directed + dedicated_sim）用旁路配置，不必改默认文件：

```bash
uv run archzero -c archzero.paper.toml run --spec specs/demo.md --through tier3 --n 5
```

### 2. 自检模型目录与池划分

```bash
uv run archzero models
# uv run archzero models --refresh   # 绕过目录缓存
```

- **默认模型**：全部 Task 默认走池 1 的 `cursor-grok-4.6-high-fast`（可在 `archzero.toml` `[pools].preferred_cursor` 改）
- **池 1 Cursor Models**（含量充裕）：`cursor-grok-4.6-high-fast`、`cursor-grok-4.6`、`cursor-grok-4.5-high-fast`、`composer-2.5`
- **池 2 Other Models**（按 API 计价）：Claude / GPT / Gemini… — 仅在 `routing.routes` 显式指向 `other` 时使用
- **SDK 别名**：配置里可用 `cursor-grok-4.6-high-fast`；调用 `create_agent` 时会映射为 `grok-4.6` + `effort=high` + `fast=true`（`Cursor.models.list()` 只列出基座 id）

### 3. 注册问题包并跑漏斗

参数含义（`--through` / `--n` / 有无 PDF / 何时扩题与进化）见下文 [CLI 参数说明](#cli-参数说明)。

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

扩题后自动再跑漏斗（§5.1 auto-round；**默认关闭**，需显式打开）：

```bash
uv run archzero run --spec specs/demo.md --n 5 \
  --expand-frontier --frontier-offline --auto-round 1
```

进化搜索（**独立命令**，针对已进入 Tier2+ 的候选；不会在 `run` 里自动执行）：

```bash
uv run archzero evolve --campaign <campaign_id>
# uv run archzero evolve --campaign <id> --generations 5 --no-reenter
```

### 4. 研究员日常查看

```bash
uv run archzero doctor                 # API key / personas / sim / corpus 前置检查
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

### 5. Corpus 脚手架（不发明成功率）

```bash
uv run archzero corpus                                    # 状态 / coverage；scaffold 时 success_rate 恒为 null
uv run archzero corpus-add-pdf <entry_id> path/to.pdf \
  --title "…" --family prefetch --label equivalent
uv run archzero corpus-import-wiki /path/to/wiki --dry-run   # 仅导入原始 PDF
uv run archzero corpus-eval-offline --through tier2 --limit 3  # FakeLLM 离线批跑
```

仓库内示例：`bash tools/demo_corpus_pdf.sh`（注册 `docs/2604.03312v1.pdf`）。细节见 [`corpus/README.md`](corpus/README.md) · [`corpus/EXAMPLE_WORKFLOW.md`](corpus/EXAMPLE_WORKFLOW.md)。

看板只读 Generation + Evaluation 状态（遥测层仍暂缓），便于对照论文漏斗进出量与失败模式。  
中文快速入门：[`docs/researcher-quickstart.html`](docs/researcher-quickstart.html)（或 `archzero ui` 后打开 `/quickstart.html`）。

---

## CLI 参数说明

全局选项：任意子命令前可加 `-c` / `--config path.toml`（例如论文协议旁路 `archzero.paper.toml`）。  
常用流程命令：`spec` → `run` →（可选）`frontier` / `evolve` → `report`。完整列表见 `uv run archzero --help`。

### `run`：漏斗主入口

```bash
uv run archzero run --spec specs/demo.md [--pdf paper.pdf] \
  --through tier2 --n 8 \
  [--seed-dir candidates/] \
  [--expand-frontier] [--frontier-offline] [--auto-round 1] \
  [--resume <campaign_id>] [--name "..."] [--max-tokens N]
```

| 参数 | 默认 | 含义 |
|------|------|------|
| `--spec` | （必填，除非 `--resume`） | NDF-lite 问题包路径。Generation / Evaluation 都按其中的 CTX/REQ/ACC/DOF 执行 |
| `--through` | `tier2` | **漏斗停在哪一层**（含该层）。候选从 Tier0 起逐级评估，通过后才进下一层；到 `--through` 后停止。合法值：`tier0`…`tier6`（`tier6` 预留，会得到 `UNAVAILABLE`） |
| `--n` | `10` | **本轮要生成多少个新候选**（在未提供 `--seed-dir` 时）。有 PDF 时做 N 次 clean-room 出题；无 PDF 时做 N 次「只读问题包」独立出题。已有内容哈希重复的会被去重丢掉 |
| `--pdf` | 无 | 可选论文 PDF。见下节「有/无 PDF」 |
| `--seed-dir` | 无 | 若给出目录，则**不再生成**，改为加载其中已有候选 Markdown，直接进漏斗 |
| `--expand-frontier` | 关 | 漏斗跑完后，按 §5.1 做范式扩题（纵向/横向/基础），从失败信号长出新问题包。**默认不扩题** |
| `--frontier-offline` | 关 | 扩题时用确定性理论脚手架，不调用 LLM（需同时开 `--expand-frontier`） |
| `--auto-round N` | `0` | 扩题后，把新问题包再跑漏斗 **N 轮**（仅在开了 `--expand-frontier` 时有意义）。`0` = 只扩题不回流 |
| `--resume ID` | 无 | 续跑已有 campaign：补跑未完成 / 未硬通过 `--through` 的候选；可同时提高 `--through` |
| `--name` | 自动 | campaign 显示名 |
| `--max-tokens` | 无 | 本次进程可选的 Cursor 池 token 上限（写入预算配置） |

#### `--through` 各层在评什么

| 值 | 层 | 作用（简述） |
|----|-----|--------------|
| `tier0` | 硬筛 | LLM 快速否决明显不可行 / 非目标越界 |
| `tier1` | 对抗评审 | 多人设质疑新颖性、正确性、可行性 |
| `tier2` | 解析模型 | 沙箱定量模型 + verifier；默认日常停在这里 |
| `tier3` | 定向/轻仿真 | directed / ChampSim 等（缺后端且 `strict_evidence` 时 → `UNAVAILABLE`） |
| `tier4` | 更重仿真 | 全仿真路径（gem5 等，视配置） |
| `tier5` | RTL | pyCircuit → Verilog → Verilator |
| `tier6` | 签核 | **预留**，不跑 OpenROAD |

例：`--through tier4` 表示候选最多评到 Tier4；没通过 Tier2 的不会被送到 Tier3/4。

#### `--n` 与候选从哪来（优先级）

1. `--seed-dir` 有内容 → 只用种子，**忽略** `--n` / `--pdf` 的生成路径  
2. 否则若给了 `--pdf` → clean-room：读论文 + 对照 `--spec`，生成 `--n` 个机制候选  
3. 否则（只有 `--spec`）→ 不读论文，仅按问题包条款 / DOF 独立生成 `--n` 个候选  

### 有论文 PDF vs 无论文 PDF

| 场景 | 怎么跑 | Generation 行为 | 适用 |
|------|--------|-----------------|------|
| **无 PDF** | `run --spec specs/….md --n 8` | 只根据问题包出题；不依赖某篇基线论文全文 | 自拟问题（如 `specs/noc_request_grant.md`）、纯 DOF 探索 |
| **有 PDF（一次跑完）** | `run --spec … --pdf paper.pdf --n 8` | Clean-room ideation：论文文本进提示，但仍要求相对问题包独立构思机制 | 对照某篇论文挖改进点，并直接进漏斗 |
| **有 PDF（分步）** | `read paper.pdf` → `ideate paper.pdf --spec … -o candidates/` → `run --spec … --seed-dir candidates/` | `read` 只做理解笔记；`ideate` 写出候选文件；`run` 用种子评估 | 想先审阅 insights / 候选再决定是否进漏斗 |

要点：

- **PDF 不是漏斗本身的输入**：Evaluation 始终以 `--spec`（NDF）为宪法；PDF 只影响「候选怎么生成」。  
- **无 PDF 完全合法**：不跑 comprehension/clean-room 论文路径即可。  
- `read` / `ideate` **必须**给 PDF；`run` 的 `--pdf` 可选。

### 何时扩题（frontier），何时进化（evolve）

二者都是 **漏斗之后的可选步骤**，默认 `run` **不会**自动做。

```
run（生成 + Tier0…through）
        │
        ├─ 可选：--expand-frontier [--auto-round N]   ← 改「问题包 / 范式」
        │
        └─ 另开命令：evolve --campaign <id>          ← 改「已有候选机制」
```

| | **扩题 `frontier` / `run --expand-frontier`** | **进化 `evolve`** |
|--|-----------------------------------------------|-------------------|
| **改什么** | 问题空间：新 REQ/DOF/NNG、新范式问题包 | 解空间：在已有候选上变异 / MAP-Elites |
| **输入** | 问题包 +（可选）某 campaign 的失败信号 | 已有 `campaign_id`，且最好已有进入 **Tier2+** 的候选 |
| **何时用** | 漏斗大量失败、发现条款有洞、要换理论透镜或换约束再搜一轮 | 已有若干过 Tier2 的机制，想在 DOF 内继续搜更好的变体 |
| **怎么调用** | 独立：`archzero frontier --spec … [--campaign id] [--offline]`；或挂在 `run`：`--expand-frontier`；回流加 `--auto-round N` | `archzero evolve --campaign <id> [--generations K] [--no-reenter]` |
| **和 `run` 关系** | 可嵌在同一次 `run` 末尾；`--auto-round` 会用扩出的包再开漏斗 | **不在 `run` 内**；对已有 campaign 另跑。默认 `--reenter`：子代再进 Tier0…`reenter_through`（配置项，默认常为 tier2） |

建议节奏：

1. 先 `run --spec … --through tier2 --n …` 看吞吐与失败分类；  
2. 失败像「问题设错了 / 范式不对」→ `--expand-frontier` 或 `frontier`；需要自动再评则加 `--auto-round 1`；  
3. 失败像「机制差一点、DOF 还没搜透」且已有 T2 幸存者 → `evolve --campaign …`；  
4. 不要指望一次 `run` 同时隐式完成扩题和进化——必须显式打开对应开关或命令。

### 其他高频命令（参数要点）

| 命令 | 关键参数 | 作用 |
|------|----------|------|
| `spec PATH` | `--lint/--no-lint`，`--register/--no-register` | 校验并（默认）登记问题包 |
| `read PDF` | `-o insights.md`，`--personas a,b` | 多专家读论文 → 笔记 |
| `ideate PDF` | `--spec`，`-o dir`，`--n` | Clean-room 出题到目录（不跑漏斗） |
| `frontier` | `--spec`，`--campaign`，`--offline`，`-o` | 只做 §5.1 扩题，不跑漏斗 |
| `evolve` | `--campaign`（必填），`--generations`，`--reenter/--no-reenter` | 进化搜索 + 可选回流 |
| `report` | `--campaign`，`-o report.md` | 漏斗吞吐 / 失败分类报告 |
| `status` / `show` | campaign id / candidate id | 查看进度或单个机制全文 |
| `export` | `--campaign`，`-o bundles/` | 可复现产物包 |
| `e2e` | `--spec`，`--through`，`--offline/--online` | 离线友好的演示路径（默认可到 tier5） |

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
  personas/         # 评审/读论文人设（自 Gauntlet 精选迁入）
  funnel/           # Tier0–5 + pipeline
  analytic/         # 共享解析核
  sim/              # stub | directed | champsim | gem5
  corpus/           # clean-room 语料脚手架（ingest / offline batch）
  evolve/           # MAP-Elites + OpenEvolve 适配
  feedback/         # 遥测接口（暂缓）
  report/           # 周级漏斗报告
  store/            # SQLite + 内容寻址产物
  web/              # 本地研究员看板（stdlib HTTP + 单页 UI）
  doctor.py         # 运行前环境自检
  cli.py            # Typer 入口（uv run archzero …）
specs/demo.md       # 示例问题包
corpus/             # 语料 manifest + papers/（见 corpus/README.md）
archzero.paper.toml # 论文协议旁路配置（ensemble / directed / dedicated_sim）
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

见 [`archzero.toml`](archzero.toml)。全局可用 `-c` / `--config` 指定旁路文件（如 [`archzero.paper.toml`](archzero.paper.toml)）。关键项：

- `[pools]` — 模型偏好与池划分
- `[budget]` — 池 2 token/调用上限、并发；可选 `cursor_pool_max_tokens`（或 `run --max-tokens`）
- `[quotas]` — 各 tier 保留名额
- `[funnel]` — `strict_evidence` / `ensemble_n` / `use_verifiers` / `llm_dedicated_sim`
- `[sim] backend` — `stub`（默认）/ `directed` / `champsim` / `gem5`
- `[rtl]` — pyCircuit 根目录与 toolchain
- `[sign] enabled` — Tier6 预留，保持 `false`
- `[evolve] backend` — `mapelites`（默认）/ `openevolve`；`reenter_through` 控制进化回流深度
- `[routing].routes` — Task → `cursor` / `other`（默认全走 cursor）

---

## 验收

```bash
uv run pytest
uv run archzero doctor
uv run archzero models
uv run archzero corpus
uv run archzero run --spec specs/demo.md --through tier2 --n 5
uv run archzero report
```

端到端成功标志：候选写入 SQLite、Tier0–2 有裁决、`report.md` 含吞吐 / 失败分类 / 两池用量。  
可选：`uv run pytest -m champsim`（需先按 `tools/CHAMPSIM.md` 建二进制）；`uv run archzero -c archzero.paper.toml e2e --offline`。

---

## 许可与归属

论文归属原作者（Karthikeyan Sankaralingam / NVIDIA Research）。本仓库为工程实现与对照笔记。各 submodule / 外部仓遵循其自身许可证。
