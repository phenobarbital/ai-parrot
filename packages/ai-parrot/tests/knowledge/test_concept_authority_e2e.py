"""End-to-end integration tests for FEAT-159 concept-document-authority.

Tests the full OntologyRAGMixin pipeline for the commissions scenario using
deterministic mocks. No real DB, no real LLM.

Commissions scenario
--------------------
- Documents:
    sales-commissions-policy  (primary for commissions, tree_policy)
    commissions-faq           (mentions commissions, tree_faq)
    commissions-memo          (mentions commissions, tree_memo)
    bonus-policy              (primary for bonuses, tree_bonus)
- Concepts: commissions, sales-commissions (is_a commissions), bonuses, pto

Pipeline under test: OntologyRAGMixin.ontology_process with mocked:
    - OntologyGraphStore.execute_traversal
    - PgVectorStore.similarity_search
    - TenantOntologyManager
    - EntityResolver (hybrid_concept_match)

All 8 spec §4 scenarios are covered.
"""
from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from parrot.knowledge.ontology.cache import OntologyCache
from parrot.knowledge.ontology.graph_store import OntologyGraphStore
from parrot.knowledge.ontology.mixin import OntologyRAGMixin
from parrot.knowledge.ontology.schema import (
    ContextEnvelope,
    EntityDef,
    EntityExtractionRule,
    MergedOntology,
    PropertyDef,
    TenantContext,
    TraversalPattern,
)
from parrot.knowledge.ontology.tenant import TenantOntologyManager

# ── Document constants (mirrors conftest.py golden fixtures) ─────────────────

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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mixin(
    tenant_mgr: MagicMock,
    graph_store: AsyncMock | None,
    cache: AsyncMock,
    vector_store: AsyncMock | None = None,
) -> OntologyRAGMixin:
    """Create a standalone OntologyRAGMixin for testing."""
    mixin = OntologyRAGMixin.__new__(OntologyRAGMixin)
    mixin._ont_tenant_manager = tenant_mgr
    mixin._ont_graph_store = graph_store
    mixin._ont_vector_store = vector_store
    mixin._ont_cache = cache
    mixin._ont_llm_client = None
    mixin._ont_tool_manager = None
    return mixin


_USER_CTX = {"user_id": "employees/u1", "roles": ["employee"]}
_TENANT = "acme"

# This is the mocked entity resolution for commissions concept
_COMMISSIONS_RESOLVED = {"topic": "concepts/commissions"}
_BONUSES_RESOLVED = {"topic": "concepts/bonuses"}
_PTO_RESOLVED = {"topic": "concepts/pto"}


# ---------------------------------------------------------------------------
# Ontology builder
# ---------------------------------------------------------------------------


def _make_commissions_ontology() -> MergedOntology:
    """Build MergedOntology with authoritative_doc_for_topic and find_department patterns."""
    from datetime import datetime, timezone

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


# ---------------------------------------------------------------------------
# Pytest fixtures (local to this module)
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# E2E Test Class
# ---------------------------------------------------------------------------


