"""Sandbox execution for LLM-generated analytic model.py."""

from __future__ import annotations

import json
import resource
import subprocess
import sys
import textwrap
from pathlib import Path


def run_model_sandboxed(
    model_path: Path,
    *,
    timeout_s: int = 30,
    mem_mb: int = 512,
) -> tuple[dict | None, str | None]:
    """Execute run_model() in a subprocess with timeout and memory limit."""
    if not model_path.is_file():
        return None, f"missing model: {model_path}"

    runner = textwrap.dedent(
        f"""
        import json, sys, runpy
        ns = runpy.run_path({str(model_path)!r})
        if "run_model" not in ns:
            print(json.dumps({{"__error__": "model.py missing run_model()"}}))
            sys.exit(2)
        result = ns["run_model"]()
        if not isinstance(result, dict):
            print(json.dumps({{"__error__": "run_model() did not return dict"}}))
            sys.exit(2)
        print(json.dumps(result, default=str))
        """
    )

    def _preexec() -> None:
        try:
            soft = mem_mb * 1024 * 1024
            resource.setrlimit(resource.RLIMIT_AS, (soft, soft))
        except (ValueError, OSError):
            pass
        # No core dumps
        try:
            resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        except (ValueError, OSError):
            pass

    try:
        proc = subprocess.run(
            [sys.executable, "-c", runner],
            capture_output=True,
            text=True,
            timeout=timeout_s,
            check=False,
            preexec_fn=_preexec if sys.platform != "win32" else None,
            cwd=str(model_path.parent),
        )
    except subprocess.TimeoutExpired:
        return None, f"model execution timed out after {timeout_s}s"
    except Exception as exc:  # noqa: BLE001
        return None, str(exc)

    if proc.returncode != 0:
        err = proc.stderr.strip() or proc.stdout.strip() or f"exit {proc.returncode}"
        try:
            data = json.loads(proc.stdout.strip().splitlines()[-1])
            if "__error__" in data:
                return None, str(data["__error__"])
        except Exception:  # noqa: BLE001
            pass
        return None, err[-2000:]

    try:
        line = proc.stdout.strip().splitlines()[-1]
        data = json.loads(line)
    except Exception as exc:  # noqa: BLE001
        return None, f"failed to parse model output: {exc}\n{proc.stdout[-1000:]}"
    if isinstance(data, dict) and "__error__" in data:
        return None, str(data["__error__"])
    return data if isinstance(data, dict) else None, None
