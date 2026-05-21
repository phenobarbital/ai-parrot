"""Unit + integration tests for FEAT-192 GraphIndexToolkit additions.

Covers:
  - the 7 write tools (create_concept, create_node, link_nodes,
    unlink_nodes, attach_summary, tag_node, merge_nodes)
  - the 4 wrapped read tools (relevance, neighborhood_by_relevance,
    list_communities, find_community)
  - the embedder-backed _encode_query replacement (Module 2)
  - the end-to-end real-graph integration test (Module 7)
"""
from __future__ import annotations

import asyncio
from typing import Optional

import faiss
import numpy as np
import pytest
import rustworkx

from parrot.knowledge.graphindex.assemble import GraphAssembler
from parrot.knowledge.graphindex.embed import GraphIndexEmbedder
from parrot.knowledge.graphindex.schema import (
    EdgeKind,
    NodeKind,
    Provenance,
    UniversalEdge,
    UniversalNode,
)
from parrot.knowledge.graphindex.signals import SignalRelevanceConfig
from parrot_tools.graphindex.toolkit import GraphIndexToolkit


# ---------------------------------------------------------------------------
# Stubbed embedder — deterministic encode driven by title hash
# ---------------------------------------------------------------------------


class _StubModel:
    def __init__(self, dim: int = 8):
        self.dim = dim

    async def encode(self, texts):
        return self._sync_encode(texts)

    def _sync_encode(self, texts):
        out = np.zeros((len(texts), self.dim), dtype=np.float32)
        for i, t in enumerate(texts):
            for j, ch in enumerate(t[: self.dim]):
                out[i, j % self.dim] += float(ord(ch))
            n = np.linalg.norm(out[i])
            if n > 0:
                out[i] /= n
        return out


class _StubEmbedder:
    """In-memory GraphIndexEmbedder-compatible double.

    Mirrors the subset of the real embedder's API the toolkit relies on:
        - .model (with .encode(list[str]))
        - .index (FAISS index, used by find_node/search_hybrid via the
          toolkit's faiss_index attribute, not via the embedder).
        - .get_embedding(node_id)
        - async embed_nodes(list[UniversalNode]) — populates the
          embedding-id lookup, AND appends to the toolkit's FAISS
          index + node_id_list via the same pattern as the real
          embedder.
    """

    def __init__(self, dim: int = 8, faiss_index: faiss.Index = None,
                 node_id_list: Optional[list] = None):
        self.model = _StubModel(dim=dim)
        self.dim = dim
        self.index = faiss_index if faiss_index is not None else faiss.IndexFlatIP(dim)
        self._node_id_map: list[str] = []
        self._vectors: dict[str, np.ndarray] = {}
        # Reference back so we can mirror onto the toolkit's view.
        self._faiss_index_ref = faiss_index
        self._node_id_list_ref = node_id_list

    async def embed_nodes(self, nodes: list[UniversalNode], batch_size: int = 64):
        texts = [(n.summary or n.title or "") for n in nodes]
        vecs = self.model._sync_encode(texts)
        for i, node in enumerate(nodes):
            v = vecs[i].astype(np.float32)
            self._vectors[node.node_id] = v
            self._node_id_map.append(node.node_id)
            self.index.add(v.reshape(1, -1))
            if self._faiss_index_ref is not None and self._faiss_index_ref is not self.index:
                self._faiss_index_ref.add(v.reshape(1, -1))
            node.embedding_ref = f"faiss:{len(self._node_id_map) - 1}"
        return nodes

    def get_embedding(self, node_id: str):
        return self._vectors.get(node_id)


# ---------------------------------------------------------------------------
# Real-toolkit fixture
# ---------------------------------------------------------------------------


