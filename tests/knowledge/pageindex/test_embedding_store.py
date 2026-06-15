"""Unit tests for FEAT-237: NodeEmbeddingStore (TASK-1546).

Covers:
  - content_key determinism and sensitivity.
  - build_tree_matrix shape, caching, and batch-embedding only misses.
  - load_tree_matrix returns mmap'd matrix.
  - invalidate_tree removes per-tree matrix but preserves global tier.
  - LRU eviction (basic).

Import note:
    ``parrot.knowledge.pageindex.__init__.py`` imports ``PageIndexLoader``,
    which transitively imports ``aiohttp_cors`` (not installed in CI).
    We therefore load ``embedding_store`` directly via
    ``importlib.util.spec_from_file_location`` to bypass the package
    ``__init__.py`` entirely.
"""
import importlib.util
import json
import sys
import pytest
import numpy as np
from pathlib import Path


def _load_embedding_store_module():
    """Load parrot.knowledge.pageindex.embedding_store bypassing __init__.py.

    The ``parrot.knowledge.pageindex`` package ``__init__.py`` triggers a deep
    import chain that ends in ``aiohttp_cors`` (not installed).  Loading the
    module file directly avoids that chain.

    Returns:
        The ``embedding_store`` module object.
    """
    module_name = "parrot.knowledge.pageindex.embedding_store"
    if module_name in sys.modules:
        return sys.modules[module_name]
    _file = (
        Path(__file__).parents[3]
        / "packages/ai-parrot/src/parrot/knowledge/pageindex/embedding_store.py"
    )
    spec = importlib.util.spec_from_file_location(module_name, str(_file))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = mod
    spec.loader.exec_module(mod)
    return mod


_es_mod = _load_embedding_store_module()
NodeEmbeddingStore = _es_mod.NodeEmbeddingStore


# ---- Fixtures ---------------------------------------------------------


@pytest.fixture
def store(tmp_path: Path):
    """NodeEmbeddingStore instance backed by a temporary directory."""
    return NodeEmbeddingStore(
        storage_dir=tmp_path / "embeddings",
        model_id="test-model",
        dimension=256,
        cache_size=10,
    )


@pytest.fixture
def mock_embed_fn():
    """Deterministic embedding function for unit tests (seeded RNG)."""
    def embed(texts: list[str]) -> np.ndarray:
        rng = np.random.default_rng(seed=42)
        return rng.standard_normal((len(texts), 256)).astype(np.float32)
    return embed


@pytest.fixture
def two_nodes() -> list[dict]:
    return [
        {"node_id": "0001", "title": "Root", "summary": "Root summary"},
        {"node_id": "0002", "title": "Child", "summary": "Child summary"},
    ]


# ---- TestContentKey ---------------------------------------------------


class TestContentKey:
    def test_deterministic(self, store) -> None:
        """Same inputs produce the same SHA-1 hash."""
        k1 = store.content_key("model", "title", "summary")
        k2 = store.content_key("model", "title", "summary")
        assert k1 == k2

    def test_varies_on_model(self, store) -> None:
        """Different model_id changes the hash."""
        k1 = store.content_key("model-a", "title", "summary")
        k2 = store.content_key("model-b", "title", "summary")
        assert k1 != k2

    def test_varies_on_title(self, store) -> None:
        """Different title changes the hash."""
        k1 = store.content_key("model", "title-a", "summary")
        k2 = store.content_key("model", "title-b", "summary")
        assert k1 != k2

    def test_varies_on_summary(self, store) -> None:
        """Different summary changes the hash."""
        k1 = store.content_key("model", "title", "summary-a")
        k2 = store.content_key("model", "title", "summary-b")
        assert k1 != k2

    def test_separator_prevents_collision(self, store) -> None:
        """'ab'+'c' and 'a'+'bc' produce different hashes (null byte separator)."""
        k1 = store.content_key("m", "ab", "c")
        k2 = store.content_key("m", "a", "bc")
        assert k1 != k2

    def test_returns_40_char_hex(self, store) -> None:
        """SHA-1 hex digest is exactly 40 characters."""
        k = store.content_key("model", "title", "summary")
        assert len(k) == 40
        assert all(c in "0123456789abcdef" for c in k)


# ---- TestBuildTreeMatrix ---------------------------------------------


