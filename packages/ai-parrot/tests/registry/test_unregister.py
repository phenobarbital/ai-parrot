"""Tests for AgentRegistry.unregister and replace-safe register (FEAT-467 TASK-2509).

Covers:
  - unregister() removes metadata + cached instance for both register()
    and register_instance() entries; returns False for unknown names.
  - register(..., replace=True) drops the stale BotMetadata._instance of
    the entry it replaces, so a reload can never serve a zombie instance.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from parrot.registry.registry import AgentRegistry
from parrot.bots.abstract import AbstractBot


@pytest.fixture
def registry(tmp_path):
    """Fresh registry with a temporary agents dir."""
    return AgentRegistry(agents_dir=tmp_path / "agents")


class _DummyBot(AbstractBot):
    """Minimal concrete AbstractBot subclass for registration tests."""


class TestUnregister:
    """AgentRegistry.unregister — per-agent removal primitive."""

    def test_unregister_removes_entry_and_instance(self, registry):
        registry.register("dummy", _DummyBot)
        meta = registry.get_metadata("dummy")
        assert meta is not None
        # Simulate a cached instance as get_instance() would set for a singleton.
        meta._instance = MagicMock(spec=AbstractBot)

        result = registry.unregister("dummy")

        assert result is True
        assert registry.get_metadata("dummy") is None
        assert registry.has("dummy") is False
        # The popped metadata's instance reference must be dropped too.
        assert meta._instance is None

    def test_unregister_instance_registered_entry(self, registry):
        """unregister also works for agents added via register_instance."""
        instance = MagicMock(spec=AbstractBot)
        registry.register_instance("dummy-instance", instance)

        result = registry.unregister("dummy-instance")

        assert result is True
        assert registry.get_metadata("dummy-instance") is None

    def test_unregister_unknown_returns_false(self, registry):
        result = registry.unregister("does-not-exist")
        assert result is False

    def test_unregister_never_raises_for_missing(self, registry):
        """Calling unregister twice on the same name is safe."""
        registry.register("dummy", _DummyBot)
        assert registry.unregister("dummy") is True
        # Second call: already gone — must return False, not raise.
        assert registry.unregister("dummy") is False


class TestRegisterReplaceSafe:
    """register(..., replace=True) must drop the replaced entry's instance."""

    def test_register_replace_drops_stale_instance(self, registry):
        registry.register("dummy", _DummyBot, singleton=True)
        original_meta = registry.get_metadata("dummy")
        stale_instance = MagicMock(spec=AbstractBot)
        original_meta._instance = stale_instance

        # Re-register (simulates the reload rebuild-and-swap flow).
        registry.register("dummy", _DummyBot, singleton=True, replace=True)

        # The OLD metadata object must have its instance reference cleared —
        # any caller still holding `original_meta` cannot serve the zombie.
        assert original_meta._instance is None

        # The NEW metadata entry is a fresh BotMetadata with no instance yet.
        new_meta = registry.get_metadata("dummy")
        assert new_meta is not original_meta
        assert new_meta._instance is None

    def test_register_without_replace_keeps_existing(self, registry):
        registry.register("dummy", _DummyBot)
        original_meta = registry.get_metadata("dummy")

        # replace=False (default) on an already-registered name is a no-op.
        registry.register("dummy", _DummyBot)

        assert registry.get_metadata("dummy") is original_meta


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
