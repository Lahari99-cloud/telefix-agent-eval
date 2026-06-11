"""Workflow and API contract regression tests."""

from fastapi.testclient import TestClient

from src.main import app


def test_degraded_service_with_consent_runs_reset_and_verification() -> None:
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/diagnose",
            json={
                "account_id": "demo-1001",
                "symptoms": "Internet is slow and drops every few minutes.",
                "consent_to_reset": True,
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["workflow_status"] == "resolved"
    assert body["reset_performed"] is True
    assert body["telemetry_before"]["status"] == "degraded"
    assert body["telemetry_after"]["status"] == "online"
    assert body["evaluation"]["tool_selection"] == 1.0
    assert body["evaluation"]["workflow_completion"] == 1.0
    assert body["evaluation"]["selected_tools"] == [
        "get_modem_telemetry",
        "perform_rf_reset",
        "get_modem_telemetry",
    ]


def test_offline_service_escalates_without_reset() -> None:
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/diagnose",
            json={
                "account_id": "demo-2002",
                "symptoms": "The modem is offline and there is no internet.",
                "consent_to_reset": True,
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["workflow_status"] == "escalate"
    assert body["reset_performed"] is False
    assert body["telemetry_after"] is None
    assert body["evaluation"]["selected_tools"] == ["get_modem_telemetry"]


def test_request_validation_rejects_empty_symptoms() -> None:
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/diagnose",
            json={"account_id": "demo-3003", "symptoms": "", "consent_to_reset": False},
        )

    assert response.status_code == 422


def test_evaluation_and_experiment_endpoints() -> None:
    with TestClient(app) as client:
        evaluation = client.post("/api/v1/evaluations/run")
        experiment = client.post("/api/v1/experiments/ab-test")
        review_queue = client.get("/api/v1/review-queue")

    assert evaluation.status_code == 200
    assert evaluation.json()["aggregate"]["total_cases"] >= 10
    assert experiment.status_code == 200
    assert experiment.json()["experiment"] == "baseline_vs_strict_grounded"
    assert review_queue.status_code == 200
    assert isinstance(review_queue.json(), list)
