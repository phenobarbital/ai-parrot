"""Tests for ontology refresh pipeline."""
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot.knowledge.ontology.cache import OntologyCache
from parrot.knowledge.ontology.discovery import DiscoveryResult, DiscoveryStats, RelationDiscovery
from parrot.knowledge.ontology.graph_store import OntologyGraphStore, UpsertResult
from parrot.knowledge.ontology.refresh import DiffResult, OntologyRefreshPipeline, RefreshReport
from parrot.knowledge.ontology.schema import (
    DiscoveryConfig,
    DiscoveryRule,
    EntityDef,
    MergedOntology,
    PropertyDef,
    RelationDef,
    TenantContext,
)
from parrot.knowledge.ontology.tenant import TenantOntologyManager
from parrot.loaders.extractors import RecordsDataSource
from parrot.loaders.extractors.base import ExtractionResult, ExtractedRecord
from parrot.loaders.extractors.factory import DataSourceFactory


@pytest.fixture
def tenant_ctx() -> TenantContext:
    return TenantContext(
        tenant_id="test",
        arango_db="test_ontology",
        pgvector_schema="test",
        ontology=MergedOntology(
            name="test",
            version="1.0",
            entities={
                "Employee": EntityDef(
                    collection="employees",
                    key_field="employee_id",
                    source="employees_csv",
                    properties=[
                        {"employee_id": PropertyDef(type="string")},
                        {"name": PropertyDef(type="string")},
                        {"department": PropertyDef(type="string")},
                    ],
                    vectorize=["name"],
                ),
                "Department": EntityDef(
                    collection="departments",
                    key_field="dept_id",
                    properties=[
                        {"dept_id": PropertyDef(type="string")},
                        {"name": PropertyDef(type="string")},
                    ],
                ),
            },
            relations={
                "belongs_to": RelationDef(
                    from_entity="Employee",
                    to_entity="Department",
                    edge_collection="belongs_to_dept",
                    discovery=DiscoveryConfig(
                        rules=[DiscoveryRule(
                            source_field="department",
                            target_field="dept_id",
                            match_type="exact",
                        )]
                    ),
                ),
            },
            traversal_patterns={},
            layers=["test"],
            merge_timestamp=datetime.now(timezone.utc),
        ),
    )


@pytest.fixture
def mock_tenant_mgr(tenant_ctx):
    mgr = MagicMock(spec=TenantOntologyManager)
    mgr.resolve.return_value = tenant_ctx
    mgr.invalidate = MagicMock()
    return mgr


@pytest.fixture
def mock_graph_store():
    store = AsyncMock(spec=OntologyGraphStore)
    store.get_all_nodes.return_value = [
        {"employee_id": "E1", "name": "Alice", "department": "ENG", "_active": True},
        {"employee_id": "E2", "name": "Bob", "department": "SALES", "_active": True},
    ]
    store.upsert_nodes.return_value = UpsertResult(inserted=1, updated=1, unchanged=0)
    store.create_edges.return_value = 1
    store.soft_delete_nodes = AsyncMock()
    return store


@pytest.fixture
def mock_discovery():
    disc = AsyncMock(spec=RelationDiscovery)
    disc.discover.return_value = DiscoveryResult(
        confirmed=[{"_from": "employees/E3", "_to": "departments/ENG"}],
        review_queue=[],
        stats=DiscoveryStats(total_source=1, total_target=2, edges_created=1, needs_review=0),
    )
    return disc


@pytest.fixture
def mock_factory():
    factory = MagicMock(spec=DataSourceFactory)
    source = AsyncMock()
    source.extract.return_value = ExtractionResult(
        records=[
            ExtractedRecord(data={"employee_id": "E1", "name": "Alice Updated", "department": "ENG"}),
            ExtractedRecord(data={"employee_id": "E3", "name": "Carol", "department": "ENG"}),
        ],
        total=2,
        source_name="employees_csv",
        extracted_at=datetime.now(timezone.utc),
    )
    factory.get.return_value = source
    return factory


@pytest.fixture
def mock_cache():
    cache = AsyncMock(spec=OntologyCache)
    return cache


