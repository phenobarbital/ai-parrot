"""Tests for projecting the approved concept catalog into vocabulary content (FEAT-824)."""

from __future__ import annotations

import concurrent.futures
import os
from datetime import datetime, timezone
from uuid import UUID, uuid4

import asyncpg
import pytest

from parrot.conf import default_dsn
from parrot.knowledge.ontology.concept_catalog.models import ConceptRow, IsaEdgeRow
from parrot.knowledge.ontology.vocabulary.catalog_bridge import (
    FRAMEWORK_NS,
    CatalogVocabularyPublisher,
    content_from_catalog,
    tenant_base_iri,
    tenant_ontology_id,
)
from parrot.knowledge.ontology.vocabulary.pg_schema import ensure_schema
from parrot.knowledge.ontology.vocabulary.publisher import PostgresOntologyPublisher

PG_DSN = os.environ.get("ONTOLOGY_PG_DSN") or default_dsn


def _concept(*, concept_id: UUID, slug: str, state: str = "approved", domain: str | None = "finance") -> ConceptRow:
    """Build a stable catalog concept fixture."""
    return ConceptRow(
        id=concept_id,
        tenant_id="acme",
        slug=slug,
        label=f"{slug} label",
        synonyms=[f"{slug} alias"],
        description=f"{slug} definition",
        domain=domain,
        state=state,
        asserted_by="curator@example.com",
        effective_from=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )


def _edge(*, child_id: UUID, parent_tier: str, parent_ref: str, state: str = "approved") -> IsaEdgeRow:
    """Build a stable catalog is-a edge fixture."""
    return IsaEdgeRow(
        id=uuid4(),
        tenant_id="acme",
        child_id=child_id,
        parent_tier=parent_tier,
        parent_ref=parent_ref,
        state=state,
        asserted_by="curator@example.com",
    )


def test_tenant_ids_validated() -> None:
    """Tenant ontology identifiers reject whitespace."""
    with pytest.raises(ValueError):
        tenant_ontology_id("a b")
    assert tenant_ontology_id("acme_1.prod") == "tenant.acme_1.prod"
    assert tenant_base_iri("acme") == "urn:parrot:tenant:acme:"


def test_content_from_catalog_mapping() -> None:
    """Approved catalog rows map to concepts, labels, domains, and both parent tiers."""
    parent_id, child_id = uuid4(), uuid4()
    content = content_from_catalog(
        "acme",
        [_concept(concept_id=child_id, slug="child"), _concept(concept_id=parent_id, slug="parent")],
        [
            _edge(child_id=child_id, parent_tier="tenant", parent_ref=str(parent_id)),
            _edge(child_id=parent_id, parent_tier="framework", parent_ref="enterprise"),
        ],
        default_lang="en",
    )
    child_iri = "urn:parrot:tenant:acme:child"
    parent_iri = "urn:parrot:tenant:acme:parent"

    assert content.base_iri == "urn:parrot:tenant:acme:"
    assert [(concept.iri, concept.kind, concept.pref_label, concept.definition) for concept in content.concepts] == [
        (child_iri, "skos_concept", "child label", "child definition"),
        (parent_iri, "skos_concept", "parent label", "parent definition"),
    ]
    assert {(label.iri, label.kind, label.lang, label.text) for label in content.labels} == {
        (child_iri, "pref", "en", "child label"),
        (child_iri, "alt", "en", "child alias"),
        (parent_iri, "pref", "en", "parent label"),
        (parent_iri, "alt", "en", "parent alias"),
    }
    assert {(statement.subject_iri, statement.predicate, statement.object["value"]) for statement in content.statements} == {
        (child_iri, "urn:parrot:core:domain", "finance"),
        (parent_iri, "urn:parrot:core:domain", "finance"),
    }
    assert {(relation.subject_iri, relation.object_iri) for relation in content.relations} == {
        (child_iri, parent_iri),
        (parent_iri, f"{FRAMEWORK_NS}enterprise"),
    }


def test_edge_to_missing_tenant_parent_skipped() -> None:
    """Tenant edges whose parent is not approved are not projected."""
    child_id = uuid4()
    content = content_from_catalog(
        "acme",
        [_concept(concept_id=child_id, slug="child")],
        [_edge(child_id=child_id, parent_tier="tenant", parent_ref=str(uuid4()))],
        default_lang="en",
    )
    assert content.relations == []


