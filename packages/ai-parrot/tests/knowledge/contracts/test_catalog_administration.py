"""Postgres catalog administration tests (TASK-3029).

Party merge and aliases, answer audit and retirement, source cursors and
item identity, relation judgements and the durable publication outbox.

Live tests require an explicit ``GRAPHINDEX_PG_DSN``.
"""

from __future__ import annotations

import os
import uuid
from datetime import date, datetime, timezone
from typing import AsyncIterator, Optional

import pytest
from parrot.knowledge.contracts.catalog import (
    AliasConflictError,
    UnknownAnswerError,
    UnknownPartyError,
)
from parrot.knowledge.contracts.catalog_postgres import PostgresContractCatalog
from parrot.knowledge.contracts.models import (
    AnswerRecord,
    AuthorizationOutcome,
    Citation,
    ContractCard,
    ContractRelation,
    Party,
    PublicationRecord,
    RelationJudgement,
    Signatory,
    SourceItem,
    TermSpec,
)

PG_DSN: Optional[str] = os.environ.get("GRAPHINDEX_PG_DSN")

requires_pg = pytest.mark.skipif(
    not PG_DSN,
    reason="live Postgres catalog tests require an explicit GRAPHINDEX_PG_DSN",
)

FROZEN_NOW = datetime(2026, 9, 9, 12, 0, 0, tzinfo=timezone.utc)


def frozen_clock() -> datetime:
    """Deterministic clock for recorded timestamps."""
    return FROZEN_NOW


def make_card(contract_id: str, **overrides) -> ContractCard:
    """Build a synthetic card for administration tests."""
    payload = {
        "contract_id": contract_id,
        "title": f"{contract_id} agreement",
        "contract_type": "msa",
        "status": "active",
        "source_uri": f"sharepoint://legal/{contract_id}.pdf",
        "source_sha256": f"sha-{contract_id}",
        "source_format": "pdf",
        "parties": [Party(party_id="party-acme", name="ACME Inc.", role="customer")],
        "term": TermSpec(expiration_date=date(2026, 12, 31)),
        "added_at": FROZEN_NOW,
        "updated_at": FROZEN_NOW,
    }
    payload.update(overrides)
    return ContractCard(**payload)


def make_answer(answer_id: str = "ans-1", **overrides) -> AnswerRecord:
    """Build a synthetic audited answer."""
    payload = {
        "answer_id": answer_id,
        "asked_at": FROZEN_NOW,
        "user": "bob@troc",
        "question": "Which contracts require SOC 2?",
        "answer_kind": "lookup",
        "pattern": "contracts_requiring_standard",
        "answer": "ACME MSA requires SOC 2.",
        "citations": [
            Citation(
                contract_id="acme-msa",
                title="acme-msa agreement",
                node_id="0007",
                quote="Vendor shall maintain SOC 2.",
                version_n=1,
                source_sha256="sha-acme-msa",
                verification="verified",
            )
        ],
        "authorization": AuthorizationOutcome(allowed=True, principal="bob@troc", matched_rule="contract_reader"),
    }
    payload.update(overrides)
    return AnswerRecord(**payload)


@pytest.fixture()
async def live_catalog() -> AsyncIterator[PostgresContractCatalog]:
    """A catalog bound to a fresh temporary schema, dropped afterwards."""
    import asyncpg

    schema = f"contracts_a_{uuid.uuid4().hex[:8]}"
    pool = await asyncpg.create_pool(dsn=PG_DSN, min_size=1, max_size=4)
    catalog = PostgresContractCatalog(pool=pool, tenant_id="troc", schema=schema, now=frozen_clock)
    await catalog.setup()
    try:
        yield catalog
    finally:
        async with pool.acquire() as conn:
            await conn.execute(f"DROP SCHEMA IF EXISTS {schema} CASCADE")
        await pool.close()


# --------------------------------------------------------------------------
# Offline guards
# --------------------------------------------------------------------------


def test_backend_implements_the_whole_protocol():
    assert PostgresContractCatalog.__abstractmethods__ == frozenset()


@pytest.mark.asyncio
async def test_self_merge_is_rejected_before_any_query():
    catalog = PostgresContractCatalog(dsn="postgresql://unused/db", tenant_id="troc")
    with pytest.raises(ValueError, match="itself"):
        await catalog.merge_parties("acme", "acme", user="bob@troc")


# --------------------------------------------------------------------------
# Live: party merge and aliases
# --------------------------------------------------------------------------


