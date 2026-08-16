"""schema_json must be stored as a jsonb OBJECT under BOTH pool regimes.

The 2026-07-30 defect, pinned at the layer that can see it: ``save()``
passes JSON TEXT as a ``::jsonb``-typed parameter, and a HOST-provided
pool that registers a json/jsonb type codec (encoder=json.dumps —
navigator's shared pool does) re-encodes that text, storing a
double-encoded jsonb STRING. Every Python reader compensates
(``json.loads`` if ``str``), so round-trip tests stay green — what breaks
is SQL: ``->>'title'`` returns NULL and ``jsonb_typeof`` says
``'string'``. These tests therefore assert the STORED SHAPE directly,
once per pool regime, so a regression on either side cannot hide behind
the compensating readers.

Requires a disposable Postgres::

    SCRATCH_DSN="postgresql://postgres:postgres@localhost:15931/postgres" \\
        pytest tests/test_jsonb_object_storage.py -v
"""

from __future__ import annotations

import json
import os
from collections.abc import AsyncIterator
from typing import Any

import pytest

from parrot_formdesigner.core.schema import FormSchema
from parrot_formdesigner.services.storage import PostgresFormStorage

_SCRATCH_DSN = os.getenv("SCRATCH_DSN")

pytestmark = [
    pytest.mark.skipif(
        not _SCRATCH_DSN,
        reason="SCRATCH_DSN not set (scratch Postgres required)",
    ),
]

SCHEMA = "pfd_jsonb_shape_test"


async def _codec_init(conn: Any) -> None:
    """Mirror navigator's shared-pool json/jsonb codec registration."""
    for name in ("json", "jsonb"):
        await conn.set_type_codec(
            name, encoder=json.dumps, decoder=json.loads, schema="pg_catalog"
        )


@pytest.fixture(params=["plain", "codec"])
async def pool(request: pytest.FixtureRequest) -> AsyncIterator[Any]:
    """One run per pool regime: parrot's own plain pool, and a pool with
    the json/jsonb codec a host application may register."""
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


async def test_save_stores_a_jsonb_object_never_a_string(pool: Any) -> None:
    storage = PostgresFormStorage(pool=pool, schema=SCHEMA)
    await storage.initialize()

    form = FormSchema(
        form_id="shape-proof",
        title="Shape Proof",
        sections=[],
        tenant=None,
    )
    await storage.save(form)

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            f'SELECT jsonb_typeof(schema_json) AS kind, '
            f"schema_json->>'title' AS title "
            f'FROM "{SCHEMA}".form_schemas WHERE form_uid = $1',
            form.form_uid,
        )
    assert row is not None
    assert row["kind"] == "object", (
        "schema_json stored as a jsonb STRING — the double-encoding "
        "defect is back for this pool regime"
    )
    # The SQL-level read the double-encoding used to break silently.
    assert row["title"] == "Shape Proof"


async def test_loader_still_reads_both_shapes(
    pool: Any, request: pytest.FixtureRequest
) -> None:
    """The compensating reader keeps accepting legacy string rows —
    fixing the writer must not strand data written before the fix.

    Codec-pool regime ONLY, because that is the only regime where legacy
    string rows exist: they were written by codec pools re-encoding the
    old ``::jsonb`` parameter, and those installations read through the
    same codec pool (which decodes one level, leaving the reader's
    ``json.loads``-if-str to unwrap the second). A plain pool never
    produced string rows — the old cast stored objects correctly there —
    so the plain+legacy combination exists in no deployment.
    """
    if "plain" in request.node.callspec.id:
        pytest.skip("legacy string rows only ever existed under codec pools")
    storage = PostgresFormStorage(pool=pool, schema=SCHEMA)
    await storage.initialize()

    form = FormSchema(
        form_id="legacy-string-row",
        title="Legacy Row",
        sections=[],
        tenant=None,
    )
    # Simulate a pre-fix row: a jsonb STRING containing the JSON text.
    async with pool.acquire() as conn:
        await conn.execute(
            f'INSERT INTO "{SCHEMA}".form_schemas '
            f"(form_uid, form_id, version, schema_json, tenant) "
            f"VALUES ($1, $2, '1.0', to_jsonb($3::text), NULL)",
            form.form_uid,
            form.form_id,
            form.model_dump_json(),
        )

    loaded = await storage.load(form.form_uid)
    assert loaded is not None
    assert loaded.form_id == "legacy-string-row"
