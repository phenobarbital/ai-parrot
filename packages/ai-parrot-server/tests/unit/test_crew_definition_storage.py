"""FEAT-860 regression tests for authoritative crew definition routing."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from parrot.handlers.crew.definition_storage import (
    CrewDefinitionStorage,
    CrewStorageConflict,
    CrewStorageUnavailable,
)
from parrot.handlers.crew.redis_persistence import CrewRedisCleanupResult
from parrot.handlers.crew.models import AgentDefinition, CrewDefinition


def _crew(name: str, crew_id: str, tenant: str = "global") -> CrewDefinition:
    """Build a minimal valid crew definition for storage tests."""
    return CrewDefinition(
        name=name,
        crew_id=crew_id,
        tenant=tenant,
        agents=[AgentDefinition(agent_id="agent")],
    )


def _row(crew: CrewDefinition, *, deleted: bool = False) -> SimpleNamespace:
    """Build the row shape consumed by the composition's PG row APIs."""
    return SimpleNamespace(
        tenant=crew.tenant,
        name=crew.name,
        crew_id=crew.crew_id,
        definition=crew,
        deleted_at=datetime.now(timezone.utc) if deleted else None,
    )


class FakePostgres:
    """Stateful Postgres row fake preserving tombstones and call failures."""

    def __init__(self, rows: list[SimpleNamespace] | None = None) -> None:
        """Initialize rows indexed by their authoritative identities."""
        self.rows = rows or []
        self.save_error: Exception | None = None
        self.delete_error: Exception | None = None
        self.ping_result = True
        self.closed = False
        self.lock_acquired = True
        self.lock_released = False
        self.malformed: set[str] = set()

    async def ping(self) -> bool:
        """Return configurable health."""
        return self.ping_result

    async def close(self) -> None:
        """Record lifecycle cleanup."""
        self.closed = True

    async def save_crew(self, crew: CrewDefinition) -> bool:
        """Save a new active row or raise the configured failure."""
        if self.save_error:
            raise self.save_error
        self.rows = [row for row in self.rows if (row.tenant, row.name) != (crew.tenant, crew.name)]
        self.rows.append(_row(crew))
        return True

    async def create_crew(self, crew: CrewDefinition) -> bool:
        """Create a new name or revive a tombstone; refuse a live same-name row."""
        existing = await self._load_row(crew.name, crew.tenant)
        if existing is not None and existing.deleted_at is None:
            return False
        by_id = await self._load_row_by_id(crew.crew_id, crew.tenant)
        if by_id is not None and (existing is None or by_id.crew_id != existing.crew_id):
            raise ValueError("identity conflict")
        self.rows = [row for row in self.rows if (row.tenant, row.name) != (crew.tenant, crew.name)]
        self.rows.append(_row(crew))
        return True

    async def tombstone_identity(self, tenant: str | None, name: str, crew_id: str) -> bool:
        """Tombstone a stored row by identity without decoding its document."""
        existing = await self._load_row(name, tenant)
        if existing is None or existing.crew_id != crew_id:
            raise ValueError("identity conflict")
        existing.deleted_at = datetime.now(timezone.utc)
        return True

    async def insert_if_absent(self, crew: CrewDefinition) -> bool:
        """Insert only an unreserved name, preserving uniqueness failures."""
        if await self._load_row(crew.name, crew.tenant) is not None:
            return False
        if await self._load_row_by_id(crew.crew_id, crew.tenant) is not None:
            raise ValueError("identity conflict")
        self.rows.append(_row(crew))
        return True

    async def delete_crew(self, crew: CrewDefinition) -> bool:
        """Durably replace the matching row with a tombstone."""
        if self.delete_error:
            raise self.delete_error
        existing = await self._load_row(crew.name, crew.tenant)
        if existing is not None and existing.crew_id != crew.crew_id:
            raise ValueError("identity conflict")
        self.rows = [row for row in self.rows if (row.tenant, row.name) != (crew.tenant, crew.name)]
        self.rows.append(_row(crew, deleted=True))
        return True

    async def _load_row(self, name: str, tenant: str | None = None) -> SimpleNamespace | None:
        """Find a row by normalized tenant/name."""
        normalized_tenant = tenant or "global"
        return next((row for row in self.rows if (row.tenant, row.name) == (normalized_tenant, name)), None)

    async def _load_row_by_id(self, crew_id: str, tenant: str | None = None) -> SimpleNamespace | None:
        """Find a row by normalized tenant/ID."""
        normalized_tenant = tenant or "global"
        return next((row for row in self.rows if (row.tenant, row.crew_id) == (normalized_tenant, crew_id)), None)

    async def _list_rows(self, tenant: str | None = None) -> list[SimpleNamespace]:
        """Return all rows for the requested tenant scope."""
        return [row for row in self.rows if tenant is None or row.tenant == (tenant or "global")]

    @asynccontextmanager
    async def migration_lock(self):
        """Expose a releasable lock for migration tests."""
        try:
            yield self.lock_acquired
        finally:
            self.lock_released = True

    def _decode_row(self, row: SimpleNamespace) -> CrewDefinition:
        """Return the decoded fake document, or fail like a malformed stored payload."""
        if row.name in self.malformed:
            raise ValueError("malformed stored definition")
        return row.definition


