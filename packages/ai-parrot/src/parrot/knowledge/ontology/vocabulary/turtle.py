"""Turtle ⇄ OntologyContent mapping, canonical form and checksum (FEAT-824).

Pure, synchronous functions; rdflib is imported inside them.
"""

from __future__ import annotations

import hashlib
import json
from importlib import resources
from typing import TYPE_CHECKING, Any, Literal, Mapping

from parrot.knowledge.ontology.vocabulary.closure import OWL, PARROT_NS, RDFS, SKOS  # noqa: F401
from parrot.knowledge.ontology.vocabulary.contracts import (
    OntologyContent,
    ParsedConcept,
    ParsedLabel,
    ParsedRelation,
    ParsedStatement,
    PublishDiff,
    ValidationIssue,
)
from parrot.knowledge.ontology.vocabulary.exceptions import OntologyValidationError

if TYPE_CHECKING:
    import rdflib

DCTERMS = "http://purl.org/dc/terms/"
KIND_BY_TYPE: dict[str, str] = {
    OWL + "Class": "class",
    RDFS + "Class": "class",
    OWL + "ObjectProperty": "object_property",
    OWL + "DatatypeProperty": "datatype_property",
    OWL + "NamedIndividual": "individual",
    SKOS + "ConceptScheme": "concept_scheme",
    SKOS + "Concept": "skos_concept",
}

RDF_TYPE = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"
LABEL_KIND_BY_PREDICATE: dict[str, str] = {
    SKOS + "prefLabel": "pref",
    SKOS + "altLabel": "alt",
    SKOS + "hiddenLabel": "hidden",
}


