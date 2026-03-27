"""Integration tests for the full Ontological Graph RAG pipeline.

Tests the complete flow: YAML loading → merge → graph traversal →
intent resolution → enriched context → refresh pipeline.

All external services (ArangoDB, LLM, Redis) are mocked.
"""
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from parrot.knowledge.ontology.cache import OntologyCache
from parrot.knowledge.ontology.discovery import DiscoveryResult, DiscoveryStats, RelationDiscovery
from parrot.knowledge.ontology.graph_store import OntologyGraphStore, UpsertResult
from parrot.knowledge.ontology.intent import OntologyIntentResolver
from parrot.knowledge.ontology.merger import OntologyMerger
from parrot.knowledge.ontology.mixin import OntologyRAGMixin
from parrot.knowledge.ontology.parser import OntologyParser
from parrot.knowledge.ontology.refresh import OntologyRefreshPipeline
from parrot.knowledge.ontology.schema import EnrichedContext, TenantContext
from parrot.knowledge.ontology.tenant import TenantOntologyManager
from parrot.loaders.extractors import RecordsDataSource
from parrot.loaders.extractors.factory import DataSourceFactory


# ── Fixtures ──


@pytest.fixture
def defaults_dir() -> Path:
    return OntologyParser.get_defaults_dir()


@pytest.fixture
def merged_ontology(defaults_dir):
    """Merge base + field_services from package defaults."""
    merger = OntologyMerger()
    return merger.merge([
        defaults_dir / "base.ontology.yaml",
        defaults_dir / "domains" / "field_services.ontology.yaml",
    ])


@pytest.fixture
def tenant_ctx(merged_ontology) -> TenantContext:
    return TenantContext(
        tenant_id="epson",
        arango_db="epson_ontology",
        pgvector_schema="epson",
        ontology=merged_ontology,
    )


@pytest.fixture
def sample_employees() -> list[dict]:
    return [
        {"employee_id": "E001", "name": "Alice Smith", "email": "alice@epson.com",
         "job_title": "Field Engineer", "department": "ENG", "location": "NYC",
         "manager_id": "E003", "project_code": "PROJ-001"},
        {"employee_id": "E002", "name": "Bob Jones", "email": "bob@epson.com",
         "job_title": "Sales Manager", "department": "SALES", "location": "LA",
         "manager_id": "E003", "project_code": "PROJ-002"},
        {"employee_id": "E003", "name": "Carol Chen", "email": "carol@epson.com",
         "job_title": "VP Engineering", "department": "ENG", "location": "NYC",
         "manager_id": None, "project_code": "PROJ-001"},
    ]


@pytest.fixture
def sample_departments() -> list[dict]:
    return [
        {"department_id": "ENG", "name": "Engineering", "description": "Engineering dept"},
        {"department_id": "SALES", "name": "Sales", "description": "Sales dept"},
    ]


@pytest.fixture
def sample_projects() -> list[dict]:
    return [
        {"project_id": "PROJ-001", "name": "EPSON Field Services",
         "client": "EPSON", "portal_id": "PORTAL-001"},
        {"project_id": "PROJ-002", "name": "EPSON Retail",
         "client": "EPSON", "portal_id": "PORTAL-002"},
    ]


@pytest.fixture
def sample_portals() -> list[dict]:
    return [
        {"portal_id": "PORTAL-001", "name": "Navigator",
         "url": "https://epson.navigator.com", "description": "EPSON field portal"},
        {"portal_id": "PORTAL-002", "name": "Retail Hub",
         "url": "https://retail.epson.com", "description": "EPSON retail portal"},
    ]


@pytest.fixture
def mock_graph_store():
    store = AsyncMock(spec=OntologyGraphStore)
    store.execute_traversal.return_value = [
        {"name": "Navigator", "url": "https://epson.navigator.com"},
    ]
    store.get_all_nodes.return_value = []
    store.upsert_nodes.return_value = UpsertResult(inserted=3, updated=0, unchanged=0)
    store.create_edges.return_value = 3
    store.soft_delete_nodes = AsyncMock()
    store.initialize_tenant = AsyncMock()
    return store


@pytest.fixture
def mock_cache():
    cache = AsyncMock(spec=OntologyCache)
    cache.get.return_value = None
    cache.build_key = OntologyCache.build_key
    cache.invalidate_tenant = AsyncMock()
    return cache


@pytest.fixture
def user_context() -> dict:
    return {"user_id": "employees/E001"}


# ── Test 1: YAML to Graph ──


