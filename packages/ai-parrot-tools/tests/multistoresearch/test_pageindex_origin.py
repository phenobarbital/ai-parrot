"""Unit tests for PageIndexOrigin (FEAT-379)."""
import asyncio
import numpy as np
import pytest

from parrot.models import SearchOriginKind
from parrot_tools.multistoresearch.origins import PageIndexOrigin


class FakeHybrid:
    async def search(self, query, top_k=10, **kw):
        return [
            {"node_id": "n1", "title": "T1", "summary": "S1", "score": 0.9, "source": "fused"},
            {"node_id": "n2", "title": "T2", "summary": "S2", "score": 0.5, "source": "bm25"},
        ]


class FakeTreeSearchResult:
    def __init__(self, node_list, thinking="reasoning"):
        self.node_list = node_list
        self.thinking = thinking


class FakeLLMRetriever:
    def __init__(self):
        self.structure = [
            {"node_id": "n1", "title": "T1", "summary": "S1"},
            {"node_id": "n2", "title": "T2", "summary": "S2"},
        ]

    async def search(self, query):
        return FakeTreeSearchResult(node_list=["n1", "n2"])


class FakeFlatMatrixSearch:
    def __init__(self, delay: float = 0.0):
        self._delay = delay

    def search(self, query_vec, top_k):
        if self._delay:
            import time

            time.sleep(self._delay)
        return [("n1", 0.9), ("n2", 0.5)][:top_k]


async def _fake_embed_fn(query):
    return np.array([0.1, 0.2, 0.3], dtype=np.float32)


def test_default_mode_is_hybrid():
    origin = PageIndexOrigin(hybrid=FakeHybrid())
    assert origin.mode == "hybrid"


def test_invalid_mode_rejected():
    with pytest.raises(ValueError):
        PageIndexOrigin(hybrid=FakeHybrid(), mode="quantum")


def test_hybrid_mode_requires_backend():
    with pytest.raises(ValueError):
        PageIndexOrigin(mode="hybrid")


def test_llm_mode_requires_backend():
    with pytest.raises(ValueError):
        PageIndexOrigin(mode="llm")


def test_vector_mode_requires_backend_and_embed_fn():
    with pytest.raises(ValueError):
        PageIndexOrigin(mode="vector")
    with pytest.raises(ValueError):
        PageIndexOrigin(mode="vector", vector=FakeFlatMatrixSearch())


def test_supports_fts_is_false():
    assert PageIndexOrigin(hybrid=FakeHybrid()).supports_fts is False


async def test_hybrid_mode_normalizes():
    hits = await PageIndexOrigin(hybrid=FakeHybrid()).search("q", k=5)
    assert hits[0].origin_kind == SearchOriginKind.PAGEINDEX
    assert [h.native_rank for h in hits] == [1, 2]
    assert hits[0].id == "n1"
    assert "T1" in hits[0].content


async def test_llm_mode_normalizes():
    origin = PageIndexOrigin(llm=FakeLLMRetriever(), mode="llm")
    hits = await origin.search("q", k=5)
    assert [h.native_rank for h in hits] == [1, 2]
    assert hits[0].origin_kind == SearchOriginKind.PAGEINDEX
    assert hits[0].metadata["thinking"] == "reasoning"


async def test_llm_mode_truncates_to_k():
    origin = PageIndexOrigin(llm=FakeLLMRetriever(), mode="llm")
    hits = await origin.search("q", k=1)
    assert len(hits) == 1


async def test_vector_mode_normalizes():
    origin = PageIndexOrigin(
        vector=FakeFlatMatrixSearch(), embed_fn=_fake_embed_fn, mode="vector"
    )
    hits = await origin.search("q", k=2)
    assert [h.native_rank for h in hits] == [1, 2]
    assert hits[0].origin_kind == SearchOriginKind.PAGEINDEX
    assert hits[0].score == 0.9


async def test_vector_mode_offloaded_does_not_block_loop():
    """A slow SYNC backend must not freeze the event loop."""
    origin = PageIndexOrigin(
        vector=FakeFlatMatrixSearch(delay=0.3), embed_fn=_fake_embed_fn, mode="vector"
    )

    progressed = False

    async def _ticker():
        nonlocal progressed
        await asyncio.sleep(0.05)
        progressed = True

    search_task = asyncio.create_task(origin.search("q", k=2))
    ticker_task = asyncio.create_task(_ticker())

    await asyncio.wait_for(ticker_task, timeout=1.0)
    assert progressed is True  # the ticker made progress DURING the slow search

    hits = await asyncio.wait_for(search_task, timeout=2.0)
    assert len(hits) == 2
