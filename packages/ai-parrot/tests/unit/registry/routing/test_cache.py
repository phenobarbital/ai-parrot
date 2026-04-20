"""Unit tests for parrot.registry.routing.cache (TASK-790)."""
import asyncio
import pytest
from parrot.registry.routing import (
    DecisionCache,
    build_cache_key,
    StoreRoutingDecision,
    StoreScore,
)
from parrot.tools.multistoresearch import StoreType


def _decision(path="fast"):
    return StoreRoutingDecision(
        rankings=[StoreScore(store=StoreType.PGVECTOR, confidence=0.9)],
        path=path,
    )


@pytest.mark.asyncio
async def test_disabled_cache():
    c = DecisionCache(0)
    await c.put("k", _decision())
    assert await c.get("k") is None


@pytest.mark.asyncio
async def test_put_and_get():
    c = DecisionCache(4)
    await c.put("k", _decision())
    assert (await c.get("k")).path == "fast"


@pytest.mark.asyncio
async def test_lru_eviction():
    c = DecisionCache(2)
    await c.put("a", _decision("a"))
    await c.put("b", _decision("b"))
    await c.put("c", _decision("c"))  # evicts "a"
    assert await c.get("a") is None
    assert await c.get("b") is not None
    assert await c.get("c") is not None


@pytest.mark.asyncio
async def test_get_promotes_to_mru():
    c = DecisionCache(2)
    await c.put("a", _decision("a"))
    await c.put("b", _decision("b"))
    await c.get("a")           # a is now MRU
    await c.put("c", _decision("c"))  # evicts "b"
    assert await c.get("b") is None
    assert await c.get("a") is not None


@pytest.mark.asyncio
async def test_overwrite_existing_key():
    c = DecisionCache(4)
    await c.put("k", _decision("fast"))
    await c.put("k", _decision("llm"))
    assert (await c.get("k")).path == "llm"


@pytest.mark.asyncio
async def test_concurrent_safety():
    c = DecisionCache(10)

    async def worker(i):
        await c.put(f"k{i}", _decision(str(i)))

    await asyncio.gather(*(worker(i) for i in range(50)))
    # Should not raise; size should be bounded.
    keys_alive = 0
    for i in range(50):
        if await c.get(f"k{i}") is not None:
            keys_alive += 1
    assert keys_alive <= 10


def test_build_cache_key_normalization():
    k1 = build_cache_key("  Hello   World  ", ("pgvector",))
    k2 = build_cache_key("hello world", ("pgvector",))
    assert k1 == k2


def test_build_cache_key_varies_with_fingerprint():
    k1 = build_cache_key("q", ("pgvector",))
    k2 = build_cache_key("q", ("pgvector", "arango"))
    assert k1 != k2


def test_build_cache_key_fingerprint_order_independent():
    k1 = build_cache_key("q", ("pgvector", "arango"))
    k2 = build_cache_key("q", ("arango", "pgvector"))
    assert k1 == k2


def test_build_cache_key_is_hex():
    k = build_cache_key("query", ("pgvector",))
    assert len(k) == 40
    assert all(c in "0123456789abcdef" for c in k)


@pytest.mark.asyncio
async def test_miss_returns_none():
    c = DecisionCache(4)
    assert await c.get("nonexistent") is None


@pytest.mark.asyncio
async def test_eviction_after_257_puts():
    c = DecisionCache(256)
    for i in range(257):
        await c.put(f"key{i}", _decision(str(i)))
    # The oldest entry (key0) should have been evicted.
    assert await c.get("key0") is None
    # More recent entries remain.
    assert await c.get("key256") is not None
