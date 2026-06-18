"""Runtime context loading for the Telefix CLI."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from telefix.models.trajectory import Trajectory


def load_runtime_context(value: str) -> dict[str, Any]:
    """Load runtime context from an inline JSON object or a JSON file path."""

    source = Path(value)
    raw = source.read_text(encoding="utf-8") if source.exists() else value
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise ValueError("runtime context must be a JSON object")
    return payload


def inject_runtime_context(trajectory: Trajectory, context: Mapping[str, Any]) -> Trajectory:
    """Attach CLI runtime context to a trajectory as forward-compatible metadata."""

    extra = dict(getattr(trajectory, "__pydantic_extra__", None) or {})
    existing = extra.get("runtime_context")
    merged = dict(existing) if isinstance(existing, Mapping) else {}
    _deep_merge(merged, context)
    extra["runtime_context"] = merged
    trajectory.__pydantic_extra__ = extra
    return trajectory


def _deep_merge(target: dict[str, Any], source: Mapping[str, Any]) -> None:
    for key, value in source.items():
        if isinstance(value, Mapping) and isinstance(target.get(key), dict):
            _deep_merge(target[key], value)
        else:
            target[key] = value
