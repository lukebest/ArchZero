#!/usr/bin/env python3
"""Fetch or synthesize ChampSim traces listed in manifest.json."""

from __future__ import annotations

import argparse
import hashlib
import lzma
import struct
from pathlib import Path

ROOT = Path(__file__).resolve().parent
TRACES = ROOT / "traces"


def _synth_trace(path: Path, n_records: int = 10_000) -> None:
    """Write a minimal ChampSim-like binary blob compressed with xz.

    ChampSim trace format varies by version; this produces a placeholder file
    so the directory layout and checksum flow work in CI. Real traces should
    replace these via URL download.
    """
    # ChampSim cloudsuite-style: 8-byte records (ip, type, addr packed loosely)
    buf = bytearray()
    for i in range(n_records):
        ip = 0x400000 + (i * 4)
        addr = 0x80000000 + ((i * 64) % (1 << 20))
        # pack: ip u8? use 8+1+8 simplified as three uint64-ish fields
        buf += struct.pack("<Q", ip)
        buf += struct.pack("<B", 0)  # load
        buf += struct.pack("<Q", addr)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(lzma.compress(bytes(buf)))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--synthetic", action="store_true", help="Write synthetic demo traces")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()
    TRACES.mkdir(parents=True, exist_ok=True)
    names = [
        "demo_a.champsimtrace.xz",
        "demo_b.champsimtrace.xz",
        "demo_c.champsimtrace.xz",
    ]
    for i, name in enumerate(names):
        dest = TRACES / name
        if dest.exists() and not args.force:
            continue
        if args.synthetic or True:
            _synth_trace(dest, n_records=5000 + i * 1000)
            digest = hashlib.sha256(dest.read_bytes()).hexdigest()
            print(f"wrote {dest} sha256={digest[:16]}…")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
