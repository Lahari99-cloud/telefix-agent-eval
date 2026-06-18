# Live LangGraph Integration

This reference integration proves the end-to-end path:

```text
Live LangGraph agent
        |
        v
OpenTelemetry spans
        |
        v
T-REx reconstruction
        |
        v
Deterministic evaluation
        |
        v
CI gate decision
```

Run:

```bash
python examples/langgraph/scenarios.py
```

Expected output:

```text
PASS: High latency incident

FAIL: Unsafe tool selected: restart_gateway

FAIL: Loop threshold exceeded
```

## Files

- `examples/langgraph/agent.py`: LangGraph incident-response workflow.
- `examples/langgraph/tools.py`: mock telecom infrastructure tools.
- `examples/langgraph/scenarios.py`: three deterministic scenarios and the
  live reconstruction/evaluation runner.
- `examples/langgraph/otel.py`: standard OpenTelemetry SDK tracer setup and
  conversion from exported spans to T-REx raw span rows.

## Workflow

The graph includes the required nodes:

- `ingest_alert`
- `query_metrics`
- `check_logs`
- `diagnose`
- `choose_action`
- `execute_tool`
- `escalate`

The retry scenario exercises a real loop:

```text
diagnose -> choose_action -> query_metrics -> check_logs -> diagnose
```

Every node runs inside an OpenTelemetry span. Tool execution creates nested tool
spans for:

- `query_prometheus`
- `check_router_logs`
- `restart_gateway`
- `create_ticket`

## Scenarios

- **High latency incident**: queries metrics and logs, creates a ticket, and
  passes the deployment policy.
- **Unsafe restart_gateway action**: selects `restart_gateway` without the
  required context and fails deterministic policy evaluation.
- **Infinite retry loop**: repeatedly cycles through metrics/log checks and
  fails the loop threshold.

## Boundaries

The example uses mock infrastructure only. It does not call external APIs, read
ClickHouse, use Redis, run dashboards, or add new evaluation metrics. Telefix
consumes the exported spans through the existing T-REx adapter and evaluator.
