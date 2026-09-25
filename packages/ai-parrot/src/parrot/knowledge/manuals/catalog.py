"""Authoritative, tenant-bound manual catalog protocol (FEAT-601 M4)."""

from __future__ import annotations

import logging
import re
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, Literal, Optional, Sequence

from pydantic import BaseModel, Field

from parrot.knowledge.common.provenance import VerificationState
from parrot.knowledge.manuals.models import EquipmentRef, ManualCard, ManualVersion, ProcedureAnswerKind

logger = logging.getLogger(__name__)

IDENTIFIER_RE = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")
VerificationReason = Literal["missing_evidence", "low_confidence_step", "unpaired_figure", "orphaned_tip", "stale"]
_QUEUE_ORDER: dict[str, int] = {
    "missing_evidence": 0,
    "low_confidence_step": 1,
    "unpaired_figure": 2,
    "orphaned_tip": 3,
    "stale": 4,
}
LOW_CONFIDENCE_STEP = 0.6
PublicationTarget = Literal["ontology"]
PublicationState = Literal["pending", "in_flight", "published", "failed"]


class CatalogError(RuntimeError):
    """Base error of the manual catalog."""


class CatalogConflictError(CatalogError):
    """``expected_revision`` did not match the stored revision."""

    def __init__(self, manual_id: str, expected: Optional[int], actual: Optional[int]) -> None:
        """Initialize the conflict with optimistic-revision details."""
        super().__init__(
            f"manual {manual_id!r} was modified concurrently (expected revision {expected}, found {actual})"
        )
        self.manual_id = manual_id
        self.expected = expected
        self.actual = actual


class DuplicateSourceError(CatalogError):
    """The source sha256 or URI already belongs to another manual."""

    def __init__(self, manual_id: str, *, source_sha256: str = "", source_uri: str = "") -> None:
        """Initialize the source-conflict error."""
        detail = source_sha256 or source_uri
        super().__init__(f"source {detail!r} already belongs to manual {manual_id!r}")
        self.manual_id = manual_id
        self.source_sha256 = source_sha256
        self.source_uri = source_uri


class UnknownManualError(CatalogError):
    """No card with this manual_id."""

    def __init__(self, manual_id: str) -> None:
        """Initialize the unknown-manual error."""
        super().__init__(f"unknown manual {manual_id!r}")
        self.manual_id = manual_id


def validate_identifier(value: str, *, what: str = "identifier") -> str:
    """Validate a configured SQL identifier before interpolation.

    Args:
        value: Configured schema or text-search configuration name.
        what: Label used in the validation error.

    Returns:
        The validated identifier.

    Raises:
        ValueError: If the value is not a plain lowercase SQL identifier.
    """
    if not IDENTIFIER_RE.match(value or ""):
        raise ValueError(f"invalid {what} {value!r}: expected a lowercase SQL name matching ^[a-z_][a-z0-9_]{0,62}$")
    return value


class PublicationRecord(BaseModel):
    """One durable ontology-publication outbox row."""

    tenant_id: str = Field(..., min_length=1)
    manual_id: str = Field(..., min_length=1)
    version_n: int = Field(default=1, ge=1)
    revision: int = Field(default=1, ge=1)
    target: PublicationTarget = "ontology"
    run_id: str = Field(..., min_length=1)
    payload: dict[str, Any] = Field(default_factory=dict)
    state: PublicationState = "pending"
    receipt: Optional[str] = None
    attempts: int = Field(default=0, ge=0)
    last_error: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    @property
    def key(self) -> tuple[str, str, int, int, str]:
        """Return the idempotency key of this row."""
        return (self.tenant_id, self.manual_id, self.version_n, self.revision, self.target)


class SearchHit(BaseModel):
    """One manual search result."""

    card: ManualCard
    rank: float = 0.0
    matched: Literal["manual", "procedure", "equipment", "caption"] = "manual"


class UpsertResult(BaseModel):
    """The outcome of one atomic manual-card write."""

    manual_id: str
    revision: int = Field(..., ge=1)
    created: bool = False
    version_n: int = Field(default=1, ge=1)
    queued: list[PublicationRecord] = Field(default_factory=list)


