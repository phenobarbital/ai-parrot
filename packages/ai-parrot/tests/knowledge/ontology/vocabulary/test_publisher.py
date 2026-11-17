"""Integration coverage for append-only ontology publication (FEAT-824)."""

from __future__ import annotations

import asyncio
import concurrent.futures
from collections.abc import AsyncIterator

import asyncpg
import pytest
import pytest_asyncio

from parrot.knowledge.ontology.vocabulary._rows import read_content
from parrot.knowledge.ontology.vocabulary.exceptions import OntologyValidationError
from parrot.knowledge.ontology.vocabulary.pg_schema import ensure_schema
from parrot.knowledge.ontology.vocabulary.publisher import PostgresOntologyPublisher
from parrot.knowledge.ontology.vocabulary.turtle import content_checksum, parse_turtle


@pytest_asyncio.fixture
async def publisher(pg_pool: asyncpg.Pool, pg_schema_name: str) -> AsyncIterator[PostgresOntologyPublisher]:
    """Create a thread-executor publisher over an isolated live-test schema."""
    await ensure_schema(pg_pool, schema=pg_schema_name)
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    instance = PostgresOntologyPublisher(pg_pool, schema=pg_schema_name, executor=executor)
    try:
        yield instance
    finally:
        await instance.close()
        executor.shutdown(wait=True)


async def _registered_publisher(
    publisher: PostgresOntologyPublisher, ontology_id: str, base_iri: str
) -> PostgresOntologyPublisher:
    """Register a unique ontology and return the publisher."""
    await publisher.ensure_ontology(ontology_id, base_iri=base_iri)
    return publisher


@pytest.mark.asyncio
async def test_publish_first_version(
    publisher: PostgresOntologyPublisher, golden_v1: bytes, golden_base_iri: str
) -> None:
    """A first document creates immutable version one with its canonical checksum."""
    instance = await _registered_publisher(publisher, "first", golden_base_iri)
    result = await instance.publish("first", golden_v1)
    expected = content_checksum(parse_turtle(golden_v1, base_iri=golden_base_iri, default_lang="es"))
    assert result.version == 1
    assert result.changed is True
    assert result.checksum == expected


@pytest.mark.asyncio
async def test_publish_twice_same_version(
    publisher: PostgresOntologyPublisher, pg_pool: asyncpg.Pool, golden_v1: bytes, golden_base_iri: str
) -> None:
    """Re-publishing equivalent Turtle is a no-op and creates no version row."""
    instance = await _registered_publisher(publisher, "same", golden_base_iri)
    first = await instance.publish("same", golden_v1)
    second = await instance.publish("same", golden_v1)
    async with pg_pool.acquire() as conn:
        versions = await conn.fetchval(
            f"SELECT count(*) FROM {instance._schema}.version WHERE ontology_id = $1", "same"
        )
    assert first.version == second.version == 1
    assert second.changed is False
    assert versions == 1


@pytest.mark.asyncio
async def test_publish_removed_iri_rejected(
    publisher: PostgresOntologyPublisher, pg_pool: asyncpg.Pool, golden_v1: bytes, golden_base_iri: str
) -> None:
    """Dropping a previously visible IRI fails validation and retains the old version."""
    instance = await _registered_publisher(publisher, "removed", golden_base_iri)
    await instance.publish("removed", golden_v1)
    content = parse_turtle(golden_v1, base_iri=golden_base_iri, default_lang="es")
    dropped = content.concepts[0].iri
    candidate = content.model_copy(
        update={
            "concepts": [concept for concept in content.concepts if concept.iri != dropped],
            "labels": [label for label in content.labels if label.iri != dropped],
        }
    )
    with pytest.raises(OntologyValidationError) as exc_info:
        await instance.publish_content("removed", candidate)
    async with pg_pool.acquire() as conn:
        version = await conn.fetchval(
            f"SELECT current_version FROM {instance._schema}.ontology WHERE ontology_id = $1", "removed"
        )
    assert "IRI_REMOVED" in {issue.code for issue in exc_info.value.issues}
    assert version == 1


