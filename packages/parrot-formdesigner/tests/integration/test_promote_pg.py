"""promote() against real Postgres (skips without SCRATCH_DSN).

Every unit test replaces ``promote()`` with a double, so the SQL itself never met a database: its
``WHERE`` referenced ``schema_json`` / ``version`` unqualified inside ``ON CONFLICT DO UPDATE``,
which Postgres rejects as ambiguous (existing row vs ``EXCLUDED``). Every publish() of a version
that already had a row (the normal case: publishing a draft) failed with AmbiguousColumnError.
"""

from __future__ import annotations

import json
import os
import uuid
from collections.abc import AsyncIterator
from typing import Any

import pytest
from parrot_formdesigner.services.storage import PostgresFormStorage

_SCRATCH_DSN = os.getenv("SCRATCH_DSN")
pytestmark = pytest.mark.skipif(not _SCRATCH_DSN, reason="SCRATCH_DSN not set (scratch Postgres required)")

SCHEMA = "pfd_promote_test"


@pytest.fixture
async def storage() -> AsyncIterator[PostgresFormStorage]:
    import asyncpg

    pool = await asyncpg.create_pool(dsn=_SCRATCH_DSN, min_size=1, max_size=2)
    async with pool.acquire() as conn:
        await conn.execute(f'DROP SCHEMA IF EXISTS "{SCHEMA}" CASCADE')
        await conn.execute(f'CREATE SCHEMA "{SCHEMA}"')
        await conn.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
    store = PostgresFormStorage(pool=pool, schema=SCHEMA)
    async with pool.acquire() as conn:
        await conn.execute(store._create_table_sql(None))
    try:
        yield store
    finally:
        async with pool.acquire() as conn:
            await conn.execute(f'DROP SCHEMA IF EXISTS "{SCHEMA}" CASCADE')
        await pool.close()


def _schema(form_uid: uuid.UUID, published: str | None) -> str:
    body: dict[str, Any] = {"form_id": "f-promote", "form_uid": str(form_uid), "title": "t", "sections": []}
    if published:
        body["published_version"] = published
    return json.dumps(body)


async def _insert_draft(store: PostgresFormStorage, form_uid: uuid.UUID, version: str) -> None:
    async with store._pool.acquire() as conn:
        await conn.execute(
            f"INSERT INTO {store._qualified(None)} (form_uid, form_id, version, schema_json) "
            "VALUES ($1, 'f-promote', $2, $3::text::jsonb)",
            form_uid,
            version,
            _schema(form_uid, None),
        )


async def test_promote_an_existing_draft_then_refuse_a_second_promote(storage: PostgresFormStorage) -> None:
    """The conflict path runs (no AmbiguousColumnError) and the immutability guard still holds."""
    form_uid = uuid.uuid4()
    await _insert_draft(storage, form_uid, "1.1")

    assert await storage.promote(form_uid, "1.1", _schema(form_uid, "1.1")) is True
    async with storage._pool.acquire() as conn:
        stored = await conn.fetchval(
            f"SELECT schema_json ->> 'published_version' FROM {storage._qualified(None)} "
            "WHERE form_uid = $1 AND version = '1.1'",
            form_uid,
        )
    assert stored == "1.1"

    # already published: the WHERE skips the update, RETURNING yields nothing
    assert await storage.promote(form_uid, "1.1", _schema(form_uid, "1.1")) is False


async def test_first_publish_without_a_row_inserts(storage: PostgresFormStorage) -> None:
    form_uid = uuid.uuid4()
    assert await storage.promote(form_uid, "1.0", _schema(form_uid, "1.0")) is True
