"""Tests for generation-keyed PageIndex embedding matrices."""
from __future__ import annotations

import numpy as np

from parrot.knowledge.pageindex.embedding_store import NodeEmbeddingStore


def _embed(texts: list[str]) -> np.ndarray:
    """Return a deterministic test embedding for each input text."""
    return np.ones((len(texts), 4), dtype=np.float32)


def _nodes() -> list[dict[str, str]]:
    """Return the minimum node shape accepted by the embedding store."""
    return [{"node_id": "0001", "title": "a", "summary": "b"}]


def test_matrix_path_has_generation(tmp_path):
    """Generation zero preserves the legacy path and later ones are keyed."""
    store = NodeEmbeddingStore(storage_dir=tmp_path, model_id="m", dimension=4)

    assert store._matrix_path("t").name == "t.matrix.npy"
    assert store._matrix_path("t", 3).name == "t.g3.matrix.npy"


def test_build_and_load_per_generation(tmp_path):
    """A generated matrix loads only through its matching generation key."""
    store = NodeEmbeddingStore(storage_dir=tmp_path, model_id="m", dimension=4)

    store.build_tree_matrix("t", _nodes(), _embed, generation_id=2)

    assert store.load_tree_matrix("t", generation_id=2) is not None
    assert store.load_tree_matrix("t") is None
    assert list(store._matrix_path("t", 2).parent.glob("*.npy")) == [
        store._matrix_path("t", 2)
    ]


def test_invalidate_and_prune(tmp_path):
    """Pruning preserves requested generations and invalidation removes all."""
    store = NodeEmbeddingStore(storage_dir=tmp_path, model_id="m", dimension=4)
    for generation_id in (3, 4, 5):
        store.build_tree_matrix("t", _nodes(), _embed, generation_id=generation_id)
    store.build_tree_matrix("t", _nodes(), _embed)

    assert store.prune_tree_matrices("t", keep={5}) == 4
    assert store.load_tree_matrix("t", generation_id=3) is None
    assert store.load_tree_matrix("t", generation_id=4) is None
    assert store.load_tree_matrix("t", generation_id=5) is not None
    assert store.load_tree_matrix("t") is not None

    store.invalidate_tree("t")

    assert store.load_tree_matrix("t") is None
    assert store.load_tree_matrix("t", generation_id=5) is None
