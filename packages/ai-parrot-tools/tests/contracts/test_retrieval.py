"""Deterministic retrieval tests (TASK-3043).

Also defines the shared in-memory catalog double and card factory the rest
of the contracts tools suites reuse.
"""

from __future__ import annotations

import ast
import inspect
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Optional

import pytest

from parrot.knowledge.contracts.catalog import (
    ContractCatalogStore,
    ObligationWindow,
    SearchHit,
    UpsertResult,
    VerificationQueueEntry,
)
from parrot.knowledge.contracts.models import (
    AnswerRecord,
    ContractCard,
    ContractRelation,
    ContractVersion,
    Obligation,
    Party,
    PartyAlias,
    PublicationRecord,
    RelationJudgement,
    Signatory,
    SourceItem,
    TermSpec,
)
from parrot_tools.contracts.retrieval import (
    DEFAULT_TOP_K,
    MAX_TOP_K,
    PATTERNS,
    AuthorizationDenied,
    Clarification,
    ContractRetrieval,
    RequestContext,
    classify,
    is_interpretation,
)

FROZEN_NOW = datetime(2026, 9, 9, 12, 0, 0, tzinfo=timezone.utc)
TODAY = date(2026, 9, 9)


# --------------------------------------------------------------------------
# Shared doubles
# --------------------------------------------------------------------------