@requires_pg
@pytest.mark.asyncio
async def test_live_party_merge_moves_cards_signatories_aliases_and_projection(live_catalog):
    await live_catalog.upsert(
        make_card(
            "acme-msa",
            parties=[
                Party(party_id="party-us", name="Troc Global", role="us", is_us=True),
                Party(party_id="acme-old", name="ACME Incorporated", role="customer"),
            ],
            signatories=[Signatory(person_id="p1", name="Jane Doe", party_id="acme-old")],
        )
    )
    await live_catalog.upsert(make_card("zeta-sow", parties=[Party(party_id="acme-new", name="ACME Inc.")]))
    await live_catalog.add_party_alias("acme incorporated", "acme-old", user="bob@troc")
    snapshot_before = (await live_catalog.versions("acme-msa"))[0].card_snapshot

    result = await live_catalog.merge_parties("acme-new", "acme-old", user="bob@troc")

    assert result.cards_updated == ["acme-msa"]
    assert result.aliases_remapped == ["acme incorporated"]
    assert [record.target for record in result.queued] == ["ontology", "temporal"]
    history = await live_catalog.versions("acme-msa")
    assert [version.revision for version in history] == [1, 2]
    assert history[-1].card_snapshot["parties"][-1]["party_id"] == "acme-new"

    merged = await live_catalog.get("acme-msa")
    assert {party.party_id for party in merged.parties} == {"party-us", "acme-new"}
    assert merged.signatories[0].party_id == "acme-new"
    assert merged.revision == 2
    assert await live_catalog.resolve_party("acme incorporated") == "acme-new"
    assert (await live_catalog.all_party_aliases())["acme-new"] == ["acme incorporated"]

    # Historical snapshots keep the identity they were signed under.
    snapshot_after = (await live_catalog.versions("acme-msa"))[0].card_snapshot
    assert snapshot_after == snapshot_before
    assert any(party["party_id"] == "acme-old" for party in snapshot_after["parties"])


@requires_pg
@pytest.mark.asyncio
async def test_live_merge_deduplicates_when_both_parties_share_a_card(live_catalog):
    await live_catalog.upsert(
        make_card(
            "acme-msa",
            parties=[
                Party(party_id="acme-old", name="ACME Incorporated"),
                Party(party_id="acme-new", name="ACME Inc."),
            ],
        )
    )
    await live_catalog.merge_parties("acme-new", "acme-old", user="bob@troc")
    merged = await live_catalog.get("acme-msa")
    assert [party.party_id for party in merged.parties] == ["acme-new"]


@requires_pg
@pytest.mark.asyncio
async def test_live_merge_rejects_unknown_identities_and_rolls_back(live_catalog):
    await live_catalog.upsert(make_card("acme-msa"))

    with pytest.raises(UnknownPartyError):
        await live_catalog.merge_parties("party-acme", "ghost-party", user="bob@troc")

    stored = await live_catalog.get("acme-msa")
    assert stored.revision == 1
    assert [party.party_id for party in stored.parties] == ["party-acme"]
    assert await live_catalog.pending_publications(target="ontology") != []


@requires_pg
@pytest.mark.asyncio
async def test_live_alias_conflicts_are_surfaced_for_review(live_catalog):
    await live_catalog.add_party_alias("acme inc", "acme-1", user="bob@troc")
    await live_catalog.add_party_alias("acme inc", "acme-1", user="bob@troc")
    with pytest.raises(AliasConflictError) as excinfo:
        await live_catalog.add_party_alias("acme inc", "acme-2", user="bob@troc")
    assert excinfo.value.existing_party_id == "acme-1"
    assert await live_catalog.resolve_party("acme inc") == "acme-1"
    assert [alias.alias for alias in await live_catalog.party_aliases("acme-1")] == ["acme inc"]


@requires_pg
@pytest.mark.asyncio
async def test_live_list_parties_is_distinct_and_skips_retracted(live_catalog):
    await live_catalog.upsert(make_card("a", parties=[Party(party_id="acme", name="ACME Inc.", role="customer")]))
    await live_catalog.upsert(make_card("b", parties=[Party(party_id="acme", name="ACME Inc.", role="customer")]))
    await live_catalog.upsert(make_card("c", parties=[Party(party_id="zeta", name="Zeta LLC")]))
    await live_catalog.remove("c")

    assert [party.party_id for party in await live_catalog.list_parties()] == ["acme"]


# --------------------------------------------------------------------------
# Live: answer audit and retirement
# --------------------------------------------------------------------------


