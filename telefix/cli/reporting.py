"""Human-readable and JSON report helpers for the Telefix CI gate."""

from __future__ import annotations

import json
from pathlib import Path

from telefix.evaluator.models import EvaluationResult
from telefix.models.trajectory import Trajectory


def warnings_for_result(result: EvaluationResult) -> list[str]:
    warnings: list[str] = []
    if result.latency.incomplete_step_count:
        warnings.append("incomplete_steps")
    return warnings


def format_evaluation_report(
    trajectory: Trajectory,
    result: EvaluationResult,
    *,
    warnings: list[str] | None = None,
) -> str:
    warnings = warnings or []
    violations = result.failed_checks or ["none"]
    loop_nodes = ", ".join(result.loops.loop_nodes) if result.loops.loop_nodes else "none"
    warning_text = ", ".join(warnings) if warnings else "none"

    return "\n".join(
        [
            "Telefix Evaluation Report",
            "=========================",
            f"Trajectory ID: {trajectory.trajectory_id}",
            f"Trace ID: {trajectory.trace_id}",
            f"Framework: {trajectory.framework_name}",
            f"Model: {trajectory.model_name}",
            f"Deployment decision: {result.decision}",
            "",
            "Metrics",
            "-------",
            f"Unsafe action rate: {result.unsafe_actions.unsafe_action_rate:.6f}",
            f"Tool precision: {result.tool_selection.precision:.6f}",
            f"Tool recall: {result.tool_selection.recall:.6f}",
            (
                "Loop summary: "
                f"detected={result.loops.loop_detected}, "
                f"max_iteration={result.loops.max_loop_iteration}, "
                f"nodes={loop_nodes}"
            ),
            (
                "Cost summary: "
                f"tokens={result.cost.total_tokens}, "
                f"estimated_cost_usd={result.cost.estimated_cost_usd:.6f}"
            ),
            (
                "Latency summary: "
                f"total_ms={result.latency.total_latency_ms:.3f}, "
                f"max_step_ms={result.latency.max_step_latency_ms:.3f}, "
                f"avg_step_ms={result.latency.average_step_latency_ms:.3f}, "
                f"incomplete_steps={result.latency.incomplete_step_count}"
            ),
            "",
            f"Policy violations: {', '.join(violations)}",
            f"Warnings: {warning_text}",
        ]
    )


def write_json_report(path: Path, result: EvaluationResult, warnings: list[str]) -> None:
    payload = result.model_dump(mode="json")
    payload["warnings"] = warnings
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
