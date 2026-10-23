"""FEAT-731 — clear-on-store and references_blob against real Postgres (skips without SCRATCH_DSN)."""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator
from typing import Any

import pytest
from parrot_formdesigner.services.pending_uploads import PendingUpload, PendingUploadStore
from parrot_formdesigner.services.submissions import FormSubmission, FormSubmissionStorage

_SCRATCH_DSN = os.getenv("SCRATCH_DSN")
pytestmark = pytest.mark.skipif(not _SCRATCH_DSN, reason="SCRATCH_DSN not set (scratch Postgres required)")

SCHEMA = "pfd_pending_uploads_test"


@pytest.fixture
async def pool() -> AsyncIterator[Any]:
    import asyncpg

    created = await asyncpg.create_pool(dsn=_SCRATCH_DSN, min_size=1, max_size=4)
    async with created.acquire() as conn:
        await conn.execute(f'DROP SCHEMA IF EXISTS "{SCHEMA}" CASCADE')
        await conn.execute(f'CREATE SCHEMA "{SCHEMA}"')
    try:
        yield created
    finally:
        async with created.acquire() as conn:
            await conn.execute(f'DROP SCHEMA IF EXISTS "{SCHEMA}" CASCADE')
        await created.close()


@pytest.fixture
async def stores(pool: Any) -> tuple[FormSubmissionStorage, PendingUploadStore]:
    storage = FormSubmissionStorage(pool, schema=SCHEMA)
    pending = PendingUploadStore(pool, schema=SCHEMA)
    await storage.initialize()
    await pending.initialize()
    storage.attach_pending_uploads(pending)
    return storage, pending


def _entry(ref: str, form_uid: uuid.UUID) -> PendingUpload:
    return PendingUpload(
        blob_ref=ref, thumbnail_ref=None, form_uid=form_uid, field_uid=uuid.uuid4(), tenant=SCHEMA, public_form=False
    )


def _submission(form_uid: uuid.UUID, data: dict[str, Any], submission_id: str | None = None) -> FormSubmission:
    kwargs: dict[str, Any] = {}
    if submission_id:
        kwargs["submission_id"] = submission_id
    return FormSubmission(form_uid=form_uid, form_id="f", form_version="1", data=data, is_valid=True, **kwargs)


async def _pending_refs(pool: Any) -> set[str]:
    async with pool.acquire() as conn:
        rows = await conn.fetch(f'SELECT blob_ref FROM "{SCHEMA}".pending_uploads')
    return {r["blob_ref"] for r in rows}


async def test_store_clears_pending_in_same_transaction(pool: Any, stores: Any) -> None:
    storage, pending = stores
    form_uid = uuid.uuid4()
    await pending.record(_entry("s3://b/a", form_uid), tenant=SCHEMA)
    await pending.record(_entry("s3://b/b", form_uid), tenant=SCHEMA)
    await storage.store(_submission(form_uid, {"photo": {"blob_ref": "s3://b/a"}}))
    assert await _pending_refs(pool) == {"s3://b/b"}


async def test_store_rolls_back_clear_on_insert_failure(pool: Any, stores: Any) -> None:
    storage, pending = stores
    form_uid = uuid.uuid4()
    await pending.record(_entry("s3://b/a", form_uid), tenant=SCHEMA)
    await storage.store(_submission(form_uid, {"x": 1}, submission_id="dup"))
    with pytest.raises(Exception):  # noqa: B017 — unique violation
        await storage.store(_submission(form_uid, {"photo": {"blob_ref": "s3://b/a"}}, submission_id="dup"))
    assert await _pending_refs(pool) == {"s3://b/a"}


async def test_clear_failure_rolls_back_the_insert(pool: Any, stores: Any) -> None:
    """Both commit or neither: a clear that fails (not a missing table) aborts the INSERT too."""
    storage, pending = stores
    form_uid = uuid.uuid4()

    async def boom(*_a: Any, **_k: Any) -> int:
        raise RuntimeError("clear failed")

    pending.clear = boom  # type: ignore[method-assign]
    with pytest.raises(RuntimeError):
        await storage.store(_submission(form_uid, {"photo": {"blob_ref": "s3://b/a"}}, submission_id="s1"))
    async with pool.acquire() as conn:
        n = await conn.fetchval(f'SELECT count(*) FROM "{SCHEMA}".form_data WHERE submission_id = $1', "s1")
    assert n == 0


async def test_store_with_missing_pending_table(pool: Any) -> None:
    storage = FormSubmissionStorage(pool, schema=SCHEMA)
    await storage.initialize()
    storage.attach_pending_uploads(PendingUploadStore(pool, schema=SCHEMA, table_name="never_created"))
    form_uid = uuid.uuid4()
    await storage.store(_submission(form_uid, {"photo": {"blob_ref": "s3://b/a"}}, submission_id="ok1"))
    async with pool.acquire() as conn:
        n = await conn.fetchval(f'SELECT count(*) FROM "{SCHEMA}".form_data WHERE submission_id = $1', "ok1")
    assert n == 1


async def test_store_without_pending_unchanged(pool: Any) -> None:
    storage = FormSubmissionStorage(pool, schema=SCHEMA)
    await storage.initialize()
    pending = PendingUploadStore(pool, schema=SCHEMA)
    await pending.initialize()
    form_uid = uuid.uuid4()
    await pending.record(_entry("s3://b/a", form_uid), tenant=SCHEMA)
    await storage.store(_submission(form_uid, {"photo": {"blob_ref": "s3://b/a"}}))  # nothing attached
    assert await _pending_refs(pool) == {"s3://b/a"}


async def test_references_blob_jsonpath(pool: Any, stores: Any) -> None:
    storage, _ = stores
    form_uid, other = uuid.uuid4(), uuid.uuid4()
    data = {"grp": {"rows": [{"n": 1}, {"photos": [{"blob_ref": "s3://b/abc/1"}, {"blob_ref": "s3://b/abc/2"}]}]}}
    await storage.store(_submission(form_uid, data))
    assert await storage.references_blob(form_uid, "s3://b/abc/2", tenant=SCHEMA) is True
    assert await storage.references_blob(other, "s3://b/abc/2", tenant=SCHEMA) is False
    assert await storage.references_blob(form_uid, "s3://b/abc", tenant=SCHEMA) is False  # prefix of a ref
    assert await storage.references_blob(form_uid, "s3://b/abc/22", tenant=SCHEMA) is False
