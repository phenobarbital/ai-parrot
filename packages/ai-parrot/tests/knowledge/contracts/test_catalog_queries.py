"""Postgres catalog query tests — FTS, windows and queue (TASK-3028).

Live tests require an explicit ``GRAPHINDEX_PG_DSN``; there is no default
DSN fallback and a skipped suite is not live acceptance.
"""

from __future__ import annotations

import os
import uuid
from datetime import date, datetime, timezone
from typing import AsyncIterator, Optional

import pytest

from parrot.knowledge.contracts.catalog import ObligationWindow
from parrot.knowledge.contracts.catalog_postgres import (
    MAX_SEARCH_TOP_K,
    PostgresContractCatalog,
)
from parrot.knowledge.contracts.models import (
    ContractCard,
    FieldProvenance,
    Obligation,
    Party,
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
    """Build a synthetic card for query tests."""
    payload = {
        "contract_id": contract_id,
        "title": f"{contract_id} agreement",
        "contract_type": "msa",
        "status": "active",
        "source_uri": f"sharepoint://legal/{contract_id}.pdf",
        "source_sha256": f"sha-{contract_id}",
        "source_format": "pdf",
        "parties": [Party(party_id="party-acme", name="ACME Inc.", role="customer")],
        "term": TermSpec(),
        "added_at": FROZEN_NOW,
        "updated_at": FROZEN_NOW,
    }
    payload.update(overrides)
    return ContractCard(**payload)


@pytest.fixture()
async def live_catalog() -> AsyncIterator[PostgresContractCatalog]:
    """A catalog bound to a fresh temporary schema, dropped afterwards."""
    import asyncpg

    schema = f"contracts_q_{uuid.uuid4().hex[:8]}"
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


def test_query_sql_uses_english_configuration_and_bound_values():
    import inspect

    import parrot.knowledge.contracts.catalog_postgres as module

    source = inspect.getsource(module.PostgresContractCatalog.search)
    assert "plainto_tsquery('english'" in source
    assert "ts_rank(" in source
    assert "$1" in source and "$2" in source


@pytest.mark.asyncio
async def test_blank_search_matches_nothing_without_touching_the_database():
    catalog = PostgresContractCatalog(dsn="postgresql://unused/db", tenant_id="troc")
    assert await catalog.search("   ") == []
    assert await catalog.search("") == []


@pytest.mark.asyncio
async def test_inverted_and_unsupported_windows_are_rejected():
    catalog = PostgresContractCatalog(dsn="postgresql://unused/db", tenant_id="troc")
    with pytest.raises(ValueError, match="unsupported expiring key"):
        await catalog.expiring(until=date(2026, 12, 1), key="added_at")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="must not be after"):
        await catalog.expiring(until=date(2026, 1, 1), since=date(2026, 2, 1))


def test_obligation_window_limit_is_bounded_by_the_model():
    with pytest.raises(Exception):
        ObligationWindow(until=date(2026, 12, 31), limit=10_000)


# --------------------------------------------------------------------------
# Live: search
# --------------------------------------------------------------------------


@requires_pg
@pytest.mark.asyncio
async def test_live_english_search_ranks_and_bounds(live_catalog):
    await live_catalog.upsert(
        make_card(
            "acme-msa",
            title="ACME master services agreement",
            summary="Security obligations, security reviews and security audits.",
            topics=["security", "compliance"],
        )
    )
    await live_catalog.upsert(make_card("zeta-nda", title="Zeta mutual NDA", summary="Confidentiality only."))

    hits = await live_catalog.search("security")
    assert [hit.card.contract_id for hit in hits] == ["acme-msa"]
    assert hits[0].rank > 0

    # English stemming: "obligation" matches "obligations".
    assert [hit.card.contract_id for hit in await live_catalog.search("obligation")] == ["acme-msa"]

    assert len(await live_catalog.search("agreement OR NDA", top_k=1)) <= 1


@requires_pg
@pytest.mark.asyncio
async def test_live_search_top_k_is_bounded_and_positive(live_catalog):
    for index in range(3):
        await live_catalog.upsert(make_card(f"contract-{index}", summary="shared security language"))

    assert len(await live_catalog.search("security", top_k=0)) == 1
    assert len(await live_catalog.search("security", top_k=10_000)) == 3
    assert MAX_SEARCH_TOP_K == 50