class FakeRedis:
    """Stateful Redis fake exposing strict inventory/snapshot contracts."""

    def __init__(self, crews: list[CrewDefinition] | None = None) -> None:
        """Initialize Redis candidates indexed by name and ID."""
        self.crews = crews or []
        self.save_crew = AsyncMock(return_value=True)
        self.delete_crew = AsyncMock(return_value=True)
        self.closed = False
        self.incomplete_name: str | None = None
        self.unreadable_name: str | None = None
        self.cleanup = AsyncMock(return_value=CrewRedisCleanupResult.deleted)

    async def ping(self) -> bool:
        """Return successful fake Redis health."""
        return True

    async def close(self) -> None:
        """Record lifecycle cleanup."""
        self.closed = True

    async def load_crew(self, name: str, tenant: str | None = None) -> CrewDefinition | None:
        """Find a crew by name."""
        normalized_tenant = tenant or "global"
        return next((crew for crew in self.crews if (crew.tenant, crew.name) == (normalized_tenant, name)), None)

    async def load_crew_by_id(self, crew_id: str, tenant: str | None = None) -> CrewDefinition | None:
        """Find a crew by ID."""
        normalized_tenant = tenant or "global"
        return next((crew for crew in self.crews if (crew.tenant, crew.crew_id) == (normalized_tenant, crew_id)), None)

    async def list_all_crews_strict(self) -> list[dict[str, str]]:
        """Return the complete strict inventory."""
        return [{"tenant": crew.tenant, "name": crew.name} for crew in self.crews]

    async def snapshot_crew(self, name: str, tenant: str | None = None) -> SimpleNamespace | None:
        """Return one snapshot or model an entry disappearing during capture."""
        if name == self.unreadable_name:
            raise ValueError("malformed Redis definition")
        if name == self.incomplete_name:
            return None
        crew = await self.load_crew(name, tenant)
        if crew is None:
            return None
        return SimpleNamespace(tenant=crew.tenant, name=crew.name, definition=crew)

    async def delete_snapshot(self, snapshot: SimpleNamespace) -> CrewRedisCleanupResult:
        """Conditionally remove the captured fake source."""
        result = await self.cleanup(snapshot)
        if result is CrewRedisCleanupResult.deleted:
            self.crews = [crew for crew in self.crews if (crew.tenant, crew.name) != (snapshot.tenant, snapshot.name)]
        return result


@pytest.mark.asyncio
async def test_write_failure_never_uses_redis() -> None:
    """Postgres write failures propagate without a Redis downgrade."""
    existing = _crew("existing", "id-v1")
    redis = FakeRedis([existing])
    postgres = FakePostgres([_row(existing)])
    postgres.save_error = ConnectionError("database unavailable")
    storage = CrewDefinitionStorage(redis, postgres)

    with pytest.raises(CrewStorageUnavailable) as error:
        await storage.save_crew(_crew("existing", "id-v2"))

    assert isinstance(error.value.__cause__, ConnectionError)
    redis.save_crew.assert_not_awaited()
    assert (await storage.load_crew("existing")).crew_id == "id-v1"


