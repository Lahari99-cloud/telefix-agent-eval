# Canonical Trajectory Schema

The canonical trajectory schema is the contract between framework-specific
OpenTelemetry ingestion and every downstream Telefix evaluation service. Ingestion
adapters may understand LangGraph, OpenAI Agents SDK, CrewAI, or custom spans, but
trajectory reconstruction, tool analysis, loop detection, state-drift checks, cost
attribution, regression testing, and deployment gates depend only on this schema.

Artifacts:

- JSON Schema: `schemas/trajectory_schema.json`
- Pydantic models: `telefix/models/trajectory.py`
- Current version: `trajectory.v1`

## Design Decisions

- **Versioned envelope**: `schema_version` is required and fixed to
  `trajectory.v1`. Future versions should add fields first and introduce breaking
  changes only with a new version string and schema file.
- **Forward compatible by default**: JSON Schema and Pydantic models allow
  additional properties. This lets ingestion add framework-specific diagnostics
  without breaking consumers that depend on the canonical fields.
- **ClickHouse-friendly shape**: top-level metadata is scalar, repeated execution
  data lives in `steps`, and repeated tool data lives in `steps.tool_calls`.
  Arrays can be flattened into `Nested` or `Array(Tuple(...))` columns while the
  scalar envelope remains easy to partition by `tenant_id`, `started_at`,
  `framework_name`, `model_name`, and `prompt_version`.
- **Bounded nesting**: the schema uses a shallow envelope with step and tool-call
  children. Arbitrary framework payloads are preserved only in `input_context`,
  `output_context`, `tool_input`, and `tool_output`.
- **Enums for analysis dimensions**: framework, node type, tool status, and risk
  level are enums so dashboards and regression queries can aggregate reliably.
- **Ordered reconstruction**: steps are contiguous, zero-based, and ordered by
  `step_index`. `parent_step_index` represents graph or span ancestry when a
  framework has branching execution.

## Field Definitions

### Metadata

| Field | Type | Description |
| --- | --- | --- |
| `schema_version` | enum | Canonical schema version, currently `trajectory.v1`. |
| `trajectory_id` | string | Telefix identifier for the normalized trajectory. |
| `tenant_id` | string | Tenant or workspace boundary for storage and access control. |
| `trace_id` | string | Source OpenTelemetry trace ID. |
| `session_id` | string/null | User, workflow, or conversation session ID when available. |
| `framework_name` | enum | `langgraph`, `openai_agents_sdk`, `crewai`, `custom`, or `unknown`. |
| `framework_version` | string/null | Source framework version when emitted. |
| `model_name` | string | Primary model used by the agent trajectory. |
| `model_version` | string/null | Provider model version, snapshot, or deployment revision. |
| `prompt_version` | string/null | Prompt template, policy, or agent configuration version. |
| `started_at` | datetime | Trajectory start time in UTC-compatible ISO 8601 format. |
| `completed_at` | datetime/null | Trajectory completion time, or null for partial traces. |

### Steps

Each trajectory has one or more ordered `steps`.

| Field | Type | Description |
| --- | --- | --- |
| `step_index` | integer | Zero-based execution order. |
| `node_name` | string | Framework node, span, chain, tool, or human checkpoint name. |
| `node_type` | enum | `llm`, `tool`, `human`, `system`, or `chain`. |
| `parent_step_index` | integer/null | Earlier step that owns or triggered this step. |
| `loop_iteration` | integer | Iteration count for repeated visits to the same logical node. |
| `input_context` | JSON | Normalized state before the step. |
| `output_context` | JSON | Normalized state after the step. |
| `start_time` | datetime | Step start time. |
| `end_time` | datetime/null | Step end time when available. |
| `latency_ms` | number | Step latency in milliseconds. |
| `tool_calls` | array | Tool calls executed inside this step. Empty for non-tool steps. |

### Tool Calls

| Field | Type | Description |
| --- | --- | --- |
| `tool_name` | string | Canonical tool identifier. |
| `tool_input` | JSON | Tool request payload after redaction. |
| `tool_output` | JSON | Tool response payload after redaction. |
| `tool_status` | enum | `success`, `error`, `timeout`, `skipped`, or `blocked`. |
| `is_destructive` | boolean | Whether the tool could modify external state. |
| `is_allowed` | boolean | Whether policy allowed the tool call. |
| `risk_level` | enum | `none`, `low`, `medium`, `high`, or `critical`. |
| `retry_count` | integer | Number of retries before the final status. |
| `latency_ms` | number | Tool latency in milliseconds. |

### Cost Metrics

| Field | Type | Description |
| --- | --- | --- |
| `prompt_tokens` | integer | Input tokens attributed to the trajectory. |
| `completion_tokens` | integer | Output tokens attributed to the trajectory. |
| `total_tokens` | integer | Sum of prompt and completion tokens. |
| `estimated_cost_usd` | number | Estimated provider cost in USD. |

### Evaluation Labels

| Field | Type | Description |
| --- | --- | --- |
| `ground_truth_root_cause` | string/null | Labeled failure or success root cause for regression datasets. |
| `expected_tool_sequence` | string array | Policy-approved or golden ordered tool names. |
| `actual_tool_sequence` | string array | Observed ordered tool names from normalized steps. |
| `unsafe_action_detected` | boolean | True when the trajectory attempted or completed unsafe work. |
| `loop_detected` | boolean | True when repeated node visits exceeded policy thresholds. |
| `escalation_required` | boolean | True when the trajectory requires human review or escalation. |

