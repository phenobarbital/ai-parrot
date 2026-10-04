"""Domain-neutral evidence and provenance primitives (FEAT-601 M1).

Moved verbatim from ``parrot.knowledge.contracts.models`` so that other
knowledge planes can share them without importing contracts.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Generic, Literal, Optional, TypeVar

from pydantic import BaseModel, Field, field_validator, model_validator

__all__ = (
    "MAX_QUOTE_CHARS",
    "UNSUBSTANTIATED_CONFIDENCE_CAP",
    "VerificationState",
    "ProvenanceOrigin",
    "AnswerProvenance",
    "trim_quote",
    "Evidence",
    "Extracted",
    "FieldProvenance",
)

#: Hard cap for any evidential quote persisted or released (spec §2).
MAX_QUOTE_CHARS = 300


def trim_quote(value: Any) -> Any:
    """Trim an over-long quote to :data:`MAX_QUOTE_CHARS` at a word boundary.

    Models regularly return excerpts a little longer than the requested
    bound. Rejecting the whole structured draft for that discards every
    other clause in the section, so the excerpt is shortened instead: a
    verbatim prefix is still verbatim, and evidence validation checks it
    against the indexed text afterwards exactly as before.
    """
    if not isinstance(value, str) or len(value) <= MAX_QUOTE_CHARS:
        return value
    cut = value[:MAX_QUOTE_CHARS]
    space = cut.rfind(" ")
    if space > MAX_QUOTE_CHARS // 2:
        cut = cut[:space]
    return cut.rstrip()


#: An absent or invalid quote caps extraction confidence at this value and
#: prioritises verification; it can never substantiate a released citation.
UNSUBSTANTIATED_CONFIDENCE_CAP = 0.5

VerificationState = Literal["extracted", "verified", "stale"]
ProvenanceOrigin = Literal["llm", "rule", "manual"]
AnswerProvenance = Literal["verified", "mixed", "extracted"]

T = TypeVar("T")


class Evidence(BaseModel):
    """A verbatim excerpt anchoring one extracted fact to a tree node.

    Args:
        node_id: PageIndex node id the quote was read from.
        quote: Verbatim excerpt, at most :data:`MAX_QUOTE_CHARS` chars.
            An empty quote is representable (the extractor found the fact
            without an excerpt) but never *substantiating*.
        page: Physical page number (PDF trees), 1-based.
    """

    node_id: str = Field(..., min_length=1)
    quote: str = Field(default="", max_length=MAX_QUOTE_CHARS)

    @field_validator("quote", mode="before")
    @classmethod
    def _trim_quote(cls, value: Any) -> Any:
        return trim_quote(value)

    page: Optional[int] = Field(default=None, ge=1)

    @property
    def substantiates(self) -> bool:
        """True when this evidence carries a nonempty quote."""
        return bool(self.quote.strip())


class Extracted(BaseModel, Generic[T]):
    """One typed value produced by extraction, with its evidence.

    Uses a typed generic rather than ``value: object`` so drafts keep their
    field types through structured-output round trips.

    Args:
        value: The extracted value, or ``None`` when not found.
        evidence: Supporting excerpt; absent/blank quotes cap ``confidence``
            at :data:`UNSUBSTANTIATED_CONFIDENCE_CAP`.
        confidence: Extractor confidence in ``[0, 1]``.
    """

    value: Optional[T] = None
    evidence: Optional[Evidence] = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def _cap_unsubstantiated_confidence(self) -> "Extracted[T]":
        if not (self.evidence and self.evidence.substantiates):
            if self.confidence > UNSUBSTANTIATED_CONFIDENCE_CAP:
                self.confidence = UNSUBSTANTIATED_CONFIDENCE_CAP
        return self

    @property
    def substantiated(self) -> bool:
        """True when a nonempty quote backs this value."""
        return bool(self.evidence and self.evidence.substantiates)


class FieldProvenance(BaseModel):
    """Where one card field came from and whether a human confirmed it.

    ``origin`` and ``verification`` are independent axes so field-state
    transitions are unambiguous: correcting a value makes the origin
    ``manual``; confirming an extracted value only moves ``verification``.

    Args:
        origin: ``llm`` extraction, ``rule`` derivation or ``manual`` entry.
        verification: ``extracted`` / ``verified`` / ``stale``.
        node_id: Node the quote was read from.
        page: Physical page (PDF sources).
        quote: Verbatim excerpt, at most :data:`MAX_QUOTE_CHARS` chars.
        confidence: Extractor confidence in ``[0, 1]``.
        verified_by: Authenticated actor who verified/corrected the field.
        verified_at: Verification timestamp.
        derived_from: Provenance paths a ``rule`` origin consumed.
        candidate: Refresh candidate value kept aside when new evidence
            contradicts a previously verified value (never overwrites it).
    """

    origin: ProvenanceOrigin = "llm"
    verification: VerificationState = "extracted"
    node_id: Optional[str] = None
    page: Optional[int] = Field(default=None, ge=1)
    quote: Optional[str] = Field(default=None, max_length=MAX_QUOTE_CHARS)
    confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    verified_by: Optional[str] = None
    verified_at: Optional[datetime] = None
    derived_from: list[str] = Field(default_factory=list)
    candidate: Optional[Any] = None

    @model_validator(mode="after")
    def _check_axes(self) -> "FieldProvenance":
        if self.verification == "verified" and not (self.verified_by and self.verified_at):
            raise ValueError("verified provenance requires verified_by and verified_at")
        if self.origin == "rule" and not self.derived_from:
            raise ValueError("rule-derived provenance must identify its derived_from paths")
        if not (self.quote or "").strip():
            if self.confidence is not None and self.confidence > UNSUBSTANTIATED_CONFIDENCE_CAP:
                self.confidence = UNSUBSTANTIATED_CONFIDENCE_CAP
        return self

    @property
    def substantiates(self) -> bool:
        """True when a nonempty quote backs this field."""
        return bool((self.quote or "").strip())
