"""Trajectory Reconstruction Engine (T-REx) v1."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from datetime import datetime

from telefix.models.trajectory import (
    CostMetrics,
    EvaluationLabels,
    FrameworkName,
    Trajectory,
    TrajectoryStep,
)
from telefix.trex.adapters.otel import (
    RawOtelSpan,
    SpanLoader,
    attr,
    extract_tool_call,
    infer_node_name,
    infer_node_type,
    parse_context,
    span_latency_ms,
)

_span_loader: SpanLoader | None = None


class SpanLoaderNotConfiguredError(RuntimeError):
    """Raised when T-REx is called before a span loader is configured."""


def configure_span_loader(loader: SpanLoader) -> None:
    """Configure the async span loader used by `reconstruct_trajectory`."""

    global _span_loader
    _span_loader = loader


async def reconstruct_trajectory(trace_id: str) -> Trajectory:
    """Load raw OpenTelemetry spans and reconstruct a canonical trajectory."""

    if _span_loader is None:
        raise SpanLoaderNotConfiguredError("configure_span_loader() must be called first")

    spans = list(await _span_loader.load_spans(trace_id))
    if not spans:
        raise ValueError(f"no spans found for trace_id={trace_id!r}")

    return reconstruct_trajectory_from_spans(trace_id, spans)


def reconstruct_trajectory_from_spans(trace_id: str, spans: Sequence[RawOtelSpan]) -> Trajectory:
    """Pure reconstruction path used by the public API and deterministic tests."""

    ordered_spans = _topological_sort(spans)
    span_to_step = {span.span_id: index for index, span in enumerate(ordered_spans)}
    loop_counts: dict[tuple[str | None, str], int] = defaultdict(int)
    steps: list[TrajectoryStep] = []
    actual_tool_sequence: list[str] = []

    for step_index, span in enumerate(ordered_spans):
        parent_step_index = _parent_step_index(span, span_to_step)
        node_name = infer_node_name(span)
        loop_key = (span.parent_span_id, node_name)
        loop_iteration = loop_counts[loop_key]
        loop_counts[loop_key] += 1
        tool_call = extract_tool_call(span)
        tool_calls = [tool_call] if tool_call is not None else []
        actual_tool_sequence.extend(call.tool_name for call in tool_calls)

        steps.append(
            TrajectoryStep(
                step_index=step_index,
                node_name=node_name,
                node_type=infer_node_type(span),
                parent_step_index=parent_step_index,
                loop_iteration=loop_iteration,
                input_context=parse_context(attr(span, "agent.input")),
                output_context=parse_context(attr(span, "agent.output")),
                start_time=span.start_time,
                end_time=span.end_time,
                latency_ms=span_latency_ms(span),
                tool_calls=tool_calls,
            )
        )

    prompt_tokens = sum(_int_attr(span, "llm.prompt_tokens") for span in spans)
    completion_tokens = sum(_int_attr(span, "llm.completion_tokens") for span in spans)
    total_tokens = prompt_tokens + completion_tokens

    first_span = ordered_spans[0]
    completed_at = _completed_at(ordered_spans)
    loop_detected = any(step.loop_iteration > 0 for step in steps)

    return Trajectory(
        trajectory_id=f"traj_{trace_id}",
        tenant_id=str(_first_attr(ordered_spans, "tenant.id") or "unknown"),
        trace_id=trace_id,
        session_id=_optional_str(_first_attr(ordered_spans, "session.id")),
        framework_name=_framework_name(_first_attr(ordered_spans, "agent.framework")),
        framework_version=_optional_str(_first_attr(ordered_spans, "agent.framework_version")),
        model_name=str(_first_attr(ordered_spans, "llm.model_name") or "unknown"),
        model_version=_optional_str(_first_attr(ordered_spans, "llm.model_version")),
        prompt_version=_optional_str(_first_attr(ordered_spans, "prompt.version")),
        started_at=min(span.start_time for span in ordered_spans),
        completed_at=completed_at,
        steps=steps,
        cost_metrics=CostMetrics(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            estimated_cost_usd=sum(_float_attr(span, "llm.estimated_cost_usd") for span in spans),
        ),
        evaluation_labels=EvaluationLabels(
            ground_truth_root_cause=None,
            expected_tool_sequence=[],
            actual_tool_sequence=actual_tool_sequence,
            unsafe_action_detected=any(
                call.is_destructive and not call.is_allowed
                for step in steps
                for call in step.tool_calls
            ),
            loop_detected=loop_detected,
            escalation_required=any(step.node_type == "human" for step in steps),
        ),
        root_span_id=first_span.span_id,
    )


def _topological_sort(spans: Sequence[RawOtelSpan]) -> list[RawOtelSpan]:
    by_id = {span.span_id: span for span in spans}
    children_by_parent: dict[str | None, list[RawOtelSpan]] = defaultdict(list)
    roots: list[RawOtelSpan] = []

    for span in spans:
        if span.parent_span_id and span.parent_span_id in by_id:
            children_by_parent[span.parent_span_id].append(span)
        else:
            roots.append(span)

    for children in children_by_parent.values():
        children.sort(key=_execution_key)
    roots.sort(key=_execution_key)

    ordered: list[RawOtelSpan] = []
    visited: set[str] = set()

    def visit(span: RawOtelSpan) -> None:
        if span.span_id in visited:
            return
        visited.add(span.span_id)
        ordered.append(span)
        for child in children_by_parent.get(span.span_id, []):
            visit(child)

    for root in roots:
        visit(root)

    for span in sorted(spans, key=_execution_key):
        visit(span)

    return ordered


def _execution_key(span: RawOtelSpan) -> tuple[datetime, int, str]:
    return span.start_time, _sequence(span), span.span_id


def _sequence(span: RawOtelSpan) -> int:
    try:
        return int(span.attributes.get("agent.sequence", 1_000_000_000))
    except (TypeError, ValueError):
        return 1_000_000_000


def _parent_step_index(span: RawOtelSpan, span_to_step: dict[str, int]) -> int | None:
    if span.parent_span_id is None:
        return None
    parent_index = span_to_step.get(span.parent_span_id)
    current_index = span_to_step[span.span_id]
    if parent_index is None or parent_index >= current_index:
        return None
    return parent_index


def _completed_at(spans: Sequence[RawOtelSpan]) -> datetime | None:
    if any(span.end_time is None for span in spans):
        return None
    return max(span.end_time for span in spans if span.end_time is not None)


def _first_attr(spans: Sequence[RawOtelSpan], key: str) -> object | None:
    for span in spans:
        value = attr(span, key)
        if value not in (None, ""):
            return value
    return None


def _optional_str(value: object | None) -> str | None:
    if value in (None, ""):
        return None
    return str(value)


def _int_attr(span: RawOtelSpan, key: str) -> int:
    try:
        return max(int(attr(span, key, 0) or 0), 0)
    except (TypeError, ValueError):
        return 0


def _float_attr(span: RawOtelSpan, key: str) -> float:
    try:
        return max(float(attr(span, key, 0.0) or 0.0), 0.0)
    except (TypeError, ValueError):
        return 0.0


def _framework_name(value: object | None) -> FrameworkName:
    normalized = str(value or "unknown").lower().replace("-", "_")
    if normalized in {framework.value for framework in FrameworkName}:
        return FrameworkName(normalized)
    return FrameworkName.UNKNOWN
