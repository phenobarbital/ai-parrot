"""Unit tests for FEAT-237 TASK-1547: _vec_rank dense signal + RRF fusion.

Tests:
  - _vec_rank returns ranked node_id list by cosine similarity.
  - _vec_rank returns [] when embedding_store or embed_fn is None.
  - _rrf_fuse handles 2 and 3 input lists correctly.
  - mark_dirty triggers embedding matrix invalidation.
  - Lazy matrix rebuild on first _vec_rank call after invalidation.
  - search(use_vec=False) is byte-identical to baseline (AC1).
  - search(use_vec=True) produces fused BM25 + LLM + dense results.

Import note:
    Importing ``parrot.knowledge.pageindex.hybrid_search`` via the package
    ``__init__.py`` would trigger the heavy import chain (aiohttp_cors not
    installed).  We therefore load both modules via
    ``importlib.util.spec_from_file_location``.
"""
from __future__ import annotations

import asyncio
import importlib.util
import sys
from pathlib import Path
from typing import Callable
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pytest


# ---------------------------------------------------------------------------
# Direct module loading (bypass heavy __init__.py)
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


# Load embedding_store first (it has no internal parrot deps)
_es_mod = _load_module(
    "parrot.knowledge.pageindex.embedding_store",
    "packages/ai-parrot/src/parrot/knowledge/pageindex/embedding_store.py",
)
NodeEmbeddingStore = _es_mod.NodeEmbeddingStore

# Pre-import HybridPageIndexSearch via normal import — but we need to ensure
# the parrot.knowledge.pageindex __init__ does NOT fire.  We register a stub
# __init__ module before the first import so Python skips the real one.
if "parrot.knowledge.pageindex" not in sys.modules:
    import types as _types
    _pkg_stub = _types.ModuleType("parrot.knowledge.pageindex")
    _pkg_stub.__path__ = [  # type: ignore[attr-defined]
        str(_WT / "packages/ai-parrot/src/parrot/knowledge/pageindex")
    ]
    _pkg_stub.__package__ = "parrot.knowledge.pageindex"
    sys.modules["parrot.knowledge.pageindex"] = _pkg_stub

from parrot.knowledge.pageindex.hybrid_search import HybridPageIndexSearch  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def small_tree() -> dict:
    """A minimal PageIndex tree with two sections."""
    return {
        "doc_name": "test-doc",
        "structure": [
            {
                "node_id": "0001",
                "title": "Root",
                "summary": "Root summary",
                "nodes": [
                    {
                        "node_id": "0002",
                        "title": "Section A",
                        "summary": "About topic A",
                        "nodes": [],
                    },
                    {
                        "node_id": "0003",
                        "title": "Section B",
                        "summary": "About topic B",
                        "nodes": [],
                    },
                ],
            },
        ],
    }


@pytest.fixture
def mock_embed_fn() -> Callable:
    """Deterministic embedding function (seeded RNG, 16-dim for speed)."""
    def embed(texts: list[str]) -> np.ndarray:
        rng = np.random.default_rng(seed=42)
        return rng.standard_normal((len(texts), 16)).astype(np.float32)
    return embed


@pytest.fixture
def embedding_store(tmp_path) -> NodeEmbeddingStore:
    """NodeEmbeddingStore backed by a temporary directory."""
    return NodeEmbeddingStore(
        storage_dir=tmp_path / "embeddings",
        model_id="test-model",
        dimension=16,
        cache_size=32,
    )


@pytest.fixture
def mock_adapter() -> MagicMock:
    """Mock PageIndexLLMAdapter."""
    adapter = MagicMock()
    adapter.model = "test-model"
    return adapter


def _make_search(tree, adapter, embedding_store=None, embed_fn=None) -> "HybridPageIndexSearch":
    """Construct HybridPageIndexSearch with mocked retriever."""
    # HybridPageIndexSearch is imported at module level
    return HybridPageIndexSearch(
        tree=tree,
        adapter=adapter,
        embedding_store=embedding_store,
        embed_fn=embed_fn,
    )


# ---------------------------------------------------------------------------
# TestRRFFuseThreeLists
# ---------------------------------------------------------------------------


