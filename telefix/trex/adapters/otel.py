"""OpenTelemetry span adapter for T-REx reconstruction."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field, field_validator

from telefix.models.trajectory import NodeType, RiskLevel, ToolCall, ToolStatus


class RawOtelSpan(BaseModel):
    """Minimal OpenTelemetry span shape loaded from analytical storage."""

    model_config = ConfigDict(extra="allow")

    trace_id: str
    span_id: str
    parent_span_id: str | None = None
    start_time: datetime
    end_time: datetime | None = None
    attributes: dict[str, Any] = Field(default_factory=dict)
    events: list[dict[str, Any]] = Field(default_factory=list)

    @field_validator("start_time", "end_time")
    @classmethod
    def normalize_datetime(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value


class SpanLoader(Protocol):
    """Async source for raw spans.

    Production implementations can read ClickHouse rows and return `RawOtelSpan`
    objects. Tests can use `InMemorySpanLoader` without any storage dependency.
    """

    async def load_spans(self, trace_id: str) -> Sequence[RawOtelSpan]:
        """Load all spans for a trace ID."""


class InMemorySpanLoader:
    """Simple async span loader for tests and local fixtures."""

    def __init__(self, spans_by_trace_id: Mapping[str, Sequence[RawOtelSpan]]) -> None:
        self._spans_by_trace_id = spans_by_trace_id

    async def load_spans(self, trace_id: str) -> Sequence[RawOtelSpan]:
        return list(self._spans_by_trace_id.get(trace_id, []))


def attr(span: RawOtelSpan, key: str, default: Any = None) -> Any:
    return span.attributes.get(key, default)


def parse_context(value: Any) -> Any:
    """Return JSON-compatible context from span attributes."""

    if value is None:
        return {}
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return {}
        try:
            return json.loads(stripped)
        except json.JSONDecodeError:
            return stripped
    return value


def span_latency_ms(span: RawOtelSpan) -> float:
    if span.end_time is None:
        return 0.0
    return max((span.end_time - span.start_time).total_seconds() * 1000.0, 0.0)


def infer_node_name(span: RawOtelSpan) -> str:
    value = attr(span, "agent.node") or attr(span, "tool.name") or attr(span, "span.name")
    return str(value or span.span_id)


def infer_node_type(span: RawOtelSpan) -> NodeType:
    explicit = str(attr(span, "agent.span_type", "")).lower()
    if explicit in {node_type.value for node_type in NodeType}:
        return NodeType(explicit)
    if attr(span, "tool.name") is not None:
        return NodeType.TOOL
    if attr(span, "llm.model_name") is not None:
        return NodeType.LLM
    return NodeType.CHAIN


def infer_tool_status(span: RawOtelSpan) -> ToolStatus:
    explicit = str(attr(span, "tool.status", "")).lower()
    if explicit in {status.value for status in ToolStatus}:
        return ToolStatus(explicit)

    span_status = str(attr(span, "otel.status_code", attr(span, "status.code", ""))).lower()
    if span_status in {"error", "2"}:
        return ToolStatus.ERROR
    if attr(span, "tool.blocked", False):
        return ToolStatus.BLOCKED
    return ToolStatus.SUCCESS


def infer_risk_level(span: RawOtelSpan) -> RiskLevel:
    explicit = str(attr(span, "tool.risk_level", "none")).lower()
    if explicit in {risk.value for risk in RiskLevel}:
        return RiskLevel(explicit)
    return RiskLevel.NONE


def extract_tool_call(span: RawOtelSpan) -> ToolCall | None:
    tool_name = attr(span, "tool.name")
    if tool_name is None:
        return None

    return ToolCall(
        tool_name=str(tool_name),
        tool_input=parse_context(attr(span, "tool.input")),
        tool_output=parse_context(attr(span, "tool.output")),
        tool_status=infer_tool_status(span),
        is_destructive=bool(attr(span, "tool.is_destructive", False)),
        is_allowed=bool(attr(span, "tool.is_allowed", True)),
        risk_level=infer_risk_level(span),
        retry_count=max(int(attr(span, "tool.retry_count", 0) or 0), 0),
        latency_ms=float(attr(span, "tool.latency_ms", span_latency_ms(span)) or 0.0),
    )
