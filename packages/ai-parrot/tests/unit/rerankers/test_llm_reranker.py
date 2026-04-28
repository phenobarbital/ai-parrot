"""Unit tests for LLMReranker.

All tests use a mocked AbstractClient — no real LLM calls are made.
"""

import math

import pytest
from unittest.mock import AsyncMock, MagicMock

from parrot.rerankers import LLMReranker
from parrot.stores.models import SearchResult


@pytest.fixture
def fake_client_ordered():
    """Mock client returning scores 0.9, 0.3, 0.7 in order."""
    scores = iter(["0.9", "0.3", "0.7"])
    client = MagicMock()
    client.invoke = AsyncMock(side_effect=lambda *a, **kw: next(scores))
    return client


@pytest.fixture
def fake_docs():
    """Three SearchResult objects for LLM reranker tests."""
    return [
        SearchResult(id="1", content="relevant doc", metadata={}, score=0.8),
        SearchResult(id="2", content="irrelevant doc", metadata={}, score=0.85),
        SearchResult(id="3", content="somewhat relevant", metadata={}, score=0.75),
    ]


# ---------------------------------------------------------------------------
# Basic ordering
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_llm_reranker_basic_ordering(fake_client_ordered, fake_docs):
    """Results are sorted by score descending."""
    reranker = LLMReranker(client=fake_client_ordered)
    results = await reranker.rerank("test query", fake_docs)

    assert len(results) == 3
    assert results[0].rerank_score == pytest.approx(0.9)
    assert results[1].rerank_score == pytest.approx(0.7)
    assert results[2].rerank_score == pytest.approx(0.3)


@pytest.mark.asyncio
async def test_llm_reranker_preserves_original_rank(fake_docs):
    """original_rank corresponds to position in the input list."""
    scores = iter(["0.5", "0.9", "0.1"])
    client = MagicMock()
    client.invoke = AsyncMock(side_effect=lambda *a, **kw: next(scores))
    reranker = LLMReranker(client=client)
    results = await reranker.rerank("query", fake_docs)

    # Doc with id="2" (originally rank=1) got score 0.9 → should be rank 0
    assert results[0].document.id == "2"
    assert results[0].original_rank == 1


# ---------------------------------------------------------------------------
# top_n truncation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_llm_reranker_top_n_truncation(fake_docs):
    """top_n=2 returns exactly 2 results."""
    scores = iter(["0.9", "0.3", "0.7"])
    client = MagicMock()
    client.invoke = AsyncMock(side_effect=lambda *a, **kw: next(scores))
    reranker = LLMReranker(client=client)
    results = await reranker.rerank("test", fake_docs, top_n=2)
    assert len(results) == 2


@pytest.mark.asyncio
async def test_llm_reranker_top_n_greater_than_docs(fake_docs):
    """top_n greater than len(documents) returns all documents."""
    scores = iter(["0.9", "0.3", "0.7"])
    client = MagicMock()
    client.invoke = AsyncMock(side_effect=lambda *a, **kw: next(scores))
    reranker = LLMReranker(client=client)
    results = await reranker.rerank("test", fake_docs, top_n=100)
    assert len(results) == 3


# ---------------------------------------------------------------------------
# Empty input
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_llm_reranker_empty_input():
    """Empty document list returns [] without LLM calls."""
    client = MagicMock()
    client.invoke = AsyncMock(return_value="0.5")
    reranker = LLMReranker(client=client)
    results = await reranker.rerank("test", [])
    assert results == []
    client.invoke.assert_not_called()


# ---------------------------------------------------------------------------
# Failure handling
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_llm_reranker_failure_returns_original_order(fake_docs):
    """When LLM raises, results are in original order with NaN scores."""
    client = MagicMock()
    client.invoke = AsyncMock(side_effect=RuntimeError("LLM down"))
    reranker = LLMReranker(client=client)
    results = await reranker.rerank("test", fake_docs)

    assert len(results) == 3
    assert all(math.isnan(r.rerank_score) for r in results)
    assert [r.original_rank for r in results] == [0, 1, 2]


@pytest.mark.asyncio
async def test_llm_reranker_parse_failure_returns_zero(fake_docs):
    """Unparseable LLM responses result in score 0.0 (not NaN)."""
    client = MagicMock()
    client.invoke = AsyncMock(return_value="not a number")
    reranker = LLMReranker(client=client)
    results = await reranker.rerank("test", fake_docs)

    assert len(results) == 3
    assert all(r.rerank_score == pytest.approx(0.0) for r in results)


@pytest.mark.asyncio
async def test_llm_reranker_score_clamping(fake_docs):
    """Scores outside [0, 1] are clamped."""
    # Return values outside [0, 1]
    scores = iter(["1.5", "-0.2", "0.8"])
    client = MagicMock()
    client.invoke = AsyncMock(side_effect=lambda *a, **kw: next(scores))
    reranker = LLMReranker(client=client)
    results = await reranker.rerank("test", fake_docs)

    score_values = sorted([r.rerank_score for r in results], reverse=True)
    assert all(0.0 <= s <= 1.0 for s in score_values)


# ---------------------------------------------------------------------------
# model_name label
# ---------------------------------------------------------------------------


def test_llm_reranker_model_name_default():
    """Default model_name label is 'llm-reranker'."""
    client = MagicMock()
    reranker = LLMReranker(client=client)
    assert reranker.model_name == "llm-reranker"


def test_llm_reranker_custom_model_name():
    """Custom model_name is stored and used in output."""
    client = MagicMock()
    reranker = LLMReranker(client=client, model_name="gpt-4-turbo")
    assert reranker.model_name == "gpt-4-turbo"
