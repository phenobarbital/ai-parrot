"""Behavioral acceptance tests for Memory resource factory and ownership lifecycle."""

from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path

import pytest

from parrot.memory.agent_memory.factory import (
    _ManagedResource,
    _OwnedEpisodicMemoryStore,
    _close_owned_resources,
    create_memory_manager,
)
from parrot.memory.agent_memory.models import AgentMemoryConfig
from parrot.memory.episodic.models import MemoryNamespace


def _namespace() -> MemoryNamespace:
    """Build an isolated namespace for factory tests."""
    return MemoryNamespace(tenant_id="tenant-factory", agent_id="agent-factory")


@pytest.mark.asyncio
async def test_user_only_does_not_construct_episodes(tmp_path: Path) -> None:
    """Verify user-only mode opens only its own persistent tables."""
    path = tmp_path / "memory.sqlite3"
    manager = await create_memory_manager(
        AgentMemoryConfig(enable_user_memory=True, storage_path=str(path)),
        namespace=_namespace(),
    )

    assert manager.episodic is None
    assert manager.user_memory_store is not None
    assert manager.config.enable_episodic is False
    assert manager.config.enable_user_memory is True

    await manager.cleanup()
    with sqlite3.connect(path) as database:
        tables = {row[0] for row in database.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert {"user_knowledge", "user_knowledge_events"} <= tables
    assert "episodes" not in tables


@pytest.mark.asyncio
async def test_partial_open_unwinds_resources(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Verify failed acquisition closes owned resources and preserves cancellation."""
    from parrot.memory.agent_memory import factory

    instances: dict[str, object] = {}

    class TrackingBackend:
        """Observe factory-owned backend cleanup without opening a database."""

        def __init__(self, path: Path) -> None:
            """Record the configured path."""
            self.path = path
            self.closed = False
            instances["backend"] = self

        async def configure(self) -> None:
            """Simulate successful acquisition."""

        async def close(self) -> None:
            """Record cleanup."""
            self.closed = True

    class CancellingUserStore:
        """Fail during acquisition after the episodic backend opened."""

        def __init__(self, path: Path) -> None:
            """Record the configured path."""
            self.path = path
            self.closed = False
            instances["user"] = self

        async def configure(self) -> None:
            """Propagate cancellation from resource setup."""
            raise asyncio.CancelledError

        async def close(self) -> None:
            """Record unwind cleanup."""
            self.closed = True

    monkeypatch.setattr(factory, "SQLiteEpisodeBackend", TrackingBackend)
    monkeypatch.setattr(factory, "UserMemoryStore", CancellingUserStore)

    with pytest.raises(asyncio.CancelledError):
        await create_memory_manager(
            AgentMemoryConfig(enable_episodic_memory=True, enable_user_memory=True, storage_path=str(tmp_path / "db")),
            namespace=_namespace(),
        )

    assert instances["backend"].closed is True
    assert instances["user"].closed is True


@pytest.mark.asyncio
async def test_owned_and_borrowed_cleanup() -> None:
    """Verify owned stores close while borrowed stores remain available."""
    calls: list[str] = []

    class Resource:
        """Track close calls for explicit ownership assertions."""

        def __init__(self, name: str) -> None:
            """Store the resource label."""
            self.name = name

        async def close(self) -> None:
            """Record cleanup order."""
            calls.append(self.name)

    owned = Resource("owned")
    borrowed = Resource("borrowed")
    await _close_owned_resources(
        [
            _ManagedResource(resource=owned, owned=True),
            _ManagedResource(resource=borrowed, owned=False),
        ]
    )
    assert calls == ["owned"]

    backend = Resource("backend")
    borrowed_store = _OwnedEpisodicMemoryStore(backend, owns_backend=False)
    owned_store = _OwnedEpisodicMemoryStore(backend, owns_backend=True)
    await borrowed_store.close()
    await owned_store.close()
    assert calls == ["owned", "backend"]
