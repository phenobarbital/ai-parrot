"""Integration tests for FEAT-237 TASK-1549: NodeEmbeddingStore wiring in PageIndexToolkit.

Tests:
  - Without embedding params, no store is created (backward compat).
  - With use_vec_rank=True, embedding store is constructed.
  - _search_for passes embedding_store + flags to HybridPageIndexSearch.
  - Publishing a generation prunes stale per-generation embedding matrices.

Imports ``parrot.knowledge.pageindex`` normally (FEAT-852). The old note here
claimed ``toolkit.py`` does not import the package ``__init__``; in fact
``toolkit.py:40`` imports ``.embedding_store``, which is exactly the leg that
closed the cycle once a stub package suppressed ``__init__``
(issue:91822a3b8548).
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from parrot.knowledge.pageindex.embedding_store import NodeEmbeddingStore
from parrot.knowledge.pageindex.hybrid_search import HybridPageIndexSearch
from parrot.knowledge.pageindex.toolkit import PageIndexToolkit


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_adapter():
    """Minimal mock for PageIndexLLMAdapter."""
    adapter = MagicMock()
    adapter.model = "test-model"
    adapter.client = MagicMock()
    return adapter


@pytest.fixture
def mock_store():
    """Mock JSONTreeStore."""
    store = MagicMock()
    store.exists.return_value = False
    store.list_names.return_value = []
    store._dir = None
    return store


def _make_toolkit(adapter, storage_dir, **kwargs) -> PageIndexToolkit:
    """Create toolkit with mocked internal store (no filesystem needed)."""
    return PageIndexToolkit(
        adapter=adapter,
        storage_dir=storage_dir,
        **kwargs,
    )


# ---------------------------------------------------------------------------
# TestToolkitEmbeddingWiring
# ---------------------------------------------------------------------------


class TestToolkitEmbeddingWiring:
    def test_no_embedding_by_default(self, mock_adapter, tmp_path) -> None:
        """Without embedding params, no store is created (backward compat)."""
        toolkit = _make_toolkit(mock_adapter, tmp_path)
        assert toolkit._embedding_store is None
        assert toolkit._embed_fn is None
        assert toolkit._use_vec_rank is False
        assert toolkit._use_embedding_walk is False

    def test_embedding_store_created_when_vec_rank_enabled(
        self, mock_adapter, tmp_path
    ) -> None:
        """With use_vec_rank=True, NodeEmbeddingStore is constructed."""
        with patch("parrot.embeddings.registry.EmbeddingRegistry") as mock_reg_cls:
            toolkit = _make_toolkit(
                mock_adapter, tmp_path,
                use_vec_rank=True,
                embedding_model="test/model",
                embedding_dimension=64,
            )
        assert toolkit._embedding_store is not None
        assert isinstance(toolkit._embedding_store, NodeEmbeddingStore)
        assert toolkit._embed_fn is not None
        assert toolkit._use_vec_rank is True

    def test_embedding_store_created_when_beam_walk_enabled(
        self, mock_adapter, tmp_path
    ) -> None:
        """With use_embedding_walk=True, NodeEmbeddingStore is constructed."""
        with patch("parrot.embeddings.registry.EmbeddingRegistry"):
            toolkit = _make_toolkit(
                mock_adapter, tmp_path,
                use_embedding_walk=True,
                embedding_model="test/model",
                embedding_dimension=64,
            )
        assert toolkit._embedding_store is not None
        assert toolkit._use_embedding_walk is True

    def test_search_for_passes_store_to_engine(
        self, mock_adapter, tmp_path
    ) -> None:
        """_search_for() passes embedding_store and flags to HybridPageIndexSearch."""
        with patch("parrot.embeddings.registry.EmbeddingRegistry"):
            toolkit = _make_toolkit(
                mock_adapter, tmp_path,
                use_vec_rank=True,
                embedding_model="test/model",
                embedding_dimension=64,
            )

        # Inject a mock tree directly so _load_tree works without filesystem
        tree = {"doc_name": "test-tree", "structure": []}
        toolkit._trees["test-tree"] = tree

        engine = toolkit._search_for("test-tree")
        assert isinstance(engine, HybridPageIndexSearch)
        assert engine._embedding_store is toolkit._embedding_store
        assert engine._use_vec_rank is True

    def test_search_for_no_store_when_disabled(
        self, mock_adapter, tmp_path
    ) -> None:
        """When embedding disabled, _search_for builds engine without store."""
        toolkit = _make_toolkit(mock_adapter, tmp_path)
        tree = {"doc_name": "t", "structure": []}
        toolkit._trees["t"] = tree
        engine = toolkit._search_for("t")
        assert engine._embedding_store is None

    async def test_publish_prunes_stale_generation_matrices(
        self, mock_adapter, tmp_path
    ) -> None:
        """Publishing keeps the new and base generations' matrices and prunes older ones."""
        with patch("parrot.embeddings.registry.EmbeddingRegistry"):
            toolkit = _make_toolkit(
                mock_adapter, tmp_path,
                use_vec_rank=True,
                embedding_model="test/model",
                embedding_dimension=16,
            )

        # create_tree publishes generation 1.
        await toolkit.create_tree("my-tree")
        first = (await toolkit.get_generation("my-tree"))["id"]
        assert first == 1

        # Build the engine so we can assert the publish drops the cached one.
        engine = toolkit._search_for("my-tree")
        assert toolkit._search.get("my-tree") is engine

        # Materialize a matrix for the live generation.
        import numpy as np

        def _tiny_embed(texts):
            return np.random.default_rng(0).standard_normal(
                (len(texts), 16)
            ).astype(np.float32)

        store = toolkit._embedding_store
        store.build_tree_matrix(
            "my-tree",
            [{"node_id": "0001", "title": "Root", "summary": "Root"}],
            _tiny_embed,
            generation_id=first,
        )
        assert store.load_tree_matrix("my-tree", generation_id=first) is not None

        # One publication keeps it: _after_publish keeps {new, base}.
        async with toolkit._write("my-tree"):
            pass
        assert (await toolkit.get_generation("my-tree"))["id"] == first + 1
        assert store.load_tree_matrix("my-tree", generation_id=first) is not None
        assert toolkit._search.get("my-tree") is None

        # The next publication makes generation `first` older than the base and prunes it.
        async with toolkit._write("my-tree"):
            pass
        assert (await toolkit.get_generation("my-tree"))["id"] == first + 2
        assert store.load_tree_matrix("my-tree", generation_id=first) is None

    def test_embedding_store_dimension_parameter(
        self, mock_adapter, tmp_path
    ) -> None:
        """embedding_dimension is forwarded to NodeEmbeddingStore."""
        with patch("parrot.embeddings.registry.EmbeddingRegistry"):
            toolkit = _make_toolkit(
                mock_adapter, tmp_path,
                use_vec_rank=True,
                embedding_model="test/model",
                embedding_dimension=512,
            )
        assert toolkit._embedding_store._dimension == 512
