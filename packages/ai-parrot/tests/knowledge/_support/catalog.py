"""Deterministic in-memory ManualCatalogStore (FEAT-601)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable, Optional

from parrot.knowledge.common.provenance import VerificationState
from parrot.knowledge.manuals.catalog import (
    AnswerRecord,
    CatalogConflictError,
    DuplicateSourceError,
    ManualCatalogStore,
    PublicationRecord,
    SearchHit,
    UpsertResult,
    VerificationQueueEntry,
    queue_entries_for,
)
from parrot.knowledge.manuals.models import ManualCard, ManualVersion, manual_snapshot_payload


class InMemoryManualCatalog(ManualCatalogStore):
    """Optimistic revisions, immutable history, durable outbox — no database."""

    def __init__(
        self,
        *,
        tenant_id: str = "t1",
        schema: str = "manuals",
        principal: Optional[str] = None,
        search_regconfig: str = "english",
        now: Callable[[], datetime] = lambda: datetime(2026, 9, 25, 12, tzinfo=timezone.utc),
    ) -> None:
        """Initialize deterministic in-memory state."""
        super().__init__(tenant_id=tenant_id, schema=schema, principal=principal, search_regconfig=search_regconfig)
        self._now = now
        self.cards: dict[str, ManualCard] = {}
        self.revisions: dict[str, int] = {}
        self.history: dict[str, list[ManualVersion]] = {}
        self.answers: dict[str, AnswerRecord] = {}
        self.outbox: dict[tuple, PublicationRecord] = {}
        self.fail_record_answer = False

    async def upsert(
        self, card: ManualCard, *, expected_revision: Optional[int] = None, version: Optional[ManualVersion] = None
    ) -> UpsertResult:
        """Write card, history, and its ontology outbox record atomically."""
        stored = self.cards.get(card.manual_id)
        actual = self.revisions.get(card.manual_id)
        if expected_revision is not None and expected_revision != actual:
            raise CatalogConflictError(card.manual_id, expected_revision, actual)
        for other in self.cards.values():
            if other.manual_id == card.manual_id:
                continue
            if card.source_sha256 and other.source_sha256 == card.source_sha256:
                raise DuplicateSourceError(other.manual_id, source_sha256=card.source_sha256)
            if card.source_uri and other.source_uri == card.source_uri:
                raise DuplicateSourceError(other.manual_id, source_uri=card.source_uri)

        created = stored is None
        revision = 1 if created else actual + 1  # type: ignore[operator]
        history = self.history.setdefault(card.manual_id, [])
        version_n = version.n if version is not None else len(history) + 1
        written = card.model_copy(update={"versions": []})
        recorded = version or ManualVersion(
            n=version_n,
            revision=card.revision,
            source_sha256=card.source_sha256,
            card_snapshot=manual_snapshot_payload(written),
            recorded_at=self._now(),
        )
        recorded = recorded.model_copy(update={"n": version_n, "revision": card.revision, "recorded_at": self._now()})
        history.append(recorded)
        written = written.model_copy(update={"versions": list(history)})
        self.cards[card.manual_id] = written
        self.revisions[card.manual_id] = revision
        queued = [
            await self.enqueue_publication(
                PublicationRecord(
                    tenant_id=self.tenant_id,
                    manual_id=card.manual_id,
                    version_n=recorded.n,
                    revision=revision,
                    run_id=f"{card.manual_id}:{recorded.n}:{revision}",
                    payload={"manual_id": card.manual_id},
                    created_at=self._now(),
                )
            )
        ]
        return UpsertResult(
            manual_id=card.manual_id,
            revision=revision,
            created=created,
            version_n=recorded.n,
            queued=queued,
        )

    async def get(self, manual_id: str) -> Optional[ManualCard]:
        """Return a stored manual card."""
        return self.cards.get(manual_id)

    async def find_by_sha(self, sha256: str) -> Optional[ManualCard]:
        """Return a card by its source hash."""
        return next((card for card in self.cards.values() if card.source_sha256 == sha256), None)

    async def find_by_source_uri(self, uri: str) -> Optional[ManualCard]:
        """Return a card by canonical source URI."""
        return next((card for card in self.cards.values() if card.source_uri == uri), None)

    async def list_cards(
        self, *, verification: Optional[VerificationState] = None, active_only: bool = True
    ) -> list[ManualCard]:
        """Return cards ordered by id; all manual cards are active in M4."""
        del active_only
        return sorted(
            (card for card in self.cards.values() if verification is None or card.verification == verification),
            key=lambda card: card.manual_id,
        )

    async def versions(self, manual_id: str) -> list[ManualVersion]:
        """Return one manual's immutable version history."""
        return list(self.history.get(manual_id, []))

    async def search(self, query: str, top_k: int = 8) -> list[SearchHit]:
        """Search the documented M4 fields using deterministic token counts."""
        terms = [term for term in query.casefold().split() if term]
        if not terms or top_k <= 0:
            return []
        hits: list[SearchHit] = []
        for card in self.cards.values():
            fields = [
                ("manual", card.manual_id),
                ("procedure", " ".join(procedure.title.value or "" for procedure in card.procedures)),
                (
                    "equipment",
                    " ".join(value for reference in card.equipment for value in [reference.model, *reference.aliases]),
                ),
                ("caption", " ".join(figure.caption or "" for figure in card.figures)),
            ]
            ranked = [
                (matched, float(sum(text.casefold().count(term) for term in terms)) / len(terms)) for matched, text in fields
            ]
            matched, rank = max(ranked, key=lambda row: (row[1], -["manual", "procedure", "equipment", "caption"].index(row[0])))
            if rank:
                hits.append(SearchHit(card=card, rank=rank, matched=matched))
        hits.sort(key=lambda hit: (-hit.rank, hit.card.manual_id))
        return hits[:top_k]

    async def verification_queue(self, *, limit: int = 50) -> list[VerificationQueueEntry]:
        """Return all derived entries in priority then manual-id order."""
        entries = [entry for card in self.cards.values() for entry in queue_entries_for(card)]
        entries.sort(key=lambda entry: (entry.priority, entry.card.manual_id))
        return entries[:limit]

    async def record_answer(self, record: AnswerRecord) -> None:
        """Persist an audit record, or expose the configured simulated failure."""
        if self.fail_record_answer:
            raise RuntimeError("answer audit unavailable")
        self.answers[record.answer_id] = record

    async def get_answer(self, answer_id: str) -> Optional[AnswerRecord]:
        """Return one audited answer."""
        return self.answers.get(answer_id)

    async def enqueue_publication(self, record: PublicationRecord) -> PublicationRecord:
        """Idempotently store one publication row."""
        existing = self.outbox.get(record.key)
        if existing is not None:
            return existing
        stored = record.model_copy(update={"created_at": record.created_at or self._now()})
        self.outbox[record.key] = stored
        return stored

    async def pending_publications(self, *, limit: int = 50) -> list[PublicationRecord]:
        """Return pending and failed rows ordered by their durable keys."""
        rows = [record for record in self.outbox.values() if record.state in ("pending", "failed")]
        return sorted(rows, key=lambda record: record.key)[:limit]

    async def claim_publication(self, *, limit: int = 1) -> list[PublicationRecord]:
        """Mark pending rows in flight and increment their attempts."""
        claimed: list[PublicationRecord] = []
        for record in await self.pending_publications(limit=limit):
            updated = record.model_copy(update={"state": "in_flight", "attempts": record.attempts + 1, "updated_at": self._now()})
            self.outbox[record.key] = updated
            claimed.append(updated)
        return claimed

    async def complete_publication(self, record: PublicationRecord, *, receipt: str) -> PublicationRecord:
        """Mark a publication record as published."""
        updated = record.model_copy(update={"state": "published", "receipt": receipt, "last_error": None, "updated_at": self._now()})
        self.outbox[record.key] = updated
        return updated

    async def fail_publication(self, record: PublicationRecord, *, error: str) -> PublicationRecord:
        """Mark a publication record retryably failed."""
        updated = record.model_copy(update={"state": "failed", "last_error": error, "updated_at": self._now()})
        self.outbox[record.key] = updated
        return updated

    async def setup(self) -> None:
        """Provide the no-op lifecycle operation required by the protocol."""

    async def close(self) -> None:
        """Provide the no-op lifecycle operation required by the protocol."""
