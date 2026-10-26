"""Typed protocol errors shared by Squawk (FEAT-746) and Roost (FEAT-747)."""

from __future__ import annotations

from enum import Enum
from typing import Any


class SquawkErrorCode(str, Enum):
    """Wire-level error codes used as the primary failure signal."""

    STALE_CONTRACT = "STALE_CONTRACT"
    POLICY_DENIED = "POLICY_DENIED"
    BUDGET_EXCEEDED = "BUDGET_EXCEEDED"
    UNAUTHORIZED = "UNAUTHORIZED"
    UNKNOWN_CAPABILITY = "UNKNOWN_CAPABILITY"
    PARTIAL = "PARTIAL"
    CANCELLED = "CANCELLED"
    UPSTREAM_FAILED = "UPSTREAM_FAILED"


class SquawkError(Exception):
    """Typed protocol error.

    Args:
        code: Wire-level error code.
        detail: Short, sanitized audit string without policy internals or payloads.
        payload: Structured extra data. ``STALE_CONTRACT`` carries the current category here.
    """

    def __init__(self, code: SquawkErrorCode, detail: str = "", payload: dict[str, Any] | None = None) -> None:
        super().__init__(f"{code.value}: {detail}" if detail else code.value)
        self.code = code
        self.detail = detail
        self.payload = payload or {}
