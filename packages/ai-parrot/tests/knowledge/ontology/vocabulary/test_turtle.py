"""Turtle parsing, canonicalization and serialization tests (FEAT-824 TASK-5258)."""

from __future__ import annotations

import pytest

from parrot.knowledge.ontology.vocabulary.closure import RDFS
from parrot.knowledge.ontology.vocabulary.contracts import ParsedRelation
from parrot.knowledge.ontology.vocabulary.exceptions import OntologyValidationError
from parrot.knowledge.ontology.vocabulary.turtle import (
    canonical_ntriples,
    content_checksum,
    parse_turtle,
    serialize,
    statement_object_hash,
)


def test_parse_kinds_labels_relations(golden_v1: bytes, golden_base_iri: str) -> None:
    """Golden v1 maps kinds, multilingual labels, relations and literals to rows."""
    content = parse_turtle(golden_v1, base_iri=golden_base_iri, default_lang="es")
    concepts = {concept.iri: concept for concept in content.concepts}
    base = golden_base_iri

    assert concepts[base + "LegalEntity"].kind == "class"
    assert concepts[base + "hasParty"].kind == "object_property"
    assert concepts[base + "signatureDate"].kind == "datatype_property"
    assert concepts[base + "contract-2026-001"].kind == "individual"
    assert concepts[base + "LegalScheme"].kind == "concept_scheme"
    assert concepts[base + "PublicLaw"].kind == "skos_concept"
    assert concepts[base + "LegalEntity"].pref_label == "Entidad jurídica"
    assert any(
        label.iri == base + "LegalEntity"
        and label.kind == "alt"
        and label.lang == "es"
        and label.text == "Sujeto jurídico"
        for label in content.labels
    )
    assert any(
        relation.subject_iri == base + "Person"
        and relation.predicate == RDFS + "subClassOf"
        and relation.object_iri == base + "LegalEntity"
        for relation in content.relations
    )
    assert any(
        relation.subject_iri == base + "contract-2026-001"
        and relation.predicate == "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"
        and relation.object_iri == base + "Contract"
        for relation in content.relations
    )
    assert any(
        statement.subject_iri == base + "contract-2026-001"
        and statement.predicate == base + "signatureDate"
        and statement.object == {"value": "2026-01-01", "datatype": "http://www.w3.org/2001/XMLSchema#date"}
        for statement in content.statements
    )


def test_blank_node_rejected() -> None:
    """Blank nodes fail with the stable validation issue code."""
    turtle = b"@prefix owl: <http://www.w3.org/2002/07/owl#> . _:b a owl:Class ."

    with pytest.raises(OntologyValidationError) as error:
        parse_turtle(turtle, base_iri="https://example.test/", default_lang="en")

    assert {issue.code for issue in error.value.issues} == {"BLANK_NODE_UNSUPPORTED"}


def test_checksum_ignores_formatting(golden_base_iri: str) -> None:
    """Equivalent prefix and whitespace choices produce the same checksum."""
    compact = b"""
        @prefix ex: <https://ontology.parrot.dev/legal_es/> .
        @prefix owl: <http://www.w3.org/2002/07/owl#> .
        @prefix skos: <http://www.w3.org/2004/02/skos/core#> .
        ex:Person a owl:Class ; skos:prefLabel "Persona"@es .
    """
    expanded = b"""
        <https://ontology.parrot.dev/legal_es/Person>
            <http://www.w3.org/2004/02/skos/core#prefLabel> "Persona"@es ;
            <http://www.w3.org/1999/02/22-rdf-syntax-ns#type>
                <http://www.w3.org/2002/07/owl#Class> .
    """

    first = parse_turtle(compact, base_iri=golden_base_iri, default_lang="es")
    second = parse_turtle(expanded, base_iri=golden_base_iri, default_lang="es")

    assert content_checksum(first) == content_checksum(second)


def test_roundtrip_preserves_checksum(golden_v1: bytes, golden_base_iri: str) -> None:
    """Turtle serialization and reparsing preserve the canonical checksum."""
    original = parse_turtle(golden_v1, base_iri=golden_base_iri, default_lang="es")
    reparsed = parse_turtle(
        serialize(original, "turtle"),
        base_iri=golden_base_iri,
        default_lang="es",
    )

    assert content_checksum(reparsed) == content_checksum(original)


def test_statement_object_hash_distinguishes_lang() -> None:
    """Language is part of the canonical statement-object hash."""
    assert statement_object_hash({"value": "a", "lang": "es"}) != statement_object_hash({"value": "a", "lang": "en"})


def test_inferred_relations_not_in_canonical(golden_base_iri: str) -> None:
    """Materialized inferred relations do not affect asserted canonical bytes."""
    turtle = b"""
        @prefix ex: <https://ontology.parrot.dev/legal_es/> .
        @prefix owl: <http://www.w3.org/2002/07/owl#> .
        ex:Person a owl:Class .
    """
    content = parse_turtle(turtle, base_iri=golden_base_iri, default_lang="es")
    before = canonical_ntriples(content)
    content.relations.append(
        ParsedRelation(
            subject_iri=golden_base_iri + "Person",
            predicate=RDFS + "subClassOf",
            object_iri=golden_base_iri + "LegalEntity",
            inferred=True,
        )
    )

    assert canonical_ntriples(content) == before
