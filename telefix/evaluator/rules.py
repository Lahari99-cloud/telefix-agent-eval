"""Context-aware policy rule models."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class RuleOutcome(StrEnum):
    PASS = "PASS"
    WARN = "WARN"
    FAIL = "FAIL"


class ContextCondition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    eq: Any = None
    neq: Any = None
    gt: Any = None
    gte: Any = None
    lt: Any = None
    lte: Any = None
    in_: list[Any] | None = Field(default=None, alias="in")
    not_in: list[Any] | None = None

    @model_validator(mode="after")
    def require_operator(self) -> ContextCondition:
        if not self.operators:
            raise ValueError("condition must define at least one operator")
        return self

    @property
    def operators(self) -> dict[str, Any]:
        values = {
            "eq": self.eq,
            "neq": self.neq,
            "gt": self.gt,
            "gte": self.gte,
            "lt": self.lt,
            "lte": self.lte,
            "in": self.in_,
            "not_in": self.not_in,
        }
        return {operator: expected for operator, expected in values.items() if expected is not None}


class PolicyRule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool: str
    allowed_if: dict[str, ContextCondition] = Field(default_factory=dict)
    denied_if: dict[str, ContextCondition] = Field(default_factory=dict)
    otherwise: RuleOutcome = RuleOutcome.FAIL


class PolicyViolation(BaseModel):
    model_config = ConfigDict(extra="allow", use_enum_values=True)

    tool_name: str
    rule_index: int
    reason: str
    missing_context: list[str] = Field(default_factory=list)
    failed_conditions: list[str] = Field(default_factory=list)
    outcome: RuleOutcome = RuleOutcome.FAIL
