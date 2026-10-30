"""Regression contract: compile cache (M9a)."""

import json

import pytest

from parrot.semantic.cache import CompileCache
from parrot.semantic.models import CompiledQuery


def _cq(model: str, n: int) -> CompiledQuery:
    key = json.dumps([model, "pol", f"q{n}", "duckdb", "v1", "conn"], separators=(",", ":"))
    return CompiledQuery(sql="select 1", dialect="duckdb", members=("m",), tables=("t",), cache_key=key)


def test_lru_bounds_and_real_model_invalidation() -> None:
    cache = CompileCache(max_entries=3)
    a, b, c = _cq("A", 1), _cq("B", 2), _cq("A", 3)
    for q in (a, b, c):
        cache.put(q)
    assert cache.get(a.cache_key) is a  # a becomes most recent
    d = _cq("B", 4)
    cache.put(d)  # evicts b
    assert len(cache) == 3
    assert cache.get(b.cache_key) is None
    assert cache.invalidate_model("A") == 2
    assert cache.get(a.cache_key) is None and cache.get(c.cache_key) is None
    assert cache.get(d.cache_key) is d
    assert cache.invalidate_model("A") == 0
    assert cache.invalidate_model("B") == 1
    assert len(cache) == 0


def test_put_rejects_opaque_key_without_mutation() -> None:
    cache = CompileCache()
    bad = CompiledQuery(sql="s", dialect="d", members=(), tables=(), cache_key="opaquehash")
    with pytest.raises(ValueError):
        cache.put(bad)
    assert len(cache) == 0