class FakeCatalog(ContractCatalogStore):
    """A compact in-memory catalog for the tools suites."""

    def __init__(self, *, tenant_id: str = "troc") -> None:
        super().__init__(tenant_id=tenant_id)
        self.cards: dict[str, ContractCard] = {}
        self.history: dict[str, list[ContractVersion]] = {}
        self.aliases: dict[str, str] = {}
        self.answers: dict[str, AnswerRecord] = {}
        self.suppressed: set[tuple[str, str]] = set()
        self.relations: list[ContractRelation] = []
        self.tokens: dict[str, str] = {}
        self.items: dict[tuple[str, str], SourceItem] = {}
        self.outbox: dict[tuple, PublicationRecord] = {}
        self.judgements: list[RelationJudgement] = []
        self.audit_fails = False

    async def upsert(self, card, *, expected_revision=None, version=None, targets=("ontology", "temporal")):
        stored = self.cards.get(card.contract_id)
        created = stored is None
        revision = 1 if created else stored.revision + 1
        history = self.history.setdefault(card.contract_id, [])
        if created and not history and card.versions and version is None:
            # A fixture card that arrives with its own history keeps it.
            history.extend(card.versions)
            self.cards[card.contract_id] = card.model_copy(update={"revision": revision})
            return UpsertResult(
                contract_id=card.contract_id,
                revision=revision,
                created=True,
                version_n=history[-1].n,
            )
        recorded = (version or ContractVersion(n=history[-1].n if history else 1)).model_copy(
            update={"revision": revision, "recorded_at": FROZEN_NOW}
        )
        history.append(recorded)
        self.cards[card.contract_id] = card.model_copy(update={"revision": revision, "versions": list(history)})
        return UpsertResult(
            contract_id=card.contract_id,
            revision=revision,
            created=created,
            version_n=recorded.n,
        )

    async def get(self, contract_id):
        return self.cards.get(contract_id)

    async def find_by_sha(self, sha256):
        return next((c for c in self.cards.values() if c.source_sha256 == sha256), None)

    async def find_by_source_uri(self, uri):
        return next((c for c in self.cards.values() if c.source_uri == uri), None)

    async def list_cards(self, *, status=None, verification=None, active_only=True):
        return sorted(
            (
                card
                for card in self.cards.values()
                if (card.active or not active_only)
                and (status is None or card.status == status)
                and (verification is None or card.verification == verification)
            ),
            key=lambda card: card.contract_id,
        )

    async def search(self, query, top_k=8):
        terms = [term for term in query.lower().split() if len(term) > 2]
        hits = []
        for card in self.cards.values():
            haystack = f"{card.title} {card.summary}".lower()
            rank = sum(haystack.count(term) for term in terms)
            if rank:
                hits.append(SearchHit(card=card, rank=float(rank)))
        hits.sort(key=lambda hit: (-hit.rank, hit.card.contract_id))
        return hits[:top_k]

    async def expiring(self, *, until, key="notice_deadline", since=None):
        selected = []
        for card in self.cards.values():
            if card.status != "active" or not card.active:
                continue
            when = card.term.expiration_date
            if key == "notice_deadline":
                when = card.term.notice_deadline or card.term.expiration_date
            if when is None or when > until or (since and when < since):
                continue
            selected.append((when, card))
        return [card for _, card in sorted(selected, key=lambda row: (row[0], row[1].contract_id))]

    async def verification_queue(self, *, limit=50):
        return [
            VerificationQueueEntry(card=card, reason="stale", fields=card.stale_fields)
            for card in await self.list_cards()
            if card.stale_fields
        ][:limit]

    async def taken_slugs(self):
        return set(self.cards)

    async def remove(self, contract_id):
        card = self.cards[contract_id]
        self.cards[contract_id] = card.model_copy(update={"active": False})

    async def obligations_for(self, contract_id):
        card = self.cards.get(contract_id)
        return list(card.obligations) if card else []

    async def obligations_due(self, window: ObligationWindow):
        rows = []
        for card in self.cards.values():
            if not card.active:
                continue
            for obligation in card.obligations:
                if not obligation.active:
                    continue
                if window.standard_id and obligation.standard_id != window.standard_id:
                    continue
                if window.kinds and obligation.kind not in window.kinds:
                    continue
                if obligation.due_date and obligation.due_date > window.until:
                    continue
                rows.append(obligation)
        return sorted(rows, key=lambda item: item.obligation_id)[: window.limit]

    async def versions(self, contract_id):
        return list(self.history.get(contract_id, []))

    async def merge_parties(self, keep_party_id, merge_party_id, *, user):
        raise NotImplementedError

    async def party_aliases(self, party_id):
        return [PartyAlias(alias=alias, party_id=value) for alias, value in self.aliases.items() if value == party_id]

    async def all_party_aliases(self):
        mapping: dict[str, list[str]] = {}
        for alias, party_id in self.aliases.items():
            mapping.setdefault(party_id, []).append(alias)
        return {key: sorted(values) for key, values in sorted(mapping.items())}

    async def add_party_alias(self, alias, party_id, *, user):
        self.aliases[alias] = party_id
        return PartyAlias(alias=alias, party_id=party_id, actor=user)

    async def resolve_party(self, alias):
        return self.aliases.get(alias)

    async def list_parties(self):
        parties: dict[str, Party] = {}
        for card in self.cards.values():
            for party in card.parties:
                parties.setdefault(party.party_id, party)
        return [parties[key] for key in sorted(parties)]

    async def record_answer(self, record):
        if self.audit_fails:
            raise RuntimeError("audit store unavailable")
        self.answers[record.answer_id] = record

    async def get_answer(self, answer_id):
        return self.answers.get(answer_id)

    async def retire_answer(self, answer_id, *, user, reason):
        record = self.answers[answer_id]
        retired = record.model_copy(update={"retired_by": user, "retired_at": FROZEN_NOW, "retirement_reason": reason})
        self.answers[answer_id] = retired
        self.suppressed.update(citation.key for citation in record.citations)
        return retired

    async def retired_citations(self):
        return set(self.suppressed)

    async def get_delta_token(self, source_uri):
        return self.tokens.get(source_uri)

    async def set_delta_token(self, source_uri, token):
        self.tokens[source_uri] = token

    async def upsert_source_item(self, item):
        self.items[(item.drive_id, item.item_id)] = item

    async def get_source_item(self, drive_id, item_id):
        return self.items.get((drive_id, item_id))

    async def list_source_items(self, source=None):
        return [item for item in self.items.values() if source is None or item.source == source]

    async def record_judgement(self, judgement):
        self.judgements.append(judgement)

    async def judgements_for(self, contract_id):
        return [
            judgement
            for judgement in self.judgements
            if contract_id in (judgement.source_contract_id, judgement.target_contract_id)
        ]

    async def replace_relations(self, contract_id, relations):
        self.relations = [relation for relation in self.relations if relation.source_contract_id != contract_id] + list(
            relations
        )

    async def active_relations(self, contract_id=None):
        return [
            relation
            for relation in self.relations
            if relation.active
            and (contract_id is None or contract_id in (relation.source_contract_id, relation.target_contract_id))
        ]

    async def invalidate_relations(self, contract_id, *, source_sha256):
        return 0

    async def enqueue_publication(self, record):
        self.outbox[record.key] = record
        return record

    async def pending_publications(self, *, target=None, limit=50):
        return [
            record
            for record in self.outbox.values()
            if record.state in ("pending", "failed") and (target is None or record.target == target)
        ][:limit]

    async def claim_publication(self, *, target, limit=1):
        claimed = []
        for record in await self.pending_publications(target=target, limit=limit):
            updated = record.model_copy(update={"state": "in_flight", "attempts": record.attempts + 1})
            self.outbox[record.key] = updated
            claimed.append(updated)
        return claimed

    async def complete_publication(self, record, *, receipt):
        updated = record.model_copy(update={"state": "published", "receipt": receipt})
        self.outbox[record.key] = updated
        return updated

    async def fail_publication(self, record, *, error):
        updated = record.model_copy(update={"state": "failed", "last_error": error})
        self.outbox[record.key] = updated
        return updated

    async def setup(self):
        return None

    async def close(self):
        return None


