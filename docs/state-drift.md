# State-Drift Analysis

State-drift analysis detects deterministic signs that an agent's working context
is degrading across a multi-step trajectory, especially during loops.

It uses pure-Python token overlap metrics. It does not call LLMs, embeddings APIs,
external model downloads, OpenTelemetry, storage, or dashboards.

## Policy

State drift is disabled by default and can be enabled in an evaluation policy:

```yaml
state_drift:
  enabled: true
  max_semantic_redundancy_score: 0.85
  min_objective_retention_score: 0.60
  max_context_growth_ratio: 3.0
```

When enabled, `evaluate_trajectory(...)` computes `state_drift` and fails the
deployment decision with `state_drift` in `failed_checks` if thresholds are
exceeded.

## Metrics

- `semantic_redundancy_score`: maximum adjacent-step Jaccard similarity. High
  values indicate repeated reasoning.
- `objective_retention_score`: fraction of objective tokens retained in the final
  step context. Low values indicate the agent lost the original objective.
- `context_growth_ratio`: largest step token count divided by the first step token
  count. High values indicate irrelevant context accumulation.
- `repeated_context_ratio`: fraction of steps whose exact token signature appears
  more than once.
- `drift_detected`: true when any enabled threshold is violated.

## Context Inputs

The analyzer uses:

- `step.input_context`
- `step.output_context`
- `evaluation_labels.ground_truth_root_cause`
- optional custom trajectory metadata such as `context.incident.objective`
- `loop_iteration` indirectly through repeated step context

The implementation is intentionally simple and deterministic so it can run in CI
without network access or model dependencies.
