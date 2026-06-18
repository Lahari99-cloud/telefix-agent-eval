# SQLite Trace Store

Telefix includes a lightweight persistence path for raw OpenTelemetry spans:

```text
OpenTelemetry SDK -> bounded queue -> background writer -> SQLite -> T-REx
```

The goal is to decouple telemetry persistence from the agent under test. The
OpenTelemetry exporter enqueues spans without waiting for SQLite writes. A
background thread flushes batches to the async trace store.

## Files

- `telefix/storage/base.py`: `TraceStore` protocol and raw `OTelSpan` model.
- `telefix/storage/sqlite.py`: async SQLite implementation and T-REx loader.
- `telefix/storage/schema.sql`: raw span schema.
- `telefix/otel/exporter.py`: non-blocking OpenTelemetry span exporter.

## Schema

The store persists raw spans only:

- `trace_id`
- `span_id`
- `parent_span_id`
- `span_name`
- `start_time`
- `end_time`
- `attributes_json`
- `events_json`
- `status_code`

It does not store workflow nodes, execution steps, reconstructed metrics, or
evaluation results. T-REx remains responsible for reconstruction.

## Usage

```python
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor

from telefix.otel.exporter import QueuedSQLiteSpanExporter
from telefix.storage.sqlite import SQLiteTraceStore

store = SQLiteTraceStore("traces.sqlite3")
exporter = QueuedSQLiteSpanExporter(store)

provider = TracerProvider()
provider.add_span_processor(SimpleSpanProcessor(exporter))
```

Load spans back through T-REx:

```python
from telefix.trex.reconstruct import configure_span_loader, reconstruct_trajectory

configure_span_loader(store)
trajectory = await reconstruct_trajectory(trace_id)
```

## Behavior

- Writes are batched.
- The queue is bounded.
- `export()` uses non-blocking enqueue operations.
- `force_flush()` waits for queued spans to persist.
- `shutdown()` drains queued spans before stopping the worker.
- Duplicate writes are safe through the `(trace_id, span_id)` primary key.

This is intentionally not an OTLP receiver, ClickHouse adapter, Redis consumer,
Kafka pipeline, or multi-tenant storage service.