class VerificationQueueEntry(BaseModel):
    """One manual awaiting verification."""

    card: ManualCard
    reason: VerificationReason
    items: list[str] = Field(default_factory=list)

    @property
    def priority(self) -> int:
        """Return the numeric queue priority (lower runs first)."""
        return _QUEUE_ORDER[self.reason]


class AnswerRecord(BaseModel):
    """One audited answer, written before release (blocked answers too)."""

    answer_id: str = Field(..., min_length=1)
    asked_at: datetime
    user: str = Field(..., min_length=1)
    question: str = Field(..., min_length=1)
    answer_kind: ProcedureAnswerKind
    pattern: Optional[str] = None
    manual_id: Optional[str] = None
    manual_revision: Optional[str] = None
    citations: list[dict[str, Any]] = Field(default_factory=list)
    allowed: bool = True
    reason: Optional[str] = None
    blocked_reason: Optional[str] = None


def queue_entries_for(card: ManualCard) -> list[VerificationQueueEntry]:
    """Derive verification-queue entries for one card without I/O.

    Args:
        card: The card whose evidence, steps, and figures are inspected.

    Returns:
        Entries ordered by their defined verification priority.
    """
    entries: list[VerificationQueueEntry] = []
    missing = sorted(
        path
        for path, provenance in card.field_provenance.items()
        if provenance.origin == "llm" and not provenance.substantiates
    )
    if missing:
        entries.append(VerificationQueueEntry(card=card, reason="missing_evidence", items=missing))

    low_confidence = sorted(
        step.identity.step_id
        for procedure in card.procedures
        for step in procedure.steps
        if step.text.confidence < LOW_CONFIDENCE_STEP
    )
    if low_confidence:
        entries.append(VerificationQueueEntry(card=card, reason="low_confidence_step", items=low_confidence))

    labels = {figure.label for figure in card.figures if figure.label}
    unpaired = sorted(
        [
            step.identity.step_id
            for procedure in card.procedures
            for step in procedure.steps
            if any(label not in labels for label in step.figure_refs)
        ]
        + [f"{figure.media_id}#{callout.label}" for figure in card.figures for callout in figure.unresolved_callouts]
    )
    if unpaired:
        entries.append(VerificationQueueEntry(card=card, reason="unpaired_figure", items=unpaired))

    if card.verification == "stale":
        entries.append(VerificationQueueEntry(card=card, reason="stale"))
    return entries


def rank_equipment(
    query: str, equipment: Sequence[EquipmentRef], *, limit: int = 5
) -> list[tuple[EquipmentRef, float]]:
    """Resolve equipment by exact or fuzzy model and alias matching.

    Args:
        query: Equipment wording supplied by a caller.
        equipment: Candidate equipment references.
        limit: Maximum candidates to return.

    Returns:
        Candidates ordered by descending score and equipment id.

    Raises:
        RuntimeError: If fuzzy matching is needed but ``rapidfuzz`` is unavailable.
    """
    normalized = (query or "").strip().casefold()
    if not normalized or limit <= 0:
        return []
    candidates = [(reference, [reference.model, *reference.aliases]) for reference in equipment]
    if any(normalized == value.strip().casefold() for _, values in candidates for value in values if value.strip()):
        scored = [
            (
                reference,
                1.0 if any(normalized == value.strip().casefold() for value in values if value.strip()) else 0.0,
            )
            for reference, values in candidates
        ]
    else:
        try:
            from rapidfuzz import fuzz  # noqa: PLC0415 - optional graphindex dependency
        except ImportError as exc:  # pragma: no cover - depends on optional install
            raise RuntimeError(
                "Equipment resolution requires rapidfuzz. Install it with `pip install 'ai-parrot[graphindex]'`."
            ) from exc
        scored = [
            (
                reference,
                max(
                    (float(fuzz.token_sort_ratio(query, value)) / 100.0 for value in values if value.strip()),
                    default=0.0,
                ),
            )
            for reference, values in candidates
        ]
    return sorted(scored, key=lambda row: (-row[1], row[0].equipment_id))[:limit]


