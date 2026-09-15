"""Contract tests for :class:`ContractCatalogStore` (TASK-3026).

Also defines :class:`InMemoryContractCatalog`, the in-memory test double
that later contracts suites reuse. The double implements the *complete*
async protocol — including conflict, duplicate-source and
unavailable-publication outcomes — without introducing a second production
backend.
"""

from __future__ import annotations

import inspect
from datetime import date, datetime, timedelta, timezone
from typing import Optional

import pytest

from parrot.knowledge.contracts.catalog import (
    AliasConflictError,
    CatalogConflictError,
    ContractCatalogStore,
    DuplicateSourceError,
    ExpiringKey,
    ObligationWindow,
    PartyMergeResult,
    PublicationUnavailableError,
    SearchHit,
    UnknownAnswerError,
    UnknownContractError,
    UnknownPartyError,
    UpsertResult,
    VerificationQueueEntry,
    validate_sql_identifier,
)
from parrot.knowledge.contracts.models import (
    AnswerRecord,
    AuthorizationOutcome,
    Citation,
    ContractCard,
    ContractRelation,
    ContractStatus,
    ContractVersion,
    FieldProvenance,
    Obligation,
    Party,
    PartyAlias,
    PublicationRecord,
    PublicationTarget,
    RelationJudgement,
    Signatory,
    SourceItem,
    TermSpec,
    VerificationState,
    card_snapshot_payload,
)

FROZEN_NOW = datetime(2026, 9, 9, 12, 0, 0, tzinfo=timezone.utc)
TODAY = date(2026, 9, 9)


# --------------------------------------------------------------------------
# In-memory double
# --------------------------------------------------------------------------


