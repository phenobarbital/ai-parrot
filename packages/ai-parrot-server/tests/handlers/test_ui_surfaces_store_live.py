"""Live-Postgres tests for `PgUISurfaceStore` tenant/group visibility (FEAT-535).

Gated on ``NAVIGATOR_PG_DSN`` (skips cleanly when unset — no live database
available). Proves what the in-memory fake in ``test_ui_surfaces_store.py``
cannot: that ``allowed_groups ?| $3::text[]`` and the ``::jsonb`` casts
actually execute against a real Postgres server.

The DDL in ``handlers/models/ui_surfaces.py`` hard-codes the ``navigator``
schema, so a throwaway schema name is not possible here (spec §3 Module 1).
Instead:

1. Create the PRE-feature ``navigator.ui_surfaces`` shape with a literal
   copy of the OLD ``CREATE TABLE IF NOT EXISTS`` text (13 columns, no
   ``tenant``/``visibility``/``allowed_groups``) — a no-op if the table
   already carries the new shape from a prior run.
2. Run ``ensure_schema()`` and assert the three columns + the
   ``(tenant, visibility)`` index exist via ``information_schema``.
3. Exercise ``list_visible``/``update_visibility`` against real rows.
4. Clean up only the rows this test inserted — never ``DROP`` the table.
"""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from asyncdb import AsyncDB
from parrot.handlers.models import ui_surfaces as m

DSN = os.getenv("NAVIGATOR_PG_DSN", "")
pytestmark = [pytest.mark.asyncio, pytest.mark.skipif(not DSN, reason="NAVIGATOR_PG_DSN not set (fs-scratch-pg)")]

