"""GraphIndexEmbedder adapter (FEAT-540 M2)."""

import inspect
from unittest.mock import AsyncMock, MagicMock

import numpy as np

from .._support.import_probe import run_import_probe


def test_old_path_is_same_class() -> None:
    from parrot.embeddings.graphindex import GraphIndexEmbedder as new
    from parrot.knowledge.graphindex.embed import GraphIndexEmbedder as old

    assert old is new


def test_adapter_satisfies_embedder() -> None:
    from parrot.embeddings.graphindex import GraphIndexEmbedder

    assert hasattr(GraphIndexEmbedder, "search_similar") and hasattr(GraphIndexEmbedder, "get_embedding")


def test_no_pgvector_dsn() -> None:
    from parrot.embeddings.graphindex import GraphIndexEmbedder

    assert "pgvector_dsn" not in inspect.signature(GraphIndexEmbedder).parameters
    assert not hasattr(GraphIndexEmbedder, "_persist_to_pgvector")


def test_old_path_import_does_not_load_adapter() -> None:
    result = run_import_probe("parrot.knowledge.graphindex.embed")
    assert result.error is None
    # faiss may already be pulled in by unrelated parrot package-root imports (parrot.memory);
    # what this module must not do is load the framework adapter (which imports faiss itself).
    assert not result.has("parrot.embeddings.graphindex")


def test_vectors_and_attach_hot_index() -> None:
    import faiss

    from parrot.embeddings.graphindex import GraphIndexEmbedder, attach_hot_index

    emb = GraphIndexEmbedder.__new__(GraphIndexEmbedder)
    emb.dimension = 4
    emb.model = MagicMock()
    emb.model.encode = AsyncMock()
    emb.index = faiss.IndexFlatL2(4)
    emb._node_id_map = []
    emb.index.add(np.eye(2, 4, dtype=np.float32))
    emb._node_id_map.extend(["a", "b"])

    vecs = emb.vectors()
    assert set(vecs) == {"a", "b"}
    assert np.allclose(vecs["b"], [0, 1, 0, 0])
    kwargs = attach_hot_index(emb)
    assert kwargs["faiss_index"] is emb.index
    assert kwargs["node_id_list"] == ["a", "b"]