@requires_pg
@pytest.mark.asyncio
async def test_live_answer_audit_round_trip_including_denied_and_empty(live_catalog):
    await live_catalog.record_answer(make_answer())
    await live_catalog.record_answer(
        make_answer(
            "ans-denied",
            answer_kind="denied",
            answer=None,
            citations=[],
            pattern=None,
            authorization=AuthorizationOutcome(allowed=False, reason="no contract_reader role"),
        )
    )
    await live_catalog.record_answer(make_answer("ans-empty", answer_kind="not_found", answer=None, citations=[]))

    stored = await live_catalog.get_answer("ans-1")
    assert stored.answer_kind == "lookup"
    assert stored.citations[0].node_id == "0007"
    assert stored.citations[0].verification == "verified"
    assert stored.authorization.matched_rule == "contract_reader"

    denied = await live_catalog.get_answer("ans-denied")
    assert denied.authorization.allowed is False
    assert denied.answer is None
    assert (await live_catalog.get_answer("ans-empty")).answer_kind == "not_found"
    assert await live_catalog.get_answer("nope") is None


@requires_pg
@pytest.mark.asyncio
async def test_live_retirement_records_actor_reason_and_suppresses_evidence(live_catalog):
    await live_catalog.record_answer(make_answer())
    assert await live_catalog.retired_citations() == set()

    retired = await live_catalog.retire_answer("ans-1", user="bob@troc", reason="wrong clause")
    assert retired.retired is True
    assert retired.retired_by == "bob@troc"
    assert retired.retirement_reason == "wrong clause"
    assert retired.retired_at == FROZEN_NOW
    assert await live_catalog.retired_citations() == {("acme-msa", "0007")}

    with pytest.raises(UnknownAnswerError):
        await live_catalog.retire_answer("ghost", user="bob@troc", reason="x")


@requires_pg
@pytest.mark.asyncio
async def test_live_suppression_is_version_independent(live_catalog):
    await live_catalog.record_answer(make_answer())
    await live_catalog.retire_answer("ans-1", user="bob@troc", reason="wrong clause")

    # A later answer citing the same node at another version stays suppressed:
    # suppression is keyed on (contract_id, node_id), so renumbering an
    # unchanged excerpt cannot evade it.
    await live_catalog.record_answer(
        make_answer(
            "ans-2",
            citations=[
                Citation(
                    contract_id="acme-msa",
                    node_id="0007",
                    quote="Vendor shall maintain SOC 2.",
                    version_n=3,
                    source_sha256="sha-refreshed",
                )
            ],
        )
    )
    assert ("acme-msa", "0007") in await live_catalog.retired_citations()


# --------------------------------------------------------------------------
# Live: cursors and source identity
# --------------------------------------------------------------------------


@requires_pg
@pytest.mark.asyncio
async def test_live_delta_cursor_survives_reconnect(live_catalog):
    assert await live_catalog.get_delta_token("sharepoint://legal") is None
    await live_catalog.set_delta_token("sharepoint://legal", "token-1")
    await live_catalog.set_delta_token("sharepoint://legal", "token-2")

    import asyncpg

    pool = await asyncpg.create_pool(dsn=PG_DSN, min_size=1, max_size=2)
    reconnected = PostgresContractCatalog(pool=pool, tenant_id="troc", schema=live_catalog.schema, now=frozen_clock)
    try:
        assert await reconnected.get_delta_token("sharepoint://legal") == "token-2"
    finally:
        await pool.close()


@requires_pg
@pytest.mark.asyncio
async def test_live_source_item_identity_rename_and_tombstone(live_catalog):
    item = SourceItem(
        source="sharepoint://legal",
        drive_id="drive-1",
        item_id="item-1",
        current_uri="sharepoint://legal/acme-msa.pdf",
        name="acme-msa.pdf",
        contract_id="acme-msa",
        sha256="sha-acme-msa",
    )
    await live_catalog.upsert_source_item(item)
    await live_catalog.upsert_source_item(
        item.model_copy(
            update={
                "current_uri": "sharepoint://legal/renamed.pdf",
                "name": "renamed.pdf",
                "contract_id": None,
            }
        )
    )

    stored = await live_catalog.get_source_item("drive-1", "item-1")
    assert stored.current_uri.endswith("renamed.pdf")
    assert stored.contract_id == "acme-msa", "a rename must not lose the card link"
    assert stored.deleted is False

    await live_catalog.upsert_source_item(stored.model_copy(update={"deleted": True}))
    assert (await live_catalog.get_source_item("drive-1", "item-1")).deleted is True
    assert len(await live_catalog.list_source_items("sharepoint://legal")) == 1
    assert await live_catalog.list_source_items("onedrive://other") == []


# --------------------------------------------------------------------------
# Live: judgements
# --------------------------------------------------------------------------


