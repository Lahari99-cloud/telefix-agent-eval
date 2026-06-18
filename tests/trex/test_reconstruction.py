"""T-REx trajectory reconstruction tests."""

from datetime import UTC, datetime, timedelta

import pytest

from telefix.models.trajectory import Trajectory
from telefix.trex.adapters.otel import InMemorySpanLoader, RawOtelSpan
from telefix.trex.reconstruct import configure_span_loader, reconstruct_trajectory


def _time(seconds: int) -> datetime:
    return datetime(2026, 6, 17, 14, 12, seconds, tzinfo=UTC)


def _span(
    span_id: str,
    start_second: int,
    *,
    parent_span_id: str | None = None,
    duration_ms: int = 100,
    attributes: dict[str, object] | None = None,
    complete: bool = True,
) -> RawOtelSpan:
    start = _time(start_second)
    return RawOtelSpan(
        trace_id="trace-trex",
        span_id=span_id,
        parent_span_id=parent_span_id,
        start_time=start,
        end_time=start + timedelta(milliseconds=duration_ms) if complete else None,
        attributes=attributes or {},
        events=[],
    )


@pytest.mark.asyncio
async def test_reconstructs_unordered_spans_into_canonical_trajectory() -> None:
    spans = [
        _span(
            "tool-read",
            4,
            parent_span_id="root",
            duration_ms=250,
            attributes={
                "agent.node": "read_modem_telemetry",
                "agent.span_type": "tool",
                "agent.input": '{"account_id": "demo-1001"}',
                "agent.output": '{"status": "degraded"}',
                "tool.name": "read_modem_telemetry",
                "tool.input": '{"account_id": "demo-1001"}',
                "tool.output": '{"status": "degraded", "snr_db": 28.1}',
                "tool.status": "success",
                "tool.is_destructive": False,
                "tool.is_allowed": True,
                "tool.risk_level": "low",
                "tool.retry_count": 1,
            },
        ),
        _span(
            "root",
            3,
            duration_ms=900,
            attributes={
                "tenant.id": "tenant-demo",
                "session.id": "session-demo",
                "agent.framework": "langgraph",
                "agent.framework_version": "0.2.74",
                "agent.node": "diagnose",
                "agent.span_type": "llm",
                "agent.input": {"symptom": "drops"},
                "agent.output": {"next_tool": "read_modem_telemetry"},
                "llm.model_name": "gpt-4.1-mini",
                "llm.model_version": "2026-04-14",
                "prompt.version": "support-policy-v1",
                "llm.prompt_tokens": 120,
                "llm.completion_tokens": 30,
                "llm.estimated_cost_usd": 0.0015,
            },
        ),
        _span(
            "tool-reset",
            5,
            parent_span_id="root",
            duration_ms=500,
            attributes={
                "agent.node": "reset_modem",
                "agent.span_type": "tool",
                "tool.name": "reset_modem",
                "tool.input": {"account_id": "demo-1001"},
                "tool.output": {"reset": "queued"},
                "tool.status": "blocked",
                "tool.is_destructive": True,
                "tool.is_allowed": False,
                "tool.risk_level": "high",
            },
        ),
    ]
    configure_span_loader(InMemorySpanLoader({"trace-trex": spans}))

    trajectory = await reconstruct_trajectory("trace-trex")

    assert isinstance(trajectory, Trajectory)
    assert trajectory.tenant_id == "tenant-demo"
    assert trajectory.session_id == "session-demo"
    assert trajectory.framework_name == "langgraph"
    assert trajectory.model_name == "gpt-4.1-mini"
    assert [step.node_name for step in trajectory.steps] == [
        "diagnose",
        "read_modem_telemetry",
        "reset_modem",
    ]
    assert trajectory.steps[1].parent_step_index == 0
    assert trajectory.steps[2].parent_step_index == 0
    assert trajectory.steps[1].latency_ms == 250.0
    assert trajectory.steps[1].tool_calls[0].tool_name == "read_modem_telemetry"
    assert trajectory.steps[1].tool_calls[0].retry_count == 1
    assert trajectory.evaluation_labels.actual_tool_sequence == [
        "read_modem_telemetry",
        "reset_modem",
    ]
    assert trajectory.evaluation_labels.unsafe_action_detected is True
    assert trajectory.cost_metrics.prompt_tokens == 120
    assert trajectory.cost_metrics.completion_tokens == 30
    assert trajectory.cost_metrics.total_tokens == 150

    dumped = trajectory.model_dump(mode="json")
    assert dumped["schema_version"] == "trajectory.v1"


@pytest.mark.asyncio
async def test_detects_loop_iterations_and_incomplete_human_pause() -> None:
    spans = [
        _span(
            "root",
            1,
            attributes={
                "tenant.id": "tenant-demo",
                "agent.node": "support_graph",
                "agent.span_type": "chain",
                "llm.model_name": "gpt-4.1-mini",
            },
        ),
        _span(
            "retry-a",
            2,
            parent_span_id="root",
            attributes={"agent.node": "clarify_issue", "agent.span_type": "llm"},
        ),
        _span(
            "retry-b",
            3,
            parent_span_id="root",
            attributes={"agent.node": "clarify_issue", "agent.span_type": "llm"},
        ),
        _span(
            "human",
            4,
            parent_span_id="root",
            attributes={"agent.node": "human_approval", "agent.span_type": "human"},
            complete=False,
        ),
    ]
    configure_span_loader(InMemorySpanLoader({"trace-trex": list(reversed(spans))}))

    trajectory = await reconstruct_trajectory("trace-trex")

    assert [step.step_index for step in trajectory.steps] == [0, 1, 2, 3]
    assert trajectory.steps[1].loop_iteration == 0
    assert trajectory.steps[2].loop_iteration == 1
    assert trajectory.steps[3].node_type == "human"
    assert trajectory.steps[3].end_time is None
    assert trajectory.steps[3].latency_ms == 0.0
    assert trajectory.completed_at is None
    assert trajectory.evaluation_labels.loop_detected is True
    assert trajectory.evaluation_labels.escalation_required is True
