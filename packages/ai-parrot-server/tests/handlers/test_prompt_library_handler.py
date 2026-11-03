"""FEAT-794 — PromptLibraryManagement writes through the real handler.

The real handler on a real aiohttp app and a real PostgreSQL (the production
``prompt_library`` shape plus Studio migration 0009). Skipped without
``TEST_STUDIO_PG_DSN``. These live under ``ai-parrot-server/tests`` on purpose:
from ``packages/ai-parrot/tests`` a worktree run resolves ``parrot.handlers`` to
the main checkout's editable install, so the handler under test would not be
the one being changed.
"""
from __future__ import annotations

import asyncio
import os
import uuid

import pytest
from aiohttp import web

_PROD_PROMPT_LIBRARY = (
    "CREATE TABLE navigator.prompt_library ("
    "prompt_id uuid PRIMARY KEY, chatbot_id uuid, title varchar, query varchar, description text, "
    "prompt_category varchar, prompt_tags varchar[], created_at timestamptz NOT NULL DEFAULT now(), "
    "created_by integer, updated_at timestamptz NOT NULL DEFAULT now())"
)
_BASE = "/api/v1/prompt_library"


def _as(user_id: int) -> dict:
    return {"X-Test-User": str(user_id)}


@pytest.fixture
async def prompt_library(aiohttp_client):
    """(client, pool): the production-shaped table plus Studio migration 0009, behind the real handler."""
    dsn = os.environ.get("TEST_STUDIO_PG_DSN")
    if not dsn:
        pytest.skip("TEST_STUDIO_PG_DSN not set; PromptLibraryManagement handler tests need Postgres")
    from asyncdb import AsyncPool
    from navigator_session import SESSION_OBJECT
    from navigator_session.data import SessionData

    from parrot.handlers.bots import PromptLibraryManagement
    from parrot.handlers.studio.storage.migrate import apply_studio_migrations

    pool = AsyncPool("pg", dsn=dsn)
    await pool.connect()
    async with pool.acquire() as conn:
        await conn.execute("CREATE SCHEMA IF NOT EXISTS navigator")
        existing = await conn.fetch_one(
            "SELECT to_regclass('navigator.prompt_library') IS NOT NULL AS present"
        )
        if dict(existing)["present"]:
            rows = await conn.fetch_one("SELECT count(*) AS n FROM navigator.prompt_library")
            if dict(rows)["n"]:
                await pool.close()
                pytest.skip("navigator.prompt_library holds data: TEST_STUDIO_PG_DSN must be a disposable database")
        await conn.execute("DROP TABLE IF EXISTS navigator.prompt_library")
        await conn.execute(_PROD_PROMPT_LIBRARY)
        # Re-run 0009 on the fresh table even when an earlier test already recorded version 9.
        await conn.execute(
            "DO $$ BEGIN IF to_regclass('navigator.ai_studio_migrations') IS NOT NULL THEN "
            "DELETE FROM navigator.ai_studio_migrations WHERE version = 9; END IF; END $$"
        )
    await apply_studio_migrations(pool)

    @web.middleware
    async def _session(request, handler):
        user = request.headers.get("X-Test-User")
        if user:
            request[SESSION_OBJECT] = SessionData(data={"session": {"user_id": int(user)}})
            request["authenticated"] = True
        return await handler(request)

    app = web.Application(middlewares=[_session])
    app["database"] = pool
    PromptLibraryManagement.configure(app, _BASE)
    client = await aiohttp_client(app)
    yield client, pool
    async with pool.acquire() as conn:
        await conn.execute("DROP TABLE IF EXISTS navigator.prompt_library")
    await pool.close()


async def _row(pool, prompt_id: str) -> dict:
    async with pool.acquire() as conn:
        row = await conn.fetch_one("SELECT * FROM navigator.prompt_library WHERE prompt_id = $1", uuid.UUID(prompt_id))
    return dict(row)