def make_card(contract_id: str = "acme-msa", **overrides) -> ContractCard:
    """A synthetic card for the tools suites."""
    payload = {
        "contract_id": contract_id,
        "title": f"{contract_id} agreement",
        "summary": "Security obligations for the ACME account.",
        "contract_type": "msa",
        "status": "active",
        "source_uri": f"sharepoint://legal/{contract_id}.pdf",
        "source_sha256": f"sha-{contract_id}",
        "source_format": "pdf",
        "owner_employee_id": "emp-1",
        "department": "legal",
        "parties": [
            Party(party_id="party-us", name="Troc Global", role="us", is_us=True),
            Party(party_id="party-acme", name="ACME Inc.", role="customer"),
        ],
        "signatories": [
            Signatory(
                person_id=f"{contract_id}-person-jane",
                name="Jane Doe",
                party_id="party-acme",
                signed_on=date(2025, 12, 20),
            )
        ],
        "term": TermSpec(
            effective_date=date(2026, 1, 1),
            expiration_date=date(2026, 12, 31),
            notice_days=60,
            notice_deadline=date(2026, 11, 1),
        ),
        "obligations": [
            Obligation(
                obligation_id=f"{contract_id}-ob-001",
                contract_id=contract_id,
                kind="compliance",
                text="Vendor shall maintain SOC 2 Type II certification.",
                node_id="0005",
                page=12,
                standard_id="soc2",
            ),
            Obligation(
                obligation_id=f"{contract_id}-ob-002",
                contract_id=contract_id,
                kind="insurance",
                text="Vendor shall carry cyber liability insurance.",
                node_id="0008",
            ),
        ],
        "versions": [
            ContractVersion(
                n=1,
                valid_from=date(2026, 1, 1),
                valid_to=date(2026, 7, 1),
                source_sha256=f"sha-{contract_id}",
                recorded_at=FROZEN_NOW,
            ),
            ContractVersion(
                n=2,
                valid_from=date(2026, 7, 1),
                source_sha256=f"sha-{contract_id}",
                recorded_at=FROZEN_NOW,
            ),
        ],
        "added_at": FROZEN_NOW,
        "updated_at": FROZEN_NOW,
    }
    payload.update(overrides)
    return ContractCard(**payload)