class InMemoryContractCatalog(ContractCatalogStore):
    """A complete, deterministic in-memory :class:`ContractCatalogStore`.

    Mirrors the Postgres backend's *observable* preconditions — optimistic
    revisions, one atomic card write, immutable history and a durable
    outbox — so library, graph and answer suites can exercise real
    behaviour without a database.

    Args:
        tenant_id: Tenant this double is bound to.
        schema: Validated schema name (kept only for parity).
        principal: Optional service principal.
        now: Frozen timestamp used for every recorded time.
    """

    def __init__(
        self,
        *,
        tenant_id: str = "troc",
        schema: str = "contracts",
        principal: Optional[str] = None,
        now: datetime = FROZEN_NOW,
    ) -> None:
        super().__init__(tenant_id=tenant_id, schema=schema, principal=principal)
        self._now = now
        self.cards: dict[str, ContractCard] = {}
        self.obligations: dict[str, list[Obligation]] = {}
        self.version_history: dict[str, list[ContractVersion]] = {}
        self.aliases: dict[str, PartyAlias] = {}
        self.answers: dict[str, AnswerRecord] = {}
        self.suppressed: set[tuple[str, str]] = set()
        self.tokens: dict[str, str] = {}
        self.items: dict[tuple[str, str], SourceItem] = {}
        self.judgements: list[RelationJudgement] = []
        self.relations: list[ContractRelation] = []
        self.outbox: dict[tuple, PublicationRecord] = {}
        #: Targets that raise :class:`PublicationUnavailableError` on claim.
        self.unavailable_targets: set[str] = set()
        self.setup_calls = 0
        self.closed = False

    # -- cards ------------------------------------------------------------

    async def upsert(
        self,
        card: ContractCard,
        *,
        expected_revision: Optional[int] = None,
        version: Optional[ContractVersion] = None,
        targets: tuple[PublicationTarget, ...] = ("ontology", "temporal"),
    ) -> UpsertResult:
        stored = self.cards.get(card.contract_id)
        if expected_revision is not None:
            actual = stored.revision if stored else None
            if actual != expected_revision:
                raise CatalogConflictError(card.contract_id, expected_revision, actual)

        for other in self.cards.values():
            if other.contract_id == card.contract_id:
                continue
            if card.source_sha256 and other.source_sha256 == card.source_sha256:
                raise DuplicateSourceError(other.contract_id, source_sha256=card.source_sha256)
            if other.source_uri == card.source_uri:
                raise DuplicateSourceError(other.contract_id, source_uri=card.source_uri)

        created = stored is None
        history = self.version_history.setdefault(card.contract_id, [])
        revision = 1 if created else stored.revision + 1
        version_n = version.n if version else (history[-1].n if history else 1)
        written = card.model_copy(update={"revision": revision, "updated_at": self._now, "versions": []})
        recorded = version or ContractVersion(
            n=version_n,
            revision=revision,
            source_sha256=card.source_sha256,
            recorded_at=self._now,
            card_snapshot=card_snapshot_payload(written),
        )
        recorded = recorded.model_copy(update={"revision": revision, "recorded_at": self._now})
        history.append(recorded)
        written = written.model_copy(update={"versions": list(history)})

        self.cards[card.contract_id] = written
        self.obligations[card.contract_id] = list(card.obligations)

        queued: list[PublicationRecord] = []
        for target in targets:
            queued.append(
                await self.enqueue_publication(
                    PublicationRecord(
                        tenant_id=self.tenant_id,
                        contract_id=card.contract_id,
                        version_n=recorded.n,
                        revision=revision,
                        target=target,
                        run_id=f"{card.contract_id}:{recorded.n}:{revision}",
                        payload={"contract_id": card.contract_id},
                        created_at=self._now,
                    )
                )
            )
        return UpsertResult(
            contract_id=card.contract_id,
            revision=revision,
            created=created,
            version_n=recorded.n,
            queued=queued,
        )

    async def get(self, contract_id: str) -> Optional[ContractCard]:
        return self.cards.get(contract_id)

    async def find_by_sha(self, sha256: str) -> Optional[ContractCard]:
        for card in self.cards.values():
            if card.source_sha256 == sha256:
                return card
        return None

    async def find_by_source_uri(self, uri: str) -> Optional[ContractCard]:
        for card in self.cards.values():
            if card.source_uri == uri:
                return card
        return None

    async def list_cards(
        self,
        *,
        status: Optional[ContractStatus] = None,
        verification: Optional[VerificationState] = None,
        active_only: bool = True,
    ) -> list[ContractCard]:
        cards = [
            card
            for card in self.cards.values()
            if (card.active or not active_only)
            and (status is None or card.status == status)
            and (verification is None or card.verification == verification)
        ]
        return sorted(cards, key=lambda card: card.contract_id)

    async def search(self, query: str, top_k: int = 8) -> list[SearchHit]:
        terms = [term for term in query.lower().split() if term]
        hits: list[SearchHit] = []
        for card in self.cards.values():
            if not card.active:
                continue
            haystack = " ".join([card.title, card.summary, card.toc_digest, " ".join(card.topics)]).lower()
            rank = sum(haystack.count(term) for term in terms) / max(len(terms), 1)
            if rank:
                hits.append(SearchHit(card=card, rank=float(rank)))
        hits.sort(key=lambda hit: (-hit.rank, hit.card.contract_id))
        return hits[:top_k]

    async def expiring(
        self,
        *,
        until: date,
        key: ExpiringKey = "notice_deadline",
        since: Optional[date] = None,
    ) -> list[ContractCard]:
        selected: list[tuple[date, ContractCard]] = []
        for card in self.cards.values():
            if not card.active or card.status != "active":
                continue
            when = card.term.expiration_date
            if key == "notice_deadline":
                when = card.term.notice_deadline or card.term.expiration_date
            if when is None:
                continue
            if when > until or (since is not None and when < since):
                continue
            selected.append((when, card))
        selected.sort(key=lambda row: (row[0], row[1].contract_id))
        return [card for _, card in selected]

    async def verification_queue(self, *, limit: int = 50) -> list[VerificationQueueEntry]:
        entries: list[VerificationQueueEntry] = []
        for card in self.cards.values():
            if not card.active or card.verification == "verified":
                continue
            missing = sorted(
                path
                for path, prov in card.field_provenance.items()
                if prov.verification != "verified" and not prov.substantiates
            )
            low = sorted(
                path
                for path, prov in card.field_provenance.items()
                if prov.verification != "verified" and prov.substantiates and (prov.confidence or 0.0) < 0.6
            )
            if missing:
                entries.append(VerificationQueueEntry(card=card, reason="missing_evidence", fields=missing))
            elif low:
                entries.append(VerificationQueueEntry(card=card, reason="low_confidence", fields=low))
            elif card.stale_fields:
                entries.append(VerificationQueueEntry(card=card, reason="stale", fields=sorted(card.stale_fields)))
        entries.sort(key=lambda entry: (entry.priority, entry.card.contract_id))
        return entries[:limit]

    async def taken_slugs(self) -> set[str]:
        return set(self.cards)

    async def remove(self, contract_id: str) -> None:
        card = self.cards.get(contract_id)
        if card is None:
            raise UnknownContractError(contract_id)
        self.cards[contract_id] = card.model_copy(
            update={
                "active": False,
                "obligations": [obligation.model_copy(update={"active": False}) for obligation in card.obligations],
                "updated_at": self._now,
            }
        )
        self.obligations[contract_id] = [
            obligation.model_copy(update={"active": False}) for obligation in self.obligations.get(contract_id, [])
        ]
        for target in ("ontology", "temporal"):
            await self.enqueue_publication(
                PublicationRecord(
                    tenant_id=self.tenant_id,
                    contract_id=contract_id,
                    version_n=card.versions[-1].n if card.versions else 1,
                    revision=card.revision,
                    target=target,  # type: ignore[arg-type]
                    run_id=f"{contract_id}:retract:{card.revision}",
                    payload={"contract_id": contract_id, "tombstone": True},
                    created_at=self._now,
                )
            )

    # -- obligations and versions -----------------------------------------

    async def obligations_for(self, contract_id: str) -> list[Obligation]:
        return sorted(
            self.obligations.get(contract_id, []),
            key=lambda obligation: obligation.obligation_id,
        )

    async def obligations_due(self, window: ObligationWindow) -> list[Obligation]:
        rows: list[Obligation] = []
        for obligations in self.obligations.values():
            for obligation in obligations:
                if not obligation.active:
                    continue
                if window.kinds and obligation.kind not in window.kinds:
                    continue
                if window.standard_id and obligation.standard_id != window.standard_id:
                    continue
                if obligation.due_date is None:
                    if window.include_recurring and obligation.recurrence:
                        rows.append(obligation)
                    continue
                if obligation.due_date > window.until:
                    continue
                if window.since is not None and obligation.due_date < window.since:
                    continue
                rows.append(obligation)
        rows.sort(key=lambda obligation: (obligation.due_date or date.max, obligation.obligation_id))
        return rows[: window.limit]

    async def versions(self, contract_id: str) -> list[ContractVersion]:
        return list(self.version_history.get(contract_id, []))

    # -- parties and aliases ----------------------------------------------

    async def merge_parties(
        self,
        keep_party_id: str,
        merge_party_id: str,
        *,
        user: str,
    ) -> PartyMergeResult:
        if keep_party_id == merge_party_id:
            raise ValueError("cannot merge a party into itself")
        known = {party.party_id for party in await self.list_parties()}
        for party_id in (keep_party_id, merge_party_id):
            if party_id not in known:
                raise UnknownPartyError(party_id)

        updated: list[str] = []
        queued: list[PublicationRecord] = []
        for contract_id, card in list(self.cards.items()):
            if not any(party.party_id == merge_party_id for party in card.parties):
                continue
            parties = [
                party
                for party in card.parties
                if not (
                    party.party_id == merge_party_id and any(other.party_id == keep_party_id for other in card.parties)
                )
            ]
            parties = [
                party.model_copy(update={"party_id": keep_party_id}) if party.party_id == merge_party_id else party
                for party in parties
            ]
            signatories = [
                (
                    signatory.model_copy(update={"party_id": keep_party_id})
                    if signatory.party_id == merge_party_id
                    else signatory
                )
                for signatory in card.signatories
            ]
            self.cards[contract_id] = card.model_copy(
                update={
                    "parties": parties,
                    "signatories": signatories,
                    "revision": card.revision + 1,
                    "updated_at": self._now,
                }
            )
            updated.append(contract_id)
            queued.append(
                await self.enqueue_publication(
                    PublicationRecord(
                        tenant_id=self.tenant_id,
                        contract_id=contract_id,
                        version_n=card.versions[-1].n if card.versions else 1,
                        revision=card.revision + 1,
                        target="ontology",
                        run_id=f"{contract_id}:merge:{card.revision + 1}",
                        payload={"party_merge": [merge_party_id, keep_party_id]},
                        created_at=self._now,
                    )
                )
            )

        remapped: list[str] = []
        for alias, row in list(self.aliases.items()):
            if row.party_id == merge_party_id:
                self.aliases[alias] = row.model_copy(
                    update={"party_id": keep_party_id, "actor": user, "created_at": self._now}
                )
                remapped.append(alias)
        return PartyMergeResult(
            keep_party_id=keep_party_id,
            merged_party_id=merge_party_id,
            cards_updated=sorted(updated),
            aliases_remapped=sorted(remapped),
            queued=queued,
        )

    async def party_aliases(self, party_id: str) -> list[PartyAlias]:
        return sorted(
            (row for row in self.aliases.values() if row.party_id == party_id),
            key=lambda row: row.alias,
        )

    async def all_party_aliases(self) -> dict[str, list[str]]:
        mapping: dict[str, list[str]] = {}
        for row in self.aliases.values():
            mapping.setdefault(row.party_id, []).append(row.alias)
        return {party_id: sorted(values) for party_id, values in sorted(mapping.items())}

    async def add_party_alias(self, alias: str, party_id: str, *, user: str) -> PartyAlias:
        existing = self.aliases.get(alias)
        if existing and existing.party_id != party_id:
            raise AliasConflictError(alias, existing.party_id, party_id)
        row = PartyAlias(alias=alias, party_id=party_id, actor=user, created_at=self._now)
        self.aliases[alias] = row
        return row

    async def resolve_party(self, alias: str) -> Optional[str]:
        row = self.aliases.get(alias)
        return row.party_id if row else None

    async def list_parties(self) -> list[Party]:
        parties: dict[str, Party] = {}
        for card in self.cards.values():
            for party in card.parties:
                parties.setdefault(party.party_id, party)
        return [parties[key] for key in sorted(parties)]

    # -- answer audit ------------------------------------------------------

    async def record_answer(self, record: AnswerRecord) -> None:
        self.answers[record.answer_id] = record

    async def get_answer(self, answer_id: str) -> Optional[AnswerRecord]:
        return self.answers.get(answer_id)

    async def retire_answer(self, answer_id: str, *, user: str, reason: str) -> AnswerRecord:
        record = self.answers.get(answer_id)
        if record is None:
            raise UnknownAnswerError(answer_id)
        retired = record.model_copy(update={"retired_by": user, "retired_at": self._now, "retirement_reason": reason})
        self.answers[answer_id] = retired
        self.suppressed.update(citation.key for citation in record.citations)
        return retired

    async def retired_citations(self) -> set[tuple[str, str]]:
        return set(self.suppressed)

    # -- sources -----------------------------------------------------------

    async def get_delta_token(self, source_uri: str) -> Optional[str]:
        return self.tokens.get(source_uri)

    async def set_delta_token(self, source_uri: str, token: str) -> None:
        self.tokens[source_uri] = token

    async def upsert_source_item(self, item: SourceItem) -> None:
        self.items[(item.drive_id, item.item_id)] = item.model_copy(
            update={"last_seen_at": item.last_seen_at or self._now}
        )

    async def get_source_item(self, drive_id: str, item_id: str) -> Optional[SourceItem]:
        return self.items.get((drive_id, item_id))

    async def list_source_items(self, source: Optional[str] = None) -> list[SourceItem]:
        return sorted(
            (item for item in self.items.values() if source is None or item.source == source),
            key=lambda item: (item.source, item.drive_id, item.item_id),
        )

    # -- relations ---------------------------------------------------------

    async def record_judgement(self, judgement: RelationJudgement) -> None:
        self.judgements.append(judgement)

    async def judgements_for(self, contract_id: str) -> list[RelationJudgement]:
        return [
            judgement
            for judgement in self.judgements
            if contract_id in (judgement.source_contract_id, judgement.target_contract_id)
        ]

    async def replace_relations(
        self,
        contract_id: str,
        relations: list[ContractRelation],
    ) -> None:
        self.relations = [relation for relation in self.relations if relation.source_contract_id != contract_id]
        self.relations.extend(relations)

    async def active_relations(
        self,
        contract_id: Optional[str] = None,
    ) -> list[ContractRelation]:
        return [
            relation
            for relation in self.relations
            if relation.active
            and (contract_id is None or contract_id in (relation.source_contract_id, relation.target_contract_id))
        ]

    async def invalidate_relations(self, contract_id: str, *, source_sha256: str) -> int:
        invalidated = 0
        for judgement in self.judgements:
            if not judgement.active:
                continue
            if judgement.source_contract_id == contract_id and judgement.source_sha256 != source_sha256:
                judgement.active = False
                invalidated += 1
            elif judgement.target_contract_id == contract_id and judgement.target_sha256 != source_sha256:
                judgement.active = False
                invalidated += 1
        remaining: list[ContractRelation] = []
        for relation in self.relations:
            if contract_id in (relation.source_contract_id, relation.target_contract_id):
                remaining.append(relation.model_copy(update={"active": False}))
            else:
                remaining.append(relation)
        self.relations = remaining
        return invalidated

    # -- outbox ------------------------------------------------------------

    async def enqueue_publication(self, record: PublicationRecord) -> PublicationRecord:
        existing = self.outbox.get(record.key)
        if existing is not None:
            return existing
        stored = record.model_copy(update={"created_at": record.created_at or self._now})
        self.outbox[record.key] = stored
        return stored

    async def pending_publications(
        self,
        *,
        target: Optional[PublicationTarget] = None,
        limit: int = 50,
    ) -> list[PublicationRecord]:
        rows = [
            record
            for record in self.outbox.values()
            if record.state in ("pending", "failed") and (target is None or record.target == target)
        ]
        rows.sort(key=lambda record: record.key)
        return rows[:limit]

    async def claim_publication(
        self,
        *,
        target: PublicationTarget,
        limit: int = 1,
    ) -> list[PublicationRecord]:
        if target in self.unavailable_targets:
            raise PublicationUnavailableError(target, "target marked unavailable in test double")
        claimed: list[PublicationRecord] = []
        for record in await self.pending_publications(target=target, limit=limit):
            updated = record.model_copy(
                update={
                    "state": "in_flight",
                    "attempts": record.attempts + 1,
                    "updated_at": self._now,
                }
            )
            self.outbox[record.key] = updated
            claimed.append(updated)
        return claimed

    async def complete_publication(
        self,
        record: PublicationRecord,
        *,
        receipt: str,
    ) -> PublicationRecord:
        updated = record.model_copy(
            update={
                "state": "published",
                "receipt": receipt,
                "last_error": None,
                "updated_at": self._now,
            }
        )
        self.outbox[record.key] = updated
        return updated

    async def fail_publication(
        self,
        record: PublicationRecord,
        *,
        error: str,
    ) -> PublicationRecord:
        updated = record.model_copy(update={"state": "failed", "last_error": error, "updated_at": self._now})
        self.outbox[record.key] = updated
        return updated

    # -- lifecycle ---------------------------------------------------------

    async def setup(self) -> None:
        self.setup_calls += 1

    async def close(self) -> None:
        self.closed = True


