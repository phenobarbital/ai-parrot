"""Librarian answer layer (FEAT-449) — span-verified, fail-closed answers.

The one-line invariant (R2): the system cannot assert anything about the
corpus without a verifiable span reference; without a citation, the answer
is "no encontré".
"""

from .models import (
    DEFAULT_DISCLAIMER,
    ConflictNote,
    DraftAnswer,
    DraftConflictNote,
    DraftReadingNote,
    DraftSpan,
    LegalAnswer,
    PayloadEntry,
    ReadingNote,
    SpanRef,
    SuppressionRecord,
    span_key,
)
from .suppression import SuppressionLog
from .verifier import SpanVerifier

__all__ = [
    "DEFAULT_DISCLAIMER",
    "ConflictNote",
    "DraftAnswer",
    "DraftConflictNote",
    "DraftReadingNote",
    "DraftSpan",
    "LegalAnswer",
    "PayloadEntry",
    "ReadingNote",
    "SpanRef",
    "SpanVerifier",
    "SuppressionLog",
    "SuppressionRecord",
    "span_key",
]
