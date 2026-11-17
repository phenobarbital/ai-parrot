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
    _manager_config,
    _warn_unsupported_knobs,
    create_memory_manager,
)
from parrot.memory.agent_memory.models import AgentMemoryConfig
from parrot.memory.episodic.models import MemoryNamespace


@pytest.mark.asyncio
async def test_agent_config_maps_new_limits(tmp_path: Path) -> None:
    """Factory forwards both limits and the explicit user token cap."""
    manager = await create_memory_manager(
        AgentMemoryConfig(
            enable_episodic_memory=True,
            storage_path=str(tmp_path / "limits.sqlite3"),
            max_episodic_recall=7,
            max_user_records=42,
            user_context_tokens=321,
        ),
        namespace=_namespace(),
    )
    try:
        assert manager.config.episodic_max_recall == 7
        assert manager.config.user_max_records == 42
        assert manager.config.user_context_tokens == 321
    finally:
        await manager.cleanup()


@pytest.mark.asyncio
async def test_agent_config_maps_user_memory_priority(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    """Both priority values map and only the remaining unsupported knobs warn."""
    configs = (
        (AgentMemoryConfig(enable_reflection=False, suppress_trivial_tools=False, flush_on_startup=True), "high"),
        (
            AgentMemoryConfig(
                user_memory_priority="normal",
                enable_reflection=False,
                suppress_trivial_tools=False,
                flush_on_startup=True,
            ),
            "normal",
        ),
    )
    for config, expected_priority in configs:
        assert _manager_config(config).user_priority == expected_priority

        caplog.clear()
        with caplog.at_level("WARNING", logger="parrot.memory.agent_memory.factory"):
            _warn_unsupported_knobs(config)
        assert "enable_reflection" in caplog.text
        assert "suppress_trivial_tools" in caplog.text
        assert "flush_on_startup" in caplog.text
        assert "user_memory_priority" not in caplog.text


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


@pytest.mark.asyncio
@pytest.mark.parametrize("stored_tenant", ["tenant-factory", "other-tenant", None, "no-resolver"])
async def test_factory_wires_trusted_evidence_resolver(tmp_path: Path, stored_tenant: str | None) -> None:
    """Only live tenant-matching ChatStorage metadata can authorize a user-knowledge write."""
    from parrot.memory.agent_memory.models import ChatStorageEvidenceRef, MemoryRequestScope
    from parrot.memory.user.models import UserKnowledgeCandidate, UserKnowledgeCommand

    scope = MemoryRequestScope(
        tenant_id="tenant-factory",
        agent_id="agent-factory",
        user_id="user",
        session_id="session",
        turn_id="turn",
        identity_provenance="server_resolved",
    )
    evidence = ChatStorageEvidenceRef(
        tenant_id=scope.tenant_id, agent_name=scope.agent_id, user_id="user", session_id="session", turn_id="turn"
    )
    observed: list[ChatStorageEvidenceRef] = []

    async def resolver(reference: ChatStorageEvidenceRef) -> str | None:
        """Read trusted metadata; None represents absent or tombstoned storage."""
        observed.append(reference)
        return stored_tenant

    manager = await create_memory_manager(
        AgentMemoryConfig(enable_user_memory=True, storage_path=str(tmp_path / "evidence.db")),
        namespace=_namespace(),
        evidence_tenant_resolver=None if stored_tenant == "no-resolver" else resolver,
    )
    try:
        receipt = await manager.user_memory_store.upsert(
            UserKnowledgeCommand(
                event_id="event",
                candidate=UserKnowledgeCandidate(
                    kind="preference", value="tea", provenance="explicit", evidence_refs=(evidence.to_reference(),)
                ),
            ),
            scope=scope,
        )
        assert receipt.status == ("applied" if stored_tenant == scope.tenant_id else "ignored")
        assert observed == ([] if stored_tenant == "no-resolver" else [evidence])
    finally:
        await manager.cleanup()


@pytest.mark.asyncio
async def test_mixin_passes_evidence_resolver_to_factory(tmp_path: Path) -> None:
    """The host's trusted resolver reaches its real user store through the facade."""
    from parrot.memory.agent_memory.mixin import AgentMemoryMixin
    from parrot.memory.agent_memory.models import ChatStorageEvidenceRef

    class Lifecycle:
        async def configure(self, app: object = None) -> None:
            """Complete minimal cooperative host setup."""

        async def cleanup(self) -> None:
            """Complete minimal cooperative host cleanup."""

    class Host(AgentMemoryMixin, Lifecycle):
        name = "agent-factory"
        tenant_id = "tenant-factory"

    async def resolver(reference: ChatStorageEvidenceRef) -> str | None:
        """Stand in for the trusted metadata service."""
        return reference.tenant_id

    host = Host()
    host.agent_memory_config = {"enable_user_memory": True, "storage_path": str(tmp_path / "host.db")}
    host.memory_evidence_tenant_resolver = resolver
    await host.configure()
    try:
        assert host._memory_manager.user_memory_store._evidence_tenant_resolver is resolver
    finally:
        await host.cleanup()
