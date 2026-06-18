# T-REx v1

T-REx, the Trajectory Reconstruction Engine, is the only Telefix component that
understands OpenTelemetry span internals. It loads raw spans for one trace,
reconstructs execution order, and emits the canonical `Trajectory` model from
`telefix/models/trajectory.py`.

The public API is:

```python
from telefix.trex.reconstruct import configure_span_loader, reconstruct_trajectory

configure_span_loader(clickhouse_span_loader)
trajectory = await reconstruct_trajectory("trace-id")
```

`configure_span_loader` accepts any async object implementing:

```python
async def load_spans(trace_id: str) -> Sequence[RawOtelSpan]:
    ...
```

Production code should provide a ClickHouse-backed implementation. T-REx v1
intentionally does not include a ClickHouse client.

## Reconstruction Flow

1. Load raw spans by `trace_id`.
2. Build a parent-child map from `span_id` and `parent_span_id`.
3. Sort roots and children by `(start_time, span_id)` to tolerate out-of-order
   storage reads.
4. Walk the graph parent-first to produce contiguous `step_index` values.
5. Detect loop iterations by counting repeated `(parent_span_id, node_name)`
   visits.
6. Convert each span into a canonical `TrajectoryStep`.
7. Convert spans with `tool.name` into canonical `ToolCall` records.
8. Aggregate LLM token attributes into `CostMetrics`.
9. Calculate latency from span timestamps. Incomplete spans keep `end_time=null`
   and use `latency_ms=0.0`.

## OpenTelemetry Adapter

`telefix/trex/adapters/otel.py` owns OpenTelemetry-specific parsing:

- `RawOtelSpan`: minimal span row shape expected from storage.
- `SpanLoader`: async protocol for loading spans.
- `InMemorySpanLoader`: test fixture loader.
- Attribute helpers for node type, tool status, risk level, context parsing, and
  latency calculation.

No framework-specific logic should be added to `reconstruct.py`. Framework
normalization belongs in adapter code so downstream services can remain tied only
to canonical trajectories.

## Attribute Mapping

| Span field or attribute | Canonical field |
| --- | --- |
| `trace_id` | `Trajectory.trace_id` |
| generated `traj_{trace_id}` | `Trajectory.trajectory_id` |
| `tenant.id` | `Trajectory.tenant_id` |
| `session.id` | `Trajectory.session_id` |
| `agent.framework` | `Trajectory.framework_name` |
| `agent.framework_version` | `Trajectory.framework_version` |
| `llm.model_name` | `Trajectory.model_name` |
| `llm.model_version` | `Trajectory.model_version` |
| `prompt.version` | `Trajectory.prompt_version` |
| earliest `start_time` | `Trajectory.started_at` |
| latest `end_time`, when all spans are complete | `Trajectory.completed_at` |
| `agent.node`, `tool.name`, or `span.name` | `TrajectoryStep.node_name` |
| `agent.span_type` or inferred type | `TrajectoryStep.node_type` |
| parent span relationship | `TrajectoryStep.parent_step_index` |
| repeated node visit count | `TrajectoryStep.loop_iteration` |
| `agent.input` | `TrajectoryStep.input_context` |
| `agent.output` | `TrajectoryStep.output_context` |
| `tool.*` attributes | `ToolCall` |
| `llm.prompt_tokens`, `llm.completion_tokens` | `CostMetrics` |

## Incomplete Traces

Partial traces are valid. Missing parent spans become root steps. Missing
`end_time` values leave the trajectory `completed_at` unset and keep the affected
step open. Human-in-the-loop pauses are represented as `node_type="human"` and
set `evaluation_labels.escalation_required=true`.