@pytest.mark.asyncio
async def test_rejection_writes_nothing(
    publisher: PostgresOntologyPublisher, pg_pool: asyncpg.Pool, golden_v1: bytes, golden_base_iri: str
) -> None:
    """A validation rejection does not append or close any persisted publication row."""
    instance = await _registered_publisher(publisher, "atomic", golden_base_iri)
    await instance.publish("atomic", golden_v1)
    tables = ("version", "concept", "label", "relation", "statement", "closure", "publication_outbox")
    async with pg_pool.acquire() as conn:
        before = {table: await conn.fetchval(f"SELECT count(*) FROM {instance._schema}.{table}") for table in tables}
    invalid = parse_turtle(
        b"@prefix owl: <http://www.w3.org/2002/07/owl#>. <bad> a owl:Class .",
        base_iri=golden_base_iri,
        default_lang="es",
    )
    with pytest.raises(OntologyValidationError):
        await instance.publish_content("atomic", invalid)
    async with pg_pool.acquire() as conn:
        after = {table: await conn.fetchval(f"SELECT count(*) FROM {instance._schema}.{table}") for table in tables}
    assert after == before


@pytest.mark.asyncio
async def test_concurrent_publish_serialised(
    publisher: PostgresOntologyPublisher,
    pg_pool: asyncpg.Pool,
    golden_v1: bytes,
    golden_v2: bytes,
    golden_v3: bytes,
    golden_base_iri: str,
) -> None:
    """Concurrent candidates retry through the row lock and receive consecutive versions."""
    instance = await _registered_publisher(publisher, "concurrent", golden_base_iri)
    await instance.publish("concurrent", golden_v1)
    results = await asyncio.gather(instance.publish("concurrent", golden_v2), instance.publish("concurrent", golden_v3))
    async with pg_pool.acquire() as conn:
        duplicates = await conn.fetchval(
            f"SELECT count(*) FROM (SELECT iri FROM {instance._schema}.concept "
            "WHERE ontology_id = $1 AND until_version IS NULL GROUP BY iri HAVING count(*) > 1) rows",
            "concurrent",
        )
    assert {result.version for result in results} == {2, 3}
    assert duplicates == 0


@pytest.mark.asyncio
async def test_attribute_change_closes_row(
    publisher: PostgresOntologyPublisher,
    pg_pool: asyncpg.Pool,
    golden_v1: bytes,
    golden_v2: bytes,
    golden_base_iri: str,
) -> None:
    """A changed concept appends a replacement row and closes its old validity interval."""
    instance = await _registered_publisher(publisher, "changed", golden_base_iri)
    await instance.publish("changed", golden_v1)
    result = await instance.publish("changed", golden_v2)
    iri = result.diff.changed_iris[0]
    async with pg_pool.acquire() as conn:
        intervals = await conn.fetch(
            f"SELECT since_version, until_version FROM {instance._schema}.concept WHERE ontology_id = $1 AND iri = $2 "
            "ORDER BY since_version",
            "changed",
            iri,
        )
    assert [(row["since_version"], row["until_version"]) for row in intervals] == [(1, 2), (2, None)]


@pytest.mark.asyncio
async def test_ensure_ontology_conflicting_base(publisher: PostgresOntologyPublisher, golden_base_iri: str) -> None:
    """Registration cannot change an ontology's immutable base IRI."""
    await publisher.ensure_ontology("conflict", base_iri=golden_base_iri)
    with pytest.raises(ValueError):
        await publisher.ensure_ontology("conflict", base_iri="https://other.example/")


@pytest.mark.asyncio
async def test_carry_forward_missing_deprecates(
    publisher: PostgresOntologyPublisher,
    pg_pool: asyncpg.Pool,
    golden_v1: bytes,
    golden_base_iri: str,
) -> None:
    """Carry-forward retains a missing concept, its labels, and marks it deprecated."""
    instance = await _registered_publisher(publisher, "carry", golden_base_iri)
    await instance.publish("carry", golden_v1)
    original = parse_turtle(golden_v1, base_iri=golden_base_iri, default_lang="es")
    dropped = original.concepts[0].iri
    candidate = original.model_copy(
        update={
            "concepts": [concept for concept in original.concepts if concept.iri != dropped],
            "labels": [label for label in original.labels if label.iri != dropped],
        }
    )
    result = await instance.publish_content("carry", candidate, carry_forward_missing=True)
    async with pg_pool.acquire() as conn:
        content, _, _ = await read_content(conn, instance._schema, "carry", result.version)
    carried = next(concept for concept in content.concepts if concept.iri == dropped)
    assert result.version == 2
    assert carried.deprecated is True
    assert any(label.iri == dropped for label in content.labels)
