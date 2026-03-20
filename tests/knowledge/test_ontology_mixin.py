"""Tests for OntologyRAGMixin pipeline orchestrator."""
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from parrot.knowledge.ontology.cache import OntologyCache
from parrot.knowledge.ontology.graph_store import OntologyGraphStore
from parrot.knowledge.ontology.mixin import OntologyRAGMixin
from parrot.knowledge.ontology.schema import (
    EntityDef,
    EnrichedContext,
    MergedOntology,
    PropertyDef,
    RelationDef,
    TenantContext,
    TraversalPattern,
)
from parrot.knowledge.ontology.tenant import TenantOntologyManager


@pytest.fixture
def ontology() -> MergedOntology:
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
            "find_dept": TraversalPattern(
                description="Find department",
                trigger_intents=["my department"],
                query_template="FOR v IN 1..1 OUTBOUND @user_id belongs_to RETURN v",
                post_action="none",
            ),
            "find_portal": TraversalPattern(
                description="Find portal",
                trigger_intents=["my portal"],
                query_template="FOR v IN 1..2 OUTBOUND @user_id assigned_to RETURN v",
                post_action="vector_search",
                post_query="portal_url",
            ),
        },
        layers=["test"],
        merge_timestamp=datetime.now(timezone.utc),
    )


@pytest.fixture
def tenant_ctx(ontology) -> TenantContext:
    return TenantContext(
        tenant_id="test",
        arango_db="test_ontology",
        pgvector_schema="test",
        ontology=ontology,
    )


@pytest.fixture
def mock_tenant_mgr(tenant_ctx):
    mgr = MagicMock(spec=TenantOntologyManager)
    mgr.resolve.return_value = tenant_ctx
    return mgr


@pytest.fixture
def mock_graph_store():
    store = AsyncMock(spec=OntologyGraphStore)
    store.execute_traversal.return_value = [
        {"name": "Engineering", "dept_id": "ENG"},
    ]
    return store


@pytest.fixture
def mock_cache():
    cache = AsyncMock(spec=OntologyCache)
    cache.get.return_value = None  # Default: cache miss
    cache.build_key = OntologyCache.build_key  # Use real static method
    return cache


@pytest.fixture
def user_context():
    return {"user_id": "employees/emp_001"}


def _make_mixin(tenant_mgr, graph_store, cache, vector_store=None, llm=None):
    """Create an OntologyRAGMixin instance (standalone, not mixed in)."""
    mixin = OntologyRAGMixin.__new__(OntologyRAGMixin)
    mixin._ont_tenant_manager = tenant_mgr
    mixin._ont_graph_store = graph_store
    mixin._ont_vector_store = vector_store
    mixin._ont_cache = cache
    mixin._ont_llm_client = llm
    return mixin


class TestGraphQueryFlow:

    @pytest.mark.asyncio
    async def test_full_pipeline(self, mock_tenant_mgr, mock_graph_store, mock_cache, user_context):
        with patch.object(OntologyRAGMixin, '_is_ontology_enabled', return_value=True):
            mixin = _make_mixin(mock_tenant_mgr, mock_graph_store, mock_cache)
            result = await mixin.ontology_process(
                "What is my department?", user_context, "test",
            )
            assert result.source == "ontology"
            assert result.graph_context is not None
            assert len(result.graph_context) == 1
            assert result.graph_context[0]["name"] == "Engineering"
            assert result.intent.action == "graph_query"
            assert result.intent.source == "fast_path"

    @pytest.mark.asyncio
    async def test_caches_result(self, mock_tenant_mgr, mock_graph_store, mock_cache, user_context):
        with patch.object(OntologyRAGMixin, '_is_ontology_enabled', return_value=True):
            mixin = _make_mixin(mock_tenant_mgr, mock_graph_store, mock_cache)
            await mixin.ontology_process(
                "my department", user_context, "test",
            )
            mock_cache.set.assert_called_once()

    @pytest.mark.asyncio
    async def test_returns_cached(self, mock_tenant_mgr, mock_graph_store, mock_cache, user_context):
        cached_ctx = EnrichedContext(source="ontology", graph_context=[{"cached": True}])
        mock_cache.get.return_value = cached_ctx

        with patch.object(OntologyRAGMixin, '_is_ontology_enabled', return_value=True):
            mixin = _make_mixin(mock_tenant_mgr, mock_graph_store, mock_cache)
            result = await mixin.ontology_process(
                "my department", user_context, "test",
            )
            assert result.graph_context == [{"cached": True}]
            mock_graph_store.execute_traversal.assert_not_called()


class TestVectorOnlyFlow:

    @pytest.mark.asyncio
    async def test_no_keyword_match(self, mock_tenant_mgr, mock_graph_store, mock_cache, user_context):
        with patch.object(OntologyRAGMixin, '_is_ontology_enabled', return_value=True):
            mixin = _make_mixin(mock_tenant_mgr, mock_graph_store, mock_cache)
            result = await mixin.ontology_process(
                "How do I reset my password?", user_context, "test",
            )
            assert result.source == "vector_only"
            mock_graph_store.execute_traversal.assert_not_called()


