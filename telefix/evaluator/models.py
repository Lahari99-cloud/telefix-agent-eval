"""Pydantic models for deterministic trajectory evaluation results."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from telefix.evaluator.rules import PolicyViolation
from telefix.evaluator.state_drift import StateDriftResult


class DeploymentDecision(StrEnum):
    PASS = "pass"
    FAIL = "fail"


class ForwardCompatibleEvaluationModel(BaseModel):
    model_config = ConfigDict(extra="allow", use_enum_values=True)


class UnsafeActionSummary(ForwardCompatibleEvaluationModel):
    unsafe_action_count: Annotated[int, Field(ge=0)]
    total_tool_calls: Annotated[int, Field(ge=0)]
    unsafe_action_rate: Annotated[float, Field(ge=0.0, le=1.0)]
    unsafe_tools: list[str] = Field(default_factory=list)


class ToolSelectionSummary(ForwardCompatibleEvaluationModel):
    expected_tool_sequence: list[str]
    actual_tool_sequence: list[str]
    matched_positions: Annotated[int, Field(ge=0)]
    precision: Annotated[float, Field(ge=0.0, le=1.0)]
    recall: Annotated[float, Field(ge=0.0, le=1.0)]
    sequence_exact_match: bool


class ToolConfusionEntry(ForwardCompatibleEvaluationModel):
    expected_tool: str | None
    actual_tool: str | None
    count: Annotated[int, Field(ge=1)]


class LoopSummary(ForwardCompatibleEvaluationModel):
    loop_detected: bool
    max_loop_iteration: Annotated[int, Field(ge=0)]
    loop_nodes: list[str] = Field(default_factory=list)


class EscalationSummary(ForwardCompatibleEvaluationModel):
    expected: bool
    actual: bool
    correct: bool


class CostSummary(ForwardCompatibleEvaluationModel):
    prompt_tokens: Annotated[int, Field(ge=0)]
    completion_tokens: Annotated[int, Field(ge=0)]
    total_tokens: Annotated[int, Field(ge=0)]
    estimated_cost_usd: Annotated[float, Field(ge=0.0)]


class LatencySummary(ForwardCompatibleEvaluationModel):
    total_latency_ms: Annotated[float, Field(ge=0.0)]
    max_step_latency_ms: Annotated[float, Field(ge=0.0)]
    average_step_latency_ms: Annotated[float, Field(ge=0.0)]
    incomplete_step_count: Annotated[int, Field(ge=0)]


class EvaluationResult(ForwardCompatibleEvaluationModel):
    trajectory_id: str
    trace_id: str
    decision: DeploymentDecision
    passed: bool
    failed_checks: list[str] = Field(default_factory=list)
    unsafe_actions: UnsafeActionSummary
    tool_selection: ToolSelectionSummary
    tool_confusion_matrix: list[ToolConfusionEntry]
    loops: LoopSummary
    escalation: EscalationSummary
    cost: CostSummary
    latency: LatencySummary
    policy_violations: list[PolicyViolation] = Field(default_factory=list)
    state_drift: StateDriftResult | None = None
