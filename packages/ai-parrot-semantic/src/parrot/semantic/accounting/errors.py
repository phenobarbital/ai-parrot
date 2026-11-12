"""Accounting-layer error taxonomy (FEAT-713 M2). Standard library and pydantic only."""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel

ProblemCode = Literal[
    "unassigned_account",
    "empty_set",
    "overlap",
    "dangling_ref",
    "cycle",
    "nature_missing",
    "nature_ambiguous",
    "float_amount",
    "numeric_type",
    "column_missing",
    "interval_gap",
    "selector_no_match",
]


class AccountingError(Exception):
    """Base of every accounting-layer error."""


class Problem(BaseModel, frozen=True):
    """One load-time validation problem."""

    code: ProblemCode
    message: str
    interval: tuple[date | None, date | None] | None = None
    accounts: tuple[str, ...] = ()


class ModelValidationError(AccountingError):
    """Model failed load-time validation; ``problems`` carries EVERY problem, never only the first."""

    def __init__(self, problems: list[Problem], message: str | None = None) -> None:
        """Store every problem and build a summary message.

        Args:
            problems: Every validation problem found (never only the first).
            message: Optional explicit message; defaults to a count plus the distinct problem codes.
        """
        self.problems = list(problems)
        if message is None:
            codes = ", ".join(sorted({problem.code for problem in self.problems})) or "none"
            message = f"{len(self.problems)} model validation problem(s): {codes}"
        super().__init__(message)


class GrammarError(AccountingError):
    """Expression syntax error at ``position`` (0-based character offset)."""

    def __init__(self, message: str, position: int) -> None:
        """Record the failing offset.

        Args:
            message: Human-readable syntax error.
            position: 0-based character offset of the error.
        """
        self.position = position
        super().__init__(f"{message} at position {position}")


class RequestValidationError(AccountingError):
    """Unknown metric/dimension/filter, cumulative/grain mismatch, bad assertion index."""


class PeriodSpansMembershipChange(RequestValidationError):
    """Requested period or cumulative window crosses a membership boundary."""

    def __init__(self, boundary: date, suggestion: str) -> None:
        """Record the boundary crossed and a remediation hint.

        Args:
            boundary: Date at which set membership changes.
            suggestion: How to split or adjust the request.
        """
        self.boundary = boundary
        self.suggestion = suggestion
        super().__init__(f"period crosses a set-membership change on {boundary.isoformat()}; {suggestion}")


class AccountingExecutionError(AccountingError):
    """Runtime failed or the result was truncated; ``audit_id`` is set when the attempt was audited."""

    def __init__(self, message: str, *, audit_id: str | None = None) -> None:
        """Record the failure and the audit entry id, if any.

        Args:
            message: Failure description.
            audit_id: Identifier of the audit entry for the attempt, when audited.
        """
        self.audit_id = audit_id
        super().__init__(message)


class AccountingAuditError(AccountingError):
    """Durable audit append failed under FINANCE_AUDIT_MODE=required."""
