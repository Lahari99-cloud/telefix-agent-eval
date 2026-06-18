# CI/CD Gate CLI

The Telefix CLI evaluates canonical trajectory JSON files in release pipelines
and exits with deterministic status codes.

```bash
telefix evaluate trajectory.json
telefix evaluate trajectory.json --policy policy.yaml
telefix evaluate trajectory.json --json-output report.json
telefix evaluate trajectory.json --fail-on-warning
```

Exit codes:

- `0`: deployment decision passed
- `1`: deployment decision failed
- `2`: invalid input, invalid policy, or runtime/configuration error

## Inputs

The `evaluate` command accepts canonical trajectory JSON that validates against
`telefix.models.trajectory.Trajectory`. It does not parse OpenTelemetry spans or
read from ClickHouse.

Optional policy files are YAML mappings passed to
`telefix.evaluator.policies.EvaluationPolicy`:

```yaml
max_unsafe_action_rate: 0.0
min_tool_precision: 0.95
max_loop_iterations: 3
max_total_cost_usd: 1.00
max_latency_ms: 30000
require_escalation_when_expected: true
```

## Report

The terminal report includes:

- Trajectory ID and trace ID
- Framework and model
- Deployment decision
- Unsafe action rate
- Tool precision and recall
- Loop summary
- Cost summary
- Latency summary
- Policy violations
- Warnings

Machine-readable reports are written with `--json-output`. The JSON payload is
the evaluator `EvaluationResult` plus a `warnings` array.

## Warnings

Warnings are non-blocking by default. `--fail-on-warning` turns warnings into a
release-blocking exit code `1`. In v1, incomplete canonical steps are reported as
`incomplete_steps`.

## Boundary

The CLI is a release-gating interface over canonical trajectories and the
deterministic evaluator. It does not implement new metrics, OpenTelemetry
parsing, storage clients, Redis consumers, dashboards, or CI/CD orchestration.
