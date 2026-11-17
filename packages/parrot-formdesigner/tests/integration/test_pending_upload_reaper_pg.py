"""FEAT-731 — reaper against real Postgres: TTL SQL, safety check, SKIP LOCKED (skips without SCRATCH_DSN)."""

from __future__ import annotations

import asyncio
import os
import uuid
from collections import Counter
from collections.abc import AsyncIterator
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from parrot_formdesigner.services.pending_uploads import PendingUpload, PendingUploadReaper, PendingUploadStore
from parrot_formdesigner.services.submissions import FormSubmission, FormSubmissionStorage

_SCRATCH_DSN = os.getenv("SCRATCH_DSN")
pytestmark = pytest.mark.skipif(not _SCRATCH_DSN, reason="SCRATCH_DSN not set (scratch Postgres required)")

SCHEMA = "pfd_reaper_test"


@pytest.fixture
async def pool() -> AsyncIterator[Any]:
    import asyncpg

    created = await asyncpg.create_pool(dsn=_SCRATCH_DSN, min_size=1, max_size=12)
    async with created.acquire() as conn:
        await conn.execute(f'DROP SCHEMA IF EXISTS "{SCHEMA}" CASCADE')
        await conn.execute(f'CREATE SCHEMA "{SCHEMA}"')
    try:
        yield created
    finally:
        async with created.acquire() as conn:
            await conn.execute(f'DROP SCHEMA IF EXISTS "{SCHEMA}" CASCADE')
        await created.close()


class RecordingBlobs:
    def __init__(self, delay: float = 0.0) -> None:
        self.calls: Counter[str] = Counter()
        self.delay = delay

    async def delete(self, ref: str, *, strict: bool = False) -> None:
        await asyncio.sleep(self.delay)
        self.calls[ref] += 1


async def _setup(pool: Any) -> tuple[FormSubmissionStorage, PendingUploadStore]:
    subs = FormSubmissionStorage(pool, schema=SCHEMA)
    pending = PendingUploadStore(pool, schema=SCHEMA)
    await subs.initialize()
    await pending.initialize()
    return subs, pending


async def _put(
    pool: Any, ref: str, *, age: timedelta, public: bool, form_uid: uuid.UUID | None = None, thumb: str | None = None
) -> None:
    async with pool.acquire() as conn:
        await conn.execute(
            f'INSERT INTO "{SCHEMA}".pending_uploads (blob_ref, thumbnail_ref, form_uid, field_uid, tenant, '
            "public_form, uploaded_at) VALUES ($1,$2,$3,$4,$5,$6,$7)",
            ref,
            thumb,
            form_uid or uuid.uuid4(),
            uuid.uuid4(),
            SCHEMA,
            public,
            datetime.now(timezone.utc) - age,
        )


async def _refs(pool: Any) -> set[str]:
    async with pool.acquire() as conn:
        return {r["blob_ref"] for r in await conn.fetch(f'SELECT blob_ref FROM "{SCHEMA}".pending_uploads')}


async def test_reaper_real_sql_ttls_and_safety_check(pool: Any) -> None:
    subs, pending = await _setup(pool)
    h = timedelta(hours=1)
    await _put(pool, "pub-49h", age=49 * h, public=True, thumb="pub-49h-t")
    await _put(pool, "pub-47h", age=47 * h, public=True)
    await _put(pool, "priv-6d", age=6 * 24 * h, public=False)
    await _put(pool, "priv-8d", age=8 * 24 * h, public=False)
    ref_form = uuid.uuid4()
    await _put(pool, "ref-9d", age=9 * 24 * h, public=False, form_uid=ref_form)
    await subs.store(
        FormSubmission(
            form_uid=ref_form, form_id="f", form_version="1", is_valid=True, data={"g": [{"p": {"blob_ref": "ref-9d"}}]}
        )
    )
    blobs = RecordingBlobs()

    result = await PendingUploadReaper(pending, blobs, subs).reap_once(tenant=SCHEMA)

    assert (result.deleted, result.failed, result.still_referenced) == (2, 0, 1)
    assert set(blobs.calls) == {"pub-49h", "pub-49h-t", "priv-8d"}
    assert await _refs(pool) == {"pub-47h", "priv-6d"}


async def test_reaper_skip_locked_concurrent(pool: Any) -> None:
    subs, pending = await _setup(pool)
    for i in range(20):
        await _put(pool, f"old-{i}", age=timedelta(days=30), public=False)
    blobs = RecordingBlobs(delay=0.05)
    reaper = PendingUploadReaper(pending, blobs, subs)

    r1, r2 = await asyncio.gather(reaper.reap_once(tenant=SCHEMA, batch=10), reaper.reap_once(tenant=SCHEMA, batch=10))

    assert r1.deleted + r2.deleted == 20
    assert r1.deleted == 10 and r2.deleted == 10
    assert set(blobs.calls) == {f"old-{i}" for i in range(20)}
    assert all(n == 1 for n in blobs.calls.values()), blobs.calls  # each row processed once
    assert await _refs(pool) == set()


async def test_failed_delete_keeps_row(pool: Any) -> None:
    subs, pending = await _setup(pool)
    await _put(pool, "boom", age=timedelta(days=30), public=False)

    class Failing(RecordingBlobs):
        async def delete(self, ref: str, *, strict: bool = False) -> None:
            raise RuntimeError("500")

    result = await PendingUploadReaper(pending, Failing(), subs).reap_once(tenant=SCHEMA)
    assert (result.deleted, result.failed) == (0, 1)
    assert await _refs(pool) == {"boom"}


async def test_record_upsert_refreshes_uploaded_at(pool: Any) -> None:
    _, pending = await _setup(pool)
    form_uid, field_uid = uuid.uuid4(), uuid.uuid4()
    entry = PendingUpload(
        blob_ref="same", thumbnail_ref=None, form_uid=form_uid, field_uid=field_uid, tenant=SCHEMA, public_form=True
    )
    await pending.record(entry, tenant=SCHEMA)
    async with pool.acquire() as conn:
        await conn.execute(f"UPDATE \"{SCHEMA}\".pending_uploads SET uploaded_at = now() - interval '3 days'")
    await pending.record(entry.model_copy(update={"thumbnail_ref": "t"}), tenant=SCHEMA)
    async with pool.acquire() as conn:
        rows = await conn.fetch(f'SELECT thumbnail_ref, uploaded_at FROM "{SCHEMA}".pending_uploads')
    assert len(rows) == 1 and rows[0]["thumbnail_ref"] == "t"
    assert datetime.now(timezone.utc) - rows[0]["uploaded_at"] < timedelta(minutes=1)
