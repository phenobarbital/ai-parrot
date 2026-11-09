"""Live Postgres coverage for FEAT-860 crew-definition persistence.

The module is deliberately skipped unless ``NAVIGATOR_PG_DSN`` names a
disposable Postgres instance.  Every test uses a distinct tenant and deletes
only rows for that tenant; it never drops the shared schema or table.
"""

from __future__ import annotations

import os
import uuid

import pytest
from asyncdb import AsyncDB
from parrot.handlers.crew.models import AgentDefinition, CrewDefinition, FlowRelation, ToolNodeDefinition
from parrot.handlers.crew.postgres_persistence import CrewPostgres

DSN = os.getenv("NAVIGATOR_PG_DSN", "")
pytestmark = [pytest.mark.asyncio, pytest.mark.skipif(not DSN, reason="NAVIGATOR_PG_DSN not set (live PG checks skipped)")]


def _crew(name: str, crew_id: str, tenant: str, *, metadata: dict[str, object] | None = None) -> CrewDefinition:
    """Build a complete definition with JSONB-representable nested data."""
    return CrewDefinition(
        crew_id=crew_id,
        tenant=tenant,
        name=name,
        description="FEAT-860 live crew",
        agents=[AgentDefinition(agent_id="researcher", name="Researcher")],
        tool_nodes=[ToolNodeDefinition(node_id="publish", tool="publish_report")],
        flow_relations=[FlowRelation(source="Researcher", target="publish")],
        metadata=metadata or {"live": {"round_trip": True}},
    )


async def _delete_tenant_rows(tenant: str) -> None:
    """Remove only rows owned by one disposable live-test tenant."""
    database = AsyncDB("pg", dsn=DSN)
    async with await database.connection() as connection:
        await connection.execute("DELETE FROM navigator.crew_definitions WHERE tenant = $1", tenant)


@pytest.mark.asyncio
async def test_live_round_trip_tombstone_and_id_collision() -> None:
    """Exercise both unique constraints, JSONB/timestamps, and tombstones live."""
    tenant = f"feat860-pg-{uuid.uuid4().hex}"
    store = CrewPostgres(DSN)
    original = _crew("research", uuid.uuid4().hex, tenant)
    same_name = _crew("research", uuid.uuid4().hex, tenant)
    same_id = _crew("analysis", original.crew_id, tenant)
    try:
        await store.ensure_schema()
        before_save = original.updated_at
        assert await store.save_crew(original) is True
        loaded = await store.load_crew(original.name, tenant)
        assert loaded is not None
        assert loaded.model_dump(mode="json") == original.model_dump(mode="json")
        assert loaded.updated_at > before_save
        assert loaded.metadata == {"live": {"round_trip": True}}

        assert await store.insert_if_absent(same_name) is False
        retained_after_name_conflict = await store.load_crew(original.name, tenant)
        assert retained_after_name_conflict is not None
        assert retained_after_name_conflict.crew_id == original.crew_id
        with pytest.raises(Exception):
            await store.insert_if_absent(same_id)

        assert await store.delete_crew(original) is True
        tombstone = await store._load_row(original.name, tenant)
        assert tombstone is not None
        assert tombstone.deleted_at is not None
        assert await store.load_crew(original.name, tenant) is None
        assert await store.load_crew_by_id(original.crew_id, tenant) is None
    finally:
        await _delete_tenant_rows(tenant)


@pytest.mark.asyncio
async def test_live_lock_exclusion_and_release() -> None:
    """Verify migration advisory locks exclude peers and release on exit."""
    first = CrewPostgres(DSN)
    second = CrewPostgres(DSN)
    await first.ensure_schema()
    async with first.migration_lock() as acquired:
        assert acquired is True
        async with second.migration_lock() as contender_acquired:
            assert contender_acquired is False

    async with second.migration_lock() as acquired_after_release:
        assert acquired_after_release is True
