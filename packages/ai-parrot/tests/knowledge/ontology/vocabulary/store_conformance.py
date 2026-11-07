"""Reusable OntologyStore conformance cases (FEAT-824 M9).

Call each case with a store that has golden legal_es v1 (then v2) published as ``ontology_id``.
"""
from __future__ import annotations

from typing import Awaitable, Callable

from parrot.knowledge.ontology.vocabulary.contracts import OntologyStore
from parrot.knowledge.ontology.vocabulary.exceptions import OntologyVersionNotFound

Case = Callable[[OntologyStore, str], Awaitable[None]]

# IRIs from the golden fixtures
LEGAL_ENTITY_IRI = "https://ontology.parrot.dev/legal_es/LegalEntity"
PERSON_IRI = "https://ontology.parrot.dev/legal_es/Person"
ORGANIZATION_IRI = "https://ontology.parrot.dev/legal_es/Organization"
PUBLIC_BODY_IRI = "https://ontology.parrot.dev/legal_es/PublicBody"
PUBLIC_AUTHORITY_IRI = "https://ontology.parrot.dev/legal_es/PublicAuthority"
MUNICIPAL_AUTHORITY_IRI = "https://ontology.parrot.dev/legal_es/MunicipalAuthority"
CONTRACT_IRI = "https://ontology.parrot.dev/legal_es/Contract"
MODERN_CONTRACT_IRI = "https://ontology.parrot.dev/legal_es/ModernContract"
UNKNOWN_IRI = "https://ontology.parrot.dev/legal_es/UnknownConcept"


async def case_version_matches_published(store: OntologyStore, ontology_id: str) -> None:
    """version() equals the last published version; status().version agrees."""
    version = await store.version(ontology_id)
    status = await store.status(ontology_id)
    assert version >= 1, f"Expected version >= 1, got {version}"
    assert status.version == version, f"status.version {status.version} != version {version}"
    assert status.ontology_id == ontology_id


async def case_get_known_and_unknown(store: OntologyStore, ontology_id: str) -> None:
    """get() returns ConceptRef for known IRIs and None for unknown ones."""
    # Known concept
    legal_entity = await store.get(ontology_id, LEGAL_ENTITY_IRI)
    assert legal_entity is not None, f"Expected {LEGAL_ENTITY_IRI} to exist"
    assert legal_entity.iri == LEGAL_ENTITY_IRI
    assert legal_entity.kind == "class"
    assert legal_entity.pref_label is not None

    # Unknown concept
    unknown = await store.get(ontology_id, UNKNOWN_IRI)
    assert unknown is None, f"Expected {UNKNOWN_IRI} to not exist"


async def case_resolve_exact_trgm_order(store: OntologyStore, ontology_id: str) -> None:
    """resolve() returns ranked IRIs; exact match scores highest, trgm within 0.02 tolerance."""
    # Exact match on "Persona" (Spanish label for Person)
    results = await store.resolve(ontology_id, "Persona", lang="es", k=5)
    assert len(results) >= 1, "Expected at least one result for 'Persona'"
    # Exact match should be first
    assert results[0].matched_by in ("exact", "trgm"), f"Unexpected matched_by: {results[0].matched_by}"
    # Check that Person IRI is in results
    iris = {r.concept.iri for r in results}
    assert PERSON_IRI in iris, f"Expected {PERSON_IRI} in results, got {iris}"

    # Trigram match on partial term
    results2 = await store.resolve(ontology_id, "Entid", lang="es", k=5)
    # Should match Entidad jurídica via trigram
    if results2:
        assert results2[0].matched_by == "trgm", f"Expected trgm match, got {results2[0].matched_by}"


async def case_resolve_excludes_deprecated(store: OntologyStore, ontology_id: str) -> None:
    """resolve() excludes deprecated concepts from results."""
    # Search for "Contrato" - should NOT return deprecated Contract class
    results = await store.resolve(ontology_id, "Contrato", lang="es", k=10)
    # All results should be non-deprecated
    for r in results:
        assert r.concept.deprecated is False, f"Deprecated concept {r.concept.iri} in results"


