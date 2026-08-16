"""Data models for the deterministic groundedness scoring pipeline.

Defines the atom vocabulary extracted from agent answers and tool-output
evidence (FEAT-398, spec §2 Data Models). Stdlib + Pydantic only.
"""
from __future__ import annotations

from enum import Enum

from pydantic import BaseModel


class AtomKind(str, Enum):
    """The five verifiable hard-data atom kinds this feature extracts."""

    MONEY = "money"
    PERCENT = "percent"
    NUMBER = "number"
    DATE = "date"
    IDENTIFIER = "identifier"


class Atom(BaseModel):
    """A single verifiable hard-data atom extracted from text.

    Attributes:
        kind: The atom kind (money, percent, number, date, identifier).
        raw: The atom exactly as it appeared in the (NFKC-normalized)
            source text.
        normalized: The comparison key — a float for numeric-ish kinds
            (money/percent/number), an ISO-8601 date string for dates, or
            a case-folded string for identifiers.
        start: Start character offset of ``raw`` in the source text.
        end: End character offset (exclusive) of ``raw`` in the source
            text.
    """

    kind: AtomKind
    raw: str
    normalized: str | float
    start: int
    end: int
