"""Parse ChampSim stdout into SimMetrics fields."""

from __future__ import annotations

import re
from typing import Any

_MPKI_RE = re.compile(
    r"LLC\s+TOTAL\s+ACCESS:[^\n]*MISS:[^\n]*MPKI:\s*([0-9.]+)",
    re.IGNORECASE,
)
_MPKI_ALT = re.compile(r"LLC LOAD\s+.*?MPKI:\s*([0-9.]+)", re.IGNORECASE | re.DOTALL)
_IPC_RE = re.compile(r"cumulative\s+IPC:\s*([0-9.]+)", re.IGNORECASE)
_CYCLES_RE = re.compile(r"cycles?:\s*([0-9]+)", re.IGNORECASE)
_INSTR_RE = re.compile(r"instructions?:\s*([0-9]+)", re.IGNORECASE)
_DRAM_RE = re.compile(
    r"(?:DRAM|AVG)\s+(?:BW|bandwidth)[^\n]*?([0-9.]+)\s*(?:GB/?s|GBps)",
    re.IGNORECASE,
)


def parse_champsim_stdout(text: str) -> dict[str, Any]:
    """Extract mpki / ipc / cycles / dram bandwidth from ChampSim text."""
    out: dict[str, Any] = {}
    m = _MPKI_RE.search(text) or _MPKI_ALT.search(text)
    if m:
        out["mpki"] = float(m.group(1))
    m = _IPC_RE.search(text)
    if m:
        out["ipc"] = float(m.group(1))
    m = _CYCLES_RE.search(text)
    if m:
        out["cycles"] = int(m.group(1))
    m = _INSTR_RE.search(text)
    if m:
        out["instructions"] = int(m.group(1))
    m = _DRAM_RE.search(text)
    if m:
        out["dram_bw_gbps"] = float(m.group(1))
    # Fallback: compute MPKI from LLC miss / instruction counts if present
    if "mpki" not in out:
        miss_m = re.search(r"LLC TOTAL\s+ACCESS:\s*(\d+)\s+HIT:\s*(\d+)\s+MISS:\s*(\d+)", text)
        instr_m = re.search(r"CPU 0 cumulative IPC:.*?instructions:\s*(\d+)", text, re.I)
        if miss_m and instr_m:
            misses = int(miss_m.group(3))
            instr = int(instr_m.group(1))
            if instr > 0:
                out["mpki"] = misses * 1000.0 / instr
    return out