class TestPromptLibraryHandler:
    """Writes through the real handler (spec AC1-AC3)."""

    async def test_create_without_category(self, prompt_library):
        """PUT with chatbot_id, title and query only → 201 with a prompt_id; author stamped (AC1)."""
        client, pool = prompt_library
        resp = await client.put(
            _BASE, json={"chatbot_id": str(uuid.uuid4()), "title": "Daily", "query": "Summarise."}, headers=_as(11)
        )
        assert resp.status == 201, await resp.text()
        body = await resp.json()
        row = await _row(pool, body["prompt_id"])
        assert row["prompt_category"] == "other"
        assert row["created_by"] == 11

    async def test_partial_update_keeps_fields_and_author(self, prompt_library):
        """POST /{id} as another user with {"sort_order": 3} → 202; only sort_order and updated_at change (AC2)."""
        client, pool = prompt_library
        resp = await client.put(
            _BASE, json={"chatbot_id": str(uuid.uuid4()), "title": "Daily", "query": "Summarise."}, headers=_as(11)
        )
        assert resp.status == 201, await resp.text()
        prompt_id = (await resp.json())["prompt_id"]
        before = await _row(pool, prompt_id)
        await asyncio.sleep(0.05)

        resp = await client.post(f"{_BASE}/{prompt_id}", json={"sort_order": 3}, headers=_as(22))
        assert resp.status == 202, await resp.text()
        after = await _row(pool, prompt_id)
        assert after["sort_order"] == 3
        assert (after["title"], after["query"], after["chatbot_id"]) == (
            before["title"], before["query"], before["chatbot_id"]
        )
        assert after["created_by"] == 11
        assert after["updated_at"] > before["updated_at"]

    async def test_get_with_new_columns(self, prompt_library):
        """GET ?chatbot_id= → 200 for a row written without the new columns and one created through the handler (AC3)."""
        client, pool = prompt_library
        chatbot_id = uuid.uuid4()
        async with pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO navigator.prompt_library (prompt_id, chatbot_id, title, query, prompt_category) "
                "VALUES ($1, $2, 'Legacy', 'Old row.', 'faq')",
                uuid.uuid4(), chatbot_id,
            )
        resp = await client.put(
            _BASE, json={"chatbot_id": str(chatbot_id), "title": "New", "query": "New row."}, headers=_as(11)
        )
        assert resp.status == 201, await resp.text()

        resp = await client.get(_BASE, params={"chatbot_id": str(chatbot_id)}, headers=_as(11))
        assert resp.status == 200, await resp.text()
        rows = await resp.json()
        rows = rows if isinstance(rows, list) else [rows]
        assert sorted(r["title"] for r in rows) == ["Legacy", "New"]

    async def test_delete_by_body_filter(self, prompt_library):
        """DELETE with a body filter and no pk removes the caller's matching rows (the write hooks stay out of it)."""
        client, pool = prompt_library
        chatbot_id = str(uuid.uuid4())
        for title in ("One", "Two"):
            resp = await client.put(
                _BASE, json={"chatbot_id": chatbot_id, "title": title, "query": "q"}, headers=_as(11)
            )
            assert resp.status == 201, await resp.text()
        resp = await client.delete(_BASE, json={"chatbot_id": chatbot_id}, headers=_as(11))
        assert resp.status in (200, 202, 204), await resp.text()
        async with pool.acquire() as conn:
            left = await conn.fetch_one("SELECT count(*) AS n FROM navigator.prompt_library")
        assert dict(left)["n"] == 0

    async def test_patch_dict_keeps_author_and_stamps_updated_at(self, prompt_library):
        """PATCH /{id} with a dict body as another user → author kept, updated_at advanced (the PATCH hooks)."""
        client, pool = prompt_library
        resp = await client.put(
            _BASE, json={"chatbot_id": str(uuid.uuid4()), "title": "Daily", "query": "q"}, headers=_as(11)
        )
        assert resp.status == 201, await resp.text()
        prompt_id = (await resp.json())["prompt_id"]
        before = await _row(pool, prompt_id)
        await asyncio.sleep(0.05)

        resp = await client.patch(f"{_BASE}/{prompt_id}", json={"sort_order": 5}, headers=_as(22))
        assert resp.status == 202, await resp.text()
        after = await _row(pool, prompt_id)
        assert after["sort_order"] == 5
        assert after["created_by"] == 11
        assert after["updated_at"] > before["updated_at"]