@pytest.mark.asyncio
async def test_tombstone_suppresses_all_aliases() -> None:
    """A tombstoned ID suppresses Redis aliases in every read surface."""
    deleted = _crew("removed", "deleted-id")
    stale_alias = _crew("stale-alias", "deleted-id")
    redis = FakeRedis([stale_alias])
    storage = CrewDefinitionStorage(redis, FakePostgres([_row(deleted, deleted=True)]))

    assert await storage.load_crew("stale-alias") is None
    assert await storage.load_crew_by_id("deleted-id") is None
    assert await storage.list_all_crews() == []
    assert await storage.get_all_crews() == []
    resolution = await storage.resolve_for_delete("deleted-id")
    assert resolution.state == "deleted"
    assert resolution.definition.crew_id == "deleted-id"


@pytest.mark.asyncio
async def test_union_snapshot_order_and_incomplete_inventory() -> None:
    """Union results are ordered and reject a Redis snapshot that disappears."""
    postgres_crew = _crew("postgres", "pg-id", "beta")
    redis_crew = _crew("redis", "redis-id", "alpha")
    redis = FakeRedis([redis_crew])
    storage = CrewDefinitionStorage(redis, FakePostgres([_row(postgres_crew)]))

    assert await storage.list_all_crews() == [
        {"tenant": "alpha", "name": "redis"},
        {"tenant": "beta", "name": "postgres"},
    ]
    assert [crew.name for crew in await storage.get_all_crews()] == ["redis", "postgres"]

    redis.incomplete_name = "redis"
    with pytest.raises(CrewStorageUnavailable):
        await storage.get_all_crews()


@pytest.mark.asyncio
async def test_vanished_redis_entry_is_resolved_against_postgres_rows() -> None:
    """An inventory entry that vanished because it was migrated is explained by its Postgres row."""
    moved = _crew("moved", "moved-id")
    redis = FakeRedis([moved])
    redis.incomplete_name = "moved"
    storage = CrewDefinitionStorage(redis, FakePostgres([_row(moved)]))

    assert await storage.list_all_crews() == [{"tenant": "global", "name": "moved"}]
    assert [crew.crew_id for crew in await storage.get_all_crews()] == ["moved-id"]


@pytest.mark.asyncio
async def test_unreadable_redis_source_does_not_hide_postgres_crews() -> None:
    """A malformed or conflicting Redis source is skipped, not allowed to fail the authoritative listing."""
    bad = _crew("bad", "bad-id")
    good = _crew("good", "good-id")
    redis = FakeRedis([bad])
    redis.unreadable_name = "bad"
    storage = CrewDefinitionStorage(redis, FakePostgres([_row(good)]))

    assert await storage.list_all_crews() == [{"tenant": "global", "name": "good"}]
    assert [crew.name for crew in await storage.get_all_crews()] == ["good"]


@pytest.mark.asyncio
async def test_create_refuses_live_name_but_revives_tombstone() -> None:
    """Create never replaces a live crew, reports ID collisions, and may reuse a tombstoned name."""
    live = _crew("taken", "live-id")
    postgres = FakePostgres([_row(live), _row(_crew("gone", "gone-id"), deleted=True)])
    storage = CrewDefinitionStorage(FakeRedis(), postgres)

    with pytest.raises(CrewStorageConflict):
        await storage.create_crew(_crew("taken", "other-id"))
    assert (await storage.load_crew("taken")).crew_id == "live-id"

    with pytest.raises(CrewStorageConflict):
        await storage.create_crew(_crew("fresh", "live-id"))

    assert await storage.create_crew(_crew("gone", "new-id")) is True
    assert (await storage.load_crew("gone")).crew_id == "new-id"

    postgres.save_error = ConnectionError("database unavailable")
    redis_save = storage.redis.save_crew
    postgres.create_crew = AsyncMock(side_effect=ConnectionError("database unavailable"))
    with pytest.raises(CrewStorageUnavailable):
        await storage.create_crew(_crew("other", "other-2"))
    redis_save.assert_not_awaited()


@pytest.mark.asyncio
async def test_malformed_row_resolves_with_identity_and_can_be_tombstoned() -> None:
    """A row whose document cannot be decoded still carries its identity and can be deleted."""
    broken = _crew("broken", "broken-id")
    postgres = FakePostgres([_row(broken)])
    postgres.malformed.add("broken")
    storage = CrewDefinitionStorage(FakeRedis(), postgres)

    resolution = await storage.resolve_for_delete("broken")
    assert resolution.state == "active"
    assert resolution.definition is None
    assert (resolution.tenant, resolution.name, resolution.crew_id) == ("global", "broken", "broken-id")

    assert await storage.tombstone_resolution(resolution) is True
    assert (await storage.resolve_for_delete("broken")).state == "deleted"
    assert await storage.load_crew("broken") is None

    stale = resolution.model_copy(update={"crew_id": "recreated"})
    with pytest.raises(CrewStorageConflict):
        await storage.tombstone_resolution(stale)


