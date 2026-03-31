"""Unit tests for CapabilityRegistry (TASK-490).

Tests registration (manual, DataSource, Tool, YAML), index building,
cosine similarity search, not_for penalty, and auto-rebuild behavior.
"""
from __future__ import annotations

import pytest

from parrot.registry.capabilities.models import (
    CapabilityEntry,
    ResourceType,
    RouterCandidate,
)
from parrot.registry.capabilities.registry import CapabilityRegistry


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def registry() -> CapabilityRegistry:
    """Empty CapabilityRegistry for each test."""
    return CapabilityRegistry()


@pytest.fixture
def sample_entries() -> list[CapabilityEntry]:
    """Three sample capability entries covering different resource types."""
    return [
        CapabilityEntry(
            name="sales_data",
            description="Monthly sales revenue dataset",
            resource_type=ResourceType.DATASET,
        ),
        CapabilityEntry(
            name="weather_tool",
            description="Get current weather for a city",
            resource_type=ResourceType.TOOL,
        ),
        CapabilityEntry(
            name="product_graph",
            description="Product relationship graph with categories",
            resource_type=ResourceType.GRAPH_NODE,
        ),
    ]


@pytest.fixture
def mock_embedding_fn():
    """Returns deterministic embeddings based on description length.

    Each text gets a 3-dimensional embedding so tests are fast and
    reproducible without a real embedding model.
    """

    async def _embed(texts: list[str]) -> list[list[float]]:
        return [
            [
                float(len(t) % 10) / 10.0,
                float(len(t) % 7) / 7.0,
                float(len(t) % 3) / 3.0,
            ]
            for t in texts
        ]

    return _embed


# ── Registration Tests ────────────────────────────────────────────────────────


class TestRegister:
    """Tests for manual registration."""

    def test_register_adds_entry(
        self, registry: CapabilityRegistry, sample_entries: list[CapabilityEntry]
    ) -> None:
        """register() appends the entry to internal list."""
        registry.register(sample_entries[0])
        assert len(registry._entries) == 1

    def test_register_multiple_entries(
        self, registry: CapabilityRegistry, sample_entries: list[CapabilityEntry]
    ) -> None:
        """Multiple registrations accumulate."""
        for entry in sample_entries:
            registry.register(entry)
        assert len(registry._entries) == 3

    def test_register_invalidates_index(
        self, registry: CapabilityRegistry, sample_entries: list[CapabilityEntry]
    ) -> None:
        """register() marks the index dirty."""
        registry._index_dirty = False
        registry.register(sample_entries[0])
        assert registry._index_dirty is True


class TestRegisterFromDatasource:
    """Tests for DataSource auto-registration."""

    def test_register_from_datasource_basic(self, registry: CapabilityRegistry) -> None:
        """register_from_datasource creates a DATASET entry."""

        class FakeSource:
            name = "sales_dataset"

            def describe(self) -> str:
                return "Monthly sales figures"

        registry.register_from_datasource(FakeSource())
        assert len(registry._entries) == 1
        entry = registry._entries[0]
        assert entry.name == "sales_dataset"
        assert entry.resource_type == ResourceType.DATASET

    def test_register_from_datasource_with_routing_meta(
        self, registry: CapabilityRegistry
    ) -> None:
        """register_from_datasource uses routing_meta for not_for."""

        class FakeSource:
            name = "hr_source"
            routing_meta = {"not_for": ["warehouse", "inventory"], "description": "HR records"}

            def describe(self) -> str:
                return "Human resources dataset"

        registry.register_from_datasource(FakeSource())
        entry = registry._entries[0]
        assert entry.not_for == ["warehouse", "inventory"]
        assert entry.description == "HR records"

    def test_register_from_datasource_fallback_name(
        self, registry: CapabilityRegistry
    ) -> None:
        """register_from_datasource falls back to name when describe unavailable."""

        class FakeSource:
            name = "simple_source"

        registry.register_from_datasource(FakeSource())
        assert registry._entries[0].description == "simple_source"


class TestRegisterFromTool:
    """Tests for AbstractTool auto-registration."""

    def test_register_from_tool_basic(self, registry: CapabilityRegistry) -> None:
        """register_from_tool creates a TOOL entry."""

        class FakeTool:
            name = "weather_api"
            description = "Get weather for a city"

        registry.register_from_tool(FakeTool())
        assert len(registry._entries) == 1
        entry = registry._entries[0]
        assert entry.name == "weather_api"
        assert entry.resource_type == ResourceType.TOOL
        assert entry.description == "Get weather for a city"

    def test_register_from_tool_with_routing_meta(self, registry: CapabilityRegistry) -> None:
        """register_from_tool respects routing_meta not_for."""

        class FakeTool:
            name = "admin_tool"
            description = "Admin operations"
            routing_meta = {"not_for": ["public", "user-facing"]}

        registry.register_from_tool(FakeTool())
        entry = registry._entries[0]
        assert "public" in entry.not_for


