"""``form_data.data`` / ``.context`` must be jsonb OBJECTS under BOTH pool regimes.

Same defect and same shape as ``test_jsonb_object_storage.py``, one table
over: ``FormSubmissionStorage.store()`` passes JSON TEXT (``json.dumps``) as
a bare parameter, and a HOST-provided pool that registers a json/jsonb codec
(encoder=``json.dumps`` — navigator's shared pool does) re-encodes it,
storing a double-encoded jsonb STRING.

The 2026-07-30 pass fixed ``form_schemas``, ``rbac`` and the question bank
and missed this table. Measured 2026-08-14 against a live FieldSync pool:
both stored submissions had ``jsonb_typeof(data) = 'string'`` and
``get_submission`` then raised ``ValidationError: Input should be a valid
dictionary`` reading back its OWN rows — so unlike the sibling defect, this
one is not even papered over by a compensating reader. That is why the
round-trip assertion below belongs here: it fails on the unfixed writer.

Requires a disposable Postgres::

    SCRATCH_DSN="postgresql://postgres:postgres@localhost:15931/postgres" \\
        pytest tests/test_submission_jsonb_shape.py -v
"""

from __future__ import annotations

import json
import os
import uuid
from collections.abc import AsyncIterator
from typing import Any

import pytest

from parrot_formdesigner.services.submissions import (
    FormSubmission,
    FormSubmissionStorage,
)

_SCRATCH_DSN = os.getenv("SCRATCH_DSN")

pytestmark = [
    pytest.mark.skipif(
        not _SCRATCH_DSN,
        reason="SCRATCH_DSN not set (scratch Postgres required)",
    ),
]

SCHEMA = "pfd_submission_shape_test"


async def _codec_init(conn: Any) -> None:
    """Mirror navigator's shared-pool json/jsonb codec registration."""
    for name in ("json", "jsonb"):
        await conn.set_type_codec(
            name, encoder=json.dumps, decoder=json.loads, schema="pg_catalog"
        )


@pytest.fixture(params=["plain", "codec"])
async def pool(request: pytest.FixtureRequest) -> AsyncIterator[Any]:
    """One run per pool regime: parrot's own plain pool, and a pool with the
    json/jsonb codec a host application may register."""
    import asyncpg

    kwargs: dict[str, Any] = {"dsn": _SCRATCH_DSN, "min_size": 1, "max_size": 2}
    if request.param == "codec":
        kwargs["init"] = _codec_init
    created = await asyncpg.create_pool(**kwargs)
    async with created.acquire() as conn:
        await conn.execute(f'CREATE SCHEMA IF NOT EXISTS "{SCHEMA}"')
    try:
        yield created
    finally:
        async with created.acquire() as conn:
            await conn.execute(f'DROP SCHEMA IF EXISTS "{SCHEMA}" CASCADE')
        await created.close()


def _submission() -> FormSubmission:
    return FormSubmission(
        form_uid=uuid.uuid4(),
        form_id="shape-proof-form",
        form_version="1.0",
        data={"field_1": ["6453"], "field_2": "testing"},
        is_valid=True,
        context={"lat": 39.9178032, "lon": -75.0, "accuracy_m": 12.5},
    )


async def test_store_writes_jsonb_objects_never_strings(pool: Any) -> None:
    storage = FormSubmissionStorage(pool, schema=SCHEMA)
    await storage.initialize()
    submission = _submission()
    await storage.store(submission)

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            f"SELECT jsonb_typeof(data) AS data_kind, "
            f"jsonb_typeof(context) AS ctx_kind, "
            f"data->>'field_2' AS answer "
            f'FROM "{SCHEMA}".form_data WHERE submission_id = $1',
            submission.submission_id,
        )

    assert row is not None
    assert row["data_kind"] == "object", (
        "data stored as a jsonb STRING — the double-encoding defect is back "
        "for this pool regime"
    )
    assert row["ctx_kind"] == "object", "context stored as a jsonb STRING"
    # The SQL-level read the double-encoding breaks silently: on a string row
    # every ->> returns NULL, which is how a reporting query goes quietly empty.
    assert row["answer"] == "testing"


async def test_get_submission_reads_back_its_own_write(pool: Any) -> None:
    """The round-trip this module could not do at all.

    With the unfixed writer under a codec pool, `get_submission` raises
    `ValidationError` on `data`/`context` — the module's own reader rejecting
    the module's own row. Asserting the round-trip pins the pair together.
    """
    storage = FormSubmissionStorage(pool, schema=SCHEMA)
    await storage.initialize()
    submission = _submission()
    await storage.store(submission)

    loaded = await storage.get_submission(submission.submission_id)

    assert loaded is not None
    assert isinstance(loaded.data, dict)
    assert loaded.data == submission.data
    assert isinstance(loaded.context, dict)
    assert loaded.context == submission.context


async def test_a_submission_without_context_is_unaffected(pool: Any) -> None:
    """`context` is nullable — the cast must not turn NULL into 'null'."""
    storage = FormSubmissionStorage(pool, schema=SCHEMA)
    await storage.initialize()
    submission = _submission()
    submission.context = None
    await storage.store(submission)

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            f'SELECT context, jsonb_typeof(data) AS data_kind '
            f'FROM "{SCHEMA}".form_data WHERE submission_id = $1',
            submission.submission_id,
        )

    assert row is not None
    assert row["context"] is None, "a null context became a jsonb value"
    assert row["data_kind"] == "object"