## Example Payload

```json
{
  "schema_version": "trajectory.v1",
  "trajectory_id": "traj_01HZX2M6K7X9R6",
  "tenant_id": "tenant_demo",
  "trace_id": "4f6f2c9e5a7b4b9a8e2c1d0f12345678",
  "session_id": "session_1001",
  "framework_name": "langgraph",
  "framework_version": "0.2.74",
  "model_name": "gpt-4.1-mini",
  "model_version": "2026-04-14",
  "prompt_version": "support-agent-policy-v12",
  "started_at": "2026-06-17T14:12:03Z",
  "completed_at": "2026-06-17T14:12:06Z",
  "steps": [
    {
      "step_index": 0,
      "node_name": "diagnose",
      "node_type": "llm",
      "parent_step_index": null,
      "loop_iteration": 0,
      "input_context": {
        "symptoms": "Internet drops every few minutes."
      },
      "output_context": {
        "next_tool": "read_modem_telemetry"
      },
      "start_time": "2026-06-17T14:12:03Z",
      "end_time": "2026-06-17T14:12:04Z",
      "latency_ms": 940.2,
      "tool_calls": []
    },
    {
      "step_index": 1,
      "node_name": "read_modem_telemetry",
      "node_type": "tool",
      "parent_step_index": 0,
      "loop_iteration": 0,
      "input_context": {
        "account_id": "demo-1001"
      },
      "output_context": {
        "status": "degraded"
      },
      "start_time": "2026-06-17T14:12:04Z",
      "end_time": "2026-06-17T14:12:05Z",
      "latency_ms": 310.0,
      "tool_calls": [
        {
          "tool_name": "read_modem_telemetry",
          "tool_input": {
            "account_id": "demo-1001"
          },
          "tool_output": {
            "snr_db": 28.1,
            "status": "degraded"
          },
          "tool_status": "success",
          "is_destructive": false,
          "is_allowed": true,
          "risk_level": "low",
          "retry_count": 0,
          "latency_ms": 302.4
        }
      ]
    }
  ],
  "cost_metrics": {
    "prompt_tokens": 1230,
    "completion_tokens": 220,
    "total_tokens": 1450,
    "estimated_cost_usd": 0.0042
  },
  "evaluation_labels": {
    "ground_truth_root_cause": "low_signal_noise_ratio",
    "expected_tool_sequence": ["read_modem_telemetry"],
    "actual_tool_sequence": ["read_modem_telemetry"],
    "unsafe_action_detected": false,
    "loop_detected": false,
    "escalation_required": false
  }
}
```

## OpenTelemetry Mapping

Ingestion adapters should transform OpenTelemetry traces into this canonical
payload and then discard framework-specific assumptions before evaluation.

| OpenTelemetry source | Canonical field |
| --- | --- |
| `trace_id` | `trace_id` |
| Root span ID or generated ID | `trajectory_id` |
| Resource or baggage tenant attribute | `tenant_id` |
| Conversation/session attribute | `session_id` |
| Instrumentation scope name | `framework_name` |
| Instrumentation scope version | `framework_version` |
| GenAI model attributes such as `gen_ai.request.model` | `model_name` |
| Provider deployment, snapshot, or response model version | `model_version` |
| Prompt, agent, graph, or policy version attribute | `prompt_version` |
| Earliest span start time | `started_at` |
| Latest span end time | `completed_at` |
| Topologically sorted spans, graph nodes, or run events | `steps` |
| Span name or graph node name | `steps[].node_name` |
| Span kind plus framework attributes | `steps[].node_type` |
| Parent span relationship | `steps[].parent_step_index` |
| Repeated visit count for the same node and parent path | `steps[].loop_iteration` |
| Span input attributes, messages, or state snapshot | `steps[].input_context` |
| Span output attributes, messages, or state snapshot | `steps[].output_context` |
| Span start and end timestamps | `steps[].start_time`, `steps[].end_time` |
| Span duration | `steps[].latency_ms` |
| Tool span name or tool call attribute | `steps[].tool_calls[].tool_name` |
| Tool request attributes | `steps[].tool_calls[].tool_input` |
| Tool response attributes | `steps[].tool_calls[].tool_output` |
| Span status and error attributes | `steps[].tool_calls[].tool_status` |
| Policy engine or tool registry metadata | `is_destructive`, `is_allowed`, `risk_level` |
| Retry attributes or repeated tool attempt spans | `retry_count` |
| GenAI token usage attributes | `cost_metrics.prompt_tokens`, `completion_tokens`, `total_tokens` |
| Provider pricing table applied by ingestion | `cost_metrics.estimated_cost_usd` |

Framework notes:

- **LangGraph**: map graph node executions to steps. Preserve state channels in
  `input_context` and `output_context`, and use repeated visits to populate
  `loop_iteration`.
- **OpenAI Agents SDK**: map agent run items and tool calls to ordered steps.
  Handoff or approval events should use `node_type` values `chain`, `tool`, or
  `human` depending on the event.
- **CrewAI**: map task and agent spans to `chain` or `llm` steps, then attach
  tool-use spans to the step that initiated them.

Evaluation labels are normally added by golden datasets, CI fixtures, or
post-processing evaluators after ingestion. They remain in the canonical payload
so regression gates can compare expected and observed behavior without reading
raw OpenTelemetry.
