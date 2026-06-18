"""SQLite trace store tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from telefix.models.trajectory import Trajectory
from telefix.storage.base import OTelSpan
from telefix.storage.sqlite import SQLiteTraceStore
from telefix.trex.reconstruct import configure_span_loader, reconstruct_trajectory


def _span(
    span_id: str,
    *,
    parent_span_id: str | None = None,
    offset_seconds: int = 0,
    tool_name: str | None = None,
) -> OTelSpan:
    start = datetime(2026, 6, 17, 14, 12, offset_seconds, tzinfo=UTC)
    attributes = {
        "tenant.id": "tenant-sqlite",
        "session.id": "session-sqlite",
        "agent.framework": "langgraph",
        "agent.node": tool_name or "diagnose",
        "agent.span_type": "tool" if tool_name else "llm",
        "llm.model_name": "gpt-4.1-mini",
        "llm.prompt_tokens": 10 if parent_span_id is None else 0,
        "llm.completion_tokens": 5 if parent_span_id is None else 0,
    }
    if tool_name:
        attributes.update(
            {
                "tool.name": tool_name,
                "tool.input": {"gateway": "gw-1"},
                "tool.output": {"status": "ok"},
                "tool.status": "success",
                "tool.is_destructive": False,
                "tool.is_allowed": True,
                "tool.risk_level": "low",
            }
        )
    return OTelSpan(
        trace_id="trace-sqlite",
        span_id=span_id,
        parent_span_id=parent_span_id,
        span_name=tool_name or "diagnose",
        start_time=start,
        end_time=start + timedelta(milliseconds=100),
        attributes=attributes,
        events=[],
        status_code="ok",
    )


@pytest.mark.asyncio
async def test_sqlite_store_persists_spans_across_instances(tmp_path) -> None:
    db_path = tmp_path / "traces.sqlite3"
    store = SQLiteTraceStore(db_path)

    await store.write_spans(
        [_span("root"), _span("tool", parent_span_id="root", tool_name="query_metrics")]
    )

    restarted_store = SQLiteTraceStore(db_path)
    loaded = await restarted_store.get_spans("trace-sqlite")

    assert [span.span_id for span in loaded] == ["root", "tool"]
    assert loaded[1].attributes["tool.name"] == "query_metrics"


@pytest.mark.asyncio
async def test_duplicate_writes_are_idempotent(tmp_path) -> None:
    store = SQLiteTraceStore(tmp_path / "traces.sqlite3")
    span = _span("root")

    await store.write_spans([span])
    await store.write_spans([span])

    loaded = await store.get_spans("trace-sqlite")
    assert len(loaded) == 1


@pytest.mark.asyncio
async def test_concurrent_writes_are_safe(tmp_path) -> None:
    store = SQLiteTraceStore(tmp_path / "traces.sqlite3")

    await asyncio_gather_writes(store)

    loaded = await store.get_spans("trace-sqlite")
    assert len(loaded) == 10


async def asyncio_gather_writes(store: SQLiteTraceStore) -> None:
    import asyncio

    await asyncio.gather(
        *[
            store.write_spans([_span(f"span-{index}", offset_seconds=index)])
            for index in range(10)
        ]
    )


@pytest.mark.asyncio
async def test_trex_reconstructs_trajectory_from_sqlite(tmp_path) -> None:
    store = SQLiteTraceStore(tmp_path / "traces.sqlite3")
    await store.write_spans(
        [
            _span("root"),
            _span("tool", parent_span_id="root", offset_seconds=1, tool_name="query_metrics"),
        ]
    )
    configure_span_loader(store)

    trajectory = await reconstruct_trajectory("trace-sqlite")

    assert isinstance(trajectory, Trajectory)
    assert trajectory.trace_id == "trace-sqlite"
    assert trajectory.steps[1].tool_calls[0].tool_name == "query_metrics"
