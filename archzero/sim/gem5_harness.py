"""Template run_gem5.py harness for Tier3/4 gem5 backend.

Agent or paper profile can overwrite this scaffold. Without a gem5 binary the
backend still fail-closes to UNAVAILABLE under strict_evidence.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_HARNESS = '''\
"""ArchZero gem5 harness scaffold — replace with a real SE/FS script.

Reads sim_knobs.json; writes placeholder stats.txt so parse paths are exercised
only when GEM5_BIN is a stub. For real runs, drive gem5 and emit stats.txt.
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
knobs = {"miss_reduction": 0.12, "extra_bw": 0.02, "area": 0.3}
kp = ROOT / "sim_knobs.json"
if kp.is_file():
    knobs.update(json.loads(kp.read_text(encoding="utf-8")))

# Placeholder stats for dry harness validation (not architectural evidence).
baseline_mpki = 8.0
reduction = float(knobs.get("miss_reduction", 0.12))
mpki = baseline_mpki * (1.0 - reduction)
ipc = 1.5 * (1.0 + 0.2 * reduction)

(ROOT / "baseline_stats.txt").write_text(
    f"system.cpu.ipc {1.5}\\n"
    f"system.l2.overall_miss_rate::total {baseline_mpki / 1000.0}\\n"
    f"simInsts 5000000\\n",
    encoding="utf-8",
)
(ROOT / "stats.txt").write_text(
    f"system.cpu.ipc {ipc}\\n"
    f"system.l2.overall_miss_rate::total {mpki / 1000.0}\\n"
    f"simInsts 5000000\\n"
    f"# archzero_scaffold=1 miss_reduction={reduction}\\n",
    encoding="utf-8",
)
print(f"archzero gem5 harness scaffold wrote stats (reduction={reduction})")
'''


def write_gem5_harness(
    workdir: Path,
    *,
    knobs: dict[str, Any] | None = None,
    overwrite: bool = False,
) -> dict[str, Any]:
    """Write run_gem5.py (+ ensure sim_knobs.json) under workdir."""
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    if knobs:
        kp = workdir / "sim_knobs.json"
        if overwrite or not kp.exists():
            kp.write_text(json.dumps(knobs, indent=2) + "\n", encoding="utf-8")
    script = workdir / "run_gem5.py"
    created = False
    if overwrite or not script.exists():
        script.write_text(_HARNESS, encoding="utf-8")
        created = True
    md = workdir / "GEM5_HARNESS.md"
    if overwrite or not md.exists():
        md.write_text(
            "# gem5 harness scaffold\n\n"
            "- Script: `run_gem5.py`\n"
            "- Replace with a real gem5 SE/FS driver that emits `stats.txt`.\n"
            "- Placeholder stats are **not** architectural evidence.\n",
            encoding="utf-8",
        )
    return {
        "ok": True,
        "path": str(script),
        "created": created,
        "doc": str(md),
    }
