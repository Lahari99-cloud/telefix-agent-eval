"""Evaluation engine v1 tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from telefix.evaluator.evaluate import evaluate_trajectory
from telefix.evaluator.policies import EvaluationPolicy
from telefix.models.trajectory import (
    CostMetrics,
    EvaluationLabels,
    FrameworkName,
    NodeType,
    RiskLevel,
    ToolCall,
    ToolStatus,
    Trajectory,
    TrajectoryStep,
)


def _tool_call(
    name: str,
    *,
    destructive: bool = False,
    allowed: bool = True,
    risk_level: RiskLevel = RiskLevel.LOW,
) -> ToolCall:
    return ToolCall(
        tool_name=name,
        tool_input={},
        tool_output={},
        tool_status=ToolStatus.SUCCESS,
        is_destructive=destructive,
        is_allowed=allowed,
        risk_level=risk_level,
        retry_count=0,
        latency_ms=100.0,
    )


def _step(
    index: int,
    *,
    name: str,
    node_type: NodeType = NodeType.TOOL,
    loop_iteration: int = 0,
    latency_ms: float = 100.0,
    tool_calls: list[ToolCall] | None = None,
    complete: bool = True,
) -> TrajectoryStep:
    start = datetime(2026, 6, 17, 14, 12, index, tzinfo=UTC)
    return TrajectoryStep(
        step_index=index,
        node_name=name,
        node_type=node_type,
        parent_step_index=0 if index else None,
        loop_iteration=loop_iteration,
        input_context={},
        output_context={},
        start_time=start,
        end_time=start + timedelta(milliseconds=latency_ms) if complete else None,
        latency_ms=latency_ms,
        tool_calls=tool_calls or [],
    )


def _trajectory(
    *,
    expected: list[str] | None = None,
    actual: list[str] | None = None,
    steps: list[TrajectoryStep] | None = None,
    cost_usd: float = 0.01,
    escalation_required: bool = False,
    unsafe_action_detected: bool = False,
) -> Trajectory:
    expected_sequence = expected if expected is not None else ["read_modem_telemetry"]
    actual_sequence = actual if actual is not None else ["read_modem_telemetry"]
    trajectory_steps = steps if steps is not None else [
        _step(
            0,
            name="read_modem_telemetry",
            tool_calls=[_tool_call("read_modem_telemetry")],
        )
    ]
    return Trajectory(
        trajectory_id="traj-test",
        tenant_id="tenant-test",
        trace_id="trace-test",
        framework_name=FrameworkName.LANGGRAPH,
        model_name="gpt-4.1-mini",
        started_at=trajectory_steps[0].start_time,
        completed_at=trajectory_steps[-1].end_time,
        steps=trajectory_steps,
        cost_metrics=CostMetrics(
            prompt_tokens=10,
            completion_tokens=5,
            total_tokens=15,
            estimated_cost_usd=cost_usd,
        ),
        evaluation_labels=EvaluationLabels(
            ground_truth_root_cause=None,
            expected_tool_sequence=expected_sequence,
            actual_tool_sequence=actual_sequence,
            unsafe_action_detected=unsafe_action_detected,
            loop_detected=any(step.loop_iteration > 0 for step in trajectory_steps),
            escalation_required=escalation_required,
        ),
    )


def test_no_unsafe_actions_passes() -> None:
    result = evaluate_trajectory(_trajectory())

    assert result.passed is True
    assert result.decision == "pass"
    assert result.unsafe_actions.unsafe_action_rate == 0.0
    assert result.tool_selection.precision == 1.0


def test_forbidden_destructive_tool_fails() -> None:
    trajectory = _trajectory(
        steps=[
            _step(
                0,
                name="reset_modem",
                tool_calls=[
                    _tool_call(
                        "reset_modem",
                        destructive=True,
                        allowed=False,
                        risk_level=RiskLevel.HIGH,
                    )
                ],
            )
        ],
        expected=["read_modem_telemetry"],
        actual=["reset_modem"],
    )

    result = evaluate_trajectory(trajectory)

    assert result.passed is False
    assert "unsafe_action_rate" in result.failed_checks
    assert result.unsafe_actions.unsafe_tools == ["reset_modem"]


def test_low_tool_precision_fails() -> None:
    result = evaluate_trajectory(
        _trajectory(
            expected=["read_modem_telemetry", "check_outage"],
            actual=["reset_modem", "check_outage"],
        )
    )

    assert result.passed is False
    assert "tool_precision" in result.failed_checks
    assert result.tool_selection.precision == 0.5
    assert result.tool_selection.recall == 0.5
    assert any(
        entry.expected_tool == "read_modem_telemetry" and entry.actual_tool == "reset_modem"
        for entry in result.tool_confusion_matrix
    )


def test_loop_threshold_violation_fails() -> None:
    trajectory = _trajectory(
        steps=[
            _step(0, name="root", node_type=NodeType.CHAIN),
            _step(1, name="clarify", node_type=NodeType.LLM, loop_iteration=4),
        ],
        expected=[],
        actual=[],
    )

    result = evaluate_trajectory(trajectory, EvaluationPolicy(max_loop_iterations=3))

    assert result.passed is False
    assert "loop_iterations" in result.failed_checks
    assert result.loops.max_loop_iteration == 4
    assert result.loops.loop_nodes == ["clarify"]


def test_cost_threshold_violation_fails() -> None:
    result = evaluate_trajectory(_trajectory(cost_usd=1.25))

    assert result.passed is False
    assert "total_cost" in result.failed_checks
    assert result.cost.estimated_cost_usd == 1.25


def test_escalation_expected_but_missing_fails() -> None:
    result = evaluate_trajectory(_trajectory(escalation_required=True))

    assert result.passed is False
    assert "escalation" in result.failed_checks
    assert result.escalation.expected is True
    assert result.escalation.actual is False


def test_empty_or_incomplete_trajectory_returns_valid_failed_evaluation_result() -> None:
    trajectory = Trajectory.model_construct(
        trajectory_id="traj-empty",
        trace_id="trace-empty",
        steps=[],
        cost_metrics=CostMetrics(
            prompt_tokens=0,
            completion_tokens=0,
            total_tokens=0,
            estimated_cost_usd=0.0,
        ),
        evaluation_labels=EvaluationLabels(
            expected_tool_sequence=[],
            actual_tool_sequence=[],
            unsafe_action_detected=False,
            loop_detected=False,
            escalation_required=False,
        ),
    )

    result = evaluate_trajectory(trajectory)

    assert result.passed is False
    assert result.decision == "fail"
    assert "empty_trajectory" in result.failed_checks
    assert result.latency.total_latency_ms == 0.0


def test_evaluation_output_is_deterministic() -> None:
    trajectory = _trajectory(
        expected=["a", "b", "c"],
        actual=["a", "x"],
        steps=[
            _step(0, name="a", tool_calls=[_tool_call("a")]),
            _step(1, name="x", tool_calls=[_tool_call("x")]),
        ],
    )

    first = evaluate_trajectory(trajectory).model_dump(mode="json")
    second = evaluate_trajectory(trajectory).model_dump(mode="json")

    assert first == second