@pytest.mark.asyncio
async def test_redis_only_crew_resolves_active_for_delete() -> None:
    """A Redis-only crew must resolve as active so it can receive a tombstone."""
    crew = _crew("legacy", "legacy-id")
    storage = CrewDefinitionStorage(FakeRedis([crew]), FakePostgres())

    by_name = await storage.resolve_for_delete("legacy")
    by_id = await storage.resolve_for_delete("legacy-id")
    assert by_name.state == by_id.state == "active"
    assert by_name.definition.crew_id == by_id.definition.crew_id == "legacy-id"

    assert await storage.delete_crew(by_name.definition) is True
    resolution = await storage.resolve_for_delete("legacy")
    assert resolution.state == "deleted"
    assert (await storage.resolve_for_delete("missing")).state == "absent"


@pytest.mark.asyncio
async def test_delete_failure_and_retry_resolution() -> None:
    """Failed deletes retain Redis, while retry resolution finds a tombstone."""
    crew = _crew("remove-me", "remove-id")
    redis = FakeRedis([crew])
    postgres = FakePostgres([_row(crew)])
    postgres.delete_error = ConnectionError("database unavailable")
    storage = CrewDefinitionStorage(redis, postgres)

    with pytest.raises(CrewStorageUnavailable):
        await storage.delete_crew(crew)
    redis.delete_crew.assert_not_awaited()
    assert (await storage.load_crew("remove-me")).crew_id == "remove-id"

    postgres.delete_error = None
    redis.delete_crew.return_value = False
    assert await storage.delete_crew(crew) is True
    resolution = await storage.resolve_for_delete("remove-id")
    assert resolution.state == "deleted"
    assert resolution.definition.crew_id == "remove-id"


@pytest.mark.asyncio
async def test_migration_preserves_different_and_changed_sources() -> None:
    """Different authoritative documents and changed Redis snapshots remain intact."""
    source = _crew("legacy", "legacy-id")
    conflicting = source.model_copy(update={"description": "Postgres wins"})
    redis = FakeRedis([source])
    postgres = FakePostgres([_row(conflicting)])
    storage = CrewDefinitionStorage(redis, postgres)

    conflict_report = await storage.migrate_from_redis()
    assert conflict_report.conflicts == ["global:legacy"]
    assert conflict_report.failed == {"global:legacy": "definition conflict"}
    assert redis.crews == [source]
    redis.cleanup.assert_not_awaited()

    postgres.rows = []
    redis.cleanup.return_value = CrewRedisCleanupResult.source_changed
    changed_report = await storage.migrate_from_redis()
    assert changed_report.failed == {"global:legacy": "source changed"}
    assert changed_report.migrated == []
    assert redis.crews == [source]
    assert postgres.lock_released is True


@pytest.mark.asyncio
async def test_dry_run_and_lock_failure_mutate_nothing() -> None:
    """No DDL/data mutation on dry run, held lock, or inventory failure."""
    source = _crew("legacy", "legacy-id")
    redis = FakeRedis([source])
    postgres = FakePostgres()
    storage = CrewDefinitionStorage(redis, postgres)

    dry_run = await storage.migrate_from_redis(dry_run=True)
    assert dry_run.dry_run is True
    assert dry_run.migrated == ["global:legacy"]
    assert postgres.rows == []
    redis.cleanup.assert_not_awaited()

    postgres.lock_acquired = False
    locked = await storage.migrate_from_redis()
    assert locked.lock_acquired is False
    assert locked.skipped_reason == "Migration advisory lock not acquired"
    assert postgres.rows == []
    redis.cleanup.assert_not_awaited()

    postgres.lock_acquired = True
    postgres.lock_released = False

    async def cancelled_inventory() -> list[dict[str, str]]:
        """Model cancellation while the migration lock is held."""
        raise asyncio.CancelledError

    redis.list_all_crews_strict = cancelled_inventory
    with pytest.raises(asyncio.CancelledError):
        await storage.migrate_from_redis()
    assert postgres.lock_released is True
