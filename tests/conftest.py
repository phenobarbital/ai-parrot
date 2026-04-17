"""Top-level pytest conftest for ai-parrot integration test fixtures.

Provides shared fixtures used by integration tests that require a live
Postgres connection (FEAT-106 / TASK-746).

Fixtures requiring a live DB are conditionally skipped when
``NAVIGATOR_PG_DSN`` is not set in the environment.
"""
from __future__ import annotations

import os

import pytest


# ---------------------------------------------------------------------------
# pg_dsn — source from environment
# ---------------------------------------------------------------------------

@pytest.fixture
def pg_dsn() -> str:
    """Return the Postgres DSN from the environment.

    Tests that use this fixture are automatically skipped when the env var
    is absent — they should be marked with ``@pytest.mark.integration``
    and guarded by ``skip_if_no_pg``.
    """
    dsn = os.getenv("NAVIGATOR_PG_DSN", "")
    return dsn


# ---------------------------------------------------------------------------
# pg_toolkit_with_fixture_table — scratch-table fixture for CRUD round-trips
# ---------------------------------------------------------------------------

@pytest.fixture
async def pg_toolkit_with_fixture_table(pg_dsn):
    """Spin up a PostgresToolkit pointing at a scratch table.

    Creates::

        CREATE TABLE IF NOT EXISTS public.test_crud (
            id    SERIAL PRIMARY KEY,
            name  TEXT   UNIQUE NOT NULL,
            data  JSONB  DEFAULT '{}'
        );

    Yields a started ``PostgresToolkit`` instance. Drops the table on
    teardown to avoid leaving debris in the test database.

    Skips automatically when ``NAVIGATOR_PG_DSN`` is not set.
    """
    import os
    import sys

    if not pg_dsn:
        pytest.skip("NAVIGATOR_PG_DSN not set — skipping integration fixture")

    # Load worktree source so we get the FEAT-106 PostgresToolkit.
    _WT_SRC = os.path.normpath(
        os.path.join(os.path.dirname(__file__), os.pardir,
                     "packages", "ai-parrot", "src")
    )
    if _WT_SRC not in sys.path:
        sys.path.insert(0, _WT_SRC)

    from parrot.bots.database.toolkits.postgres import PostgresToolkit

    CREATE_SQL = """
        CREATE TABLE IF NOT EXISTS public.test_crud (
            id    SERIAL PRIMARY KEY,
            name  TEXT   UNIQUE NOT NULL,
            data  JSONB  DEFAULT '{}'
        );
    """
    DROP_SQL = "DROP TABLE IF EXISTS public.test_crud;"

    tk = PostgresToolkit(
        dsn=pg_dsn,
        tables=["test_crud"],
        primary_schema="public",
        allowed_schemas=["public"],
        read_only=False,
    )

    # Use asyncpg directly to create the scratch table.
    import asyncpg  # type: ignore[import]
    conn = await asyncpg.connect(pg_dsn)
    try:
        await conn.execute(CREATE_SQL)
    finally:
        await conn.close()

    yield tk

    # Teardown: drop the scratch table.
    conn = await asyncpg.connect(pg_dsn)
    try:
        await conn.execute(DROP_SQL)
    finally:
        await conn.close()
