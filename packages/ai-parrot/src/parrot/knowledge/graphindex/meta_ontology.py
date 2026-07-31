"""Universal meta-ontology for GraphIndex.

Provides the programmatic ``MergedOntology``-compatible definition with:
- 9 entity types: document, section, symbol, concept, rationale, skill,
  wiki_page, run, claim
- 10 relation types: contains, references, defines, mentions, explains,
  extends, produced, about, supported_by, contradicts

These definitions are **additive** — they do not conflict with existing
tenant ontologies.  They are intended to be merged at tenant initialisation
time via ``OntologyMerger``.

FEAT-377 TASK-1909: ``wiki_page``/``run``/``claim`` entities and
``produced``/``about``/``supported_by``/``contradicts`` relations complete
the mapping so ``NodeKind``/``EdgeKind`` (``schema.py``) route fully —
these are the agent graph-memory kinds (work lineage, assertions) that
``persist.py``'s ``_upsert_nodes``/``_create_edges`` previously dropped
with an "Unknown kind" warning. ``build_graphindex_ontology()`` is used
as the tenant ontology by ``GraphIndexLoader`` (see its docstring at
``loader.py:198-201``), so ``initialize_tenant`` provisions these new
``gi_*`` collections automatically from ``_ENTITY_DEFS``/``_RELATION_DEFS``
— no separate collection-creation code to update.
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
# Entity definitions (9 vertex collections)
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
    "wiki_page": EntityDef(
        collection="gi_wiki_pages",
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
    "run": EntityDef(
        collection="gi_runs",
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
    "claim": EntityDef(
        collection="gi_claims",
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
}


# ---------------------------------------------------------------------------
# Relation definitions (10 edge collections)
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
    "extends": RelationDef(**{
        "from": "*",
        "to": "*",
        "edge_collection": "gi_extends",
        "properties": [
            {"provenance": PropertyDef(type="string", required=True)},
        ],
        "discovery": DiscoveryConfig(strategy="field_match"),
    }),
    "produced": RelationDef(**{
        "from": "*",
        "to": "*",
        "edge_collection": "gi_produced",
        "properties": [
            {"provenance": PropertyDef(type="string", required=True)},
        ],
        "discovery": DiscoveryConfig(strategy="field_match"),
    }),
    "about": RelationDef(**{
        "from": "*",
        "to": "*",
        "edge_collection": "gi_about",
        "properties": [
            {"provenance": PropertyDef(type="string", required=True)},
        ],
        "discovery": DiscoveryConfig(strategy="field_match"),
    }),
    "supported_by": RelationDef(**{
        "from": "*",
        "to": "*",
        "edge_collection": "gi_supported_by",
        "properties": [
            {"provenance": PropertyDef(type="string", required=True)},
        ],
        "discovery": DiscoveryConfig(strategy="field_match"),
    }),
    "contradicts": RelationDef(**{
        "from": "*",
        "to": "*",
        "edge_collection": "gi_contradicts",
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
    "gi_wiki_pages": "wiki_page",
    "gi_runs": "run",
    "gi_claims": "claim",
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
    "extends": "gi_extends",
    "produced": "gi_produced",
    "about": "gi_about",
    "supported_by": "gi_supported_by",
    "contradicts": "gi_contradicts",
}


def build_graphindex_ontology() -> MergedOntology:
    """Return the universal GraphIndex meta-ontology as a ``MergedOntology``.

    The returned object is additive — it defines new collections prefixed
    with ``gi_`` that do not overlap with any existing tenant ontology.

    Returns:
        A ``MergedOntology`` instance with 9 entities and 10 relations.
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
