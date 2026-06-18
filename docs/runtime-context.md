# Runtime Context Injection

The Telefix CLI can inject runtime context at evaluation time:

```bash
telefix evaluate trajectory.json \
  --policy policy.yaml \
  --context context.json
```

Inline JSON is also supported:

```bash
telefix evaluate trajectory.json \
  --policy policy.yaml \
  --context '{"network":{"packet_loss_pct":98}}'
```

## Merge Order

Runtime context is merged into the evaluator context with this precedence:

1. CLI `--context`
2. trajectory-provided `context` and other forward-compatible metadata
3. default canonical trajectory fields

Nested objects are merged recursively. If the same nested key appears in the
trajectory and CLI context, the CLI value wins.

## Policy Example

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

With runtime context:

```bash
telefix evaluate incident.json \
  --policy restart-policy.yaml \
  --context '{"network":{"packet_loss_pct":98},"incident":{"severity":"critical"},"human_approval":true}'
```

Invalid JSON or non-object JSON context returns CLI exit code `2`.

## GitHub Actions

The local GitHub Action wrapper also accepts runtime context through
`context-path`:

```yaml
- uses: ./.github/actions/evaluate
  with:
    trajectory-path: incident.json
    policy-path: restart-policy.yaml
    context-path: runtime-context.json
```
