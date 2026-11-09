"""Live Redis/Postgres migration-race coverage for FEAT-860.

These tests require an explicitly supplied disposable Redis endpoint.  They
use unique key prefixes and delete exact owned keys only; ``FLUSHDB`` is never
used.  Skipping this module is disclosed by its environment gate and is not
live migration evidence.
"""

from __future__ import annotations

import asyncio
import os
import uuid

import pytest
from parrot.handlers.crew.definition_storage import CrewDefinitionStorage
from parrot.handlers.crew.models import AgentDefinition, CrewDefinition, FlowRelation, ToolNodeDefinition
from parrot.handlers.crew.postgres_persistence import CrewPostgres
from parrot.handlers.crew.redis_persistence import CrewRedis

DSN = os.getenv("NAVIGATOR_PG_DSN", "")
REDIS_URL = os.getenv("CREW_MIGRATION_TEST_REDIS_URL", "")
pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(not DSN or not REDIS_URL, reason="NAVIGATOR_PG_DSN and CREW_MIGRATION_TEST_REDIS_URL required"),
]


def _crew(name: str, crew_id: str, tenant: str, *, version: int) -> CrewDefinition:
    """Build a valid definition whose payload version is observable in Redis."""
    return CrewDefinition(
        crew_id=crew_id,
        tenant=tenant,
        name=name,
        description=f"FEAT-860 version {version}",
        agents=[AgentDefinition(agent_id="researcher", name="Researcher")],
        tool_nodes=[ToolNodeDefinition(node_id="publish", tool="publish_report")],
        flow_relations=[FlowRelation(source="Researcher", target="publish")],
        metadata={"version": version},
    )


async def _delete_owned_rows(postgres: CrewPostgres, crews: list[CrewDefinition]) -> None:
    """Remove only exact fixture identities, including global legacy probes."""
    database = postgres._get_db()
    async with await database.connection() as connection:
        for crew in crews:
            await connection.execute(
                "DELETE FROM navigator.crew_definitions WHERE tenant = $1 AND name = $2 AND crew_id = $3",
                crew.tenant or "global",
                crew.name,
                crew.crew_id,
            )


async def _delete_owned_redis_keys(store: CrewRedis, crews: list[CrewDefinition]) -> None:
    """Delete exact per-test keys without scanning or flushing a shared Redis DB."""
    keys = [store._get_tenants_key()]
    for crew in crews:
        tenant = crew.tenant or "global"
        keys.extend(
            [
                store._get_key(crew.name, tenant),
                store._get_list_key(tenant),
                store._get_id_mapping_key(crew.crew_id, tenant),
            ]
        )
        if tenant == "global":
            keys.extend([store._get_legacy_key(crew.name), store._get_legacy_list_key(), store._get_legacy_id_mapping_key(crew.crew_id)])
    await store.redis.delete(*keys)


def _live_stores() -> tuple[CrewRedis, CrewPostgres, CrewDefinitionStorage, str]:
    """Build isolated client instances and identities for one live scenario."""
    marker = uuid.uuid4().hex
    redis = CrewRedis(redis_url=REDIS_URL, key_prefix=f"feat860-live-{marker}")
    postgres = CrewPostgres(DSN)
    return redis, postgres, CrewDefinitionStorage(redis, postgres, migration=True), f"feat860-pg-{marker}"


@pytest.mark.asyncio
async def test_live_changed_redis_snapshot_is_preserved() -> None:
    """A barrier-controlled write between snapshot and Lua cleanup survives."""
    redis, postgres, storage, tenant = _live_stores()
    first = _crew("research", uuid.uuid4().hex, tenant, version=1)
    changed = _crew(first.name, first.crew_id, tenant, version=2)
    snapshot_ready = asyncio.Event()
    write_finished = asyncio.Event()
    original_delete_snapshot = redis.delete_snapshot

    async def delete_after_write(snapshot: object) -> object:
        """Hold real Lua cleanup until the concurrent writer has completed."""
        snapshot_ready.set()
        await write_finished.wait()
        return await original_delete_snapshot(snapshot)  # type: ignore[arg-type]

    async def concurrent_writer() -> None:
        """Persist the changed payload while migration owns its PG advisory lock."""
        await snapshot_ready.wait()
        assert await redis.save_crew(changed) is True
        write_finished.set()

    try:
        await postgres.ensure_schema()
        assert await redis.save_crew(first) is True
        redis.delete_snapshot = delete_after_write  # type: ignore[method-assign]
        writer = asyncio.create_task(concurrent_writer())
        report = await storage.migrate_from_redis()
        await writer

        key = f"{tenant}:{first.name}"
        assert report.failed[key] == "source changed"
        retained = await redis.load_crew(first.name, tenant)
        assert retained is not None
        assert retained.metadata == {"version": 2}
        assert await redis.redis.get(redis._get_id_mapping_key(first.crew_id, tenant)) == first.name
    finally:
        await _delete_owned_redis_keys(redis, [first])
        await _delete_owned_rows(postgres, [first])
        await redis.close()


