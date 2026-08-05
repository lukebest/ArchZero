#!/usr/bin/env bash
# Build ChampSim into tools/champsim (pin a known commit when possible).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DEST="${CHAMPSIM_DIR:-$ROOT/tools/champsim}"
REPO="${CHAMPSIM_REPO:-https://github.com/ChampSim/ChampSim.git}"
PIN="${CHAMPSIM_PIN:-master}"

mkdir -p "$(dirname "$DEST")"
if [[ ! -d "$DEST/.git" ]]; then
  git clone --depth 1 --branch "$PIN" "$REPO" "$DEST" || \
    git clone --depth 1 "$REPO" "$DEST"
fi
cd "$DEST"
./config.sh champsim_config.json 2>/dev/null || ./vcpkg/bootstrap-vcpkg.sh 2>/dev/null || true
if [[ -f config.sh ]]; then
  ./config.sh || true
fi
make -j"${JOBS:-2}" || make -j2 || true

BIN=""
for cand in bin/champsim champsim bin/champsim_bin; do
  if [[ -x "$DEST/$cand" ]]; then BIN="$DEST/$cand"; break; fi
done
if [[ -n "$BIN" ]]; then
  echo "ChampSim binary: $BIN"
  echo "Set in archzero.toml: champsim_bin = \"$BIN\""
else
  echo "WARNING: ChampSim build finished but binary not found under $DEST" >&2
  echo "Install deps per ChampSim README and re-run." >&2
  exit 1
fi
