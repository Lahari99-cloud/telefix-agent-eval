# GitHub Action

Telefix-Agent-Eval includes a composite GitHub Action that wraps the existing
CLI release gate:

```bash
telefix evaluate
```

The action does not implement evaluation logic. It validates and evaluates a
canonical trajectory through the CLI, parses the JSON report, exposes selected
outputs, and exits with the same deterministic status code.

## Usage

```yaml
- name: Evaluate agent safety
  id: telefix
  uses: ./.github/actions/evaluate
  with:
    trajectory-path: examples/telecom/tool_misfire/expected_trajectory.json
    policy-path: examples/telecom/tool_misfire/policy.yaml
```

Failing evaluations stop the workflow because `telefix evaluate` exits `1`.
Invalid inputs or configuration exit `2`.

## Inputs

| Input | Required | Description |
| --- | --- | --- |
| `trajectory-path` | yes | Canonical trajectory JSON file to evaluate. |
| `policy-path` | no | YAML evaluation policy. |
| `fail-on-warning` | no | Set to `true` to fail when warnings are present. |
| `json-output-path` | no | Optional path for the JSON report. |
| `context-path` | no | Optional path to a JSON runtime context file passed to `--context`. |

If `json-output-path` is omitted, the action writes a temporary report so outputs
can still be exposed to downstream steps.

## Outputs

| Output | Description |
| --- | --- |
| `deployment-decision` | `pass`, `fail`, or `error`. |
| `unsafe-action-rate` | Unsafe action rate from the evaluator. |
| `tool-precision` | Tool-selection precision. |
| `loop-detected` | Whether loop detection triggered. |
| `state-drift-detected` | Whether state drift detection triggered. |

Example downstream usage:

```yaml
- name: Use Telefix outputs
  run: |
    echo "Decision: ${{ steps.telefix.outputs.deployment-decision }}"
    echo "Tool precision: ${{ steps.telefix.outputs.tool-precision }}"
```

## Repository CI

The checked-in workflow at `.github/workflows/ci.yml` installs the package,
runs tests and lint, then evaluates the passing high-latency fixture with the
local action.

The reusable example at `examples/github-actions/evaluate.yml` shows the minimal
workflow teams can adapt in their own repositories.