class TestBuildTreeMatrix:
    def test_shape(self, store, mock_embed_fn, two_nodes) -> None:
        """Matrix has shape (N, d) where N = len(nodes), d = 256."""
        matrix, order = store.build_tree_matrix("test-tree", two_nodes, mock_embed_fn)
        assert matrix.shape == (2, 256)
        assert len(order) == 2

    def test_node_id_order_matches(self, store, mock_embed_fn, two_nodes) -> None:
        """Returned node_id_order matches the input node order."""
        _, order = store.build_tree_matrix("test-tree", two_nodes, mock_embed_fn)
        assert order == ["0001", "0002"]

    def test_matrix_is_contiguous_float32(self, store, mock_embed_fn, two_nodes) -> None:
        """Matrix is C-contiguous float32."""
        matrix, _ = store.build_tree_matrix("test-tree", two_nodes, mock_embed_fn)
        assert matrix.dtype == np.float32
        assert matrix.flags["C_CONTIGUOUS"]

    def test_cache_hit_skips_embed(self, store, mock_embed_fn, two_nodes) -> None:
        """Nodes already cached are NOT passed to embed_fn on second build."""
        store.build_tree_matrix("tree1", two_nodes, mock_embed_fn)

        call_count = [0]

        def counting_embed(texts: list[str]) -> np.ndarray:
            call_count[0] += len(texts)
            return mock_embed_fn(texts)

        store.build_tree_matrix("tree2", two_nodes, counting_embed)
        assert call_count[0] == 0, (
            f"Expected 0 embeddings called (all cached), got {call_count[0]}"
        )

    def test_empty_nodes_raises(self, store, mock_embed_fn) -> None:
        """Empty node list raises ValueError."""
        with pytest.raises(ValueError):
            store.build_tree_matrix("test-tree", [], mock_embed_fn)

    def test_matrix_persisted_to_disk(self, store, mock_embed_fn, two_nodes, tmp_path) -> None:
        """build_tree_matrix writes .npy and .json files to disk."""
        store.build_tree_matrix("test-tree", two_nodes, mock_embed_fn)
        matrix_path = tmp_path / "embeddings" / "test-tree" / "embeddings" / "test-tree.matrix.npy"
        order_path = tmp_path / "embeddings" / "test-tree" / "embeddings" / "test-tree.node_order.json"
        assert matrix_path.exists(), "Matrix .npy file should exist"
        assert order_path.exists(), "Node order .json file should exist"


# ---- TestLoadTreeMatrix ----------------------------------------------


class TestLoadTreeMatrix:
    def test_load_after_build(self, store, mock_embed_fn, two_nodes) -> None:
        """load_tree_matrix returns a matrix with the same shape as built."""
        store.build_tree_matrix("test-tree", two_nodes, mock_embed_fn)
        result = store.load_tree_matrix("test-tree")
        assert result is not None
        matrix, order = result
        assert matrix.shape == (2, 256)
        assert len(order) == 2

    def test_load_nonexistent_returns_none(self, store) -> None:
        """load_tree_matrix returns None for a tree that was never built."""
        result = store.load_tree_matrix("nonexistent")
        assert result is None

    def test_load_is_mmap(self, store, mock_embed_fn, two_nodes) -> None:
        """load_tree_matrix uses mmap mode (matrix is read-only)."""
        store.build_tree_matrix("test-tree", two_nodes, mock_embed_fn)
        result = store.load_tree_matrix("test-tree")
        assert result is not None
        matrix, _ = result
        # mmap arrays are not writeable by default in r mode
        assert not matrix.flags["WRITEABLE"]


# ---- TestInvalidateTree ----------------------------------------------


class TestInvalidateTree:
    def test_invalidate_removes_matrix(self, store, mock_embed_fn, two_nodes) -> None:
        """invalidate_tree makes load_tree_matrix return None."""
        store.build_tree_matrix("test-tree", two_nodes, mock_embed_fn)
        store.invalidate_tree("test-tree")
        assert store.load_tree_matrix("test-tree") is None

    def test_invalidate_preserves_global_cache(
        self, store, mock_embed_fn, two_nodes
    ) -> None:
        """Global cache entries survive per-tree invalidation."""
        store.build_tree_matrix("test-tree", two_nodes, mock_embed_fn)
        store.invalidate_tree("test-tree")

        # Rebuilding should not call embed_fn for nodes already in global cache.
        call_count = [0]

        def counting_embed(texts: list[str]) -> np.ndarray:
            call_count[0] += len(texts)
            return mock_embed_fn(texts)

        store.build_tree_matrix("test-tree", two_nodes, counting_embed)
        assert call_count[0] == 0, (
            "Global cache should still have entries after per-tree invalidation"
        )

    def test_invalidate_nonexistent_is_noop(self, store) -> None:
        """invalidate_tree on a tree that was never built does not raise."""
        store.invalidate_tree("ghost-tree")  # must not raise


# ---- TestGetOrEmbed --------------------------------------------------


class TestGetOrEmbed:
    def test_returns_none_before_build(self, store) -> None:
        """get_or_embed returns None if the node was never embedded."""
        result = store.get_or_embed("tree", "0001", "Title", "Summary")
        assert result is None

    def test_returns_vector_after_build(self, store, mock_embed_fn) -> None:
        """get_or_embed returns the cached vector after build_tree_matrix."""
        nodes = [{"node_id": "0001", "title": "Title", "summary": "Summary"}]
        store.build_tree_matrix("tree", nodes, mock_embed_fn)
        result = store.get_or_embed("tree", "0001", "Title", "Summary")
        assert result is not None
        assert result.shape == (256,)
