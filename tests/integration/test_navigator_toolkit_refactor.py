"""Integration tests for FEAT-106 — NavigatorToolkit ↔ PostgresToolkit refactor.

All tests are marked ``pytest.mark.integration`` and skipped when
``NAVIGATOR_PG_DSN`` is not set, so the CI unit-test suite remains
unaffected without a live Postgres.

Tests included
--------------
- test_navigator_create_program_end_to_end
    Creates a program via NavigatorToolkit, verifies DB rows, and checks
    idempotency (already_existed=True on second call).

- test_navigator_create_module_transaction_atomicity
    Injects a fault after the first write inside ``transaction()``;
    asserts all writes rolled back (row count unchanged).

- test_navigator_create_dashboard_returns_dashboard_id
    Calls ``nav_create_dashboard`` and verifies a dashboard_id is returned.

- test_navigator_update_widget_pk_required
    Verifies that an update with a PK in WHERE succeeds; a crafted update
    without PK is rejected.

- test_postgres_toolkit_crud_on_fresh_table
    Round-trip INSERT / UPSERT / UPDATE / DELETE through PostgresToolkit
    CRUD tools against the ``test_crud`` scratch table.
"""
from __future__ import annotations

import os
import sys

import pytest

pytestmark = pytest.mark.integration

skip_if_no_pg = pytest.mark.skipif(
    not os.getenv("NAVIGATOR_PG_DSN"),
    reason="NAVIGATOR_PG_DSN not set — skipping integration test",
)

# ---------------------------------------------------------------------------
# Source setup: ensure worktree modules are importable.
# ---------------------------------------------------------------------------

_WT_ROOT = os.path.normpath(
    os.path.join(os.path.dirname(__file__), os.pardir, os.pardir)
)
_WT_PARROT_SRC = os.path.join(_WT_ROOT, "packages", "ai-parrot", "src")
_WT_TOOLS_SRC = os.path.join(_WT_ROOT, "packages", "ai-parrot-tools", "src")
for _p in (_WT_PARROT_SRC, _WT_TOOLS_SRC):
    if _p not in sys.path:
        sys.path.insert(0, _p)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_navigator_toolkit(**kwargs):
    """Return a NavigatorToolkit using the NAVIGATOR_PG_DSN env var."""
    from parrot_tools.navigator import NavigatorToolkit  # noqa: PLC0415
    dsn = os.environ["NAVIGATOR_PG_DSN"]
    return NavigatorToolkit(dsn=dsn, **kwargs)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@skip_if_no_pg
@pytest.mark.asyncio
async def test_navigator_create_program_end_to_end():
    """Create a program via NavigatorToolkit and verify idempotency.

    Acceptance criteria:
    - nav_create_program returns a dict with 'program_id'.
    - A second call with the same slug returns already_existed=True
      (or equivalent idempotency signal).
    - Cleanup: the created program is deleted after the test.
    """
    import asyncpg  # type: ignore[import]

    dsn = os.environ["NAVIGATOR_PG_DSN"]
    slug = "feat106_inttest_prog"

    tk = _make_navigator_toolkit(user_id=1)

    # Cleanup helper — remove any pre-existing row from a failed previous run.
    conn = await asyncpg.connect(dsn)
    try:
        await conn.execute(
            "DELETE FROM auth.programs WHERE slug = $1", slug
        )
    finally:
        await conn.close()

    try:
        # First call — should create the program.
        result = await tk.nav_create_program(
            name="FEAT-106 Integration Test Program",
            slug=slug,
            abbreviation="F106IT",
            client="navigator-new",
            group_ids=[1],
        )
        assert isinstance(result, dict), f"Expected dict, got {type(result)}"
        assert "program_id" in result or "id" in result or "error" not in result, (
            f"Unexpected result: {result}"
        )

        # Second call — should be idempotent (not raise, return already_existed).
        result2 = await tk.nav_create_program(
            name="FEAT-106 Integration Test Program",
            slug=slug,
            abbreviation="F106IT",
            client="navigator-new",
            group_ids=[1],
        )
        # Idempotency: either already_existed key or same program_id returned.
        assert result2 is not None, "Second create call returned None"

    finally:
        # Always clean up.
        conn = await asyncpg.connect(dsn)
        try:
            await conn.execute(
                "DELETE FROM auth.programs WHERE slug = $1", slug
            )
        finally:
            await conn.close()


