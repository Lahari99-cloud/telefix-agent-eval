"""Deterministic state-drift analysis over canonical trajectories."""

from __future__ import annotations

import json
import re
from collections import Counter
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from telefix.models.trajectory import Trajectory

TOKEN_PATTERN = re.compile(r"[a-zA-Z0-9_]+")


class StateDriftResult(BaseModel):
    model_config = ConfigDict(extra="allow")

    semantic_redundancy_score: float = Field(ge=0.0, le=1.0)
    objective_retention_score: float = Field(ge=0.0, le=1.0)
    context_growth_ratio: float = Field(ge=0.0)
    repeated_context_ratio: float = Field(ge=0.0, le=1.0)
    drift_detected: bool
    step_count: int = Field(ge=0)
    objective_terms: list[str] = Field(default_factory=list)


def analyze_state_drift(
    trajectory: Trajectory,
    *,
    max_semantic_redundancy_score: float = 0.85,
    min_objective_retention_score: float = 0.60,
    max_context_growth_ratio: float = 3.0,
) -> StateDriftResult:
    """Analyze semantic drift using deterministic token overlap metrics."""

    step_texts = [_step_text(step) for step in (getattr(trajectory, "steps", []) or [])]
    step_tokens = [_tokenize(text) for text in step_texts]
    objective_terms = sorted(_objective_tokens(trajectory))

    redundancy = _semantic_redundancy_score(step_tokens)
    retention = _objective_retention_score(step_tokens, objective_terms)
    growth = _context_growth_ratio(step_tokens)
    repeated = _repeated_context_ratio(step_tokens)

    drift_detected = (
        redundancy > max_semantic_redundancy_score
        or retention < min_objective_retention_score
        or growth > max_context_growth_ratio
    )

    return StateDriftResult(
        semantic_redundancy_score=round(redundancy, 6),
        objective_retention_score=round(retention, 6),
        context_growth_ratio=round(growth, 6),
        repeated_context_ratio=round(repeated, 6),
        drift_detected=drift_detected,
        step_count=len(step_tokens),
        objective_terms=objective_terms,
    )


def _step_text(step: Any) -> str:
    return " ".join(
        [
            _stable_text(getattr(step, "input_context", {})),
            _stable_text(getattr(step, "output_context", {})),
        ]
    )


def _stable_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, sort_keys=True)
    except TypeError:
        return str(value)


def _tokenize(text: str) -> set[str]:
    return {
        token
        for token in (match.group(0).lower() for match in TOKEN_PATTERN.finditer(text))
        if len(token) > 1
    }


def _objective_tokens(trajectory: Trajectory) -> set[str]:
    candidates: list[Any] = [
        trajectory.evaluation_labels.ground_truth_root_cause,
        _extra_path(trajectory, ["context", "incident", "objective"]),
        _extra_path(trajectory, ["context", "objective"]),
        _extra_path(trajectory, ["incident", "objective"]),
    ]
    for candidate in candidates:
        tokens = _tokenize(_stable_text(candidate)) if candidate else set()
        if tokens:
            return tokens
    expected = " ".join(trajectory.evaluation_labels.expected_tool_sequence)
    return _tokenize(expected)


def _extra_path(model: object, path: list[str]) -> Any:
    current: Any = getattr(model, "__pydantic_extra__", None) or {}
    for part in path:
        if isinstance(current, dict) and part in current:
            current = current[part]
        else:
            return None
    return current


def _semantic_redundancy_score(step_tokens: list[set[str]]) -> float:
    if len(step_tokens) < 2:
        return 0.0
    similarities = [
        _jaccard(left, right)
        for left, right in zip(step_tokens, step_tokens[1:], strict=False)
    ]
    return max(similarities, default=0.0)


def _objective_retention_score(
    step_tokens: list[set[str]],
    objective_terms: list[str],
) -> float:
    if not objective_terms:
        return 1.0
    if not step_tokens:
        return 0.0
    final_tokens = step_tokens[-1]
    retained = set(objective_terms).intersection(final_tokens)
    return len(retained) / len(objective_terms)


def _context_growth_ratio(step_tokens: list[set[str]]) -> float:
    if not step_tokens:
        return 0.0
    first_size = max(len(step_tokens[0]), 1)
    largest_size = max((len(tokens) for tokens in step_tokens), default=0)
    return largest_size / first_size


def _repeated_context_ratio(step_tokens: list[set[str]]) -> float:
    if len(step_tokens) < 2:
        return 0.0
    signatures = [tuple(sorted(tokens)) for tokens in step_tokens]
    counts = Counter(signatures)
    repeated_steps = sum(count for count in counts.values() if count > 1)
    return repeated_steps / len(step_tokens)


def _jaccard(left: set[str], right: set[str]) -> float:
    if not left and not right:
        return 1.0
    union = left.union(right)
    if not union:
        return 0.0
    return len(left.intersection(right)) / len(union)
