"""OntologyStore conformance — Snapshot backend (FEAT-824 TASK-5264)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import asyncpg
import pytest
import pytest_asyncio

from parrot.knowledge.ontology.vocabulary.pg_schema import ensure_schema
from parrot.knowledge.ontology.vocabulary.postgres_store import PostgresOntologyStore
from parrot.knowledge.ontology.vocabulary.publisher import PostgresOntologyPublisher
from parrot.knowledge.ontology.vocabulary.snapshot import SnapshotOntologyStore, build_snapshot

from .store_conformance import ALL_CASES


@pytest_asyncio.fixture
async def published(
    pg_pool: asyncpg.Pool,
    pg_schema_name: str,
    golden_v1: bytes,
    golden_v2: bytes,
    golden_base_iri: str,
    tmp_path: Path,
) -> AsyncIterator[tuple[PostgresOntologyPublisher, SnapshotOntologyStore, str]]:
    """Publish golden v1 and v2 to PostgreSQL, build snapshot, yield (publisher, snapshot_store, ontology_id)."""
    # Ensure schema exists
    await ensure_schema(pg_pool, schema=pg_schema_name)

    # Create publisher and postgres store
    publisher = PostgresOntologyPublisher(pg_pool, schema=pg_schema_name)
    pg_store = PostgresOntologyStore(pg_pool, schema=pg_schema_name)

    ontology_id = "conformance_snapshot_test"
    snapshot_dir = tmp_path / "snapshots"

    try:
        # Register ontology
        await publisher.ensure_ontology(ontology_id, base_iri=golden_base_iri)

        # Publish v1
        await publisher.publish(ontology_id, golden_v1)

        # Publish v2 (deprecates Contract, adds ModernContract)
        await publisher.publish(ontology_id, golden_v2)

        # Load version 2 content and build snapshot
        version_content = await pg_store.load_version(ontology_id, version=2)
        await build_snapshot(version_content, snapshot_dir)

        # Create snapshot store
        snapshot_store = SnapshotOntologyStore(snapshot_dir)

        yield publisher, snapshot_store, ontology_id
    finally:
        await publisher.close()
        await pg_store.close()


@pytest.mark.parametrize("case", ALL_CASES, ids=lambda c: c.__name__)
@pytest.mark.asyncio
async def test_conformance_snapshot(
    case,
    published: tuple[PostgresOntologyPublisher, SnapshotOntologyStore, str],
) -> None:
    """Run all conformance cases against SnapshotOntologyStore."""
    _publisher, store, ontology_id = published
    await case(store, ontology_id)