def reader_context(**overrides) -> RequestContext:
    """An authenticated contract_reader."""
    payload = {
        "user_id": "bob@troc",
        "roles": ("contract_reader",),
        "tenant_id": "troc",
        "employee_id": "emp-1",
        "employee_graph_id": "employees/emp-1",
        "department": "legal",
    }
    payload.update(overrides)
    return RequestContext(**payload)


@pytest.fixture()
async def retrieval() -> ContractRetrieval:
    catalog = FakeCatalog()
    await catalog.upsert(make_card())
    await catalog.add_party_alias("acme incorporated", "party-acme", user="bob@troc")
    return ContractRetrieval(catalog=catalog, today=lambda: TODAY)


# --------------------------------------------------------------------------
# Classification
# --------------------------------------------------------------------------


def test_the_ten_patterns_are_the_allowlist():
    assert len(PATTERNS) == 10
    assert set(PATTERNS) == {
        "contracts_requiring_standard",
        "expiring_within",
        "notice_deadlines_within",
        "contracts_with_party",
        "contract_family",
        "signatories_of",
        "obligations_of_contract",
        "contract_in_force",
        "my_contracts",
        "search_contracts",
    }


@pytest.mark.parametrize(
    ("question", "pattern"),
    [
        ("Which contracts require SOC 2?", "contracts_requiring_standard"),
        ("What renews in the next 90 days?", "expiring_within"),
        ("By when must we give notice on the ACME MSA?", "notice_deadlines_within"),
        ("What contracts with ACME Inc. do we have?", "contracts_with_party"),
        ("Show the contract family of acme-msa", "contract_family"),
        ("Who signed acme-msa?", "signatories_of"),
        ("What obligations does acme-msa carry?", "obligations_of_contract"),
        ("Which version of acme-msa was in force on 2026-03-01?", "contract_in_force"),
        ("Show my contracts", "my_contracts"),
        ("Which contract mentions data residency?", "search_contracts"),
    ],
)
def test_each_pattern_has_a_trigger(question, pattern):
    assert classify(question) == pattern


def test_the_most_specific_trigger_wins():
    # "notice" is more specific than the generic renewal window.
    assert classify("By when must we give notice before renewal?") == "notice_deadlines_within"
    # A standard requirement beats a plain search.
    assert classify("Which contracts require SOC 2 and mention audits?") == "contracts_requiring_standard"


def test_an_unclassifiable_question_fails_closed():
    assert classify("what is the weather in madrid") is None


@pytest.mark.parametrize(
    "question",
    [
        "Should we accept the redline?",
        "Can we terminate early?",
        "Is ACME compliant with our security policy?",
        "Do we have to notify them?",
    ],
)
def test_evaluative_questions_are_interpretation_requests(question):
    assert is_interpretation(question) is True


# --------------------------------------------------------------------------
# 1. Bind sets
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_standard_alias_resolves_over_the_full_question(retrieval):
    plan = await retrieval.plan("Which contracts require SOC 2?", reader_context())
    assert plan.pattern == "contracts_requiring_standard"
    assert plan.binds == {"standard_id": "soc2", "statuses": ["active"]}
    assert plan.entities["standard"] == "soc2"


@pytest.mark.asyncio
async def test_an_unnamed_or_ambiguous_standard_asks_for_clarification(retrieval):
    unnamed = await retrieval.plan("Which contracts require certification?", reader_context())
    assert isinstance(unnamed, Clarification)

    several = await retrieval.plan("Which contracts require SOC 2 and ISO 27001?", reader_context())
    assert isinstance(several, Clarification)
    assert several.candidates == ["soc2", "iso27001"]


