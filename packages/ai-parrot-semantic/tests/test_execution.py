"""Regression contract: execution bridge (M9a)."""
from types import SimpleNamespace
from typing import Any

import pytest

import parrot.semantic.execution as execution
from parrot.semantic.errors import SemanticExecutionError
from parrot.semantic.execution import ConnectionResolver, Executor
from parrot.semantic.models import GovernedQuery


def _governed(limit: int = 2) -> GovernedQuery:
    return GovernedQuery(
        sql="select a from t", dialect="duckdb", driver="duckdb", tables=("t",), rls_applied=(),
        masked_columns=(), limit=limit, subject_digest="s", members=("a",), physical_columns=("a",),
    )


class _Source:
    def __init__(self, result: Any = None, exc: Exception | None = None) -> None:
        self.result, self.exc, self.creds = result, exc, None

    async def query(self, creds: dict, sql: str) -> Any:
        self.creds = creds
        if self.exc:
            raise self.exc
        return self.result


class _Toolkit:
    def __init__(self, source: _Source | None) -> None:
        self.source = source

    def get_source(self, driver: str) -> _Source:
        if self.source is None:
            raise KeyError(driver)
        return self.source


def test_named_env_overlay_and_missing_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(execution, "get_default_credentials", lambda d: {"host": "h", "port": 1})
    env = {"PARROT_SEMANTIC_CONN_MY_DB_HOST": "override", "PARROT_SEMANTIC_CONN_OTHER_HOST": "x"}
    creds = ConnectionResolver(env).resolve("my-db", "pg")
    assert creds == {"host": "override", "port": 1}
    monkeypatch.setattr(execution, "get_default_credentials", lambda d: {})
    with pytest.raises(SemanticExecutionError) as ei:
        ConnectionResolver({}).resolve("none", "pg")
    assert ei.value.code == "no_credentials"


@pytest.mark.asyncio
async def test_queryresult_unwrap_and_execution_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(execution, "get_default_credentials", lambda d: {"k": "v"})
    resolver = ConnectionResolver({})
    res = SimpleNamespace(rows=[{"a": 1}, {"a": 2}, {"a": 3}], row_count=3, columns=["a"])
    rows, n, trunc, ms, cols = await Executor(_Toolkit(_Source(res)), resolver).run_with_columns(
        _governed(2), connection="c"
    )
    assert rows == [{"a": 1}, {"a": 2}] and n == 2 and trunc is True and cols == ["a"] and ms >= 0
    exact = SimpleNamespace(rows=[{"a": 1}, {"a": 2}], row_count=2, columns=["a"])
    _, n, trunc, _ = await Executor(_Toolkit(_Source(exact)), resolver).run(_governed(2), connection="c")
    assert n == 2 and trunc is False
    empty = SimpleNamespace(rows=[], row_count=0, columns=["a", "b"])
    _, _, _, _, cols = await Executor(_Toolkit(_Source(empty)), resolver).run_with_columns(
        _governed(), connection="c"
    )
    assert cols == ["a", "b"]
    with pytest.raises(SemanticExecutionError) as ei:
        await Executor(_Toolkit(_Source(exc=RuntimeError("select a from t boom"))), resolver).run(
            _governed(), connection="c"
        )
    assert ei.value.code == "execution_failed" and "select" not in str(ei.value)
    with pytest.raises(SemanticExecutionError) as ei:
        await Executor(_Toolkit(None), resolver).run(_governed(), connection="c")
    assert ei.value.code == "no_source"
