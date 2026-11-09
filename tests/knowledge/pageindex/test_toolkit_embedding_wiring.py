"""Integration tests for FEAT-237 TASK-1549: NodeEmbeddingStore wiring in PageIndexToolkit.

Tests:
  - Without embedding params, no store is created (backward compat).
  - With use_vec_rank=True, embedding store is constructed.
  - _search_for passes embedding_store + flags to HybridPageIndexSearch.
  - Tree mutations via _persist propagate dirty flag to embedding store.

Import note:
    We use PageIndexToolkit via normal import since toolkit.py does not
    import from parrot.knowledge.pageindex package __init__ — it uses
    direct relative imports of submodules (content_store, hybrid_search, etc.).
    We pre-register the package stub to prevent __init__.py from loading.
"""
from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Module loading helpers (bypass heavy __init__.py)
# ---------------------------------------------------------------------------

_WT = Path(__file__).parents[3]  # <worktree root>


def _load_module(name: str, rel_path: str):
    """Load a module by file path, bypassing __init__.py chains."""
    if name in sys.modules:
        return sys.modules[name]
    full = _WT / rel_path
    spec = importlib.util.spec_from_file_location(name, str(full))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


# Pre-register stub package to avoid __init__.py execution.
if "parrot.knowledge.pageindex" not in sys.modules:
    _pkg_stub = types.ModuleType("parrot.knowledge.pageindex")
    _pkg_stub.__path__ = [  # type: ignore[attr-defined]
        str(_WT / "packages/ai-parrot/src/parrot/knowledge/pageindex")
    ]
    _pkg_stub.__package__ = "parrot.knowledge.pageindex"
    sys.modules["parrot.knowledge.pageindex"] = _pkg_stub

# Load embedding_store (no internal parrot deps)
_es_mod = _load_module(
    "parrot.knowledge.pageindex.embedding_store",
    "packages/ai-parrot/src/parrot/knowledge/pageindex/embedding_store.py",
)
NodeEmbeddingStore = _es_mod.NodeEmbeddingStore

# Load HybridPageIndexSearch via module stub
from parrot.knowledge.pageindex.hybrid_search import HybridPageIndexSearch  # noqa: E402

# Load PageIndexToolkit
from parrot.knowledge.pageindex.toolkit import PageIndexToolkit  # noqa: E402


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

    async def test_dirty_propagation_via_publish(
        self, mock_adapter, tmp_path
    ) -> None:
        """A published write drops the cached engine and its embedding view.

        Matrices are keyed by tree generation, so the engine rebuilt after the
        write reads the new generation's key and never the stale matrix.
        """
        with patch("parrot.embeddings.registry.EmbeddingRegistry"):
            toolkit = _make_toolkit(
                mock_adapter, tmp_path,
                use_vec_rank=True,
                embedding_model="test/model",
                embedding_dimension=16,
            )

        await toolkit.create_tree("my-tree", doc_name="v1")

        # Build the engine first by calling _search_for
        engine = toolkit._search_for("my-tree")
        assert toolkit._search.get("my-tree") is engine
        old_generation = engine.generation_id

        import numpy as np

        # Use a tiny embed_fn to build the matrix for the current generation
        def _tiny_embed(texts):
            return np.random.default_rng(0).standard_normal(
                (len(texts), 16)
            ).astype(np.float32)

        store = toolkit._embedding_store
        assert store is not None
        store.build_tree_matrix("my-tree", [
            {"node_id": "0001", "title": "Root", "summary": "Root"}
        ], _tiny_embed, generation_id=old_generation)
        assert store.load_tree_matrix("my-tree", generation_id=old_generation) is not None

        # Publishing a write must drop the cached engine
        async with toolkit._write("my-tree") as txn:
            txn.tree["doc_name"] = "v2"
        assert "my-tree" not in toolkit._search

        # The rebuilt engine reads the new generation, which has no matrix yet
        new_engine = toolkit._search_for("my-tree")
        assert new_engine is not engine
        assert new_engine.generation_id != old_generation
        assert store.load_tree_matrix("my-tree", generation_id=new_engine.generation_id) is None

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