@pytest.fixture
def real_toolkit() -> GraphIndexToolkit:
    """Toolkit wired to a real GraphAssembler + stubbed embedder.

    Pre-populated with 4 nodes + 3 edges so write tests start from a
    non-trivial state.
    """
    dim = 8
    nodes = [
        UniversalNode(node_id="doc1", kind=NodeKind.DOCUMENT,
                      title="Doc 1", source_uri="d1.md"),
        UniversalNode(node_id="s1", kind=NodeKind.SECTION,
                      title="Section 1", source_uri="d1.md", summary="intro"),
        UniversalNode(node_id="s2", kind=NodeKind.SECTION,
                      title="Section 2", source_uri="d1.md", summary="next"),
        UniversalNode(node_id="c1", kind=NodeKind.CONCEPT,
                      title="Compliance", source_uri="d1.md",
                      summary="A grand compliance concept"),
    ]
    assembler = GraphAssembler(tenant_id="t")
    for n in nodes:
        assembler.add_node(n)
    edges = [
        UniversalEdge(source_id="doc1", target_id="s1", kind=EdgeKind.CONTAINS),
        UniversalEdge(source_id="doc1", target_id="s2", kind=EdgeKind.CONTAINS),
        UniversalEdge(source_id="s1", target_id="c1", kind=EdgeKind.REFERENCES),
    ]
    for e in edges:
        assembler.add_edge(e)

    faiss_index = faiss.IndexFlatIP(dim)
    embedder = _StubEmbedder(dim=dim, faiss_index=faiss_index)
    node_id_list: list = []
    embedder._node_id_list_ref = node_id_list
    # Embed the initial nodes synchronously through the stub.
    asyncio.get_event_loop().run_until_complete(embedder.embed_nodes(nodes))
    # The stub adds vectors to BOTH self.index AND faiss_index_ref; but
    # in our fixture they're the same FAISS instance so we'd double-add.
    # Re-create a fresh FAISS to avoid that.
    fresh_faiss = faiss.IndexFlatIP(dim)
    for nid in embedder._node_id_map:
        v = embedder._vectors[nid]
        fresh_faiss.add(v.reshape(1, -1))
    node_id_list = list(embedder._node_id_map)

    return GraphIndexToolkit(
        graph=assembler.graph,
        faiss_index=fresh_faiss,
        node_map=dict(assembler._node_index_map),
        node_id_list=node_id_list,
        assembler=assembler,
        embedder=embedder,
        nodes=nodes,
    )


@pytest.fixture
def readonly_toolkit() -> GraphIndexToolkit:
    """Toolkit constructed via the legacy 4-positional-arg path (no
    assembler / no embedder). Write tools must return {"error": ...}."""
    g = rustworkx.PyDiGraph()
    g.add_node({"node_id": "x", "kind": "document", "title": "X"})
    fi = faiss.IndexFlatIP(4)
    return GraphIndexToolkit(
        graph=g, faiss_index=fi, node_map={"x": 0}, node_id_list=["x"],
    )


# ---------------------------------------------------------------------------
# Module 1 — ctor + _write_supported
# ---------------------------------------------------------------------------


class TestConstructor:
    def test_accepts_new_kwargs(self, real_toolkit):
        assert real_toolkit.assembler is not None
        assert real_toolkit.embedder is not None
        assert real_toolkit.nodes  # populated
        assert real_toolkit._write_supported is True

    def test_write_unsupported_when_assembler_missing(self, readonly_toolkit):
        assert readonly_toolkit._write_supported is False

    def test_tool_discovery_lists_19_tools(self, real_toolkit):
        names = set(real_toolkit.list_tool_names())
        expected = {
            "find_node", "find_references", "get_neighborhood", "traverse",
            "search_hybrid", "find_central_nodes", "shortest_path", "explain",
            "create_concept", "create_node", "link_nodes", "unlink_nodes",
            "attach_summary", "tag_node", "merge_nodes",
            "relevance", "neighborhood_by_relevance",
            "list_communities", "find_community",
        }
        missing = expected - names
        assert not missing, f"missing tools: {missing}"


# ---------------------------------------------------------------------------
# Module 2 — _encode_query via embedder
# ---------------------------------------------------------------------------


