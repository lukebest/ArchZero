# ChampSim — 环境依赖与构建

Tier3/Tier4 ChampSim 为 **可选** 实证后端。无二进制时 `pytest -m champsim` 会 skip；
`strict_evidence=true` 下缺失二进制 → `UNAVAILABLE`（不会假 PASS）。

## 主机依赖（构建前）

| 工具 | 用途 | Ubuntu / Debian 示例 |
|------|------|----------------------|
| `git` | 克隆 ChampSim + vcpkg submodule | `git` |
| `g++` (C++17) | 编译 | `build-essential` |
| `cmake` | vcpkg / 部分端口 | `cmake` |
| `ninja` | 推荐（vcpkg 加速） | `ninja-build` |
| `curl` | 下载源码包 | `curl` |
| `zip` / `unzip` | vcpkg 解包 | `zip unzip` |
| `tar` | 解包 | 系统自带 |
| `pkg-config` | 部分端口探测 | `pkg-config` |
| 网络 | 首次 clone / `vcpkg install` | — |

一键安装主机包（Ubuntu/Debian）：

```bash
sudo apt-get update
sudo apt-get install -y \
  build-essential cmake ninja-build git curl zip unzip pkg-config \
  tar ca-certificates
```

WSL2：建议可用内存 ≥ 4 GiB；构建时用 `JOBS=1` 或 `JOBS=2`，避免 OOM。

## vcpkg 依赖（脚本自动安装）

ChampSim 用仓库内 **vcpkg submodule** 管理 C++ 库（见 `tools/champsim/vcpkg.json`）：

| 包 | 作用 |
|----|------|
| `fmt` | 格式化（缺则报 `fmt/core.h: No such file`） |
| `cli11` | 命令行 |
| `nlohmann-json` | JSON |
| `bzip2` / `liblzma` / `zlib` | 压缩 trace 读写 |
| `catch2` | ChampSim 自测（可选） |

**不要**只靠系统 `libfmt9`：通常没有开发头文件，且 include 路径由 ChampSim Makefile
的 `vcpkg_installed/<triplet>/include` 注入。

## 构建步骤

```bash
# 推荐：低并行，避免内存打满
JOBS=2 bash tools/setup_champsim.sh
```

脚本会依次：

1. `git clone` ChampSim → `tools/champsim/`（已存在则复用）
2. `git submodule update --init` 拉取 `vcpkg/`
3. `vcpkg/bootstrap-vcpkg.sh` + `vcpkg install`
4. `./config.sh champsim_config.json`
5. **删除并重建** `absolute.options`（避免旧失败留下 `-isystem /include`）
6. `make -j$JOBS` → `tools/champsim/bin/champsim`

环境变量：

| 变量 | 默认 | 含义 |
|------|------|------|
| `JOBS` | `2` | `make -j` |
| `CHAMPSIM_DIR` | `tools/champsim` | 安装目录 |
| `CHAMPSIM_REPO` | ChampSim 官方 git | 源码 URL |
| `CHAMPSIM_PIN` | `master` | 分支 / tag |

## 配置与 traces

```bash
uv run python benchmarks/fetch_traces.py --synthetic
```

```toml
[sim]
backend = "champsim"
champsim_bin = "tools/champsim/bin/champsim"   # 或绝对路径
traces_dir = "benchmarks/traces"
```

```bash
uv run pytest -q -m champsim
uv run archzero doctor   # 应显示 ChampSim binary ready
```

## 常见错误

| 症状 | 原因 | 处理 |
|------|------|------|
| `fmt/core.h: No such file` | 未跑 vcpkg，或 `absolute.options` 指向 `/include` | 重新执行 `JOBS=2 bash tools/setup_champsim.sh`（脚本会 `rm -f absolute.options`） |
| `WARNING: binary not found`（旧脚本） | `make` 失败被 `\|\| true` 吞掉 | 已改为失败即退出；看完整 make 日志 |
| `vcpkg submodule missing` | 浅克隆未 init submodule | `(cd tools/champsim && git submodule update --init)` |
| OOM / 被 kill | 并行过高 | `JOBS=1 bash tools/setup_champsim.sh` |
| `unzip` / `cmake` missing | 主机包不全 | 安装上表 apt 列表 |

手动修复 stale include 路径：

```bash
cd tools/champsim
rm -f absolute.options
make absolute.options
cat absolute.options   # 应含 …/vcpkg_installed/x64-linux/include
make -j2
```

## Mechanism config scaffold

Tier3 会在候选 workdir 写入：

- `champsim_config.json` / `champsim_patch.json` / `MECHANISM_PATCH.md`
- `champsim_src/*.cc|.h`（prefetch/replacement 源码模板）

这是意图脚手架，**不是**已链入机制的实证；真机制需拷入 ChampSim 树并重建。

## Out of scope

- Tier6 OpenROAD/sky130
- 部署遥测 Feedback

相关：`archzero corpus-eval-offline`（无需 ChampSim）。
