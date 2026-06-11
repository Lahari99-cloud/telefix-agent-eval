"""CI regression gate for golden-dataset agent quality."""

import pytest

from src.agent import BroadbandTroubleshootingAgent
from src.config import Settings
from src.evaluation import EvaluationRunner, load_golden_cases
from src.rag import LocalSyntheticRetriever
from src.review_queue import ReviewQueue


def test_golden_dataset_has_at_least_ten_synthetic_cases() -> None:
    cases = load_golden_cases()

    assert len(cases) >= 10
    assert all(case.mac_address.startswith("02:") for case in cases)
    assert all("comcast" not in case.user_prompt.lower() for case in cases)


@pytest.mark.asyncio
async def test_eval_regression_gate() -> None:
    agent = BroadbandTroubleshootingAgent(
        settings=Settings(rag_backend="local"),
        retriever=LocalSyntheticRetriever(),
    )
    result = await EvaluationRunner(agent, ReviewQueue()).run()
    metrics = result.aggregate

    assert metrics.tool_selection_accuracy >= 0.80
    assert metrics.workflow_completion_rate >= 0.85
    assert metrics.groundedness_score >= 0.75
    assert metrics.hallucination_risk <= 0.35
