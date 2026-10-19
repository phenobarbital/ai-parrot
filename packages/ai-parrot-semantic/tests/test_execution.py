"""Tests for ConnectionResolver and Executor."""

from __future__ import annotations

import duckdb
import pytest

from parrot.semantic.errors import SemanticExecutionError
from parrot.semantic.execution import ConnectionResolver, Executor
from parrot.semantic.models import GovernedQuery
from parrot.tools.databasequery.base import QueryResult
from parrot.tools.databasequery.toolkit import DatabaseQueryToolkit


def test_connection_resolver_env_overlay(monkeypatch) -> None:
    monkeypatch.setattr("parrot.semantic.execution.get_default_credentials", lambda d: {"user": "u", "password": "x"})
    r = ConnectionResolver(env={"PARROT_SEMANTIC_CONN_WAREHOUSE_PG_PASSWORD": "y"})
    creds = r.resolve("warehouse_pg", "pg")
    assert creds["password"] == "y" and creds["user"] == "u"
    monkeypatch.setattr("parrot.semantic.execution.get_default_credentials", lambda d: {})
    with pytest.raises(SemanticExecutionError) as ei:
        ConnectionResolver(env={}).resolve("x", "pg")
    assert ei.value.code == "no_credentials"


def _patch_duckdb_source(toolkit: DatabaseQueryToolkit) -> None:
    """Keep the stock duckdb source (issue:58d44d14dd8a fixed); errors still surface as source failures."""
    source = toolkit.get_source("duckdb")
    real_query = source.query

    async def _query(credentials, sql, params=None):
        try:
            return await real_query(credentials, sql, params)
        except Exception:
            raise RuntimeError("boom") from None

    source.query = _query  # type: ignore[method-assign]


def _gq(sql: str, limit: int = 100, driver: str = "duckdb") -> GovernedQuery:
    return GovernedQuery(
        sql=sql,
        dialect="duckdb",
        driver=driver,
        tables=(),
        rls_applied=(),
        masked_columns=(),
        limit=limit,
        subject_digest="d",
    )


@pytest.mark.asyncio
async def test_executor_runs_against_duckdb(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr("parrot.semantic.execution.get_default_credentials", lambda d: {})
    db = str(tmp_path / "t.duckdb")
    resolver = ConnectionResolver(env={"PARROT_SEMANTIC_CONN_LOCAL_DATABASE": db})
    tk = DatabaseQueryToolkit()
    _patch_duckdb_source(tk)
    ex = Executor(tk, resolver)
    rows, n, truncated, ms = await ex.run(_gq("SELECT * FROM range(5) t(x)", limit=10), connection="local")
    assert n == 5 and len(rows) == 5 and truncated is False and ms >= 0
    rows, n, truncated, _ = await ex.run(_gq("SELECT * FROM range(5) t(x)", limit=3), connection="local")
    assert n == 3 and truncated is True and len(rows) == 3


@pytest.mark.asyncio
async def test_executor_errors_hide_sql(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr("parrot.semantic.execution.get_default_credentials", lambda d: {})
    resolver = ConnectionResolver(env={"PARROT_SEMANTIC_CONN_LOCAL_DATABASE": str(tmp_path / "t.duckdb")})
    tk = DatabaseQueryToolkit()
    _patch_duckdb_source(tk)
    ex = Executor(tk, resolver)
    sql = "SELECT * FROM missing_table_zz"
    with pytest.raises(SemanticExecutionError) as ei:
        await ex.run(_gq(sql), connection="local")
    assert ei.value.code == "execution_failed" and "missing_table_zz" not in str(ei.value)
    with pytest.raises(SemanticExecutionError) as ei:
        await ex.run(_gq("SELECT 1", driver="nope_driver"), connection="local")
    assert ei.value.code == "no_source"
