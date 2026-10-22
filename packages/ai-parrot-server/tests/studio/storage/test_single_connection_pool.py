"""Review fix: no service reads through ``pool.acquire()`` while its own write transaction holds a connection.

A pool of exactly one connection makes that mistake a deadlock, so every transactional service path must finish.
"""
import asyncio
import os

import pytest
from asyncdb import AsyncPool
from aiohttp import web

from parrot.handlers.studio.storage.migrate import apply_studio_migrations
from parrot.handlers.studio.storage.models import (
    StudioAgentBundle,
    StudioAgentDefinition,
    StudioAgentPatch,
    StudioAssetInput,
    StudioPartition,
    StudioWriteGuard,
)
from parrot.handlers.studio.storage.repositories import build_studio_repositories
from parrot.handlers.studio.storage.services._common import build_studio_services

GLOBAL = StudioPartition.GLOBAL
GUARD = StudioWriteGuard()


@pytest.fixture
async def one_connection_services():
    dsn = os.environ.get("TEST_STUDIO_PG_DSN")
    if not dsn:
        pytest.skip("TEST_STUDIO_PG_DSN not set; Studio storage integration tests need Postgres")
    setup = AsyncPool("pg", dsn=dsn)
    await setup.connect()
    await apply_studio_migrations(setup)
    async with setup.acquire() as conn:
        for table in ("ai_agent_assets", "ai_agent_tooling", "ai_agent_drafts", "ai_agents", "ai_skills_catalog"):
            await conn.execute(f"TRUNCATE navigator.{table} CASCADE")
    await setup.close()
    pool = AsyncPool("pg", dsn=dsn, min_size=1, max_clients=1)
    await pool.connect()
    yield build_studio_services(web.Application(), build_studio_repositories(pool))
    async with pool.acquire() as conn:
        for table in ("ai_agent_assets", "ai_agent_tooling", "ai_agent_drafts", "ai_agents", "ai_skills_catalog"):
            await conn.execute(f"TRUNCATE navigator.{table} CASCADE")
    await pool.close()


async def test_every_transactional_path_completes_on_a_pool_of_one(one_connection_services):
    s = one_connection_services

    async def scenario():
        await s.agents.create(GLOBAL, name="a1", owner="u1", definition=StudioAgentDefinition())
        await s.agents.patch(GLOBAL, "a1", StudioAgentPatch(description="d"), guard=GUARD)
        await s.assets.put(GLOBAL, "a1", StudioAssetInput(kind="kb", name="k.md", content="x"), actor="u1",
                           guard=GUARD)
        await s.assets.put(GLOBAL, "a1", StudioAssetInput(kind="kb", name="k.md", content="yy"), actor="u1",
                           guard=GUARD)                                   # replacement reads the old size
        await s.assets.delete(GLOBAL, "a1", "kb", "k.md", actor="u1", guard=GUARD)
        await s.tooling.put_mcp_servers(GLOBAL, "a1", [{"name": "m", "url": "https://m/"}], actor="u1", guard=GUARD)
        await s.drafts.save_bundle(GLOBAL, owner="u1", bundle=StudioAgentBundle(name="d1",
                                                                              definition=StudioAgentDefinition()))
        await s.drafts.save_bundle(GLOBAL, owner="u1", bundle=StudioAgentBundle(name="d1",
                                                                              definition=StudioAgentDefinition()))
        await s.drafts.activate(GLOBAL, "d1", owner="u1")
        await s.drafts.save_bundle(GLOBAL, owner="u1", bundle=StudioAgentBundle(
            name="a1", definition=StudioAgentDefinition(description="replaced")))
        return await s.drafts.activate(GLOBAL, "a1", owner="u1", replace=True)

    record = await asyncio.wait_for(scenario(), timeout=30)
    assert record.definition.description == "replaced"