@pytest.mark.asyncio
async def test_date_windows_are_injected_never_derived_in_the_query(retrieval):
    plan = await retrieval.plan("What is expiring in the next 30 days?", reader_context())
    assert plan.binds["today"] == TODAY
    assert plan.binds["until"] == date(2026, 10, 9)

    default = await retrieval.plan("Which contracts are expiring?", reader_context())
    assert default.binds["until"] == date(2026, 12, 8), "90-day default"


@pytest.mark.asyncio
async def test_obligation_kind_is_nullable_but_always_bound(retrieval):
    typed = await retrieval.plan("What insurance obligations does acme-msa carry?", reader_context())
    assert typed.binds["kind"] == "insurance"

    untyped = await retrieval.plan("What obligations does acme-msa carry?", reader_context())
    assert "kind" in untyped.binds
    assert untyped.binds["kind"] is None


@pytest.mark.asyncio
async def test_as_of_uses_an_explicit_date_or_the_injected_today(retrieval):
    explicit = await retrieval.plan("Which version of acme-msa was in force on 2026-03-01?", reader_context())
    assert explicit.binds["as_of"] == date(2026, 3, 1)

    implicit = await retrieval.plan("Which version of acme-msa is in force?", reader_context())
    assert implicit.binds["as_of"] == TODAY


@pytest.mark.asyncio
async def test_my_contracts_binds_the_employee_graph_id(retrieval):
    plan = await retrieval.plan("Show my contracts", reader_context())
    assert plan.binds == {"user_id": "employees/emp-1"}, "a full _id, not a _key"


@pytest.mark.asyncio
async def test_search_top_k_is_bounded(retrieval):
    plan = await retrieval.plan("Which contract mentions data residency?", reader_context())
    assert plan.binds["top_k"] == DEFAULT_TOP_K
    assert DEFAULT_TOP_K <= MAX_TOP_K


@pytest.mark.asyncio
async def test_contract_and_party_binds_are_keys_not_ids(retrieval):
    contract = await retrieval.plan("Who signed acme-msa?", reader_context())
    assert contract.binds == {"contract_id": "acme-msa"}

    party = await retrieval.plan("What contracts with ACME Inc. do we have?", reader_context())
    assert party.binds == {"party_id": "party-acme"}


# --------------------------------------------------------------------------
# Entity resolution
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_parties_resolve_by_name_and_by_catalog_alias(retrieval):
    by_name = await retrieval.resolve_party("contracts with ACME Inc.", reader_context())
    assert by_name == "party-acme"
    by_alias = await retrieval.resolve_party("contracts with acme incorporated", reader_context())
    assert by_alias == "party-acme"


@pytest.mark.asyncio
async def test_an_ambiguous_contract_match_returns_a_clarification(retrieval):
    # Two cards whose *titles* are identical and whose ids the question
    # never names: only fuzzy matching can apply, and it ties.
    await retrieval.catalog.upsert(make_card("alpha-2024", title="master agreement with globex"))
    await retrieval.catalog.upsert(make_card("beta-2026", title="master agreement with globex"))

    resolved = await retrieval.resolve_contract("who signed the master agreement with globex", reader_context())
    assert isinstance(resolved, Clarification)
    assert resolved.candidates == ["alpha-2024", "beta-2026"]


@pytest.mark.asyncio
async def test_an_unmatched_entity_returns_a_clarification(retrieval):
    resolved = await retrieval.resolve_contract("who signed the zeta nda", reader_context())
    assert isinstance(resolved, Clarification)
    party = await retrieval.resolve_party("contracts with Omega SA", reader_context())
    assert isinstance(party, Clarification)


# --------------------------------------------------------------------------
# Execution over SQL (no ArangoDB anywhere)
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_standard_lookup_returns_cards_and_their_obligations(retrieval):
    result = await retrieval.retrieve("Which contracts require SOC 2?", reader_context())
    assert [card.contract_id for card in result.cards] == ["acme-msa"]
    assert [obligation.obligation_id for obligation in result.obligations] == ["acme-msa-ob-001"]
    assert result.used_graph is False


