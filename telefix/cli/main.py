"""Command-line interface for Telefix-Agent-Eval."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

import yaml
from pydantic import ValidationError

from telefix.cli.context import inject_runtime_context, load_runtime_context
from telefix.cli.reporting import (
    format_evaluation_report,
    warnings_for_result,
    write_json_report,
)
from telefix.evaluator.evaluate import evaluate_trajectory
from telefix.evaluator.models import DeploymentDecision
from telefix.evaluator.policies import EvaluationPolicy
from telefix.models.trajectory import Trajectory

PASS_EXIT_CODE = 0
FAIL_EXIT_CODE = 1
ERROR_EXIT_CODE = 2


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command == "evaluate":
        return _evaluate_command(args)

    parser.print_help(sys.stderr)
    return ERROR_EXIT_CODE


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="telefix")
    subparsers = parser.add_subparsers(dest="command")

    evaluate = subparsers.add_parser(
        "evaluate",
        help="Evaluate a canonical trajectory JSON file for deployment gating.",
    )
    evaluate.add_argument("trajectory", type=Path, help="Path to canonical trajectory JSON.")
    evaluate.add_argument("--policy", type=Path, help="Optional YAML evaluation policy.")
    evaluate.add_argument(
        "--context",
        help="Runtime context as inline JSON object or path to a JSON file.",
    )
    evaluate.add_argument("--json-output", type=Path, help="Optional path for JSON report.")
    evaluate.add_argument(
        "--fail-on-warning",
        action="store_true",
        help="Return exit code 1 when non-blocking warnings are present.",
    )

    return parser


def _evaluate_command(args: argparse.Namespace) -> int:
    try:
        trajectory = _load_trajectory(args.trajectory)
        if args.context:
            trajectory = inject_runtime_context(
                trajectory,
                load_runtime_context(args.context),
            )
        policy = _load_policy(args.policy) if args.policy else None
        result = evaluate_trajectory(trajectory, policy)
        warnings = warnings_for_result(result)

        print(format_evaluation_report(trajectory, result, warnings=warnings))

        if args.json_output:
            write_json_report(args.json_output, result, warnings)

        if result.decision == DeploymentDecision.FAIL:
            return FAIL_EXIT_CODE
        if args.fail_on_warning and warnings:
            return FAIL_EXIT_CODE
        return PASS_EXIT_CODE
    except (
        OSError,
        json.JSONDecodeError,
        ValidationError,
        yaml.YAMLError,
        TypeError,
        ValueError,
    ) as exc:
        print(f"telefix: error: {exc}", file=sys.stderr)
        return ERROR_EXIT_CODE


def _load_trajectory(path: Path) -> Trajectory:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return Trajectory.model_validate(payload)


def _load_policy(path: Path) -> EvaluationPolicy:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if payload is None:
        payload = {}
    if not isinstance(payload, dict):
        raise ValueError("policy YAML must contain a mapping")
    return EvaluationPolicy.model_validate(payload)


if __name__ == "__main__":
    raise SystemExit(main())
