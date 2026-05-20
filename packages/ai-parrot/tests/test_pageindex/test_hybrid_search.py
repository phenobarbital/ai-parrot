"""Tests for parrot.pageindex.hybrid_search.HybridPageIndexSearch."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot.pageindex.hybrid_search import HybridPageIndexSearch
from parrot.pageindex.schemas import TreeSearchResult


def _fixture_tree() -> dict:
    return {
        "doc_name": "demo",
        "structure": [
            {
                "title": "Billing", "node_id": "0000",
                "summary": "Invoices and payments",
                "text": "Invoices are due 30 days after issuance.",
                "nodes": [
                    {"title": "Late fees", "node_id": "0001",
                     "summary": "Penalties for late payment",
                     "text": "Late fees apply after 30 days."},
                    {"title": "Refunds", "node_id": "0002",
                     "summary": "How refunds work",
                     "text": "Refunds are processed within 7 days."},
                ],
            },
            {
                "title": "Onboarding", "node_id": "0003",
                "summary": "Welcome flow",
                "text": "Setup wizard guides new users through configuration.",
            },
            {
                "title": "Security", "node_id": "0004",
                "summary": "Auth and permissions",
                "text": "Multi-factor authentication is required.",
            },
        ],
    }


def _adapter() -> MagicMock:
    a = MagicMock()
    a.model = "heavy"
    a.client = MagicMock()
    return a


@pytest.mark.asyncio
async def test_bm25_only_returns_lexical_matches():
    engine = HybridPageIndexSearch(
        tree=_fixture_tree(), adapter=_adapter(), default_bm25_k=5,
    )
    results = await engine.search(
        "late fee payment", top_k=3, use_bm25=True, use_llm_walk=False,
    )
    assert results
    assert results[0]["source"] == "bm25"
    ids = [r["node_id"] for r in results]
    assert "0001" in ids[:2]


@pytest.mark.asyncio
async def test_llm_only_returns_walk_order(monkeypatch):
    async def fake_search(self, query):
        return TreeSearchResult(thinking="", node_list=["0002", "0001"])
    monkeypatch.setattr(
        "parrot.pageindex.hybrid_search.PageIndexRetriever.search", fake_search,
    )
    engine = HybridPageIndexSearch(tree=_fixture_tree(), adapter=_adapter())
    results = await engine.search(
        "refund", top_k=5, use_bm25=False, use_llm_walk=True,
    )
    assert [r["node_id"] for r in results] == ["0002", "0001"]
    assert results[0]["source"] == "llm"


@pytest.mark.asyncio
async def test_fused_combines_both_signals(monkeypatch):
    async def fake_search(self, query):
        return TreeSearchResult(thinking="", node_list=["0003", "0001"])
    monkeypatch.setattr(
        "parrot.pageindex.hybrid_search.PageIndexRetriever.search", fake_search,
    )
    engine = HybridPageIndexSearch(
        tree=_fixture_tree(), adapter=_adapter(), default_bm25_k=5,
    )
    results = await engine.search(
        "late fees", top_k=5, use_bm25=True, use_llm_walk=True,
    )
    assert results
    sources = {r["source"] for r in results}
    assert sources == {"fused"}
    ids = [r["node_id"] for r in results]
    # Both signals' top-ranked nodes must be present in the fused output
    assert "0003" in ids   # from LLM walk only
    assert "0001" in ids   # from BM25 (and LLM walk)


def test_rrf_formula_matches_reference():
    rankings = [["a", "b", "c"], ["b", "d"]]
    fused = HybridPageIndexSearch._rrf_fuse(rankings, k=60)
    # In list 1: a@rank0, b@rank1, c@rank2
    # In list 2: b@rank0, d@rank1
    expected_a = 1.0 / (60 + 0 + 1)
    expected_b = 1.0 / (60 + 1 + 1) + 1.0 / (60 + 0 + 1)
    expected_c = 1.0 / (60 + 2 + 1)
    expected_d = 1.0 / (60 + 1 + 1)
    scores = dict(fused)
    assert scores["a"] == pytest.approx(expected_a)
    assert scores["b"] == pytest.approx(expected_b)
    assert scores["c"] == pytest.approx(expected_c)
    assert scores["d"] == pytest.approx(expected_d)
    # b dominates (appears in both rankings)
    assert fused[0][0] == "b"


def test_mark_dirty_triggers_rebuild():
    engine = HybridPageIndexSearch(tree=_fixture_tree(), adapter=_adapter())
    engine._rebuild_bm25()
    assert engine._dirty is False
    engine.mark_dirty()
    assert engine._dirty is True


@pytest.mark.asyncio
async def test_reranker_invoked_when_requested(monkeypatch):
    async def fake_search(self, query):
        return TreeSearchResult(thinking="", node_list=["0001", "0002"])
    monkeypatch.setattr(
        "parrot.pageindex.hybrid_search.PageIndexRetriever.search", fake_search,
    )

    reranker = MagicMock()

    class _Item:
        def __init__(self, doc_id, score):
            self.id = doc_id
            self.rerank_score = score

    reranker.rerank = AsyncMock(return_value=[_Item("0002", 0.9), _Item("0001", 0.1)])
    engine = HybridPageIndexSearch(
        tree=_fixture_tree(), adapter=_adapter(), reranker=reranker,
    )
    results = await engine.search(
        "refund", top_k=2, use_bm25=False, use_llm_walk=True, rerank=True,
    )
    reranker.rerank.assert_awaited_once()
    assert [r["node_id"] for r in results] == ["0002", "0001"]
    assert results[0]["source"] == "reranked"
