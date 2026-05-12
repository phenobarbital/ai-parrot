"""Tests for OntologyRAGMixin 4-level degradation chain (FEAT-159 TASK-1090).

Covers:
- Level 1: primary authority traversal returns results → source="graph:primary"
- Level 2: primary empty, secondary returns results → source="graph:secondary"
- Level 3: both graph levels empty, filtered vector search hits → source="vector:filtered"
- Level 4: filtered vector empty, plain vector search hits → source="vector:plain"
- All levels exhausted → source="vector_only"
- Non-authority patterns: single traversal → source="ontology"
- Non-authority fallback to vector levels when graph empty
- Bypass conditions (ambiguous, denied, entity_not_found) still short-circuit before chain
"""
from __future__ import annotations

from datetime import datetime, timezone
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


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

_AUTHORITY_PATTERN_TRIGGERS = ["what is the policy on", "authority doc for"]


def _make_authority_ontology() -> MergedOntology:
    """Create a MergedOntology with an ``authoritative_doc_for_topic`` pattern."""
    return MergedOntology(
        name="test",
        version="1.0",
        entities={
            "Document": EntityDef(
                collection="documents",
                key_field="doc_id",
                properties=[{"doc_id": PropertyDef(type="string")}],
            ),
        },
        relations={},
        traversal_patterns={
            "authoritative_doc_for_topic": TraversalPattern(
                description="Find authoritative document for topic",
                trigger_intents=_AUTHORITY_PATTERN_TRIGGERS,
                query_template=(
                    "FOR doc IN documents FILTER doc.authority_level == @authority_level "
                    "RETURN doc"
                ),
                post_action="none",
                entity_extraction={
                    "topic": EntityExtractionRule(
                        type="Document",
                        resolver="hybrid_concept_match",
                    ),
                },
            ),
        },
        layers=["test"],
        merge_timestamp=datetime.now(timezone.utc),
    )


def _make_standard_ontology() -> MergedOntology:
    """Create a MergedOntology with a non-authority pattern."""
    return MergedOntology(
        name="test",
        version="1.0",
        entities={
            "Employee": EntityDef(
                collection="employees",
                key_field="employee_id",
                properties=[{"employee_id": PropertyDef(type="string")}],
            ),
        },
        relations={},
        traversal_patterns={
            "find_department": TraversalPattern(
                description="Find department for employee",
                trigger_intents=["my department"],
                query_template="FOR v IN 1..1 OUTBOUND @user_id belongs_to RETURN v",
                post_action="none",
            ),
        },
        layers=["test"],
        merge_timestamp=datetime.now(timezone.utc),
    )


def _make_mixin(
    tenant_mgr: MagicMock,
    graph_store: AsyncMock | None,
    cache: AsyncMock,
    vector_store: AsyncMock | None = None,
    tool_manager: MagicMock | None = None,
) -> OntologyRAGMixin:
    """Create a standalone OntologyRAGMixin instance for testing."""
    mixin = OntologyRAGMixin.__new__(OntologyRAGMixin)
    mixin._ont_tenant_manager = tenant_mgr
    mixin._ont_graph_store = graph_store
    mixin._ont_vector_store = vector_store
    mixin._ont_cache = cache
    mixin._ont_llm_client = None
    mixin._ont_tool_manager = tool_manager
    return mixin


@pytest.fixture
def authority_tenant_ctx() -> TenantContext:
    """TenantContext with authoritative_doc_for_topic pattern."""
    return TenantContext(
        tenant_id="acme",
        arango_db="acme_ontology",
        pgvector_schema="acme",
        ontology=_make_authority_ontology(),
    )


@pytest.fixture
def standard_tenant_ctx() -> TenantContext:
    """TenantContext with a standard non-authority pattern."""
    return TenantContext(
        tenant_id="acme",
        arango_db="acme_ontology",
        pgvector_schema="acme",
        ontology=_make_standard_ontology(),
    )