@pytest.mark.asyncio
async def test_windows_queue_and_search_work_without_a_graph_store(retrieval):
    assert retrieval.graph_store is None

    expiring = await retrieval.retrieve("What is expiring in the next 200 days?", reader_context())
    assert [card.contract_id for card in expiring.cards] == ["acme-msa"]

    notice = await retrieval.retrieve("By when must we give notice in the next 120 days?", reader_context())
    assert [card.contract_id for card in notice.cards] == ["acme-msa"]

    search = await retrieval.retrieve("Find the contract about security for the ACME account", reader_context())
    assert [card.contract_id for card in search.cards] == ["acme-msa"]
    assert search.rows[0]["rank"] > 0


@pytest.mark.asyncio
async def test_obligations_are_filtered_by_the_bound_kind(retrieval):
    everything = await retrieval.retrieve("What obligations does acme-msa carry?", reader_context())
    assert len(everything.obligations) == 2

    insurance = await retrieval.retrieve("What insurance obligations does acme-msa carry?", reader_context())
    assert [item.kind for item in insurance.obligations] == ["insurance"]


@pytest.mark.asyncio
async def test_contract_in_force_selects_the_effective_version(retrieval):
    result = await retrieval.retrieve("Which version of acme-msa was in force on 2026-03-01?", reader_context())
    assert [row["n"] for row in result.rows] == [1]

    later = await retrieval.retrieve("Which version of acme-msa was in force on 2026-08-01?", reader_context())
    assert [row["n"] for row in later.rows] == [2]


@pytest.mark.asyncio
async def test_contract_family_deduplicates_by_identity(retrieval):
    await retrieval.catalog.upsert(make_card("acme-sow-1", contract_type="sow", parent_contract_id="acme-msa"))
    await retrieval.catalog.upsert(make_card("acme-sow-2", contract_type="sow", parent_contract_id="acme-msa"))
    result = await retrieval.retrieve("Show the contract family of acme-msa", reader_context())
    ids = [card.contract_id for card in result.cards]
    assert ids == ["acme-msa", "acme-sow-1", "acme-sow-2"]
    assert len(ids) == len(set(ids))


@pytest.mark.asyncio
async def test_an_unsupported_question_returns_a_clarification(retrieval):
    result = await retrieval.retrieve("what is the weather in madrid", reader_context())
    assert isinstance(result, Clarification)


@pytest.mark.asyncio
async def test_an_evaluative_question_is_routed_to_interpretation(retrieval):
    result = await retrieval.retrieve("Should we accept the redline?", reader_context())
    assert result.pattern == "interpretation"
    assert result.cards == []


# --------------------------------------------------------------------------
# Graph execution: allowlist and staleness
# --------------------------------------------------------------------------


class FakeOntology:
    def __init__(self) -> None:
        self.traversal_patterns = {
            name: type("Pattern", (), {"query_template": f"FOR c IN @@contract // {name}"})() for name in PATTERNS
        }


class FakeGraphStore:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def execute_traversal(self, ctx, aql, bind_vars=None, collection_binds=None):
        self.calls.append((aql, dict(bind_vars or {})))
        return self.rows


@pytest.mark.asyncio
async def test_only_allowlisted_patterns_may_be_executed(retrieval):
    retrieval.ontology = FakeOntology()
    retrieval.graph_store = FakeGraphStore([])

    assert retrieval.aql_for("signatories_of")
    with pytest.raises(AuthorizationDenied, match="not an allowlisted pattern"):
        retrieval.aql_for("FOR doc IN contract REMOVE doc IN contract")