# --------------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------------


def make_card(contract_id: str = "acme-msa", **overrides) -> ContractCard:
    """Build a synthetic card for catalog tests."""
    payload = {
        "contract_id": contract_id,
        "title": f"{contract_id} agreement",
        "contract_type": "msa",
        "status": "active",
        "source_uri": f"sharepoint://legal/{contract_id}.pdf",
        "source_sha256": f"{contract_id}-sha",
        "source_format": "pdf",
        "parties": [
            Party(party_id="party-us", name="Troc Global", role="us", is_us=True),
            Party(party_id="party-acme", name="ACME Inc.", role="customer"),
        ],
        "term": TermSpec(
            effective_date=date(2026, 1, 1),
            expiration_date=date(2026, 12, 31),
            notice_days=60,
            notice_deadline=date(2026, 11, 1),
        ),
        "added_at": FROZEN_NOW,
        "updated_at": FROZEN_NOW,
    }
    payload.update(overrides)
    return ContractCard(**payload)


@pytest.fixture()
def catalog() -> InMemoryContractCatalog:
    return InMemoryContractCatalog()


# --------------------------------------------------------------------------
# 1. The double satisfies the complete async protocol
# --------------------------------------------------------------------------


def test_protocol_is_fully_implemented_and_async():
    assert not getattr(InMemoryContractCatalog, "__abstractmethods__", set())

    abstract = {
        name
        for name, member in inspect.getmembers(ContractCatalogStore)
        if getattr(member, "__isabstractmethod__", False)
    }
    assert abstract, "the protocol must declare abstract methods"
    for name in abstract:
        assert inspect.iscoroutinefunction(getattr(ContractCatalogStore, name)), name
        assert inspect.iscoroutinefunction(getattr(InMemoryContractCatalog, name)), name


