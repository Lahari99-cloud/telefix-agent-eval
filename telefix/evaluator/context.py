"""Context extraction helpers for context-aware policy evaluation."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from telefix.models.trajectory import ToolCall, Trajectory, TrajectoryStep

MISSING = object()


def build_base_context(trajectory: Trajectory) -> dict[str, Any]:
    """Build deterministic trajectory-level policy context."""

    context: dict[str, Any] = {
        "trajectory": {
            "trajectory_id": trajectory.trajectory_id,
            "tenant_id": getattr(trajectory, "tenant_id", None),
            "trace_id": trajectory.trace_id,
            "session_id": getattr(trajectory, "session_id", None),
            "framework_name": getattr(trajectory, "framework_name", None),
            "model_name": getattr(trajectory, "model_name", None),
            "prompt_version": getattr(trajectory, "prompt_version", None),
        },
        "evaluation": trajectory.evaluation_labels.model_dump(mode="json"),
        "cost": trajectory.cost_metrics.model_dump(mode="json"),
    }
    _deep_merge(context, _model_extra(trajectory))
    extra_context = context.get("context")
    if isinstance(extra_context, Mapping):
        _deep_merge(context, dict(extra_context))
    _merge_runtime_context(context)
    return context


def build_tool_context(
    trajectory: Trajectory,
    step: TrajectoryStep,
    tool_call: ToolCall,
) -> dict[str, Any]:
    """Build context for one tool call by overlaying step and tool payloads."""

    context = build_base_context(trajectory)
    _deep_merge(
        context,
        {
            "step": step.model_dump(mode="json"),
            "tool": tool_call.model_dump(mode="json"),
        },
    )
    for payload in (
        step.input_context,
        step.output_context,
        tool_call.tool_input,
        tool_call.tool_output,
    ):
        if isinstance(payload, Mapping):
            _deep_merge(context, dict(payload))
    _merge_runtime_context(context)
    return context


def resolve_context_path(context: Mapping[str, Any], path: str) -> Any:
    current: Any = context
    for part in path.split("."):
        if isinstance(current, Mapping) and part in current:
            current = current[part]
        else:
            return MISSING
    return current


def iter_tool_calls(trajectory: Trajectory):
    for step in getattr(trajectory, "steps", []) or []:
        for tool_call in getattr(step, "tool_calls", []) or []:
            yield step, tool_call


def _model_extra(model: object) -> dict[str, Any]:
    extra = getattr(model, "__pydantic_extra__", None)
    return dict(extra or {})


def _merge_runtime_context(context: dict[str, Any]) -> None:
    runtime_context = context.get("runtime_context")
    if isinstance(runtime_context, Mapping):
        _deep_merge(context, dict(runtime_context))


def _deep_merge(target: dict[str, Any], source: Mapping[str, Any]) -> None:
    for key, value in source.items():
        if isinstance(value, Mapping) and isinstance(target.get(key), dict):
            _deep_merge(target[key], value)
        else:
            target[key] = value
