"""Universal meta-ontology for GraphIndex.

Provides the programmatic ``MergedOntology``-compatible definition with:
- 6 entity types: document, section, symbol, concept, rationale, skill
- 5 relation types: contains, references, defines, mentions, explains

These definitions are **additive** — they do not conflict with existing
tenant ontologies.  They are intended to be merged at tenant initialisation
time via ``OntologyMerger``.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from parrot.knowledge.ontology.schema import (
    DiscoveryConfig,
    EntityDef,
    MergedOntology,
    PropertyDef,
    RelationDef,
    TraversalPattern,
)

# ---------------------------------------------------------------------------
# Entity definitions (6 vertex collections)
# ---------------------------------------------------------------------------

_ENTITY_DEFS: dict[str, EntityDef] = {
    "document": EntityDef(
        collection="gi_documents",
        key_field="node_id",
        properties=[
            {"title": PropertyDef(type="string", required=True)},
            {"source_uri": PropertyDef(type="string", required=True)},
            {"kind": PropertyDef(type="string", required=True)},
            {"summary": PropertyDef(type="string", required=False)},
            {"content_ref": PropertyDef(type="string", required=False)},
            {"embedding_ref": PropertyDef(type="string", required=False)},
            {"provenance": PropertyDef(type="string", required=True)},
        ],
        vectorize=["summary", "title"],
        extend=False,
    ),
    "section": EntityDef(
        collection="gi_sections",
        key_field="node_id",
        properties=[
            {"title": PropertyDef(type="string", required=True)},
            {"source_uri": PropertyDef(type="string", required=True)},
            {"kind": PropertyDef(type="string", required=True)},
            {"summary": PropertyDef(type="string", required=False)},
            {"content_ref": PropertyDef(type="string", required=False)},
            {"embedding_ref": PropertyDef(type="string", required=False)},
            {"parent_id": PropertyDef(type="string", required=False)},
            {"provenance": PropertyDef(type="string", required=True)},
        ],
        vectorize=["summary", "title"],
        extend=False,
    ),
    "symbol": EntityDef(
        collection="gi_symbols",
        key_field="node_id",
        properties=[
            {"title": PropertyDef(type="string", required=True)},
            {"source_uri": PropertyDef(type="string", required=True)},
            {"kind": PropertyDef(type="string", required=True)},
            {"summary": PropertyDef(type="string", required=False)},
            {"content_ref": PropertyDef(type="string", required=False)},
            {"embedding_ref": PropertyDef(type="string", required=False)},
            {"provenance": PropertyDef(type="string", required=True)},
        ],
        vectorize=["summary", "title"],
        extend=False,
    ),
    "concept": EntityDef(
        collection="gi_concepts",
        key_field="node_id",
        properties=[
            {"title": PropertyDef(type="string", required=True)},
            {"source_uri": PropertyDef(type="string", required=True)},
            {"kind": PropertyDef(type="string", required=True)},
            {"summary": PropertyDef(type="string", required=False)},
            {"embedding_ref": PropertyDef(type="string", required=False)},
            {"provenance": PropertyDef(type="string", required=True)},
        ],
        vectorize=["summary", "title"],
        extend=False,
    ),
    "rationale": EntityDef(
        collection="gi_rationales",
        key_field="node_id",
        properties=[
            {"title": PropertyDef(type="string", required=True)},
            {"source_uri": PropertyDef(type="string", required=True)},
            {"kind": PropertyDef(type="string", required=True)},
            {"summary": PropertyDef(type="string", required=False)},
            {"content_ref": PropertyDef(type="string", required=False)},
            {"embedding_ref": PropertyDef(type="string", required=False)},
            {"provenance": PropertyDef(type="string", required=True)},
        ],
        vectorize=["summary", "title"],
        extend=False,
    ),
    "skill": EntityDef(
        collection="gi_skills",
        key_field="node_id",
        properties=[
            {"title": PropertyDef(type="string", required=True)},
            {"source_uri": PropertyDef(type="string", required=True)},
            {"kind": PropertyDef(type="string", required=True)},
            {"summary": PropertyDef(type="string", required=False)},
            {"embedding_ref": PropertyDef(type="string", required=False)},
            {"provenance": PropertyDef(type="string", required=True)},
        ],
        vectorize=["summary", "title"],
        extend=False,
    ),
}


# ---------------------------------------------------------------------------
# Relation definitions (5 edge collections)
# ---------------------------------------------------------------------------

_RELATION_DEFS: dict[str, RelationDef] = {
    "contains": RelationDef(**{
        "from": "*",
        "to": "*",
        "edge_collection": "gi_contains",
        "properties": [
            {"provenance": PropertyDef(type="string", required=True)},
        ],
        "discovery": DiscoveryConfig(strategy="field_match"),
    }),
    "references": RelationDef(**{
        "from": "*",
        "to": "*",
        "edge_collection": "gi_references",
        "properties": [
            {"provenance": PropertyDef(type="string", required=True)},
        ],
        "discovery": DiscoveryConfig(strategy="field_match"),
    }),
    "defines": RelationDef(**{
        "from": "*",
        "to": "*",
        "edge_collection": "gi_defines",
        "properties": [
            {"provenance": PropertyDef(type="string", required=True)},
        ],
        "discovery": DiscoveryConfig(strategy="field_match"),
    }),
    "mentions": RelationDef(**{
        "from": "*",
        "to": "*",
        "edge_collection": "gi_mentions",
        "properties": [
            {"provenance": PropertyDef(type="string", required=True)},
            {"confidence": PropertyDef(type="float", required=False)},
        ],
        "discovery": DiscoveryConfig(strategy="ai_assisted"),
    }),
    "explains": RelationDef(**{
        "from": "*",
        "to": "*",
        "edge_collection": "gi_explains",
        "properties": [
            {"provenance": PropertyDef(type="string", required=True)},
        ],
        "discovery": DiscoveryConfig(strategy="field_match"),
    }),
}


# ---------------------------------------------------------------------------
# Public helper
# ---------------------------------------------------------------------------

# Collection name → NodeKind string  (for persistence routing)
COLLECTION_TO_KIND: dict[str, str] = {
    "gi_documents": "document",
    "gi_sections": "section",
    "gi_symbols": "symbol",
    "gi_concepts": "concept",
    "gi_rationales": "rationale",
    "gi_skills": "skill",
}

# NodeKind string → collection name
KIND_TO_COLLECTION: dict[str, str] = {v: k for k, v in COLLECTION_TO_KIND.items()}

# EdgeKind string → edge collection name
EDGE_KIND_TO_COLLECTION: dict[str, str] = {
    "contains": "gi_contains",
    "references": "gi_references",
    "defines": "gi_defines",
    "mentions": "gi_mentions",
    "explains": "gi_explains",
}


def build_graphindex_ontology() -> MergedOntology:
    """Return the universal GraphIndex meta-ontology as a ``MergedOntology``.

    The returned object is additive — it defines new collections prefixed
    with ``gi_`` that do not overlap with any existing tenant ontology.

    Returns:
        A ``MergedOntology`` instance with 6 entities and 5 relations.
    """
    return MergedOntology(
        name="graphindex-meta-ontology",
        version="1.0",
        entities=_ENTITY_DEFS,
        relations=_RELATION_DEFS,
        traversal_patterns={},
        layers=["graphindex-meta-ontology:builtin"],
        merge_timestamp=datetime.now(tz=timezone.utc),
    )
