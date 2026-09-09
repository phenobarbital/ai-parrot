"""Postgres catalog schema and transaction tests (TASK-3027).

Live tests require an **explicit** ``GRAPHINDEX_PG_DSN``: this feature
deliberately does not fall back to ``parrot.conf.default_dsn``, so an
absent DSN skips the live suite only — it never silently targets another
database, and a skipped suite is not live acceptance.

The offline tests always run: they assert the DDL shape, identifier
validation, pool ownership and the "no default DSN" rule without a server.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from datetime import date, datetime, timezone
from typing import AsyncIterator, Optional

import pytest

from parrot.knowledge.contracts.catalog import (
    CatalogConflictError,
    DuplicateSourceError,
    UnknownContractError,
)
from parrot.knowledge.contracts.catalog_postgres import (
    CONTRACTS_DDL,
    PostgresContractCatalog,
)
from parrot.knowledge.contracts.models import (
    ContractCard,
    ContractVersion,
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


def make_card(contract_id: str = "acme-msa", **overrides) -> ContractCard:
    """Build a synthetic card for catalog tests."""
    payload = {
        "contract_id": contract_id,
        "title": f"{contract_id} master services agreement",
        "summary": "Security and compliance obligations for the ACME account.",
        "topics": ["security", "compliance"],
        "contract_type": "msa",
        "status": "active",
        "source_uri": f"sharepoint://legal/{contract_id}.pdf",
        "source_sha256": f"sha-{contract_id}",
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
        "field_provenance": {
            "term.effective_date": FieldProvenance(
                origin="llm", node_id="0002", quote="effective as of January 1, 2026", confidence=0.9
            )
        },
        "added_at": FROZEN_NOW,
        "updated_at": FROZEN_NOW,
    }
    payload.update(overrides)
    return ContractCard(**payload)


def make_obligation(contract_id: str = "acme-msa", suffix: str = "1", **overrides) -> Obligation:
    """Build a synthetic obligation belonging to ``contract_id``."""
    payload = {
        "obligation_id": f"{contract_id}-ob-{suffix}",
        "contract_id": contract_id,
        "kind": "compliance",
        "obligor": "counterparty",
        "text": "Vendor shall maintain SOC 2 Type II certification.",
        "node_id": "0007",
        "page": 12,
        "standard_id": "soc2",
    }
    payload.update(overrides)
    return Obligation(**payload)


# --------------------------------------------------------------------------
# Offline: DDL shape, configuration and pool ownership
# --------------------------------------------------------------------------


def test_ddl_creates_every_table_from_the_spec():
    rendered = "\n".join(statement.format(schema="t") for statement in CONTRACTS_DDL)
    for table in (
        "t.contracts",
        "t.obligations",
        "t.contract_versions",
        "t.party_aliases",
        "t.contract_answers",
        "t.source_delta_tokens",
        "t.source_items",
        "t.relation_judgements",
        "t.contract_relations",
        "t.publication_outbox",
    ):
        assert f"CREATE TABLE IF NOT EXISTS {table} " in rendered.replace("\n", " ").replace(
            "  ", " "
        ) or f"CREATE TABLE IF NOT EXISTS {table}" in rendered


def test_ddl_is_idempotent_by_construction():
    for statement in CONTRACTS_DDL:
        head = statement.strip().split("\n")[0].strip()
        assert "IF NOT EXISTS" in head, head


def test_ddl_declares_english_fts_and_typed_indexes():
    rendered = " ".join(statement.format(schema="t") for statement in CONTRACTS_DDL)
    assert "to_tsvector(\n                'english'" in "\n".join(CONTRACTS_DDL)
    assert "USING GIN (search_vector)" in rendered
    assert "contracts_source_uri_key" in rendered
    assert "contracts_source_sha_key" in rendered
    for index in (
        "contracts_status_idx",
        "contracts_verification_idx",
        "contracts_expiration_idx",
        "contracts_notice_idx",
        "obligations_due_idx",
    ):
        assert index in rendered


def test_outbox_and_version_keys_are_durable():
    rendered = " ".join(
        " ".join(statement.split()) for statement in (s.format(schema="t") for s in CONTRACTS_DDL)
    )
    assert "PRIMARY KEY (tenant_id, contract_id, version_n, revision, target)" in rendered
    assert "PRIMARY KEY (contract_id, version_n, revision)" in rendered


def test_a_dsn_or_pool_is_mandatory_no_default_fallback():
    with pytest.raises(ValueError, match="no default DSN fallback"):
        PostgresContractCatalog(tenant_id="troc")


@pytest.mark.parametrize("schema", ["public; drop table x", "Contracts", "3vil", ""])
def test_invalid_schema_configuration_is_rejected(schema):
    with pytest.raises(ValueError, match="catalog schema"):
        PostgresContractCatalog(dsn="postgresql://x/y", tenant_id="troc", schema=schema)


def test_tenant_binding_is_construction_only():
    catalog = PostgresContractCatalog(
        dsn="postgresql://x/y", tenant_id="troc", schema="contracts_troc"
    )
    assert catalog.tenant_id == "troc"
    assert catalog.schema == "contracts_troc"


def test_sql_never_interpolates_anything_but_the_validated_schema():
    """Every f-string substitution in the backend is the validated schema.

    User- and model-supplied values must always be bound parameters, so the
    only expression allowed inside an interpolated SQL literal is
    ``self.schema`` (already validated as a plain SQL identifier).
    """
    import ast
    import inspect

    import parrot.knowledge.contracts.catalog_postgres as module

    keywords = ("SELECT", "INSERT", "UPDATE", "DELETE", "CREATE", "DROP", "FROM")
    tree = ast.parse(inspect.getsource(module))
    sql_strings = 0
    substitutions: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.JoinedStr):
            continue
        literal = " ".join(
            part.value for part in node.values if isinstance(part, ast.Constant)
        ).upper()
        if not any(keyword in literal for keyword in keywords):
            continue
        sql_strings += 1
        substitutions.update(
            ast.unparse(part.value)
            for part in node.values
            if isinstance(part, ast.FormattedValue)
        )
    assert sql_strings > 10, "expected the backend to build SQL with f-strings"
    assert substitutions == {"self.schema"}, substitutions


def test_ddl_only_formats_the_schema_placeholder():
    for statement in CONTRACTS_DDL:
        rendered = statement.format(schema="t")
        assert "{" not in rendered.replace("{}", ""), statement


@pytest.mark.asyncio
async def test_close_does_not_close_an_injected_pool():
    class FakePool:
        def __init__(self) -> None:
            self.closed = False

        async def close(self) -> None:
            self.closed = True

    pool = FakePool()
    catalog = PostgresContractCatalog(pool=pool, tenant_id="troc")  # type: ignore[arg-type]
    await catalog.close()
    assert pool.closed is False


@pytest.mark.asyncio
async def test_missing_asyncpg_raises_an_actionable_error(monkeypatch):
    import builtins

    catalog = PostgresContractCatalog(dsn="postgresql://x/y", tenant_id="troc")
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "asyncpg":
            raise ImportError("no asyncpg")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    with pytest.raises(RuntimeError, match="graphindex-postgres"):
        await catalog._ensure_pool()


# --------------------------------------------------------------------------
# Live Postgres
# --------------------------------------------------------------------------


@pytest.fixture()
async def live_catalog() -> AsyncIterator[PostgresContractCatalog]:
    """A catalog bound to a fresh temporary schema, dropped afterwards."""
    import asyncpg

    schema = f"contracts_t_{uuid.uuid4().hex[:8]}"
    pool = await asyncpg.create_pool(dsn=PG_DSN, min_size=1, max_size=4)
    catalog = PostgresContractCatalog(
        pool=pool, tenant_id="troc", schema=schema, now=frozen_clock
    )
    await catalog.setup()
    try:
        yield catalog
    finally:
        async with pool.acquire() as conn:
            await conn.execute(f"DROP SCHEMA IF EXISTS {schema} CASCADE")
        await pool.close()


@requires_pg
@pytest.mark.asyncio
async def test_live_repeated_ddl_is_safe(live_catalog):
    await live_catalog.setup()
    await live_catalog.setup()
    assert await live_catalog.taken_slugs() == set()


@requires_pg
@pytest.mark.asyncio
async def test_live_upsert_writes_card_obligations_version_and_outbox(live_catalog):
    card = make_card(obligations=[make_obligation()])
    result = await live_catalog.upsert(card)

    assert result.created is True
    assert result.revision == 1
    assert {record.target for record in result.queued} == {"ontology", "temporal"}

    stored = await live_catalog.get("acme-msa")
    assert stored.title == card.title
    assert stored.revision == 1
    assert stored.term.effective_date == date(2026, 1, 1)
    assert len(await live_catalog.obligations_for("acme-msa")) == 1
    assert len(await live_catalog.versions("acme-msa")) == 1
    assert await live_catalog.find_by_sha("sha-acme-msa") is not None
    assert await live_catalog.find_by_source_uri(card.source_uri) is not None
    assert await live_catalog.taken_slugs() == {"acme-msa"}


@requires_pg
@pytest.mark.asyncio
async def test_live_injected_failure_rolls_back_every_table(live_catalog, monkeypatch):
    await live_catalog.upsert(make_card(obligations=[make_obligation()]))
    before_versions = await live_catalog.versions("acme-msa")

    bad = make_card(
        obligations=[
            make_obligation(suffix="2"),
            make_obligation(suffix="2"),  # duplicate PK -> failure mid-transaction
        ]
    )
    with pytest.raises(Exception):
        await live_catalog.upsert(bad, expected_revision=1)

    stored = await live_catalog.get("acme-msa")
    assert stored.revision == 1, "the failed write must not advance the revision"
    obligations = await live_catalog.obligations_for("acme-msa")
    assert [ob.obligation_id for ob in obligations] == ["acme-msa-ob-1"]
    assert await live_catalog.versions("acme-msa") == before_versions


@requires_pg
@pytest.mark.asyncio
async def test_live_stale_revision_is_rejected(live_catalog):
    await live_catalog.upsert(make_card())
    stored = await live_catalog.get("acme-msa")

    await live_catalog.upsert(
        stored.model_copy(update={"summary": "verified by bob"}), expected_revision=1
    )
    with pytest.raises(CatalogConflictError):
        await live_catalog.upsert(
            stored.model_copy(update={"summary": "refresh overwrote"}), expected_revision=1
        )
    assert (await live_catalog.get("acme-msa")).summary == "verified by bob"


@requires_pg
@pytest.mark.asyncio
async def test_live_concurrent_verify_and_refresh_keep_one_writer(live_catalog):
    await live_catalog.upsert(make_card())
    stored = await live_catalog.get("acme-msa")

    results = await asyncio.gather(
        live_catalog.upsert(stored.model_copy(update={"summary": "verify"}), expected_revision=1),
        live_catalog.upsert(stored.model_copy(update={"summary": "refresh"}), expected_revision=1),
        return_exceptions=True,
    )
    conflicts = [item for item in results if isinstance(item, CatalogConflictError)]
    successes = [item for item in results if not isinstance(item, Exception)]
    assert len(successes) == 1 and len(conflicts) == 1
    assert (await live_catalog.get("acme-msa")).revision == 2


@requires_pg
@pytest.mark.asyncio
async def test_live_duplicate_source_is_reported_without_data_loss(live_catalog):
    await live_catalog.upsert(make_card("acme-msa"))

    same_content = make_card("acme-msa-copy", source_uri="sharepoint://legal/copy.pdf")
    same_content = same_content.model_copy(update={"source_sha256": "sha-acme-msa"})
    with pytest.raises(DuplicateSourceError) as excinfo:
        await live_catalog.upsert(same_content)
    assert excinfo.value.contract_id == "acme-msa"

    same_uri = make_card("acme-msa-2", source_uri="sharepoint://legal/acme-msa.pdf")
    with pytest.raises(DuplicateSourceError):
        await live_catalog.upsert(same_uri)

    assert await live_catalog.taken_slugs() == {"acme-msa"}
    assert (await live_catalog.get("acme-msa")).revision == 1


@requires_pg
@pytest.mark.asyncio
async def test_live_history_keeps_effective_intervals_and_admin_revisions(live_catalog):
    card = make_card()
    await live_catalog.upsert(
        card,
        version=ContractVersion(
            n=1,
            valid_from=date(2026, 1, 1),
            valid_to=None,
            kind="original",
            source_sha256="sha-acme-msa",
        ),
    )
    stored = await live_catalog.get("acme-msa")
    # Administrative correction: new recorded revision, no new effective interval.
    await live_catalog.upsert(
        stored.model_copy(update={"department": "legal"}), expected_revision=1
    )

    history = await live_catalog.versions("acme-msa")
    assert [(version.n, version.revision) for version in history] == [(1, 1), (1, 2)]
    assert history[0].valid_from == date(2026, 1, 1)
    assert history[1].valid_from is None, "corrections must not fabricate an effective date"
    assert all(not version.card_snapshot.get("versions") for version in history)


@requires_pg
@pytest.mark.asyncio
async def test_live_remove_retracts_without_destroying_history(live_catalog):
    await live_catalog.upsert(make_card(obligations=[make_obligation()]))
    await live_catalog.remove("acme-msa")

    stored = await live_catalog.get("acme-msa")
    assert stored.active is False
    assert all(not ob.active for ob in await live_catalog.obligations_for("acme-msa"))
    assert await live_catalog.versions("acme-msa"), "history is retained"

    with pytest.raises(UnknownContractError):
        await live_catalog.remove("ghost")


@requires_pg
@pytest.mark.asyncio
async def test_live_two_schemas_cannot_leak():
    import asyncpg

    pool = await asyncpg.create_pool(dsn=PG_DSN, min_size=1, max_size=4)
    schema_a = f"contracts_a_{uuid.uuid4().hex[:8]}"
    schema_b = f"contracts_b_{uuid.uuid4().hex[:8]}"
    tenant_a = PostgresContractCatalog(pool=pool, tenant_id="a", schema=schema_a, now=frozen_clock)
    tenant_b = PostgresContractCatalog(pool=pool, tenant_id="b", schema=schema_b, now=frozen_clock)
    try:
        await tenant_a.setup()
        await tenant_b.setup()
        # Both tenants deliberately reuse the same slug and node ids.
        await tenant_a.upsert(make_card("shared-slug"))
        await tenant_b.upsert(make_card("shared-slug", summary="tenant b copy"))

        assert (await tenant_a.get("shared-slug")).summary != "tenant b copy"
        assert (await tenant_b.get("shared-slug")).summary == "tenant b copy"
        assert await tenant_a.taken_slugs() == {"shared-slug"}
    finally:
        async with pool.acquire() as conn:
            await conn.execute(f"DROP SCHEMA IF EXISTS {schema_a} CASCADE")
            await conn.execute(f"DROP SCHEMA IF EXISTS {schema_b} CASCADE")
        await pool.close()