def test_protocol_declares_every_spec_operation():
    expected = {
        "upsert",
        "get",
        "find_by_sha",
        "find_by_source_uri",
        "list_cards",
        "search",
        "expiring",
        "verification_queue",
        "taken_slugs",
        "remove",
        "obligations_for",
        "obligations_due",
        "versions",
        "merge_parties",
        "party_aliases",
        "all_party_aliases",
        "add_party_alias",
        "resolve_party",
        "list_parties",
        "record_answer",
        "get_answer",
        "retire_answer",
        "retired_citations",
        "get_delta_token",
        "set_delta_token",
        "upsert_source_item",
        "get_source_item",
        "list_source_items",
        "record_judgement",
        "judgements_for",
        "replace_relations",
        "active_relations",
        "invalidate_relations",
        "enqueue_publication",
        "pending_publications",
        "claim_publication",
        "complete_publication",
        "fail_publication",
        "setup",
        "close",
    }
    assert expected <= set(ContractCatalogStore.__abstractmethods__)


def test_cannot_instantiate_the_protocol_directly():
    with pytest.raises(TypeError):
        ContractCatalogStore(tenant_id="troc")  # type: ignore[abstract]


# --------------------------------------------------------------------------
# 2. Tenancy is construction-bound, identifiers are validated
# --------------------------------------------------------------------------


