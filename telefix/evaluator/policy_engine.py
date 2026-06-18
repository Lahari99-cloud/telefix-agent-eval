"""Deterministic context-aware policy rule evaluation."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from telefix.evaluator.context import (
    MISSING,
    build_tool_context,
    iter_tool_calls,
    resolve_context_path,
)
from telefix.evaluator.policies import EvaluationPolicy
from telefix.evaluator.rules import ContextCondition, PolicyRule, PolicyViolation, RuleOutcome
from telefix.models.trajectory import Trajectory


def evaluate_policy_rules(
    trajectory: Trajectory,
    policy: EvaluationPolicy,
) -> list[PolicyViolation]:
    """Evaluate context-aware policy rules against canonical trajectory tool calls."""

    violations: list[PolicyViolation] = []
    rules = list(policy.rules)
    if not rules and not policy.forbidden_tools:
        return violations

    for step, tool_call in iter_tool_calls(trajectory):
        context = build_tool_context(trajectory, step, tool_call)
        if tool_call.tool_name in policy.forbidden_tools:
            violations.append(
                PolicyViolation(
                    tool_name=tool_call.tool_name,
                    rule_index=-1,
                    reason="tool is forbidden",
                    outcome=RuleOutcome.FAIL,
                )
            )
        for rule_index, rule in enumerate(rules):
            if rule.tool != tool_call.tool_name:
                continue
            violation = _evaluate_rule(rule, rule_index, tool_call.tool_name, context)
            if violation is not None:
                violations.append(violation)

    return violations


def _evaluate_rule(
    rule: PolicyRule,
    rule_index: int,
    tool_name: str,
    context: dict[str, Any],
) -> PolicyViolation | None:
    denied = _evaluate_conditions(rule.denied_if, context)
    if denied.matched and rule.denied_if:
        return PolicyViolation(
            tool_name=tool_name,
            rule_index=rule_index,
            reason="denied_if matched",
            outcome=RuleOutcome.FAIL,
        )

    allowed = _evaluate_conditions(rule.allowed_if, context)
    if allowed.matched:
        return None

    if rule.otherwise != RuleOutcome.FAIL:
        return None

    return PolicyViolation(
        tool_name=tool_name,
        rule_index=rule_index,
        reason="allowed_if conditions not satisfied",
        missing_context=allowed.missing_context,
        failed_conditions=allowed.failed_conditions,
        outcome=rule.otherwise,
    )


class _ConditionResult:
    def __init__(
        self,
        *,
        matched: bool,
        missing_context: list[str] | None = None,
        failed_conditions: list[str] | None = None,
    ) -> None:
        self.matched = matched
        self.missing_context = missing_context or []
        self.failed_conditions = failed_conditions or []


def _evaluate_conditions(
    conditions: dict[str, ContextCondition],
    context: dict[str, Any],
) -> _ConditionResult:
    missing_context: list[str] = []
    failed_conditions: list[str] = []

    for path, condition in conditions.items():
        actual = resolve_context_path(context, path)
        if actual is MISSING:
            missing_context.append(path)
            continue
        if not _condition_matches(actual, condition):
            failed_conditions.append(path)

    return _ConditionResult(
        matched=not missing_context and not failed_conditions,
        missing_context=missing_context,
        failed_conditions=failed_conditions,
    )


def _condition_matches(actual: Any, condition: ContextCondition) -> bool:
    return all(
        _operator_matches(actual, operator, expected)
        for operator, expected in condition.operators.items()
    )


def _operator_matches(actual: Any, operator: str, expected: Any) -> bool:
    if operator == "eq":
        return actual == expected
    if operator == "neq":
        return actual != expected
    if operator == "gt":
        return _compare(actual, expected, operator)
    if operator == "gte":
        return _compare(actual, expected, operator)
    if operator == "lt":
        return _compare(actual, expected, operator)
    if operator == "lte":
        return _compare(actual, expected, operator)
    if operator == "in":
        return _contains(expected, actual)
    if operator == "not_in":
        return not _contains(expected, actual)
    return False


def _compare(actual: Any, expected: Any, operator: str) -> bool:
    try:
        if operator == "gt":
            return actual > expected
        if operator == "gte":
            return actual >= expected
        if operator == "lt":
            return actual < expected
        if operator == "lte":
            return actual <= expected
    except TypeError:
        return False
    return False


def _contains(expected_values: Any, actual: Any) -> bool:
    if isinstance(expected_values, Sequence) and not isinstance(expected_values, str):
        return actual in expected_values
    return actual == expected_values