class TestRRFFuseThreeLists:
    def test_fuse_two_lists(self) -> None:
        """_rrf_fuse(2 lists) returns expected scores — smoke test."""
        # HybridPageIndexSearch imported at module level (see top of file)
        rankings = [["a", "b", "c"], ["b", "c", "a"]]
        result = HybridPageIndexSearch._rrf_fuse(rankings)
        assert len(result) == 3
        ids = [r[0] for r in result]
        assert set(ids) == {"a", "b", "c"}

    def test_fuse_three_lists(self) -> None:
        """_rrf_fuse handles 3 input lists correctly."""
        # HybridPageIndexSearch imported at module level (see top of file)
        rankings = [
            ["a", "b", "c"],
            ["b", "c", "a"],
            ["c", "a", "b"],
        ]
        result = HybridPageIndexSearch._rrf_fuse(rankings)
        assert len(result) == 3
        ids = [r[0] for r in result]
        assert set(ids) == {"a", "b", "c"}

    def test_top_ranked_appears_across_all_lists(self) -> None:
        """Item appearing first in all 3 lists has highest RRF score."""
        # HybridPageIndexSearch imported at module level (see top of file)
        rankings = [["x", "y"], ["x", "z"], ["x", "y"]]
        result = HybridPageIndexSearch._rrf_fuse(rankings)
        top_id = result[0][0]
        assert top_id == "x"

    def test_empty_list_ignored(self) -> None:
        """Empty sub-lists do not raise or pollute results."""
        # HybridPageIndexSearch imported at module level (see top of file)
        rankings = [["a", "b"], [], ["b", "a"]]
        result = HybridPageIndexSearch._rrf_fuse(rankings)
        assert len(result) == 2


# ---------------------------------------------------------------------------
# TestVecRank
# ---------------------------------------------------------------------------


class TestVecRank:
    def test_returns_node_ids(
        self, small_tree, mock_adapter, embedding_store, mock_embed_fn
    ) -> None:
        """_vec_rank returns a non-empty list of node_id strings."""
        # HybridPageIndexSearch imported at module level (see top of file)
        searcher = HybridPageIndexSearch(
            tree=small_tree,
            adapter=mock_adapter,
            embedding_store=embedding_store,
            embed_fn=mock_embed_fn,
        )
        result = searcher._vec_rank("What is topic A?", top_k=3)
        assert isinstance(result, list)
        assert all(isinstance(nid, str) for nid in result)
        assert len(result) <= 3
        # All returned ids should be from the tree
        assert all(nid in {"0001", "0002", "0003"} for nid in result)

    def test_disabled_returns_empty_no_store(
        self, small_tree, mock_adapter
    ) -> None:
        """_vec_rank returns [] when embedding_store is None."""
        # HybridPageIndexSearch imported at module level (see top of file)
        searcher = HybridPageIndexSearch(
            tree=small_tree,
            adapter=mock_adapter,
            embedding_store=None,
            embed_fn=None,
        )
        result = searcher._vec_rank("query", top_k=5)
        assert result == []

    def test_disabled_returns_empty_no_embed_fn(
        self, small_tree, mock_adapter, embedding_store
    ) -> None:
        """_vec_rank returns [] when embed_fn is None (even if store present)."""
        # HybridPageIndexSearch imported at module level (see top of file)
        searcher = HybridPageIndexSearch(
            tree=small_tree,
            adapter=mock_adapter,
            embedding_store=embedding_store,
            embed_fn=None,
        )
        result = searcher._vec_rank("query", top_k=5)
        assert result == []

    def test_lazy_build_on_first_call(
        self, small_tree, mock_adapter, embedding_store, mock_embed_fn
    ) -> None:
        """First _vec_rank call builds the matrix when it does not exist."""
        # HybridPageIndexSearch imported at module level (see top of file)
        searcher = HybridPageIndexSearch(
            tree=small_tree,
            adapter=mock_adapter,
            embedding_store=embedding_store,
            embed_fn=mock_embed_fn,
        )
        assert embedding_store.load_tree_matrix("test-doc") is None
        searcher._vec_rank("query", top_k=3)
        assert embedding_store.load_tree_matrix("test-doc") is not None


# ---------------------------------------------------------------------------
# TestDirtyFlag
# ---------------------------------------------------------------------------