@pytest.fixture
def mock_cache() -> AsyncMock:
    """Cache mock that always misses."""
    cache = AsyncMock(spec=OntologyCache)
    cache.get.return_value = None
    cache.build_key = OntologyCache.build_key
    return cache


@pytest.fixture
def mock_graph_store() -> AsyncMock:
    return AsyncMock(spec=OntologyGraphStore)


@pytest.fixture
def user_context() -> dict:
    return {"user_id": "employees/u1"}


# ---------------------------------------------------------------------------
# 4-Level Degradation Chain Tests
# ---------------------------------------------------------------------------


class TestDegradationChain:
    """Tests for the 4-level degradation chain on authoritative_doc_for_topic."""

    @pytest.mark.asyncio
    async def test_level1_primary_returns_graph_primary(
        self,
        authority_tenant_ctx: TenantContext,
        mock_cache: AsyncMock,
        mock_graph_store: AsyncMock,
        user_context: dict,
    ) -> None:
        """Level 1: primary traversal returns results → source="graph:primary"."""
        mock_tenant_mgr = MagicMock(spec=TenantOntologyManager)
        mock_tenant_mgr.resolve.return_value = authority_tenant_ctx

        policy_row = {"_id": "documents/policy_1", "title": "Sales Commissions Policy"}
        # primary returns results, secondary should NOT be called
        mock_graph_store.execute_traversal.return_value = [policy_row]

        with patch.object(OntologyRAGMixin, "_is_ontology_enabled", return_value=True), \
             patch(
                "parrot.knowledge.ontology.mixin.EntityResolver",
                autospec=True,
             ) as MockResolver:
            MockResolver.return_value.extract_and_resolve = AsyncMock(
                return_value={"topic": "documents/policy_1"}
            )
            mixin = _make_mixin(mock_tenant_mgr, mock_graph_store, mock_cache)
            result = await mixin.ontology_process(
                "what is the policy on commissions",
                user_context=user_context,
                tenant_id="acme",
            )

        assert isinstance(result, ContextEnvelope)
        assert result.state == "ok"
        assert result.context is not None
        assert result.context.source == "graph:primary"
        assert result.context.graph_context == [policy_row]
        # Level 1 call uses authority_level="primary"
        call_args = mock_graph_store.execute_traversal.call_args_list[0]
        assert call_args.kwargs.get("bind_vars", {}).get("authority_level") == "primary"

    @pytest.mark.asyncio
    async def test_level2_secondary_when_primary_empty(
        self,
        authority_tenant_ctx: TenantContext,
        mock_cache: AsyncMock,
        mock_graph_store: AsyncMock,
        user_context: dict,
    ) -> None:
        """Level 2: primary empty, secondary returns results → source="graph:secondary"."""
        mock_tenant_mgr = MagicMock(spec=TenantOntologyManager)
        mock_tenant_mgr.resolve.return_value = authority_tenant_ctx

        faq_row = {"_id": "documents/faq_1", "title": "Commissions FAQ"}

        def traversal_side_effect(**kwargs: dict) -> list:
            level = kwargs.get("bind_vars", {}).get("authority_level", "")
            if level == "primary":
                return []  # Level 1 empty
            if level == "secondary":
                return [faq_row]  # Level 2 hit
            return []

        mock_graph_store.execute_traversal.side_effect = traversal_side_effect

        with patch.object(OntologyRAGMixin, "_is_ontology_enabled", return_value=True), \
             patch(
                "parrot.knowledge.ontology.mixin.EntityResolver",
                autospec=True,
             ) as MockResolver:
            MockResolver.return_value.extract_and_resolve = AsyncMock(
                return_value={"topic": "documents/policy_1"}
            )
            mixin = _make_mixin(mock_tenant_mgr, mock_graph_store, mock_cache)
            result = await mixin.ontology_process(
                "what is the policy on commissions",
                user_context=user_context,
                tenant_id="acme",
            )

        assert isinstance(result, ContextEnvelope)
        assert result.state == "ok"
        assert result.context is not None
        assert result.context.source == "graph:secondary"
        assert result.context.graph_context == [faq_row]
        assert mock_graph_store.execute_traversal.call_count == 2

    @pytest.mark.asyncio
    async def test_level3_filtered_vector_when_graph_empty(
        self,
        authority_tenant_ctx: TenantContext,
        mock_cache: AsyncMock,
        mock_graph_store: AsyncMock,
        user_context: dict,
    ) -> None:
        """Level 3: both graph levels empty, filtered vector search succeeds."""
        mock_tenant_mgr = MagicMock(spec=TenantOntologyManager)
        mock_tenant_mgr.resolve.return_value = authority_tenant_ctx
        mock_graph_store.execute_traversal.return_value = []  # Both levels empty

        filtered_doc = {"doc_id": "policy_manual_1", "content": "Commission rules"}
        mock_vector_store = AsyncMock()
        mock_vector_store.similarity_search.side_effect = [
            [filtered_doc],  # Level 3 filtered call
        ]

        with patch.object(OntologyRAGMixin, "_is_ontology_enabled", return_value=True), \
             patch(
                "parrot.knowledge.ontology.mixin.EntityResolver",
                autospec=True,
             ) as MockResolver:
            MockResolver.return_value.extract_and_resolve = AsyncMock(
                return_value={"topic": "documents/policy_1"}
            )
            mixin = _make_mixin(
                mock_tenant_mgr, mock_graph_store, mock_cache,
                vector_store=mock_vector_store,
            )
            result = await mixin.ontology_process(
                "what is the policy on commissions",
                user_context=user_context,
                tenant_id="acme",
            )

        assert isinstance(result, ContextEnvelope)
        assert result.state == "ok"
        assert result.context is not None
        assert result.context.source == "vector:filtered"
        assert result.context.vector_context == [filtered_doc]
        # Level 3 is called with metadata_filters
        level3_call = mock_vector_store.similarity_search.call_args_list[0]
        assert "metadata_filters" in level3_call.kwargs
        assert "doc_type" in level3_call.kwargs["metadata_filters"]

    @pytest.mark.asyncio
    async def test_level4_plain_vector_when_filtered_empty(
        self,
        authority_tenant_ctx: TenantContext,
        mock_cache: AsyncMock,
        mock_graph_store: AsyncMock,
        user_context: dict,
    ) -> None:
        """Level 4: filtered vector empty, plain vector search succeeds."""
        mock_tenant_mgr = MagicMock(spec=TenantOntologyManager)
        mock_tenant_mgr.resolve.return_value = authority_tenant_ctx
        mock_graph_store.execute_traversal.return_value = []

        plain_doc = {"doc_id": "some_doc", "content": "Some related content"}
        mock_vector_store = AsyncMock()
        mock_vector_store.similarity_search.side_effect = [
            [],         # Level 3: filtered → empty
            [plain_doc],  # Level 4: plain → hit
        ]

        with patch.object(OntologyRAGMixin, "_is_ontology_enabled", return_value=True), \
             patch(
                "parrot.knowledge.ontology.mixin.EntityResolver",
                autospec=True,
             ) as MockResolver:
            MockResolver.return_value.extract_and_resolve = AsyncMock(
                return_value={"topic": "documents/policy_1"}
            )
            mixin = _make_mixin(
                mock_tenant_mgr, mock_graph_store, mock_cache,
                vector_store=mock_vector_store,
            )
            result = await mixin.ontology_process(
                "what is the policy on commissions",
                user_context=user_context,
                tenant_id="acme",
            )

        assert isinstance(result, ContextEnvelope)
        assert result.state == "ok"
        assert result.context is not None
        assert result.context.source == "vector:plain"
        assert result.context.vector_context == [plain_doc]
        assert mock_vector_store.similarity_search.call_count == 2

    @pytest.mark.asyncio
    async def test_all_levels_exhausted_returns_vector_only(
        self,
        authority_tenant_ctx: TenantContext,
        mock_cache: AsyncMock,
        mock_graph_store: AsyncMock,
        user_context: dict,
    ) -> None:
        """All levels exhausted → source="vector_only"."""
        mock_tenant_mgr = MagicMock(spec=TenantOntologyManager)
        mock_tenant_mgr.resolve.return_value = authority_tenant_ctx
        mock_graph_store.execute_traversal.return_value = []

        mock_vector_store = AsyncMock()
        mock_vector_store.similarity_search.return_value = []  # All vector levels empty

        with patch.object(OntologyRAGMixin, "_is_ontology_enabled", return_value=True), \
             patch(
                "parrot.knowledge.ontology.mixin.EntityResolver",
                autospec=True,
             ) as MockResolver:
            MockResolver.return_value.extract_and_resolve = AsyncMock(
                return_value={"topic": "documents/policy_1"}
            )
            mixin = _make_mixin(
                mock_tenant_mgr, mock_graph_store, mock_cache,
                vector_store=mock_vector_store,
            )
            result = await mixin.ontology_process(
                "what is the policy on commissions",
                user_context=user_context,
                tenant_id="acme",
            )

        assert isinstance(result, ContextEnvelope)
        assert result.state == "ok"
        assert result.context is not None
        assert result.context.source == "vector_only"

    @pytest.mark.asyncio
    async def test_all_levels_no_vector_store_returns_vector_only(
        self,
        authority_tenant_ctx: TenantContext,
        mock_cache: AsyncMock,
        mock_graph_store: AsyncMock,
        user_context: dict,
    ) -> None:
        """Graph empty + no vector store → source="vector_only"."""
        mock_tenant_mgr = MagicMock(spec=TenantOntologyManager)
        mock_tenant_mgr.resolve.return_value = authority_tenant_ctx
        mock_graph_store.execute_traversal.return_value = []

        with patch.object(OntologyRAGMixin, "_is_ontology_enabled", return_value=True), \
             patch(
                "parrot.knowledge.ontology.mixin.EntityResolver",
                autospec=True,
             ) as MockResolver:
            MockResolver.return_value.extract_and_resolve = AsyncMock(
                return_value={"topic": "documents/policy_1"}
            )
            mixin = _make_mixin(
                mock_tenant_mgr, mock_graph_store, mock_cache,
                vector_store=None,  # no vector store
            )
            result = await mixin.ontology_process(
                "what is the policy on commissions",
                user_context=user_context,
                tenant_id="acme",
            )

        assert isinstance(result, ContextEnvelope)
        assert result.state == "ok"
        assert result.context is not None
        assert result.context.source == "vector_only"


