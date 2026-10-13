"""Result and context types for spoken-value post-processors (FEAT-653)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel

from ...core.types import FieldType
from ..narration.lexicon import Lexicon

Status = Literal["accepted", "confirm", "rejected"]

REFINABLE_TYPES: frozenset[FieldType] = frozenset(
    {
        FieldType.EMAIL,
        FieldType.PHONE,
        FieldType.NUMBER,
        FieldType.INTEGER,
        FieldType.DATE,
        FieldType.TIME,
        FieldType.DATETIME,
    }
)


class NormalizeResult(BaseModel):
    """Outcome of one post-processor.

    ``accepted``: valid canonical value. ``confirm``: valid canonical value whose reading is
    uncertain (reason: ambiguous_order | needs_timezone | ambiguous_meridiem). ``rejected``: no
    valid value (reason: invalid_email | too_short | no_parse | multiple_values | non_integral |
    out_of_range); ``value`` is a best-effort candidate or None.
    """

    value: Any = None
    status: Status
    reason: str | None = None

    @classmethod
    def accepted(cls, value: Any) -> "NormalizeResult":
        """Build an ``accepted`` result."""
        return cls(value=value, status="accepted")

    @classmethod
    def confirm(cls, value: Any, reason: str) -> "NormalizeResult":
        """Build a ``confirm`` result (valid but uncertain reading)."""
        return cls(value=value, status="confirm", reason=reason)

    @classmethod
    def rejected(cls, reason: str, value: Any = None) -> "NormalizeResult":
        """Build a ``rejected`` result with an optional best-effort candidate."""
        return cls(value=value, status="rejected", reason=reason)


@dataclass(frozen=True)
class NormalizeContext:
    """What a normalizer may read: the locale lexicon and a tz-aware 'now' in the client timezone."""

    lexicon: Lexicon
    now: datetime
    timezone_known: bool