@requires_pg
@pytest.mark.asyncio
async def test_live_judgement_history_including_none_and_force(live_catalog):
    first = RelationJudgement(
        judgement_id="j1",
        source_contract_id="acme-msa",
        target_contract_id="zeta-nda",
        outcome="none",
        source_sha256="sha-1",
        target_sha256="sha-2",
        rationale="no overlap",
        model="test-model",
        judged_at=FROZEN_NOW,
    )
    await live_catalog.record_judgement(first)
    # --force records a NEW judgement instead of rewriting the old row.
    await live_catalog.record_judgement(
        first.model_copy(update={"judgement_id": "j2", "outcome": "conflicts_with", "confidence": 0.8})
    )

    history = await live_catalog.judgements_for("acme-msa")
    assert [judgement.judgement_id for judgement in history] == ["j1", "j2"]
    assert [judgement.outcome for judgement in history] == ["none", "conflicts_with"]
    assert history[1].confidence == pytest.approx(0.8)
    assert await live_catalog.judgements_for("zeta-nda") == history


@requires_pg
@pytest.mark.asyncio
async def test_live_relations_are_replaced_and_invalidated_on_source_change(live_catalog):
    await live_catalog.record_judgement(
        RelationJudgement(
            judgement_id="j1",
            source_contract_id="acme-msa",
            target_contract_id="zeta-nda",
            outcome="conflicts_with",
            source_sha256="sha-1",
            target_sha256="sha-2",
            judged_at=FROZEN_NOW,
        )
    )
    await live_catalog.replace_relations(
        "acme-msa",
        [
            ContractRelation(
                source_contract_id="acme-msa",
                target_contract_id="zeta-nda",
                kind="conflicts_with",
                confidence=0.9,
                judged_at=FROZEN_NOW,
            )
        ],
    )
    assert len(await live_catalog.active_relations("acme-msa")) == 1
    assert len(await live_catalog.active_relations()) == 1

    await live_catalog.replace_relations("acme-msa", [])
    assert await live_catalog.active_relations("acme-msa") == []

    await live_catalog.replace_relations(
        "acme-msa",
        [
            ContractRelation(
                source_contract_id="acme-msa",
                target_contract_id="zeta-nda",
                kind="conflicts_with",
                judged_at=FROZEN_NOW,
            )
        ],
    )
    invalidated = await live_catalog.invalidate_relations("acme-msa", source_sha256="sha-new")
    assert invalidated == 1
    assert await live_catalog.active_relations("acme-msa") == []
    assert [j.active for j in await live_catalog.judgements_for("acme-msa")] == [False]

    # An unchanged hash invalidates nothing.
    assert await live_catalog.invalidate_relations("acme-msa", source_sha256="sha-new") == 0


# --------------------------------------------------------------------------
# Live: durable outbox
# --------------------------------------------------------------------------


@requires_pg
@pytest.mark.asyncio
async def test_live_outbox_claim_receipt_and_retry_cycle(live_catalog):
    await live_catalog.upsert(make_card("acme-msa"))

    claimed = await live_catalog.claim_publication(target="temporal")
    assert len(claimed) == 1
    assert claimed[0].state == "in_flight"
    assert claimed[0].attempts == 1
    assert claimed[0].payload["contract_id"] == "acme-msa"
    # In-flight work is not claimable again.
    assert await live_catalog.claim_publication(target="temporal") == []

    failed = await live_catalog.fail_publication(claimed[0], error="connection reset")
    assert failed.state == "failed"
    assert failed.last_error == "connection reset"

    retried = await live_catalog.claim_publication(target="temporal")
    assert retried[0].attempts == 2
    done = await live_catalog.complete_publication(retried[0], receipt="commit-123")
    assert done.state == "published"
    assert done.receipt == "commit-123"
    assert await live_catalog.pending_publications(target="temporal") == []
    assert len(await live_catalog.pending_publications(target="ontology")) == 1


@requires_pg
@pytest.mark.asyncio
async def test_live_outbox_rows_are_idempotent_and_payload_is_immutable(live_catalog):
    record = PublicationRecord(
        tenant_id="troc",
        contract_id="acme-msa",
        version_n=1,
        revision=1,
        target="ontology",
        run_id="acme-msa:1:1",
        payload={"original": True},
        created_at=FROZEN_NOW,
    )
    first = await live_catalog.enqueue_publication(record)
    second = await live_catalog.enqueue_publication(
        record.model_copy(update={"payload": {"tampered": True}, "run_id": "other"})
    )
    assert first.payload == {"original": True}
    assert second.payload == {"original": True}
    assert second.run_id == "acme-msa:1:1"
    assert len(await live_catalog.pending_publications(target="ontology")) == 1


