"""Run the Telefix-Agent-Eval end-to-end examples."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from telefix.evaluator.evaluate import evaluate_trajectory  # noqa: E402
from telefix.evaluator.policies import EvaluationPolicy  # noqa: E402
from telefix.models.trajectory import EvaluationLabels, Trajectory  # noqa: E402
from telefix.trex.adapters.otel import InMemorySpanLoader, RawOtelSpan  # noqa: E402
from telefix.trex.reconstruct import configure_span_loader, reconstruct_trajectory  # noqa: E402

EXAMPLES_ROOT = ROOT / "examples" / "telecom"

SCENARIOS = [
    ("high_latency", "High latency incident"),
    ("tool_misfire", "Unsafe tool selected: restart_gateway"),
    ("bgp_route_flap", "Loop threshold exceeded"),
]


async def main() -> int:
    for scenario_dir, label in SCENARIOS:
        scenario_path = EXAMPLES_ROOT / scenario_dir
        reconstructed = await _reconstruct(scenario_path)
        expected = _load_expected_trajectory(scenario_path)
        reconstructed.evaluation_labels = EvaluationLabels.model_validate(
            expected.evaluation_labels.model_dump(mode="json")
        )
        policy = _load_policy(scenario_path)
        result = evaluate_trajectory(reconstructed, policy)
        prefix = "PASS" if result.passed else "FAIL"
        print(f"{prefix}: {label}")
    return 0


async def _reconstruct(scenario_path: Path) -> Trajectory:
    spans_payload = json.loads((scenario_path / "spans.json").read_text(encoding="utf-8"))
    spans = [RawOtelSpan.model_validate(span) for span in spans_payload["spans"]]
    trace_id = spans_payload["trace_id"]
    configure_span_loader(InMemorySpanLoader({trace_id: spans}))
    return await reconstruct_trajectory(trace_id)


def _load_expected_trajectory(scenario_path: Path) -> Trajectory:
    payload = json.loads((scenario_path / "expected_trajectory.json").read_text(encoding="utf-8"))
    return Trajectory.model_validate(payload)


def _load_policy(scenario_path: Path) -> EvaluationPolicy:
    payload = yaml.safe_load((scenario_path / "policy.yaml").read_text(encoding="utf-8"))
    return EvaluationPolicy.model_validate(payload or {})


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