@pytest.mark.asyncio
async def test_live_legacy_and_reassigned_mapping_survive() -> None:
    """A newly appearing global legacy key and reassigned mapping block cleanup."""
    redis, postgres, storage, _ = _live_stores()
    first = _crew("global-research", uuid.uuid4().hex, "global", version=1)
    replacement_name = f"replacement-{uuid.uuid4().hex}"
    snapshot_ready = asyncio.Event()
    write_finished = asyncio.Event()
    original_delete_snapshot = redis.delete_snapshot

    async def delete_after_global_change(snapshot: object) -> object:
        """Ensure legacy and mapping changes occur before the real Lua comparison."""
        snapshot_ready.set()
        await write_finished.wait()
        return await original_delete_snapshot(snapshot)  # type: ignore[arg-type]

    async def mutate_legacy_and_mapping() -> None:
        """Create a legacy source and repoint the ID mapping without sleeps."""
        await snapshot_ready.wait()
        await redis.redis.set(redis._get_legacy_key(first.name), redis._serialize_crew(_crew(first.name, first.crew_id, "global", version=2)))
        await redis.redis.set(redis._get_id_mapping_key(first.crew_id, "global"), replacement_name)
        await redis.redis.set(redis._get_legacy_id_mapping_key(first.crew_id), replacement_name)
        write_finished.set()

    try:
        await postgres.ensure_schema()
        assert await redis.save_crew(first) is True
        redis.delete_snapshot = delete_after_global_change  # type: ignore[method-assign]
        writer = asyncio.create_task(mutate_legacy_and_mapping())
        report = await storage.migrate_from_redis()
        await writer

        key = f"global:{first.name}"
        assert report.failed[key] == "source changed"
        assert await redis.redis.get(redis._get_key(first.name, "global")) is not None
        assert await redis.redis.get(redis._get_legacy_key(first.name)) is not None
        assert await redis.redis.get(redis._get_id_mapping_key(first.crew_id, "global")) == replacement_name
        assert await redis.redis.get(redis._get_legacy_id_mapping_key(first.crew_id)) == replacement_name
    finally:
        await _delete_owned_redis_keys(redis, [first])
        await _delete_owned_rows(postgres, [first])
        await redis.close()


@pytest.mark.asyncio
async def test_live_rerun_dry_run_and_conflicts() -> None:
    """Dry runs mutate nothing; reruns retain definitions differing from PG."""
    redis, postgres, storage, tenant = _live_stores()
    first = _crew("research", uuid.uuid4().hex, tenant, version=1)
    conflicting = _crew(first.name, first.crew_id, tenant, version=2)
    try:
        await postgres.ensure_schema()
        assert await redis.save_crew(first) is True
        raw_before_dry_run = await redis.redis.get(redis._get_key(first.name, tenant))
        dry_report = await storage.migrate_from_redis(dry_run=True)
        assert dry_report.migrated == [f"{tenant}:{first.name}"]
        assert await postgres._load_row(first.name, tenant) is None
        assert await redis.redis.get(redis._get_key(first.name, tenant)) == raw_before_dry_run

        migrated = await storage.migrate_from_redis()
        assert migrated.migrated == [f"{tenant}:{first.name}"]
        assert await redis.redis.get(redis._get_key(first.name, tenant)) is None

        assert await redis.save_crew(conflicting) is True
        conflict_report = await storage.migrate_from_redis()
        key = f"{tenant}:{first.name}"
        assert conflict_report.conflicts == [key]
        assert conflict_report.failed[key] == "definition conflict"
        retained = await redis.load_crew(first.name, tenant)
        assert retained is not None
        assert retained.metadata == {"version": 2}
    finally:
        await _delete_owned_redis_keys(redis, [first])
        await _delete_owned_rows(postgres, [first])
        await redis.close()
