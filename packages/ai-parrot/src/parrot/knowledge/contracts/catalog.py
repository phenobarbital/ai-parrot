"""The tenant-bound asynchronous contract catalog protocol (FEAT-539 M2).

:class:`ContractCatalogStore` is the *only* authoritative interface to
contract state: cards, obligations, version history, party aliases, answer
audit, source cursors, relation judgements and the durable publication
outbox. ``PostgresContractCatalog`` (TASK-3027…3029) is its single
production implementation; there is no SQLite backend.

Tenancy and transaction preconditions
-------------------------------------

* **Tenant binding happens at construction.** ``tenant_id`` and the SQL
  ``schema`` are configuration, never arguments — no method accepts a
  model-supplied tenant name, so a document or an LLM cannot reach another
  tenant's rows. Identifiers are validated with
  :func:`validate_sql_identifier` before they can reach any statement.
* **One transaction per :meth:`ContractCatalogStore.upsert`.** The card row,
  the complete replacement of its obligation set, the appended version
  history and the enqueued :class:`PublicationRecord` rows commit or roll
  back together. Implementations must not split them.
* **Optimistic revisions.** Callers that read-modify-write a card (verify,
  refresh, party merge, owner override) pass ``expected_revision``; the
  store raises :class:`CatalogConflictError` when the stored revision has
  moved on. ``expected_revision=None`` means "insert or unconditional
  write" and is reserved for first ingestion.
* **Publication is never claimed atomically with the catalog write.**
  ``apply_update`` on the GraphIndex plane and the Arango projections own
  their own transactions, so the outbox is the recovery mechanism:
  :meth:`ContractCatalogStore.claim_publication` marks work in flight,
  :meth:`ContractCatalogStore.complete_publication` records the receipt and
  :meth:`ContractCatalogStore.fail_publication` records a retryable error.
* **History is immutable.** :meth:`ContractCatalogStore.remove` is a
  retraction: the card and its obligations become inactive and tombstones
  are queued, but versions, evidence references, judgements and the answer
  audit are retained.
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from datetime import date
from typing import Literal, Optional

from pydantic import BaseModel, Field

from .models import (
    AnswerRecord,
    ContractCard,
    ContractRelation,
    ContractStatus,
    ContractVersion,
    Obligation,
    ObligationKind,
    Party,
    PartyAlias,
    PublicationRecord,
    PublicationTarget,
    RelationJudgement,
    SourceItem,
    VerificationState,
)

__all__ = (
    "CatalogError",
    "CatalogConflictError",
    "DuplicateSourceError",
    "AliasConflictError",
    "UnknownContractError",
    "UnknownPartyError",
    "UnknownAnswerError",
    "PublicationUnavailableError",
    "ExpiringKey",
    "VerificationReason",
    "SearchHit",
    "UpsertResult",
    "VerificationQueueEntry",
    "ObligationWindow",
    "PartyMergeResult",
    "SQL_IDENTIFIER_RE",
    "validate_sql_identifier",
    "ContractCatalogStore",
)


# --------------------------------------------------------------------------
# Errors
# --------------------------------------------------------------------------


class CatalogError(RuntimeError):
    """Base class for every contract catalog failure."""


class CatalogConflictError(CatalogError):
    """A write lost an optimistic revision check.

    Raised when ``expected_revision`` does not match the stored revision —
    a concurrent verify/refresh already advanced the card.
    """

    def __init__(self, contract_id: str, expected: Optional[int], actual: Optional[int]) -> None:
        super().__init__(
            f"contract {contract_id!r} was modified concurrently " f"(expected revision {expected}, found {actual})"
        )
        self.contract_id = contract_id
        self.expected = expected
        self.actual = actual


class DuplicateSourceError(CatalogError):
    """The same source content or URI already belongs to another card."""

    def __init__(self, contract_id: str, *, source_sha256: str = "", source_uri: str = "") -> None:
        detail = source_sha256 or source_uri
        super().__init__(f"source {detail!r} already belongs to contract {contract_id!r}")
        self.contract_id = contract_id
        self.source_sha256 = source_sha256
        self.source_uri = source_uri


class AliasConflictError(CatalogError):
    """A normalized party alias already maps to a different canonical party."""

    def __init__(self, alias: str, existing_party_id: str, requested_party_id: str) -> None:
        super().__init__(
            f"alias {alias!r} already maps to party {existing_party_id!r}; "
            f"cannot remap to {requested_party_id!r} without review"
        )
        self.alias = alias
        self.existing_party_id = existing_party_id
        self.requested_party_id = requested_party_id


class UnknownContractError(CatalogError):
    """The requested contract does not exist in this tenant."""

    def __init__(self, contract_id: str) -> None:
        super().__init__(f"unknown contract {contract_id!r}")
        self.contract_id = contract_id


class UnknownPartyError(CatalogError):
    """The requested party identity does not exist in this tenant."""

    def __init__(self, party_id: str) -> None:
        super().__init__(f"unknown party {party_id!r}")
        self.party_id = party_id


class UnknownAnswerError(CatalogError):
    """The requested audited answer does not exist in this tenant."""

    def __init__(self, answer_id: str) -> None:
        super().__init__(f"unknown answer {answer_id!r}")
        self.answer_id = answer_id


class PublicationUnavailableError(CatalogError):
    """A publication target could not be reached; the work stays queued.

    The outbox row remains recoverable: callers surface a partial/unavailable
    target state instead of claiming a successful publication.
    """

    def __init__(self, target: str, reason: str) -> None:
        super().__init__(f"publication target {target!r} unavailable: {reason}")
        self.target = target
        self.reason = reason


# --------------------------------------------------------------------------
# Typed inputs and results
# --------------------------------------------------------------------------

#: Which date drives an expiry window. ``notice_deadline`` falls back to
#: ``expiration_date`` for cards without a notice period.
ExpiringKey = Literal["notice_deadline", "expiration_date"]

#: Why a card sits in the verification queue, in priority order.
VerificationReason = Literal["missing_evidence", "low_confidence", "stale"]

#: Queue priority — missing evidence first, then low-confidence unresolved
#: fields, then remaining stale cards; ties break on contract_id.
_QUEUE_ORDER: dict[str, int] = {"missing_evidence": 0, "low_confidence": 1, "stale": 2}


class SearchHit(BaseModel):
    """One English full-text search result with its rank."""

    card: ContractCard
    rank: float = 0.0


class UpsertResult(BaseModel):
    """The outcome of one atomic card write.

    Args:
        contract_id: The written card.
        revision: The recorded revision after the write.
        created: True when the card did not exist before.
        version_n: The contractual version this write recorded.
        queued: Publication rows enqueued in the same transaction.
    """

    contract_id: str
    revision: int = Field(..., ge=1)
    created: bool = False
    version_n: int = Field(default=1, ge=1)
    queued: list[PublicationRecord] = Field(default_factory=list)


class VerificationQueueEntry(BaseModel):
    """One card awaiting human verification, with its queue reason."""

    card: ContractCard
    reason: VerificationReason
    fields: list[str] = Field(default_factory=list)

    @property
    def priority(self) -> int:
        """Numeric queue priority (lower runs first)."""
        return _QUEUE_ORDER[self.reason]


class ObligationWindow(BaseModel):
    """A typed obligation due-date window for digests and reports.

    Args:
        until: Inclusive end of the window.
        since: Inclusive start; ``None`` includes everything already due.
        kinds: Restrict to these obligation kinds.
        standard_id: Restrict to obligations requiring one standard.
        include_recurring: Include recognised recurrence rules that fall in
            the window; unrecognised/unanchored recurrence is surfaced for
            review rather than interpreted.
        limit: Maximum rows returned.
    """

    until: date
    since: Optional[date] = None
    kinds: Optional[list[ObligationKind]] = None
    standard_id: Optional[str] = None
    include_recurring: bool = True
    limit: int = Field(default=200, ge=1, le=1000)


class PartyMergeResult(BaseModel):
    """What a party merge touched, for operator output and audit."""

    keep_party_id: str
    merged_party_id: str
    cards_updated: list[str] = Field(default_factory=list)
    aliases_remapped: list[str] = Field(default_factory=list)
    queued: list[PublicationRecord] = Field(default_factory=list)


# --------------------------------------------------------------------------
# Identifier validation
# --------------------------------------------------------------------------

#: Configured SQL identifiers (schemas) must be plain lowercase names.
SQL_IDENTIFIER_RE = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")


def validate_sql_identifier(value: str, *, what: str = "identifier") -> str:
    """Validate a configured SQL identifier before it reaches a statement.

    Only *configuration* may supply identifiers; user and model values are
    always bound parameters.

    Args:
        value: The configured identifier (a schema name).
        what: Label used in the error message.

    Returns:
        The validated identifier.

    Raises:
        ValueError: When the identifier is not a plain lowercase SQL name.
    """
    if not SQL_IDENTIFIER_RE.match(value or ""):
        raise ValueError(f"invalid {what} {value!r}: expected a lowercase SQL name " "matching ^[a-z_][a-z0-9_]{0,62}$")
    return value


# --------------------------------------------------------------------------
# The protocol
# --------------------------------------------------------------------------


class ContractCatalogStore(ABC):
    """Async, tenant-bound authoritative store for contract state.

    Args:
        tenant_id: The tenant this store is bound to for its whole lifetime.
        schema: The SQL schema holding this tenant's tables. Defaults to
            ``"contracts"``; a shared bare ``contracts`` schema is only
            acceptable in a single-tenant deployment.
        principal: Optional service principal recorded as the actor for
            unattended writes (scheduler jobs).

    Raises:
        ValueError: When ``tenant_id`` is empty or ``schema`` is not a valid
            SQL identifier.
    """

    def __init__(
        self,
        *,
        tenant_id: str,
        schema: str = "contracts",
        principal: Optional[str] = None,
    ) -> None:
        if not (tenant_id or "").strip():
            raise ValueError("a contract catalog must be bound to a tenant_id")
        self._tenant_id = tenant_id
        self._schema = validate_sql_identifier(schema, what="catalog schema")
        self._principal = principal

    @property
    def tenant_id(self) -> str:
        """The tenant this store is bound to (never an argument)."""
        return self._tenant_id

    @property
    def schema(self) -> str:
        """The validated SQL schema holding this tenant's tables."""
        return self._schema

    @property
    def principal(self) -> Optional[str]:
        """Configured service principal for unattended writes."""
        return self._principal

    # -- cards ------------------------------------------------------------

    @abstractmethod
    async def upsert(
        self,
        card: ContractCard,
        *,
        expected_revision: Optional[int] = None,
        version: Optional[ContractVersion] = None,
        targets: tuple[PublicationTarget, ...] = ("ontology", "temporal"),
    ) -> UpsertResult:
        """Atomically write a card, its obligations, history and outbox rows.

        Args:
            card: The card to write.
            expected_revision: Revision the caller read; ``None`` for a
                first insert or an unconditional write.
            version: Version/revision row to append; implementations derive
                one from the card when omitted.
            targets: Publication targets to enqueue in the same transaction.

        Returns:
            The :class:`UpsertResult` describing the committed write.

        Raises:
            CatalogConflictError: When ``expected_revision`` is stale.
            DuplicateSourceError: When the SHA-256 or source URI already
                belongs to a different contract.
        """

    @abstractmethod
    async def get(self, contract_id: str) -> Optional[ContractCard]:
        """Return one card by id, or ``None`` when it does not exist."""

    @abstractmethod
    async def find_by_sha(self, sha256: str) -> Optional[ContractCard]:
        """Return the card whose current source content hashes to ``sha256``."""

    @abstractmethod
    async def find_by_source_uri(self, uri: str) -> Optional[ContractCard]:
        """Return the card whose canonical source URI is ``uri``."""

    @abstractmethod
    async def list_cards(
        self,
        *,
        status: Optional[ContractStatus] = None,
        verification: Optional[VerificationState] = None,
        active_only: bool = True,
    ) -> list[ContractCard]:
        """List cards, optionally filtered by status and verification state.

        Args:
            status: Restrict to one contract status.
            verification: Restrict to one verification state.
            active_only: Exclude retracted cards (the default).

        Returns:
            Cards ordered deterministically by ``contract_id``.
        """

    @abstractmethod
    async def search(self, query: str, top_k: int = 8) -> list[SearchHit]:
        """Rank cards against an English full-text query.

        Args:
            query: Free-form user query, always a bound parameter.
            top_k: Maximum hits to return.

        Returns:
            Hits ordered by descending rank, then ``contract_id``.
        """

    @abstractmethod
    async def expiring(
        self,
        *,
        until: date,
        key: ExpiringKey = "notice_deadline",
        since: Optional[date] = None,
    ) -> list[ContractCard]:
        """Return active cards whose ``key`` date falls in an inclusive window.

        ``notice_deadline`` falls back to ``expiration_date`` when a card has
        no notice period; cards with a null date are omitted entirely.

        Args:
            until: Inclusive end of the window.
            key: Which date drives the window.
            since: Inclusive start; ``None`` includes everything up to
                ``until``.
        """

    @abstractmethod
    async def verification_queue(self, *, limit: int = 50) -> list[VerificationQueueEntry]:
        """Return cards awaiting verification in deterministic priority order.

        Missing evidence first, then low-confidence unresolved fields, then
        remaining stale cards, with ``contract_id`` as the tie-break.
        """

    @abstractmethod
    async def taken_slugs(self) -> set[str]:
        """Return every slug already used, for collision-free allocation.

        Slug uniqueness is additionally enforced in SQL: this set is a
        convenience for the allocator, never the only guard.
        """

    @abstractmethod
    async def remove(self, contract_id: str) -> None:
        """Retract a contract without destroying its history.

        The card and its obligations become inactive and tombstone
        publications are queued; versions, evidence references, judgements
        and the answer audit are retained.

        Raises:
            UnknownContractError: When the contract does not exist.
        """

    # -- obligations and versions -----------------------------------------

    @abstractmethod
    async def obligations_for(self, contract_id: str) -> list[Obligation]:
        """Return one contract's obligation set in stable id order."""

    @abstractmethod
    async def obligations_due(self, window: ObligationWindow) -> list[Obligation]:
        """Return obligations due inside a typed window, deterministically."""

    @abstractmethod
    async def versions(self, contract_id: str) -> list[ContractVersion]:
        """Return the retained version/revision history, oldest first."""

    # -- parties and aliases ----------------------------------------------

    @abstractmethod
    async def merge_parties(
        self,
        keep_party_id: str,
        merge_party_id: str,
        *,
        user: str,
    ) -> PartyMergeResult:
        """Merge two party identities inside one transaction.

        Updates current cards, signatories, alias mappings and queued
        projections together; historical snapshots are preserved.

        Args:
            keep_party_id: Canonical identity to keep.
            merge_party_id: Identity to fold into it.
            user: Authenticated actor recorded on the alias rows.

        Raises:
            ValueError: When both ids are the same (invalid self-merge).
            UnknownPartyError: When either identity is unknown.
        """

    @abstractmethod
    async def party_aliases(self, party_id: str) -> list[PartyAlias]:
        """Return every alias mapped onto one canonical party."""

    @abstractmethod
    async def all_party_aliases(self) -> dict[str, list[str]]:
        """Return catalog-wide aliases keyed by canonical ``party_id``.

        Aliases are global within a tenant, so the ontology datasource
        unions them into the shared ``Party`` vertex instead of letting one
        card's extraction define global identity.
        """

    @abstractmethod
    async def add_party_alias(self, alias: str, party_id: str, *, user: str) -> PartyAlias:
        """Map a normalized alias onto a canonical party.

        Raises:
            AliasConflictError: When the alias already maps elsewhere.
        """

    @abstractmethod
    async def resolve_party(self, alias: str) -> Optional[str]:
        """Resolve a normalized alias to its canonical ``party_id``."""

    @abstractmethod
    async def list_parties(self) -> list[Party]:
        """Return every distinct party across active cards, id-ordered."""

    # -- answer audit and retirement --------------------------------------

    @abstractmethod
    async def record_answer(self, record: AnswerRecord) -> None:
        """Persist an audited answer *before* it is released.

        Denials, empty answers and failed verifications are retained. When
        this write is unavailable the caller must fail the request rather
        than release an unaudited answer.
        """

    @abstractmethod
    async def get_answer(self, answer_id: str) -> Optional[AnswerRecord]:
        """Return one audited answer, or ``None`` when unknown."""

    @abstractmethod
    async def retire_answer(self, answer_id: str, *, user: str, reason: str) -> AnswerRecord:
        """Retire an answer and suppress its cited evidence.

        Every ``(contract_id, node_id)`` pair cited by the answer is
        suppressed from future lookups and handoffs in this tenant —
        deliberately broad, and unaffected by renumbering an unchanged
        excerpt on refresh.

        Raises:
            UnknownAnswerError: When the answer does not exist.
        """

    @abstractmethod
    async def retired_citations(self) -> set[tuple[str, str]]:
        """Return every suppressed ``(contract_id, node_id)`` pair."""

    # -- source identity and cursors --------------------------------------

    @abstractmethod
    async def get_delta_token(self, source_uri: str) -> Optional[str]:
        """Return the committed opaque delta cursor for a configured source."""

    @abstractmethod
    async def set_delta_token(self, source_uri: str, token: str) -> None:
        """Commit a delta cursor *after* the whole batch is durable."""

    @abstractmethod
    async def upsert_source_item(self, item: SourceItem) -> None:
        """Record stable remote-item identity for renames, moves and tombstones."""

    @abstractmethod
    async def get_source_item(self, drive_id: str, item_id: str) -> Optional[SourceItem]:
        """Return one recorded source item by its stable drive/item identity."""

    @abstractmethod
    async def list_source_items(self, source: Optional[str] = None) -> list[SourceItem]:
        """Return recorded source items.

        Args:
            source: Restrict to one configured source, or None for every
                source. The unrestricted form exists because a contract can
                be backed by identical files ingested under *different*
                sources — deciding whether a card is still referenced has to
                look past the source currently being processed.
        """

    # -- relation judgements ----------------------------------------------

    @abstractmethod
    async def record_judgement(self, judgement: RelationJudgement) -> None:
        """Append a judgement, including ``none`` outcomes.

        History is preserved: ``--force`` records a *new* judgement and
        replaces the active result rather than rewriting the old row.
        """

    @abstractmethod
    async def judgements_for(self, contract_id: str) -> list[RelationJudgement]:
        """Return judgement history touching one contract, newest last."""

    @abstractmethod
    async def replace_relations(
        self,
        contract_id: str,
        relations: list[ContractRelation],
    ) -> None:
        """Replace the active judged relations owned by one source contract."""

    @abstractmethod
    async def active_relations(
        self,
        contract_id: Optional[str] = None,
    ) -> list[ContractRelation]:
        """Return active judged relations, optionally for one contract."""

    @abstractmethod
    async def invalidate_relations(self, contract_id: str, *, source_sha256: str) -> int:
        """Deactivate relations judged against an outdated source hash.

        Args:
            contract_id: The contract whose source changed.
            source_sha256: The new current hash.

        Returns:
            How many relations were invalidated.
        """

    # -- durable publication outbox ---------------------------------------

    @abstractmethod
    async def enqueue_publication(self, record: PublicationRecord) -> PublicationRecord:
        """Queue one publication row idempotently on its durable key."""

    @abstractmethod
    async def pending_publications(
        self,
        *,
        target: Optional[PublicationTarget] = None,
        limit: int = 50,
    ) -> list[PublicationRecord]:
        """Return queued/failed publication work, oldest first."""

    @abstractmethod
    async def claim_publication(
        self,
        *,
        target: PublicationTarget,
        limit: int = 1,
    ) -> list[PublicationRecord]:
        """Claim publication work, marking it in flight and counting attempts.

        Publication is serialized per tenant: claiming is how a crashed run
        is recovered instead of re-emitting a duplicate logical version.
        """

    @abstractmethod
    async def complete_publication(
        self,
        record: PublicationRecord,
        *,
        receipt: str,
    ) -> PublicationRecord:
        """Record a verified receipt and mark the row published."""

    @abstractmethod
    async def fail_publication(
        self,
        record: PublicationRecord,
        *,
        error: str,
    ) -> PublicationRecord:
        """Record a retryable failure without losing the queued payload."""

    # -- lifecycle ---------------------------------------------------------

    @abstractmethod
    async def setup(self) -> None:
        """Create or migrate this tenant's schema idempotently."""

    @abstractmethod
    async def close(self) -> None:
        """Release owned resources; injected pools are left untouched."""