def test_tenant_and_schema_are_bound_at_construction(catalog):
    assert catalog.tenant_id == "troc"
    assert catalog.schema == "contracts"
    assert catalog.principal is None
    # No method takes a tenant argument.
    for name in ContractCatalogStore.__abstractmethods__:
        params = inspect.signature(getattr(ContractCatalogStore, name)).parameters
        assert "tenant_id" not in params, name
        assert "tenant" not in params, name


def test_empty_tenant_is_rejected():
    with pytest.raises(ValueError, match="tenant_id"):
        InMemoryContractCatalog(tenant_id="  ")


@pytest.mark.parametrize("schema", ["contracts; drop table x", "Contracts", "1contracts", ""])
def test_invalid_schema_identifiers_are_rejected(schema):
    with pytest.raises(ValueError, match="catalog schema"):
        InMemoryContractCatalog(schema=schema)


def test_valid_identifier_passes_through():
    assert validate_sql_identifier("contracts_troc") == "contracts_troc"


# --------------------------------------------------------------------------
# 3. Atomic write, revisions and conflicts
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_upsert_writes_card_obligations_history_and_outbox(catalog):
    card = make_card(
        obligations=[
            Obligation(
                obligation_id="acme-msa-ob-1",
                contract_id="acme-msa",
                kind="compliance",
                text="Vendor shall maintain SOC 2.",
                node_id="0007",
                standard_id="soc2",
            )
        ]
    )
    result = await catalog.upsert(card)

    assert result.created is True
    assert result.revision == 1
    assert [record.target for record in result.queued] == ["ontology", "temporal"]
    assert (await catalog.get("acme-msa")).revision == 1
    assert len(await catalog.obligations_for("acme-msa")) == 1
    assert len(await catalog.versions("acme-msa")) == 1
    assert await catalog.taken_slugs() == {"acme-msa"}