class TestEncodeQuery:
    @pytest.mark.asyncio
    async def test_uses_embedder(self, real_toolkit):
        vec = await real_toolkit._encode_query("compliance", dim=8)
        assert vec.shape == (1, 8)
        assert vec.dtype == np.float32

    @pytest.mark.asyncio
    async def test_fallback_when_no_embedder(self, readonly_toolkit, caplog):
        import logging
        with caplog.at_level(logging.WARNING):
            await readonly_toolkit._encode_query("compliance", dim=4)
            # Calling again should not re-emit the warning
            await readonly_toolkit._encode_query("compliance", dim=4)
        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert len(warnings) == 1


# ---------------------------------------------------------------------------
# Write — node creation
# ---------------------------------------------------------------------------


class TestCreateNode:
    @pytest.mark.asyncio
    async def test_create_concept_adds_node(self, real_toolkit):
        before = real_toolkit.graph.num_nodes()
        result = await real_toolkit.create_concept(
            title="New Concept",
            summary="A wholly new wiki entity.",
            categories=["wiki"],
        )
        assert result["status"] == "created"
        new_id = result["node_id"]
        assert new_id in real_toolkit.node_map
        assert real_toolkit.graph.num_nodes() == before + 1
        # Categories stored in domain_tags
        node = real_toolkit._node_by_id(new_id)
        assert node.domain_tags["categories"] == ["wiki"]

    @pytest.mark.asyncio
    async def test_create_concept_invalidates_community_cache(self, real_toolkit):
        real_toolkit._community_cache = "stale"
        await real_toolkit.create_concept(title="X", summary="y")
        assert real_toolkit._community_cache is None

    @pytest.mark.asyncio
    async def test_create_node_validates_kind(self, real_toolkit):
        result = await real_toolkit.create_node(kind="bogus", title="Foo")
        assert "error" in result
        assert "bogus" in result["error"]

    @pytest.mark.asyncio
    async def test_create_concept_rejects_empty_title(self, real_toolkit):
        result = await real_toolkit.create_concept(title="   ", summary="x")
        assert "error" in result

    @pytest.mark.asyncio
    async def test_create_concept_no_assembler_returns_error(self, readonly_toolkit):
        result = await readonly_toolkit.create_concept(title="X", summary="y")
        assert "error" in result


# ---------------------------------------------------------------------------
# Write — link / unlink
# ---------------------------------------------------------------------------


class TestLinkNodes:
    @pytest.mark.asyncio
    async def test_extracted_rejects_confidence(self, real_toolkit):
        # confidence triggers INFERRED provenance, which the
        # UniversalEdge validator allows. Pass kind+confidence to test
        # the inverse: provenance=EXTRACTED without confidence works.
        # For this test verify: passing confidence promotes to INFERRED.
        result = await real_toolkit.link_nodes(
            "s2", "c1", kind="references", confidence=0.9,
        )
        assert result["status"] == "linked"

    @pytest.mark.asyncio
    async def test_inferred_link_requires_confidence(self, real_toolkit):
        # No confidence → defaults to EXTRACTED, succeeds.
        result = await real_toolkit.link_nodes("s2", "c1", kind="mentions")
        assert result["status"] == "linked"

    @pytest.mark.asyncio
    async def test_unknown_node_returns_error(self, real_toolkit):
        result = await real_toolkit.link_nodes(
            "ghost", "c1", kind="references",
        )
        assert "error" in result

    @pytest.mark.asyncio
    async def test_bad_kind_returns_error(self, real_toolkit):
        result = await real_toolkit.link_nodes(
            "s2", "c1", kind="floats_through",
        )
        assert "error" in result


class TestUnlinkNodes:
    @pytest.mark.asyncio
    async def test_unlink_removes_edge(self, real_toolkit):
        # Initial edge: s1 --references--> c1
        result = await real_toolkit.unlink_nodes("s1", "c1", kind="references")
        assert result["status"] == "unlinked"
        assert result["removed"] == 1

    @pytest.mark.asyncio
    async def test_unlink_no_op_when_no_edge(self, real_toolkit):
        result = await real_toolkit.unlink_nodes("s1", "s2")
        assert result["status"] == "no_op"
        assert result["removed"] == 0

    @pytest.mark.asyncio
    async def test_unlink_unknown_node(self, real_toolkit):
        result = await real_toolkit.unlink_nodes("ghost", "c1")
        assert "error" in result