# The OLD (pre-FEAT-535) `CREATE TABLE IF NOT EXISTS` text — a literal copy
# of what `_DDL_STATEMENTS` looked like before this feature added the three
# columns. `IF NOT EXISTS` makes this a no-op against a table that already
# has the new shape (e.g. a second run of this suite against the same
# scratch database).
_OLD_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS navigator.ui_surfaces (
    surface_id UUID PRIMARY KEY,
    kind VARCHAR(32) NOT NULL,
    title TEXT NOT NULL,
    envelope JSONB NOT NULL,
    catalog_id VARCHAR,
    agent_id VARCHAR NOT NULL,
    user_id VARCHAR NOT NULL,
    session_id VARCHAR,
    recipe_name VARCHAR,
    recipe_owner VARCHAR,
    recipe_params JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
)
"""


def _scope(user_id=None, tenant=None, groups=(), is_superuser=False):
    """Duck-typed ``SurfaceScope`` stand-in (spec §3 Module 1 — this module
    never imports the handler-package type)."""
    return SimpleNamespace(user_id=user_id, tenant=tenant, groups=groups, is_superuser=is_superuser)


@pytest.fixture
async def raw_conn():
    """A raw connection for setup/introspection/cleanup outside the store."""
    db = AsyncDB("pg", dsn=DSN)
    async with await db.connection() as conn:
        yield conn


@pytest.fixture
def live_store():
    return m.PgUISurfaceStore(dsn=DSN)


@pytest.fixture
def _run_marker() -> str:
    """A unique tag folded into ``user_id`` so cleanup only ever touches rows
    this test run created, never any other data in the scratch database."""
    return uuid.uuid4().hex[:8]


async def test_ensure_schema_adds_columns_to_pre_feature_table(raw_conn, live_store):
    # 1. Simulate a pre-feature database (no-op if already migrated).
    await raw_conn.execute("CREATE SCHEMA IF NOT EXISTS navigator")
    await raw_conn.execute(_OLD_CREATE_TABLE_SQL)

    # 2. Run the live migration this feature adds.
    await live_store.ensure_schema()

    columns = await raw_conn.fetch_all(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema = 'navigator' AND table_name = 'ui_surfaces'"
    )
    column_names = {dict(r)["column_name"] for r in columns}
    assert {"tenant", "visibility", "allowed_groups"} <= column_names

    indexes = await raw_conn.fetch_all(
        "SELECT indexname FROM pg_indexes WHERE schemaname = 'navigator' AND tablename = 'ui_surfaces'"
    )
    index_names = {dict(r)["indexname"] for r in indexes}
    assert "ix_ui_surfaces_tenant_visibility" in index_names

    # 3. Second run is a no-op (idempotent `IF NOT EXISTS` everywhere).
    await live_store.ensure_schema()


def _make_record(**overrides) -> m.UISurfaceRecord:
    now = datetime.now(UTC)
    defaults = {
        "surface_id": str(uuid.uuid4()),
        "kind": m.UISurfaceKind.dashboard,
        "title": "FEAT-535 live test surface",
        "envelope": {"components": []},
        "catalog_id": None,
        "agent_id": "agent-live-test",
        "user_id": "owner-live-test",
        "session_id": None,
        "recipe_name": None,
        "recipe_owner": None,
        "recipe_params": {},
        "created_at": now,
        "updated_at": now,
    }
    defaults.update(overrides)
    return m.UISurfaceRecord(**defaults)


async def test_list_visible_matrix(live_store, raw_conn, _run_marker):
    owner = f"owner-a-{_run_marker}"
    tenant = f"tenant-epson-{_run_marker}"
    other_tenant = f"tenant-other-{_run_marker}"
    group = f"epson_fieldsync_manager-{_run_marker}"

    owned = _make_record(user_id=owner, tenant=None, visibility=m.SurfaceVisibility.private)
    tenant_visible_same = _make_record(
        user_id=f"owner-b-{_run_marker}", tenant=tenant, visibility=m.SurfaceVisibility.tenant
    )
    tenant_visible_other = _make_record(
        user_id=f"owner-c-{_run_marker}", tenant=other_tenant, visibility=m.SurfaceVisibility.tenant
    )
    groups_hit = _make_record(
        user_id=f"owner-d-{_run_marker}",
        tenant=tenant,
        visibility=m.SurfaceVisibility.groups,
        allowed_groups=[group],
    )
    groups_miss = _make_record(
        user_id=f"owner-e-{_run_marker}",
        tenant=tenant,
        visibility=m.SurfaceVisibility.groups,
        allowed_groups=[f"other-group-{_run_marker}"],
    )
    private_same_tenant = _make_record(
        user_id=f"owner-f-{_run_marker}", tenant=tenant, visibility=m.SurfaceVisibility.private
    )
    row_without_tenant = _make_record(
        user_id=f"owner-g-{_run_marker}", tenant=None, visibility=m.SurfaceVisibility.tenant
    )
    all_records = [
        owned,
        tenant_visible_same,
        tenant_visible_other,
        groups_hit,
        groups_miss,
        private_same_tenant,
        row_without_tenant,
    ]
    try:
        for r in all_records:
            await live_store.save(r)

        caller_scope = _scope(user_id=owner, tenant=tenant, groups=[group])
        visible_ids = {r.surface_id for r in await live_store.list_visible(caller_scope)}
        assert owned.surface_id in visible_ids
        assert tenant_visible_same.surface_id in visible_ids
        assert tenant_visible_other.surface_id not in visible_ids
        assert groups_hit.surface_id in visible_ids
        assert groups_miss.surface_id not in visible_ids
        assert private_same_tenant.surface_id not in visible_ids
        assert row_without_tenant.surface_id not in visible_ids

        superuser_scope = _scope(user_id=f"superuser-{_run_marker}", tenant=tenant, groups=[], is_superuser=True)
        superuser_visible = {r.surface_id for r in await live_store.list_visible(superuser_scope)}
        assert tenant_visible_same.surface_id in superuser_visible
        assert groups_hit.surface_id in superuser_visible
        assert groups_miss.surface_id in superuser_visible
        assert private_same_tenant.surface_id in superuser_visible
        assert tenant_visible_other.surface_id not in superuser_visible
        assert row_without_tenant.surface_id not in superuser_visible

        no_tenant_scope = _scope(user_id=owner, tenant=None, groups=[group])
        no_tenant_visible = {r.surface_id for r in await live_store.list_visible(no_tenant_scope)}
        assert no_tenant_visible == {owned.surface_id}
    finally:
        for r in all_records:
            await live_store.delete(r.surface_id, r.user_id)


async def test_update_visibility_owner_only_live(live_store, _run_marker):
    owner = f"owner-a-{_run_marker}"
    record = _make_record(user_id=owner, tenant=f"tenant-{_run_marker}", visibility=m.SurfaceVisibility.private)
    try:
        await live_store.save(record)

        non_owner_result = await live_store.update_visibility(
            record.surface_id, f"owner-b-{_run_marker}", m.SurfaceVisibility.tenant, []
        )
        assert non_owner_result is False
        unchanged = await live_store.get(record.surface_id)
        assert unchanged.visibility is m.SurfaceVisibility.private

        owner_result = await live_store.update_visibility(
            record.surface_id, owner, m.SurfaceVisibility.groups, [f"group-{_run_marker}"]
        )
        assert owner_result is True
        updated = await live_store.get(record.surface_id)
        assert updated.visibility is m.SurfaceVisibility.groups
        assert updated.allowed_groups == [f"group-{_run_marker}"]
    finally:
        await live_store.delete(record.surface_id, owner)
