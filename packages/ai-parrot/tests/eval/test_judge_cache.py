"""Unit tests for judge models and caches (TASK-4240)."""

import os
import uuid

import pytest

from parrot.eval.judge import (
    InMemoryJudgeCache,
    JudgeCriterion,
    JudgeVerdict,
    PostgresJudgeCache,
    Rubric,
    judge_cache_key,
)
from parrot.eval.sink import PostgresEvalSink


def _rubric(version="1", question="Is it correct?"):
    return Rubric(name="qa", version=version, criteria=[JudgeCriterion(name="correct", question=question)])


def test_cache_key_stable_and_sensitive():
    base = dict(judge_model="j", rubric=_rubric(), question="q", expected={"answer": "a"}, answer="a")
    k1 = judge_cache_key(**base)
    assert k1 == judge_cache_key(**base)
    assert len(k1) == 64
    assert judge_cache_key(**{**base, "rubric": _rubric(version="2")}) != k1
    assert judge_cache_key(**{**base, "rubric": _rubric(question="Other?")}) != k1
    assert judge_cache_key(**{**base, "judge_model": "j2"}) != k1
    assert judge_cache_key(**{**base, "question": "q2"}) != k1
    assert judge_cache_key(**{**base, "expected": {"answer": "b"}}) != k1
    assert judge_cache_key(**{**base, "answer": "b"}) != k1


@pytest.mark.asyncio
async def test_inmemory_roundtrip():
    cache = InMemoryJudgeCache()
    assert await cache.get("k") is None
    verdict = JudgeVerdict(criteria={"correct": True}, rationale="ok")
    await cache.set("k", verdict, judge_model_version="j", rubric_version="1")
    assert await cache.get("k") == verdict


@pytest.mark.asyncio
async def test_postgres_requires_dsn(monkeypatch):
    monkeypatch.setattr(PostgresEvalSink, "_resolve_dsn", staticmethod(lambda: None))
    cache = PostgresJudgeCache(dsn=None)
    with pytest.raises(RuntimeError):
        await cache.get("k")
    with pytest.raises(RuntimeError):
        await cache.set("k", JudgeVerdict(criteria={}), judge_model_version="", rubric_version="")


@pytest.mark.skipif(not os.environ.get("EVAL_DB_DSN"), reason="EVAL_DB_DSN not set")
@pytest.mark.asyncio
async def test_postgres_upsert():
    cache = PostgresJudgeCache(dsn=os.environ["EVAL_DB_DSN"])
    key = f"test-{uuid.uuid4().hex}"
    await cache.set(key, JudgeVerdict(criteria={"a": False}), judge_model_version="j", rubric_version="1")
    await cache.set(key, JudgeVerdict(criteria={"a": True}, rationale="r"), judge_model_version="j", rubric_version="2")
    got = await cache.get(key)
    assert got is not None and got.criteria == {"a": True} and got.rationale == "r"
    import asyncpg

    conn = await asyncpg.connect(os.environ["EVAL_DB_DSN"])
    try:
        n = await conn.fetchval("SELECT count(*) FROM judge_cache WHERE cache_key = $1", key)
        await conn.execute("DELETE FROM judge_cache WHERE cache_key = $1", key)
    finally:
        await conn.close()
    assert n == 1


async def test_postgres_cache_schema_ddl_runs_once(monkeypatch):
    """Concurrent get() calls on one cache execute the schema DDL a single time."""
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
    cache = PostgresJudgeCache(dsn="postgresql://fake")
    await asyncio.gather(*(cache.get(f"k{i}") for i in range(5)))

    assert len(executed) == 1
