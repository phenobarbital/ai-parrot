"""Tests for ToolkitRegistry.get()'s class-name resolution fallback.

Existing fixture/agent YAML across the repo uses toolkit *class* names
(e.g. "JiraToolkit"), while ToolkitRegistry keys entries by a short
canonical name (e.g. "jira"). get() must resolve both.
"""
import pytest

from parrot.tools.registry import ToolkitRegistry
from parrot.tools.toolkit import AbstractToolkit


class FakeRegistryResolutionToolkit(AbstractToolkit):
    """Minimal toolkit used only to exercise registry name resolution."""


@pytest.fixture
def toolkit_registry_sandbox():
    """Snapshot and restore ToolkitRegistry's lazily-built class registry
    so test registrations don't leak into other tests."""
    original = ToolkitRegistry.get_registry()
    snapshot = dict(original)
    try:
        yield
    finally:
        ToolkitRegistry._registry = snapshot


class TestToolkitRegistryClassNameFallback:
    def test_get_by_canonical_short_name(self, toolkit_registry_sandbox):
        ToolkitRegistry.register("fakeregistryresolution", FakeRegistryResolutionToolkit)
        assert ToolkitRegistry.get("fakeregistryresolution") is FakeRegistryResolutionToolkit

    def test_get_by_class_name_fallback(self, toolkit_registry_sandbox):
        """Registered under a short canonical key, still resolvable by its
        class name — mirrors "JiraToolkit" (class name) vs "jira"
        (registry key) in real fixtures."""
        ToolkitRegistry.register("fakeregistryresolution", FakeRegistryResolutionToolkit)
        assert ToolkitRegistry.get("FakeRegistryResolutionToolkit") is FakeRegistryResolutionToolkit

    def test_class_name_lookup_is_case_insensitive(self, toolkit_registry_sandbox):
        ToolkitRegistry.register("fakeregistryresolution", FakeRegistryResolutionToolkit)
        assert ToolkitRegistry.get("fakeREGISTRYresolutionTOOLKIT") is FakeRegistryResolutionToolkit

    def test_unknown_name_returns_none(self, toolkit_registry_sandbox):
        assert ToolkitRegistry.get("totally-unknown-toolkit-xyz") is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
