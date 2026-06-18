CREATE TABLE IF NOT EXISTS otel_spans (
  trace_id TEXT NOT NULL,
  span_id TEXT NOT NULL,
  parent_span_id TEXT,
  span_name TEXT NOT NULL,
  start_time TEXT NOT NULL,
  end_time TEXT,
  attributes_json TEXT NOT NULL,
  events_json TEXT NOT NULL,
  status_code TEXT,
  PRIMARY KEY (trace_id, span_id)
);

CREATE INDEX IF NOT EXISTS idx_otel_spans_trace_start
ON otel_spans (trace_id, start_time, span_id);
