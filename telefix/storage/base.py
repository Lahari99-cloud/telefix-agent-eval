"""Trace storage interfaces and raw span models."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field, field_validator

from telefix.trex.adapters.otel import RawOtelSpan


class OTelSpan(BaseModel):
    """Raw OpenTelemetry span persisted before T-REx reconstruction."""

    model_config = ConfigDict(extra="allow")

    trace_id: str
    span_id: str
    parent_span_id: str | None = None
    span_name: str
    start_time: datetime
    end_time: datetime | None = None
    attributes: dict[str, Any] = Field(default_factory=dict)
    events: list[dict[str, Any]] = Field(default_factory=list)
    status_code: str | None = None

    @field_validator("start_time", "end_time")
    @classmethod
    def normalize_datetime(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value

    def to_raw_otel_span(self) -> RawOtelSpan:
        attributes = dict(self.attributes)
        attributes.setdefault("span.name", self.span_name)
        if self.status_code:
            attributes.setdefault("otel.status_code", self.status_code)
        return RawOtelSpan(
            trace_id=self.trace_id,
            span_id=self.span_id,
            parent_span_id=self.parent_span_id,
            start_time=self.start_time,
            end_time=self.end_time,
            attributes=attributes,
            events=self.events,
        )


class TraceStore(Protocol):
    async def write_spans(self, spans: list[OTelSpan]) -> None:
        """Persist raw OpenTelemetry spans."""

    async def get_spans(self, trace_id: str) -> list[OTelSpan]:
        """Load raw OpenTelemetry spans for a trace."""