@pytest.mark.asyncio
async def test_a_stale_graph_projection_fails_closed(retrieval):
    retrieval.ontology = FakeOntology()
    retrieval.graph_store = FakeGraphStore(
        [{"contract": {"contract_id": "acme-msa", "card_revision": 99, "active": True}}]
    )
    plan = await retrieval.plan("Who signed acme-msa?", reader_context())

    with pytest.raises(AuthorizationDenied, match="stale"):
        await retrieval.execute_graph(plan, reader_context())


@pytest.mark.asyncio
async def test_an_inactive_or_incomplete_projection_fails_closed(retrieval):
    retrieval.ontology = FakeOntology()
    plan = await retrieval.plan("Who signed acme-msa?", reader_context())

    retrieval.graph_store = FakeGraphStore(
        [{"contract": {"contract_id": "acme-msa", "card_revision": 1, "active": False}}]
    )
    with pytest.raises(AuthorizationDenied, match="inactive"):
        await retrieval.execute_graph(plan, reader_context())

    retrieval.graph_store = FakeGraphStore([{"contract": {"title": "no identity"}}])
    with pytest.raises(AuthorizationDenied, match="incomplete"):
        await retrieval.execute_graph(plan, reader_context())


@pytest.mark.asyncio
async def test_a_current_projection_is_accepted_with_bound_values(retrieval):
    retrieval.ontology = FakeOntology()
    store = FakeGraphStore([{"contract": {"contract_id": "acme-msa", "card_revision": 1, "active": True}}])
    retrieval.graph_store = store
    plan = await retrieval.plan("Who signed acme-msa?", reader_context())
    rows = await retrieval.execute_graph(plan, reader_context())

    assert len(rows) == 1
    aql, binds = store.calls[0]
    assert "signatories_of" in aql
    assert binds == {"contract_id": "acme-msa"}


# --------------------------------------------------------------------------
# 3. No LLM anywhere
# --------------------------------------------------------------------------


def test_retrieval_accepts_no_llm_client():
    signature = inspect.signature(ContractRetrieval.__init__)
    assert not {"adapter", "client", "llm", "model"} & set(signature.parameters)

    source = Path(inspect.getfile(ContractRetrieval)).read_text()
    tree = ast.parse(source)
    called = {
        node.func.attr for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    for forbidden in ("ask", "ask_structured", "invoke", "completion", "generate"):
        assert forbidden not in called, forbidden


@pytest.mark.asyncio
async def test_a_standing_requirement_without_dates_is_still_found_by_standard():
    """"Shall maintain ISO 27001 throughout the term" has no due date and no
    recurrence; the standard lookup must still return it (it used to go
    through the due-window query, which silently excluded it)."""
    from datetime import date

    from parrot.knowledge.contracts.models import ContractCard, FieldProvenance, Obligation, Party, TermSpec

    card = ContractCard(
        contract_id="acme-msa",
        title="ACME MSA",
        contract_type="msa",
        status="active",
        parties=[Party(party_id="acme", name="ACME, Inc.", role="vendor")],
        term=TermSpec(effective_date=date(2026, 1, 1)),
        source_uri="file:///acme-msa.md",
        source_sha256="a" * 64,
    )
    standing = Obligation(
        obligation_id="acme-msa-ob-001",
        contract_id="acme-msa",
        kind="compliance",
        obligor="counterparty",
        text="Vendor shall maintain ISO/IEC 27001 certification throughout the term.",
        node_id="0002",
        standard_id="iso27001",
        provenance=FieldProvenance(origin="llm", node_id="0002", quote="Vendor shall maintain ISO/IEC 27001"),
    )
    catalog = FakeCatalog()
    await catalog.upsert(card.model_copy(update={"obligations": [standing]}))
    retrieval = ContractRetrieval(catalog=catalog, today=lambda: date(2026, 9, 9))
    result = await retrieval.retrieve("Which agreements require ISO 27001?", reader_context())
    assert not isinstance(result, Clarification)
    assert [c.contract_id for c in result.cards] == ["acme-msa"]
    assert [o.obligation_id for o in result.obligations] == ["acme-msa-ob-001"]
