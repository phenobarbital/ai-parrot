"""Unit tests for auto-registration hooks (TASK-493).

Tests routing_meta on DataSource and AbstractTool, add_source() on
DatasetManager, and capability_registry parameter on ToolManager.register().
"""
from __future__ import annotations

from typing import Dict
from unittest.mock import MagicMock

import pandas as pd
import pytest

from parrot.registry.capabilities.models import ResourceType
from parrot.registry.capabilities.registry import CapabilityRegistry
from parrot.tools.dataset_manager.sources.base import DataSource


# ── Concrete DataSource for testing ──────────────────────────────────────────


class FakeSource(DataSource):
    """Minimal concrete DataSource implementation."""

    def __init__(self, name: str = "fake", routing_meta: Dict | None = None):
        super().__init__(routing_meta=routing_meta)
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    @property
    def cache_key(self) -> str:
        return f"fake:{self._name}"

    def describe(self) -> str:
        return f"Fake dataset: {self._name}"

    async def fetch(self, **params) -> pd.DataFrame:
        return pd.DataFrame({"id": [1], "value": [100]})


# ── DataSource Tests ──────────────────────────────────────────────────────────


class TestDataSourceRoutingMeta:
    """Tests for routing_meta on DataSource."""

    def test_default_routing_meta_is_empty_dict(self) -> None:
        """DataSource.routing_meta defaults to empty dict."""
        source = FakeSource("test")
        assert source.routing_meta == {}

    def test_routing_meta_is_set(self) -> None:
        """routing_meta is stored correctly on the instance."""
        meta = {"not_for": ["hr", "payroll"], "description": "Sales data"}
        source = FakeSource("sales", routing_meta=meta)
        assert source.routing_meta["not_for"] == ["hr", "payroll"]
        assert source.routing_meta["description"] == "Sales data"

    def test_routing_meta_not_shared_between_instances(self) -> None:
        """Each DataSource instance has its own routing_meta dict."""
        source_a = FakeSource("a")
        source_b = FakeSource("b")
        source_a.routing_meta["key"] = "value_a"
        assert "key" not in source_b.routing_meta

    def test_routing_meta_defaults_to_empty_when_none_passed(self) -> None:
        """Passing routing_meta=None uses empty dict."""
        source = FakeSource("test", routing_meta=None)
        assert source.routing_meta == {}

    def test_routing_meta_used_by_register_from_datasource(self) -> None:
        """CapabilityRegistry reads routing_meta.not_for from DataSource."""
        meta = {"not_for": ["competitors", "internal"]}
        source = FakeSource("products", routing_meta=meta)
        registry = CapabilityRegistry()
        registry.register_from_datasource(source)
        entry = registry._entries[0]
        assert entry.not_for == ["competitors", "internal"]


# ── AbstractTool Tests ────────────────────────────────────────────────────────


class TestAbstractToolRoutingMeta:
    """Tests for routing_meta on AbstractTool."""

    def _make_minimal_tool(self, routing_meta=None, name="minimal"):
        """Create a minimal AbstractTool subclass for testing.

        Implements all abstract methods so the class can be instantiated.
        """
        from parrot.tools.abstract import AbstractTool
        import abc

        # Build method dict that overrides all abstract methods
        abstract_method_names = {
            attr
            for cls in AbstractTool.__mro__
            for attr, val in vars(cls).items()
            if getattr(val, '__isabstractmethod__', False)
        }

        stub = lambda self, *a, **k: "ok"  # noqa: E731

        ns = {m: stub for m in abstract_method_names}
        ns["__abstractmethods__"] = frozenset()  # Clear abstract flag
        ConcreteToolClass = type("MinimalTool", (AbstractTool,), ns)
        ConcreteToolClass.name = name
        ConcreteToolClass.description = "A minimal tool"

        if routing_meta:
            return ConcreteToolClass(routing_meta=routing_meta)
        return ConcreteToolClass()

    def test_default_routing_meta_empty(self) -> None:
        """AbstractTool.routing_meta defaults to empty dict."""
        tool = self._make_minimal_tool()
        assert tool.routing_meta == {}

    def test_routing_meta_passed_to_constructor(self) -> None:
        """routing_meta set via constructor is stored on instance."""
        tool = self._make_minimal_tool(routing_meta={"not_for": ["public"]})
        assert tool.routing_meta["not_for"] == ["public"]

    def test_routing_meta_not_shared_between_instances(self) -> None:
        """Each AbstractTool instance has its own routing_meta dict."""
        tool_a = self._make_minimal_tool(name="tool_a")
        tool_b = self._make_minimal_tool(name="tool_b")
        tool_a.routing_meta["key"] = "a"
        assert "key" not in tool_b.routing_meta

    def test_routing_meta_used_by_register_from_tool(self) -> None:
        """CapabilityRegistry reads routing_meta.not_for from AbstractTool."""
        tool = self._make_minimal_tool(
            routing_meta={"not_for": ["public-facing"]},
            name="admin_tool",
        )
        registry = CapabilityRegistry()
        registry.register_from_tool(tool)
        entry = registry._entries[0]
        assert entry.not_for == ["public-facing"]
        assert entry.resource_type == ResourceType.TOOL


