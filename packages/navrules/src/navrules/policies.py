"""Evaluation policies and typed results."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Generic, Optional, TypeVar, TYPE_CHECKING

if TYPE_CHECKING:
    from .abstract import AbstractRule

T = TypeVar("T")


class Policy(str, Enum):
    """How a RuleSet combines its rules.

    * ALL_MATCH — every rule must match (historic rewards semantics).
    * ANY_MATCH — at least one rule must match.
    * FIRST_MATCH — rules are scanned in priority order (descending, stable);
      the first matching rule short-circuits and provides the result value.
    """

    ALL_MATCH = "all_match"
    ANY_MATCH = "any_match"
    FIRST_MATCH = "first_match"


@dataclass(frozen=True, slots=True)
class RuleResult(Generic[T]):
    """Outcome of evaluating one rule.

    Attributes:
        matched: Whether the rule matched.
        rule: The rule instance (None for synthetic results).
        value: The rule's declared result payload when matched.
        error: Exception message when the rule raised (treated as no-match).
        meta: Free-form diagnostic data.
    """

    matched: bool
    rule: Optional["AbstractRule"] = None
    value: Optional[T] = None
    error: Optional[str] = None
    meta: dict = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class RuleSetResult(Generic[T]):
    """Outcome of evaluating a whole RuleSet.

    Attributes:
        matched: Aggregate verdict under the policy.
        value: FIRST_MATCH: the winning rule's result (or the set default);
            ALL/ANY: the default payload when matched, else None.
        results: Per-rule outcomes. Under FIRST_MATCH with short-circuit only
            the rules actually inspected are present.
        policy: The policy that produced this result.
    """

    matched: bool
    value: Optional[T]
    results: tuple[RuleResult, ...]
    policy: Policy

    @property
    def rule(self) -> Optional["AbstractRule"]:
        """The winning rule under FIRST_MATCH (None otherwise/no match)."""
        for result in self.results:
            if result.matched:
                return result.rule
        return None