@pytest.mark.asyncio
async def test_stale_expected_revision_raises_conflict(catalog):
    card = make_card()
    await catalog.upsert(card)
    stored = await catalog.get("acme-msa")

    await catalog.upsert(stored.model_copy(update={"title": "first writer"}), expected_revision=1)

    with pytest.raises(CatalogConflictError) as excinfo:
        await catalog.upsert(stored.model_copy(update={"title": "second writer"}), expected_revision=1)
    assert excinfo.value.expected == 1
    assert excinfo.value.actual == 2
    assert (await catalog.get("acme-msa")).title == "first writer"


@pytest.mark.asyncio
async def test_history_is_appended_never_rewritten(catalog):
    card = make_card()
    await catalog.upsert(card)
    stored = await catalog.get("acme-msa")
    await catalog.upsert(stored.model_copy(update={"summary": "corrected"}), expected_revision=1)

    history = await catalog.versions("acme-msa")
    assert [version.revision for version in history] == [1, 2]
    assert all("versions" not in version.card_snapshot for version in history)


@pytest.mark.asyncio
async def test_duplicate_source_content_and_uri_are_reported(catalog):
    await catalog.upsert(make_card("acme-msa"))

    clone = make_card("acme-msa-copy", source_uri="sharepoint://legal/other.pdf")
    clone = clone.model_copy(update={"source_sha256": "acme-msa-sha"})
    with pytest.raises(DuplicateSourceError) as excinfo:
        await catalog.upsert(clone)
    assert excinfo.value.contract_id == "acme-msa"

    same_uri = make_card("acme-msa-2", source_uri="sharepoint://legal/acme-msa.pdf")
    with pytest.raises(DuplicateSourceError):
        await catalog.upsert(same_uri)


@pytest.mark.asyncio
async def test_remove_is_a_non_destructive_retraction(catalog):
    await catalog.upsert(
        make_card(
            obligations=[
                Obligation(
                    obligation_id="o1",
                    contract_id="acme-msa",
                    text="clause",
                    node_id="0001",
                )
            ]
        )
    )
    await catalog.remove("acme-msa")

    card = await catalog.get("acme-msa")
    assert card.active is False
    assert all(not obligation.active for obligation in await catalog.obligations_for("acme-msa"))
    assert await catalog.versions("acme-msa"), "history must be retained"
    assert await catalog.list_cards() == []
    assert await catalog.list_cards(active_only=False)

    with pytest.raises(UnknownContractError):
        await catalog.remove("does-not-exist")


# --------------------------------------------------------------------------
# 4. Queries: search, windows, verification queue
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_search_ranks_and_bounds_results(catalog):
    await catalog.upsert(make_card("acme-msa", summary="security security security"))
    await catalog.upsert(make_card("zeta-nda", summary="security"))

    hits = await catalog.search("security", top_k=1)
    assert [hit.card.contract_id for hit in hits] == ["acme-msa"]
    assert hits[0].rank > 0


@pytest.mark.asyncio
async def test_expiring_window_is_inclusive_and_skips_null_dates(catalog):
    await catalog.upsert(make_card("acme-msa"))  # notice_deadline 2026-11-01
    await catalog.upsert(make_card("no-dates", term=TermSpec(), source_uri="x://no-dates"))

    assert [card.contract_id for card in await catalog.expiring(until=date(2026, 11, 1))] == ["acme-msa"]
    assert await catalog.expiring(until=date(2026, 10, 31)) == []


@pytest.mark.asyncio
async def test_expiring_key_falls_back_to_expiration(catalog):
    await catalog.upsert(
        make_card(
            "no-notice",
            term=TermSpec(expiration_date=date(2026, 12, 31)),
        )
    )
    by_notice = await catalog.expiring(until=date(2026, 12, 31), key="notice_deadline")
    by_expiry = await catalog.expiring(until=date(2026, 12, 31), key="expiration_date")
    assert [card.contract_id for card in by_notice] == ["no-notice"]
    assert by_notice == by_expiry


@pytest.mark.asyncio
async def test_verification_queue_priority_and_tie_breaks(catalog):
    missing = make_card(
        "b-missing",
        field_provenance={"title": FieldProvenance(origin="llm", node_id="0001")},
    )
    low = make_card(
        "a-low",
        field_provenance={"title": FieldProvenance(origin="llm", node_id="0001", quote="ACME", confidence=0.4)},
    )
    stale = make_card("c-stale", stale_fields=["term.expiration_date"])
    for card in (missing, low, stale):
        await catalog.upsert(card)

    queue = await catalog.verification_queue()
    assert [entry.card.contract_id for entry in queue] == ["b-missing", "a-low", "c-stale"]
    assert [entry.reason for entry in queue] == ["missing_evidence", "low_confidence", "stale"]
    assert queue[0].fields == ["title"]

    assert len(await catalog.verification_queue(limit=1)) == 1


