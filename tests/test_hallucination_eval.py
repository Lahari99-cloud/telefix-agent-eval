"""Evaluation checks for evidence use and unsupported claims."""

import pytest

from src.agent import BroadbandTroubleshootingAgent
from src.config import Settings
from src.rag import LocalSyntheticRetriever
from src.schemas import DiagnoseRequest


@pytest.mark.asyncio
async def test_response_is_grounded_in_synthetic_sources() -> None:
    agent = BroadbandTroubleshootingAgent(
        settings=Settings(rag_backend="local"),
        retriever=LocalSyntheticRetriever(),
    )

    response = await agent.diagnose(
        DiagnoseRequest(
            account_id="demo-4004",
            symptoms="Intermittent slow broadband with buffering",
            consent_to_reset=True,
        )
    )

    assert response.citations
    assert all(citation.document_id.startswith("broadband-") for citation in response.citations)
    assert response.evaluation.groundedness == 1.0
    assert response.evaluation.hallucination_risk == 0.0
    assert response.evaluation.unsupported_claims == []
    assert "Comcast" not in response.summary


@pytest.mark.asyncio
async def test_no_proprietary_or_unverified_outage_claims() -> None:
    agent = BroadbandTroubleshootingAgent(
        settings=Settings(rag_backend="local"),
        retriever=LocalSyntheticRetriever(),
    )

    response = await agent.diagnose(
        DiagnoseRequest(
            account_id="demo-5005",
            symptoms="No internet and modem offline",
            consent_to_reset=False,
        )
    )
    text = f"{response.summary} {response.recommended_action}".lower()

    assert "area outage" not in text
    assert "comcast" not in text
    assert "customer history" not in text
    assert response.workflow_status.value == "escalate"
    assert response.evaluation.workflow_completion == 1.0

