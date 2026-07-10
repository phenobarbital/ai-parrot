"""Unit tests for TASK-013 — fieldsync schema DDL (no real DB).

Verifies:
- DDL strings are well-formed and contain expected identifiers.
- FieldsyncSchemaManager.initialize() calls conn.execute for every DDL
  statement (idempotence path tested via fake pool).
- Second call to initialize() runs without error (idempotent).
- ddl_statements() returns a fresh copy (mutation-safe).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot_formdesigner.services.fieldsync_schema import (
    FieldsyncSchemaManager,
    _CREATE_AUTH_POLICIES_SQL,
    _CREATE_LOCATIONS_SQL,
    _CREATE_PROJECTS_SQL,
    _CREATE_SCHEMA_SQL,
    _CREATE_SITES_SQL,
    _CREATE_WORKDAY_COST_CENTER_MAPPINGS_SQL,
)


# ---------------------------------------------------------------------------
# Fake pool / connection helpers
# ---------------------------------------------------------------------------


def _make_fake_pool() -> MagicMock:
    """Build a fake asyncpg-style pool that records executed SQL."""
    conn = MagicMock()
    conn.execute = AsyncMock(return_value=None)

    pool = MagicMock()
    # acquire() is an async context manager
    acquire_cm = MagicMock()
    acquire_cm.__aenter__ = AsyncMock(return_value=conn)
    acquire_cm.__aexit__ = AsyncMock(return_value=False)
    pool.acquire = MagicMock(return_value=acquire_cm)
    pool._conn = conn  # expose for assertions
    return pool


# ---------------------------------------------------------------------------
# DDL content tests (pure string assertions — no I/O)
# ---------------------------------------------------------------------------


class TestDDLContent:
    """Verify DDL strings contain the expected Postgres constructs."""

    def test_schema_ddl_is_idempotent(self) -> None:
        assert "CREATE SCHEMA IF NOT EXISTS fieldsync" in _CREATE_SCHEMA_SQL

    def test_projects_table_ddl(self) -> None:
        sql = _CREATE_PROJECTS_SQL
        assert "CREATE TABLE IF NOT EXISTS fieldsync.projects" in sql
        assert "accounting_code" in sql
        assert "client_id" in sql
        assert "UNIQUE (client_id, accounting_code)" in sql or "UNIQUE(client_id, accounting_code)" in sql or "uq_projects_client_accounting" in sql

    def test_workday_mappings_ddl(self) -> None:
        sql = _CREATE_WORKDAY_COST_CENTER_MAPPINGS_SQL
        assert "CREATE TABLE IF NOT EXISTS fieldsync.workday_cost_center_mappings" in sql
        assert "project_id" in sql
        assert "workday_code" in sql
        # UNIQUE on project_id
        assert "UNIQUE" in sql

    def test_auth_policies_ddl(self) -> None:
        sql = _CREATE_AUTH_POLICIES_SQL
        assert "CREATE TABLE IF NOT EXISTS fieldsync.auth_policies" in sql
        assert "policy" in sql
        assert "JSONB" in sql
        assert "enforcing" in sql
        assert "priority" in sql

    def test_sites_table_ddl(self) -> None:
        sql = _CREATE_SITES_SQL
        assert "CREATE TABLE IF NOT EXISTS fieldsync.sites" in sql
        assert "store_id" in sql
        assert "uq_sites_store_name" in sql

    def test_locations_table_ddl(self) -> None:
        sql = _CREATE_LOCATIONS_SQL
        assert "CREATE TABLE IF NOT EXISTS fieldsync.locations" in sql
        assert "geofence_radius_m" in sql
        assert "REFERENCES fieldsync.sites" in sql
        assert "ON DELETE CASCADE" in sql

    def test_ddl_statements_returns_six(self) -> None:
        # 4 base (schema, projects, workday_map, auth_policies)
        # + 2 FEAT-330 (sites, locations)
        stmts = FieldsyncSchemaManager.ddl_statements()
        assert len(stmts) == 6

    def test_ddl_statements_is_copy(self) -> None:
        stmts = FieldsyncSchemaManager.ddl_statements()
        stmts.clear()
        assert len(FieldsyncSchemaManager.ddl_statements()) == 6


# ---------------------------------------------------------------------------
# Fake-pool integration tests
# ---------------------------------------------------------------------------


class TestFieldsyncSchemaManager:
    """Test FieldsyncSchemaManager behavior with a fake pool."""

    @pytest.mark.asyncio
    async def test_initialize_calls_all_ddl_statements(self) -> None:
        pool = _make_fake_pool()
        mgr = FieldsyncSchemaManager(pool)
        await mgr.initialize()

        conn = pool._conn
        calls = [call.args[0] for call in conn.execute.call_args_list]
        expected = FieldsyncSchemaManager.ddl_statements()
        assert len(calls) == len(expected), f"Expected {len(expected)} DDL calls, got {len(calls)}"
        for stmt in expected:
            assert stmt in calls, f"DDL statement not executed: {stmt[:60]!r}"

    @pytest.mark.asyncio
    async def test_initialize_twice_no_error(self) -> None:
        """Second call must not raise (idempotent)."""
        pool = _make_fake_pool()
        mgr = FieldsyncSchemaManager(pool)
        await mgr.initialize()
        await mgr.initialize()  # should not raise
        conn = pool._conn
        # 6 statements × 2 calls = 12
        assert conn.execute.call_count == 12

    @pytest.mark.asyncio
    async def test_initialize_propagates_db_error(self) -> None:
        """DB errors must propagate (not swallowed)."""
        pool = _make_fake_pool()
        pool._conn.execute = AsyncMock(side_effect=RuntimeError("DB down"))
        mgr = FieldsyncSchemaManager(pool)
        with pytest.raises(RuntimeError, match="DB down"):
            await mgr.initialize()