@pytest.mark.asyncio
async def test_obligation_window_is_typed_and_bounded(catalog):
    await catalog.upsert(
        make_card(
            obligations=[
                Obligation(
                    obligation_id="ob-due",
                    contract_id="acme-msa",
                    kind="reporting",
                    text="report quarterly",
                    node_id="0003",
                    due_date=date(2026, 10, 1),
                ),
                Obligation(
                    obligation_id="ob-late",
                    contract_id="acme-msa",
                    kind="reporting",
                    text="report later",
                    node_id="0004",
                    due_date=date(2027, 1, 1),
                ),
                Obligation(
                    obligation_id="ob-recurring",
                    contract_id="acme-msa",
                    kind="audit_right",
                    text="annual audit",
                    node_id="0005",
                    recurrence="annually",
                ),
            ]
        )
    )
    window = ObligationWindow(until=date(2026, 12, 31), kinds=["reporting"])
    assert [ob.obligation_id for ob in await catalog.obligations_due(window)] == ["ob-due"]

    all_due = await catalog.obligations_due(ObligationWindow(until=date(2026, 12, 31)))
    assert {ob.obligation_id for ob in all_due} == {"ob-due", "ob-recurring"}

    no_recurrence = await catalog.obligations_due(ObligationWindow(until=date(2026, 12, 31), include_recurring=False))
    assert [ob.obligation_id for ob in no_recurrence] == ["ob-due"]


# --------------------------------------------------------------------------
# 5. Parties, answers and sources
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_party_merge_updates_cards_aliases_and_queues_projection(catalog):
    card = make_card(
        parties=[
            Party(party_id="party-us", name="Troc Global", role="us", is_us=True),
            Party(party_id="acme-old", name="ACME Incorporated", role="customer"),
        ],
        signatories=[Signatory(person_id="p1", name="Jane", party_id="acme-old")],
    )
    other = make_card(
        "zeta-nda",
        parties=[Party(party_id="acme-new", name="ACME Inc.", role="customer")],
    )
    await catalog.upsert(card)
    await catalog.upsert(other)
    await catalog.add_party_alias("acme incorporated", "acme-old", user="bob@troc")

    result = await catalog.merge_parties("acme-new", "acme-old", user="bob@troc")

    assert result.cards_updated == ["acme-msa"]
    assert result.aliases_remapped == ["acme incorporated"]
    assert result.queued
    merged = await catalog.get("acme-msa")
    assert {party.party_id for party in merged.parties} == {"party-us", "acme-new"}
    assert merged.signatories[0].party_id == "acme-new"
    assert await catalog.resolve_party("acme incorporated") == "acme-new"
    assert (await catalog.all_party_aliases())["acme-new"] == ["acme incorporated"]


@pytest.mark.asyncio
async def test_party_merge_rejects_self_merge_and_unknown_ids(catalog):
    await catalog.upsert(make_card())
    with pytest.raises(ValueError, match="itself"):
        await catalog.merge_parties("party-acme", "party-acme", user="bob@troc")
    with pytest.raises(UnknownPartyError):
        await catalog.merge_parties("party-acme", "ghost", user="bob@troc")


@pytest.mark.asyncio
async def test_conflicting_alias_is_reported_for_review(catalog):
    await catalog.add_party_alias("acme inc", "acme-1", user="bob@troc")
    await catalog.add_party_alias("acme inc", "acme-1", user="bob@troc")  # idempotent
    with pytest.raises(AliasConflictError):
        await catalog.add_party_alias("acme inc", "acme-2", user="bob@troc")


@pytest.mark.asyncio
async def test_retirement_suppresses_cited_nodes_and_retains_the_record(catalog):
    record = AnswerRecord(
        answer_id="ans-1",
        asked_at=FROZEN_NOW,
        user="bob@troc",
        question="Which contracts require SOC 2?",
        answer_kind="lookup",
        answer="ACME MSA does.",
        citations=[
            Citation(
                contract_id="acme-msa",
                node_id="0007",
                quote="Vendor shall maintain SOC 2.",
                source_sha256="acme-msa-sha",
            )
        ],
        authorization=AuthorizationOutcome(allowed=True, principal="bob@troc"),
    )
    await catalog.record_answer(record)
    retired = await catalog.retire_answer("ans-1", user="bob@troc", reason="wrong clause")

    assert retired.retired is True
    assert retired.retirement_reason == "wrong clause"
    assert await catalog.retired_citations() == {("acme-msa", "0007")}
    assert (await catalog.get_answer("ans-1")).answer_kind == "lookup"

    with pytest.raises(UnknownAnswerError):
        await catalog.retire_answer("nope", user="bob@troc", reason="x")


