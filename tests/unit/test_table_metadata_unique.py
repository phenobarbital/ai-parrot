"""Tests for TableMetadata.unique_constraints + SQLToolkit hook (TASK-740 / FEAT-106).

Verifies the new ``unique_constraints`` field on ``TableMetadata`` and the
``_get_unique_constraints_query`` dialect hook on ``SQLToolkit``.
"""
from __future__ import annotations

import os
import sys

# Use the worktree's source tree to ensure our changes are visible.
sys.path.insert(0, os.path.dirname(__file__))
from conftest_db import setup_worktree_imports  # noqa: E402
setup_worktree_imports()

import pytest
from parrot.bots.database.models import TableMetadata
from parrot.bots.database.toolkits.sql import SQLToolkit


class TestTableMetadataUniqueConstraints:
    """TableMetadata.unique_constraints field behaviour."""

    def test_default_empty(self) -> None:
        """Constructing TableMetadata without unique_constraints defaults to []."""
        meta = TableMetadata(
            schema="test",
            tablename="t",
            table_type="BASE TABLE",
            full_name='"test"."t"',
            columns=[{"name": "id", "type": "integer", "nullable": False, "default": None}],
            primary_keys=["id"],
        )
        assert meta.unique_constraints == []

    def test_explicit_value_preserved(self) -> None:
        """An explicitly set unique_constraints value is preserved."""
        meta = TableMetadata(
            schema="test",
            tablename="t",
            table_type="BASE TABLE",
            full_name='"test"."t"',
            primary_keys=["id"],
            unique_constraints=[["email"], ["a", "b"]],
        )
        assert meta.unique_constraints == [["email"], ["a", "b"]]

    def test_to_dict_includes_unique_constraints(self) -> None:
        """to_dict() serialises unique_constraints."""
        meta = TableMetadata(
            schema="test",
            tablename="t",
            table_type="BASE TABLE",
            full_name='"test"."t"',
            primary_keys=["id"],
            unique_constraints=[["email"], ["a", "b"]],
        )
        d = meta.to_dict()
        assert "unique_constraints" in d
        assert d["unique_constraints"] == [["email"], ["a", "b"]]

    def test_to_dict_primary_keys_present(self) -> None:
        """to_dict() includes primary_keys alongside unique_constraints."""
        meta = TableMetadata(
            schema="s",
            tablename="t",
            table_type="BASE TABLE",
            full_name='"s"."t"',
            primary_keys=["id"],
            unique_constraints=[["slug"]],
        )
        d = meta.to_dict()
        assert d["primary_keys"] == ["id"]
        assert d["unique_constraints"] == [["slug"]]

    def test_existing_callers_unaffected(self) -> None:
        """Code that creates TableMetadata without the new field still works."""
        meta = TableMetadata(
            schema="public",
            tablename="users",
            table_type="BASE TABLE",
            full_name='"public"."users"',
        )
        # No AttributeError; field defaults to []
        assert isinstance(meta.unique_constraints, list)


class TestSqlToolkitUniqueHook:
    """SQLToolkit._get_unique_constraints_query dialect hook."""

    def test_get_unique_constraints_query_shape(self) -> None:
        """Hook returns (str, dict) with UNIQUE keyword and schema param."""
        sql, params = SQLToolkit._get_unique_constraints_query(None, "public", "t")  # type: ignore[arg-type]
        assert isinstance(sql, str)
        assert "UNIQUE" in sql.upper()
        assert isinstance(params, dict)
        assert params.get("schema") == "public"
        assert params.get("table") == "t"

    def test_unique_query_contains_information_schema(self) -> None:
        """Default query targets information_schema."""
        sql, _ = SQLToolkit._get_unique_constraints_query(None, "auth", "programs")  # type: ignore[arg-type]
        assert "information_schema" in sql.lower()

    @pytest.mark.asyncio
    async def test_build_table_metadata_populates_unique(self) -> None:
        """_build_table_metadata fills unique_constraints when hook returns rows."""
        from unittest.mock import MagicMock

        toolkit = SQLToolkit.__new__(SQLToolkit)
        toolkit.logger = MagicMock()
        toolkit.backend = "asyncdb"
        toolkit._connection = MagicMock()

        col_rows = [
            {"column_name": "id", "data_type": "integer", "is_nullable": "NO", "column_default": None},
            {"column_name": "email", "data_type": "varchar", "is_nullable": "NO", "column_default": None},
        ]
        pk_rows = [{"column_name": "id"}]
        uq_rows = [
            {"constraint_name": "users_email_key", "column_name": "email", "ordinal_position": 1},
        ]

        call_results = [
            (col_rows, None),
            (pk_rows, None),
            (uq_rows, None),
        ]

        async def fake_execute(sql: str, limit: int = 0, timeout: int = 15):
            return call_results.pop(0)

        toolkit._execute_asyncdb = fake_execute

        meta = await toolkit._build_table_metadata("public", "users", "BASE TABLE")
        assert meta is not None
        assert meta.unique_constraints == [["email"]]

    @pytest.mark.asyncio
    async def test_build_table_metadata_empty_unique_on_no_rows(self) -> None:
        """_build_table_metadata leaves unique_constraints=[] when hook returns nothing."""
        from unittest.mock import MagicMock

        toolkit = SQLToolkit.__new__(SQLToolkit)
        toolkit.logger = MagicMock()
        toolkit.backend = "asyncdb"
        toolkit._connection = MagicMock()

        col_rows = [
            {"column_name": "id", "data_type": "integer", "is_nullable": "NO", "column_default": None},
        ]
        call_results = [
            (col_rows, None),
            ([{"column_name": "id"}], None),
            ([], None),
        ]

        async def fake_execute(sql: str, limit: int = 0, timeout: int = 15):
            return call_results.pop(0)

        toolkit._execute_asyncdb = fake_execute

        meta = await toolkit._build_table_metadata("public", "simple", "BASE TABLE")
        assert meta is not None
        assert meta.unique_constraints == []
