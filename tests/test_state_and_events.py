"""Session persistence and asynchronous evaluation event tests."""

import pytest
from fastapi.testclient import TestClient

from src.main import app
from src.schemas import (
    DiagnoseRequest,
    DiagnoseResponse,
    EvaluationMetrics,
    ServiceStatus,
    TelemetrySnapshot,
    WorkflowStatus,
)
from src.state_store import DiagnosticSession, InMemoryStateStore


def _response(session_id: str) -> DiagnoseResponse:
    return DiagnoseResponse(
        session_id=session_id,
        account_id="synthetic-account",
        workflow_status=WorkflowStatus.NO_ACTION,
        summary="Synthetic telemetry is healthy.",
        recommended_action="Continue isolation.",
        reset_performed=False,
        telemetry_before=TelemetrySnapshot(
            modem_id="MODEM-SYNTHETIC",
            status=ServiceStatus.ONLINE,
            downstream_power_dbmv=0.0,
            upstream_power_dbmv=42.0,
            snr_db=39.0,
            corrected_codewords=0,
            uncorrectable_codewords=0,
            last_seen_seconds_ago=1,
        ),
        citations=[],
        evaluation=EvaluationMetrics(
            tool_selection=1.0,
            groundedness=1.0,
            hallucination_risk=0.0,
            workflow_completion=1.0,
            selected_tools=["get_modem_telemetry"],
            expected_tools=["get_modem_telemetry"],
        ),
        trace=["workflow_started", "evaluation_completed"],
    )


@pytest.mark.asyncio
async def test_in_memory_state_store_round_trip() -> None:
    store = InMemoryStateStore()
    session = DiagnosticSession(
        session_id="session-round-trip",
        request=DiagnoseRequest(
            account_id="synthetic-account",
            symptoms="Routine healthy modem check",
            session_id="session-round-trip",
        ),
        response=_response("session-round-trip"),
    )

    await store.save(session)
    loaded = await store.get(session.session_id)

    assert loaded == session
    assert loaded is not session


def test_diagnose_saves_and_resumes_session() -> None:
    with TestClient(app) as client:
        first = client.post(
            "/api/v1/diagnose",
            json={
                "account_id": "session-demo",
                "symptoms": "Internet is slow and intermittent.",
                "consent_to_reset": True,
            },
        )
        session_id = first.json()["session_id"]
        lookup = client.get(f"/api/v1/sessions/{session_id}")
        resumed = client.post(
            "/api/v1/diagnose",
            json={
                "account_id": "session-demo",
                "symptoms": "Resume the existing synthetic session.",
                "session_id": session_id,
            },
        )
        second_lookup = client.get(f"/api/v1/sessions/{session_id}")

    assert first.status_code == 200
    assert lookup.status_code == 200
    assert resumed.json() == first.json()
    assert second_lookup.json()["resume_count"] == 1


def test_diagnose_emits_event_and_worker_consumes_it() -> None:
    with TestClient(app) as client:
        diagnosis = client.post(
            "/api/v1/diagnose",
            json={
                "account_id": "event-demo",
                "symptoms": "The modem is offline with no internet.",
                "consent_to_reset": False,
            },
        )
        events = client.get("/api/v1/events")
        processed = client.post("/api/v1/evaluations/process-events")
        processed_again = client.post("/api/v1/evaluations/process-events")

    assert diagnosis.status_code == 200
    assert events.status_code == 200
    assert any(
        event["session_id"] == diagnosis.json()["session_id"] for event in events.json()
    )
    assert processed.json()["processed_count"] >= 1
    assert processed_again.json()["processed_count"] == 0