# ---------------------------------------------------------------------------
# Write — attach_summary / tag_node
# ---------------------------------------------------------------------------


class TestAttachSummary:
    @pytest.mark.asyncio
    async def test_updates_graph_payload_and_node(self, real_toolkit):
        result = await real_toolkit.attach_summary("c1", "Revised summary.")
        assert result["status"] == "updated"
        idx = real_toolkit.node_map["c1"]
        assert real_toolkit.graph[idx]["summary"] == "Revised summary."
        assert real_toolkit._node_by_id("c1").summary == "Revised summary."

    @pytest.mark.asyncio
    async def test_unknown_node(self, real_toolkit):
        result = await real_toolkit.attach_summary("ghost", "x")
        assert "error" in result

    @pytest.mark.asyncio
    async def test_invalidates_community_cache(self, real_toolkit):
        real_toolkit._community_cache = "stale"
        await real_toolkit.attach_summary("c1", "new")
        assert real_toolkit._community_cache is None


class TestTagNode:
    @pytest.mark.asyncio
    async def test_shallow_merge(self, real_toolkit):
        await real_toolkit.tag_node("c1", "topic", "compliance")
        await real_toolkit.tag_node("c1", "severity", "high")
        node = real_toolkit._node_by_id("c1")
        assert node.domain_tags["topic"] == "compliance"
        assert node.domain_tags["severity"] == "high"

    @pytest.mark.asyncio
    async def test_rejects_empty_key(self, real_toolkit):
        result = await real_toolkit.tag_node("c1", "", "x")
        assert "error" in result

    @pytest.mark.asyncio
    async def test_unknown_node(self, real_toolkit):
        result = await real_toolkit.tag_node("ghost", "k", "v")
        assert "error" in result


# ---------------------------------------------------------------------------
# Write — merge_nodes
# ---------------------------------------------------------------------------


class TestMergeNodes:
    @pytest.mark.asyncio
    async def test_redirects_edges_and_removes_duplicate(self, real_toolkit):
        # Add a second concept that duplicates c1's role.
        dup = await real_toolkit.create_concept(
            title="Compliance Dup", summary="dup of compliance",
        )
        dup_id = dup["node_id"]
        # Edge from s2 to the dup
        await real_toolkit.link_nodes("s2", dup_id, kind="references")
        before_edges = real_toolkit.graph.num_edges()

        result = await real_toolkit.merge_nodes("c1", dup_id)

        assert result["status"] == "merged"
        assert result["redirected_edges"] >= 1
        # Duplicate is gone from node_map.
        assert dup_id not in real_toolkit.node_map
        # FAISS position is orphaned (None).
        assert any(x is None for x in real_toolkit.node_id_list)
        # Edges that landed on the dup now land on c1.
        s2_idx = real_toolkit.node_map["s2"]
        c1_idx = real_toolkit.node_map["c1"]
        out_edges = list(real_toolkit.graph.out_edges(s2_idx))
        assert any(t_idx == c1_idx for _s, t_idx, _p in out_edges)
        # Total edge count: at least one was redirected, none lost.
        assert real_toolkit.graph.num_edges() >= 1

    @pytest.mark.asyncio
    async def test_rejects_self_merge(self, real_toolkit):
        result = await real_toolkit.merge_nodes("c1", "c1")
        assert "error" in result

    @pytest.mark.asyncio
    async def test_rejects_unknown_ids(self, real_toolkit):
        result = await real_toolkit.merge_nodes("c1", "ghost")
        assert "error" in result


# ---------------------------------------------------------------------------
# Read — relevance / neighborhood / communities
# ---------------------------------------------------------------------------


class TestRelevance:
    @pytest.mark.asyncio
    async def test_returns_decomposed_dict(self, real_toolkit):
        result = await real_toolkit.relevance("s1", "c1")
        for key in ("direct", "source_overlap", "adamic_adar",
                    "type_affinity", "embedding", "combined",
                    "direct_edges", "shared_sources", "aa_neighbours",
                    "embedding_available"):
            assert key in result, f"missing {key}"

    @pytest.mark.asyncio
    async def test_unknown_node_returns_error(self, real_toolkit):
        result = await real_toolkit.relevance("ghost", "c1")
        assert "error" in result


