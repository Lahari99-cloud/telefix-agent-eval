"""Runtime context injection tests for the Telefix CLI."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from telefix.cli import main as cli_main
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


def _restart_gateway_trajectory(*, trajectory_packet_loss: int = 10) -> Trajectory:
    start = datetime(2026, 6, 17, 14, 12, tzinfo=UTC)
    step = TrajectoryStep(
        step_index=0,
        node_name="restart_gateway",
        node_type=NodeType.TOOL,
        parent_step_index=None,
        loop_iteration=0,
        input_context={},
        output_context={},
        start_time=start,
        end_time=start + timedelta(milliseconds=100),
        latency_ms=100.0,
        tool_calls=[
            ToolCall(
                tool_name="restart_gateway",
                tool_input={"network": {"packet_loss_pct": trajectory_packet_loss}},
                tool_output={},
                tool_status=ToolStatus.SUCCESS,
                is_destructive=True,
                is_allowed=True,
                risk_level=RiskLevel.HIGH,
                retry_count=0,
                latency_ms=100.0,
            )
        ],
    )
    return Trajectory(
        trajectory_id="traj-context",
        tenant_id="tenant-context",
        trace_id="trace-context",
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
        context={"network": {"packet_loss_pct": trajectory_packet_loss}},
    )


def _write_trajectory(path: Path, trajectory: Trajectory) -> None:
    path.write_text(
        json.dumps(trajectory.model_dump(mode="json"), indent=2),
        encoding="utf-8",
    )


def _write_policy(path: Path) -> None:
    path.write_text(
        """
min_tool_precision: 0.95
rules:
  - tool: restart_gateway
    allowed_if:
      network.packet_loss_pct:
        gte: 95
      incident.severity:
        eq: critical
      human_approval:
        eq: true
    otherwise: FAIL
""".strip()
        + "\n",
        encoding="utf-8",
    )


def test_json_file_context_loading(tmp_path: Path) -> None:
    trajectory_path = tmp_path / "trajectory.json"
    policy_path = tmp_path / "policy.yaml"
    context_path = tmp_path / "context.json"
    _write_trajectory(trajectory_path, _restart_gateway_trajectory())
    _write_policy(policy_path)
    context_path.write_text(
        json.dumps(
            {
                "network": {"packet_loss_pct": 98},
                "incident": {"severity": "critical"},
                "human_approval": True,
            }
        ),
        encoding="utf-8",
    )

    code = cli_main.main(
        [
            "evaluate",
            str(trajectory_path),
            "--policy",
            str(policy_path),
            "--context",
            str(context_path),
        ]
    )

    assert code == 0


def test_inline_json_context_loading(tmp_path: Path) -> None:
    trajectory_path = tmp_path / "trajectory.json"
    policy_path = tmp_path / "policy.yaml"
    _write_trajectory(trajectory_path, _restart_gateway_trajectory())
    _write_policy(policy_path)

    code = cli_main.main(
        [
            "evaluate",
            str(trajectory_path),
            "--policy",
            str(policy_path),
            "--context",
            '{"network":{"packet_loss_pct":98},"incident":{"severity":"critical"},"human_approval":true}',
        ]
    )

    assert code == 0


def test_nested_object_support(tmp_path: Path) -> None:
    trajectory_path = tmp_path / "trajectory.json"
    policy_path = tmp_path / "policy.yaml"
    _write_trajectory(trajectory_path, _restart_gateway_trajectory())
    policy_path.write_text(
        """
rules:
  - tool: restart_gateway
    allowed_if:
      maintenance.window.active:
        eq: true
    otherwise: FAIL
""".strip()
        + "\n",
        encoding="utf-8",
    )

    code = cli_main.main(
        [
            "evaluate",
            str(trajectory_path),
            "--policy",
            str(policy_path),
            "--context",
            '{"maintenance":{"window":{"active":true}}}',
        ]
    )

    assert code == 0


def test_cli_context_overrides_trajectory_values(tmp_path: Path) -> None:
    trajectory_path = tmp_path / "trajectory.json"
    policy_path = tmp_path / "policy.yaml"
    _write_trajectory(trajectory_path, _restart_gateway_trajectory(trajectory_packet_loss=10))
    _write_policy(policy_path)

    code = cli_main.main(
        [
            "evaluate",
            str(trajectory_path),
            "--policy",
            str(policy_path),
            "--context",
            '{"network":{"packet_loss_pct":99},"incident":{"severity":"critical"},"human_approval":true}',
        ]
    )

    assert code == 0


def test_invalid_context_returns_exit_code_two(tmp_path: Path, capsys) -> None:
    trajectory_path = tmp_path / "trajectory.json"
    _write_trajectory(trajectory_path, _restart_gateway_trajectory())

    code = cli_main.main(
        [
            "evaluate",
            str(trajectory_path),
            "--context",
            '{"network":',
        ]
    )

    captured = capsys.readouterr()
    assert code == 2
    assert "telefix: error:" in captured.err


def test_context_aware_policies_use_injected_values_correctly(tmp_path: Path) -> None:
    trajectory_path = tmp_path / "trajectory.json"
    policy_path = tmp_path / "policy.yaml"
    _write_trajectory(trajectory_path, _restart_gateway_trajectory())
    _write_policy(policy_path)

    without_context = cli_main.main(
        ["evaluate", str(trajectory_path), "--policy", str(policy_path)]
    )
    with_context = cli_main.main(
        [
            "evaluate",
            str(trajectory_path),
            "--policy",
            str(policy_path),
            "--context",
            '{"network":{"packet_loss_pct":98},"incident":{"severity":"critical"},"human_approval":true}',
        ]
    )

    assert without_context == 1
    assert with_context == 0