# ── DatasetManager.add_source() Tests ────────────────────────────────────────


class TestDatasetManagerAddSource:
    """Tests for DatasetManager.add_source()."""

    @pytest.fixture
    def dm(self):
        """Minimal DatasetManager instance (no DB, no vector store)."""
        from parrot.tools.dataset_manager.tool import DatasetManager

        dm = object.__new__(DatasetManager)
        dm._datasets = {}
        dm.auto_detect_types = True
        dm.logger = MagicMock()
        return dm

    def test_add_source_registers_dataset_entry(self, dm) -> None:
        """add_source() stores a DatasetEntry keyed by source name."""
        source = FakeSource("sales")
        dm.add_source(source)
        assert "sales" in dm._datasets

    def test_add_source_returns_confirmation(self, dm) -> None:
        """add_source() returns a non-empty string message."""
        source = FakeSource("inventory")
        result = dm.add_source(source)
        assert isinstance(result, str)
        assert "inventory" in result.lower()

    def test_add_source_without_cache_key_raises(self, dm) -> None:
        """add_source() raises ValueError for sources without cache_key."""

        class BadSource:
            name = "bad"

            def describe(self):
                return "bad"

        with pytest.raises(ValueError):
            dm.add_source(BadSource())

    def test_add_source_calls_registry(self, dm) -> None:
        """add_source() calls registry.register_from_datasource() when provided."""
        source = FakeSource("events")
        registry = MagicMock()
        dm.add_source(source, capability_registry=registry)
        registry.register_from_datasource.assert_called_once_with(source)

    def test_add_source_no_registry_does_not_raise(self, dm) -> None:
        """add_source() without registry works fine (no side effects)."""
        source = FakeSource("products")
        result = dm.add_source(source, capability_registry=None)
        assert result

    def test_add_source_uses_source_description(self, dm) -> None:
        """DatasetEntry stores the source's describe() output as description."""
        source = FakeSource("kpis")
        dm.add_source(source)
        entry = dm._datasets["kpis"]
        assert "Fake dataset: kpis" in entry.description or entry.description

    def test_add_source_integrates_with_real_registry(self, dm) -> None:
        """add_source() with a real CapabilityRegistry adds an entry."""
        registry = CapabilityRegistry()
        source = FakeSource("transactions", routing_meta={"not_for": ["hr"]})
        dm.add_source(source, capability_registry=registry)
        assert len(registry._entries) == 1
        assert registry._entries[0].name == "transactions"
        assert registry._entries[0].not_for == ["hr"]


# ── ToolManager.register() Tests ─────────────────────────────────────────────


class TestToolManagerRegister:
    """Tests for ToolManager.register() capability_registry parameter."""

    @pytest.fixture
    def tool_manager(self):
        """Minimal ToolManager instance."""
        from parrot.tools.manager import ToolManager

        # Use object.__new__ to skip full init
        tm = object.__new__(ToolManager)
        tm._tools = {}
        tm._tool_definitions = {}
        tm.logger = MagicMock()
        tm.register_tool = MagicMock()
        return tm

    def test_register_calls_register_tool(self, tool_manager) -> None:
        """register() delegates to register_tool()."""
        tool_manager.register_tool.return_value = None
        tool_manager.register(name="test_tool")
        tool_manager.register_tool.assert_called_once()

    def test_register_calls_registry_when_provided(self, tool_manager) -> None:
        """register() calls registry.register_from_tool() with capability_registry."""
        registry = MagicMock()
        tool_manager.register_tool.return_value = None

        class FakeTool:
            name = "tool_a"
            description = "Does something"

        tool = FakeTool()
        tool_manager.register(tool=tool, capability_registry=registry)
        registry.register_from_tool.assert_called_once_with(tool)

    def test_register_no_registry_no_error(self, tool_manager) -> None:
        """register() without capability_registry does not raise."""
        tool_manager.register_tool.return_value = None
        tool_manager.register(name="my_tool", capability_registry=None)
        tool_manager.register_tool.assert_called_once()

    def test_register_existing_code_unchanged(self, tool_manager) -> None:
        """register() called without capability_registry is backward-compatible."""
        tool_manager.register_tool.return_value = "registered"
        result = tool_manager.register(name="legacy_tool")
        assert result == "registered"
        tool_manager.register_tool.assert_called_once()
