"""Shared fixtures for concept authority e2e tests (FEAT-159 TASK-1092).

Provides deterministic mock data for the commissions scenario:

Documents
---------
- sales-commissions-policy: primary authority for commissions concept,
  pageindex_tree_id="tree_policy"
- commissions-faq: mentions commissions, pageindex_tree_id="tree_faq"
- commissions-memo: mentions commissions, pageindex_tree_id="tree_memo"
- bonus-policy: primary authority for bonuses concept,
  pageindex_tree_id="tree_bonus"

Concepts
--------
- commissions: root concept
- sales-commissions: is_a commissions
- bonuses: separate concept
- pto: unrelated concept

Graph traversal
---------------
Mocked via OntologyGraphStore.execute_traversal side-effects keyed on
bind_vars["authority_level"]:
- "primary"   → [sales-commissions-policy]
- "secondary" → [commissions-faq, commissions-memo]
- any other   → []

Vector search
-------------
Mocked via PgVectorStore.similarity_search side-effects:
- with metadata_filters {"doc_type": [...]} → [filtered vector doc]
- without filters                           → [plain vector doc]
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot.knowledge.ontology.cache import OntologyCache
from parrot.knowledge.ontology.graph_store import OntologyGraphStore
from parrot.knowledge.ontology.schema import (
    EntityDef,
    EntityExtractionRule,
    MergedOntology,
    PropertyDef,
    TenantContext,
    TraversalPattern,
)
from parrot.knowledge.ontology.tenant import TenantOntologyManager


# ── Documents ────────────────────────────────────────────────────────────────

SALES_COMMISSIONS_POLICY = {
    "_id": "documents/sales-commissions-policy",
    "doc_id": "sales-commissions-policy",
    "title": "Sales Commissions Policy",
    "doc_type": "policy",
    "authority": "primary",
    "pageindex_tree_id": "tree_policy",
}

COMMISSIONS_FAQ = {
    "_id": "documents/commissions-faq",
    "doc_id": "commissions-faq",
    "title": "Commissions FAQ",
    "doc_type": "faq",
    "authority": "mentions",
    "pageindex_tree_id": "tree_faq",
}

COMMISSIONS_MEMO = {
    "_id": "documents/commissions-memo",
    "doc_id": "commissions-memo",
    "title": "Q1 Commissions Memo",
    "doc_type": "memo",
    "authority": "mentions",
    "pageindex_tree_id": "tree_memo",
}

BONUS_POLICY = {
    "_id": "documents/bonus-policy",
    "doc_id": "bonus-policy",
    "title": "Bonus Policy",
    "doc_type": "policy",
    "authority": "primary",
    "pageindex_tree_id": "tree_bonus",
}

# ── Vector docs ──────────────────────────────────────────────────────────────

FILTERED_VECTOR_DOC = {
    "doc_id": "filtered-policy-chunk",
    "content": "Commission rates are determined by the regional sales manager.",
    "doc_type": "policy",
    "score": 0.91,
}

PLAIN_VECTOR_DOC = {
    "doc_id": "plain-chunk",
    "content": "Employees may receive commissions based on sales performance.",
    "score": 0.74,
}


# ── Ontology helpers ─────────────────────────────────────────────────────────


def _make_commissions_ontology() -> MergedOntology:
    """Build a MergedOntology with authoritative_doc_for_topic pattern."""
    return MergedOntology(
        name="acme-knowledge",
        version="1.0",
        entities={
            "Document": EntityDef(
                collection="documents",
                key_field="doc_id",
                properties=[
                    {"doc_id": PropertyDef(type="string")},
                    {"title": PropertyDef(type="string")},
                    {"doc_type": PropertyDef(type="string")},
                ],
            ),
            "Concept": EntityDef(
                collection="concepts",
                key_field="concept_id",
                properties=[
                    {"concept_id": PropertyDef(type="string")},
                    {"name": PropertyDef(type="string")},
                ],
            ),
        },
        relations={},
        traversal_patterns={
            "authoritative_doc_for_topic": TraversalPattern(
                description="Find authoritative document for concept topic",
                trigger_intents=["what is the policy on", "authority doc for"],
                query_template=(
                    "FOR doc IN documents "
                    "FILTER doc.authority == @authority_level "
                    "AND doc.concept_id == @topic_id "
                    "RETURN doc"
                ),
                post_action="none",
                entity_extraction={
                    "topic": EntityExtractionRule(
                        type="Concept",
                        resolver="hybrid_concept_match",
                        required=True,
                    ),
                },
            ),
            "find_department": TraversalPattern(
                description="Find department for employee",
                trigger_intents=["my department"],
                query_template="FOR v IN 1..1 OUTBOUND @user_id belongs_to RETURN v",
                post_action="none",
            ),
        },
        layers=["acme-knowledge"],
        merge_timestamp=datetime.now(timezone.utc),
    )


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
def acme_ontology() -> MergedOntology:
    """Shared MergedOntology for all commissions scenario tests."""
    return _make_commissions_ontology()


@pytest.fixture
def acme_tenant_ctx(acme_ontology: MergedOntology) -> TenantContext:
    """TenantContext for the Acme Corp scenario."""
    return TenantContext(
        tenant_id="acme",
        arango_db="acme_ontology",
        pgvector_schema="acme",
        ontology=acme_ontology,
    )


@pytest.fixture
def mock_tenant_mgr(acme_tenant_ctx: TenantContext) -> MagicMock:
    """TenantOntologyManager mock that returns acme_tenant_ctx."""
    mgr = MagicMock(spec=TenantOntologyManager)
    mgr.resolve.return_value = acme_tenant_ctx
    return mgr


@pytest.fixture
def mock_cache() -> AsyncMock:
    """OntologyCache mock — always a cache miss."""
    cache = AsyncMock(spec=OntologyCache)
    cache.get.return_value = None
    cache.build_key = OntologyCache.build_key
    return cache


@pytest.fixture
def mock_graph_store() -> AsyncMock:
    """Graph store mock with authority-level-based traversal results."""

    def _traversal_side_effect(**kwargs: Any) -> list[dict]:
        bind_vars = kwargs.get("bind_vars", {})
        level = bind_vars.get("authority_level", "")
        if level == "primary":
            return [SALES_COMMISSIONS_POLICY]
        if level == "secondary":
            return [COMMISSIONS_FAQ, COMMISSIONS_MEMO]
        return []

    store = AsyncMock(spec=OntologyGraphStore)
    store.execute_traversal.side_effect = _traversal_side_effect
    return store


@pytest.fixture
def mock_vector_store() -> AsyncMock:
    """Vector store mock — returns different results based on metadata_filters."""

    async def _search_side_effect(query: str = "", **kwargs: Any) -> list[dict]:
        metadata_filters = kwargs.get("metadata_filters")
        if metadata_filters:
            return [FILTERED_VECTOR_DOC]
        return [PLAIN_VECTOR_DOC]

    store = AsyncMock()
    store.similarity_search = AsyncMock(side_effect=_search_side_effect)
    return store