@pytest.mark.asyncio
async def test_denied_answers_are_retained(catalog):
    await catalog.record_answer(
        AnswerRecord(
            answer_id="ans-denied",
            asked_at=FROZEN_NOW,
            user="mallory@example",
            question="show me everything",
            answer_kind="denied",
            authorization=AuthorizationOutcome(allowed=False, reason="no contract_reader role"),
        )
    )
    stored = await catalog.get_answer("ans-denied")
    assert stored.authorization.allowed is False


@pytest.mark.asyncio
async def test_source_cursor_and_item_identity_round_trip(catalog):
    assert await catalog.get_delta_token("sharepoint://legal") is None
    await catalog.set_delta_token("sharepoint://legal", "token-1")
    assert await catalog.get_delta_token("sharepoint://legal") == "token-1"

    item = SourceItem(
        source="sharepoint://legal",
        drive_id="drive-1",
        item_id="item-1",
        current_uri="sharepoint://legal/acme-msa.pdf",
        contract_id="acme-msa",
    )
    await catalog.upsert_source_item(item)
    renamed = item.model_copy(update={"current_uri": "sharepoint://legal/acme-msa-v2.pdf"})
    await catalog.upsert_source_item(renamed)

    stored = await catalog.get_source_item("drive-1", "item-1")
    assert stored.current_uri.endswith("acme-msa-v2.pdf")
    assert len(await catalog.list_source_items("sharepoint://legal")) == 1


# --------------------------------------------------------------------------
# 6. Judgements and the durable outbox
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_judgement_history_is_preserved_and_invalidated_on_hash_change(catalog):
    judgement = RelationJudgement(
        judgement_id="j1",
        source_contract_id="acme-msa",
        target_contract_id="zeta-nda",
        outcome="conflicts_with",
        source_sha256="sha-1",
        target_sha256="sha-2",
        judged_at=FROZEN_NOW,
    )
    await catalog.record_judgement(judgement)
    await catalog.record_judgement(judgement.model_copy(update={"judgement_id": "j2", "outcome": "none"}))
    await catalog.replace_relations(
        "acme-msa",
        [
            ContractRelation(
                source_contract_id="acme-msa",
                target_contract_id="zeta-nda",
                kind="conflicts_with",
            )
        ],
    )

    assert len(await catalog.judgements_for("acme-msa")) == 2
    assert len(await catalog.active_relations("acme-msa")) == 1

    invalidated = await catalog.invalidate_relations("acme-msa", source_sha256="sha-new")
    assert invalidated == 2
    assert await catalog.active_relations("acme-msa") == []


@pytest.mark.asyncio
async def test_outbox_claim_complete_and_fail_cycle(catalog):
    await catalog.upsert(make_card())

    claimed = await catalog.claim_publication(target="temporal")
    assert len(claimed) == 1
    assert claimed[0].state == "in_flight"
    assert claimed[0].attempts == 1
    assert await catalog.claim_publication(target="temporal") == []

    failed = await catalog.fail_publication(claimed[0], error="connection reset")
    assert failed.state == "failed"
    assert failed.last_error == "connection reset"

    retried = await catalog.claim_publication(target="temporal")
    assert retried[0].attempts == 2

    done = await catalog.complete_publication(retried[0], receipt="commit-123")
    assert done.state == "published"
    assert done.receipt == "commit-123"
    assert await catalog.pending_publications(target="temporal") == []


@pytest.mark.asyncio
async def test_publication_rows_are_idempotent_on_their_durable_key(catalog):
    record = PublicationRecord(
        tenant_id="troc",
        contract_id="acme-msa",
        version_n=1,
        revision=1,
        target="ontology",
        run_id="acme-msa:1:1",
    )
    first = await catalog.enqueue_publication(record)
    second = await catalog.enqueue_publication(record.model_copy(update={"payload": {"x": 1}}))
    assert first is second or first.key == second.key
    assert len(await catalog.pending_publications(target="ontology")) == 1


@pytest.mark.asyncio
async def test_unavailable_publication_target_is_representable(catalog):
    await catalog.upsert(make_card())
    catalog.unavailable_targets.add("ontology")

    with pytest.raises(PublicationUnavailableError) as excinfo:
        await catalog.claim_publication(target="ontology")
    assert excinfo.value.target == "ontology"
    # The work stays queued and recoverable.
    assert len(await catalog.pending_publications(target="ontology")) == 1


@pytest.mark.asyncio
async def test_setup_and_close_are_lifecycle_only(catalog):
    await catalog.setup()
    await catalog.setup()
    await catalog.close()
    assert catalog.setup_calls == 2
    assert catalog.closed is True


def test_no_sqlite_or_postgres_backend_is_introduced_here():
    import parrot.knowledge.contracts.catalog as catalog_module

    source = inspect.getsource(catalog_module)
    assert "sqlite3" not in source
    assert "import asyncpg" not in source
    assert not any(line.strip().startswith(("import ", "from ")) and "asyncpg" in line for line in source.splitlines())


def test_expiry_window_helper_dates_are_deterministic():
    assert TODAY + timedelta(days=90) == date(2026, 12, 8)
