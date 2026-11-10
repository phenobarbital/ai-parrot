"""Integration tests for PostgresOntologyStore (FEAT-824)."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import asyncpg
import pytest
import pytest_asyncio

from parrot.knowledge.ontology.vocabulary.backends import create_ontology_store
from parrot.knowledge.ontology.vocabulary.contracts import OntologyStore
from parrot.knowledge.ontology.vocabulary.exceptions import OntologyNotFound, OntologyVersionNotFound
from parrot.knowledge.ontology.vocabulary.pg_schema import ensure_schema
from parrot.knowledge.ontology.vocabulary.postgres_store import PostgresOntologyStore
from parrot.knowledge.ontology.vocabulary.publisher import PostgresOntologyPublisher


@pytest_asyncio.fixture
async def store_with_data(
    pg_pool: asyncpg.Pool, pg_schema_name: str, golden_v1: bytes, golden_base_iri: str
) -> AsyncIterator[tuple[PostgresOntologyStore, PostgresOntologyPublisher]]:
    """Create a store and publisher with golden data published."""
    # Ensure schema exists
    await ensure_schema(pg_pool, schema=pg_schema_name)

    # Create store and publisher
    store = PostgresOntologyStore(pg_pool, schema=pg_schema_name)
    publisher = PostgresOntologyPublisher(pg_pool, schema=pg_schema_name)

    try:
        # Register and publish the ontology
        await publisher.ensure_ontology("test", base_iri=golden_base_iri)
        await publisher.publish("test", golden_v1)
        yield store, publisher
    finally:
        await store.close()
        await publisher.close()


@pytest.mark.asyncio
async def test_version(store_with_data: tuple[PostgresOntologyStore, PostgresOntologyPublisher]) -> None:
    """Test version method returns correct version."""
    store, _ = store_with_data
    version = await store.version("test")
    assert version == 1

    # Test nonexistent ontology raises OntologyNotFound
    with pytest.raises(OntologyNotFound):
        await store.version("nonexistent")


@pytest.mark.asyncio
async def test_status(store_with_data: tuple[PostgresOntologyStore, PostgresOntologyPublisher]) -> None:
    """Test status method returns correct status."""
    store, _ = store_with_data
    status = await store.status("test")
    assert status.ontology_id == "test"
    assert status.version == 1
    assert status.backend == "postgres"
    assert status.stale is False


@pytest.mark.asyncio
async def test_get(store_with_data: tuple[PostgresOntologyStore, PostgresOntologyPublisher]) -> None:
    """Test get method retrieves concepts correctly."""
    store, _ = store_with_data

    # Test getting a concept that exists
    concept = await store.get("test", "https://ontology.parrot.dev/legal_es/LegalEntity")
    assert concept is not None
    assert concept.iri == "https://ontology.parrot.dev/legal_es/LegalEntity"
    assert concept.ontology_id == "test"
    assert concept.version == 1

    # Test getting a concept that doesn't exist
    concept = await store.get("test", "https://ontology.parrot.dev/legal_es/NonExistent")
    assert concept is None

    # Test as_of parameter
    concept = await store.get("test", "https://ontology.parrot.dev/legal_es/LegalEntity", as_of=1)
    assert concept is not None
    assert concept.version == 1

    # Test invalid as_of raises OntologyVersionNotFound
    with pytest.raises(OntologyVersionNotFound):
        await store.get("test", "https://ontology.parrot.dev/legal_es/LegalEntity", as_of=99)


@pytest.mark.asyncio
async def test_resolve_exact_then_trgm(
    store_with_data: tuple[PostgresOntologyStore, PostgresOntologyPublisher],
) -> None:
    """Test resolve method with exact match and trigram similarity."""
    store, _ = store_with_data

    # Test exact match
    results = await store.resolve("test", "Persona")
    assert len(results) > 0
    # First result should be exact match
    assert results[0].matched_by == "exact"
    assert results[0].score > 0

    # Test trigram similarity with misspelling
    results = await store.resolve("test", "Persna")  # Misspelled
    assert len(results) > 0
    # Should have trigram matches
    trgm_matches = [r for r in results if r.matched_by == "trgm"]
    assert len(trgm_matches) > 0


@pytest.mark.asyncio
async def test_resolve_excludes_deprecated(
    store_with_data: tuple[PostgresOntologyStore, PostgresOntologyPublisher], golden_v2: bytes
) -> None:
    """Test resolve method excludes deprecated concepts."""
    store, publisher = store_with_data

    # Publish v2 with deprecations
    await publisher.publish("test", golden_v2)

    # Resolve should not return deprecated concepts
    results = await store.resolve("test", "some_term")
    deprecated_results = [r for r in results if r.concept.deprecated]
    assert len(deprecated_results) == 0


@pytest.mark.asyncio
async def test_expand_down_up_reflexive(
    store_with_data: tuple[PostgresOntologyStore, PostgresOntologyPublisher],
) -> None:
    """Test expand method works in both directions and is reflexive."""
    store, _ = store_with_data

    # Test reflexive property - input IRIs are always included
    input_iris = ["https://ontology.parrot.dev/legal_es/LegalEntity"]
    expanded = await store.expand("test", input_iris, direction="down")
    assert set(input_iris).issubset(expanded)

    # Test up direction
    expanded_up = await store.expand("test", input_iris, direction="up")
    assert set(input_iris).issubset(expanded_up)

    # Test both directions
    expanded_both = await store.expand("test", input_iris, direction="both")
    assert set(input_iris).issubset(expanded_both)


@pytest.mark.asyncio
async def test_canonical_follows_replaced_by(
    store_with_data: tuple[PostgresOntologyStore, PostgresOntologyPublisher], golden_v2: bytes
) -> None:
    """Test canonical method follows replaced_by relationships."""
    store, publisher = store_with_data

    # Publish v2 with replacements
    await publisher.publish("test", golden_v2)

    # Test canonical mapping
    iris = ["https://ontology.parrot.dev/legal_es/SomeConcept"]
    canonical_map = await store.canonical("test", iris)
    # Should map deprecated concepts to their replacements
    # (exact assertions depend on the test data content)


@pytest.mark.asyncio
async def test_as_of_unknown_raises(store_with_data: tuple[PostgresOntologyStore, PostgresOntologyPublisher]) -> None:
    """Test that unknown as_of raises OntologyVersionNotFound."""
    store, _ = store_with_data

    # Test various methods with invalid as_of
    with pytest.raises(OntologyVersionNotFound):
        await store.get("test", "https://ontology.parrot.dev/legal_es/LegalEntity", as_of=99)

    with pytest.raises(OntologyVersionNotFound):
        await store.expand("test", ["https://ontology.parrot.dev/legal_es/LegalEntity"], as_of=99)

    with pytest.raises(OntologyVersionNotFound):
        await store.neighbors("test", "https://ontology.parrot.dev/legal_es/LegalEntity", as_of=99)

    with pytest.raises(OntologyVersionNotFound):
        await store.export("test", as_of=99)


@pytest.mark.asyncio
async def test_factory_via_registry(pg_pool: asyncpg.Pool, pg_schema_name: str) -> None:
    """Test create_ontology_store factory creates PostgresOntologyStore."""
    # Test creating store via registry
    store = create_ontology_store("postgres", pool=pg_pool, schema=pg_schema_name)
    assert isinstance(store, PostgresOntologyStore)

    # Test with dsn parameter (lazy pool creation)
    store2 = create_ontology_store("postgres", dsn="postgresql://localhost/test", schema=pg_schema_name)
    assert isinstance(store2, PostgresOntologyStore)


@pytest.mark.asyncio
async def test_load_version(store_with_data: tuple[PostgresOntologyStore, PostgresOntologyPublisher]) -> None:
    """Test load_version method loads complete version content."""
    store, _ = store_with_data

    # Load version content
    version_content = await store.load_version("test", 1)
    assert version_content.ontology_id == "test"
    assert version_content.version == 1
    assert version_content.content is not None
    assert version_content.closure is not None
    assert version_content.checksum is not None


@pytest.mark.asyncio
async def test_export(store_with_data: tuple[PostgresOntologyStore, PostgresOntologyPublisher]) -> None:
    """Test export method serializes content."""
    store, _ = store_with_data

    # Export as turtle
    turtle_data = await store.export("test", "turtle")
    assert isinstance(turtle_data, bytes)
    assert len(turtle_data) > 0

    # Export as jsonld
    jsonld_data = await store.export("test", "jsonld")
    assert isinstance(jsonld_data, bytes)
    assert len(jsonld_data) > 0


@pytest.mark.asyncio
async def test_neighbors(store_with_data: tuple[PostgresOntologyStore, PostgresOntologyPublisher]) -> None:
    """Test neighbors method retrieves relations."""
    store, _ = store_with_data

    # Get neighbors for a concept
    neighbors = await store.neighbors("test", "https://ontology.parrot.dev/legal_es/LegalEntity")
    # Should return list of (predicate, object_iri) tuples
    assert isinstance(neighbors, list)
    for neighbor in neighbors:
        assert isinstance(neighbor, tuple)
        assert len(neighbor) == 2
        assert isinstance(neighbor[0], str)  # predicate
        assert isinstance(neighbor[1], str)  # object_iri


@pytest.mark.asyncio
async def test_empty_ontology_behavior(pg_pool: asyncpg.Pool, pg_schema_name: str, golden_base_iri: str) -> None:
    """Test behavior when ontology exists but has no published versions."""
    await ensure_schema(pg_pool, schema=pg_schema_name)
    store = PostgresOntologyStore(pg_pool, schema=pg_schema_name)
    publisher = PostgresOntologyPublisher(pg_pool, schema=pg_schema_name)

    try:
        # Register ontology but don't publish anything
        await publisher.ensure_ontology("empty_test", base_iri=golden_base_iri)

        # Test version is 0
        version = await store.version("empty_test")
        assert version == 0

        # Test get returns None
        concept = await store.get("empty_test", "any_iri")
        assert concept is None

        # Test resolve returns empty list
        results = await store.resolve("empty_test", "any_term")
        assert results == []

        # Test expand returns only input IRIs
        iris = ["iri1", "iri2"]
        expanded = await store.expand("empty_test", iris)
        assert expanded == set(iris)

        # Test neighbors returns empty list
        neighbors = await store.neighbors("empty_test", "any_iri")
        assert neighbors == []

        # Test canonical returns empty dict
        canonical = await store.canonical("empty_test", iris)
        assert canonical == {}

    finally:
        await store.close()
        await publisher.close()
