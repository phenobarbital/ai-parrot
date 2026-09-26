"""Shared, domain-neutral knowledge primitives (FEAT-601 M1)."""

from .provenance import (
    MAX_QUOTE_CHARS,
    UNSUBSTANTIATED_CONFIDENCE_CAP,
    AnswerProvenance,
    Evidence,
    Extracted,
    FieldProvenance,
    ProvenanceOrigin,
    VerificationState,
    trim_quote,
)
from .validation import load_bodies, normalize_whitespace, quote_supported, validate_extracted

__all__ = (
    "MAX_QUOTE_CHARS",
    "UNSUBSTANTIATED_CONFIDENCE_CAP",
    "AnswerProvenance",
    "Evidence",
    "Extracted",
    "FieldProvenance",
    "ProvenanceOrigin",
    "VerificationState",
    "trim_quote",
    "load_bodies",
    "normalize_whitespace",
    "quote_supported",
    "validate_extracted",
)
