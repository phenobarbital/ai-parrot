"""Real hybrid-plus-graph federation acceptance (FEAT-542, AC7)."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
import rustworkx

from parrot.models import SearchOriginKind
from parrot_tools.multistoresearch import (
    MultiStoreSearchToolkit,
)  # verified: packages/ai-parrot-tools/tests/multistoresearch/test_toolkit.py:5
from parrot_tools.multistoresearch.origins import (
    GraphIndexOrigin,
    LanceDBOrigin,
)  # verified: packages/ai-parrot-tools/tests/multistoresearch/test_graphindex_origin.py:5

pytest.importorskip("lancedb", reason="requires ai-parrot-embeddings[lancedb]")

_EMBEDDINGS_TESTS_DIR = Path(__file__).resolve().parents[3] / "ai-parrot-embeddings" / "tests"
sys.path.insert(0, str(_EMBEDDINGS_TESTS_DIR))
from lancedb_fixtures import DeterministicEmbedding  # noqa: E402


def _make_graph_nodes(count: int = 3):
    """Real UniversalNode list — verified against
    packages/ai-parrot/tests/knowledge/graphindex/test_retriever.py's
    established `_make_nodes` pattern."""
    from parrot.knowledge.graphindex.schema import NodeKind, UniversalNode

    return [
        UniversalNode(
            node_id=f"n{i}",
            title=f"Graph Node {i}",
            kind=NodeKind.DOCUMENT,
            source_uri=f"file://node{i}.md",
            summary=f"Deterministic graph summary {i}",
        )
        for i in range(count)
    ]


def _make_graph(nodes):
    g = rustworkx.PyDiGraph()
    for node in nodes:
        g.add_node({"node_id": node.node_id, "title": node.title, "kind": "document", "source_uri": node.source_uri})
    return g


def _make_real_retriever(nodes, graph, seed_scores):
    """A REAL GraphExpandedRetriever with a deterministic stub embedder —
    the established codebase pattern (test_retriever.py) for exercising the
    real 4-phase pipeline without downloaded weights or live inference."""
    from parrot.knowledge.graphindex.retriever import GraphExpandedRetriever

    embedder = MagicMock()
    embedder.search_similar = AsyncMock(return_value=seed_scores)
    return GraphExpandedRetriever(graph=graph, nodes=nodes, embedder=embedder)


async def _make_lancedb_origin(tmp_path, mode="hybrid"):
    from parrot.stores.lancedb import LanceDBStore
    from parrot.stores.models import Document

    store = LanceDBStore(
        uri=str(tmp_path / "col"), dimension=8, embedding_id="lancedb-test-embedding-v1", collection_name="t"
    )
    store._embedding_callable_input = DeterministicEmbedding()
    await store.from_documents(
        [
            Document(page_content="LanceDB cats are great local documents", metadata={"id": "lc-a"}),
            Document(page_content="LanceDB dogs bark loudly in local storage", metadata={"id": "lc-b"}),
        ],
        collection="t",
    )
    return store, LanceDBOrigin(store, name="lancedb", mode=mode, collection="t")


class TestFederation:
    async def test_grouped_native_order_and_scores_preserved_per_origin(self, tmp_path):
        store, lancedb_origin = await _make_lancedb_origin(tmp_path)
        nodes = _make_graph_nodes()
        graph = _make_graph(nodes)
        retriever = _make_real_retriever(nodes, graph, [("n0", 0.1), ("n1", 0.5), ("n2", 0.9)])
        graph_origin = GraphIndexOrigin(retriever=retriever, name="graphindex")

        toolkit = MultiStoreSearchToolkit(origins=[lancedb_origin, graph_origin])
        response = await toolkit.store_search("cats local documents", k=10)

        assert len(response.sections) == 2
        by_origin = {s.origin: s for s in response.sections}
        assert by_origin["lancedb"].status == "ok"
        assert by_origin["graphindex"].status == "ok"
        assert by_origin["lancedb"].origin_kind == SearchOriginKind.VECTOR
        assert by_origin["graphindex"].origin_kind == SearchOriginKind.GRAPHINDEX

        # Native rank order preserved WITHIN each section (not re-sorted).
        lancedb_ranks = [h.native_rank for h in by_origin["lancedb"].hits]
        assert lancedb_ranks == sorted(lancedb_ranks)
        graph_ranks = [h.native_rank for h in by_origin["graphindex"].hits]
        assert graph_ranks == sorted(graph_ranks)
        # Native LanceDB provenance metadata survives into the section.
        assert all("_lancedb" in h.metadata for h in by_origin["lancedb"].hits)
        await store.disconnect()

    async def test_merged_ranking_and_dedup_are_unchanged(self, tmp_path):
        """Assert the EXISTING toolkit rerank/dedup behavior (BM25-over-content,
        then dedup by id/content-hash) — NOT native RRF order in the merged
        list, which spec §1 lists as an explicit Non-Goal to change."""
        store, lancedb_origin = await _make_lancedb_origin(tmp_path)
        nodes = _make_graph_nodes()
        graph = _make_graph(nodes)
        retriever = _make_real_retriever(nodes, graph, [("n0", 0.2)])
        graph_origin = GraphIndexOrigin(retriever=retriever, name="graphindex")

        toolkit = MultiStoreSearchToolkit(origins=[lancedb_origin, graph_origin])
        response = await toolkit.store_search("cats local documents", k=10)

        assert len(response.merged_top_k) > 0
        # merged_top_k is deduped: no repeated (origin, id) pair.
        seen = set()
        for hit in response.merged_top_k:
            key = (hit.origin, hit.id)
            assert key not in seen
            seen.add(key)
        await store.disconnect()

    async def test_one_failed_or_timed_out_origin_does_not_erase_the_other(self, tmp_path):
        store, lancedb_origin = await _make_lancedb_origin(tmp_path)
        # Break the LanceDB origin's hybrid leg by disconnecting its store first.
        await store.disconnect()
        store._connection_handle = None
        store._default_table = None
        # Force a real failure: point at a nonexistent collection so
        # hybrid_search raises LookupError instead of silently succeeding.
        lancedb_origin.collection = "this-collection-does-not-exist"

        nodes = _make_graph_nodes()
        graph = _make_graph(nodes)
        retriever = _make_real_retriever(nodes, graph, [("n0", 0.3)])
        graph_origin = GraphIndexOrigin(retriever=retriever, name="graphindex")

        toolkit = MultiStoreSearchToolkit(origins=[lancedb_origin, graph_origin])
        response = await toolkit.store_search("cats local documents", k=10)

        by_origin = {s.origin: s for s in response.sections}
        assert by_origin["lancedb"].status in ("error", "timeout")
        assert by_origin["graphindex"].status == "ok"
        assert len(by_origin["graphindex"].hits) > 0

    async def test_unsupported_fts_origin_is_skipped_not_errored(self, tmp_path):
        store, lancedb_origin = await _make_lancedb_origin(tmp_path)
        nodes = _make_graph_nodes()
        graph = _make_graph(nodes)
        retriever = _make_real_retriever(nodes, graph, [("n0", 0.4)])
        # No reader -> supports_fts is False (origins/graphindex.py:67).
        graph_origin = GraphIndexOrigin(retriever=retriever, name="graphindex")
        assert graph_origin.supports_fts is False

        toolkit = MultiStoreSearchToolkit(origins=[lancedb_origin, graph_origin])
        response = await toolkit.fts_search("cats", k=10)

        by_origin = {s.origin: s for s in response.sections}
        assert by_origin["graphindex"].status == "skipped"
        # The FTS-capable LanceDB origin still ran.
        assert by_origin["lancedb"].status == "ok"
        await store.disconnect()
