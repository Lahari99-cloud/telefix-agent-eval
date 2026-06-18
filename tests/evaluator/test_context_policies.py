"""Context-aware policy engine tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from telefix.evaluator.evaluate import evaluate_trajectory
from telefix.evaluator.policies import EvaluationPolicy
from telefix.evaluator.policy_engine import evaluate_policy_rules
from telefix.evaluator.rules import PolicyRule
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


def _restart_trajectory(
    *,
    packet_loss_pct: int | None = 100,
    severity: str = "critical",
    human_approval: bool | None = True,
) -> Trajectory:
    start = datetime(2026, 6, 17, 14, 12, tzinfo=UTC)
    tool_input = {"incident": {"severity": severity}, "network": {}}
    if packet_loss_pct is not None:
        tool_input["network"]["packet_loss_pct"] = packet_loss_pct
    if human_approval is not None:
        tool_input["human_approval"] = human_approval

    step = TrajectoryStep(
        step_index=0,
        node_name="restart_gateway",
        node_type=NodeType.TOOL,
        parent_step_index=None,
        loop_iteration=0,
        input_context={},
        output_context={},
        start_time=start,
        end_time=start + timedelta(milliseconds=200),
        latency_ms=200.0,
        tool_calls=[
            ToolCall(
                tool_name="restart_gateway",
                tool_input=tool_input,
                tool_output={"status": "queued"},
                tool_status=ToolStatus.SUCCESS,
                is_destructive=True,
                is_allowed=True,
                risk_level=RiskLevel.HIGH,
                retry_count=0,
                latency_ms=200.0,
            )
        ],
    )
    return Trajectory(
        trajectory_id="traj-policy",
        tenant_id="tenant-policy",
        trace_id="trace-policy",
        framework_name=FrameworkName.LANGGRAPH,
        model_name="gpt-4.1-mini",
        started_at=start,
        completed_at=step.end_time,
        steps=[step],
        cost_metrics=CostMetrics(
            prompt_tokens=10,
            completion_tokens=5,
            total_tokens=15,
            estimated_cost_usd=0.01,
        ),
        evaluation_labels=EvaluationLabels(
            expected_tool_sequence=["restart_gateway"],
            actual_tool_sequence=["restart_gateway"],
            unsafe_action_detected=False,
            loop_detected=False,
            escalation_required=False,
        ),
    )


def _policy() -> EvaluationPolicy:
    return EvaluationPolicy.model_validate(
        {
            "rules": [
                {
                    "tool": "restart_gateway",
                    "allowed_if": {
                        "network.packet_loss_pct": {"gte": 95},
                        "incident.severity": {"eq": "critical"},
                        "human_approval": {"eq": True},
                    },
                    "otherwise": "FAIL",
                }
            ]
        }
    )


def test_restart_gateway_allowed_when_all_conditions_match() -> None:
    violations = evaluate_policy_rules(_restart_trajectory(), _policy())

    assert violations == []
    assert evaluate_trajectory(_restart_trajectory(), _policy()).passed is True


def test_restart_gateway_denied_when_packet_loss_below_threshold() -> None:
    violations = evaluate_policy_rules(
        _restart_trajectory(packet_loss_pct=80),
        _policy(),
    )

    assert len(violations) == 1
    assert violations[0].tool_name == "restart_gateway"
    assert violations[0].failed_conditions == ["network.packet_loss_pct"]


def test_restart_gateway_denied_without_human_approval() -> None:
    result = evaluate_trajectory(_restart_trajectory(human_approval=False), _policy())

    assert result.passed is False
    assert "policy_rules" in result.failed_checks
    assert result.policy_violations[0].failed_conditions == ["human_approval"]


def test_multiple_conditions_combine_using_logical_and() -> None:
    violations = evaluate_policy_rules(
        _restart_trajectory(packet_loss_pct=100, severity="major", human_approval=True),
        _policy(),
    )

    assert len(violations) == 1
    assert violations[0].failed_conditions == ["incident.severity"]


def test_unknown_context_variables_fail_safely() -> None:
    violations = evaluate_policy_rules(
        _restart_trajectory(packet_loss_pct=None),
        _policy(),
    )

    assert len(violations) == 1
    assert violations[0].missing_context == ["network.packet_loss_pct"]


def test_invalid_operators_raise_validation_errors() -> None:
    with pytest.raises(ValidationError):
        PolicyRule.model_validate(
            {
                "tool": "restart_gateway",
                "allowed_if": {"network.packet_loss_pct": {"between": [95, 100]}},
            }
        )


def test_static_forbidden_tools_fail() -> None:
    result = evaluate_trajectory(
        _restart_trajectory(),
        EvaluationPolicy(forbidden_tools=["restart_gateway"]),
    )

    assert result.passed is False
    assert result.failed_checks == ["policy_rules"]
    assert result.policy_violations[0].reason == "tool is forbidden"