def parse_turtle(turtle: bytes, *, base_iri: str, default_lang: str) -> OntologyContent:
    """Parse Turtle into rows according to the vocabulary mapping rules.

    Args:
        turtle: UTF-8 Turtle document.
        base_iri: Base IRI used to resolve relative IRIs and stored on the result.
        default_lang: Language assigned to label literals without a language tag.

    Returns:
        Deterministically ordered ontology content.

    Raises:
        OntologyValidationError: If parsing fails or the graph contains a blank node.
    """
    import rdflib

    graph = rdflib.Graph()
    try:
        graph.parse(data=turtle, format="turtle", publicID=base_iri)
    except Exception as exc:
        raise OntologyValidationError([ValidationIssue(code="SYNTAX", message=str(exc))]) from exc

    blank_nodes = sorted(
        {str(node) for subject, _, obj in graph for node in (subject, obj) if isinstance(node, rdflib.BNode)}
    )
    if blank_nodes:
        raise OntologyValidationError(
            [
                ValidationIssue(
                    code="BLANK_NODE_UNSUPPORTED",
                    message=f"Blank node {node} is not supported",
                    subject=node,
                )
                for node in blank_nodes
            ]
        )

    rdf_type = rdflib.URIRef(RDF_TYPE)
    class_types = {rdflib.URIRef(OWL + "Class"), rdflib.URIRef(RDFS + "Class")}
    defined_classes = {subject for subject, obj in graph.subject_objects(rdf_type) if obj in class_types}
    types_by_subject: dict[Any, set[str]] = {}
    for subject, obj in graph.subject_objects(rdf_type):
        types_by_subject.setdefault(subject, set()).add(str(obj))

    kind_by_subject: dict[Any, str] = {}
    kind_type_by_subject: dict[Any, str] = {}
    for subject in sorted(types_by_subject, key=str):
        subject_types = types_by_subject[subject]
        for type_iri, kind in KIND_BY_TYPE.items():
            if type_iri in subject_types:
                kind_by_subject[subject] = kind
                kind_type_by_subject[subject] = type_iri
                break
        else:
            defined_class_types = sorted(subject_types & {str(iri) for iri in defined_classes})
            if defined_class_types:
                kind_by_subject[subject] = "individual"

    labels: list[ParsedLabel] = []
    relations: list[ParsedRelation] = []
    statements: list[ParsedStatement] = []
    concepts: list[ParsedConcept] = []

    for subject in sorted(kind_by_subject, key=str):
        pref_labels: list[tuple[str, str]] = []
        skos_pref_langs: set[str] = set()
        for obj in graph.objects(subject, rdflib.URIRef(SKOS + "prefLabel")):
            if isinstance(obj, rdflib.Literal):
                skos_pref_langs.add(obj.language or default_lang)

        for predicate, obj in graph.predicate_objects(subject):
            predicate_iri = str(predicate)
            label_kind = LABEL_KIND_BY_PREDICATE.get(predicate_iri)
            if predicate_iri == RDFS + "label":
                lang = obj.language or default_lang if isinstance(obj, rdflib.Literal) else default_lang
                if lang not in skos_pref_langs:
                    label_kind = "pref"
            if label_kind is not None and isinstance(obj, rdflib.Literal):
                lang = obj.language or default_lang
                text = str(obj)
                labels.append(ParsedLabel(iri=str(subject), lang=lang, kind=label_kind, text=text))
                if label_kind == "pref":
                    pref_labels.append((lang, text))

        default_pref_labels = sorted(text for lang, text in pref_labels if lang == default_lang)
        all_pref_labels = sorted(text for _, text in pref_labels)
        pref_label = (
            default_pref_labels[0] if default_pref_labels else (all_pref_labels[0] if all_pref_labels else None)
        )
        definitions = sorted(str(obj) for obj in graph.objects(subject, rdflib.URIRef(SKOS + "definition")))
        replacements = sorted(str(obj) for obj in graph.objects(subject, rdflib.URIRef(DCTERMS + "isReplacedBy")))
        deprecated = any(
            bool(obj.toPython()) if isinstance(obj, rdflib.Literal) else False
            for obj in graph.objects(subject, rdflib.URIRef(OWL + "deprecated"))
        )
        concepts.append(
            ParsedConcept(
                iri=str(subject),
                kind=kind_by_subject[subject],
                pref_label=pref_label,
                definition=definitions[0] if definitions else None,
                deprecated=deprecated,
                replaced_by=replacements[0] if replacements else None,
            )
        )

    attribute_predicates = {
        SKOS + "prefLabel",
        SKOS + "altLabel",
        SKOS + "hiddenLabel",
        RDFS + "label",
        SKOS + "definition",
        OWL + "deprecated",
        DCTERMS + "isReplacedBy",
    }
    for subject, predicate, obj in graph:
        predicate_iri = str(predicate)
        if predicate_iri in attribute_predicates:
            continue
        if predicate_iri == RDF_TYPE and kind_type_by_subject.get(subject) == str(obj):
            continue
        if isinstance(obj, rdflib.URIRef):
            relations.append(
                ParsedRelation(subject_iri=str(subject), predicate=predicate_iri, object_iri=str(obj), inferred=False)
            )
            continue
        if isinstance(obj, rdflib.Literal):
            statement_object: dict[str, Any] = {"value": str(obj)}
            if obj.datatype is not None:
                statement_object["datatype"] = str(obj.datatype)
            if obj.language is not None:
                statement_object["lang"] = obj.language
            statements.append(
                ParsedStatement(subject_iri=str(subject), predicate=predicate_iri, object=statement_object)
            )

    concepts.sort(key=lambda concept: concept.iri)
    labels.sort(key=lambda label: (label.iri, label.lang, label.kind, label.text))
    relations.sort(key=lambda relation: (relation.subject_iri, relation.predicate, relation.object_iri))
    statements.sort(
        key=lambda statement: (
            statement.subject_iri,
            statement.predicate,
            json.dumps(statement.object, sort_keys=True, separators=(",", ":")),
        )
    )
    return OntologyContent(
        base_iri=base_iri,
        concepts=concepts,
        labels=labels,
        relations=relations,
        statements=statements,
    )


