"""Pipeline uses LocalWorkerPool for tier concurrency."""

from __future__ import annotations

import ast
from pathlib import Path


def test_pipeline_imports_worker_pool():
    src = Path("archzero/funnel/pipeline.py").read_text(encoding="utf-8")
    assert "LocalWorkerPool" in src
    ast.parse(src)