@pytest.mark.asyncio
async def test_catalog_publish_tenant(pg_pool: asyncpg.Pool, pg_schema_name: str) -> None:
    """A removed approved catalog concept is retained as deprecated after republishing."""
    catalog_schema = f"catalog_t_{uuid4().hex[:8]}"
    async with pg_pool.acquire() as conn:
        await conn.execute(f'CREATE SCHEMA "{catalog_schema}"')
        await conn.execute(
            f'''CREATE TABLE "{catalog_schema}".ontology_concept (
                id UUID PRIMARY KEY, tenant_id VARCHAR(64) NOT NULL, slug VARCHAR(128) NOT NULL,
                label VARCHAR(256) NOT NULL, synonyms TEXT[] NOT NULL DEFAULT '{{}}', description TEXT,
                domain VARCHAR(64), state VARCHAR(16) NOT NULL, asserted_by VARCHAR(96) NOT NULL,
                reviewed_by VARCHAR(96), reviewed_at TIMESTAMPTZ, rationale TEXT,
                effective_from TIMESTAMPTZ NOT NULL, effective_to TIMESTAMPTZ
            )'''
        )
        await conn.execute(
            f'''CREATE TABLE "{catalog_schema}".ontology_concept_isa (
                id UUID PRIMARY KEY, tenant_id VARCHAR(64) NOT NULL, child_id UUID NOT NULL,
                parent_tier VARCHAR(16) NOT NULL, parent_ref VARCHAR(256) NOT NULL,
                state VARCHAR(16) NOT NULL, asserted_by VARCHAR(96) NOT NULL,
                reviewed_by VARCHAR(96), rationale TEXT
            )'''
        )

    catalog_pool = await asyncpg.create_pool(PG_DSN, server_settings={"search_path": catalog_schema})
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    publisher = PostgresOntologyPublisher(pg_pool, schema=pg_schema_name, executor=executor)
    parent_id, child_id = uuid4(), uuid4()
    try:
        async with catalog_pool.acquire() as conn:
            for concept in (_concept(concept_id=parent_id, slug="parent"), _concept(concept_id=child_id, slug="child")):
                await conn.execute(
                    """INSERT INTO ontology_concept
                    (id, tenant_id, slug, label, synonyms, description, domain, state, asserted_by, effective_from)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)""",
                    concept.id, concept.tenant_id, concept.slug, concept.label, concept.synonyms, concept.description,
                    concept.domain, concept.state, concept.asserted_by, concept.effective_from,
                )
            await conn.execute(
                """INSERT INTO ontology_concept_isa
                (id, tenant_id, child_id, parent_tier, parent_ref, state, asserted_by)
                VALUES ($1, $2, $3, $4, $5, $6, $7)""",
                uuid4(), "acme", child_id, "tenant", str(parent_id), "approved", "curator@example.com",
            )

        await ensure_schema(pg_pool, schema=pg_schema_name)
        bridge = CatalogVocabularyPublisher(catalog_pool, publisher, default_lang="en")
        first = await bridge.publish_tenant("acme")
        async with catalog_pool.acquire() as conn:
            await conn.execute("UPDATE ontology_concept SET state = 'deprecated' WHERE id = $1", child_id)
        second = await bridge.publish_tenant("acme")
        child_iri = "urn:parrot:tenant:acme:child"
        async with pg_pool.acquire() as conn:
            deprecated = await conn.fetchval(
                f"SELECT deprecated FROM {pg_schema_name}.concept "
                "WHERE ontology_id = $1 AND iri = $2 AND until_version IS NULL",
                "tenant.acme",
                child_iri,
            )
        assert first.version == 1
        assert second.version == 2
        assert child_iri in second.diff.deprecated
        assert deprecated is True
    finally:
        await catalog_pool.close()
        await publisher.close()
        executor.shutdown(wait=True)
        async with pg_pool.acquire() as conn:
            await conn.execute(f'DROP SCHEMA IF EXISTS "{catalog_schema}" CASCADE')