class TestNonAuthorityPatterns:
    """Tests that non-authority patterns use single traversal (source="ontology")."""

    @pytest.mark.asyncio
    async def test_standard_pattern_uses_single_traversal(
        self,
        standard_tenant_ctx: TenantContext,
        mock_cache: AsyncMock,
        mock_graph_store: AsyncMock,
        user_context: dict,
    ) -> None:
        """Non-authority pattern succeeds → source="ontology", no authority_level bind var."""
        mock_tenant_mgr = MagicMock(spec=TenantOntologyManager)
        mock_tenant_mgr.resolve.return_value = standard_tenant_ctx
        mock_graph_store.execute_traversal.return_value = [
            {"name": "Engineering", "dept_id": "ENG"}
        ]

        with patch.object(OntologyRAGMixin, "_is_ontology_enabled", return_value=True):
            mixin = _make_mixin(mock_tenant_mgr, mock_graph_store, mock_cache)
            result = await mixin.ontology_process(
                "my department",
                user_context=user_context,
                tenant_id="acme",
            )

        assert isinstance(result, ContextEnvelope)
        assert result.state == "ok"
        assert result.context is not None
        assert result.context.source == "ontology"
        # Only one traversal call, no authority_level in bind_vars
        assert mock_graph_store.execute_traversal.call_count == 1
        call_kwargs = mock_graph_store.execute_traversal.call_args.kwargs
        assert "authority_level" not in call_kwargs.get("bind_vars", {})

    @pytest.mark.asyncio
    async def test_standard_pattern_falls_to_vector_levels_when_empty(
        self,
        standard_tenant_ctx: TenantContext,
        mock_cache: AsyncMock,
        mock_graph_store: AsyncMock,
        user_context: dict,
    ) -> None:
        """Non-authority pattern empty graph → vector fallback levels still apply."""
        mock_tenant_mgr = MagicMock(spec=TenantOntologyManager)
        mock_tenant_mgr.resolve.return_value = standard_tenant_ctx
        mock_graph_store.execute_traversal.return_value = []

        plain_doc = {"doc_id": "doc1", "content": "Department info"}
        mock_vector_store = AsyncMock()
        mock_vector_store.similarity_search.side_effect = [
            [],          # Level 3 filtered → empty
            [plain_doc], # Level 4 plain → hit
        ]

        with patch.object(OntologyRAGMixin, "_is_ontology_enabled", return_value=True):
            mixin = _make_mixin(
                mock_tenant_mgr, mock_graph_store, mock_cache,
                vector_store=mock_vector_store,
            )
            result = await mixin.ontology_process(
                "my department",
                user_context=user_context,
                tenant_id="acme",
            )

        assert isinstance(result, ContextEnvelope)
        assert result.state == "ok"
        assert result.context.source == "vector:plain"


