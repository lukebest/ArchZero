"""Map ArchZero / IDE model aliases to cursor-sdk ModelSelection ids + params.

The agent catalog historically used names like ``cursor-grok-4.5-high-fast``.
``Cursor.models.list()`` / ``create_agent`` expect base ids such as ``grok-4.5``
with explicit ``effort`` / ``fast`` parameter values.
"""

from __future__ import annotations

from typing import Any

# Logical alias → (sdk_model_id, params)
_ALIASES: dict[str, tuple[str, dict[str, str]]] = {
    "cursor-grok-4.5-high-fast": ("grok-4.5", {"effort": "high", "fast": "true"}),
    "cursor-grok-4.5": ("grok-4.5", {}),
    "auto": ("default", {}),
    "auto-smart": ("default", {}),
}


def resolve_model_ref(
    model_id: str,
    *,
    extra_params: dict[str, str] | None = None,
    optimize_for: str | None = None,
) -> tuple[str, dict[str, str]]:
    """Return ``(sdk_id, params)`` for create_agent / ModelSelection."""
    mid = (model_id or "").strip()
    if mid in _ALIASES:
        sdk_id, params = _ALIASES[mid]
        params = dict(params)
    else:
        sdk_id, params = mid, {}

    if optimize_for:
        params.setdefault("optimize_for", optimize_for)
    if extra_params:
        params.update({str(k): str(v) for k, v in extra_params.items()})
    return sdk_id, params


def to_model_selection(
    model_id: str,
    *,
    extra_params: dict[str, str] | None = None,
    optimize_for: str | None = None,
) -> Any:
    """Build a cursor-sdk ``ModelSelection``, or a plain id string if SDK missing."""
    sdk_id, params = resolve_model_ref(
        model_id, extra_params=extra_params, optimize_for=optimize_for
    )
    try:
        from cursor_sdk import ModelParameterValue, ModelSelection  # type: ignore
    except ImportError:
        return sdk_id
    if not params:
        return ModelSelection(id=sdk_id)
    return ModelSelection(
        id=sdk_id,
        params=[ModelParameterValue(id=k, value=v) for k, v in params.items()],
    )