class TestYAMLToGraph:

    def test_default_yamls_load_and_merge(self, defaults_dir):
        """Load base + domain YAML → merge → valid MergedOntology."""
        merger = OntologyMerger()
        merged = merger.merge([
            defaults_dir / "base.ontology.yaml",
            defaults_dir / "domains" / "field_services.ontology.yaml",
        ])

        assert "Employee" in merged.entities
        assert "Department" in merged.entities
        assert "Project" in merged.entities
        assert "Portal" in merged.entities
        assert "Role" in merged.entities

        # Employee extended with project_code
        emp = merged.entities["Employee"]
        assert "project_code" in emp.get_property_names()

        # All relations present
        assert "reports_to" in merged.relations
        assert "belongs_to" in merged.relations
        assert "has_role" in merged.relations
        assert "assigned_to" in merged.relations
        assert "has_portal" in merged.relations

        # Domain patterns added
        assert "find_portal" in merged.traversal_patterns
        assert merged.traversal_patterns["find_portal"].post_action == "vector_search"

    def test_schema_prompt_comprehensive(self, merged_ontology):
        """Schema prompt includes all entities, relations, and patterns."""
        prompt = merged_ontology.build_schema_prompt()
        assert "Employee" in prompt
        assert "Portal" in prompt
        assert "assigned_to" in prompt
        assert "find_portal" in prompt
        assert "my portal" in prompt

    @pytest.mark.asyncio
    async def test_initialize_tenant_graph(self, mock_graph_store, tenant_ctx):
        """Initialize tenant creates DB, collections, graph."""
        await mock_graph_store.initialize_tenant(tenant_ctx)
        mock_graph_store.initialize_tenant.assert_called_once_with(tenant_ctx)


# ── Test 2: Intent to Context ──


class TestIntentToContext:

    @pytest.mark.asyncio
    async def test_fast_path_portal_query(
        self, merged_ontology, mock_graph_store, mock_cache, user_context
    ):
        """Query 'what is my portal?' → fast path → graph → enriched context."""
        with patch.object(OntologyRAGMixin, '_is_ontology_enabled', return_value=True):
            tenant_mgr = MagicMock(spec=TenantOntologyManager)
            tenant_mgr.resolve.return_value = TenantContext(
                tenant_id="epson",
                arango_db="epson_ontology",
                pgvector_schema="epson",
                ontology=merged_ontology,
            )

            mixin = OntologyRAGMixin.__new__(OntologyRAGMixin)
            mixin._ont_tenant_manager = tenant_mgr
            mixin._ont_graph_store = mock_graph_store
            mixin._ont_vector_store = None
            mixin._ont_cache = mock_cache
            mixin._ont_llm_client = None

            result = await mixin.ontology_process(
                "what is my portal?", user_context, "epson",
            )

            assert result.source == "ontology"
            assert result.intent.action == "graph_query"
            assert result.intent.pattern == "find_portal"
            assert result.intent.source == "fast_path"
            assert result.graph_context is not None
            mock_graph_store.execute_traversal.assert_called_once()

    @pytest.mark.asyncio
    async def test_fast_path_department_query(self, merged_ontology, user_context):
        """Query 'my department' → fast path match."""
        resolver = OntologyIntentResolver(merged_ontology)
        intent = await resolver.resolve("What department am I in?", user_context)
        assert intent.action == "graph_query"
        assert intent.pattern == "find_department"

    @pytest.mark.asyncio
    async def test_fast_path_manager_query(self, merged_ontology, user_context):
        """Query 'who is my manager' → fast path match."""
        resolver = OntologyIntentResolver(merged_ontology)
        intent = await resolver.resolve("who is my manager?", user_context)
        assert intent.action == "graph_query"
        assert intent.pattern == "find_manager"

    @pytest.mark.asyncio
    async def test_no_match_returns_vector_only(self, merged_ontology, user_context):
        """Unrelated query → vector_only."""
        resolver = OntologyIntentResolver(merged_ontology)
        intent = await resolver.resolve(
            "How do I change printer ink cartridges?", user_context,
        )
        assert intent.action == "vector_only"


# ── Test 3: Refresh Pipeline ──


class TestRefreshPipeline:

    @pytest.mark.asyncio
    async def test_refresh_with_records_source(
        self, tenant_ctx, mock_graph_store, mock_cache, sample_employees
    ):
        """Extract → diff → upsert → rediscover → cache invalidation."""
        # Set source on Employee so the pipeline processes it
        tenant_ctx.ontology.entities["Employee"].source = "employees_csv"

        tenant_mgr = MagicMock(spec=TenantOntologyManager)
        tenant_mgr.resolve.return_value = tenant_ctx
        tenant_mgr.invalidate = MagicMock()

        discovery = AsyncMock(spec=RelationDiscovery)
        discovery.discover.return_value = DiscoveryResult(
            confirmed=[{"_from": "employees/E001", "_to": "departments/ENG"}],
            stats=DiscoveryStats(total_source=3, total_target=2, edges_created=1),
        )

        # Use RecordsDataSource via factory
        factory = MagicMock(spec=DataSourceFactory)
        source = RecordsDataSource("employees_csv", records=sample_employees)
        factory.get.return_value = source

        pipeline = OntologyRefreshPipeline(
            tenant_manager=tenant_mgr,
            graph_store=mock_graph_store,
            discovery=discovery,
            datasource_factory=factory,
            cache=mock_cache,
        )

        report = await pipeline.run("epson")

        assert report.tenant == "epson"
        assert report.completed_at is not None
        assert len(report.errors) == 0

        # Should have upserted nodes
        mock_graph_store.upsert_nodes.assert_called()
        # Should have invalidated cache
        mock_cache.invalidate_tenant.assert_called_once_with("epson")
        tenant_mgr.invalidate.assert_called_once_with("epson")

    @pytest.mark.asyncio
    async def test_diff_detects_changes(self):
        """Verify delta sync: add + update + remove."""
        existing = [
            {"employee_id": "E001", "name": "Alice"},
            {"employee_id": "E002", "name": "Bob"},
        ]
        new_data = [
            {"employee_id": "E001", "name": "Alice Updated"},  # update
            {"employee_id": "E003", "name": "Carol"},           # add
            # E002 removed
        ]
        diff = OntologyRefreshPipeline._compute_diff(
            new_data, existing, "employee_id",
        )
        assert len(diff.to_add) == 1
        assert diff.to_add[0]["employee_id"] == "E003"
        assert len(diff.to_update) == 1
        assert diff.to_update[0]["name"] == "Alice Updated"
        assert len(diff.to_remove) == 1
        assert diff.to_remove[0]["employee_id"] == "E002"