@pytest.fixture
def pipeline(mock_tenant_mgr, mock_graph_store, mock_discovery, mock_factory, mock_cache):
    return OntologyRefreshPipeline(
        tenant_manager=mock_tenant_mgr,
        graph_store=mock_graph_store,
        discovery=mock_discovery,
        datasource_factory=mock_factory,
        cache=mock_cache,
    )


class TestDiffComputation:

    def test_detects_additions(self):
        new = [{"id": "1", "name": "Alice"}, {"id": "2", "name": "Bob"}]
        existing = [{"id": "1", "name": "Alice"}]
        diff = OntologyRefreshPipeline._compute_diff(new, existing, "id")
        assert len(diff.to_add) == 1
        assert diff.to_add[0]["id"] == "2"

    def test_detects_removals(self):
        new = [{"id": "1", "name": "Alice"}]
        existing = [{"id": "1", "name": "Alice"}, {"id": "2", "name": "Bob"}]
        diff = OntologyRefreshPipeline._compute_diff(new, existing, "id")
        assert len(diff.to_remove) == 1
        assert diff.to_remove[0]["id"] == "2"

    def test_detects_updates(self):
        new = [{"id": "1", "name": "Alice Updated"}]
        existing = [{"id": "1", "name": "Alice"}]
        diff = OntologyRefreshPipeline._compute_diff(new, existing, "id")
        assert len(diff.to_update) == 1
        assert diff.to_update[0]["name"] == "Alice Updated"

    def test_unchanged_not_in_update(self):
        new = [{"id": "1", "name": "Alice"}]
        existing = [{"id": "1", "name": "Alice"}]
        diff = OntologyRefreshPipeline._compute_diff(new, existing, "id")
        assert len(diff.to_update) == 0
        assert len(diff.to_add) == 0
        assert len(diff.to_remove) == 0

    def test_mixed_operations(self):
        new = [
            {"id": "1", "name": "Alice Updated"},  # update
            {"id": "3", "name": "Carol"},           # add
        ]
        existing = [
            {"id": "1", "name": "Alice"},           # will be updated
            {"id": "2", "name": "Bob"},             # will be removed
        ]
        diff = OntologyRefreshPipeline._compute_diff(new, existing, "id")
        assert len(diff.to_add) == 1
        assert len(diff.to_update) == 1
        assert len(diff.to_remove) == 1


class TestRefreshPipeline:

    @pytest.mark.asyncio
    async def test_full_refresh(self, pipeline, mock_graph_store, mock_discovery, mock_cache, mock_tenant_mgr):
        report = await pipeline.run("test")
        assert isinstance(report, RefreshReport)
        assert report.tenant == "test"
        assert report.completed_at is not None
        assert len(report.errors) == 0

        # Should have extracted, diffed, upserted
        mock_graph_store.upsert_nodes.assert_called()
        # Should have soft-deleted removed nodes (E2 is not in new data)
        mock_graph_store.soft_delete_nodes.assert_called()
        # Should have invalidated cache
        mock_cache.invalidate_tenant.assert_called_once_with("test")
        mock_tenant_mgr.invalidate.assert_called_once_with("test")

    @pytest.mark.asyncio
    async def test_rediscovery_for_changed(self, pipeline, mock_discovery):
        await pipeline.run("test")
        # Discovery should be called for changed nodes
        mock_discovery.discover.assert_called()

    @pytest.mark.asyncio
    async def test_entity_without_source_skipped(self, pipeline, mock_graph_store):
        """Department has no source — should not be extracted."""
        report = await pipeline.run("test")
        # Factory.get should only be called once (for Employee, not Department)
        pipeline.datasource_factory.get.assert_called_once()

    @pytest.mark.asyncio
    async def test_tenant_resolve_failure(self, pipeline, mock_tenant_mgr):
        mock_tenant_mgr.resolve.side_effect = FileNotFoundError("no YAML")
        report = await pipeline.run("missing_tenant")
        assert len(report.errors) > 0
        assert "resolve" in report.errors[0].lower() or "tenant" in report.errors[0].lower()

    @pytest.mark.asyncio
    async def test_report_timing(self, pipeline):
        report = await pipeline.run("test")
        assert report.started_at <= report.completed_at
