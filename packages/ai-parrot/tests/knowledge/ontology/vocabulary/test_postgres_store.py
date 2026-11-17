"""OntologyStore conformance — PostgreSQL backend (FEAT-824 TASK-5264)."""

from __future__ import annotations

from collections.abc import AsyncIterator

import asyncpg
import pytest
import pytest_asyncio

from parrot.knowledge.ontology.vocabulary.pg_schema import ensure_schema
from parrot.knowledge.ontology.vocabulary.postgres_store import PostgresOntologyStore
from parrot.knowledge.ontology.vocabulary.publisher import PostgresOntologyPublisher

from .store_conformance import ALL_CASES


@pytest_asyncio.fixture
async def published(
    pg_pool: asyncpg.Pool,
    pg_schema_name: str,
    golden_v1: bytes,
    golden_v2: bytes,
    golden_base_iri: str,
) -> AsyncIterator[tuple[PostgresOntologyPublisher, PostgresOntologyStore, str]]:
    """Publish golden v1 and v2, yielding (publisher, store, ontology_id)."""
    # Ensure schema exists
    await ensure_schema(pg_pool, schema=pg_schema_name)

    # Create publisher and store
    publisher = PostgresOntologyPublisher(pg_pool, schema=pg_schema_name)
    store = PostgresOntologyStore(pg_pool, schema=pg_schema_name)

    ontology_id = "conformance_test"

    try:
        # Register ontology
        await publisher.ensure_ontology(ontology_id, base_iri=golden_base_iri)

        # Publish v1
        await publisher.publish(ontology_id, golden_v1)

        # Publish v2 (deprecates Contract, adds ModernContract)
        await publisher.publish(ontology_id, golden_v2)

        yield publisher, store, ontology_id
    finally:
        await publisher.close()
        await store.close()


@pytest.mark.parametrize("case", ALL_CASES, ids=lambda c: c.__name__)
@pytest.mark.asyncio
async def test_conformance_postgres(
    case,
    published: tuple[PostgresOntologyPublisher, PostgresOntologyStore, str],
) -> None:
    """Run all conformance cases against PostgresOntologyStore."""
    _publisher, store, ontology_id = published
    await case(store, ontology_id)