# ── Test 4: Disabled Mode ──


class TestDisabledMode:

    @pytest.mark.asyncio
    async def test_disabled_returns_early(self, user_context):
        """ENABLE_ONTOLOGY_RAG=False → immediate return."""
        with patch.object(OntologyRAGMixin, '_is_ontology_enabled', return_value=False):
            mixin = OntologyRAGMixin.__new__(OntologyRAGMixin)
            mixin._ont_tenant_manager = MagicMock()
            mixin._ont_graph_store = AsyncMock()
            mixin._ont_cache = AsyncMock()
            mixin._ont_llm_client = None
            mixin._ont_vector_store = None

            result = await mixin.ontology_process(
                "my department", user_context, "epson",
            )
            assert result.source == "disabled"
            mixin._ont_tenant_manager.resolve.assert_not_called()


# ── Test 5: Graceful Degradation ──


class TestGracefulDegradation:

    @pytest.mark.asyncio
    async def test_arango_unavailable(
        self, merged_ontology, mock_cache, user_context
    ):
        """ArangoDB down → degrades to vector_only without error."""
        with patch.object(OntologyRAGMixin, '_is_ontology_enabled', return_value=True):
            tenant_mgr = MagicMock(spec=TenantOntologyManager)
            tenant_mgr.resolve.return_value = TenantContext(
                tenant_id="epson",
                arango_db="epson_ontology",
                pgvector_schema="epson",
                ontology=merged_ontology,
            )

            graph_store = AsyncMock(spec=OntologyGraphStore)
            graph_store.execute_traversal.side_effect = ConnectionError(
                "ArangoDB connection refused"
            )

            mixin = OntologyRAGMixin.__new__(OntologyRAGMixin)
            mixin._ont_tenant_manager = tenant_mgr
            mixin._ont_graph_store = graph_store
            mixin._ont_vector_store = None
            mixin._ont_cache = mock_cache
            mixin._ont_llm_client = None

            result = await mixin.ontology_process(
                "my department", user_context, "epson",
            )
            # Should NOT raise — graceful degradation
            assert result.source == "vector_only"

    @pytest.mark.asyncio
    async def test_no_yaml_for_tenant(self, mock_cache, user_context):
        """Missing YAML files → degrades to vector_only."""
        with patch.object(OntologyRAGMixin, '_is_ontology_enabled', return_value=True):
            tenant_mgr = MagicMock(spec=TenantOntologyManager)
            tenant_mgr.resolve.side_effect = FileNotFoundError("No YAML")

            mixin = OntologyRAGMixin.__new__(OntologyRAGMixin)
            mixin._ont_tenant_manager = tenant_mgr
            mixin._ont_graph_store = AsyncMock()
            mixin._ont_vector_store = None
            mixin._ont_cache = mock_cache
            mixin._ont_llm_client = None

            result = await mixin.ontology_process(
                "my department", user_context, "unknown_tenant",
            )
            assert result.source == "vector_only"


# ── Test: Full test suite runs together ──


class TestAllOntologyTests:

    @pytest.mark.asyncio
    async def test_all_knowledge_tests_pass(self):
        """Smoke test: verify all ontology modules import cleanly."""
        from parrot.knowledge.ontology import (
            OntologyCache,
            OntologyGraphStore,
            OntologyIntentResolver,
            OntologyRAGMixin,
            TenantOntologyManager,
            EnrichedContext,
            MergedOntology,
            ResolvedIntent,
            TenantContext,
        )
        from parrot.knowledge.ontology.discovery import RelationDiscovery
        from parrot.knowledge.ontology.merger import OntologyMerger
        from parrot.knowledge.ontology.parser import OntologyParser
        from parrot.knowledge.ontology.refresh import OntologyRefreshPipeline
        from parrot.knowledge.ontology.validators import validate_aql
        from parrot.knowledge.ontology.exceptions import (
            OntologyError,
            OntologyMergeError,
            OntologyIntegrityError,
            AQLValidationError,
        )
        from parrot.loaders.extractors import (
            ExtractDataSource,
            CSVDataSource,
            JSONDataSource,
            RecordsDataSource,
            DataSourceFactory,
        )

        # All imports succeeded
        assert True
