"""Golden-dataset evaluation runner for the troubleshooting agent."""

import json
from collections.abc import Callable
from pathlib import Path
from time import perf_counter

from pydantic import BaseModel, Field, TypeAdapter

from src.agent import BroadbandTroubleshootingAgent
from src.review_queue import ReviewQueue
from src.schemas import DiagnoseRequest, WorkflowStatus

DEFAULT_GOLDEN_CASES_PATH = Path(__file__).resolve().parents[1] / "evals" / "golden_cases.json"


class GoldenCase(BaseModel):
    """Expected behavior for one fully synthetic broadband scenario."""

    id: str
    user_prompt: str
    mac_address: str
    expected_tools: list[str]
    expected_resolution_type: WorkflowStatus
    expected_grounding_context: list[str]
    severity: str


class CaseEvaluationResult(BaseModel):
    case_id: str
    strategy: str
    severity: str
    actual_resolution_type: WorkflowStatus
    expected_resolution_type: WorkflowStatus
    selected_tools: list[str]
    expected_tools: list[str]
    tool_selection_accuracy: float = Field(ge=0.0, le=1.0)
    workflow_completed: bool
    groundedness_score: float = Field(ge=0.0, le=1.0)
    hallucination_risk: float = Field(ge=0.0, le=1.0)
    latency_ms: float = Field(ge=0.0)
    cited_context: list[str]
    expected_grounding_context: list[str]
    routed_to_review: bool


class AggregateEvaluationMetrics(BaseModel):
    total_cases: int
    tool_selection_accuracy: float = Field(ge=0.0, le=1.0)
    workflow_completion_rate: float = Field(ge=0.0, le=1.0)
    groundedness_score: float = Field(ge=0.0, le=1.0)
    hallucination_risk: float = Field(ge=0.0, le=1.0)
    average_latency_ms: float = Field(ge=0.0)
    review_queue_count: int


class EvaluationRunResult(BaseModel):
    strategy: str
    dataset: str
    aggregate: AggregateEvaluationMetrics
    cases: list[CaseEvaluationResult]


PromptTransform = Callable[[str], str]


def load_golden_cases(path: Path = DEFAULT_GOLDEN_CASES_PATH) -> list[GoldenCase]:
    """Load and validate the checked-in golden evaluation dataset."""

    raw_cases = json.loads(path.read_text(encoding="utf-8"))
    return TypeAdapter(list[GoldenCase]).validate_python(raw_cases)


def _has_explicit_reset_consent(prompt: str) -> bool:
    normalized = prompt.lower()
    negative_phrases = ("does not consent", "declines", "not provided", "no consent")
    if any(phrase in normalized for phrase in negative_phrases):
        return False
    return "consents" in normalized or "permission granted" in normalized


def _ordered_tool_accuracy(actual: list[str], expected: list[str]) -> float:
    matched = sum(
        actual[index] == expected[index]
        for index in range(min(len(actual), len(expected)))
    )
    return matched / max(len(actual), len(expected), 1)


class EvaluationRunner:
    """Execute golden cases and aggregate deterministic quality metrics."""

    def __init__(
        self,
        agent: BroadbandTroubleshootingAgent,
        review_queue: ReviewQueue,
        *,
        strategy: str = "baseline",
        prompt_transform: PromptTransform | None = None,
        dataset_path: Path = DEFAULT_GOLDEN_CASES_PATH,
    ) -> None:
        self._agent = agent
        self._review_queue = review_queue
        self._strategy = strategy
        self._prompt_transform = prompt_transform or (lambda prompt: prompt)
        self._dataset_path = dataset_path

    async def run(self) -> EvaluationRunResult:
        cases = load_golden_cases(self._dataset_path)
        results = [await self._run_case(case) for case in cases]
        return EvaluationRunResult(
            strategy=self._strategy,
            dataset=self._dataset_path.name,
            aggregate=self._aggregate(results),
            cases=results,
        )

    async def _run_case(self, case: GoldenCase) -> CaseEvaluationResult:
        prompt = self._prompt_transform(case.user_prompt)
        request = DiagnoseRequest(
            account_id=case.mac_address,
            symptoms=prompt,
            consent_to_reset=_has_explicit_reset_consent(case.user_prompt),
        )
        started = perf_counter()
        response = await self._agent.diagnose(request)
        latency_ms = (perf_counter() - started) * 1000

        cited_context = [citation.document_id for citation in response.citations]
        expected_context = set(case.expected_grounding_context)
        context_coverage = len(expected_context.intersection(cited_context)) / max(
            len(expected_context), 1
        )
        groundedness = round(
            (context_coverage + response.evaluation.groundedness) / 2,
            3,
        )
        hallucination_risk = round(
            max(response.evaluation.hallucination_risk, 1.0 - groundedness),
            3,
        )
        workflow_completed = (
            response.evaluation.workflow_completion == 1.0
            and response.workflow_status == case.expected_resolution_type
        )
        tool_accuracy = round(
            _ordered_tool_accuracy(
                response.evaluation.selected_tools,
                case.expected_tools,
            ),
            3,
        )
        routed = self._review_queue.route_if_needed(
            case_id=case.id,
            strategy=self._strategy,
            severity=case.severity,
            groundedness_score=groundedness,
            hallucination_risk=hallucination_risk,
        )
        return CaseEvaluationResult(
            case_id=case.id,
            strategy=self._strategy,
            severity=case.severity,
            actual_resolution_type=response.workflow_status,
            expected_resolution_type=case.expected_resolution_type,
            selected_tools=response.evaluation.selected_tools,
            expected_tools=case.expected_tools,
            tool_selection_accuracy=tool_accuracy,
            workflow_completed=workflow_completed,
            groundedness_score=groundedness,
            hallucination_risk=hallucination_risk,
            latency_ms=round(latency_ms, 3),
            cited_context=cited_context,
            expected_grounding_context=case.expected_grounding_context,
            routed_to_review=routed,
        )

    @staticmethod
    def _aggregate(results: list[CaseEvaluationResult]) -> AggregateEvaluationMetrics:
        count = len(results)
        return AggregateEvaluationMetrics(
            total_cases=count,
            tool_selection_accuracy=round(
                sum(result.tool_selection_accuracy for result in results) / count,
                3,
            ),
            workflow_completion_rate=round(
                sum(result.workflow_completed for result in results) / count,
                3,
            ),
            groundedness_score=round(
                sum(result.groundedness_score for result in results) / count,
                3,
            ),
            hallucination_risk=round(
                sum(result.hallucination_risk for result in results) / count,
                3,
            ),
            average_latency_ms=round(
                sum(result.latency_ms for result in results) / count,
                3,
            ),
            review_queue_count=sum(result.routed_to_review for result in results),
        )
