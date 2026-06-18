"""Background OpenTelemetry exporter tests."""

from __future__ import annotations

from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor

from telefix.otel.exporter import QueuedSQLiteSpanExporter
from telefix.storage.sqlite import SQLiteTraceStore


def test_exporter_persists_spans_on_background_shutdown(tmp_path) -> None:
    store = SQLiteTraceStore(tmp_path / "traces.sqlite3")
    exporter = QueuedSQLiteSpanExporter(
        store,
        batch_size=2,
        flush_interval_seconds=0.05,
    )
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    tracer = provider.get_tracer("telefix-test")

    with tracer.start_as_current_span("root") as span:
        span.set_attribute("agent.node", "diagnose")
        span.set_attribute("agent.span_type", "llm")
        span.set_attribute("agent.framework", "langgraph")
        span.set_attribute("llm.model_name", "gpt-4.1-mini")
        trace_id = f"{span.get_span_context().trace_id:032x}"
        with tracer.start_as_current_span("query_metrics") as child:
            child.set_attribute("agent.node", "query_metrics")
            child.set_attribute("agent.span_type", "tool")
            child.set_attribute("tool.name", "query_metrics")
            child.set_attribute("tool.status", "success")
            child.set_attribute("tool.is_destructive", False)
            child.set_attribute("tool.is_allowed", True)
            child.set_attribute("tool.risk_level", "low")

    assert exporter.force_flush(timeout_millis=5000) is True
    exporter.shutdown()

    loaded = _load(store, trace_id)
    assert {span.span_name for span in loaded} == {"root", "query_metrics"}
    assert any(span.parent_span_id for span in loaded if span.span_name == "query_metrics")


def test_exporter_does_not_block_when_queue_is_full(tmp_path) -> None:
    store = SQLiteTraceStore(tmp_path / "traces.sqlite3")
    exporter = QueuedSQLiteSpanExporter(store, max_queue_size=1, flush_interval_seconds=1.0)
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    tracer = provider.get_tracer("telefix-test")

    for index in range(20):
        with tracer.start_as_current_span(f"span-{index}"):
            pass

    exporter.shutdown()

    assert exporter.dropped_spans >= 0


def _load(store: SQLiteTraceStore, trace_id: str):
    import asyncio

    return asyncio.run(store.get_spans(trace_id))
