"""Real FTS, fusion, filter and freshness tests (FEAT-542, AC5/AC6/AC7)."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

pytest.importorskip("lancedb", reason="requires ai-parrot-embeddings[lancedb]")

sys.path.insert(0, str(Path(__file__).parent))
from lancedb_fixtures import DeterministicEmbedding  # noqa: E402

from parrot.stores.lancedb import LanceDBStore  # noqa: E402
from parrot.stores.lancedb_models import LanceDBHybridHit  # noqa: E402
from parrot.stores.models import Document  # noqa: E402


class _RaisingProvider:
    async def embed_documents(self, texts):  # pragma: no cover — must never be called
        raise AssertionError("FTS must never construct/invoke an embedding provider")

    async def embed_query(self, text):  # pragma: no cover — must never be called
        raise AssertionError("FTS must never construct/invoke an embedding provider")


def _make_store(uri, **kwargs) -> LanceDBStore:
    kwargs.setdefault("dimension", 8)
    kwargs.setdefault("embedding_id", "fixed-id")
    kwargs.setdefault("collection_name", "t")
    store = LanceDBStore(uri=str(uri), **kwargs)
    store._embedding_callable_input = DeterministicEmbedding()
    return store


async def _seed(store: LanceDBStore, docs: list[Document]) -> None:
    await store.from_documents(docs, collection="t")


class TestModelFreeLexicalPath:
    async def test_fts_never_constructs_or_invokes_a_provider(self, tmp_path):
        store = _make_store(tmp_path / "col")
        await _seed(store, [Document(page_content="cats are great", metadata={"id": "a"})])
        store._embedding_callable_input = _RaisingProvider()
        store._embedding_provider = None  # force a fresh (raising-if-touched) lookup
        results = await store.fulltext_search("cats")
        assert len(results) == 1

    async def test_fts_works_on_a_reopen_with_no_provider_configured(self, tmp_path):
        uri = tmp_path / "col"
        store = _make_store(uri)
        await _seed(store, [Document(page_content="cats are great", metadata={"id": "a"})])
        await store.disconnect()

        # Fresh store instance, reopened with NO embedding configuration at all.
        reopened = LanceDBStore(uri=str(uri), dimension=8, collection_name="t")
        results = await reopened.fulltext_search("cats")
        assert len(results) == 1
        assert reopened._embedding_provider is None


class TestScores:
    async def test_fts_scores_are_bm25_higher_is_better(self, tmp_path):
        store = _make_store(tmp_path / "col")
        await _seed(
            store,
            [
                Document(page_content="cats cats cats are wonderful", metadata={"id": "a"}),
                Document(page_content="dogs are also nice", metadata={"id": "b"}),
            ],
        )
        results = await store.fulltext_search("cats")
        assert len(results) == 1
        assert results[0].metadata["_lancedb"]["score_kind"] == "bm25"
        assert results[0].metadata["_lancedb"]["higher_is_better"] is True
        assert results[0].score > 0
        assert results[0].distance == results[0].score  # documented legacy alias, not a distance

    async def test_hybrid_returns_hybrid_hits_without_a_distance_alias(self, tmp_path):
        store = _make_store(tmp_path / "col")
        await _seed(store, [Document(page_content="cats are great", metadata={"id": "a"})])
        results = await store.hybrid_search("cats")
        assert len(results) == 1
        assert isinstance(results[0], LanceDBHybridHit)
        assert not hasattr(results[0], "distance")
        assert results[0].score_kind == "rrf"
        assert results[0].higher_is_better is True

    async def test_hybrid_retains_sdk_rrf_order(self, tmp_path):
        store = _make_store(tmp_path / "col")
        await _seed(
            store,
            [
                Document(page_content="cats are great and wonderful", metadata={"id": "a"}),
                Document(page_content="dogs bark", metadata={"id": "b"}),
                Document(page_content="cats meow softly", metadata={"id": "c"}),
            ],
        )
        results = await store.hybrid_search("cats", limit=3)
        ranks = [r.metadata["_lancedb"]["native_rank"] for r in results]
        assert ranks == sorted(ranks)  # 1-based, ascending, not re-sorted
        scores = [r.score for r in results]
        assert scores == sorted(scores, reverse=True)  # higher relevance first


class TestRetrievalMatrix:
    async def test_lexical_only_identifier_and_semantic_only_neighbour_both_eligible(self, tmp_path):
        store = _make_store(tmp_path / "col")
        await _seed(
            store,
            [
                Document(page_content="Internal reference token ZXQ731 identifies this case", metadata={"id": "lexical"}),
                Document(page_content="A dedicated case identifier is assigned when escalated", metadata={"id": "semantic"}),
                Document(page_content="unrelated filler about the weather today", metadata={"id": "noise"}),
            ],
        )
        fts_results = await store.fulltext_search("ZXQ731")
        assert {r.metadata["_lancedb"]["record_id"] for r in fts_results} == {"lexical"}

        hybrid_results = await store.hybrid_search("ZXQ731 case identifier", limit=3)
        ids = {r.metadata["_lancedb"]["record_id"] for r in hybrid_results}
        assert "lexical" in ids or "semantic" in ids

    async def test_one_prefilter_applies_to_both_hybrid_legs(self, tmp_path):
        store = _make_store(tmp_path / "col")
        await _seed(
            store,
            [
                Document(page_content="cats are great", metadata={"id": "a", "source": "x"}),
                Document(page_content="cats are wonderful too", metadata={"id": "b", "source": "y"}),
            ],
        )
        results = await store.hybrid_search("cats", metadata_filters={"source": "x"}, limit=5)
        assert {r.metadata["_lancedb"]["record_id"] for r in results} == {"a"}

        fts_results = await store.fulltext_search("cats", metadata_filters={"source": "x"}, limit=5)
        assert {r.metadata["_lancedb"]["record_id"] for r in fts_results} == {"a"}

    async def test_excluded_parents_respected_in_fts_and_hybrid(self, tmp_path):
        store = _make_store(tmp_path / "col")
        await _seed(
            store,
            [
                Document(
                    page_content="cats parent document",
                    metadata={"id": "parent", "document_type": "parent", "is_full_document": True},
                ),
                Document(page_content="cats child document", metadata={"id": "child"}),
            ],
        )
        fts_results = await store.fulltext_search("cats", limit=5)
        assert {r.metadata["_lancedb"]["record_id"] for r in fts_results} == {"child"}

        hybrid_results = await store.hybrid_search("cats", limit=5)
        assert {r.metadata["_lancedb"]["record_id"] for r in hybrid_results} == {"child"}

    async def test_rows_added_after_index_creation_are_visible(self, tmp_path):
        store = _make_store(tmp_path / "col")
        await store.create_collection("t")  # creates the FTS index with no rows yet
        await store.add_documents([Document(page_content="cats are great", metadata={"id": "a"})], collection="t")
        results = await store.fulltext_search("cats")
        assert len(results) == 1

        # Upsert and delete visibility, no manual maintenance.
        await store.add_documents([Document(page_content="cats are amazing", metadata={"id": "a"})], collection="t")
        results2 = await store.fulltext_search("amazing")
        assert len(results2) == 1
        n = await store.delete_documents(pk="id", values=["a"], collection="t")
        assert n == 1
        results3 = await store.fulltext_search("cats")
        assert results3 == []


class TestFailure:
    async def test_failing_hybrid_leg_raises_and_never_falls_back(self, tmp_path):
        store = _make_store(tmp_path / "col")
        await _seed(store, [Document(page_content="cats are great", metadata={"id": "a"})])
        store._embedding_callable_input = _RaisingProvider()
        store._embedding_provider = None
        with pytest.raises(AssertionError):
            await store.hybrid_search("cats")

    async def test_missing_collection_raises_for_fts_and_hybrid(self, tmp_path):
        store = _make_store(tmp_path / "col")
        with pytest.raises(LookupError):
            await store.fulltext_search("cats", collection="never-created")
        with pytest.raises(LookupError):
            await store.hybrid_search("cats", collection="never-created")
