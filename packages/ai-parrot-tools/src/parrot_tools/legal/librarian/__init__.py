"""Librarian answer layer (FEAT-449) — span-verified, fail-closed answers.

The one-line invariant (R2): the system cannot assert anything about the
corpus without a verifiable span reference; without a citation, the answer
is "no encontré".
"""

from .agent import LegalLibrarianAgent
from .as_of import AsOfExtraction, extract_as_of, regex_dates
from .flow import answer, build_legal_librarian_crew
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
    "AsOfExtraction",
    "ConflictNote",
    "DraftAnswer",
    "DraftConflictNote",
    "DraftReadingNote",
    "DraftSpan",
    "LegalAnswer",
    "LegalLibrarianAgent",
    "PayloadEntry",
    "ReadingNote",
    "SpanRef",
    "SpanVerifier",
    "SuppressionLog",
    "SuppressionRecord",
    "answer",
    "build_legal_librarian_crew",
    "extract_as_of",
    "regex_dates",
    "span_key",
]
