"""Externalized diagnostic session state adapters."""

import json
from typing import Protocol

from pydantic import BaseModel

from src.config import Settings
from src.schemas import DiagnoseRequest, DiagnoseResponse


class DiagnosticSession(BaseModel):
    """Serializable session envelope stored independently from API compute."""

    session_id: str
    request: DiagnoseRequest
    response: DiagnoseResponse
    resume_count: int = 0


class DiagnosticStateStore(Protocol):
    """Persistence contract for resumable diagnostic sessions."""

    async def save(self, session: DiagnosticSession) -> None:
        """Create or replace a diagnostic session."""

    async def get(self, session_id: str) -> DiagnosticSession | None:
        """Retrieve a diagnostic session by identifier."""


class InMemoryStateStore:
    """Process-local state store for tests and local development."""

    def __init__(self) -> None:
        self._sessions: dict[str, DiagnosticSession] = {}

    async def save(self, session: DiagnosticSession) -> None:
        self._sessions[session.session_id] = session.model_copy(deep=True)

    async def get(self, session_id: str) -> DiagnosticSession | None:
        session = self._sessions.get(session_id)
        return session.model_copy(deep=True) if session else None


class RedisStateStore:
    """Redis-backed state adapter for horizontally scaled API pods."""

    def __init__(self, redis_url: str, *, key_prefix: str = "telefix:session:") -> None:
        try:
            from redis.asyncio import Redis
        except ImportError as exc:
            raise RuntimeError("Redis state requires the redis package.") from exc

        self._client = Redis.from_url(redis_url, decode_responses=True)
        self._key_prefix = key_prefix

    async def save(self, session: DiagnosticSession) -> None:
        await self._client.set(
            f"{self._key_prefix}{session.session_id}",
            session.model_dump_json(),
        )

    async def get(self, session_id: str) -> DiagnosticSession | None:
        payload = await self._client.get(f"{self._key_prefix}{session_id}")
        if payload is None:
            return None
        return DiagnosticSession.model_validate(json.loads(payload))


def build_state_store(settings: Settings) -> DiagnosticStateStore:
    """Build the configured state backend."""

    if settings.state_backend == "redis":
        return RedisStateStore(settings.redis_url)
    return InMemoryStateStore()