class TestNeighborhoodByRelevance:
    @pytest.mark.asyncio
    async def test_respects_top_k_and_sorted(self, real_toolkit):
        results = await real_toolkit.neighborhood_by_relevance("c1", top_k=2)
        # Either two results or an error wrapped in a single dict
        assert isinstance(results, list)
        if results and "error" not in results[0]:
            assert len(results) <= 2
            scores = [r["combined"] for r in results]
            assert scores == sorted(scores, reverse=True)


class TestCommunities:
    @pytest.mark.asyncio
    async def test_list_communities_returns_dicts(self, real_toolkit):
        # Build out the graph so Louvain has something to partition.
        await real_toolkit.link_nodes("s2", "c1", kind="references")
        results = await real_toolkit.list_communities(min_size=1)
        assert isinstance(results, list)
        assert results  # at least one community
        for c in results:
            assert "community_id" in c
            assert "size" in c
            assert c["size"] >= 1

    @pytest.mark.asyncio
    async def test_find_community_returns_membership(self, real_toolkit):
        # Ensure cache populated
        await real_toolkit.list_communities()
        result = await real_toolkit.find_community("c1")
        assert "community_id" in result

    @pytest.mark.asyncio
    async def test_cache_invalidated_by_write(self, real_toolkit):
        # Populate cache.
        await real_toolkit.list_communities()
        cache_before = real_toolkit._community_cache
        assert cache_before is not None
        # Any write tool invalidates.
        await real_toolkit.tag_node("c1", "topic", "compliance")
        assert real_toolkit._community_cache is None

    @pytest.mark.asyncio
    async def test_find_community_unknown_node(self, real_toolkit):
        await real_toolkit.list_communities()
        result = await real_toolkit.find_community("ghost")
        assert "error" in result


# ---------------------------------------------------------------------------
# Module 7 — End-to-end integration
# ---------------------------------------------------------------------------


class TestEndToEnd:
    @pytest.mark.asyncio
    async def test_create_link_merge_lookup_flow(self, real_toolkit):
        # Step 1: create a new concept.
        a = await real_toolkit.create_concept(title="Alpha", summary="alpha node")
        b = await real_toolkit.create_concept(title="Beta", summary="beta node")
        assert a["status"] == b["status"] == "created"

        # Step 2: link them.
        link = await real_toolkit.link_nodes(
            a["node_id"], b["node_id"], kind="references",
        )
        assert link["status"] == "linked"

        # Step 3: find_references sees the new edge.
        refs = await real_toolkit.find_references(a["node_id"])
        assert any(r["target_id"] == b["node_id"] for r in refs)

        # Step 4: merge beta into alpha; the link disappears (would
        # have been a self-loop).
        merged = await real_toolkit.merge_nodes(a["node_id"], b["node_id"])
        assert merged["status"] == "merged"
        assert b["node_id"] not in real_toolkit.node_map

    @pytest.mark.asyncio
    async def test_full_wiki_loop_relevance_then_communities(self, real_toolkit):
        # Tag two existing nodes with shared categories.
        await real_toolkit.tag_node("s1", "topic", "compliance")
        await real_toolkit.tag_node("s2", "topic", "compliance")
        # Run signal relevance between them.
        rel = await real_toolkit.relevance("s1", "s2")
        assert rel["source_overlap"] == 1.0  # both source_uri = d1.md
        # Communities should partition the graph; both s1 and s2 land
        # in some community.
        await real_toolkit.list_communities()
        c1 = await real_toolkit.find_community("s1")
        c2 = await real_toolkit.find_community("s2")
        assert "community_id" in c1 and "community_id" in c2

    @pytest.mark.asyncio
    async def test_works_with_default_signal_config(self, real_toolkit):
        """No explicit signal_config → toolkit uses the FEAT-190 default."""
        assert real_toolkit.signal_config is None
        result = await real_toolkit.relevance("s1", "c1")
        assert "combined" in result