@requires_pg
@pytest.mark.asyncio
async def test_live_outbox_receipts_survive_reconnect(live_catalog):
    await live_catalog.upsert(make_card("acme-msa"))
    claimed = await live_catalog.claim_publication(target="ontology")
    await live_catalog.complete_publication(claimed[0], receipt="commit-abc")

    import asyncpg

    pool = await asyncpg.create_pool(dsn=PG_DSN, min_size=1, max_size=2)
    reconnected = PostgresContractCatalog(pool=pool, tenant_id="troc", schema=live_catalog.schema, now=frozen_clock)
    try:
        assert await reconnected.pending_publications(target="ontology") == []
        assert await reconnected.claim_publication(target="ontology") == []
    finally:
        await pool.close()


@requires_pg
@pytest.mark.asyncio
async def test_live_administration_is_tenant_isolated():
    import asyncpg

    pool = await asyncpg.create_pool(dsn=PG_DSN, min_size=1, max_size=4)
    schema_a = f"contracts_adm_a_{uuid.uuid4().hex[:8]}"
    schema_b = f"contracts_adm_b_{uuid.uuid4().hex[:8]}"
    tenant_a = PostgresContractCatalog(pool=pool, tenant_id="a", schema=schema_a, now=frozen_clock)
    tenant_b = PostgresContractCatalog(pool=pool, tenant_id="b", schema=schema_b, now=frozen_clock)
    try:
        await tenant_a.setup()
        await tenant_b.setup()

        await tenant_a.record_answer(make_answer())
        await tenant_a.retire_answer("ans-1", user="bob@troc", reason="wrong clause")
        await tenant_a.add_party_alias("acme inc", "acme-1", user="bob@troc")
        await tenant_a.set_delta_token("sharepoint://legal", "token-a")

        assert await tenant_b.get_answer("ans-1") is None
        assert await tenant_b.retired_citations() == set()
        assert await tenant_b.resolve_party("acme inc") is None
        assert await tenant_b.get_delta_token("sharepoint://legal") is None
    finally:
        async with pool.acquire() as conn:
            await conn.execute(f"DROP SCHEMA IF EXISTS {schema_a} CASCADE")
            await conn.execute(f"DROP SCHEMA IF EXISTS {schema_b} CASCADE")
        await pool.close()


@requires_pg
@pytest.mark.asyncio
async def test_retraction_has_a_new_snapshot_and_tombstone_outbox(live_catalog):
    await live_catalog.upsert(make_card("retracted"))
    for record in await live_catalog.claim_publication(target="temporal", limit=10):
        await live_catalog.complete_publication(record, receipt="initial")
    await live_catalog.remove("retracted")
    history = await live_catalog.versions("retracted")
    assert [version.revision for version in history] == [1, 2]
    assert history[0].card_snapshot["active"] is True
    assert history[1].card_snapshot["active"] is False
    pending = await live_catalog.pending_publications(target="temporal")
    assert len(pending) == 1
    assert pending[0].revision == 2 and pending[0].payload["tombstone"] is True
    await live_catalog.remove("retracted")
    assert len(await live_catalog.versions("retracted")) == 2


@requires_pg
@pytest.mark.asyncio
async def test_outbox_reads_and_claims_are_bound_to_catalog_tenant(live_catalog):
    from parrot.knowledge.contracts.catalog import CatalogError

    await live_catalog.upsert(make_card("local"))
    own = (await live_catalog.pending_publications(target="temporal"))[0]
    foreign = own.model_copy(update={"tenant_id": "other"})
    with pytest.raises(CatalogError, match="tenant"):
        await live_catalog.enqueue_publication(foreign)
    with pytest.raises(CatalogError, match="tenant"):
        await live_catalog.complete_publication(foreign, receipt="bad")
    # Seed a foreign row directly, bypassing the public tenant guard.
    async with await live_catalog._connection() as conn:
        await conn.execute(
            f"INSERT INTO {live_catalog.schema}.publication_outbox "
            "(tenant_id, contract_id, version_n, revision, target, run_id, payload, state, created_at) "
            "VALUES ('other', 'foreign', 1, 1, 'temporal', 'foreign', '{}'::jsonb, 'pending', now())"
        )
    assert {record.tenant_id for record in await live_catalog.pending_publications()} == {"troc"}
    assert {record.tenant_id for record in await live_catalog.claim_publication(target="temporal", limit=10)} == {
        "troc"
    }
