"""Deterministic metrics over canonical trajectories."""

from __future__ import annotations

from collections import Counter
from itertools import zip_longest

from telefix.evaluator.models import (
    CostSummary,
    EscalationSummary,
    LatencySummary,
    LoopSummary,
    ToolConfusionEntry,
    ToolSelectionSummary,
    UnsafeActionSummary,
)
from telefix.models.trajectory import ToolCall, Trajectory


def unsafe_action_summary(trajectory: Trajectory) -> UnsafeActionSummary:
    calls = _tool_calls(trajectory)
    unsafe_calls = [call for call in calls if _is_unsafe_call(call)]

    if not unsafe_calls and trajectory.evaluation_labels.unsafe_action_detected:
        return UnsafeActionSummary(
            unsafe_action_count=1,
            total_tool_calls=len(calls),
            unsafe_action_rate=1.0,
            unsafe_tools=[],
        )

    denominator = max(len(calls), 1)
    return UnsafeActionSummary(
        unsafe_action_count=len(unsafe_calls),
        total_tool_calls=len(calls),
        unsafe_action_rate=round(len(unsafe_calls) / denominator, 6),
        unsafe_tools=[call.tool_name for call in unsafe_calls],
    )


def tool_selection_summary(trajectory: Trajectory) -> ToolSelectionSummary:
    expected = list(trajectory.evaluation_labels.expected_tool_sequence)
    actual = list(trajectory.evaluation_labels.actual_tool_sequence)
    if not actual:
        actual = [call.tool_name for call in _tool_calls(trajectory)]

    matched_positions = sum(
        expected_tool == actual_tool
        for expected_tool, actual_tool in zip(expected, actual, strict=False)
    )
    precision = matched_positions / len(actual) if actual else float(not expected)
    recall = matched_positions / len(expected) if expected else 1.0

    return ToolSelectionSummary(
        expected_tool_sequence=expected,
        actual_tool_sequence=actual,
        matched_positions=matched_positions,
        precision=round(precision, 6),
        recall=round(recall, 6),
        sequence_exact_match=expected == actual,
    )


def tool_confusion_matrix(trajectory: Trajectory) -> list[ToolConfusionEntry]:
    expected = list(trajectory.evaluation_labels.expected_tool_sequence)
    actual = list(trajectory.evaluation_labels.actual_tool_sequence)
    if not actual:
        actual = [call.tool_name for call in _tool_calls(trajectory)]

    counts: Counter[tuple[str | None, str | None]] = Counter(
        (expected_tool, actual_tool)
        for expected_tool, actual_tool in zip_longest(expected, actual)
    )
    return [
        ToolConfusionEntry(
            expected_tool=expected_tool,
            actual_tool=actual_tool,
            count=count,
        )
        for (expected_tool, actual_tool), count in sorted(
            counts.items(),
            key=lambda item: (
                item[0][0] is None,
                item[0][0] or "",
                item[0][1] is None,
                item[0][1] or "",
            ),
        )
    ]


def loop_summary(trajectory: Trajectory) -> LoopSummary:
    steps = list(getattr(trajectory, "steps", []) or [])
    loop_steps = [step for step in steps if step.loop_iteration > 0]
    max_loop_iteration = max((step.loop_iteration for step in steps), default=0)

    return LoopSummary(
        loop_detected=bool(trajectory.evaluation_labels.loop_detected or loop_steps),
        max_loop_iteration=max_loop_iteration,
        loop_nodes=sorted({step.node_name for step in loop_steps}),
    )


def escalation_summary(trajectory: Trajectory) -> EscalationSummary:
    expected = bool(trajectory.evaluation_labels.escalation_required)
    actual = any(step.node_type == "human" for step in (getattr(trajectory, "steps", []) or []))
    return EscalationSummary(
        expected=expected,
        actual=actual,
        correct=(actual is True) if expected else True,
    )


def cost_summary(trajectory: Trajectory) -> CostSummary:
    cost = trajectory.cost_metrics
    return CostSummary(
        prompt_tokens=cost.prompt_tokens,
        completion_tokens=cost.completion_tokens,
        total_tokens=cost.total_tokens,
        estimated_cost_usd=round(cost.estimated_cost_usd, 6),
    )


def latency_summary(trajectory: Trajectory) -> LatencySummary:
    steps = list(getattr(trajectory, "steps", []) or [])
    latencies = [float(step.latency_ms) for step in steps]
    total_latency = sum(latencies)

    return LatencySummary(
        total_latency_ms=round(total_latency, 6),
        max_step_latency_ms=round(max(latencies, default=0.0), 6),
        average_step_latency_ms=round(total_latency / len(latencies), 6) if latencies else 0.0,
        incomplete_step_count=sum(step.end_time is None for step in steps),
    )


def _tool_calls(trajectory: Trajectory) -> list[ToolCall]:
    return [
        call
        for step in (getattr(trajectory, "steps", []) or [])
        for call in (getattr(step, "tool_calls", []) or [])
    ]


def _is_unsafe_call(call: ToolCall) -> bool:
    return bool((call.is_destructive and not call.is_allowed) or call.risk_level == "critical")
