"""Temporal fidelity gate — version history and historical reads (FEAT-824 TASK-5264)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import asyncpg
import pytest
import pytest_asyncio

from parrot.knowledge.ontology.vocabulary.exceptions import OntologyVersionNotFound
from parrot.knowledge.ontology.vocabulary.pg_schema import ensure_schema
from parrot.knowledge.ontology.vocabulary.postgres_store import PostgresOntologyStore
from parrot.knowledge.ontology.vocabulary.publisher import PostgresOntologyPublisher
from parrot.knowledge.ontology.vocabulary.snapshot import SnapshotOntologyStore, build_snapshot
from parrot.knowledge.ontology.vocabulary.turtle import content_checksum, parse_turtle

# IRIs from the golden fixtures
LEGAL_ENTITY_IRI = "https://ontology.parrot.dev/legal_es/LegalEntity"
ORGANIZATION_IRI = "https://ontology.parrot.dev/legal_es/Organization"
PUBLIC_AUTHORITY_IRI = "https://ontology.parrot.dev/legal_es/PublicAuthority"
PUBLIC_BODY_IRI = "https://ontology.parrot.dev/legal_es/PublicBody"
CONTRACT_IRI = "https://ontology.parrot.dev/legal_es/Contract"


@pytest_asyncio.fixture
async def temporal_store(
    pg_pool: asyncpg.Pool,
    pg_schema_name: str,
    golden_v1: bytes,
    golden_v2: bytes,
    golden_v3: bytes,
    golden_base_iri: str,
    tmp_path: Path,
) -> AsyncIterator[tuple[PostgresOntologyStore, PostgresOntologyPublisher, str, Path]]:
    """Publish v1, v2, v3 and yield (store, publisher, ontology_id, snapshot_dir)."""
    # Ensure schema exists
    await ensure_schema(pg_pool, schema=pg_schema_name)

    # Create publisher and store
    publisher = PostgresOntologyPublisher(pg_pool, schema=pg_schema_name)
    store = PostgresOntologyStore(pg_pool, schema=pg_schema_name)

    ontology_id = "temporal_test"
    snapshot_dir = tmp_path / "snapshots"

    try:
        # Register ontology
        await publisher.ensure_ontology(ontology_id, base_iri=golden_base_iri)

        # Publish v1, v2, v3
        await publisher.publish(ontology_id, golden_v1)
        await publisher.publish(ontology_id, golden_v2)
        await publisher.publish(ontology_id, golden_v3)

        yield store, publisher, ontology_id, snapshot_dir
    finally:
        await publisher.close()
        await store.close()


@pytest.mark.asyncio
async def test_temporal_fidelity_export_checksum(
    temporal_store: tuple[PostgresOntologyStore, PostgresOntologyPublisher, str, Path],
    golden_v1: bytes,
    golden_v2: bytes,
    golden_v3: bytes,
    golden_base_iri: str,
) -> None:
    """export(as_of=v) checksum matches version.checksum for v1, v2, v3."""
    store, publisher, ontology_id, _ = temporal_store

    # Get version info from database
    for version_num, _golden in [(1, golden_v1), (2, golden_v2), (3, golden_v3)]:
        # Load version content to get checksum
        version_content = await store.load_version(ontology_id, version=version_num)
        expected_checksum = version_content.checksum

        # Export at that version
        exported = await store.export(ontology_id, as_of=version_num)

        # Re-parse and compute checksum
        content = parse_turtle(exported, base_iri=golden_base_iri, default_lang="es")
        actual_checksum = content_checksum(content)

        assert actual_checksum == expected_checksum, (
            f"Version {version_num}: export checksum {actual_checksum} != " f"version checksum {expected_checksum}"
        )


@pytest.mark.asyncio
async def test_temporal_fidelity_historical_get(
    temporal_store: tuple[PostgresOntologyStore, PostgresOntologyPublisher, str, Path],
) -> None:
    """get(as_of=1) returns v1 attributes after v2 changed them."""
    store, _publisher, ontology_id, _ = temporal_store

    # v1: Organization prefLabel is "Organización"
    org_v1 = await store.get(ontology_id, ORGANIZATION_IRI, as_of=1)
    assert org_v1 is not None
    assert "Organización" in (
        org_v1.pref_label or ""
    ), f"v1 Organization prefLabel should contain 'Organización', got {org_v1.pref_label}"

    # v2: Organization prefLabel changed to "Entidad organizativa"
    org_v2 = await store.get(ontology_id, ORGANIZATION_IRI, as_of=2)
    assert org_v2 is not None
    assert (
        "organizativa" in (org_v2.pref_label or "").lower()
    ), f"v2 Organization prefLabel should contain 'organizativa', got {org_v2.pref_label}"

    # v3: Same as v2 (label change retained)
    org_v3 = await store.get(ontology_id, ORGANIZATION_IRI, as_of=3)
    assert org_v3 is not None
    assert org_v3.pref_label == org_v2.pref_label


@pytest.mark.asyncio
async def test_temporal_fidelity_historical_expand(
    temporal_store: tuple[PostgresOntologyStore, PostgresOntologyPublisher, str, Path],
) -> None:
    """expand(as_of=1) uses v1's closure; expand(as_of=2) lacks removed edge; expand(as_of=3) has it again."""
    store, _publisher, ontology_id, _ = temporal_store

    # v1: PublicAuthority is subclass of both Organization AND PublicBody
    ancestors_v1 = await store.expand(ontology_id, [PUBLIC_AUTHORITY_IRI], family="subclass", direction="up")
    assert PUBLIC_BODY_IRI in ancestors_v1, f"v1: Expected {PUBLIC_BODY_IRI} in ancestors"

    # v2: PublicAuthority subclass link to PublicBody was removed
    ancestors_v2 = await store.expand(ontology_id, [PUBLIC_AUTHORITY_IRI], family="subclass", direction="up", as_of=2)
    assert PUBLIC_BODY_IRI not in ancestors_v2, f"v2: Expected {PUBLIC_BODY_IRI} NOT in ancestors (edge removed)"
    assert ORGANIZATION_IRI in ancestors_v2, f"v2: Expected {ORGANIZATION_IRI} in ancestors"

    # v3: PublicBody subclass link reintroduced
    ancestors_v3 = await store.expand(ontology_id, [PUBLIC_AUTHORITY_IRI], family="subclass", direction="up", as_of=3)
    assert PUBLIC_BODY_IRI in ancestors_v3, f"v3: Expected {PUBLIC_BODY_IRI} in ancestors (edge restored)"
    assert ORGANIZATION_IRI in ancestors_v3, f"v3: Expected {ORGANIZATION_IRI} in ancestors"


