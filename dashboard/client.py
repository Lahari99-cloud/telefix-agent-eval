"""Typed HTTP client and data transformations for the dashboard."""

from dataclasses import dataclass
from typing import Any, Protocol


class HttpResponse(Protocol):
    def raise_for_status(self) -> None:
        """Raise when the response is unsuccessful."""

    def json(self) -> Any:
        """Decode the JSON response."""


class HttpSession(Protocol):
    def get(self, url: str, *, timeout: float) -> HttpResponse:
        """Issue an HTTP GET request."""

    def post(self, url: str, *, timeout: float) -> HttpResponse:
        """Issue an HTTP POST request."""


@dataclass(frozen=True)
class DashboardSnapshot:
    evaluation: dict[str, Any]
    experiment: dict[str, Any]
    review_queue: list[dict[str, Any]]
    events: list[dict[str, Any]]


class TelefixApiClient:
    """Fetch dashboard data from the FastAPI service."""

    def __init__(
        self,
        base_url: str,
        session: HttpSession,
        *,
        timeout_seconds: float = 30.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._session = session
        self._timeout = timeout_seconds

    def load_snapshot(self) -> DashboardSnapshot:
        evaluation = self._post("/api/v1/evaluations/run")
        experiment = self._post("/api/v1/experiments/ab-test")
        review_queue = self._get("/api/v1/review-queue")
        events = self._get("/api/v1/events")
        return DashboardSnapshot(
            evaluation=evaluation,
            experiment=experiment,
            review_queue=review_queue,
            events=events,
        )

    def _get(self, path: str) -> Any:
        response = self._session.get(f"{self._base_url}{path}", timeout=self._timeout)
        response.raise_for_status()
        return response.json()

    def _post(self, path: str) -> Any:
        response = self._session.post(f"{self._base_url}{path}", timeout=self._timeout)
        response.raise_for_status()
        return response.json()


def quality_gate_status(aggregate: dict[str, Any]) -> tuple[str, str]:
    """Return an interview-friendly release gate label and explanation."""

    checks = {
        "tool selection": aggregate["tool_selection_accuracy"] >= 0.80,
        "workflow completion": aggregate["workflow_completion_rate"] >= 0.85,
        "groundedness": aggregate["groundedness_score"] >= 0.75,
        "hallucination risk": aggregate["hallucination_risk"] <= 0.35,
    }
    failed = [name for name, passed in checks.items() if not passed]
    if failed:
        return "BLOCKED", f"Below threshold: {', '.join(failed)}"
    return "PASS", "All CI quality thresholds satisfied"


def case_rows(evaluation: dict[str, Any]) -> list[dict[str, Any]]:
    """Flatten per-case results for charts and tables."""

    return [
        {
            "case": case["case_id"],
            "severity": case["severity"],
            "resolution": case["actual_resolution_type"],
            "tool_accuracy": case["tool_selection_accuracy"],
            "groundedness": case["groundedness_score"],
            "hallucination_risk": case["hallucination_risk"],
            "latency_ms": case["latency_ms"],
            "review": case["routed_to_review"],
        }
        for case in evaluation["cases"]
    ]


def ab_metric_rows(experiment: dict[str, Any]) -> list[dict[str, Any]]:
    """Convert A/B metric comparisons into a chart-friendly shape."""

    labels = {
        "groundedness_score": "Groundedness",
        "hallucination_risk": "Hallucination risk",
        "tool_selection_accuracy": "Tool accuracy",
        "workflow_completion_rate": "Completion",
    }
    rows: list[dict[str, Any]] = []
    for key, label in labels.items():
        comparison = experiment["comparison"][key]
        rows.extend(
            [
                {
                    "metric": label,
                    "strategy": "Baseline",
                    "score": comparison["baseline"],
                },
                {
                    "metric": label,
                    "strategy": "Strict grounded",
                    "score": comparison["strict_grounded"],
                },
            ]
        )
    return rows


def failure_analysis_rows(
    evaluation: dict[str, Any],
    *,
    latency_multiplier: float = 1.5,
) -> list[dict[str, Any]]:
    """Rank cases by quality risk and attach actionable failure explanations."""

    cases = evaluation["cases"]
    average_latency = evaluation["aggregate"]["average_latency_ms"]
    latency_threshold = average_latency * latency_multiplier
    rows: list[dict[str, Any]] = []

    for case in cases:
        failure_modes: list[str] = []
        recommendations: list[str] = []
        groundedness = case["groundedness_score"]
        hallucination_risk = case["hallucination_risk"]
        tool_accuracy = case["tool_selection_accuracy"]

        if groundedness < 0.75:
            failure_modes.append("Grounding gap")
            recommendations.append("Inspect retrieval ranking and expected context coverage.")
        if hallucination_risk > 0.35:
            failure_modes.append("Hallucination risk")
            recommendations.append("Route to human review and tighten evidence constraints.")
        if tool_accuracy < 0.80:
            failure_modes.append("Tool mismatch")
            recommendations.append("Review tool-selection policy and ordered execution trace.")
        if not case["workflow_completed"]:
            failure_modes.append("Incomplete workflow")
            recommendations.append("Inspect terminal-state routing and response completion.")
        if case["latency_ms"] > latency_threshold:
            failure_modes.append("Latency outlier")
            recommendations.append("Profile retrieval and tool execution on this scenario.")

        failure_score = (
            (1.0 - groundedness) * 0.35
            + hallucination_risk * 0.30
            + (1.0 - tool_accuracy) * 0.20
            + (0.0 if case["workflow_completed"] else 0.15)
        )
        if case["latency_ms"] > latency_threshold:
            failure_score += 0.05

        rows.append(
            {
                "case": case["case_id"],
                "severity": case["severity"],
                "resolution": case["actual_resolution_type"],
                "failure_score": round(min(1.0, failure_score), 3),
                "groundedness": groundedness,
                "hallucination_risk": hallucination_risk,
                "tool_accuracy": tool_accuracy,
                "latency_ms": case["latency_ms"],
                "failure_modes": ", ".join(failure_modes) if failure_modes else "Healthy",
                "recommendation": (
                    " ".join(recommendations)
                    if recommendations
                    else "No remediation required; continue monitoring."
                ),
            }
        )

    return sorted(
        rows,
        key=lambda row: (row["failure_score"], row["hallucination_risk"]),
        reverse=True,
    )
