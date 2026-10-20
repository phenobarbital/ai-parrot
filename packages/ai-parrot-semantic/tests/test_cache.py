"""Tests for the pre-governance compile cache."""

from __future__ import annotations

from parrot.semantic.cache import CompileCache
from parrot.semantic.engines import compile as compile_query
from parrot.semantic.models import CompiledQuery, SemanticQuery

from ._models import loaded_models, models_dir  # noqa: F401 - pytest fixtures


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


async def test_compile_registers_model_digest_for_invalidation(loaded_models) -> None:
    """compile() must record the model digest, or invalidate_model can never drop its entries."""
    model = loaded_models["orders"]
    cache = CompileCache()
    query = SemanticQuery(model="orders", metrics=["revenue"], dimensions=["region"])

    compiled = await compile_query(query, model, "duckdb", cache=cache)

    assert cache.get(compiled.cache_key) is not None
    assert cache.invalidate_model(model.model_digest) == 1
    assert cache.get(compiled.cache_key) is None
