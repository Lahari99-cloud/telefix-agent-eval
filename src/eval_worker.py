"""Offline worker for evaluation events emitted by the live API path."""

from pydantic import BaseModel, Field

from src.event_stream import EvaluationEvent, EvaluationEventStream
from src.review_queue import ReviewQueue


class EventEvaluationSummary(BaseModel):
    event_id: str
    session_id: str
    groundedness_score: float = Field(ge=0.0, le=1.0)
    hallucination_risk: float = Field(ge=0.0, le=1.0)
    tool_selection_accuracy: float = Field(ge=0.0, le=1.0)
    workflow_completion: float = Field(ge=0.0, le=1.0)
    routed_to_review: bool


class EventProcessingResult(BaseModel):
    processed_count: int
    summaries: list[EventEvaluationSummary]


class OfflineEvaluationWorker:
    """Consume trace events and evaluate them away from the latency-sensitive path."""

    def __init__(
        self,
        event_stream: EvaluationEventStream,
        review_queue: ReviewQueue,
    ) -> None:
        self._event_stream = event_stream
        self._review_queue = review_queue

    async def process_pending(self) -> EventProcessingResult:
        events = await self._event_stream.consume_pending()
        summaries = [self._evaluate(event) for event in events]
        return EventProcessingResult(
            processed_count=len(summaries),
            summaries=summaries,
        )

    def _evaluate(self, event: EvaluationEvent) -> EventEvaluationSummary:
        has_context = bool(event.retrieved_context)
        evidence_terms = {"telemetry", "synthetic", "rf", "offline", "healthy", "reset"}
        response_terms = set(event.agent_response.lower().split())
        groundedness = 1.0 if has_context and evidence_terms & response_terms else 0.5
        expected_tools = (
            ["get_modem_telemetry", "perform_rf_reset", "get_modem_telemetry"]
            if event.workflow_status == "resolved"
            else ["get_modem_telemetry"]
        )
        tool_accuracy = self._ordered_accuracy(event.tools_triggered, expected_tools)
        workflow_completion = float(
            event.workflow_status in {"resolved", "escalate", "no_action"}
            and bool(event.agent_response)
        )
        hallucination_risk = round(1.0 - groundedness, 3)
        routed = self._review_queue.route_if_needed(
            case_id=event.event_id,
            strategy="offline_event_worker",
            severity="unknown",
            groundedness_score=groundedness,
            hallucination_risk=hallucination_risk,
        )
        return EventEvaluationSummary(
            event_id=event.event_id,
            session_id=event.session_id,
            groundedness_score=groundedness,
            hallucination_risk=hallucination_risk,
            tool_selection_accuracy=tool_accuracy,
            workflow_completion=workflow_completion,
            routed_to_review=routed,
        )

    @staticmethod
    def _ordered_accuracy(actual: list[str], expected: list[str]) -> float:
        matches = sum(
            actual[index] == expected[index]
            for index in range(min(len(actual), len(expected)))
        )
        return round(matches / max(len(actual), len(expected), 1), 3)