class TestBypassConditions:
    """Tests that bypass conditions (ambiguous, denied, entity_not_found) short-circuit."""

    @pytest.mark.asyncio
    async def test_ambiguous_bypasses_chain(
        self,
        authority_tenant_ctx: TenantContext,
        mock_cache: AsyncMock,
        mock_graph_store: AsyncMock,
        user_context: dict,
    ) -> None:
        """Ambiguous entity resolution still short-circuits before the chain."""
        from parrot.knowledge.ontology.entity_resolver import EntityAmbiguityError

        mock_tenant_mgr = MagicMock(spec=TenantOntologyManager)
        mock_tenant_mgr.resolve.return_value = authority_tenant_ctx

        with patch.object(OntologyRAGMixin, "_is_ontology_enabled", return_value=True), \
             patch(
                "parrot.knowledge.ontology.mixin.EntityResolver",
                autospec=True,
             ) as MockResolver:
            MockResolver.return_value.extract_and_resolve = AsyncMock(
                side_effect=EntityAmbiguityError(
                    rule_name="topic",
                    mention="commissions",
                    candidates=[
                        {"_id": "d/1", "name": "Sales Commissions"},
                        {"_id": "d/2", "name": "Broker Commissions"},
                    ],
                )
            )
            mixin = _make_mixin(mock_tenant_mgr, mock_graph_store, mock_cache)
            result = await mixin.ontology_process(
                "what is the policy on commissions",
                user_context=user_context,
                tenant_id="acme",
            )

        assert result.state == "ambiguous"
        mock_graph_store.execute_traversal.assert_not_called()

    @pytest.mark.asyncio
    async def test_entity_not_found_bypasses_chain(
        self,
        authority_tenant_ctx: TenantContext,
        mock_cache: AsyncMock,
        mock_graph_store: AsyncMock,
        user_context: dict,
    ) -> None:
        """entity_not_found still short-circuits before the chain."""
        from parrot.knowledge.ontology.entity_resolver import EntityNotFoundError

        mock_tenant_mgr = MagicMock(spec=TenantOntologyManager)
        mock_tenant_mgr.resolve.return_value = authority_tenant_ctx

        with patch.object(OntologyRAGMixin, "_is_ontology_enabled", return_value=True), \
             patch(
                "parrot.knowledge.ontology.mixin.EntityResolver",
                autospec=True,
             ) as MockResolver:
            MockResolver.return_value.extract_and_resolve = AsyncMock(
                side_effect=EntityNotFoundError(rule_name="topic", mention="unknown_topic")
            )
            mixin = _make_mixin(mock_tenant_mgr, mock_graph_store, mock_cache)
            result = await mixin.ontology_process(
                "what is the policy on unknown_topic",
                user_context=user_context,
                tenant_id="acme",
            )

        assert result.state == "entity_not_found"
        mock_graph_store.execute_traversal.assert_not_called()