@requires_pg
@pytest.mark.asyncio
async def test_live_search_treats_injection_payloads_as_terms(live_catalog):
    await live_catalog.upsert(make_card("acme-msa", summary="security"))

    payload = "'; DROP SCHEMA public CASCADE; --"
    assert await live_catalog.search(payload) == []
    # The catalog is intact.
    assert await live_catalog.get("acme-msa") is not None
    assert [hit.card.contract_id for hit in await live_catalog.search("security")] == ["acme-msa"]


@requires_pg
@pytest.mark.asyncio
async def test_live_search_skips_retracted_cards(live_catalog):
    await live_catalog.upsert(make_card("acme-msa", summary="security"))
    await live_catalog.remove("acme-msa")
    assert await live_catalog.search("security") == []


# --------------------------------------------------------------------------
# Live: filters and windows
# --------------------------------------------------------------------------


@requires_pg
@pytest.mark.asyncio
async def test_live_list_cards_filter_combinations(live_catalog):
    await live_catalog.upsert(make_card("active-extracted", status="active"))
    await live_catalog.upsert(
        make_card(
            "expired-verified",
            status="expired",
            verification="verified",
            verified_by="bob@troc",
            verified_at=FROZEN_NOW,
        )
    )

    assert [card.contract_id for card in await live_catalog.list_cards()] == [
        "active-extracted",
        "expired-verified",
    ]
    assert [card.contract_id for card in await live_catalog.list_cards(status="expired")] == ["expired-verified"]
    assert [card.contract_id for card in await live_catalog.list_cards(verification="extracted")] == [
        "active-extracted"
    ]
    assert await live_catalog.list_cards(status="active", verification="verified") == []

    await live_catalog.remove("active-extracted")
    assert [card.contract_id for card in await live_catalog.list_cards()] == ["expired-verified"]
    assert len(await live_catalog.list_cards(active_only=False)) == 2


@requires_pg
@pytest.mark.asyncio
async def test_live_expiring_boundaries_null_dates_and_fallback(live_catalog):
    await live_catalog.upsert(
        make_card(
            "with-notice",
            term=TermSpec(
                expiration_date=date(2026, 12, 31),
                notice_days=60,
                notice_deadline=date(2026, 11, 1),
            ),
        )
    )
    await live_catalog.upsert(make_card("no-notice", term=TermSpec(expiration_date=date(2026, 11, 1))))
    await live_catalog.upsert(make_card("no-dates", term=TermSpec()))

    # Exact boundary is inclusive on both ends.
    on_boundary = await live_catalog.expiring(until=date(2026, 11, 1))
    assert [card.contract_id for card in on_boundary] == ["no-notice", "with-notice"]

    assert await live_catalog.expiring(until=date(2026, 10, 31)) == []
    assert [
        card.contract_id for card in await live_catalog.expiring(until=date(2026, 11, 1), since=date(2026, 11, 1))
    ] == ["no-notice", "with-notice"]

    # expiration_date key ignores the notice deadline.
    by_expiration = await live_catalog.expiring(until=date(2026, 11, 1), key="expiration_date")
    assert [card.contract_id for card in by_expiration] == ["no-notice"]

    assert "no-dates" not in {card.contract_id for card in await live_catalog.expiring(until=date(2099, 1, 1))}


@requires_pg
@pytest.mark.asyncio
async def test_live_expiring_skips_inactive_and_non_active_status(live_catalog):
    await live_catalog.upsert(
        make_card(
            "terminated",
            status="terminated",
            term=TermSpec(expiration_date=date(2026, 11, 1)),
        )
    )
    await live_catalog.upsert(make_card("retracted", term=TermSpec(expiration_date=date(2026, 11, 1))))
    await live_catalog.remove("retracted")

    assert await live_catalog.expiring(until=date(2026, 12, 31)) == []


# --------------------------------------------------------------------------
# Live: verification queue
# --------------------------------------------------------------------------


