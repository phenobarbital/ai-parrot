"""Registry read-through: a cache miss falls through to storage (2026-08-13).

The live failure this closes: ``FormRegistry.get``/``get_by_slug`` were pure
in-memory lookups, and boot-time hydration does not cover per-tenant-schema
forms — so after any restart, every uid-gated handler (DELETE/PUT/validate/
render/clone) answered 404 for a form that demonstrably existed in storage
(observed on a day-old ``flexroc`` form; the row was intact, only the cache
was cold). Creating a form masked the gap until the next restart, because
the create path registers in memory as a side effect.

Proven BY EFFECT against a real Postgres, mirroring
``test_create_slug_suffix.py``'s cold-boot discipline: every test uses a
FRESH registry against pre-persisted rows.

Requires a disposable Postgres::

    SCRATCH_DSN="postgresql://postgres:postgres@localhost:15931/postgres" \\
        pytest tests/test_registry_read_through.py -v
"""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator

import pytest

from parrot_formdesigner.core.schema import FormSchema
from parrot_formdesigner.services.registry import FormRegistry
from parrot_formdesigner.services.storage import PostgresFormStorage

_SCRATCH_DSN = os.getenv("SCRATCH_DSN")

pytestmark = [
    pytest.mark.skipif(
        not _SCRATCH_DSN,
        reason="SCRATCH_DSN not set (scratch Postgres required)",
    ),
]

SCHEMA = "pfd_read_through_test"
TENANT = "flexroc_rt_test"


@pytest.fixture()
async def storage() -> AsyncIterator[PostgresFormStorage]:
    import asyncpg

    pool = await asyncpg.create_pool(dsn=_SCRATCH_DSN, min_size=1, max_size=2)
    async with pool.acquire() as conn:
        await conn.execute(f'CREATE SCHEMA IF NOT EXISTS "{SCHEMA}"')
        await conn.execute(f'CREATE SCHEMA IF NOT EXISTS "{TENANT}"')
    built = PostgresFormStorage(pool=pool, schema=SCHEMA)
    await built.initialize(tenant=TENANT)
    try:
        yield built
    finally:
        async with pool.acquire() as conn:
            await conn.execute(f'DROP SCHEMA IF EXISTS "{SCHEMA}" CASCADE')
            await conn.execute(f'DROP SCHEMA IF EXISTS "{TENANT}" CASCADE')
        await pool.close()


def _fresh_registry(storage: PostgresFormStorage | None) -> FormRegistry:
    """A COLD registry (empty cache) — the post-restart reality."""
    registry = FormRegistry(require_tenant=False, default_tenant=TENANT)
    if storage is not None:
        registry.set_storage(storage)
    return registry


def _form(slug: str) -> FormSchema:
    return FormSchema(form_id=slug, title=slug, sections=[], tenant=TENANT)


async def _persist(storage: PostgresFormStorage, slug: str) -> FormSchema:
    """Persist through one registry, so the row is exactly what a real
    create writes — then every test reads it through a DIFFERENT, cold one."""
    form = _form(slug)
    await _fresh_registry(storage).register(form, persist=True)
    return form


async def test_cold_get_reads_through_and_caches(
    storage: PostgresFormStorage,
) -> None:
    persisted = await _persist(storage, "contact-form")

    cold = _fresh_registry(storage)
    loaded = await cold.get(persisted.form_uid, tenant=TENANT)
    assert loaded is not None
    assert loaded.form_id == "contact-form"

    # Admitted into the cache: a second lookup is served in-memory —
    # proven by detaching storage and asking again.
    cold.set_storage(None)
    cached = await cold.get(persisted.form_uid, tenant=TENANT)
    assert cached is not None
    assert cached.form_uid == persisted.form_uid


async def test_cold_get_by_slug_reads_through(
    storage: PostgresFormStorage,
) -> None:
    persisted = await _persist(storage, "visit-recap")

    cold = _fresh_registry(storage)
    loaded = await cold.get_by_slug("visit-recap", tenant=TENANT)
    assert loaded is not None
    assert loaded.form_uid == persisted.form_uid


async def test_read_through_respects_tenant_isolation(
    storage: PostgresFormStorage,
) -> None:
    """A form persisted under TENANT must NOT resolve under another tenant
    — read-through widens the SOURCE, never the isolation contract."""
    persisted = await _persist(storage, "isolated-form")

    cold = _fresh_registry(storage)
    assert await cold.get(persisted.form_uid, tenant="some_other_tenant") is None


async def test_miss_everywhere_is_none(storage: PostgresFormStorage) -> None:
    cold = _fresh_registry(storage)
    assert await cold.get(uuid.uuid4(), tenant=TENANT) is None
    assert await cold.get_by_slug("never-created", tenant=TENANT) is None


async def test_no_storage_stays_cache_only() -> None:
    """Without a backend the pre-read-through behaviour survives
    byte-identical: pure in-memory answer, no error."""
    cold = _fresh_registry(None)
    assert await cold.get(uuid.uuid4(), tenant=TENANT) is None


async def test_storage_fault_degrades_to_none() -> None:
    """A lookup NEVER raises on a storage fault — callers already treat
    None as not-found; a flaky pool must not turn reads into 500s."""

    class _ExplodingStorage:
        async def load(self, *a, **kw):  # noqa: ANN001, ANN003
            raise RuntimeError("pool is down")

        async def load_by_slug(self, *a, **kw):  # noqa: ANN001, ANN003
            raise RuntimeError("pool is down")

    registry = FormRegistry(require_tenant=False, default_tenant=TENANT)
    registry.set_storage(_ExplodingStorage())
    assert await registry.get(uuid.uuid4(), tenant=TENANT) is None
    assert await registry.get_by_slug("whatever", tenant=TENANT) is None


async def test_unregister_after_read_through(
    storage: PostgresFormStorage,
) -> None:
    """The DELETE flow's registry half on a cold cache: get() admits the
    form, unregister() then finds it — the exact gate that 404'd live."""
    persisted = await _persist(storage, "deletable-form")

    cold = _fresh_registry(storage)
    assert await cold.get(persisted.form_uid, tenant=TENANT) is not None
    await cold.unregister(persisted.form_uid, tenant=TENANT)
    # Gone from the cache; storage row untouched by unregister (the
    # handler deletes storage separately).
    cold.set_storage(None)
    assert await cold.get(persisted.form_uid, tenant=TENANT) is None
