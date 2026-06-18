"""Canonical trajectory models for normalized agent telemetry."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

JsonValue = dict[str, Any] | list[Any] | str | int | float | bool | None
NonEmptyId = Annotated[str, Field(min_length=1, max_length=128)]


class ForwardCompatibleModel(BaseModel):
    """Base model that accepts additive fields from newer schema producers."""

    model_config = ConfigDict(extra="allow", use_enum_values=True)


class FrameworkName(StrEnum):
    LANGGRAPH = "langgraph"
    OPENAI_AGENTS_SDK = "openai_agents_sdk"
    CREWAI = "crewai"
    CUSTOM = "custom"
    UNKNOWN = "unknown"


class NodeType(StrEnum):
    LLM = "llm"
    TOOL = "tool"
    HUMAN = "human"
    SYSTEM = "system"
    CHAIN = "chain"


class ToolStatus(StrEnum):
    SUCCESS = "success"
    ERROR = "error"
    TIMEOUT = "timeout"
    SKIPPED = "skipped"
    BLOCKED = "blocked"


class RiskLevel(StrEnum):
    NONE = "none"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ToolCall(ForwardCompatibleModel):
    tool_name: Annotated[str, Field(min_length=1, max_length=256)]
    tool_input: JsonValue
    tool_output: JsonValue
    tool_status: ToolStatus
    is_destructive: bool
    is_allowed: bool
    risk_level: RiskLevel
    retry_count: Annotated[int, Field(ge=0)]
    latency_ms: Annotated[float, Field(ge=0)]


class CostMetrics(ForwardCompatibleModel):
    prompt_tokens: Annotated[int, Field(ge=0)]
    completion_tokens: Annotated[int, Field(ge=0)]
    total_tokens: Annotated[int, Field(ge=0)]
    estimated_cost_usd: Annotated[float, Field(ge=0)]

    @model_validator(mode="after")
    def validate_total_tokens(self) -> CostMetrics:
        expected_total = self.prompt_tokens + self.completion_tokens
        if self.total_tokens != expected_total:
            raise ValueError("total_tokens must equal prompt_tokens + completion_tokens")
        return self


class EvaluationLabels(ForwardCompatibleModel):
    ground_truth_root_cause: Annotated[str | None, Field(default=None, max_length=512)]
    expected_tool_sequence: list[Annotated[str, Field(max_length=256)]]
    actual_tool_sequence: list[Annotated[str, Field(max_length=256)]]
    unsafe_action_detected: bool
    loop_detected: bool
    escalation_required: bool


class TrajectoryStep(ForwardCompatibleModel):
    step_index: Annotated[int, Field(ge=0)]
    node_name: Annotated[str, Field(min_length=1, max_length=256)]
    node_type: NodeType
    parent_step_index: Annotated[int | None, Field(default=None, ge=0)]
    loop_iteration: Annotated[int, Field(ge=0)]
    input_context: JsonValue
    output_context: JsonValue
    start_time: datetime
    end_time: datetime | None = None
    latency_ms: Annotated[float, Field(ge=0)]
    tool_calls: list[ToolCall] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_step_timing(self) -> TrajectoryStep:
        if self.end_time is not None and self.end_time < self.start_time:
            raise ValueError("end_time must be greater than or equal to start_time")
        return self


class Trajectory(ForwardCompatibleModel):
    schema_version: Literal["trajectory.v1"] = "trajectory.v1"
    trajectory_id: NonEmptyId
    tenant_id: NonEmptyId
    trace_id: NonEmptyId
    session_id: Annotated[str | None, Field(default=None, max_length=128)]
    framework_name: FrameworkName
    framework_version: Annotated[str | None, Field(default=None, max_length=64)]
    model_name: Annotated[str, Field(min_length=1, max_length=128)]
    model_version: Annotated[str | None, Field(default=None, max_length=128)]
    prompt_version: Annotated[str | None, Field(default=None, max_length=128)]
    started_at: datetime
    completed_at: datetime | None = None
    steps: Annotated[list[TrajectoryStep], Field(min_length=1)]
    cost_metrics: CostMetrics
    evaluation_labels: EvaluationLabels

    @model_validator(mode="after")
    def validate_trajectory(self) -> Trajectory:
        indexes = [step.step_index for step in self.steps]
        expected_indexes = list(range(len(self.steps)))
        if indexes != expected_indexes:
            raise ValueError("steps must be ordered with contiguous zero-based step_index values")

        for step in self.steps:
            if step.parent_step_index is not None and step.parent_step_index >= step.step_index:
                raise ValueError("parent_step_index must reference an earlier step")

        if self.completed_at is not None and self.completed_at < self.started_at:
            raise ValueError("completed_at must be greater than or equal to started_at")

        return self
