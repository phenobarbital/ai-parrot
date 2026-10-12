"""Unit tests for the regression gate (TASK-4242)."""

import os

import pytest

from parrot.eval.regression import (
    InMemoryBaselineStore,
    PostgresBaselineStore,
    RegressionVerdict,
    check_regression,
)
from parrot.eval.runner import EvalReport, EvalRunConfig
from parrot.eval.sink import PostgresEvalSink


def _report(pass_k, per_tag, name="qa"):
    return EvalReport(dataset_name=name, config=EvalRunConfig(), pass_k=pass_k, per_tag=per_tag)


async def test_per_tag_independent():
    store = InMemoryBaselineStore()
    await store.record(_report(0.9, {"A": 0.8, "B": 0.9}))
    verdict = await check_regression(_report(0.9, {"A": 0.95, "B": 0.7}), store, tolerance=0.05)
    assert isinstance(verdict, RegressionVerdict)
    assert verdict.regressed_tags == ["B"]
    assert not verdict.passed


async def test_no_baseline_passes():
    store = InMemoryBaselineStore()
    verdict = await check_regression(_report(0.1, {"A": 0.0}), store)
    assert verdict.passed
    assert verdict.overall_baseline is None
    assert await store.get_baseline("qa") is None  # gate never writes


async def test_overall_regression_flags_empty_tag():
    store = InMemoryBaselineStore()
    await store.record(_report(0.9, {}))
    verdict = await check_regression(_report(0.5, {}), store, tolerance=0.05)
    assert verdict.regressed_tags == [""]
    assert verdict.overall_baseline == 0.9
    assert verdict.overall_candidate == 0.5


async def test_within_tolerance_passes():
    store = InMemoryBaselineStore()
    await store.record(_report(0.9, {"A": 0.9}))
    verdict = await check_regression(_report(0.86, {"A": 0.86}), store, tolerance=0.05)
    assert verdict.passed


async def test_record_overall_and_tags():
    store = InMemoryBaselineStore()
    await store.record(_report(0.7, {"A": 0.6}))
    assert await store.get_baseline("qa") == 0.7
    assert await store.get_baseline("qa", "A") == 0.6
    await store.record(_report(None, {"A": 0.5}))
    assert await store.get_baseline("qa") == 0.7
    assert await store.get_baseline("qa", "A") == 0.5


async def test_postgres_requires_dsn(monkeypatch):
    monkeypatch.setattr(PostgresEvalSink, "_resolve_dsn", staticmethod(lambda: None))
    store = PostgresBaselineStore()  # construction must not raise
    with pytest.raises(RuntimeError):
        await store.get_baseline("qa")
    with pytest.raises(RuntimeError):
        await store.record(_report(0.5, {}))


@pytest.mark.skipif(not os.environ.get("EVAL_DB_DSN"), reason="EVAL_DB_DSN not set")
async def test_postgres_roundtrip():
    store = PostgresBaselineStore(os.environ["EVAL_DB_DSN"])
    name = f"regression-test-{os.getpid()}"
    await store.record(_report(0.5, {"A": 0.4}, name=name))
    await store.record(_report(0.8, {"A": 0.7}, name=name))
    assert await store.get_baseline(name) == pytest.approx(0.8)
    assert await store.get_baseline(name, "A") == pytest.approx(0.7)


async def test_postgres_schema_ddl_runs_once(monkeypatch):
    """Concurrent calls on one store execute the schema DDL a single time."""
    import asyncio
    import sys
    import types

    executed: list[str] = []

    class FakeConn:
        async def execute(self, sql, *args):
            executed.append(sql)

        async def fetchrow(self, sql, *args):
            return None

        async def close(self):
            return None

    async def connect(dsn):
        return FakeConn()

    monkeypatch.setitem(sys.modules, "asyncpg", types.SimpleNamespace(connect=connect))
    store = PostgresBaselineStore(dsn="postgresql://fake")
    await asyncio.gather(*(store.get_baseline("qa", "t") for _ in range(5)))
    await store.get_baseline("qa", "t")

    assert len(executed) == 1