@requires_pg
@pytest.mark.asyncio
async def test_live_verification_queue_priority_and_stable_ties(live_catalog):
    await live_catalog.upsert(
        make_card(
            "z-missing",
            field_provenance={"title": FieldProvenance(origin="llm", node_id="0001")},
        )
    )
    await live_catalog.upsert(
        make_card(
            "a-missing",
            field_provenance={"term.effective_date": FieldProvenance(origin="llm", node_id="0002", quote="  ")},
        )
    )
    await live_catalog.upsert(
        make_card(
            "m-low",
            field_provenance={"title": FieldProvenance(origin="llm", node_id="0001", quote="ACME", confidence=0.4)},
        )
    )
    await live_catalog.upsert(make_card("s-stale", stale_fields=["term.expiration_date"]))
    await live_catalog.upsert(
        make_card(
            "clean-verified",
            verification="verified",
            verified_by="bob@troc",
            verified_at=FROZEN_NOW,
        )
    )

    queue = await live_catalog.verification_queue()
    assert [entry.card.contract_id for entry in queue] == [
        "a-missing",
        "z-missing",
        "m-low",
        "s-stale",
    ]
    assert [entry.reason for entry in queue] == [
        "missing_evidence",
        "missing_evidence",
        "low_confidence",
        "stale",
    ]
    assert queue[0].fields == ["term.effective_date"]
    assert queue[2].fields == ["title"]
    assert queue[3].fields == ["term.expiration_date"]

    assert len(await live_catalog.verification_queue(limit=2)) == 2


@requires_pg
@pytest.mark.asyncio
async def test_live_verification_queue_skips_verified_fields_and_cards(live_catalog):
    await live_catalog.upsert(
        make_card(
            "verified-field",
            field_provenance={
                "title": FieldProvenance(
                    origin="manual",
                    verification="verified",
                    verified_by="bob@troc",
                    verified_at=FROZEN_NOW,
                )
            },
        )
    )
    assert await live_catalog.verification_queue() == []


# --------------------------------------------------------------------------
# Live: obligation windows
# --------------------------------------------------------------------------


@requires_pg
@pytest.mark.asyncio
async def test_live_obligation_window_filters_and_ordering(live_catalog):
    await live_catalog.upsert(
        make_card(
            "acme-msa",
            obligations=[
                Obligation(
                    obligation_id="ob-soon",
                    contract_id="acme-msa",
                    kind="reporting",
                    text="quarterly report",
                    node_id="0003",
                    due_date=date(2026, 10, 1),
                ),
                Obligation(
                    obligation_id="ob-later",
                    contract_id="acme-msa",
                    kind="reporting",
                    text="annual report",
                    node_id="0004",
                    due_date=date(2027, 3, 1),
                ),
                Obligation(
                    obligation_id="ob-standard",
                    contract_id="acme-msa",
                    kind="compliance",
                    text="maintain SOC 2",
                    node_id="0005",
                    standard_id="soc2",
                    due_date=date(2026, 11, 15),
                ),
                Obligation(
                    obligation_id="ob-recurring",
                    contract_id="acme-msa",
                    kind="audit_right",
                    text="annual audit rights",
                    node_id="0006",
                    recurrence="annually",
                ),
            ],
        )
    )

    window = ObligationWindow(until=date(2026, 12, 31))
    due = await live_catalog.obligations_due(window)
    assert [ob.obligation_id for ob in due] == ["ob-soon", "ob-standard", "ob-recurring"]

    assert [
        ob.obligation_id
        for ob in await live_catalog.obligations_due(ObligationWindow(until=date(2026, 12, 31), kinds=["reporting"]))
    ] == ["ob-soon"]

    assert [
        ob.obligation_id
        for ob in await live_catalog.obligations_due(ObligationWindow(until=date(2026, 12, 31), standard_id="soc2"))
    ] == ["ob-standard"]

    assert [
        ob.obligation_id
        for ob in await live_catalog.obligations_due(
            ObligationWindow(until=date(2026, 12, 31), include_recurring=False)
        )
    ] == ["ob-soon", "ob-standard"]

    assert [
        ob.obligation_id
        for ob in await live_catalog.obligations_due(
            ObligationWindow(until=date(2026, 12, 31), since=date(2026, 11, 1))
        )
    ] == ["ob-standard", "ob-recurring"]

    assert len(await live_catalog.obligations_due(ObligationWindow(until=date(2026, 12, 31), limit=1))) == 1


@requires_pg
@pytest.mark.asyncio
async def test_live_obligation_window_skips_retracted_contracts(live_catalog):
    await live_catalog.upsert(
        make_card(
            "acme-msa",
            obligations=[
                Obligation(
                    obligation_id="ob-1",
                    contract_id="acme-msa",
                    text="report",
                    node_id="0003",
                    due_date=date(2026, 10, 1),
                )
            ],
        )
    )
    await live_catalog.remove("acme-msa")
    assert await live_catalog.obligations_due(ObligationWindow(until=date(2026, 12, 31))) == []