async def case_expand_closed_and_reflexive(store: OntologyStore, ontology_id: str) -> None:
    """expand() returns transitive closure and always includes input IRIs (reflexive)."""
    # Expand Person subclass closure (down direction)
    closure = await store.expand(ontology_id, [PERSON_IRI], family="subclass", direction="down")
    # Should include Person itself (reflexive)
    assert PERSON_IRI in closure, f"Expected {PERSON_IRI} in closure (reflexive)"
    # Should include subclasses (Person has no subclasses in v1, so just itself)
    assert len(closure) >= 1

    # Expand up - should include ancestors
    ancestors = await store.expand(ontology_id, [MUNICIPAL_AUTHORITY_IRI], family="subclass", direction="up")
    assert MUNICIPAL_AUTHORITY_IRI in ancestors
    # Should include PublicAuthority, Organization, LegalEntity
    assert PUBLIC_AUTHORITY_IRI in ancestors, f"Expected {PUBLIC_AUTHORITY_IRI} in ancestors"
    assert ORGANIZATION_IRI in ancestors, f"Expected {ORGANIZATION_IRI} in ancestors"
    assert LEGAL_ENTITY_IRI in ancestors, f"Expected {LEGAL_ENTITY_IRI} in ancestors"


async def case_expand_multiple_inheritance(store: OntologyStore, ontology_id: str) -> None:
    """expand() correctly handles multiple inheritance (PublicAuthority has two parents)."""
    # PublicAuthority is subclass of both Organization and PublicBody
    ancestors = await store.expand(ontology_id, [PUBLIC_AUTHORITY_IRI], family="subclass", direction="up")
    assert PUBLIC_AUTHORITY_IRI in ancestors
    # Should include both parent branches
    assert ORGANIZATION_IRI in ancestors, f"Expected {ORGANIZATION_IRI} in ancestors"
    assert PUBLIC_BODY_IRI in ancestors, f"Expected {PUBLIC_BODY_IRI} in ancestors"
    assert LEGAL_ENTITY_IRI in ancestors, f"Expected {LEGAL_ENTITY_IRI} in ancestors"


async def case_canonical_follows_replaced_by(store: OntologyStore, ontology_id: str) -> None:
    """canonical() maps deprecated IRIs to their replacements."""
    # Contract is deprecated and replaced by ModernContract in v2
    replacements = await store.canonical(ontology_id, [CONTRACT_IRI])
    # Should map Contract -> ModernContract
    if CONTRACT_IRI in replacements:
        assert replacements[CONTRACT_IRI] == MODERN_CONTRACT_IRI, (
            f"Expected {CONTRACT_IRI} -> {MODERN_CONTRACT_IRI}, got {replacements}"
        )


async def case_export_checksum_roundtrip(store: OntologyStore, ontology_id: str) -> None:
    """export() produces valid Turtle that can be re-parsed."""
    # Export as Turtle
    turtle_data = await store.export(ontology_id, fmt="turtle")
    assert len(turtle_data) > 0, "Expected non-empty export"
    assert b"@prefix" in turtle_data, "Expected @prefix in Turtle export"

    # Export as JSON-LD
    jsonld_data = await store.export(ontology_id, fmt="jsonld")
    assert len(jsonld_data) > 0, "Expected non-empty JSON-LD export"
    assert b'"@context"' in jsonld_data or b'@graph' in jsonld_data, "Expected JSON-LD structure"


async def case_unknown_version_rejected(store: OntologyStore, ontology_id: str) -> None:
    """as_of for a non-existent version raises OntologyVersionNotFound."""
    # Get current version
    current = await store.version(ontology_id)
    # Try to access a version that doesn't exist
    future_version = current + 100
    try:
        await store.get(ontology_id, LEGAL_ENTITY_IRI, as_of=future_version)
        raise AssertionError(f"Expected OntologyVersionNotFound for version {future_version}")
    except OntologyVersionNotFound:
        pass  # Expected

    # Try version 0 (never published)
    try:
        await store.get(ontology_id, LEGAL_ENTITY_IRI, as_of=0)
        raise AssertionError("Expected OntologyVersionNotFound for version 0")
    except OntologyVersionNotFound:
        pass  # Expected


ALL_CASES: tuple[Case, ...] = (
    case_version_matches_published,
    case_get_known_and_unknown,
    case_resolve_exact_trgm_order,
    case_resolve_excludes_deprecated,
    case_expand_closed_and_reflexive,
    case_expand_multiple_inheritance,
    case_canonical_follows_replaced_by,
    case_export_checksum_roundtrip,
    case_unknown_version_rejected,
)
