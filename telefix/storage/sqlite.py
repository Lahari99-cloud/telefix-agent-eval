"""Async SQLite-backed raw trace store."""

from __future__ import annotations

import asyncio
import json
import sqlite3
from pathlib import Path
from typing import Any

try:  # pragma: no cover - exercised when dependency is installed.
    import aiosqlite
except ModuleNotFoundError:  # pragma: no cover - local fallback for editable tests.
    aiosqlite = None

from telefix.storage.base import OTelSpan
from telefix.trex.adapters.otel import RawOtelSpan

SCHEMA_PATH = Path(__file__).with_name("schema.sql")


class SQLiteTraceStore:
    """Persist raw OpenTelemetry spans in SQLite."""

    def __init__(self, database_path: str | Path) -> None:
        self.database_path = Path(database_path)
        self._schema_sql = SCHEMA_PATH.read_text(encoding="utf-8")

    async def write_spans(self, spans: list[OTelSpan]) -> None:
        if not spans:
            return
        if aiosqlite is not None:
            await self._write_spans_aiosqlite(spans)
            return
        await asyncio.to_thread(self._write_spans_sync, spans)

    async def get_spans(self, trace_id: str) -> list[OTelSpan]:
        if aiosqlite is not None:
            return await self._get_spans_aiosqlite(trace_id)
        return await asyncio.to_thread(self._get_spans_sync, trace_id)

    async def load_spans(self, trace_id: str) -> list[RawOtelSpan]:
        """T-REx SpanLoader adapter."""

        spans = await self.get_spans(trace_id)
        return [span.to_raw_otel_span() for span in spans]

    async def _write_spans_aiosqlite(self, spans: list[OTelSpan]) -> None:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(self.database_path) as db:
            await db.executescript(self._schema_sql)
            await db.executemany(_UPSERT_SQL, [_span_row(span) for span in spans])
            await db.commit()

    async def _get_spans_aiosqlite(self, trace_id: str) -> list[OTelSpan]:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(self.database_path) as db:
            await db.executescript(self._schema_sql)
            async with db.execute(_SELECT_SQL, (trace_id,)) as cursor:
                rows = await cursor.fetchall()
        return [_row_to_span(row) for row in rows]

    def _write_spans_sync(self, spans: list[OTelSpan]) -> None:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.database_path) as db:
            db.executescript(self._schema_sql)
            db.executemany(_UPSERT_SQL, [_span_row(span) for span in spans])
            db.commit()

    def _get_spans_sync(self, trace_id: str) -> list[OTelSpan]:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.database_path) as db:
            db.executescript(self._schema_sql)
            rows = db.execute(_SELECT_SQL, (trace_id,)).fetchall()
        return [_row_to_span(row) for row in rows]


_UPSERT_SQL = """
INSERT OR REPLACE INTO otel_spans (
  trace_id,
  span_id,
  parent_span_id,
  span_name,
  start_time,
  end_time,
  attributes_json,
  events_json,
  status_code
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
"""

_SELECT_SQL = """
SELECT
  trace_id,
  span_id,
  parent_span_id,
  span_name,
  start_time,
  end_time,
  attributes_json,
  events_json,
  status_code
FROM otel_spans
WHERE trace_id = ?
ORDER BY start_time, span_id
"""


def _span_row(
    span: OTelSpan,
) -> tuple[str, str, str | None, str, str, str | None, str, str, str | None]:
    return (
        span.trace_id,
        span.span_id,
        span.parent_span_id,
        span.span_name,
        span.start_time.isoformat(),
        span.end_time.isoformat() if span.end_time else None,
        json.dumps(span.attributes, sort_keys=True),
        json.dumps(span.events, sort_keys=True),
        span.status_code,
    )


def _row_to_span(row: tuple[Any, ...]) -> OTelSpan:
    return OTelSpan(
        trace_id=row[0],
        span_id=row[1],
        parent_span_id=row[2],
        span_name=row[3],
        start_time=row[4],
        end_time=row[5],
        attributes=json.loads(row[6]),
        events=json.loads(row[7]),
        status_code=row[8],
    )
