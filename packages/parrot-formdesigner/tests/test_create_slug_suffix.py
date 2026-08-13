"""Create-from-template: colliding slugs suffix numerically, renames still raise.

The 2026-08-12 live failure: the quick-start templates deterministically
mint canonical slugs (``bug-report-form``), so the SECOND create from the
same template collided with the per-tenant unique constraint — and with a
cold registry cache (hydration gap) the friendly in-memory guard never
fired, so the collision surfaced as a raw database error swallowed into a
fake "Form created" success.

The fix, proven here BY EFFECT against a real Postgres:

- A brand-new form whose slug is taken gets ``-2``/``-3``/... — probing
  STORAGE, so a cold cache cannot hide the collision (every test below
  uses a FRESH registry against pre-persisted rows, exactly the cold
  boot).
- Re-registering/updating the SAME form_uid never suffixes.
- Renaming an EXISTING form onto another form's slug still raises
  ``FormAlreadyExistsError`` — silently renaming an explicit user choice
  would be worse than the error.

Requires a disposable Postgres::

    SCRATCH_DSN="postgresql://postgres:postgres@localhost:15931/postgres" \\
        pytest tests/test_create_slug_suffix.py -v
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from typing import Any

import pytest

from parrot_formdesigner.core.schema import FormSchema
from parrot_formdesigner.services.registry import (
    FormAlreadyExistsError,
    FormRegistry,
)
from parrot_formdesigner.services.storage import PostgresFormStorage

_SCRATCH_DSN = os.getenv("SCRATCH_DSN")

pytestmark = [
    pytest.mark.skipif(
        not _SCRATCH_DSN,
        reason="SCRATCH_DSN not set (scratch Postgres required)",
    ),
]

SCHEMA = "pfd_slug_suffix_test"
TENANT = "flexroc_suffix_test"


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


def _fresh_registry(storage: PostgresFormStorage) -> FormRegistry:
    """A COLD registry (empty slug index) — the post-boot reality under
    the hydration gap; the storage probe is what must catch collisions."""
    registry = FormRegistry(require_tenant=False, default_tenant=TENANT)
    registry.set_storage(storage)
    return registry


def _template_form(slug: str = "bug-report-form") -> FormSchema:
    return FormSchema(
        form_id=slug, title="Bug Report Form", sections=[], tenant=TENANT
    )


async def test_second_create_from_template_suffixes(
    storage: PostgresFormStorage,
) -> None:
    first = _template_form()
    await _fresh_registry(storage).register(first, persist=True)
    assert first.form_id == "bug-report-form"

    # Fresh registry = cold cache: only the storage probe can see `first`.
    second = _template_form()
    await _fresh_registry(storage).register(second, persist=True)
    assert second.form_id == "bug-report-form-2"

    third = _template_form()
    await _fresh_registry(storage).register(third, persist=True)
    assert third.form_id == "bug-report-form-3"

    # All three persisted as independent identities.
    listed = await storage.list_forms(tenant=TENANT)
    slugs = sorted(entry["form_id"] for entry in listed)
    assert slugs == ["bug-report-form", "bug-report-form-2", "bug-report-form-3"]


async def test_updating_the_same_form_never_suffixes(
    storage: PostgresFormStorage,
) -> None:
    form = _template_form(slug="visit-recap")
    registry = _fresh_registry(storage)
    await registry.register(form, persist=True)
    # Same uid, same slug, new save — an UPDATE, not a new identity.
    await registry.register(form, persist=True)
    assert form.form_id == "visit-recap"


async def test_rename_onto_a_taken_slug_still_raises(
    storage: PostgresFormStorage,
) -> None:
    registry = _fresh_registry(storage)
    owner = _template_form(slug="owner-form")
    victim = _template_form(slug="victim-form")
    await registry.register(owner, persist=True)
    await registry.register(victim, persist=True)

    victim.form_id = "owner-form"  # explicit rename onto a taken slug
    with pytest.raises(FormAlreadyExistsError):
        await registry.register(victim, persist=True)
