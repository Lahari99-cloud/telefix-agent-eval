"""In-memory human review queue for low-confidence evaluation cases."""

from datetime import UTC, datetime

from pydantic import BaseModel, Field


class ReviewItem(BaseModel):
    """A synthetic evaluation result requiring human review."""

    case_id: str
    strategy: str
    severity: str
    groundedness_score: float = Field(ge=0.0, le=1.0)
    hallucination_risk: float = Field(ge=0.0, le=1.0)
    reasons: list[str]
    created_at: datetime


class ReviewQueue:
    """Process-local queue suitable for a deterministic interview demo."""

    def __init__(self) -> None:
        self._items: dict[tuple[str, str], ReviewItem] = {}

    def route_if_needed(
        self,
        *,
        case_id: str,
        strategy: str,
        severity: str,
        groundedness_score: float,
        hallucination_risk: float,
    ) -> bool:
        reasons: list[str] = []
        if hallucination_risk > 0.35:
            reasons.append("hallucination_risk_above_0.35")
        if groundedness_score < 0.75:
            reasons.append("groundedness_score_below_0.75")
        if not reasons:
            return False

        self._items[(strategy, case_id)] = ReviewItem(
            case_id=case_id,
            strategy=strategy,
            severity=severity,
            groundedness_score=groundedness_score,
            hallucination_risk=hallucination_risk,
            reasons=reasons,
            created_at=datetime.now(UTC),
        )
        return True

    def list_items(self) -> list[ReviewItem]:
        """Return a stable snapshot with newest items first."""

        return sorted(self._items.values(), key=lambda item: item.created_at, reverse=True)

