"""Validation and publication-diff tests for ontology vocabulary content."""

from __future__ import annotations

from parrot.knowledge.ontology.vocabulary.turtle import diff_content, parse_turtle, validate_content

BASE = "https://ontology.parrot.dev/t/"
PREFIXES = """
@prefix ex: <https://ontology.parrot.dev/t/> .
@prefix other: <https://outside.parrot.dev/> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix sh: <http://www.w3.org/ns/shacl#> .
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
"""


def _content(turtle: str):
    """Parse a small fixture with the shared ontology base IRI."""
    return parse_turtle(turtle.encode(), base_iri=BASE, default_lang="en")


def _codes(turtle: str, **kwargs: object) -> set[str]:
    """Return validation issue codes for an inline Turtle fixture."""
    return {issue.code for issue in validate_content(_content(PREFIXES + turtle), **kwargs)}


def test_valid_golden_has_no_issues(golden_v1: bytes, golden_base_iri: str) -> None:
    """The baseline vocabulary satisfies both Parrot rules and bundled SHACL."""
    content = parse_turtle(golden_v1, base_iri=golden_base_iri, default_lang="es")

    assert validate_content(content) == []


def test_rule_iri_outside_base() -> None:
    """Defined concepts outside the configured base IRI are rejected."""
    codes = _codes('other:Outside a owl:Class ; skos:prefLabel "Outside"@en .')

    assert codes == {"IRI_OUTSIDE_BASE"}


def test_rule_iri_removed() -> None:
    """A previously published IRI cannot silently disappear."""
    codes = _codes('ex:Current a owl:Class ; skos:prefLabel "Current"@en .', previous_iris=frozenset({BASE + "Gone"}))

    assert codes == {"IRI_REMOVED"}


def test_rule_iri_deprecated_is_not_removed() -> None:
    """A deprecated concept remains present and is therefore not removed."""
    codes = _codes(
        'ex:Gone a owl:Class ; skos:prefLabel "Gone"@en ; owl:deprecated true .',
        previous_iris=frozenset({BASE + "Gone"}),
    )

    assert codes == set()


def test_rule_hierarchy_cycle() -> None:
    """Cycles in a hierarchy family are rejected."""
    codes = _codes(
        'ex:A a owl:Class ; skos:prefLabel "A"@en ; rdfs:subClassOf ex:B . '
        'ex:B a owl:Class ; skos:prefLabel "B"@en ; rdfs:subClassOf ex:A .'
    )

    assert codes == {"HIERARCHY_CYCLE"}


def test_rule_missing_pref_label() -> None:
    """Classes and SKOS concepts require a preferred label."""
    codes = _codes("ex:Unlabelled a owl:Class .")

    assert codes == {"MISSING_PREF_LABEL"}


def test_rule_shacl_extra_shapes() -> None:
    """Caller-provided SHACL shapes are composed with the bundled shapes."""
    shapes = b"""
        @prefix ex: <https://ontology.parrot.dev/t/> .
        @prefix sh: <http://www.w3.org/ns/shacl#> .
        ex:Shape a sh:NodeShape ; sh:targetNode ex:A ; sh:property [ sh:path ex:required ; sh:minCount 1 ] .
    """

    codes = _codes('ex:A a owl:Class ; skos:prefLabel "A"@en .', shapes=shapes)

    assert codes == {"SHACL"}


def test_rules_report_every_issue() -> None:
    """Independent rule failures are accumulated instead of short-circuiting."""
    codes = _codes("other:Outside a owl:Class .")

    assert codes == {"IRI_OUTSIDE_BASE", "MISSING_PREF_LABEL"}


def test_diff_v1_v2(golden_v1: bytes, golden_v2: bytes, golden_base_iri: str) -> None:
    """The v2 fixture reports its new, changed, deprecated, and closed rows."""
    base = parse_turtle(golden_v1, base_iri=golden_base_iri, default_lang="es")
    candidate = parse_turtle(golden_v2, base_iri=golden_base_iri, default_lang="es")

    diff = diff_content(base, candidate)

    assert golden_base_iri + "ModernContract" in diff.added_iris
    assert {golden_base_iri + "Contract", golden_base_iri + "LegalEntity", golden_base_iri + "Organization"} <= set(
        diff.changed_iris
    )
    assert diff.deprecated == {golden_base_iri + "Contract": golden_base_iri + "ModernContract"}
    assert diff.relations_added >= 1
    assert diff.relations_closed >= 1


def test_diff_identical_is_empty(golden_v1: bytes, golden_base_iri: str) -> None:
    """Comparing content with itself produces an empty publication diff."""
    content = parse_turtle(golden_v1, base_iri=golden_base_iri, default_lang="es")

    assert diff_content(content, content).model_dump() == {
        "added_iris": [],
        "changed_iris": [],
        "deprecated": {},
        "relations_added": 0,
        "relations_closed": 0,
    }
