"""Unit tests for GraphIndexOrigin (FEAT-379)."""
import pytest

from parrot.models import SearchOriginKind
from parrot_tools.multistoresearch.origins import GraphIndexOrigin


class FakeScoredNode:
    def __init__(self, node_id, title, combined_score, summary="s", **kw):
        self.node_id = node_id
        self.title = title
        self.summary = summary
        self.combined_score = combined_score
        self.kind = kw.get("kind", "document")
        self.hop_distance = kw.get("hop_distance", 0)
        self.is_seed = kw.get("is_seed", True)
        self.community_id = kw.get("community_id", None)
        self.source_uri = kw.get("source_uri", None)


class FakeGraphRetrievalResult:
    def __init__(self, nodes):
        self.nodes = nodes


class FakeRetriever:
    async def search(self, query, seed_top_k=10, **kw):
        return FakeGraphRetrievalResult(
            nodes=[
                FakeScoredNode("g1", "Title1", 0.9),
                FakeScoredNode("g2", "Title2", 0.5),
            ]
        )


class FakeReader:
    async def search_symbols(self, query, *, limit=20):
        return [
            {
                "node_id": "a",
                "kind": "class",
                "title": "Best",
                "source_uri": "x",
                "summary": "s",
                "score": -9.1,
                "domain_tags": {},
            },
            {
                "node_id": "b",
                "kind": "class",
                "title": "Second",
                "source_uri": "y",
                "summary": "s",
                "score": -3.2,
                "domain_tags": {},
            },
        ]


def test_fts_capability_reflects_reader():
    assert GraphIndexOrigin(retriever=object()).supports_fts is False
    assert (
        GraphIndexOrigin(retriever=object(), reader=FakeReader()).supports_fts is True
    )


async def test_fts_preserves_reader_order():
    origin = GraphIndexOrigin(retriever=object(), reader=FakeReader())
    hits = await origin.fts_search("q", k=5)
    assert [h.native_rank for h in hits] == [1, 2]
    assert "Best" in hits[0].content
    assert hits[0].score == -9.1  # raw, negative BM25 score preserved
    assert hits[1].score == -3.2


async def test_fts_search_raises_without_reader():
    origin = GraphIndexOrigin(retriever=object())
    with pytest.raises(NotImplementedError):
        await origin.fts_search("q", k=1)


async def test_search_flattens_retrieval_result():
    origin = GraphIndexOrigin(retriever=FakeRetriever())
    hits = await origin.search("q", k=10)
    assert [h.native_rank for h in hits] == [1, 2]
    assert all(h.origin_kind == SearchOriginKind.GRAPHINDEX for h in hits)
    assert hits[0].id == "g1"
    assert hits[0].score == 0.9
    assert "Title1" in hits[0].content


async def test_search_metadata_carries_graph_fields():
    origin = GraphIndexOrigin(retriever=FakeRetriever())
    hits = await origin.search("q", k=10)
    assert hits[0].metadata["node_id"] == "g1"
    assert hits[0].metadata["kind"] == "document"
    assert "hop_distance" in hits[0].metadata
    assert "is_seed" in hits[0].metadata