class TestConceptAuthorityE2E:
    """8 end-to-end scenarios for concept-document authority pipeline."""

    # ------------------------------------------------------------------
    # Scenario 1: primary authority hit
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_e2e_primary_authority_hit(
        self,
        mock_tenant_mgr: MagicMock,
        mock_cache: AsyncMock,
        mock_graph_store: AsyncMock,
    ) -> None:
        """Commissions query → primary traversal returns policy → source=graph:primary."""
        with patch.object(OntologyRAGMixin, "_is_ontology_enabled", return_value=True), \
             patch(
                "parrot.knowledge.ontology.mixin.EntityResolver",
                autospec=True,
             ) as MockResolver:
            MockResolver.return_value.extract_and_resolve = AsyncMock(
                return_value=_COMMISSIONS_RESOLVED,
            )
            mixin = _make_mixin(mock_tenant_mgr, mock_graph_store, mock_cache)
            result = await mixin.ontology_process(
                "what is the policy on commissions",
                user_context=_USER_CTX,
                tenant_id=_TENANT,
            )

        assert isinstance(result, ContextEnvelope)
        assert result.state == "ok"
        assert result.context is not None
        assert result.context.source == "graph:primary"
        assert result.context.graph_context is not None
        assert len(result.context.graph_context) == 1
        assert result.context.graph_context[0]["doc_id"] == "sales-commissions-policy"

    # ------------------------------------------------------------------
    # Scenario 2: secondary authority hit when primary empty
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_e2e_secondary_authority_hit(
        self,
        mock_tenant_mgr: MagicMock,
        mock_cache: AsyncMock,
    ) -> None:
        """No primary result → secondary traversal returns FAQ + memo."""
        def _empty_primary_traversal(**kwargs: Any) -> list[dict]:
            level = kwargs.get("bind_vars", {}).get("authority_level", "")
            if level == "primary":
                return []
            if level == "secondary":
                return [COMMISSIONS_FAQ, COMMISSIONS_MEMO]
            return []

        graph_store = AsyncMock(spec=OntologyGraphStore)
        graph_store.execute_traversal.side_effect = _empty_primary_traversal

        with patch.object(OntologyRAGMixin, "_is_ontology_enabled", return_value=True), \
             patch(
                "parrot.knowledge.ontology.mixin.EntityResolver",
                autospec=True,
             ) as MockResolver:
            MockResolver.return_value.extract_and_resolve = AsyncMock(
                return_value=_COMMISSIONS_RESOLVED,
            )
            mixin = _make_mixin(mock_tenant_mgr, graph_store, mock_cache)
            result = await mixin.ontology_process(
                "what is the policy on commissions",
                user_context=_USER_CTX,
                tenant_id=_TENANT,
            )

        assert result.state == "ok"
        assert result.context.source == "graph:secondary"
        assert len(result.context.graph_context) == 2
        doc_ids = {d["doc_id"] for d in result.context.graph_context}
        assert "commissions-faq" in doc_ids
        assert "commissions-memo" in doc_ids

    # ------------------------------------------------------------------
    # Scenario 3: filtered vector fallback
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_e2e_filtered_vector_fallback(
        self,
        mock_tenant_mgr: MagicMock,
        mock_cache: AsyncMock,
        mock_vector_store: AsyncMock,
    ) -> None:
        """Both graph levels empty → filtered vector search succeeds."""
        graph_store = AsyncMock(spec=OntologyGraphStore)
        graph_store.execute_traversal.return_value = []  # Both levels empty

        with patch.object(OntologyRAGMixin, "_is_ontology_enabled", return_value=True), \
             patch(
                "parrot.knowledge.ontology.mixin.EntityResolver",
                autospec=True,
             ) as MockResolver:
            MockResolver.return_value.extract_and_resolve = AsyncMock(
                return_value=_COMMISSIONS_RESOLVED,
            )
            mixin = _make_mixin(mock_tenant_mgr, graph_store, mock_cache, mock_vector_store)
            result = await mixin.ontology_process(
                "what is the policy on commissions",
                user_context=_USER_CTX,
                tenant_id=_TENANT,
            )

        assert result.state == "ok"
        assert result.context.source == "vector:filtered"
        assert result.context.vector_context is not None
        assert result.context.vector_context[0]["doc_id"] == "filtered-policy-chunk"

    # ------------------------------------------------------------------
    # Scenario 4: plain vector fallback
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_e2e_plain_vector_fallback(
        self,
        mock_tenant_mgr: MagicMock,
        mock_cache: AsyncMock,
    ) -> None:
        """Graph empty + filtered vector empty → plain vector fallback."""
        graph_store = AsyncMock(spec=OntologyGraphStore)
        graph_store.execute_traversal.return_value = []

        async def _filtered_empty_plain_hit(query: str = "", **kwargs: Any) -> list[dict]:
            if kwargs.get("metadata_filters"):
                return []  # Level 3 empty
            return [PLAIN_VECTOR_DOC]  # Level 4 hit

        vector_store = AsyncMock()
        vector_store.similarity_search = AsyncMock(side_effect=_filtered_empty_plain_hit)

        with patch.object(OntologyRAGMixin, "_is_ontology_enabled", return_value=True), \
             patch(
                "parrot.knowledge.ontology.mixin.EntityResolver",
                autospec=True,
             ) as MockResolver:
            MockResolver.return_value.extract_and_resolve = AsyncMock(
                return_value=_COMMISSIONS_RESOLVED,
            )
            mixin = _make_mixin(mock_tenant_mgr, graph_store, mock_cache, vector_store)
            result = await mixin.ontology_process(
                "what is the policy on commissions",
                user_context=_USER_CTX,
                tenant_id=_TENANT,
            )

        assert result.state == "ok"
        assert result.context.source == "vector:plain"
        assert result.context.vector_context[0]["doc_id"] == "plain-chunk"

    # ------------------------------------------------------------------
    # Scenario 5: all levels exhausted
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_e2e_all_levels_exhausted(
        self,
        mock_tenant_mgr: MagicMock,
        mock_cache: AsyncMock,
    ) -> None:
        """All levels return empty → source="vector_only"."""
        graph_store = AsyncMock(spec=OntologyGraphStore)
        graph_store.execute_traversal.return_value = []

        vector_store = AsyncMock()
        vector_store.similarity_search = AsyncMock(return_value=[])

        with patch.object(OntologyRAGMixin, "_is_ontology_enabled", return_value=True), \
             patch(
                "parrot.knowledge.ontology.mixin.EntityResolver",
                autospec=True,
             ) as MockResolver:
            MockResolver.return_value.extract_and_resolve = AsyncMock(
                return_value=_COMMISSIONS_RESOLVED,
            )
            mixin = _make_mixin(mock_tenant_mgr, graph_store, mock_cache, vector_store)
            result = await mixin.ontology_process(
                "commissions policy",
                user_context=_USER_CTX,
                tenant_id=_TENANT,
            )

        assert result.state == "ok"
        assert result.context.source == "vector_only"

    # ------------------------------------------------------------------
    # Scenario 6: unrelated topic (pto) — non-commissions concept
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_e2e_unrelated_topic_falls_to_vector(
        self,
        mock_tenant_mgr: MagicMock,
        mock_cache: AsyncMock,
        mock_vector_store: AsyncMock,
    ) -> None:
        """Query about PTO (different concept) → graph empty → filtered vector hit."""
        def _pto_traversal(**kwargs: Any) -> list[dict]:
            # No primary/secondary results for PTO (no authority doc configured)
            return []

        graph_store = AsyncMock(spec=OntologyGraphStore)
        graph_store.execute_traversal.side_effect = _pto_traversal

        with patch.object(OntologyRAGMixin, "_is_ontology_enabled", return_value=True), \
             patch(
                "parrot.knowledge.ontology.mixin.EntityResolver",
                autospec=True,
             ) as MockResolver:
            MockResolver.return_value.extract_and_resolve = AsyncMock(
                return_value=_PTO_RESOLVED,
            )
            mixin = _make_mixin(mock_tenant_mgr, graph_store, mock_cache, mock_vector_store)
            result = await mixin.ontology_process(
                "what is the policy on pto",
                user_context=_USER_CTX,
                tenant_id=_TENANT,
            )

        assert result.state == "ok"
        # Falls to vector (filtered or plain depending on mock_vector_store behavior)
        assert result.context.source in ("vector:filtered", "vector:plain", "vector_only")

    # ------------------------------------------------------------------
    # Scenario 7: bonus policy — different primary doc
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_e2e_bonus_policy_primary_hit(
        self,
        mock_tenant_mgr: MagicMock,
        mock_cache: AsyncMock,
    ) -> None:
        """Query about bonuses → primary traversal returns bonus-policy."""
        def _bonus_traversal(**kwargs: Any) -> list[dict]:
            level = kwargs.get("bind_vars", {}).get("authority_level", "")
            if level == "primary":
                return [BONUS_POLICY]
            return []

        graph_store = AsyncMock(spec=OntologyGraphStore)
        graph_store.execute_traversal.side_effect = _bonus_traversal

        with patch.object(OntologyRAGMixin, "_is_ontology_enabled", return_value=True), \
             patch(
                "parrot.knowledge.ontology.mixin.EntityResolver",
                autospec=True,
             ) as MockResolver:
            MockResolver.return_value.extract_and_resolve = AsyncMock(
                return_value=_BONUSES_RESOLVED,
            )
            mixin = _make_mixin(mock_tenant_mgr, graph_store, mock_cache)
            result = await mixin.ontology_process(
                "what is the policy on bonuses",
                user_context=_USER_CTX,
                tenant_id=_TENANT,
            )

        assert result.state == "ok"
        assert result.context.source == "graph:primary"
        assert result.context.graph_context[0]["doc_id"] == "bonus-policy"

    # ------------------------------------------------------------------
    # Scenario 8: non-authority pattern uses single traversal (source=ontology)
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_e2e_standard_pattern_single_traversal(
        self,
        mock_tenant_mgr: MagicMock,
        mock_cache: AsyncMock,
    ) -> None:
        """find_department pattern (non-authority) → single traversal → source=ontology."""
        dept_row = {"name": "Engineering", "dept_id": "ENG"}
        graph_store = AsyncMock(spec=OntologyGraphStore)
        graph_store.execute_traversal.return_value = [dept_row]

        with patch.object(OntologyRAGMixin, "_is_ontology_enabled", return_value=True):
            mixin = _make_mixin(mock_tenant_mgr, graph_store, mock_cache)
            result = await mixin.ontology_process(
                "my department",
                user_context=_USER_CTX,
                tenant_id=_TENANT,
            )

        assert result.state == "ok"
        assert result.context.source == "ontology"
        assert result.context.graph_context == [dept_row]
        # Exactly one traversal — no authority_level in bind_vars
        assert graph_store.execute_traversal.call_count == 1
        call_kwargs = graph_store.execute_traversal.call_args.kwargs
        assert "authority_level" not in call_kwargs.get("bind_vars", {})
