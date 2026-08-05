"""RTL equivalence gates: Verilator vs C++ sim, optional Yosys LEC."""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class EquivResult:
    ok: bool
    unavailable: bool = False
    method: str = ""
    summary: str = ""
    details: dict[str, Any] = field(default_factory=dict)
    tool_versions: dict[str, str] = field(default_factory=dict)


def _verilator_version() -> str | None:
    path = shutil.which("verilator")
    if not path:
        return None
    try:
        out = subprocess.run(
            [path, "--version"], capture_output=True, text=True, timeout=10, check=False
        )
        return (out.stdout or out.stderr).splitlines()[0][:120]
    except Exception:  # noqa: BLE001
        return path


def compare_commit_traces(
    workdir: Path,
    *,
    left: Path | None = None,
    right: Path | None = None,
) -> EquivResult:
    """Compare commit-point traces if present; else UNAVAILABLE (not a PASS)."""
    versions = {}
    vv = _verilator_version()
    if vv:
        versions["verilator"] = vv

    left = left or workdir / "trace_cpp.commit"
    right = right or workdir / "trace_verilator.commit"
    if not left.is_file() or not right.is_file():
        # Look for any *.commit pair
        commits = sorted(workdir.rglob("*.commit"))
        if len(commits) >= 2:
            left, right = commits[0], commits[1]
        else:
            return EquivResult(
                ok=False,
                unavailable=True,
                method="commit_trace",
                summary="no commit-point traces produced by testbench",
                tool_versions=versions,
            )

    a = left.read_text(encoding="utf-8", errors="replace").splitlines()
    b = right.read_text(encoding="utf-8", errors="replace").splitlines()
    # Normalize whitespace
    a = [ln.strip() for ln in a if ln.strip() and not ln.startswith("#")]
    b = [ln.strip() for ln in b if ln.strip() and not ln.startswith("#")]
    n = min(len(a), len(b))
    mismatches = sum(1 for i in range(n) if a[i] != b[i])
    mismatches += abs(len(a) - len(b))
    ok = mismatches == 0 and n > 0
    return EquivResult(
        ok=ok,
        unavailable=False,
        method="commit_trace",
        summary=f"commit traces compared: n={n} mismatches={mismatches}",
        details={"n": n, "mismatches": mismatches, "left": str(left), "right": str(right)},
        tool_versions=versions,
    )


def optional_yosys_lec(
    workdir: Path,
    gold: Path,
    gate: Path,
    *,
    enabled: bool = True,
) -> EquivResult:
    """Optional Yosys LEC. Missing yosys → skip (unavailable), never PASS."""
    if not enabled:
        return EquivResult(
            ok=False,
            unavailable=True,
            method="yosys_lec",
            summary="yosys LEC disabled",
        )
    if not shutil.which("yosys"):
        return EquivResult(
            ok=False,
            unavailable=True,
            method="yosys_lec",
            summary="yosys not installed — LEC skipped",
        )
    if not gold.is_file() or not gate.is_file():
        return EquivResult(
            ok=False,
            unavailable=True,
            method="yosys_lec",
            summary="missing gold/gate netlists for LEC",
        )
    script = workdir / "lec.ys"
    script.write_text(
        f"read_verilog {gold}\n"
        f"rename -top gold\n"
        f"design -stash gold\n"
        f"read_verilog {gate}\n"
        f"rename -top gate\n"
        f"design -stash gate\n"
        f"design -copy-from gold -as gold gold\n"
        f"design -copy-from gate -as gate gate\n"
        f"equiv_make gold gate equiv\n"
        f"equiv_simple equiv\n"
        f"equiv_status -assert\n",
        encoding="utf-8",
    )
    try:
        proc = subprocess.run(
            ["yosys", "-s", str(script)],
            cwd=str(workdir),
            capture_output=True,
            text=True,
            timeout=300,
            check=False,
        )
    except Exception as exc:  # noqa: BLE001
        return EquivResult(
            ok=False,
            unavailable=False,
            method="yosys_lec",
            summary=f"yosys LEC error: {exc}",
        )
    ok = proc.returncode == 0
    return EquivResult(
        ok=ok,
        unavailable=False,
        method="yosys_lec",
        summary=f"yosys LEC returncode={proc.returncode}",
        details={"log_tail": (proc.stdout + proc.stderr)[-2000:]},
        tool_versions={"yosys": "present"},
    )