def statement_object_hash(obj: Mapping[str, Any]) -> str:
    """Return the SHA-256 of a statement object's canonical JSON representation."""
    return hashlib.sha256(json.dumps(dict(obj), sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def canonical_ntriples(content: OntologyContent) -> bytes:
    """Return sorted N-Triples of the asserted graph, excluding inferred relations."""
    serialized = _to_graph(content).serialize(format="nt")
    text = serialized.decode("utf-8") if isinstance(serialized, bytes) else serialized
    lines = sorted(line for line in text.splitlines() if line.strip())
    return ("\n".join(lines) + "\n").encode("utf-8")


def content_checksum(content: OntologyContent) -> str:
    """Return the SHA-256 hex digest of the canonical asserted graph."""
    return hashlib.sha256(canonical_ntriples(content)).hexdigest()


def serialize(content: OntologyContent, fmt: Literal["turtle", "jsonld"]) -> bytes:
    """Serialize the asserted graph as Turtle or JSON-LD."""
    graph = _to_graph(content)
    graph.bind("owl", OWL)
    graph.bind("rdfs", RDFS)
    graph.bind("skos", SKOS)
    graph.bind("dcterms", DCTERMS)
    graph.bind("parrot", PARROT_NS)
    serialized = graph.serialize(format="turtle" if fmt == "turtle" else "json-ld")
    return serialized if isinstance(serialized, bytes) else serialized.encode("utf-8")


def _to_graph(content: OntologyContent) -> "rdflib.Graph":
    """Rebuild the asserted RDF graph from ontology rows."""
    import rdflib

    graph = rdflib.Graph()
    rdf_type = rdflib.URIRef(RDF_TYPE)
    type_by_kind: dict[str, str] = {}
    for type_iri, kind in KIND_BY_TYPE.items():
        type_by_kind.setdefault(kind, type_iri)

    for concept in content.concepts:
        subject = rdflib.URIRef(concept.iri)
        graph.add((subject, rdf_type, rdflib.URIRef(type_by_kind[concept.kind])))
        if concept.definition is not None:
            graph.add((subject, rdflib.URIRef(SKOS + "definition"), rdflib.Literal(concept.definition)))
        if concept.deprecated:
            graph.add((subject, rdflib.URIRef(OWL + "deprecated"), rdflib.Literal(True)))
        if concept.replaced_by is not None:
            graph.add((subject, rdflib.URIRef(DCTERMS + "isReplacedBy"), rdflib.URIRef(concept.replaced_by)))

    predicate_by_label_kind = {
        "pref": SKOS + "prefLabel",
        "alt": SKOS + "altLabel",
        "hidden": SKOS + "hiddenLabel",
    }
    for label in content.labels:
        graph.add(
            (
                rdflib.URIRef(label.iri),
                rdflib.URIRef(predicate_by_label_kind[label.kind]),
                rdflib.Literal(label.text, lang=label.lang),
            )
        )

    for relation in content.relations:
        if not relation.inferred:
            graph.add(
                (
                    rdflib.URIRef(relation.subject_iri),
                    rdflib.URIRef(relation.predicate),
                    rdflib.URIRef(relation.object_iri),
                )
            )

    for statement in content.statements:
        obj = statement.object
        if "iri" in obj:
            rdf_object = rdflib.URIRef(str(obj["iri"]))
        else:
            datatype = rdflib.URIRef(str(obj["datatype"])) if obj.get("datatype") is not None else None
            rdf_object = rdflib.Literal(str(obj["value"]), lang=obj.get("lang"), datatype=datatype)
        graph.add((rdflib.URIRef(statement.subject_iri), rdflib.URIRef(statement.predicate), rdf_object))
    return graph


def validate_content(
    content: OntologyContent,
    *,
    previous_iris: frozenset[str] = frozenset(),
    shapes: bytes | None = None,
) -> list[ValidationIssue]:
    """Validate bundled SHACL shapes, optional shapes, and Parrot rules.

    Args:
        content: Candidate ontology content to validate.
        previous_iris: Concept IRIs in the version being replaced.
        shapes: Optional caller-provided SHACL Turtle shapes.

    Returns:
        Every validation issue, sorted by code and subject. An empty list means valid.
    """
    import pyshacl
    import rdflib

    from parrot.knowledge.ontology.vocabulary.closure import FAMILY_PREDICATES, find_cycle

    issues: list[ValidationIssue] = []
    concept_iris = {concept.iri for concept in content.concepts}
    for concept in content.concepts:
        if not concept.iri.startswith(content.base_iri):
            issues.append(
                ValidationIssue(
                    code="IRI_OUTSIDE_BASE",
                    message=f"Concept IRI {concept.iri} is outside base IRI {content.base_iri}",
                    subject=concept.iri,
                )
            )

    for iri in sorted(previous_iris - concept_iris):
        issues.append(
            ValidationIssue(
                code="IRI_REMOVED",
                message=f"Previously published IRI {iri} is absent from the candidate",
                subject=iri,
            )
        )

    for family in FAMILY_PREDICATES:
        cycle = find_cycle(content.relations, family)
        if cycle is not None:
            issues.append(
                ValidationIssue(
                    code="HIERARCHY_CYCLE",
                    message=f"{family} hierarchy cycle: {' -> '.join(cycle)}",
                    subject=cycle[0],
                )
            )

    pref_label_iris = {label.iri for label in content.labels if label.kind == "pref"}
    for concept in content.concepts:
        if concept.kind in {"class", "skos_concept"} and concept.iri not in pref_label_iris:
            issues.append(
                ValidationIssue(
                    code="MISSING_PREF_LABEL",
                    message=f"{concept.kind} {concept.iri} has no preferred label",
                    subject=concept.iri,
                )
            )

    shacl_graph = rdflib.Graph()
    bundled_shapes = resources.files("parrot.knowledge.ontology.vocabulary.shapes").joinpath("parrot-core.shacl.ttl")
    shacl_graph.parse(data=bundled_shapes.read_bytes(), format="turtle")
    if shapes is not None:
        shacl_graph.parse(data=shapes, format="turtle")
    _, report_graph, _ = pyshacl.validate(_to_graph(content), shacl_graph=shacl_graph, inference="none")
    sh_result = rdflib.URIRef("http://www.w3.org/ns/shacl#ValidationResult")
    sh_focus_node = rdflib.URIRef("http://www.w3.org/ns/shacl#focusNode")
    sh_result_message = rdflib.URIRef("http://www.w3.org/ns/shacl#resultMessage")
    for result in report_graph.subjects(rdflib.RDF.type, sh_result):
        focus_node = report_graph.value(result, sh_focus_node)
        message = report_graph.value(result, sh_result_message)
        issues.append(
            ValidationIssue(
                code="SHACL",
                message=str(message) if message is not None else "SHACL validation failed",
                subject=str(focus_node) if focus_node is not None else None,
            )
        )
    return sorted(issues, key=lambda issue: (issue.code, issue.subject or ""))


def diff_content(base: OntologyContent | None, candidate: OntologyContent) -> PublishDiff:
    """Return the row-level difference from ``base`` to ``candidate``.

    Args:
        base: Existing published content, or ``None`` for the first publication.
        candidate: Content proposed for publication.

    Returns:
        Added and changed concepts, new deprecations, and asserted relation counts.
    """
    candidate_concepts = {concept.iri: concept for concept in candidate.concepts}
    candidate_labels = {}
    candidate_statements = {}
    for label in candidate.labels:
        candidate_labels.setdefault(label.iri, set()).add((label.lang, label.kind, label.text))
    for statement in candidate.statements:
        candidate_statements.setdefault(statement.subject_iri, set()).add(
            (statement.predicate, json.dumps(statement.object, sort_keys=True, separators=(",", ":")))
        )
    candidate_relations = {
        (relation.subject_iri, relation.predicate, relation.object_iri)
        for relation in candidate.relations
        if not relation.inferred
    }
    if base is None:
        return PublishDiff(
            added_iris=sorted(candidate_concepts),
            deprecated={
                iri: concept.replaced_by for iri, concept in sorted(candidate_concepts.items()) if concept.deprecated
            },
            relations_added=len(candidate_relations),
        )

    base_concepts = {concept.iri: concept for concept in base.concepts}
    base_labels = {}
    base_statements = {}
    for label in base.labels:
        base_labels.setdefault(label.iri, set()).add((label.lang, label.kind, label.text))
    for statement in base.statements:
        base_statements.setdefault(statement.subject_iri, set()).add(
            (statement.predicate, json.dumps(statement.object, sort_keys=True, separators=(",", ":")))
        )
    base_relations = {
        (relation.subject_iri, relation.predicate, relation.object_iri)
        for relation in base.relations
        if not relation.inferred
    }

    added_iris = sorted(set(candidate_concepts) - set(base_concepts))
    shared_iris = set(candidate_concepts) & set(base_concepts)
    changed_iris = sorted(
        iri
        for iri in shared_iris
        if candidate_concepts[iri] != base_concepts[iri]
        or candidate_labels.get(iri, set()) != base_labels.get(iri, set())
        or candidate_statements.get(iri, set()) != base_statements.get(iri, set())
    )
    deprecated = {
        iri: concept.replaced_by
        for iri, concept in sorted(candidate_concepts.items())
        if concept.deprecated and (iri not in base_concepts or not base_concepts[iri].deprecated)
    }
    return PublishDiff(
        added_iris=added_iris,
        changed_iris=changed_iris,
        deprecated=deprecated,
        relations_added=len(candidate_relations - base_relations),
        relations_closed=len(base_relations - candidate_relations),
    )
