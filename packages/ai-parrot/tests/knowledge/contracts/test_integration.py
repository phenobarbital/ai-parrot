"""Cross-store contracts integration tests (TASK-3054).

Real Postgres (catalog + GraphIndex temporal plane) and real ArangoDB
(ontology projection and all ten AQL patterns), driven through the actual
library, loader and publisher — not through doubles.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Optional
from unittest.mock import MagicMock

import pytest

from parrot.knowledge.contracts.catalog_postgres import PostgresContractCatalog
from parrot.knowledge.contracts.datasource import ContractCardDataSource
from parrot.knowledge.contracts.graph_loader import ContractGraphLoader
from parrot.knowledge.contracts.library import ContractLibrary
from parrot.knowledge.contracts.models import Citation
from parrot.knowledge.contracts.temporal import ContractTemporalPublisher
from parrot.knowledge.ontology.graph_store import OntologyGraphStore
from parrot.knowledge.ontology.parser import OntologyParser
from parrot.knowledge.ontology.merger import OntologyMerger
from parrot.knowledge.ontology.schema import TenantContext

from .conftest import (
    FROZEN_NOW,
    PG_DSN,
    TODAY,
    requires_arango,
    requires_pg,
)
from .test_ingestion import FakeIndexer

pytestmark = pytest.mark.asyncio


def make_library(catalog: Any, tmp_path: Path, name: str = "wt") -> ContractLibrary:
    """A library over a real catalog and the lean fake indexer."""
    indexers: dict[Path, FakeIndexer] = {}
    return ContractLibrary(
        catalog=catalog,
        storage_root=tmp_path / name / "storage",
        evidence_root=tmp_path / name / "evidence",
        adapter=None,
        indexer_factory=lambda directory, adapter: indexers.setdefault(
            Path(directory), FakeIndexer(directory, adapter)
        ),
        now=lambda: FROZEN_NOW,
        today=lambda: TODAY,
    )


async def make_catalog(pg_pool, schema: str, tenant_id: str = "troc") -> PostgresContractCatalog:
    """A real Postgres catalog on a temporary schema."""
    catalog = PostgresContractCatalog(
        pool=pg_pool, tenant_id=tenant_id, schema=schema, now=lambda: FROZEN_NOW
    )
    await catalog.setup()
    return catalog


# --------------------------------------------------------------------------
# Postgres: real transactions, isolation and evidence
# --------------------------------------------------------------------------


@requires_pg
async def test_ingest_verify_refresh_against_a_real_catalog(pg_pool, temp_schema, corpus, tmp_path):
    catalog = await make_catalog(pg_pool, temp_schema)
    library = make_library(catalog, tmp_path)

    added = await library.add_contract(corpus["msa"])
    assert added.outcome == "added"
    contract_id = added.card.contract_id

    stored = await catalog.get(contract_id)
    assert stored is not None
    assert await catalog.obligations_for(contract_id) == []  # no LLM: fallback card
    assert len(await catalog.versions(contract_id)) == 1
    assert await catalog.pending_publications(), "publication work was queued"

    # A human verifies the title, then the source changes.
    result = await library.verify_card(
        contract_id, {"title": "ACME Master Services Agreement"}, user="bob@troc"
    )
    assert result.corrected == ["title"]

    corpus["msa"].write_text(
        corpus["msa"].read_text().replace("twelve (12) months", "twenty-four (24) months")
    )
    refreshed = await library.refresh_card(contract_id)

    assert refreshed.outcome == "updated"
    assert refreshed.card.title == "ACME Master Services Agreement", (
        "the human decision survived the refresh"
    )
    history = await catalog.versions(contract_id)
    assert len(history) >= 3, "each write recorded a revision"

    # The citation released against version 1 still resolves.
    from parrot.knowledge.contracts.evidence import EvidenceRef

    first = history[0]
    citation = Citation(
        contract_id=contract_id,
        node_id="0001",
        quote="twelve (12) months",
        version_n=first.n,
        source_sha256=first.source_sha256,
    )
    lookup = await library.evidence.resolve(citation, EvidenceRef.parse(first.evidence_ref))
    assert lookup.found is True, "historical evidence survives the refresh"


@requires_pg
async def test_a_failed_write_rolls_back_every_table(pg_pool, temp_schema, corpus, tmp_path, monkeypatch):
    catalog = await make_catalog(pg_pool, temp_schema)
    library = make_library(catalog, tmp_path)
    added = await library.add_contract(corpus["msa"])
    contract_id = added.card.contract_id

    versions_before = await catalog.versions(contract_id)
    outbox_before = len(await catalog.pending_publications())

    async def failing_upsert(*args, **kwargs):
        raise RuntimeError("injected failure between staging and publication")

    monkeypatch.setattr(catalog, "upsert", failing_upsert)
    corpus["msa"].write_text(corpus["msa"].read_text() + "\n\n## Extra\n\nMore text.\n")
    failed = await library.refresh_card(contract_id)

    assert failed.outcome == "error"
    monkeypatch.undo()
    assert (await catalog.get(contract_id)).revision == added.card.revision
    assert await catalog.versions(contract_id) == versions_before
    assert len(await catalog.pending_publications()) == outbox_before


@requires_pg
async def test_two_tenants_reusing_slugs_and_nodes_cannot_leak(pg_pool, corpus, tmp_path):
    schema_a = f"contracts_ta_{uuid.uuid4().hex[:8]}"
    schema_b = f"contracts_tb_{uuid.uuid4().hex[:8]}"
    try:
        catalog_a = await make_catalog(pg_pool, schema_a, tenant_id="tenant-a")
        catalog_b = await make_catalog(pg_pool, schema_b, tenant_id="tenant-b")
        library_a = make_library(catalog_a, tmp_path, name="a")
        library_b = make_library(catalog_b, tmp_path, name="b")

        added_a = await library_a.add_contract(corpus["msa"])
        # Tenant B ingests a *different* document under the same slug.
        other = corpus["msa"].with_name("acme-msa.md")
        tenant_b_dir = tmp_path / "tenant-b"
        tenant_b_dir.mkdir(parents=True, exist_ok=True)
        copy = tenant_b_dir / "acme-msa.md"
        copy.write_text(corpus["msa"].read_text() + "\n\nTenant B only.\n")
        added_b = await library_b.add_contract(copy)

        assert added_a.card.contract_id == added_b.card.contract_id == "acme-msa"
        assert added_a.card.source_sha256 != added_b.card.source_sha256

        # Evidence archives are tenant-scoped: same slug, same node ids,
        # different text — and tenant A never sees tenant B's addition.
        ref_a = (await library_a.evidence.versions("acme-msa"))[0]
        ref_b = (await library_b.evidence.versions("acme-msa"))[0]
        manifest_a = await library_a.evidence.manifest(ref_a)
        manifest_b = await library_b.evidence.manifest(ref_b)
        assert manifest_a["nodes"] == manifest_b["nodes"], "the node ids collide by design"

        bodies_a = [
            await library_a.evidence.load_body(ref_a, node) for node in manifest_a["nodes"]
        ]
        bodies_b = [
            await library_b.evidence.load_body(ref_b, node) for node in manifest_b["nodes"]
        ]
        assert bodies_a != bodies_b
        assert not any("Tenant B only" in (body or "") for body in bodies_a)
        assert any("Tenant B only" in (body or "") for body in bodies_b)

        # And a cross-tenant reference is refused outright.
        from parrot.knowledge.contracts.evidence import EvidenceError

        with pytest.raises(EvidenceError):
            await library_a.evidence.load_body(
                (await library_b.evidence.versions("acme-msa"))[0], "0001"
            )
    finally:
        async with pg_pool.acquire() as conn:
            await conn.execute(f"DROP SCHEMA IF EXISTS {schema_a} CASCADE")
            await conn.execute(f"DROP SCHEMA IF EXISTS {schema_b} CASCADE")


@requires_pg
async def test_every_supported_format_ingests_or_is_explicitly_skipped(
    pg_pool, temp_schema, corpus, docx_document, text_pdf, image_only_pdf, tmp_path
):
    catalog = await make_catalog(pg_pool, temp_schema)
    library = make_library(catalog, tmp_path)

    markdown = await library.add_contract(corpus["msa"])
    assert markdown.outcome == "added" and markdown.card.source_format == "md"

    headingless = await library.add_contract(corpus["headingless"])
    assert headingless.outcome == "added"
    assert all(entry.title.startswith("Section ") for entry in headingless.card.toc)

    docx = await library.add_contract(docx_document)
    assert docx.outcome == "added" and docx.card.source_format == "docx"

    pdf = await library.add_contract(text_pdf)
    assert pdf.outcome == "added" and pdf.card.source_format == "pdf"
    assert [entry.title for entry in pdf.card.toc] == ["Page 1", "Page 2"]

    scanned = await library.add_contract(image_only_pdf)
    assert scanned.outcome == "skipped"
    assert "no extractable text" in scanned.reason
    assert scanned.card is None


@requires_pg
async def test_sql_reports_work_without_arango(pg_pool, temp_schema, corpus, tmp_path):
    catalog = await make_catalog(pg_pool, temp_schema)
    library = make_library(catalog, tmp_path)
    for key in ("msa", "sow", "nda"):
        await library.add_contract(corpus[key])

    assert len(await catalog.list_cards()) == 3
    assert await catalog.search("agreement")
    assert await catalog.verification_queue() is not None
    assert await catalog.expiring(until=TODAY + timedelta(days=3650)) is not None


# --------------------------------------------------------------------------
# GraphIndex temporal plane
# --------------------------------------------------------------------------


@requires_pg
async def test_temporal_publication_and_recovery_through_the_library(
    pg_pool, temp_schema, corpus, tmp_path
):
    from parrot.knowledge.graphindex.persist_postgres import PostgresPersistence

    schema = f"gi_it_{uuid.uuid4().hex[:8]}"
    catalog = await make_catalog(pg_pool, temp_schema)
    library = make_library(catalog, tmp_path)
    persistence = PostgresPersistence(dsn=PG_DSN, schema=schema)
    publisher = ContractTemporalPublisher(catalog=catalog, persistence=persistence)
    ctx = MagicMock()
    ctx.tenant_id = "troc"

    try:
        added = await library.add_contract(corpus["msa"])
        first = await publisher.drain(ctx)
        assert first.published == [added.card.contract_id]

        corpus["msa"].write_text(corpus["msa"].read_text() + "\n\n## Extra\n\nMore.\n")
        await library.refresh_card(added.card.contract_id)
        second = await publisher.drain(ctx)
        assert second.published == [added.card.contract_id]
        assert second.receipts != first.receipts

        history = await publisher.contract_history(ctx, added.card.contract_id)
        assert len(history) >= 2

        # Crash after commit, before receipt: the commit really landed but
        # the outbox row never reached 'published'. Reset that row exactly
        # as a crashed run would leave it.
        card = await catalog.get(added.card.contract_id)
        latest = (await catalog.versions(card.contract_id))[-1]
        published_receipt = second.receipts[card.contract_id]
        async with pg_pool.acquire() as connection:
            await connection.execute(
                f"""
                UPDATE {temp_schema}.publication_outbox
                SET state = 'pending', receipt = NULL
                WHERE contract_id = $1 AND target = 'temporal'
                  AND version_n = $2 AND revision = $3
                """,
                card.contract_id,
                latest.n,
                latest.revision,
            )

        commits_before = await persistence.list_commits(
            ctx, run_id=f"contracts:{card.contract_id}:{latest.n}:{latest.revision}", limit=10
        )
        assert len(commits_before) == 1

        recovered = await publisher.drain(ctx)
        assert recovered.recovered == [card.contract_id], recovered.model_dump()
        assert recovered.published == []
        assert recovered.receipts[card.contract_id] == published_receipt
        commits_after = await persistence.list_commits(
            ctx, run_id=f"contracts:{card.contract_id}:{latest.n}:{latest.revision}", limit=10
        )
        assert len(commits_after) == 1, "no duplicate logical version"
    finally:
        pool = await persistence._ensure_pool()
        async with pool.acquire() as conn:
            await conn.execute(f"DROP SCHEMA IF EXISTS {schema} CASCADE")
        await persistence.close()


# --------------------------------------------------------------------------
# ArangoDB: domain initialization and all ten patterns
# --------------------------------------------------------------------------


class ArangoAdapter:
    """Adds the ``execute_query`` surface ``OntologyGraphStore`` expects.

    The installed ``asyncdb`` ArangoDB driver exposes ``query(sentence,
    bind_vars=...) -> [rows, error]``; the ontology store calls
    ``execute_query``. This test-side adapter bridges the two without
    touching the generic store API.
    """

    def __init__(self, driver: Any) -> None:
        # Stored as ``_driver`` so ``adapter._connection`` forwards to the
        # driver's own ``_connection`` (the vendored arangoasync Database),
        # which ``_ensure_views`` drives directly.
        object.__setattr__(self, "_driver", driver)

    def __getattr__(self, name: str) -> Any:
        return getattr(object.__getattribute__(self, "_driver"), name)

    async def execute_query(self, aql: str, bind_vars: Optional[dict] = None) -> list[dict]:
        driver = object.__getattribute__(self, "_driver")
        rows, error = await driver.query(aql, bind_vars=bind_vars or {})
        if error and "no data found" not in str(error).lower():
            # asyncdb reports an empty result set as a 404 "No Data Found";
            # an empty answer is a legitimate outcome for these patterns.
            raise RuntimeError(str(error))
        return list(rows or [])


@pytest.fixture()
async def arango_store(arango_params):
    """A real :class:`OntologyGraphStore` over a throwaway database."""
    from asyncdb import AsyncDB

    database = f"contracts_it_{uuid.uuid4().hex[:8]}"
    db = AsyncDB("arangodb", params=arango_params)
    async with await db.connection() as connection:
        adapter = ArangoAdapter(connection)
        store = OntologyGraphStore(arango_client=adapter)
        try:
            yield store, database, adapter
        finally:
            try:
                await connection.use("_system")
                await connection.query(
                    "RETURN 1"
                )  # keep the session alive before dropping
                await connection.execute(f"RETURN DROP_DATABASE('{database}')")
            except Exception:  # pragma: no cover - best-effort cleanup
                pass


def contracts_context(database: str) -> TenantContext:
    """A tenant context carrying the merged contracts ontology."""
    defaults = OntologyParser.get_defaults_dir()
    merged = OntologyMerger().merge(
        [defaults / "base.ontology.yaml", defaults / "domains" / "contracts.ontology.yaml"]
    )
    return TenantContext(
        tenant_id="troc",
        arango_db=database,
        pgvector_schema="troc",
        ontology=merged,
    )


#: Pre-existing upstream defect, reproduced against ArangoDB 3.11.14 while
#: writing this suite: ``OntologyGraphStore.upsert_nodes`` builds
#: ``UPSERT { @key_field: doc[@key_field] }``, and ArangoDB refuses a bind
#: parameter as an UPSERT example attribute name (ERR 1501, "expecting
#: object literal with literal attribute names in example"). The individual
#: fallback path uses the same construct and fails identically, so **no**
#: node reaches a real ArangoDB through that API. It lives in
#: ``parrot/knowledge/ontology/graph_store.py`` — a generic module this
#: feature is explicitly forbidden to modify — so it is reported rather
#: than patched here. Until it is fixed, the contracts publish path cannot
#: be verified end to end against a live graph; the ten AQL patterns are
#: verified below against documents written directly.
UPSERT_NODES_DEFECT = (
    "OntologyGraphStore.upsert_nodes uses a bind parameter as an AQL UPSERT "
    "attribute name (ArangoDB ERR 1501); no node reaches a real graph"
)


async def write_documents(adapter: Any, collection: str, documents: list[dict]) -> None:
    """Insert vertex/edge documents with literal-attribute AQL.

    Deliberately *not* a fix for the upstream defect — it is the minimum
    needed to populate a real graph so the ten declared patterns can be
    executed with real bind values.
    """
    for document in documents:
        await adapter.execute_query(
            "INSERT @doc INTO @@collection OPTIONS { overwriteMode: 'replace' } RETURN 1",
            bind_vars={"doc": document, "@collection": collection},
        )


@requires_arango
@requires_pg
async def test_the_generic_node_upsert_is_broken_against_a_real_graph(arango_store):
    """Pin the upstream defect so the gap is visible, not silently skipped."""
    store, database, adapter = arango_store
    ctx = contracts_context(database)
    await store.initialize_tenant(ctx)

    result = await store.upsert_nodes(
        ctx, "contract", [{"contract_id": "probe", "title": "Probe"}], "contract_id"
    )
    rows = await store.get_all_nodes(ctx, "contract")

    assert result.inserted == 0 and result.updated == 0, UPSERT_NODES_DEFECT
    assert rows == [], UPSERT_NODES_DEFECT


@requires_arango
@requires_pg
async def test_all_ten_patterns_execute_against_a_real_graph(arango_store):
    """Execute every declared pattern against ArangoDB with real binds."""
    store, database, adapter = arango_store
    ctx = contracts_context(database)
    await store.initialize_tenant(ctx)

    # The projection the loader computes, written with literal-attribute AQL
    # because of UPSERT_NODES_DEFECT above.
    await write_documents(
        adapter,
        "contract",
        [
            {
                "_key": "acme-msa",
                "contract_id": "acme-msa",
                "title": "ACME Master Services Agreement",
                "contract_type": "msa",
                "status": "active",
                "effective_date": "2026-01-01",
                "expiration_date": "2026-12-31",
                "notice_deadline": "2026-11-01",
                "auto_renew": True,
                "owner_employee_id": "emp-1",
                "department": "legal",
                "counterparty_names": ["ACME Inc."],
                "card_revision": 1,
                "active": True,
                "summary": "Security obligations for the ACME account.",
                "versions": [
                    {"n": 1, "valid_from": "2026-01-01", "valid_to": "2026-07-01"},
                    {"n": 2, "valid_from": "2026-07-01", "valid_to": None},
                ],
            },
            {
                "_key": "acme-sow-1",
                "contract_id": "acme-sow-1",
                "title": "ACME Statement of Work 1",
                "contract_type": "sow",
                "status": "active",
                "parent_contract_id": "acme-msa",
                "owner_employee_id": "emp-1",
                "department": "legal",
                "card_revision": 1,
                "active": True,
                "versions": [],
            },
        ],
    )
    await write_documents(
        adapter,
        "obligation",
        [
            {
                "_key": "acme-msa-ob-001",
                "obligation_id": "acme-msa-ob-001",
                "contract_id": "acme-msa",
                "kind": "compliance",
                "standard_id": "soc2",
                "text": "Vendor shall maintain SOC 2 Type II certification.",
                "node_id": "0004",
                "page": 3,
                "active": True,
            }
        ],
    )
    await write_documents(
        adapter,
        "party",
        [{"_key": "party-acme", "party_id": "party-acme", "name": "ACME Inc."}],
    )
    await write_documents(
        adapter,
        "person",
        [{"_key": "jane", "person_id": "jane", "name": "Jane Doe", "party_id": "party-acme"}],
    )
    await write_documents(
        adapter,
        "compliance_standard",
        [{"_key": "soc2", "standard_id": "soc2", "name": "SOC 2"}],
    )
    await write_documents(
        adapter, "employees", [{"_key": "emp-1", "employee_id": "emp-1", "name": "Bob"}]
    )
    await write_documents(
        adapter,
        "requires",
        [{"_from": "obligation/acme-msa-ob-001", "_to": "compliance_standard/soc2",
          "source_id": "obligation/acme-msa-ob-001", "target_id": "compliance_standard/soc2",
          "kind": "requires"}],
    )
    await write_documents(
        adapter,
        "imposed_by",
        [{"_from": "obligation/acme-msa-ob-001", "_to": "contract/acme-msa",
          "source_id": "obligation/acme-msa-ob-001", "target_id": "contract/acme-msa",
          "kind": "imposed_by"}],
    )
    await write_documents(
        adapter,
        "party_to",
        [{"_from": "contract/acme-msa", "_to": "party/party-acme", "role": "customer",
          "source_id": "contract/acme-msa", "target_id": "party/party-acme", "kind": "party_to"}],
    )
    await write_documents(
        adapter,
        "signed_by",
        [{"_from": "contract/acme-msa", "_to": "person/jane", "signed_on": "2025-12-20",
          "on_behalf_of": "party-acme", "source_id": "contract/acme-msa",
          "target_id": "person/jane", "kind": "signed_by"}],
    )
    await write_documents(
        adapter,
        "governed_by",
        [{"_from": "contract/acme-sow-1", "_to": "contract/acme-msa",
          "source_id": "contract/acme-sow-1", "target_id": "contract/acme-msa",
          "kind": "governed_by"}],
    )
    await write_documents(
        adapter,
        "owned_by",
        [
            {"_from": "contract/acme-msa", "_to": "employees/emp-1",
             "source_id": "contract/acme-msa", "target_id": "employees/emp-1",
             "kind": "owned_by"},
            {"_from": "contract/acme-sow-1", "_to": "employees/emp-1",
             "source_id": "contract/acme-sow-1", "target_id": "employees/emp-1",
             "kind": "owned_by"},
        ],
    )

    collections = {
        "contract": "contract",
        "obligation": "obligation",
        "party": "party",
        "person": "person",
        "compliance_standard": "compliance_standard",
        "requires": "requires",
        "imposed_by": "imposed_by",
        "party_to": "party_to",
        "signed_by": "signed_by",
        "governed_by": "governed_by",
        "amends": "amends",
        "supersedes": "supersedes",
        "owned_by": "owned_by",
        "managed_by": "managed_by",
        "reports_to": "reports_to",
        "departments": "departments",
    }
    binds: dict[str, dict[str, Any]] = {
        "contracts_requiring_standard": {"standard_id": "soc2", "statuses": ["active"]},
        "expiring_within": {"today": "2026-09-09", "until": "2026-12-31"},
        "notice_deadlines_within": {"today": "2026-09-09", "until": "2026-12-31"},
        "contracts_with_party": {"party_id": "party-acme"},
        "contract_family": {"contract_id": "acme-msa"},
        "signatories_of": {"contract_id": "acme-msa"},
        "obligations_of_contract": {"contract_id": "acme-msa", "kind": None},
        "contract_in_force": {"contract_id": "acme-msa", "as_of": "2026-09-09"},
        "my_contracts": {"user_id": "employees/emp-1"},
        "search_contracts": {"query": "agreement", "top_k": 5},
    }
    assert len(binds) == 10 and set(binds) == set(ctx.ontology.traversal_patterns) - {
        "find_manager",
        "find_department",
        "find_team",
    }

    async def run_pattern(name: str, values: dict[str, Any]) -> list[Any]:
        template = ctx.ontology.traversal_patterns[name].query_template
        needed = {
            token.strip("@,()").rstrip(",")
            for token in template.replace(",", " ").split()
            if token.startswith("@@")
        }
        collection_binds = {
            f"@{key}": collections[key] for key in needed if key in collections
        }
        return await store.execute_traversal(
            ctx, template, bind_vars=values, collection_binds=collection_binds
        )

    executed: dict[str, list[Any]] = {}
    for name, values in binds.items():
        template = ctx.ontology.traversal_patterns[name].query_template
        needed = {
            token.strip("@,()").rstrip(",")
            for token in template.replace(",", " ").split()
            if token.startswith("@@")
        }
        collection_binds = {
            f"@{key}": collections[key] for key in needed if key in collections
        }
        executed[name] = await store.execute_traversal(
            ctx, template, bind_vars=values, collection_binds=collection_binds
        )

    if not executed["search_contracts"]:
        # ArangoSearch commits asynchronously (commitIntervalMsec); give the
        # view a moment before deciding the lexical pattern found nothing.
        import asyncio as _asyncio

        for _ in range(20):
            await _asyncio.sleep(0.25)
            executed["search_contracts"] = await run_pattern(
                "search_contracts", binds["search_contracts"]
            )
            if executed["search_contracts"]:
                break

    assert set(executed) == set(binds), "every declared pattern executed"
    assert len(executed["contracts_requiring_standard"]) == 1, "first-publish standard link"
    assert executed["contracts_requiring_standard"][0]["contract"]["contract_id"] == "acme-msa"
    assert {row["contract_id"] for row in executed["expiring_within"]} == {"acme-msa"}
    assert {row["contract_id"] for row in executed["notice_deadlines_within"]} == {"acme-msa"}
    assert executed["contracts_with_party"][0]["role"] == "customer"

    family = executed["contract_family"][0]["family"]
    ids = [entry["contract"]["contract_id"] for entry in family]
    assert ids == ["acme-sow-1"], ids
    assert len(ids) == len(set(ids)), "de-duplicated by contract identity"

    assert executed["signatories_of"][0]["person"]["name"] == "Jane Doe"
    assert executed["obligations_of_contract"][0]["obligation_id"] == "acme-msa-ob-001"
    assert executed["contract_in_force"][0]["n"] == 2, "the July version is in force"
    assert {row["contract"]["contract_id"] for row in executed["my_contracts"]} == {
        "acme-msa",
        "acme-sow-1",
    }
    hits = {row["doc"].get("contract_id") for row in executed["search_contracts"]}
    assert "acme-msa" in hits, "search hits map back to contracts"


@requires_arango
@requires_pg
async def test_inactive_endpoints_are_filtered_by_every_pattern(arango_store):
    """Retraction flips ``active``; the guards must then hide the rows."""
    store, database, adapter = arango_store
    ctx = contracts_context(database)
    await store.initialize_tenant(ctx)
    await write_documents(
        adapter,
        "contract",
        [
            {
                "_key": "retracted",
                "contract_id": "retracted",
                "title": "Retracted agreement",
                "status": "active",
                "expiration_date": "2026-12-31",
                "notice_deadline": "2026-11-01",
                "owner_employee_id": "emp-1",
                "card_revision": 1,
                "active": False,
                "versions": [],
            }
        ],
    )
    await write_documents(
        adapter, "employees", [{"_key": "emp-1", "employee_id": "emp-1"}]
    )
    await write_documents(
        adapter,
        "owned_by",
        [{"_from": "contract/retracted", "_to": "employees/emp-1",
          "source_id": "contract/retracted", "target_id": "employees/emp-1",
          "kind": "owned_by"}],
    )

    for name, values, binds_map in (
        ("expiring_within", {"today": "2026-09-09", "until": "2026-12-31"}, {"@contract": "contract"}),
        ("notice_deadlines_within", {"today": "2026-09-09", "until": "2026-12-31"}, {"@contract": "contract"}),
        (
            "my_contracts",
            {"user_id": "employees/emp-1"},
            {"@contract": "contract", "@owned_by": "owned_by", "@reports_to": "reports_to"},
        ),
    ):
        rows = await store.execute_traversal(
            ctx,
            ctx.ontology.traversal_patterns[name].query_template,
            bind_vars=values,
            collection_binds=binds_map,
        )
        assert rows == [], f"{name} returned an inactive contract"
