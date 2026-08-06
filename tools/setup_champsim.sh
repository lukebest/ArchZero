#!/usr/bin/env bash
# Build ChampSim into tools/champsim.
#
# Host deps (Ubuntu/Debian):
#   sudo apt-get install -y build-essential cmake ninja-build git curl \
#     zip unzip pkg-config tar ca-certificates
# vcpkg (auto): fmt cli11 nlohmann-json bzip2 liblzma zlib catch2
# Docs: tools/CHAMPSIM.md
#
# Usage: JOBS=2 bash tools/setup_champsim.sh
# Env: CHAMPSIM_DIR, CHAMPSIM_REPO, CHAMPSIM_PIN, JOBS
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DEST="${CHAMPSIM_DIR:-$ROOT/tools/champsim}"
REPO="${CHAMPSIM_REPO:-https://github.com/ChampSim/ChampSim.git}"
PIN="${CHAMPSIM_PIN:-master}"
JOBS="${JOBS:-2}"

need_cmd() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "ERROR: missing required command: $1" >&2
    echo "Ubuntu/Debian:" >&2
    echo "  sudo apt-get install -y build-essential cmake ninja-build git curl \\" >&2
    echo "    zip unzip pkg-config tar ca-certificates" >&2
    echo "See tools/CHAMPSIM.md" >&2
    exit 1
  }
}

echo "==> ChampSim setup (JOBS=${JOBS})"
echo "    Host tools: git g++ cmake curl zip unzip tar (+ ninja/pkg-config recommended)"
echo "    Docs: ${ROOT}/tools/CHAMPSIM.md"

need_cmd git
need_cmd g++
need_cmd cmake
need_cmd curl
need_cmd zip
need_cmd unzip
need_cmd tar
# Recommended but not hard-fail (vcpkg can fall back)
if ! command -v ninja >/dev/null 2>&1; then
  echo "NOTE: ninja not found — install ninja-build for faster vcpkg builds" >&2
fi
if ! command -v pkg-config >/dev/null 2>&1; then
  echo "NOTE: pkg-config not found — install pkg-config if vcpkg ports fail" >&2
fi

mkdir -p "$(dirname "$DEST")"
if [[ ! -d "$DEST/.git" ]]; then
  echo "==> Cloning ChampSim ($PIN) into $DEST"
  if ! git clone --depth 1 --branch "$PIN" "$REPO" "$DEST"; then
    echo "Branch $PIN unavailable; cloning default tip"
    git clone --depth 1 "$REPO" "$DEST"
  fi
else
  echo "==> Using existing ChampSim checkout at $DEST"
fi

cd "$DEST"

echo "==> Initializing vcpkg submodule (provides fmt, cli11, …)"
if [[ ! -f vcpkg/bootstrap-vcpkg.sh ]]; then
  # Shallow clones leave an empty vcpkg/ dir; populate the submodule.
  git submodule sync --recursive
  git submodule update --init --depth 1
fi
if [[ ! -f vcpkg/bootstrap-vcpkg.sh ]]; then
  echo "ERROR: vcpkg submodule missing under $DEST/vcpkg" >&2
  echo "Try: (cd \"$DEST\" && git submodule update --init)" >&2
  exit 1
fi

if [[ ! -x vcpkg/vcpkg ]]; then
  echo "==> Bootstrapping vcpkg"
  ./vcpkg/bootstrap-vcpkg.sh -disableMetrics
fi

echo "==> Installing ChampSim dependencies via vcpkg (may take a while)"
./vcpkg/vcpkg install

echo "==> Configuring ChampSim"
if [[ -f champsim_config.json ]]; then
  ./config.sh champsim_config.json
else
  ./config.sh
fi

# ChampSim's Makefile writes absolute.options with no deps; a prior failed build
# may leave `-isystem /include` (empty TRIPLET_DIR). Force regenerate after vcpkg.
rm -f absolute.options
make absolute.options
inc_line="$(cat absolute.options)"
if [[ "$inc_line" != *"vcpkg_installed"* ]]; then
  echo "ERROR: absolute.options missing vcpkg include path:" >&2
  echo "  $inc_line" >&2
  echo "Expected …/vcpkg_installed/<triplet>/include (fmt headers)." >&2
  exit 1
fi

echo "==> Building with make -j${JOBS}"
make -j"${JOBS}"

BIN=""
for cand in bin/champsim champsim bin/champsim_bin; do
  if [[ -x "$DEST/$cand" ]]; then
    BIN="$DEST/$cand"
    break
  fi
done
# Newer layouts sometimes place the binary under .csconfig or bin/<hash>
if [[ -z "$BIN" ]]; then
  while IFS= read -r -d '' cand; do
    BIN="$cand"
    break
  done < <(find "$DEST" -maxdepth 3 -type f -name 'champsim' -perm -111 -print0 2>/dev/null || true)
fi

if [[ -n "$BIN" ]]; then
  echo "ChampSim binary: $BIN"
  echo "Set in archzero.toml:"
  echo "  [sim]"
  echo "  backend = \"champsim\""
  echo "  champsim_bin = \"$BIN\""
  echo "Docs: $ROOT/tools/CHAMPSIM.md"
else
  echo "ERROR: ChampSim build completed but binary not found under $DEST" >&2
  echo "Check make output above; see tools/CHAMPSIM.md." >&2
  exit 1
fi