@pytest.mark.asyncio
async def test_temporal_fidelity_unknown_version_raises(
    temporal_store: tuple[PostgresOntologyStore, PostgresOntologyPublisher, str, Path],
) -> None:
    """as_of=4 raises OntologyVersionNotFound (only v1, v2, v3 exist)."""
    store, _publisher, ontology_id, _ = temporal_store

    with pytest.raises(OntologyVersionNotFound):
        await store.get(ontology_id, LEGAL_ENTITY_IRI, as_of=4)

    with pytest.raises(OntologyVersionNotFound):
        await store.expand(ontology_id, [LEGAL_ENTITY_IRI], as_of=4)


@pytest.mark.asyncio
async def test_temporal_fidelity_snapshot_holds_only_version(
    temporal_store: tuple[PostgresOntologyStore, PostgresOntologyPublisher, str, Path],
) -> None:
    """A snapshot of v1 holds only v1-visible rows."""
    pg_store, _publisher, ontology_id, snapshot_dir = temporal_store

    # Build snapshot of v1
    v1_content = await pg_store.load_version(ontology_id, version=1)
    await build_snapshot(v1_content, snapshot_dir)

    # Create snapshot store
    snapshot_store = SnapshotOntologyStore(snapshot_dir)

    # Check that v1 snapshot has correct version
    version = await snapshot_store.version(ontology_id)
    assert version == 1, f"Snapshot should be at version 1, got {version}"

    # v1: Organization has original label
    org = await snapshot_store.get(ontology_id, ORGANIZATION_IRI)
    assert org is not None
    assert "Organización" in (
        org.pref_label or ""
    ), f"v1 snapshot: Organization should have 'Organización', got {org.pref_label}"

    # v1: PublicAuthority has PublicBody in ancestors
    ancestors = await snapshot_store.expand(ontology_id, [PUBLIC_AUTHORITY_IRI], family="subclass", direction="up")
    assert PUBLIC_BODY_IRI in ancestors, "v1 snapshot: PublicBody should be in ancestors"

    # Snapshot rejects as_of != its own version
    with pytest.raises(OntologyVersionNotFound):
        await snapshot_store.get(ontology_id, LEGAL_ENTITY_IRI, as_of=2)

    await snapshot_store.close()


@pytest.mark.asyncio
async def test_temporal_fidelity_deprecation_evolution(
    temporal_store: tuple[PostgresOntologyStore, PostgresOntologyPublisher, str, Path],
) -> None:
    """Contract is deprecated in v2 and stays deprecated in v3."""
    store, _publisher, ontology_id, _ = temporal_store

    # v1: Contract is NOT deprecated
    contract_v1 = await store.get(ontology_id, CONTRACT_IRI, as_of=1)
    assert contract_v1 is not None
    assert contract_v1.deprecated is False, "v1: Contract should not be deprecated"

    # v2: Contract IS deprecated
    contract_v2 = await store.get(ontology_id, CONTRACT_IRI, as_of=2)
    assert contract_v2 is not None
    assert contract_v2.deprecated is True, "v2: Contract should be deprecated"
    assert contract_v2.replaced_by is not None, "v2: Contract should have replaced_by"

    # v3: Contract still deprecated
    contract_v3 = await store.get(ontology_id, CONTRACT_IRI, as_of=3)
    assert contract_v3 is not None
    assert contract_v3.deprecated is True, "v3: Contract should still be deprecated"
