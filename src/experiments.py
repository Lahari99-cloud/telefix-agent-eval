"""A/B prompt strategy experiments over the golden evaluation dataset."""

from pydantic import BaseModel

from src.agent import BroadbandTroubleshootingAgent
from src.evaluation import EvaluationRunner, EvaluationRunResult
from src.review_queue import ReviewQueue


def baseline(prompt: str) -> str:
    """Use the original synthetic customer prompt."""

    return prompt


def strict_grounded(prompt: str) -> str:
    """Add an instruction to rely only on retrieved and observed evidence."""

    return (
        f"{prompt} Use only retrieved synthetic manual evidence and observed tool outputs; "
        "do not infer unobserved network conditions."
    )


PROMPT_STRATEGIES = {
    "baseline": baseline,
    "strict_grounded": strict_grounded,
}


class MetricComparison(BaseModel):
    baseline: float
    strict_grounded: float
    delta: float


class ABTestResult(BaseModel):
    experiment: str
    baseline: EvaluationRunResult
    strict_grounded: EvaluationRunResult
    comparison: dict[str, MetricComparison]


class ExperimentRunner:
    """Run both prompt strategies against identical golden cases."""

    def __init__(
        self,
        agent: BroadbandTroubleshootingAgent,
        review_queue: ReviewQueue,
    ) -> None:
        self._agent = agent
        self._review_queue = review_queue

    async def run_ab_test(self) -> ABTestResult:
        runs: dict[str, EvaluationRunResult] = {}
        for name, strategy in PROMPT_STRATEGIES.items():
            runs[name] = await EvaluationRunner(
                self._agent,
                self._review_queue,
                strategy=name,
                prompt_transform=strategy,
            ).run()

        baseline_run = runs["baseline"]
        strict_run = runs["strict_grounded"]
        baseline_metrics = baseline_run.aggregate
        strict_metrics = strict_run.aggregate
        metric_names = (
            "groundedness_score",
            "hallucination_risk",
            "tool_selection_accuracy",
            "workflow_completion_rate",
            "average_latency_ms",
        )
        comparison = {
            name: MetricComparison(
                baseline=getattr(baseline_metrics, name),
                strict_grounded=getattr(strict_metrics, name),
                delta=round(
                    getattr(strict_metrics, name) - getattr(baseline_metrics, name),
                    3,
                ),
            )
            for name in metric_names
        }
        return ABTestResult(
            experiment="baseline_vs_strict_grounded",
            baseline=baseline_run,
            strict_grounded=strict_run,
            comparison=comparison,
        )
