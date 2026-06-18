# Context-Aware Policies

Evaluation policies can include deterministic rules for tools that are safe only
under specific operating conditions.

```yaml
rules:
  - tool: restart_gateway
    allowed_if:
      network.packet_loss_pct:
        gte: 95
      incident.severity:
        eq: critical
      human_approval:
        eq: true
    otherwise: FAIL
```

The public API is:

```python
from telefix.evaluator.policy_engine import evaluate_policy_rules

violations = evaluate_policy_rules(trajectory, policy)
```

`evaluate_trajectory(...)` also runs these rules and fails the deployment
decision with `policy_rules` when violations are present.

## Context Sources

Rules evaluate tool calls using a merged context:

- trajectory metadata under `trajectory.*`
- evaluation labels under `evaluation.*`
- cost metrics under `cost.*`
- top-level custom trajectory fields, including a nested `context` object
- step `input_context` and `output_context`
- tool input and output payloads
- canonical tool fields under `tool.*`

Tool and step payloads are overlaid on trajectory context so incident-specific
fields such as `network.packet_loss_pct`, `incident.severity`, and
`human_approval` can be evaluated at action time.

## Operators

Supported operators:

- `eq`
- `neq`
- `gt`
- `gte`
- `lt`
- `lte`
- `in`
- `not_in`

Multiple operators on one variable and multiple variables in one rule combine
with logical AND. Unknown context variables fail safely. Invalid operators are
Pydantic validation errors.

## Static And Conditional Rules

Static denylist:

```yaml
forbidden_tools:
  - restart_gateway
```

Conditional allowlist:

```yaml
rules:
  - tool: restart_gateway
    allowed_if:
      network.packet_loss_pct:
        gte: 95
      human_approval:
        eq: true
    otherwise: FAIL
```

Conditional denylist:

```yaml
rules:
  - tool: apply_route_change
    denied_if:
      incident.severity:
        not_in: [critical]
```

The engine is deterministic and does not call LLMs, embeddings, OpenTelemetry,
ClickHouse, or Redis.
