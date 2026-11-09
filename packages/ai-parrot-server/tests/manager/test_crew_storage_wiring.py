"""FEAT-860 regression tests for manager storage wiring."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from parrot.handlers.crew.definition_storage import CrewDeletionResolution, CrewStorageConflict, CrewStorageUnavailable
from parrot.handlers.crew.models import AgentDefinition, CrewDefinition
from parrot.manager.manager import BotManager


def _definition(name: str = "crew", crew_id: str = "crew-id") -> CrewDefinition:
    """Build a minimal definition suitable for manager persistence tests."""
    return CrewDefinition(
        name=name,
        crew_id=crew_id,
        tenant="tenant",
        agents=[AgentDefinition(agent_id="agent")],
    )


def _manager(storage: MagicMock) -> BotManager:
    """Build a PostgreSQL-mode manager with the supplied storage fake."""
    with (
        patch("parrot.manager.manager.CrewRedis"),
        patch("parrot.manager.manager.CrewPostgres"),
        patch("parrot.manager.manager.agent_registry"),
    ):
        manager = BotManager(enable_crews=True, crew_storage_backend="postgres")
    manager.crew_storage = storage
    return manager


@pytest.mark.asyncio
async def test_persistence_precedes_cache_mutation() -> None:
    """Failed PostgreSQL writes leave a prior cache entry unchanged."""
    storage = MagicMock()
    storage.save_crew = AsyncMock(side_effect=CrewStorageUnavailable("down"))
    manager = _manager(storage)
    old_crew = MagicMock()
    old_definition = _definition()
    manager._crews["tenant:crew"] = (old_crew, old_definition)

    with pytest.raises(CrewStorageUnavailable):
        await manager.add_crew("new", MagicMock(), _definition("new", "new-id"))

    assert manager._crews == {"tenant:crew": (old_crew, old_definition)}


@pytest.mark.asyncio
async def test_delete_retry_with_empty_cache() -> None:
    """A committed tombstone is an idempotent successful delete after restart."""
    storage = MagicMock()
    storage.resolve_for_delete = AsyncMock(
        return_value=CrewDeletionResolution(state="deleted", definition=_definition())
    )
    manager = _manager(storage)

    assert await manager.remove_crew("crew", "tenant") is True
    storage.delete_crew.assert_not_called()
    assert manager._crews == {}


@pytest.mark.asyncio
async def test_update_is_one_upsert_and_no_delete() -> None:
    """Same-name updates retain identity and replace cache only after one save."""
    storage = MagicMock()
    original = _definition()
    storage.load_crew = AsyncMock(return_value=original)
    storage.save_crew = AsyncMock(return_value=True)
    manager = _manager(storage)
    updated = _definition("crew", "replacement-id")
    updated.created_at = datetime(2025, 1, 1, tzinfo=timezone.utc)
    crew = MagicMock()

    await manager.persist_crew_update("crew", crew, updated)

    storage.save_crew.assert_awaited_once()
    saved = storage.save_crew.await_args.args[0]
    assert saved.crew_id == original.crew_id
    assert saved.created_at == original.created_at
    assert manager._crews["tenant:crew"] == (crew, saved)
    assert not hasattr(storage, "delete_crew") or not storage.delete_crew.called


@pytest.mark.asyncio
async def test_update_failure_preserves_existing_cache() -> None:
    """A failed update save cannot publish its replacement into the cache."""
    storage = MagicMock()
    original = _definition()
    storage.load_crew = AsyncMock(return_value=original)
    storage.save_crew = AsyncMock(side_effect=CrewStorageUnavailable("down"))
    manager = _manager(storage)
    old_crew = MagicMock()
    manager._crews["tenant:crew"] = (old_crew, original)

    with pytest.raises(CrewStorageUnavailable):
        await manager.persist_crew_update("crew", MagicMock(), _definition())

    assert manager._crews == {"tenant:crew": (old_crew, original)}


@pytest.mark.asyncio
async def test_incomplete_sync_preserves_cache() -> None:
    """A failed authoritative inventory cannot trigger cache eviction."""
    storage = MagicMock()
    storage.list_all_crews = AsyncMock(side_effect=CrewStorageUnavailable("down"))
    manager = _manager(storage)
    crew = MagicMock()
    definition = _definition()
    manager._crews["tenant:crew"] = (crew, definition)

    await manager.sync_crews()

    assert manager._crews == {"tenant:crew": (crew, definition)}


@pytest.mark.asyncio
async def test_stale_cached_identity_cannot_delete_recreated_crew() -> None:
    """A stale cache entry cannot evict a recreated authoritative identity."""
    storage = MagicMock()
    storage.resolve_for_delete = AsyncMock(
        return_value=CrewDeletionResolution(state="active", definition=_definition(crew_id="current"))
    )
    manager = _manager(storage)
    manager._crews["tenant:crew"] = (MagicMock(), _definition(crew_id="stale"))

    with pytest.raises(CrewStorageConflict):
        await manager.remove_crew("crew", "tenant")
    assert "tenant:crew" in manager._crews
