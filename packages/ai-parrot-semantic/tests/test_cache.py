"""Tests for the pre-governance compile cache."""
from __future__ import annotations

from parrot.semantic.cache import CompileCache
from parrot.semantic.models import CompiledQuery


def _cq(key: str) -> CompiledQuery:
    return CompiledQuery(sql="SELECT 1", dialect="duckdb", engine="native", members=(), tables=(), cache_key=key)


def test_compile_cache_pre_governance_only() -> None:
    cache = CompileCache(max_entries=2)
    cache.put(_cq("a"), model_digest="m1")
    cache.put(_cq("b"), model_digest="m2")
    assert cache.get("a") is not None  # refresh a
    cache.put(_cq("c"), model_digest="m1")  # evicts b
    assert cache.get("b") is None
    assert isinstance(cache.get("a"), CompiledQuery)
    assert cache.invalidate_model("m1") == 2
    assert cache.get("a") is None and cache.get("c") is None
    assert cache.invalidate_model("m1") == 0
