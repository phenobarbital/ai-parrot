"""Vector contracts and tool-argument compatibility (FEAT-542, AC5)."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

pytest.importorskip("lancedb", reason="requires ai-parrot-embeddings[lancedb]")

sys.path.insert(0, str(Path(__file__).parent))
from lancedb_fixtures import DeterministicEmbedding  # noqa: E402

from parrot.stores.lancedb import LanceDBStore  # noqa: E402
from parrot.stores.models import Document  # noqa: E402


def _make_store(uri, **kwargs) -> LanceDBStore:
    kwargs.setdefault("dimension", 4)
    kwargs.setdefault("embedding_id", "fixed-id")
    kwargs.setdefault("collection_name", "t")
    store = LanceDBStore(uri=str(uri), **kwargs)
    store._embedding_callable_input = DeterministicEmbedding()
    return store


class _FixedVectorEmbedding:
    """Deterministic provider with explicit, hand-picked query/document vectors."""

    def __init__(self, vectors: dict[str, list[float]]):
        self._vectors = vectors
        self.embed_query_calls = 0

    async def embed_documents(self, texts):
        return [self._vectors[t] for t in texts]

    async def embed_query(self, text):
        self.embed_query_calls += 1
        return self._vectors[text]


async def _seed(store: LanceDBStore, docs: list[Document]) -> None:
    await store.from_documents(docs, collection="t")


class TestValidation:
    @pytest.mark.parametrize("limit", [0, -1, True, 1.5])
    async def test_invalid_limits_raise(self, tmp_path, limit):
        store = _make_store(tmp_path / "col")
        with pytest.raises(ValueError):
            await store.similarity_search("hello", limit=limit)

    async def test_blank_query_returns_empty_without_embedding(self, tmp_path):
        vectors = {"a": [1.0, 0.0, 0.0, 0.0]}
        store = _make_store(tmp_path / "col")
        store._embedding_callable_input = _FixedVectorEmbedding(vectors)
        result = await store.similarity_search("   ")
        assert result == []
        assert store._embedding_callable_input.embed_query_calls == 0

    async def test_unsupported_search_strategy_rejected(self, tmp_path):
        store = _make_store(tmp_path / "col")
        with pytest.raises(ValueError):
            await store.similarity_search("hello", search_strategy="mmr")

    async def test_custom_column_kwargs_rejected(self, tmp_path):
        store = _make_store(tmp_path / "col")
        with pytest.raises(ValueError):
            await store.similarity_search("hello", content_column="text")

    async def test_unknown_kwargs_rejected(self, tmp_path):
        store = _make_store(tmp_path / "col")
        with pytest.raises(ValueError):
            await store.similarity_search("hello", totally_unknown=True)


class TestScores:
    async def test_score_is_raw_cosine_distance_lower_is_better(self, tmp_path):
        vectors = {
            "same": [1.0, 0.0, 0.0, 0.0],
            "orthogonal": [0.0, 1.0, 0.0, 0.0],
            "opposite": [-1.0, 0.0, 0.0, 0.0],
            "query": [1.0, 0.0, 0.0, 0.0],
        }
        store = _make_store(tmp_path / "col")
        store._embedding_callable_input = _FixedVectorEmbedding(vectors)
        await _seed(
            store,
            [
                Document(page_content="same", metadata={"id": "same"}),
                Document(page_content="orthogonal", metadata={"id": "orthogonal"}),
                Document(page_content="opposite", metadata={"id": "opposite"}),
            ],
        )
        results = await store.similarity_search("query", limit=3)
        by_id = {r.metadata["_lancedb"]["record_id"]: r.score for r in results}
        assert by_id["same"] == pytest.approx(0.0, abs=1e-5)
        assert by_id["orthogonal"] == pytest.approx(1.0, abs=1e-5)
        assert by_id["opposite"] == pytest.approx(2.0, abs=1e-5)
        # lower is better: same < orthogonal < opposite
        assert by_id["same"] < by_id["orthogonal"] < by_id["opposite"]

    async def test_distance_alias_is_unchanged(self, tmp_path):
        vectors = {"a": [1.0, 0.0, 0.0, 0.0], "query": [1.0, 0.0, 0.0, 0.0]}
        store = _make_store(tmp_path / "col")
        store._embedding_callable_input = _FixedVectorEmbedding(vectors)
        await _seed(store, [Document(page_content="a", metadata={"id": "a"})])
        results = await store.similarity_search("query", limit=1)
        assert results[0].distance == results[0].score

    async def test_result_id_is_namespaced_and_provenance_present(self, tmp_path):
        vectors = {"a": [1.0, 0.0, 0.0, 0.0], "query": [1.0, 0.0, 0.0, 0.0]}
        store = _make_store(tmp_path / "col")
        store._embedding_callable_input = _FixedVectorEmbedding(vectors)
        await _seed(store, [Document(page_content="a", metadata={"id": "a"})])
        results = await store.similarity_search("query", limit=1)
        assert results[0].id.startswith("lancedb:")
        assert results[0].metadata["_lancedb"]["mode"] == "vector"
        assert results[0].metadata["_lancedb"]["score_kind"] == "cosine_distance"
        assert results[0].metadata["_lancedb"]["higher_is_better"] is False


class TestThresholds:
    @pytest.mark.parametrize(
        "similarity,score_threshold,expected_ceiling",
        [
            (0.0, None, None),  # both disabled
            (0.3, None, pytest.approx(0.7)),  # base only
            (0.0, 0.4, pytest.approx(0.6)),  # tool only, including 0 is NOT the sentinel
            (0.0, 0.0, pytest.approx(1.0)),  # tool score_threshold=0 IS a real constraint
            (0.3, 0.5, pytest.approx(0.5)),  # stricter (score_threshold=0.5 -> ceiling 0.5) wins
            (0.9, 0.1, pytest.approx(0.1)),  # stricter (similarity=0.9 -> ceiling 0.1) wins
        ],
    )
    def test_distance_ceiling_rules(self, tmp_path, similarity, score_threshold, expected_ceiling):
        store = _make_store(tmp_path / "col")
        ceiling = store._distance_ceiling(similarity, score_threshold)
        if expected_ceiling is None:
            assert ceiling is None
        else:
            assert ceiling == expected_ceiling

    def test_out_of_range_similarity_threshold_raises(self, tmp_path):
        store = _make_store(tmp_path / "col")
        with pytest.raises(ValueError):
            store._distance_ceiling(1.5, None)
        with pytest.raises(ValueError):
            store._distance_ceiling(-0.1, None)

    def test_out_of_range_score_threshold_raises(self, tmp_path):
        store = _make_store(tmp_path / "col")
        with pytest.raises(ValueError):
            store._distance_ceiling(0.0, 1.5)
        with pytest.raises(ValueError):
            store._distance_ceiling(0.0, -0.1)


class TestFilters:
    async def test_excluded_parents_do_not_consume_the_candidate_budget(self, tmp_path):
        vectors = {
            "parent": [1.0, 0.0, 0.0, 0.0],
            "child1": [0.99, 0.01, 0.0, 0.0],
            "child2": [0.98, 0.02, 0.0, 0.0],
            "query": [1.0, 0.0, 0.0, 0.0],
        }
        store = _make_store(tmp_path / "col")
        store._embedding_callable_input = _FixedVectorEmbedding(vectors)
        await _seed(
            store,
            [
                Document(
                    page_content="parent",
                    metadata={"id": "parent", "document_type": "parent", "is_full_document": True},
                ),
                Document(page_content="child1", metadata={"id": "child1"}),
                Document(page_content="child2", metadata={"id": "child2"}),
            ],
        )
        # limit=2: even though "parent" is the closest neighbor, it must be
        # excluded BEFORE the limit is applied, so both children still fit.
        results = await store.similarity_search("query", limit=2)
        ids = {r.metadata["_lancedb"]["record_id"] for r in results}
        assert ids == {"child1", "child2"}

    async def test_empty_collection_returns_empty_and_missing_raises(self, tmp_path):
        store = _make_store(tmp_path / "col")
        await store.create_collection("t")
        vectors = {"query": [1.0, 0.0, 0.0, 0.0]}
        store._embedding_callable_input = _FixedVectorEmbedding(vectors)
        results = await store.similarity_search("query", limit=5)
        assert results == []

        with pytest.raises(LookupError):
            await store.similarity_search("query", limit=5, collection="never-created")


class TestUnsupported:
    async def test_mmr_search_raises_notimplementederror(self, tmp_path):
        store = _make_store(tmp_path / "col")
        with pytest.raises(NotImplementedError, match="exact cosine search"):
            await store.mmr_search()


class TestConcreteStore:
    def test_no_remaining_abstract_methods(self, tmp_path):
        import inspect

        store = _make_store(tmp_path / "col")
        assert not inspect.isabstract(type(store))
        assert isinstance(store, LanceDBStore)
