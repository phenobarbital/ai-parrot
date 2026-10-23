"""FEAT-730 — store_guarded atomicity against a real Postgres (skips without SCRATCH_DSN)."""
import asyncio
import os
import uuid
from collections.abc import AsyncIterator
from typing import Any

import pytest

from parrot_formdesigner.services.submissions import (
    DuplicateResponse,
    FormSubmission,
    FormSubmissionStorage,
    ResponseLimitReached,
)

_SCRATCH_DSN = os.getenv("SCRATCH_DSN")
pytestmark = pytest.mark.skipif(not _SCRATCH_DSN, reason="SCRATCH_DSN not set (scratch Postgres required)")

SCHEMA = "pfd_store_guarded_test"


@pytest.fixture
async def storage() -> AsyncIterator[FormSubmissionStorage]:
    import asyncpg

    pool = await asyncpg.create_pool(dsn=_SCRATCH_DSN, min_size=1, max_size=12)
    async with pool.acquire() as conn:
        await conn.execute(f'DROP SCHEMA IF EXISTS "{SCHEMA}" CASCADE')
        await conn.execute(f'CREATE SCHEMA "{SCHEMA}"')
    st = FormSubmissionStorage(pool, schema=SCHEMA)
    await st.initialize()
    try:
        yield st
    finally:
        async with pool.acquire() as conn:
            await conn.execute(f'DROP SCHEMA IF EXISTS "{SCHEMA}" CASCADE')
        await pool.close()


def _sub(form_uid: uuid.UUID, data: dict[str, Any] | None = None, **kw: Any) -> FormSubmission:
    return FormSubmission(
        form_uid=form_uid, form_id="pub", form_version="1.0", data=data or {}, is_valid=True, **kw
    )


async def test_store_guarded_cap_concurrent(storage):
    form_uid = uuid.uuid4()
    results = await asyncio.gather(
        *[storage.store_guarded(_sub(form_uid, {"n": i}), max_responses=5) for i in range(20)],
        return_exceptions=True,
    )
    assert sum(isinstance(r, str) for r in results) == 5
    assert sum(isinstance(r, ResponseLimitReached) for r in results) == 15
    assert await storage.count_responses(form_uid) == 5


async def test_store_guarded_unique_concurrent(storage):
    form_uid = uuid.uuid4()
    values = ["A@x.com ", "a@X.com"]
    results = await asyncio.gather(
        *[
            storage.store_guarded(_sub(form_uid, {"email": v}), unique_key_field="email", unique_value=v)
            for v in values
        ],
        return_exceptions=True,
    )
    assert sum(isinstance(r, str) for r in results) == 1
    dups = [r for r in results if isinstance(r, DuplicateResponse)]
    assert len(dups) == 1 and dups[0].field_id == "email"
    assert await storage.count_responses(form_uid) == 1


async def test_store_guarded_unique_non_string_and_blank(storage):
    form_uid = uuid.uuid4()
    await storage.store_guarded(_sub(form_uid, {"age": 5}), unique_key_field="age", unique_value=5)
    with pytest.raises(DuplicateResponse):
        await storage.store_guarded(_sub(form_uid, {"age": 5}), unique_key_field="age", unique_value=5)
    # a blank/absent value is never checked
    await storage.store_guarded(_sub(form_uid, {}), unique_key_field="age", unique_value=None)
    await storage.store_guarded(_sub(form_uid, {}), unique_key_field="age", unique_value=None)
    # another form is unaffected
    await storage.store_guarded(_sub(uuid.uuid4(), {"age": 5}), unique_key_field="age", unique_value=5)


async def test_count_responses_roots_only(storage):
    form_uid = uuid.uuid4()
    root = _sub(form_uid, {"a": 1})
    await storage.store(root)
    await storage.store(_sub(form_uid, {"a": 2}, root_submission_id=root.submission_id, revision=2))
    assert await storage.count_responses(form_uid) == 1
    # revisions never consume the cap: 1 root + 1 revision still leaves room under a cap of 2
    await storage.store_guarded(_sub(form_uid, {"a": 3}), max_responses=2)
    with pytest.raises(ResponseLimitReached):
        await storage.store_guarded(_sub(form_uid, {"a": 4}), max_responses=2)