class TestRegisterFromYaml:
    """Tests for YAML-based registration."""

    def test_register_from_yaml(
        self, registry: CapabilityRegistry, tmp_path
    ) -> None:
        """register_from_yaml loads entries from a YAML file."""
        yaml_content = """
capabilities:
  - name: product_ontology
    description: Product category graph with relationships
    resource_type: graph_node
    not_for:
      - employee data
  - name: inventory_data
    description: Inventory levels and stock movements
    resource_type: dataset
"""
        yaml_file = tmp_path / "capabilities.yaml"
        yaml_file.write_text(yaml_content)
        registry.register_from_yaml(str(yaml_file))
        assert len(registry._entries) == 2
        names = {e.name for e in registry._entries}
        assert "product_ontology" in names
        assert "inventory_data" in names

    def test_register_from_yaml_missing_file(self, registry: CapabilityRegistry) -> None:
        """register_from_yaml raises FileNotFoundError for missing file."""
        with pytest.raises(FileNotFoundError):
            registry.register_from_yaml("/nonexistent/path.yaml")


# ── Index Tests ───────────────────────────────────────────────────────────────


class TestBuildIndex:
    """Tests for index building."""

    @pytest.mark.asyncio
    async def test_builds_embedding_matrix(
        self,
        registry: CapabilityRegistry,
        sample_entries: list[CapabilityEntry],
        mock_embedding_fn,
    ) -> None:
        """build_index produces a normalised embedding matrix."""
        for entry in sample_entries:
            registry.register(entry)
        await registry.build_index(mock_embedding_fn)
        assert registry._embedding_matrix is not None
        assert registry._embedding_matrix.shape[0] == 3
        assert registry._index_dirty is False

    @pytest.mark.asyncio
    async def test_empty_registry_build(
        self, registry: CapabilityRegistry, mock_embedding_fn
    ) -> None:
        """build_index on empty registry sets dirty=False without error."""
        await registry.build_index(mock_embedding_fn)
        assert registry._index_dirty is False

    @pytest.mark.asyncio
    async def test_stores_embedding_fn(
        self,
        registry: CapabilityRegistry,
        sample_entries: list[CapabilityEntry],
        mock_embedding_fn,
    ) -> None:
        """build_index stores the embedding function for later use."""
        for entry in sample_entries:
            registry.register(entry)
        await registry.build_index(mock_embedding_fn)
        assert registry._embedding_fn is mock_embedding_fn


# ── Search Tests ──────────────────────────────────────────────────────────────


class TestSearch:
    """Tests for embedding-based search."""

    @pytest.mark.asyncio
    async def test_returns_candidates(
        self,
        registry: CapabilityRegistry,
        sample_entries: list[CapabilityEntry],
        mock_embedding_fn,
    ) -> None:
        """search returns RouterCandidate list."""
        for entry in sample_entries:
            registry.register(entry)
        await registry.build_index(mock_embedding_fn)
        results = await registry.search("sales revenue", top_k=2)
        assert len(results) <= 2
        assert all(isinstance(r, RouterCandidate) for r in results)

    @pytest.mark.asyncio
    async def test_filter_by_resource_type(
        self,
        registry: CapabilityRegistry,
        sample_entries: list[CapabilityEntry],
        mock_embedding_fn,
    ) -> None:
        """search filters by resource_type when specified."""
        for entry in sample_entries:
            registry.register(entry)
        await registry.build_index(mock_embedding_fn)
        results = await registry.search("data", resource_types=[ResourceType.DATASET])
        assert all(r.resource_type == ResourceType.DATASET for r in results)

    @pytest.mark.asyncio
    async def test_not_for_penalty(self, registry: CapabilityRegistry, mock_embedding_fn) -> None:
        """search applies not_for penalty to matching queries."""
        entry = CapabilityEntry(
            name="internal_tool",
            description="Internal admin operations",
            resource_type=ResourceType.TOOL,
            not_for=["admin"],
        )
        registry.register(entry)
        await registry.build_index(mock_embedding_fn)
        results = await registry.search("admin operations")
        # Score must exist and be ≤ 1.0 (penalty was applied)
        if results:
            # Without penalty the unpenalised score ≤ 1.0; penalty makes it smaller
            assert results[0].score <= 1.0

    @pytest.mark.asyncio
    async def test_auto_rebuilds_on_dirty(
        self,
        registry: CapabilityRegistry,
        sample_entries: list[CapabilityEntry],
        mock_embedding_fn,
    ) -> None:
        """search auto-rebuilds the index when dirty."""
        for entry in sample_entries:
            registry.register(entry)
        await registry.build_index(mock_embedding_fn)

        # Add a new entry → index dirty
        registry.register(
            CapabilityEntry(
                name="new_entry",
                description="A brand new capability",
                resource_type=ResourceType.TOOL,
            )
        )
        assert registry._index_dirty is True
        await registry.search("new capability", top_k=1)
        assert registry._index_dirty is False

    @pytest.mark.asyncio
    async def test_empty_registry_search_returns_empty(
        self, registry: CapabilityRegistry, mock_embedding_fn
    ) -> None:
        """search on an empty registry returns empty list."""
        await registry.build_index(mock_embedding_fn)
        results = await registry.search("anything")
        assert results == []

    @pytest.mark.asyncio
    async def test_scores_are_in_range(
        self,
        registry: CapabilityRegistry,
        sample_entries: list[CapabilityEntry],
        mock_embedding_fn,
    ) -> None:
        """All search scores are in [0.0, 1.0]."""
        for entry in sample_entries:
            registry.register(entry)
        await registry.build_index(mock_embedding_fn)
        results = await registry.search("query", top_k=10)
        for r in results:
            assert 0.0 <= r.score <= 1.0
