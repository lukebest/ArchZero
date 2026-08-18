"""Template run_gem5.py harness for Tier3/4 gem5 backend.

Agent or paper profile can overwrite this scaffold. Without a gem5 binary the
backend still fail-closes to UNAVAILABLE under strict_evidence.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from archzero.sim.families import CACHE, family_domain

_HARNESS = '''\
"""ArchZero gem5 harness scaffold — replace with a real SE/FS script.

Reads sim_knobs.json; writes placeholder stats.txt so parse paths are exercised
only when GEM5_BIN is a stub. For real runs, drive gem5 and emit stats.txt.
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
knobs = {}
kp = ROOT / "sim_knobs.json"
if kp.is_file():
    knobs.update(json.loads(kp.read_text(encoding="utf-8")))

# Placeholder stats for dry harness validation (not architectural evidence).
# Do not invent a 12% MPKI cut when knobs omitted the key.
baseline_mpki = 8.0
raw = knobs.get("miss_reduction")
if raw is None:
    reduction = None
    mpki = baseline_mpki
    ipc = 1.5
    tag = "archzero_scaffold=1 no_invented_miss_reduction"
else:
    reduction = float(raw)
    mpki = baseline_mpki * (1.0 - reduction)
    ipc = 1.5 * (1.0 + 0.2 * reduction)
    tag = f"archzero_scaffold=1 miss_reduction={reduction}"

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
    f"# {tag}\\n",
    encoding="utf-8",
)
print(f"archzero gem5 harness scaffold wrote stats ({tag})")
'''

_HARNESS_INAPPLICABLE = '''\
"""ArchZero gem5 harness — inapplicable for this domain.

gem5 SE/FS is a CPU/cache driver. Use the domain analytic backend instead.
This script does not emit CPU or L2 placeholder stats.
"""

from __future__ import annotations

print("archzero gem5 harness inapplicable")
'''


def write_gem5_harness(
    workdir: Path,
    *,
    knobs: dict[str, Any] | None = None,
    overwrite: bool = False,
    family: str | None = None,
    domain: str | None = None,
) -> dict[str, Any]:
    """Write run_gem5.py (+ ensure sim_knobs.json) under workdir."""
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    if knobs:
        kp = workdir / "sim_knobs.json"
        if overwrite or not kp.exists():
            kp.write_text(json.dumps(knobs, indent=2) + "\n", encoding="utf-8")
    fam = family or (knobs or {}).get("family")
    kind = (domain or "").strip().lower()
    off_cache = kind in {"noc", "dataflow", "wafer"} or family_domain(fam) != CACHE
    script = workdir / "run_gem5.py"
    created = False
    md = workdir / "GEM5_HARNESS.md"
    if off_cache:
        resolved = kind if kind in {"noc", "dataflow", "wafer"} else family_domain(fam)
        if overwrite or not script.exists():
            script.write_text(_HARNESS_INAPPLICABLE, encoding="utf-8")
            created = True
        if overwrite or not md.exists():
            md.write_text(
                "# gem5 harness — inapplicable\n\n"
                "gem5 SE/FS is a CPU/cache driver. This candidate's domain is "
                f"`{resolved}`.\n"
                f"Use the `{resolved}` analytic backend instead of writing L2 "
                "miss_rate / IPC placeholder stats.\n",
                encoding="utf-8",
            )
        return {
            "ok": True,
            "path": str(script),
            "created": created,
            "doc": str(md),
            "inapplicable": True,
        }
    if overwrite or not script.exists():
        script.write_text(_HARNESS, encoding="utf-8")
        created = True
    if overwrite or not md.exists():
        md.write_text(
            "# gem5 harness scaffold\n\n"
            "- Script: `run_gem5.py`\n"
            "- Replace with a real gem5 SE/FS driver that emits `stats.txt`.\n"
            "- Placeholder stats are **not** architectural evidence.\n"
            "- Missing `miss_reduction` in knobs writes an iso-baseline "
            "placeholder; it does not invent a 12% cut.\n",
            encoding="utf-8",
        )
    return {
        "ok": True,
        "path": str(script),
        "created": created,
        "doc": str(md),
    }
