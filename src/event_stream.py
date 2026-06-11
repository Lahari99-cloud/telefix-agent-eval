"""Asynchronous evaluation event stream abstractions."""

from datetime import UTC, datetime
from typing import Protocol

from pydantic import BaseModel, Field


class EvaluationEvent(BaseModel):
    """Compact immutable trace emitted by the latency-sensitive live path."""

    event_id: str
    session_id: str
    user_prompt: str
    retrieved_context: list[str]
    agent_response: str
    tools_triggered: list[str]
    latency_ms: float = Field(ge=0.0)
    timestamp: datetime
    workflow_status: str
    processed: bool = False


class EvaluationEventStream(Protocol):
    """Transport-neutral event publishing and consumption contract."""

    async def publish(self, event: EvaluationEvent) -> None:
        """Publish an evaluation trace."""

    async def list_events(self) -> list[EvaluationEvent]:
        """Return an observable event snapshot."""

    async def consume_pending(self) -> list[EvaluationEvent]:
        """Claim events that have not yet been evaluated."""


class InMemoryEventStream:
    """Process-local event stream used by tests and the local demo."""

    def __init__(self) -> None:
        self._events: dict[str, EvaluationEvent] = {}

    async def publish(self, event: EvaluationEvent) -> None:
        self._events[event.event_id] = event.model_copy(deep=True)

    async def list_events(self) -> list[EvaluationEvent]:
        return sorted(
            (event.model_copy(deep=True) for event in self._events.values()),
            key=lambda event: event.timestamp,
        )

    async def consume_pending(self) -> list[EvaluationEvent]:
        pending: list[EvaluationEvent] = []
        for event_id, event in self._events.items():
            if event.processed:
                continue
            pending.append(event.model_copy(deep=True))
            self._events[event_id] = event.model_copy(update={"processed": True})
        return pending


class KafkaStyleEventStream(Protocol):
    """Optional adapter boundary for Kafka, Kinesis, or another durable stream."""

    async def publish(self, event: EvaluationEvent) -> None:
        """Serialize and publish an event to a durable topic."""


def new_event(
    *,
    event_id: str,
    session_id: str,
    user_prompt: str,
    retrieved_context: list[str],
    agent_response: str,
    tools_triggered: list[str],
    latency_ms: float,
    workflow_status: str,
) -> EvaluationEvent:
    return EvaluationEvent(
        event_id=event_id,
        session_id=session_id,
        user_prompt=user_prompt,
        retrieved_context=retrieved_context,
        agent_response=agent_response,
        tools_triggered=tools_triggered,
        latency_ms=latency_ms,
        timestamp=datetime.now(UTC),
        workflow_status=workflow_status,
    )
