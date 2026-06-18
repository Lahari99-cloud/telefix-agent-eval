"""OpenTelemetry helpers for the LangGraph integration example."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from opentelemetry import trace
from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor, SpanExporter, SpanExportResult

from telefix.trex.adapters.otel import RawOtelSpan

_EXPORTER: InMemorySpanExporter | None = None


class InMemorySpanExporter(SpanExporter):
    def __init__(self) -> None:
        self.spans: list[ReadableSpan] = []

    def export(self, spans: list[ReadableSpan]) -> SpanExportResult:
        self.spans.extend(spans)
        return SpanExportResult.SUCCESS

    def shutdown(self) -> None:
        return None

    def force_flush(self, timeout_millis: int = 30_000) -> bool:
        return True

    def clear(self) -> None:
        self.spans.clear()


def configure_tracing() -> InMemorySpanExporter:
    global _EXPORTER
    if _EXPORTER is not None:
        _EXPORTER.clear()
        return _EXPORTER

    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    _EXPORTER = exporter
    return exporter


def tracer():
    return trace.get_tracer("telefix.examples.langgraph")


def readable_span_to_raw(span: ReadableSpan) -> RawOtelSpan:
    context = span.get_span_context()
    parent = span.parent
    return RawOtelSpan(
        trace_id=f"{context.trace_id:032x}",
        span_id=f"{context.span_id:016x}",
        parent_span_id=f"{parent.span_id:016x}" if parent else None,
        start_time=_ns_to_datetime(span.start_time),
        end_time=_ns_to_datetime(span.end_time) if span.end_time else None,
        attributes=dict(span.attributes or {}),
        events=[
            {
                "name": event.name,
                "timestamp": _ns_to_datetime(event.timestamp).isoformat(),
                "attributes": dict(event.attributes or {}),
            }
            for event in span.events
        ],
    )


def exported_spans_to_raw(spans: list[ReadableSpan]) -> list[RawOtelSpan]:
    return [readable_span_to_raw(span) for span in spans]


def set_common_span_attributes(
    *,
    node_name: str,
    span_type: str,
    scenario: dict[str, Any],
    model_name: str = "mock-incident-agent",
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
) -> None:
    span = trace.get_current_span()
    span.set_attribute("agent.node", node_name)
    span.set_attribute("agent.span_type", span_type)
    span.set_attribute("agent.framework", "langgraph")
    span.set_attribute("agent.framework_version", "reference")
    sequence = int(scenario.get("_otel_sequence", 0))
    span.set_attribute("agent.sequence", sequence)
    scenario["_otel_sequence"] = sequence + 1
    span.set_attribute("tenant.id", "telecom-demo")
    span.set_attribute("session.id", scenario["name"])
    span.set_attribute("llm.model_name", model_name)
    if prompt_tokens:
        span.set_attribute("llm.prompt_tokens", prompt_tokens)
    if completion_tokens:
        span.set_attribute("llm.completion_tokens", completion_tokens)
    if prompt_tokens or completion_tokens:
        estimated_cost = round((prompt_tokens + completion_tokens) * 0.000002, 6)
        span.set_attribute("llm.estimated_cost_usd", estimated_cost)


def _ns_to_datetime(value: int) -> datetime:
    return datetime.fromtimestamp(value / 1_000_000_000, tz=UTC)
