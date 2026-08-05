#!/usr/bin/env bash
# Register docs/2604.03312v1.pdf as a corpus example (scaffold only).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PDF="$ROOT/docs/2604.03312v1.pdf"
if [[ ! -f "$PDF" ]]; then
  echo "missing $PDF" >&2
  exit 1
fi
cd "$ROOT"
uv run archzero corpus-add-pdf arch-alphazero "$PDF" \
  --title "Computer Architecture's AlphaZero Moment" \
  --family other \
  --label equivalent
uv run archzero corpus
echo "See corpus/EXAMPLE_WORKFLOW.md"
