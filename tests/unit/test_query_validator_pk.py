"""Tests for QueryValidator PK-presence extension (TASK-739 / FEAT-106).

Verifies the new ``require_pk_in_where`` and ``primary_keys`` kwargs on
``validate_sql_ast`` while ensuring backward-compatible default behaviour.
"""
from __future__ import annotations

import pytest
from parrot.security import QueryValidator


class TestValidateSqlAstPkPresence:
    """PK-presence enforcement in UPDATE / DELETE WHERE clauses."""

    def test_pk_presence_passes_with_pk_in_where(self) -> None:
        """UPDATE with WHERE on PK column is accepted."""
        result = QueryValidator.validate_sql_ast(
            "UPDATE test.t SET x=1 WHERE id=5",
            dialect="postgres",
            read_only=False,
            require_pk_in_where=True,
            primary_keys=["id"],
        )
        assert result.get("is_safe") is True

    def test_pk_presence_rejects_non_pk_where(self) -> None:
        """UPDATE with WHERE only on non-PK column is rejected."""
        result = QueryValidator.validate_sql_ast(
            "UPDATE test.t SET x=1 WHERE status='y'",
            dialect="postgres",
            read_only=False,
            require_pk_in_where=True,
            primary_keys=["id"],
        )
        assert result.get("is_safe") is False
        assert "primary key" in result.get("message", "").lower()

    def test_pk_presence_accepts_any_pk_of_composite(self) -> None:
        """Composite PK: WHERE with any one PK column is accepted."""
        result = QueryValidator.validate_sql_ast(
            "UPDATE test.t SET x=1 WHERE a=1",
            dialect="postgres",
            read_only=False,
            require_pk_in_where=True,
            primary_keys=["a", "b"],
        )
        assert result.get("is_safe") is True

    def test_pk_presence_rejects_neither_pk_of_composite(self) -> None:
        """Composite PK: WHERE with neither PK column is rejected."""
        result = QueryValidator.validate_sql_ast(
            "UPDATE test.t SET x=1 WHERE status='y'",
            dialect="postgres",
            read_only=False,
            require_pk_in_where=True,
            primary_keys=["a", "b"],
        )
        assert result.get("is_safe") is False

    def test_pk_presence_backcompat_default_false(self) -> None:
        """Default (require_pk_in_where=False) preserves pre-feature behaviour.

        An UPDATE on a non-PK column is still accepted because the original
        validator only checks for the presence of WHERE, not its contents.
        """
        baseline = QueryValidator.validate_sql_ast(
            "UPDATE test.t SET x=1 WHERE status='y'",
            dialect="postgres",
            read_only=False,
        )
        assert baseline.get("is_safe") is True

    def test_pk_presence_delete(self) -> None:
        """DELETE with WHERE on PK column is accepted."""
        result = QueryValidator.validate_sql_ast(
            "DELETE FROM test.t WHERE id=5",
            dialect="postgres",
            read_only=False,
            require_pk_in_where=True,
            primary_keys=["id"],
        )
        assert result.get("is_safe") is True

    def test_pk_presence_delete_rejects_non_pk(self) -> None:
        """DELETE with WHERE on non-PK column is rejected."""
        result = QueryValidator.validate_sql_ast(
            "DELETE FROM test.t WHERE status='active'",
            dialect="postgres",
            read_only=False,
            require_pk_in_where=True,
            primary_keys=["id"],
        )
        assert result.get("is_safe") is False
        assert "primary key" in result.get("message", "").lower()

    def test_pk_presence_true_with_empty_primary_keys_rejects(self) -> None:
        """require_pk_in_where=True with empty primary_keys is a misconfiguration."""
        result = QueryValidator.validate_sql_ast(
            "UPDATE test.t SET x=1 WHERE id=5",
            dialect="postgres",
            read_only=False,
            require_pk_in_where=True,
            primary_keys=[],
        )
        assert result.get("is_safe") is False
        assert "non-empty" in result.get("message", "").lower() or "primary_keys" in result.get("message", "")

    def test_pk_presence_true_with_none_primary_keys_rejects(self) -> None:
        """require_pk_in_where=True with None primary_keys is a misconfiguration."""
        result = QueryValidator.validate_sql_ast(
            "UPDATE test.t SET x=1 WHERE id=5",
            dialect="postgres",
            read_only=False,
            require_pk_in_where=True,
            primary_keys=None,
        )
        assert result.get("is_safe") is False

    def test_validate_sql_query_legacy_unchanged(self) -> None:
        """The regex-based validate_sql_query is not affected by this change."""
        result = QueryValidator.validate_sql_query("SELECT 1")
        assert isinstance(result, dict)
        assert "is_safe" in result