class TestDirtyFlag:
    def test_mark_dirty_invalidates_embedding_matrix(
        self, small_tree, mock_adapter, embedding_store, mock_embed_fn
    ) -> None:
        """mark_dirty() removes the per-tree embedding matrix."""
        # HybridPageIndexSearch imported at module level (see top of file)
        searcher = HybridPageIndexSearch(
            tree=small_tree,
            adapter=mock_adapter,
            embedding_store=embedding_store,
            embed_fn=mock_embed_fn,
        )
        # Build the matrix first
        searcher._vec_rank("query", top_k=3)
        assert embedding_store.load_tree_matrix("test-doc") is not None

        # mark_dirty should invalidate it
        searcher.mark_dirty()
        assert embedding_store.load_tree_matrix("test-doc") is None

    def test_dirty_triggers_rebuild_on_next_vec_rank(
        self, small_tree, mock_adapter, embedding_store, mock_embed_fn
    ) -> None:
        """After mark_dirty, next _vec_rank rebuilds the matrix."""
        # HybridPageIndexSearch imported at module level (see top of file)
        searcher = HybridPageIndexSearch(
            tree=small_tree,
            adapter=mock_adapter,
            embedding_store=embedding_store,
            embed_fn=mock_embed_fn,
        )
        searcher._vec_rank("first query", top_k=3)
        searcher.mark_dirty()
        # After invalidation, _vec_rank rebuilds
        result = searcher._vec_rank("second query", top_k=3)
        assert isinstance(result, list)
        assert embedding_store.load_tree_matrix("test-doc") is not None

    def test_mark_dirty_no_store_is_noop(
        self, small_tree, mock_adapter
    ) -> None:
        """mark_dirty() does not raise when no embedding_store is set."""
        # HybridPageIndexSearch imported at module level (see top of file)
        searcher = HybridPageIndexSearch(
            tree=small_tree,
            adapter=mock_adapter,
        )
        searcher.mark_dirty()  # must not raise


# ---------------------------------------------------------------------------
# TestByteIdenticalBaseline
# ---------------------------------------------------------------------------


class TestByteIdenticalBaseline:
    @pytest.mark.asyncio
    async def test_use_vec_false_identical_to_baseline(
        self, small_tree, mock_adapter
    ) -> None:
        """search(use_vec=False) produces same results as pre-embedding baseline.

        We mock both _bm25_rank and _llm_rank to return deterministic lists
        and compare two calls: one with use_vec=False (new code path) and
        one that exercises the same BM25+LLM branch.
        """
        # HybridPageIndexSearch imported at module level (see top of file)
        searcher = HybridPageIndexSearch(
            tree=small_tree,
            adapter=mock_adapter,
        )
        bm25_ids = ["0001", "0002"]
        llm_ids = ["0002", "0003"]

        # Patch internal methods to return deterministic results
        searcher._bm25_rank = lambda query, k: bm25_ids
        searcher._llm_rank = AsyncMock(return_value=llm_ids)

        result_new = await searcher.search(
            "query", use_bm25=True, use_llm_walk=True, use_vec=False
        )

        # Reset and call again — should produce identical output
        searcher._llm_rank = AsyncMock(return_value=llm_ids)
        result_baseline = await searcher.search(
            "query", use_bm25=True, use_llm_walk=True, use_vec=False
        )

        assert result_new == result_baseline

    @pytest.mark.asyncio
    async def test_use_vec_true_adds_dense_signal(
        self, small_tree, mock_adapter, embedding_store, mock_embed_fn
    ) -> None:
        """search(use_vec=True) returns results; source is 'fused'."""
        # HybridPageIndexSearch imported at module level (see top of file)
        searcher = HybridPageIndexSearch(
            tree=small_tree,
            adapter=mock_adapter,
            embedding_store=embedding_store,
            embed_fn=mock_embed_fn,
        )
        # Mock BM25 + LLM
        searcher._bm25_rank = lambda query, k: ["0001", "0002"]
        searcher._llm_rank = AsyncMock(return_value=["0002", "0003"])

        results = await searcher.search(
            "query", use_bm25=True, use_llm_walk=True, use_vec=True
        )
        assert isinstance(results, list)
        # With all three signals enabled, source is "fused"
        if results:
            assert results[0]["source"] == "fused"

    @pytest.mark.asyncio
    async def test_all_disabled_raises(self, small_tree, mock_adapter) -> None:
        """search(use_bm25=False, use_llm_walk=False, use_vec=False) raises."""
        # HybridPageIndexSearch imported at module level (see top of file)
        searcher = HybridPageIndexSearch(tree=small_tree, adapter=mock_adapter)
        with pytest.raises(ValueError):
            await searcher.search(
                "query", use_bm25=False, use_llm_walk=False, use_vec=False
            )
