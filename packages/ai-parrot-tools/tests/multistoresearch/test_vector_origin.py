"""Unit tests for VectorStoreOrigin (FEAT-379)."""
import pytest

from parrot.models import SearchOriginKind
from parrot.models.stores import SearchResult
from parrot_tools.multistoresearch.origins import VectorStoreOrigin


class FakeStore:
    async def similarity_search(self, query, limit=10):
        return [
            SearchResult(id=str(i), content=f"doc {i}", metadata={}, score=0.1 * i)
            for i in range(3)
        ]


class FakeArango(FakeStore):
    async def fulltext_search(self, query, limit=10):
        return [SearchResult(id="f1", content="fts doc", metadata={}, score=1.0)]


async def test_search_normalizes_to_origin_hits():
    origin = VectorStoreOrigin(store=FakeStore(), name="pgvector")
    hits = await origin.search("q", k=3)
    assert [h.native_rank for h in hits] == [1, 2, 3]
    assert all(
        h.origin == "pgvector" and h.origin_kind == SearchOriginKind.VECTOR
        for h in hits
    )


def test_fts_capability_detection():
    assert VectorStoreOrigin(store=FakeArango(), name="arango").supports_fts is True
    assert VectorStoreOrigin(store=FakeStore(), name="faiss").supports_fts is False


async def test_fts_search_on_arango():
    origin = VectorStoreOrigin(store=FakeArango(), name="arango")
    hits = await origin.fts_search("q", k=1)
    assert len(hits) == 1
    assert hits[0].origin == "arango"
    assert hits[0].native_rank == 1


async def test_fts_search_raises_when_unsupported():
    origin = VectorStoreOrigin(store=FakeStore(), name="faiss")
    with pytest.raises(NotImplementedError):
        await origin.fts_search("q", k=1)


async def test_backend_error_propagates():
    class Boom:
        async def similarity_search(self, query, limit=10):
            raise RuntimeError("db down")

    with pytest.raises(RuntimeError):
        await VectorStoreOrigin(store=Boom(), name="pgvector").search("q", k=1)


def test_default_description_and_timeout():
    origin = VectorStoreOrigin(store=FakeStore(), name="pgvector")
    assert "pgvector" in origin.description
    assert origin.timeout is None


def test_custom_description_and_timeout():
    origin = VectorStoreOrigin(
        store=FakeStore(), name="pgvector", description="custom", timeout=5.0
    )
    assert origin.description == "custom"
    assert origin.timeout == 5.0
