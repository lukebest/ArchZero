"""Parse gem5 stats.txt into SimMetrics fields."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any


def parse_stats_txt(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    text = path.read_text(encoding="utf-8", errors="replace")
    return parse_stats_text(text)


def parse_stats_text(text: str) -> dict[str, Any]:
    kv: dict[str, float] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or line.startswith("-"):
            continue
        m = re.match(r"^(\S+)\s+([-+]?[0-9]*\.?[0-9]+(?:[eE][-+]?[0-9]+)?)", line)
        if m:
            try:
                kv[m.group(1)] = float(m.group(2))
            except ValueError:
                continue

    out: dict[str, Any] = {}
    # Common gem5 keys
    if "system.cpu.ipc" in kv:
        out["ipc"] = kv["system.cpu.ipc"]
    elif "system.cpu.cpi" in kv and kv["system.cpu.cpi"] > 0:
        out["ipc"] = 1.0 / kv["system.cpu.cpi"]

    if "simInsts" in kv:
        out["instructions"] = int(kv["simInsts"])
    if "simTicks" in kv:
        # ticks → cycles depends on tick rate; leave as cycles proxy
        out["cycles"] = int(kv.get("system.cpu.numCycles") or kv["simTicks"])

    # L2 / LLC miss rate → MPKI approximation
    misses = (
        kv.get("system.l2.overallMisses::total")
        or kv.get("system.l2.demandMisses::total")
        or kv.get("system.llc.overallMisses::total")
    )
    instr = out.get("instructions") or kv.get("simInsts")
    if misses is not None and instr and instr > 0:
        out["mpki"] = float(misses) * 1000.0 / float(instr)

    bw = kv.get("system.mem_ctrls.bwTotal::total") or kv.get(
        "system.mem_ctrl.dram.bwTotal::total"
    )
    if bw is not None:
        # gem5 often reports bytes/s — convert roughly to GB/s
        out["dram_bw_gbps"] = float(bw) / 1e9

    out["raw_keys"] = {k: kv[k] for k in list(kv)[:40]}
    return out
