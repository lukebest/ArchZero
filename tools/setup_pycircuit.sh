#!/usr/bin/env bash
# Clone / update pyCircuit submodule and build pycc with LLVM 19 (apt packages).
# Memory-constrained hosts: use JOBS=2 (default).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VENDOR="$ROOT/vendor/pycircuit"
JOBS="${JOBS:-2}"
LLVM_VERSION="${LLVM_VERSION:-19}"

mkdir -p "$ROOT/vendor"
if [[ ! -d "$VENDOR/.git" ]]; then
  if [[ -f "$ROOT/.gitmodules" ]] && grep -q pycircuit "$ROOT/.gitmodules" 2>/dev/null; then
    git -C "$ROOT" submodule update --init --recursive vendor/pycircuit
  else
    git clone --depth 1 https://github.com/lukebest/pyCircuit.git "$VENDOR"
  fi
fi

echo "Installing LLVM/MLIR ${LLVM_VERSION} (requires sudo)…"
if ! command -v "llvm-config-${LLVM_VERSION}" >/dev/null 2>&1; then
  wget -q https://apt.llvm.org/llvm.sh -O /tmp/llvm.sh
  chmod +x /tmp/llvm.sh
  sudo /tmp/llvm.sh "${LLVM_VERSION}"
  sudo apt-get install -y \
    "llvm-${LLVM_VERSION}-dev" \
    "mlir-${LLVM_VERSION}-tools" \
    "libmlir-${LLVM_VERSION}-dev" \
    cmake ninja-build clang verilator iverilog || true
fi

export LLVM_CONFIG="/usr/lib/llvm-${LLVM_VERSION}/bin/llvm-config"
export PATH="/usr/lib/llvm-${LLVM_VERSION}/bin:$PATH"
export CMAKE_BUILD_PARALLEL_LEVEL="$JOBS"

cd "$VENDOR"
if [[ -x flows/scripts/pyc ]]; then
  bash flows/scripts/pyc build \
    --llvm-config "$LLVM_CONFIG" \
    --build-dir "$ROOT/.pycircuit_out/toolchain/build" \
    --install-prefix "$ROOT/.pycircuit_out/toolchain/install" || {
      echo "pyc build failed — try lower JOBS=1" >&2
      exit 1
    }
else
  echo "flows/scripts/pyc missing; configure via Makefile" >&2
  make -C "$VENDOR" tools CMAKE_BUILD_PARALLEL_LEVEL="$JOBS" || true
fi

echo "Toolchain: $ROOT/.pycircuit_out/toolchain/install"
echo "Set in archzero.toml:"
echo "  [rtl]"
echo "  pycircuit_root = \"vendor/pycircuit\""
echo "  pyc_toolchain_root = \".pycircuit_out/toolchain/install\""