class ManualCatalogStore(ABC):
    """Async, tenant-bound authoritative store for manual cards."""

    def __init__(
        self,
        *,
        tenant_id: str,
        schema: str = "manuals",
        principal: Optional[str] = None,
        search_regconfig: str = "english",
    ) -> None:
        if not (tenant_id or "").strip():
            raise ValueError("a manual catalog must be bound to a tenant_id")
        self._tenant_id = tenant_id
        self._schema = validate_identifier(schema, what="catalog schema")
        self._search_regconfig = validate_identifier(search_regconfig, what="search regconfig")
        self._principal = principal

    @property
    def tenant_id(self) -> str:
        """Return the tenant permanently bound to this store."""
        return self._tenant_id

    @property
    def schema(self) -> str:
        """Return the validated SQL schema."""
        return self._schema

    @property
    def search_regconfig(self) -> str:
        """Return the validated PostgreSQL text-search configuration."""
        return self._search_regconfig

    @property
    def principal(self) -> Optional[str]:
        """Return the configured unattended-write principal."""
        return self._principal

    @abstractmethod
    async def upsert(
        self, card: ManualCard, *, expected_revision: Optional[int] = None, version: Optional[ManualVersion] = None
    ) -> UpsertResult:
        """Atomically write a card, history row, and publication record."""

    @abstractmethod
    async def get(self, manual_id: str) -> Optional[ManualCard]:
        """Return one manual card or ``None``."""

    @abstractmethod
    async def find_by_sha(self, sha256: str) -> Optional[ManualCard]:
        """Return the card currently owning a source SHA-256."""

    @abstractmethod
    async def find_by_source_uri(self, uri: str) -> Optional[ManualCard]:
        """Return the card currently owning a source URI."""

    @abstractmethod
    async def list_cards(
        self, *, verification: Optional[VerificationState] = None, active_only: bool = True
    ) -> list[ManualCard]:
        """List cards in stable manual-id order."""

    @abstractmethod
    async def versions(self, manual_id: str) -> list[ManualVersion]:
        """Return immutable manual version history, oldest first."""

    @abstractmethod
    async def search(self, query: str, top_k: int = 8) -> list[SearchHit]:
        """Search cards by manual, procedure, equipment, and figure text."""

    @abstractmethod
    async def verification_queue(self, *, limit: int = 50) -> list[VerificationQueueEntry]:
        """Return verification rows in deterministic priority order."""

    @abstractmethod
    async def record_answer(self, record: AnswerRecord) -> None:
        """Persist an audit record before releasing an answer."""

    @abstractmethod
    async def get_answer(self, answer_id: str) -> Optional[AnswerRecord]:
        """Return one audit record or ``None``."""

    @abstractmethod
    async def enqueue_publication(self, record: PublicationRecord) -> PublicationRecord:
        """Idempotently queue one publication record."""

    @abstractmethod
    async def pending_publications(self, *, limit: int = 50) -> list[PublicationRecord]:
        """Return pending and failed publication work."""

    @abstractmethod
    async def claim_publication(self, *, limit: int = 1) -> list[PublicationRecord]:
        """Claim pending work for ontology publication."""

    @abstractmethod
    async def complete_publication(self, record: PublicationRecord, *, receipt: str) -> PublicationRecord:
        """Mark a claimed row published with its receipt."""

    @abstractmethod
    async def fail_publication(self, record: PublicationRecord, *, error: str) -> PublicationRecord:
        """Return a claimed row to the retryable failed state."""

    @abstractmethod
    async def setup(self) -> None:
        """Create or migrate owned storage idempotently."""

    @abstractmethod
    async def close(self) -> None:
        """Release owned resources."""

    async def resolve_equipment(self, query: str, *, limit: int = 5) -> list[EquipmentRef]:
        """Resolve equipment deterministically across every active card."""
        cards = await self.list_cards(active_only=True)
        pool = {reference.equipment_id: reference for card in cards for reference in card.equipment}
        return [reference for reference, _score in rank_equipment(query, list(pool.values()), limit=limit)]
