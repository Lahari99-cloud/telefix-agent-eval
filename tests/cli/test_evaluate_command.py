"""CI gate CLI tests."""

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


def _tool_call(
    name: str,
    *,
    destructive: bool = False,
    allowed: bool = True,
) -> ToolCall:
    return ToolCall(
        tool_name=name,
        tool_input={},
        tool_output={},
        tool_status=ToolStatus.SUCCESS,
        is_destructive=destructive,
        is_allowed=allowed,
        risk_level=RiskLevel.HIGH if destructive else RiskLevel.LOW,
        retry_count=0,
        latency_ms=100.0,
    )


def _trajectory(
    *,
    expected: list[str] | None = None,
    actual: list[str] | None = None,
    destructive: bool = False,
) -> Trajectory:
    start = datetime(2026, 6, 17, 14, 12, tzinfo=UTC)
    tool_name = (actual or ["read_modem_telemetry"])[0]
    step = TrajectoryStep(
        step_index=0,
        node_name=tool_name,
        node_type=NodeType.TOOL,
        parent_step_index=None,
        loop_iteration=0,
        input_context={},
        output_context={},
        start_time=start,
        end_time=start + timedelta(milliseconds=100),
        latency_ms=100.0,
        tool_calls=[_tool_call(tool_name, destructive=destructive, allowed=not destructive)],
    )
    return Trajectory(
        trajectory_id="traj-cli",
        tenant_id="tenant-cli",
        trace_id="trace-cli",
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
            expected_tool_sequence=expected or ["read_modem_telemetry"],
            actual_tool_sequence=actual or ["read_modem_telemetry"],
            unsafe_action_detected=False,
            loop_detected=False,
            escalation_required=False,
        ),
    )


def _write_trajectory(path: Path, trajectory: Trajectory) -> None:
    path.write_text(
        json.dumps(trajectory.model_dump(mode="json"), indent=2),
        encoding="utf-8",
    )


def test_passing_trajectory_exits_zero(tmp_path: Path, capsys) -> None:
    trajectory_path = tmp_path / "trajectory.json"
    _write_trajectory(trajectory_path, _trajectory())

    code = cli_main.main(["evaluate", str(trajectory_path)])

    output = capsys.readouterr().out
    assert code == 0
    assert "Deployment decision: pass" in output
    assert "Policy violations: none" in output


def test_failing_trajectory_exits_one_and_prints_violations(tmp_path: Path, capsys) -> None:
    trajectory_path = tmp_path / "trajectory.json"
    _write_trajectory(
        trajectory_path,
        _trajectory(expected=["read_modem_telemetry"], actual=["reset_modem"], destructive=True),
    )

    code = cli_main.main(["evaluate", str(trajectory_path)])

    output = capsys.readouterr().out
    assert code == 1
    assert "Deployment decision: fail" in output
    assert "unsafe_action_rate" in output
    assert "tool_precision" in output


def test_invalid_trajectory_exits_two(tmp_path: Path, capsys) -> None:
    trajectory_path = tmp_path / "invalid.json"
    trajectory_path.write_text('{"trajectory_id": "missing-required-fields"}', encoding="utf-8")

    code = cli_main.main(["evaluate", str(trajectory_path)])

    captured = capsys.readouterr()
    assert code == 2
    assert "telefix: error:" in captured.err


def test_invalid_policy_exits_two(tmp_path: Path, capsys) -> None:
    trajectory_path = tmp_path / "trajectory.json"
    policy_path = tmp_path / "policy.yaml"
    _write_trajectory(trajectory_path, _trajectory())
    policy_path.write_text("min_tool_precision: 2.0\n", encoding="utf-8")

    code = cli_main.main(["evaluate", str(trajectory_path), "--policy", str(policy_path)])

    captured = capsys.readouterr()
    assert code == 2
    assert "telefix: error:" in captured.err


def test_json_report_is_written_correctly(tmp_path: Path) -> None:
    trajectory_path = tmp_path / "trajectory.json"
    report_path = tmp_path / "report.json"
    _write_trajectory(trajectory_path, _trajectory())

    code = cli_main.main(
        ["evaluate", str(trajectory_path), "--json-output", str(report_path)]
    )

    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert code == 0
    assert report["trajectory_id"] == "traj-cli"
    assert report["decision"] == "pass"
    assert report["unsafe_actions"]["unsafe_action_rate"] == 0.0
    assert report["warnings"] == []


def test_policy_file_changes_decision(tmp_path: Path) -> None:
    trajectory_path = tmp_path / "trajectory.json"
    policy_path = tmp_path / "policy.yaml"
    _write_trajectory(trajectory_path, _trajectory())
    policy_path.write_text("max_total_cost_usd: 0.001\n", encoding="utf-8")

    code = cli_main.main(["evaluate", str(trajectory_path), "--policy", str(policy_path)])

    assert code == 1


def test_cli_uses_existing_evaluator(monkeypatch, tmp_path: Path) -> None:
    trajectory_path = tmp_path / "trajectory.json"
    _write_trajectory(trajectory_path, _trajectory())
    calls = {"count": 0}
    real_evaluator = cli_main.evaluate_trajectory

    def tracking_evaluator(*args, **kwargs):
        calls["count"] += 1
        return real_evaluator(*args, **kwargs)

    monkeypatch.setattr(cli_main, "evaluate_trajectory", tracking_evaluator)

    code = cli_main.main(["evaluate", str(trajectory_path)])

    assert code == 0
    assert calls["count"] == 1


def test_fail_on_warning_exits_one_for_incomplete_trajectory(tmp_path: Path) -> None:
    trajectory = _trajectory()
    trajectory.steps[0].end_time = None
    trajectory.completed_at = None
    trajectory_path = tmp_path / "trajectory.json"
    _write_trajectory(trajectory_path, trajectory)

    code = cli_main.main(["evaluate", str(trajectory_path), "--fail-on-warning"])

    assert code == 1
