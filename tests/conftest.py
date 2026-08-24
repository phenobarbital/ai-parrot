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


# ---------------------------------------------------------------------------
# Loop-local SDK client binding for tests (FEAT-112)
#
# `AbstractClient.client` became a loop-local property whose setter rejects
# non-None assignment: the SDK client must come back from `get_client()` and
# is cached per event loop in `_clients_by_loop`.
#
# The client fixtures below build their instances with `cls.__new__(cls)` to
# skip `__init__`, so there is no per-loop cache to populate, and they are
# sync, so there is no running loop whose id could key one. Both reasons rule
# out writing the cache directly — and `client` is a data descriptor on the
# class, so an instance attribute cannot shadow it either.
#
# Binding at the class level (undone by monkeypatch) is what is left, plus
# neutralising `_ensure_client()` so `invoke()` does not try to build a real
# SDK client on the way through.
# ---------------------------------------------------------------------------
@pytest.fixture
def bind_sdk_client(monkeypatch):
    """Return a helper that binds a mock SDK client onto an AbstractClient.

    Usage::

        @pytest.fixture
        def mock_groq_client(bind_sdk_client):
            client = _make_client()
            sdk = MagicMock()
            sdk.chat.completions.create = AsyncMock(return_value=...)
            bind_sdk_client(client, sdk)
            return client

    After binding, ``client.client`` returns ``sdk``, so existing test bodies
    that reach through ``client.client...`` keep working unchanged.
    """
    from unittest.mock import AsyncMock

    def _bind(client, sdk):
        # Mirror the real property's contract: reading returns the bound SDK,
        # assigning None resets it (legacy semantics), assigning anything else
        # raises exactly as AbstractClient does.
        state = {"sdk": sdk}

        def _get(_self):
            return state["sdk"]

        def _set(_self, value):
            if value is not None:
                raise AttributeError(
                    "AbstractClient.client is now a loop-local property. "
                    "Do not assign directly — return the client from get_client()."
                )
            state["sdk"] = None

        monkeypatch.setattr(type(client), "client", property(_get, _set))
        monkeypatch.setattr(
            client, "get_client", AsyncMock(return_value=sdk), raising=False
        )
        monkeypatch.setattr(
            client, "_ensure_client", AsyncMock(return_value=sdk), raising=False
        )
        return sdk

    return _bind
