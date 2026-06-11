"""Public API and evaluation schemas."""

from enum import StrEnum

from pydantic import BaseModel, Field


class ServiceStatus(StrEnum):
    ONLINE = "online"
    DEGRADED = "degraded"
    OFFLINE = "offline"


class WorkflowStatus(StrEnum):
    RESOLVED = "resolved"
    ESCALATE = "escalate"
    NO_ACTION = "no_action"


class DiagnoseRequest(BaseModel):
    """Synthetic customer context supplied to the troubleshooting agent."""

    account_id: str = Field(min_length=3, max_length=64, examples=["demo-1001"])
    symptoms: str = Field(
        min_length=3,
        max_length=500,
        examples=["Internet is slow and drops every few minutes."],
    )
    consent_to_reset: bool = Field(
        default=False,
        description="Explicit permission to run the mock RF reset.",
    )
    session_id: str | None = Field(
        default=None,
        min_length=8,
        max_length=128,
        description="Existing session to resume, or omitted to create a new session.",
    )


class TelemetrySnapshot(BaseModel):
    modem_id: str
    status: ServiceStatus
    downstream_power_dbmv: float
    upstream_power_dbmv: float
    snr_db: float
    corrected_codewords: int
    uncorrectable_codewords: int
    last_seen_seconds_ago: int


class Citation(BaseModel):
    document_id: str
    title: str
    excerpt: str
    score: float = Field(ge=0.0, le=1.0)
    lexical_hits: int = Field(default=0, ge=0)
    semantic_hits: int = Field(default=0, ge=0)
    fused_rank: int | None = Field(default=None, ge=1)
    rerank_score: float = Field(default=0.0, ge=0.0, le=1.0)


class EvaluationMetrics(BaseModel):
    tool_selection: float = Field(ge=0.0, le=1.0)
    groundedness: float = Field(ge=0.0, le=1.0)
    hallucination_risk: float = Field(ge=0.0, le=1.0)
    workflow_completion: float = Field(ge=0.0, le=1.0)
    selected_tools: list[str]
    expected_tools: list[str]
    unsupported_claims: list[str] = Field(default_factory=list)


class DiagnoseResponse(BaseModel):
    session_id: str = ""
    account_id: str
    workflow_status: WorkflowStatus
    summary: str
    recommended_action: str
    reset_performed: bool
    telemetry_before: TelemetrySnapshot
    telemetry_after: TelemetrySnapshot | None = None
    citations: list[Citation]
    evaluation: EvaluationMetrics
    trace: list[str]
