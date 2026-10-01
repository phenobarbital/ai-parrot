"""FEAT-621 storage test fixtures (spec §4)."""
import asyncio
import os

import pytest
from aiohttp.test_utils import make_mocked_request
from asyncdb import AsyncPool
from navigator_session.data import SessionData

from parrot.handlers.studio.storage.migrate import apply_studio_migrations

STUDIO_TABLES = ("ai_agent_assets", "ai_agent_tooling", "ai_agent_drafts", "ai_agents", "ai_skills_catalog")


async def _truncate_studio_tables(pool) -> None:
    """TRUNCATE the Studio data tables (never the ledger)."""
    async with pool.acquire() as conn:
        for table in STUDIO_TABLES:
            await conn.execute(f"TRUNCATE navigator.{table} CASCADE")


@pytest.fixture
async def studio_pool():
    dsn = os.environ.get("TEST_STUDIO_PG_DSN")
    if not dsn:
        pytest.skip("TEST_STUDIO_PG_DSN not set; Studio storage integration tests need Postgres")
    pool = AsyncPool("pg", dsn=dsn)
    await pool.connect()
    await apply_studio_migrations(pool)
    yield pool
    await _truncate_studio_tables(pool)
    await pool.close()


def real_request(app, method, path, *, user_id="u1", groups=(), superuser=False, match_info=None):
    """A mocked aiohttp request carrying a real ``SessionData`` (never a hand-set ``.session``)."""
    req = make_mocked_request(method, path, app=app, match_info=match_info or {})
    req["NAV_SESSION"] = SessionData(
        data={"session": {"user_id": user_id, "groups": list(groups), "superuser": superuser}}
    )
    return req


@pytest.fixture
def no_subprocess(monkeypatch):
    async def _refuse(*a, **k):
        raise AssertionError("a process was started")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", _refuse)