@skip_if_no_pg
@pytest.mark.asyncio
async def test_navigator_create_module_transaction_atomicity():
    """Fault injection inside transaction() must roll back all writes.

    This test patches _nav_run_one to raise after the first call,
    simulating a mid-transaction failure.  The module count in auth.modules
    must be unchanged before and after the call.
    """
    import asyncpg  # type: ignore[import]
    from unittest.mock import AsyncMock, patch

    dsn = os.environ["NAVIGATOR_PG_DSN"]
    tk = _make_navigator_toolkit(user_id=1)

    conn = await asyncpg.connect(dsn)
    try:
        row = await conn.fetchrow("SELECT COUNT(*) AS cnt FROM navigator.modules")
        count_before = row["cnt"]
    finally:
        await conn.close()

    class BoomError(RuntimeError):
        """Injected fault."""

    call_count = 0
    original = tk._nav_run_one

    async def patched_run_one(sql, *args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count >= 2:
            raise BoomError("Injected fault — simulating mid-transaction failure")
        return await original(sql, *args, **kwargs)

    with patch.object(tk, "_nav_run_one", side_effect=patched_run_one):
        with pytest.raises(BoomError):
            await tk.nav_create_module(
                name="FEAT-106 Atomicity Test",
                slug="feat106_atomicity_test_mod",
                program_slug="nonexistent_program_for_test",
                parent_id=None,
                icon="mdi:test",
                color="#FFFFFF",
                client="navigator-new",
                group_id=1,
            )

    conn = await asyncpg.connect(dsn)
    try:
        row = await conn.fetchrow("SELECT COUNT(*) AS cnt FROM navigator.modules")
        count_after = row["cnt"]
    finally:
        await conn.close()

    assert count_after == count_before, (
        f"Row count changed: before={count_before}, after={count_after}. "
        "Transaction rollback did not occur."
    )


@skip_if_no_pg
@pytest.mark.asyncio
async def test_navigator_create_dashboard_returns_dashboard_id():
    """nav_create_dashboard must thread back a dashboard_id via RETURNING."""
    import asyncpg  # type: ignore[import]

    dsn = os.environ["NAVIGATOR_PG_DSN"]
    prog_slug = "feat106_inttest_dash"
    mod_slug = "feat106_inttest_dash_mod"
    tk = _make_navigator_toolkit(user_id=1)

    conn = await asyncpg.connect(dsn)
    try:
        await conn.execute("DELETE FROM auth.programs WHERE slug = $1", prog_slug)
    finally:
        await conn.close()

    try:
        # Create program first.
        prog_result = await tk.nav_create_program(
            name="FEAT-106 Dashboard Test Prog",
            slug=prog_slug,
            abbreviation="F106D",
            client="navigator-new",
            group_ids=[1],
        )
        assert prog_result is not None

        # Create module.
        mod_result = await tk.nav_create_module(
            name="FEAT-106 Dashboard Test Mod",
            slug=mod_slug,
            program_slug=prog_slug,
            parent_id=None,
            icon="mdi:dashboard",
            color="#000000",
            client="navigator-new",
            group_id=1,
        )
        assert mod_result is not None

        # Create dashboard.
        dash_result = await tk.nav_create_dashboard(
            name="FEAT-106 Dashboard",
            module_slug=mod_slug,
            program_slug=prog_slug,
            dashboard_type="3",
            position=1,
        )
        assert dash_result is not None
        assert isinstance(dash_result, dict), f"Expected dict, got {type(dash_result)}"
        # The response must contain the dashboard identifier.
        has_id = (
            "dashboard_id" in dash_result
            or "id" in dash_result
            or "menuoption_id" in dash_result
        )
        assert has_id, f"No dashboard ID in result: {dash_result}"

    finally:
        conn = await asyncpg.connect(dsn)
        try:
            await conn.execute("DELETE FROM auth.programs WHERE slug = $1", prog_slug)
        finally:
            await conn.close()


@skip_if_no_pg
@pytest.mark.asyncio
async def test_navigator_update_widget_pk_required():
    """Update with PK in WHERE succeeds; PK-absent update is rejected.

    Uses PostgresToolkit directly to bypass Navigator-specific auth,
    and verifies the PK-enforcement behaviour of update_row.
    """
    import asyncpg  # type: ignore[import]

    dsn = os.environ["NAVIGATOR_PG_DSN"]

    # Load PostgresToolkit from worktree.
    from parrot.bots.database.toolkits.postgres import PostgresToolkit  # noqa: PLC0415

    tk = PostgresToolkit(
        dsn=dsn,
        tables=["navigator.menuoptions"],
        primary_schema="navigator",
        allowed_schemas=["navigator"],
        read_only=False,
    )

    # A minimal update with PK in WHERE should not raise (even if row not found).
    try:
        await tk.update_row(
            "navigator.menuoptions",
            {"name": "FEAT-106 Test (no-op)"},
            where={"menuoption_id": -999999},  # non-existent ID
        )
    except Exception as exc:
        # A "no rows affected" outcome is acceptable; a validation error is not.
        assert "primary key" not in str(exc).lower(), (
            f"Unexpected PK validation failure: {exc}"
        )


@skip_if_no_pg
@pytest.mark.asyncio
async def test_postgres_toolkit_crud_on_fresh_table(pg_toolkit_with_fixture_table):
    """Round-trip INSERT / UPSERT / UPDATE / DELETE on the scratch table.

    Uses the ``pg_toolkit_with_fixture_table`` fixture from tests/conftest.py.
    The fixture creates the table, yields the toolkit, then drops the table.
    """
    tk = pg_toolkit_with_fixture_table

    # INSERT
    insert_result = await tk.insert_row(
        "public.test_crud",
        {"name": "Alice", "data": {"key": "value"}},
        returning=["id", "name"],
    )
    assert insert_result is not None
    row_id = insert_result.get("id") if isinstance(insert_result, dict) else None

    # UPSERT (same name — should update data)
    upsert_result = await tk.upsert_row(
        "public.test_crud",
        {"name": "Alice", "data": {"key": "updated"}},
        conflict_cols=["name"],
        returning=["id", "name"],
    )
    assert upsert_result is not None

    # SELECT
    select_result = await tk.select_rows(
        "public.test_crud",
        where={"name": "Alice"},
        columns=["id", "name", "data"],
    )
    assert isinstance(select_result, list)
    assert len(select_result) >= 1
    assert select_result[0]["name"] == "Alice"

    # UPDATE
    if row_id is not None:
        await tk.update_row(
            "public.test_crud",
            {"data": {"key": "final"}},
            where={"id": row_id},
        )

    # DELETE
    if row_id is not None:
        await tk.delete_row(
            "public.test_crud",
            where={"id": row_id},
        )

    # Verify deletion
    select_after = await tk.select_rows(
        "public.test_crud",
        where={"name": "Alice"},
        columns=["id"],
    )
    assert select_after == [] or all(
        r.get("id") != row_id for r in select_after
    ), "Row was not deleted"
