"""State-drift analysis tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from telefix.evaluator.evaluate import evaluate_trajectory
from telefix.evaluator.policies import EvaluationPolicy
from telefix.evaluator.state_drift import analyze_state_drift
from telefix.models.trajectory import (
    CostMetrics,
    EvaluationLabels,
    FrameworkName,
    NodeType,
    Trajectory,
    TrajectoryStep,
)


def _step(index: int, objective_text: str, *, loop_iteration: int = 0) -> TrajectoryStep:
    start = datetime(2026, 6, 17, 14, 12, index, tzinfo=UTC)
    return TrajectoryStep(
        step_index=index,
        node_name=f"reason_{index}",
        node_type=NodeType.LLM,
        parent_step_index=0 if index else None,
        loop_iteration=loop_iteration,
        input_context={"incident": {"objective": objective_text}},
        output_context={"reasoning": objective_text},
        start_time=start,
        end_time=start + timedelta(milliseconds=100),
        latency_ms=100.0,
        tool_calls=[],
    )


def _trajectory(steps: list[TrajectoryStep]) -> Trajectory:
    return Trajectory(
        trajectory_id="traj-drift",
        tenant_id="tenant-drift",
        trace_id="trace-drift",
        framework_name=FrameworkName.LANGGRAPH,
        model_name="gpt-4.1-mini",
        started_at=steps[0].start_time,
        completed_at=steps[-1].end_time,
        steps=steps,
        cost_metrics=CostMetrics(
            prompt_tokens=10,
            completion_tokens=5,
            total_tokens=15,
            estimated_cost_usd=0.01,
        ),
        evaluation_labels=EvaluationLabels(
            ground_truth_root_cause="restore metro latency",
            expected_tool_sequence=[],
            actual_tool_sequence=[],
            unsafe_action_detected=False,
            loop_detected=any(step.loop_iteration > 0 for step in steps),
            escalation_required=False,
        ),
    )


def _enabled_policy(**overrides) -> EvaluationPolicy:
    payload = {
        "min_tool_precision": 0.0,
        "state_drift": {
            "enabled": True,
            "max_semantic_redundancy_score": 0.85,
            "min_objective_retention_score": 0.60,
            "max_context_growth_ratio": 3.0,
        },
    }
    payload["state_drift"].update(overrides)
    return EvaluationPolicy.model_validate(payload)


def test_stable_trajectory_does_not_trigger_drift() -> None:
    trajectory = _trajectory(
        [
            _step(0, "restore metro latency by checking queue drops"),
            _step(1, "restore metro latency using interface congestion evidence"),
            _step(2, "restore metro latency with qos ticket remediation"),
        ]
    )

    result = analyze_state_drift(trajectory)

    assert result.drift_detected is False
    assert result.objective_retention_score >= 0.60
    assert result.context_growth_ratio <= 3.0


def test_repeated_reasoning_triggers_high_redundancy() -> None:
    repeated = "restore metro latency check same queue drops and same qos evidence"
    trajectory = _trajectory(
        [
            _step(0, repeated),
            _step(1, repeated, loop_iteration=1),
            _step(2, repeated, loop_iteration=2),
        ]
    )

    result = analyze_state_drift(trajectory)

    assert result.semantic_redundancy_score > 0.85
    assert result.repeated_context_ratio == 1.0
    assert result.drift_detected is True


def test_objective_loss_triggers_low_objective_retention() -> None:
    trajectory = _trajectory(
        [
            _step(0, "restore metro latency by checking queue drops"),
            _step(1, "summarize billing email preferences and account notes"),
        ]
    )

    result = analyze_state_drift(trajectory)

    assert result.objective_retention_score < 0.60
    assert result.drift_detected is True


def test_excessive_context_growth_triggers_drift() -> None:
    large_context = "restore metro latency " + " ".join(
        f"irrelevant_token_{index}" for index in range(40)
    )
    trajectory = _trajectory(
        [
            _step(0, "restore metro latency"),
            _step(1, large_context),
        ]
    )

    result = analyze_state_drift(trajectory)

    assert result.context_growth_ratio > 3.0
    assert result.drift_detected is True


def test_state_drift_can_be_disabled_by_policy() -> None:
    repeated = "restore metro latency check same queue drops and same qos evidence"
    trajectory = _trajectory([_step(0, repeated), _step(1, repeated, loop_iteration=1)])

    result = evaluate_trajectory(
        trajectory,
        EvaluationPolicy(min_tool_precision=0.0, state_drift={"enabled": False}),
    )

    assert result.passed is True
    assert result.state_drift is None


def test_evaluation_fails_when_drift_exceeds_policy_thresholds() -> None:
    repeated = "restore metro latency check same queue drops and same qos evidence"
    trajectory = _trajectory([_step(0, repeated), _step(1, repeated, loop_iteration=1)])

    result = evaluate_trajectory(trajectory, _enabled_policy())

    assert result.passed is False
    assert "state_drift" in result.failed_checks
    assert result.state_drift is not None
    assert result.state_drift.drift_detected is True