class TestDisabledFlow:

    @pytest.mark.asyncio
    async def test_disabled_returns_early(self, mock_tenant_mgr, mock_graph_store, mock_cache, user_context):
        with patch.object(OntologyRAGMixin, '_is_ontology_enabled', return_value=False):
            mixin = _make_mixin(mock_tenant_mgr, mock_graph_store, mock_cache)
            result = await mixin.ontology_process(
                "my department", user_context, "test",
            )
            assert result.source == "disabled"
            mock_tenant_mgr.resolve.assert_not_called()


class TestGracefulDegradation:

    @pytest.mark.asyncio
    async def test_graph_store_failure(self, mock_tenant_mgr, mock_graph_store, mock_cache, user_context):
        mock_graph_store.execute_traversal.side_effect = Exception("ArangoDB down")
        with patch.object(OntologyRAGMixin, '_is_ontology_enabled', return_value=True):
            mixin = _make_mixin(mock_tenant_mgr, mock_graph_store, mock_cache)
            result = await mixin.ontology_process(
                "my department", user_context, "test",
            )
            assert result.source == "vector_only"

    @pytest.mark.asyncio
    async def test_no_graph_store(self, mock_tenant_mgr, mock_cache, user_context):
        with patch.object(OntologyRAGMixin, '_is_ontology_enabled', return_value=True):
            mixin = _make_mixin(mock_tenant_mgr, None, mock_cache)
            result = await mixin.ontology_process(
                "my department", user_context, "test",
            )
            assert result.source == "vector_only"

    @pytest.mark.asyncio
    async def test_tenant_not_found(self, mock_tenant_mgr, mock_graph_store, mock_cache, user_context):
        mock_tenant_mgr.resolve.side_effect = FileNotFoundError("no YAML")
        with patch.object(OntologyRAGMixin, '_is_ontology_enabled', return_value=True):
            mixin = _make_mixin(mock_tenant_mgr, mock_graph_store, mock_cache)
            result = await mixin.ontology_process(
                "my department", user_context, "test",
            )
            assert result.source == "vector_only"


class TestPostActions:

    @pytest.mark.asyncio
    async def test_vector_search_post_action(self, mock_tenant_mgr, mock_graph_store, mock_cache, user_context):
        mock_graph_store.execute_traversal.return_value = [
            {"portal_url": "https://epson.navigator.com"},
        ]
        mock_vector_store = AsyncMock()
        mock_vector_store.search.return_value = [{"doc": "portal docs"}]

        with patch.object(OntologyRAGMixin, '_is_ontology_enabled', return_value=True):
            mixin = _make_mixin(
                mock_tenant_mgr, mock_graph_store, mock_cache,
                vector_store=mock_vector_store,
            )
            result = await mixin.ontology_process(
                "what is my portal?", user_context, "test",
            )
            assert result.source == "ontology"
            assert result.vector_context is not None
            mock_vector_store.search.assert_called_once()

    @pytest.mark.asyncio
    async def test_tool_hint_post_action(self, mock_tenant_mgr, mock_cache, user_context, ontology):
        # Add a tool_call pattern
        ontology.traversal_patterns["find_tools"] = TraversalPattern(
            description="Find tools",
            trigger_intents=["my tools"],
            query_template="FOR v IN 1..1 OUTBOUND @user_id has_tools RETURN v",
            post_action="tool_call",
        )
        tenant_ctx = TenantContext(
            tenant_id="test", arango_db="test_ontology",
            pgvector_schema="test", ontology=ontology,
        )
        mock_tenant_mgr.resolve.return_value = tenant_ctx

        mock_graph_store = AsyncMock()
        mock_graph_store.execute_traversal.return_value = [
            {"name": "Workday"},
        ]

        with patch.object(OntologyRAGMixin, '_is_ontology_enabled', return_value=True):
            mixin = _make_mixin(mock_tenant_mgr, mock_graph_store, mock_cache)
            result = await mixin.ontology_process(
                "what are my tools?", user_context, "test",
            )
            assert result.tool_hint is not None
            assert "Workday" in result.tool_hint


class TestHelpers:

    def test_extract_post_query(self):
        results = [{"portal_url": "https://example.com", "name": "Portal"}]
        val = OntologyRAGMixin._extract_post_query(results, "portal_url")
        assert val == "https://example.com"

    def test_extract_post_query_missing(self):
        val = OntologyRAGMixin._extract_post_query([{"name": "x"}], "missing_field")
        assert val is None

    def test_extract_post_query_empty(self):
        val = OntologyRAGMixin._extract_post_query([], "any")
        assert val is None

    def test_build_tool_hint(self):
        hint = OntologyRAGMixin._build_tool_hint([
            {"name": "Workday"}, {"name": "Jira"},
        ])
        assert "Workday" in hint
        assert "Jira" in hint
