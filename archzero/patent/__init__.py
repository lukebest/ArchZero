"""Optional patent disclosure module.

Nothing here is imported by the core funnel. The pptx renderer needs the
``patent`` extra (``uv sync --extra patent``); prior-art search and the
Markdown disclosure work with the base install.

Keep this module free of heavy top-level imports so ``import archzero.patent``
stays cheap and never fails on a machine without the extra.
"""

from __future__ import annotations


class PatentDepsMissing(RuntimeError):
    """Raised when an optional patent dependency is not installed."""

    def __init__(self, package: str = "python-pptx") -> None:
        super().__init__(
            f"{package} 未安装。请执行 uv sync --extra patent，"
            f"或改用 --md-only 仅生成交底书 Markdown。"
        )
        self.package = package


__all__ = ["PatentDepsMissing"]
