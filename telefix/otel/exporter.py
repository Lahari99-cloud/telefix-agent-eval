"""Non-blocking OpenTelemetry exporter backed by a SQLite trace store."""

from __future__ import annotations

import asyncio
import queue
import threading
from datetime import UTC, datetime

from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.sdk.trace.export import SpanExporter, SpanExportResult

from telefix.storage.base import OTelSpan, TraceStore


class QueuedSQLiteSpanExporter(SpanExporter):
    """Queue spans synchronously and persist them from a background thread."""

    def __init__(
        self,
        store: TraceStore,
        *,
        max_queue_size: int = 2048,
        batch_size: int = 128,
        flush_interval_seconds: float = 0.5,
    ) -> None:
        self._store = store
        self._batch_size = batch_size
        self._flush_interval = flush_interval_seconds
        self._queue: queue.Queue[OTelSpan | None] = queue.Queue(maxsize=max_queue_size)
        self._stop = threading.Event()
        self._thread = threading.Thread(
            target=self._run_worker,
            name="telefix-sqlite-span-exporter",
            daemon=True,
        )
        self._dropped_spans = 0
        self._thread.start()

    @property
    def dropped_spans(self) -> int:
        return self._dropped_spans

    def export(self, spans: list[ReadableSpan]) -> SpanExportResult:
        dropped = False
        for readable_span in spans:
            try:
                self._queue.put_nowait(readable_span_to_otel_span(readable_span))
            except queue.Full:
                self._dropped_spans += 1
                dropped = True
        return SpanExportResult.FAILURE if dropped else SpanExportResult.SUCCESS

    def force_flush(self, timeout_millis: int = 30_000) -> bool:
        deadline = threading.Event()

        def wait_until_empty() -> None:
            self._queue.join()
            deadline.set()

        waiter = threading.Thread(target=wait_until_empty, daemon=True)
        waiter.start()
        return deadline.wait(timeout_millis / 1000)

    def shutdown(self) -> None:
        if self._stop.is_set():
            return
        self._stop.set()
        try:
            self._queue.put_nowait(None)
        except queue.Full:
            pass
        self._thread.join(timeout=max(self._flush_interval * 2, 1.0))

    def _run_worker(self) -> None:
        batch: list[OTelSpan] = []
        while not self._stop.is_set() or not self._queue.empty():
            got_sentinel = False
            try:
                item = self._queue.get(timeout=self._flush_interval)
            except queue.Empty:
                item = None
            else:
                got_sentinel = item is None

            if item is None:
                if batch:
                    self._write_batch(batch)
                    for _ in batch:
                        self._queue.task_done()
                    batch = []
                if got_sentinel:
                    self._queue.task_done()
                    break
                continue

            batch.append(item)
            if len(batch) >= self._batch_size:
                self._write_batch(batch)
                for _ in batch:
                    self._queue.task_done()
                batch = []

        if batch:
            self._write_batch(batch)
            for _ in batch:
                self._queue.task_done()

    def _write_batch(self, batch: list[OTelSpan]) -> None:
        asyncio.run(self._store.write_spans(list(batch)))


def readable_span_to_otel_span(span: ReadableSpan) -> OTelSpan:
    context = span.get_span_context()
    parent = span.parent
    status = getattr(span, "status", None)
    status_code = str(status.status_code.name).lower() if status else None
    return OTelSpan(
        trace_id=f"{context.trace_id:032x}",
        span_id=f"{context.span_id:016x}",
        parent_span_id=f"{parent.span_id:016x}" if parent else None,
        span_name=span.name,
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
        status_code=status_code,
    )


def _ns_to_datetime(value: int) -> datetime:
    return datetime.fromtimestamp(value / 1_000_000_000, tz=UTC)
