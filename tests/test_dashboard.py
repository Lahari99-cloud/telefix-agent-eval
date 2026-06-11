"""Dashboard transformation tests that do not require a running UI."""

from dashboard.client import (
    ab_metric_rows,
    case_rows,
    failure_analysis_rows,
    quality_gate_status,
)


def test_quality_gate_passes_current_thresholds() -> None:
    status, detail = quality_gate_status(
        {
            "tool_selection_accuracy": 1.0,
            "workflow_completion_rate": 1.0,
            "groundedness_score": 0.95,
            "hallucination_risk": 0.05,
        }
    )

    assert status == "PASS"
    assert "satisfied" in detail


def test_case_rows_flattens_evaluation_results() -> None:
    rows = case_rows(
        {
            "cases": [
                {
                    "case_id": "synthetic-1",
                    "severity": "medium",
                    "actual_resolution_type": "resolved",
                    "tool_selection_accuracy": 1.0,
                    "groundedness_score": 0.9,
                    "hallucination_risk": 0.1,
                    "latency_ms": 4.2,
                    "routed_to_review": False,
                }
            ]
        }
    )

    assert rows[0]["case"] == "synthetic-1"
    assert rows[0]["resolution"] == "resolved"
    assert rows[0]["tool_accuracy"] == 1.0


def test_ab_rows_include_both_strategies() -> None:
    metric = {"baseline": 0.9, "strict_grounded": 0.95, "delta": 0.05}
    rows = ab_metric_rows(
        {
            "comparison": {
                "groundedness_score": metric,
                "hallucination_risk": metric,
                "tool_selection_accuracy": metric,
                "workflow_completion_rate": metric,
            }
        }
    )

    assert len(rows) == 8
    assert {row["strategy"] for row in rows} == {"Baseline", "Strict grounded"}


def test_failure_analysis_prioritizes_grounding_and_latency_signals() -> None:
    rows = failure_analysis_rows(
        {
            "aggregate": {"average_latency_ms": 10.0},
            "cases": [
                {
                    "case_id": "healthy",
                    "severity": "low",
                    "actual_resolution_type": "no_action",
                    "tool_selection_accuracy": 1.0,
                    "workflow_completed": True,
                    "groundedness_score": 1.0,
                    "hallucination_risk": 0.0,
                    "latency_ms": 5.0,
                },
                {
                    "case_id": "needs-analysis",
                    "severity": "high",
                    "actual_resolution_type": "escalate",
                    "tool_selection_accuracy": 1.0,
                    "workflow_completed": True,
                    "groundedness_score": 0.5,
                    "hallucination_risk": 0.5,
                    "latency_ms": 20.0,
                },
            ],
        }
    )

    assert rows[0]["case"] == "needs-analysis"
    assert "Grounding gap" in rows[0]["failure_modes"]
    assert "Hallucination risk" in rows[0]["failure_modes"]
    assert "Latency outlier" in rows[0]["failure_modes"]
    assert rows[-1]["failure_modes"] == "Healthy"
