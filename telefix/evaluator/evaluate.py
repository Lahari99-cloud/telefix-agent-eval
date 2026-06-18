"""Public evaluation API for canonical trajectories."""

from __future__ import annotations

from telefix.evaluator.metrics import (
    cost_summary,
    escalation_summary,
    latency_summary,
    loop_summary,
    tool_confusion_matrix,
    tool_selection_summary,
    unsafe_action_summary,
)
from telefix.evaluator.models import DeploymentDecision, EvaluationResult
from telefix.evaluator.policies import DEFAULT_EVALUATION_POLICY, EvaluationPolicy
from telefix.evaluator.policy_engine import evaluate_policy_rules
from telefix.evaluator.state_drift import analyze_state_drift
from telefix.models.trajectory import Trajectory


def evaluate_trajectory(
    trajectory: Trajectory,
    policy: EvaluationPolicy | None = None,
) -> EvaluationResult:
    """Evaluate a canonical trajectory with deterministic policy checks."""

    active_policy = policy or DEFAULT_EVALUATION_POLICY
    unsafe = unsafe_action_summary(trajectory)
    tool_selection = tool_selection_summary(trajectory)
    loops = loop_summary(trajectory)
    escalation = escalation_summary(trajectory)
    cost = cost_summary(trajectory)
    latency = latency_summary(trajectory)
    policy_violations = evaluate_policy_rules(trajectory, active_policy)
    state_drift = (
        analyze_state_drift(
            trajectory,
            max_semantic_redundancy_score=active_policy.state_drift.max_semantic_redundancy_score,
            min_objective_retention_score=active_policy.state_drift.min_objective_retention_score,
            max_context_growth_ratio=active_policy.state_drift.max_context_growth_ratio,
        )
        if active_policy.state_drift.enabled
        else None
    )

    failed_checks = _failed_checks(
        trajectory=trajectory,
        policy=active_policy,
        unsafe=unsafe,
        tool_selection=tool_selection,
        loops=loops,
        escalation=escalation,
        cost=cost,
        latency=latency,
        policy_violations=policy_violations,
        state_drift=state_drift,
    )
    passed = not failed_checks

    return EvaluationResult(
        trajectory_id=trajectory.trajectory_id,
        trace_id=trajectory.trace_id,
        decision=DeploymentDecision.PASS if passed else DeploymentDecision.FAIL,
        passed=passed,
        failed_checks=failed_checks,
        unsafe_actions=unsafe,
        tool_selection=tool_selection,
        tool_confusion_matrix=tool_confusion_matrix(trajectory),
        loops=loops,
        escalation=escalation,
        cost=cost,
        latency=latency,
        policy_violations=policy_violations,
        state_drift=state_drift,
    )


def _failed_checks(
    *,
    trajectory: Trajectory,
    policy: EvaluationPolicy,
    unsafe,
    tool_selection,
    loops,
    escalation,
    cost,
    latency,
    policy_violations,
    state_drift,
) -> list[str]:
    failures: list[str] = []

    if not (getattr(trajectory, "steps", []) or []):
        failures.append("empty_trajectory")
    if unsafe.unsafe_action_rate > policy.max_unsafe_action_rate:
        failures.append("unsafe_action_rate")
    if tool_selection.precision < policy.min_tool_precision:
        failures.append("tool_precision")
    if loops.max_loop_iteration > policy.max_loop_iterations:
        failures.append("loop_iterations")
    if cost.estimated_cost_usd > policy.max_total_cost_usd:
        failures.append("total_cost")
    if latency.total_latency_ms > policy.max_latency_ms:
        failures.append("latency")
    if policy.require_escalation_when_expected and not escalation.correct:
        failures.append("escalation")
    if policy_violations:
        failures.append("policy_rules")
    if state_drift is not None and state_drift.drift_detected:
        failures.append("state_drift")

    return failures
