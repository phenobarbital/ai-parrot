"""Tests for the LLM-Wiki example wiring (``examples/knowledge_wiki/wiki.py``).

These tests are deterministic and offline: no API keys, no databases, no model
downloads. They exercise the *real* PageIndex and GraphIndex toolkits through
the example's inline composition helpers, plus the graceful degradation of the
Ontology layer.

Run with::

    pytest examples/knowledge_wiki/ -v
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
import pytest_asyncio

# Make the example package importable (`import wiki`) regardless of CWD.
_EXAMPLE_DIR = Path(__file__).resolve().parent.parent
if str(_EXAMPLE_DIR) not in sys.path:
    sys.path.insert(0, str(_EXAMPLE_DIR))

import wiki  # noqa: E402
from parrot.knowledge.graphindex.schema import (  # noqa: E402
    EdgeKind,
    NodeKind,
    UniversalEdge,
    UniversalNode,
)

RAW_DIR = _EXAMPLE_DIR / "raw"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _seed_graph() -> tuple[list[UniversalNode], list[UniversalEdge]]:
    nodes = [
        UniversalNode(node_id="doc::wiki", kind=NodeKind.DOCUMENT,
                      title="Knowledge Wiki", source_uri="wiki://",
                      summary="Root of the knowledge wiki."),
        UniversalNode(node_id="c::pageindex", kind=NodeKind.CONCEPT,
                      title="PageIndex", source_uri="wiki://pageindex",
                      summary="Hierarchical wiki pages with hybrid search."),
        UniversalNode(node_id="c::graphindex", kind=NodeKind.CONCEPT,
                      title="GraphIndex", source_uri="wiki://graphindex",
                      summary="Agent-maintained knowledge graph with FAISS."),
    ]
    edges = [
        UniversalEdge(source_id="doc::wiki", target_id="c::pageindex",
                      kind=EdgeKind.CONTAINS),
        UniversalEdge(source_id="doc::wiki", target_id="c::graphindex",
                      kind=EdgeKind.CONTAINS),
    ]
    return nodes, edges


@pytest_asyncio.fixture
async def gi_toolkit():
    nodes, edges = _seed_graph()
    return await wiki.build_graphindex_toolkit(nodes, edges)


@pytest.fixture
def pi_toolkit(tmp_path):
    from parrot.knowledge.pageindex import PageIndexLLMAdapter

    class _NullClient:
        """add_node / BM25 search never call the client."""

    adapter = PageIndexLLMAdapter(client=_NullClient(), model="test-model")
    return wiki.build_pageindex_toolkit(adapter=adapter, storage_dir=tmp_path)


# ---------------------------------------------------------------------------
# GraphIndex composition
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_build_graphindex_toolkit_is_write_enabled(gi_toolkit):
    assert gi_toolkit._write_supported is True
    names = set(gi_toolkit.list_tool_names())
    # The 7 write tools must be present — this is what lets the LLM contribute.
    for write_tool in (
        "create_concept", "create_node", "link_nodes", "unlink_nodes",
        "attach_summary", "tag_node", "merge_nodes",
    ):
        assert write_tool in names, f"missing write tool: {write_tool}"
    assert len(names) == 19


@pytest.mark.asyncio
async def test_build_graphindex_toolkit_empty_start():
    """A blank graph the agent fills from scratch must still be write-enabled."""
    gi = await wiki.build_graphindex_toolkit([], [])
    assert gi._write_supported is True
    assert gi.faiss_index.ntotal == 0
    created = await gi.create_concept(title="First", summary="seed")
    assert created["status"] == "created"
    assert gi.faiss_index.ntotal == 1


# ---------------------------------------------------------------------------
# The contribution loop — the heart of the LLM-Wiki idea
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_contribution_loop(gi_toolkit):
    # 1. The agent files a new concept.
    created = await gi_toolkit.create_concept(
        title="Hybrid Retrieval",
        summary="Fusing BM25 lexical search with an LLM tree-walk via RRF.",
        categories=["retrieval"],
    )
    assert created["status"] == "created"
    new_id = created["node_id"]

    # 2. It is immediately searchable (write updated the shared FAISS index).
    found = await gi_toolkit.find_node("hybrid retrieval bm25 fusion rrf")
    assert "error" not in found
    assert found["node_id"] == new_id

    # 3. Cross-link it into the existing knowledge.
    linked = await gi_toolkit.link_nodes("c::pageindex", new_id, kind="references")
    assert linked["status"] == "linked"

    # 4. The link is reflected in the relevance signals.
    rel = await gi_toolkit.relevance("c::pageindex", new_id)
    assert rel["direct"] > 0
    assert rel["combined"] > 0

    # 5. attach_summary keeps the node model authoritative.
    summed = await gi_toolkit.attach_summary(new_id, "Blends sparse + dense.")
    assert "error" not in summed


@pytest.mark.asyncio
async def test_communities_surface_linked_cluster(gi_toolkit):
    created = await gi_toolkit.create_concept(title="Hybrid Retrieval",
                                              summary="bm25 + llm walk")
    new_id = created["node_id"]
    await gi_toolkit.link_nodes("c::pageindex", new_id, kind="references")
    await gi_toolkit.link_nodes("c::graphindex", new_id, kind="references")
    community = await gi_toolkit.find_community(new_id)
    assert "error" not in community
    assert new_id in community["member_node_ids"]


@pytest.mark.asyncio
async def test_merge_nodes_orphans_faiss_row(gi_toolkit):
    a = (await gi_toolkit.create_concept(title="RRF", summary="rank fusion"))["node_id"]
    b = (await gi_toolkit.create_concept(title="Reciprocal Rank Fusion",
                                         summary="rank fusion duplicate"))["node_id"]
    result = await gi_toolkit.merge_nodes(canonical_id=a, duplicate_id=b)
    assert result.get("status") == "merged" or "error" not in result
    # The duplicate is gone from the graph, and its FAISS row is orphaned.
    assert b not in gi_toolkit.node_map
    assert None in gi_toolkit.node_id_list


# ---------------------------------------------------------------------------
# PageIndex side — pages + BM25 retrieval, no LLM
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_pageindex_seed_and_bm25(pi_toolkit):
    await pi_toolkit.create_tree("wiki", doc_name="Knowledge Wiki")
    await pi_toolkit.add_node(
        tree_name="wiki",
        title="GraphIndex",
        body="GraphIndex is the knowledge graph the agent grows with write tools.",
        summary="The knowledge-graph half of the wiki.",
        categories=["seed"],
    )
    await pi_toolkit.add_node(
        tree_name="wiki",
        title="PageIndex",
        body="PageIndex stores durable wiki pages as a lean tree.",
        summary="The wiki-pages half.",
        categories=["seed"],
    )
    pages = (await pi_toolkit.get_tree("wiki")).get("structure", [])
    assert len(pages) == 2

    hits = await pi_toolkit.search(
        "wiki", "knowledge graph write tools", top_k=2,
        use_bm25=True, use_llm_walk=False,
    )
    assert hits, "BM25 search returned no candidates"
    assert hits[0]["title"] == "GraphIndex"


# ---------------------------------------------------------------------------
# Lint
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_wiki_lint_detects_orphan(gi_toolkit, pi_toolkit):
    await pi_toolkit.create_tree("knowledge_wiki", doc_name="Knowledge Wiki")
    # Create a concept but never link it -> orphan.
    orphan = await gi_toolkit.create_concept(title="Lonely Concept",
                                             summary="no edges at all")
    report = await wiki.wiki_lint(gi_toolkit, pi_toolkit, "knowledge_wiki")
    orphan_ids = {o["node_id"] for o in report["orphan_nodes"]}
    assert orphan["node_id"] in orphan_ids
    assert report["graph_nodes"] >= 4


# ---------------------------------------------------------------------------
# Ontology layer — graceful degradation without ArangoDB
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_ontology_degrades_when_unconfigured():
    """The Ontology composition must not raise without a tenant manager."""
    from parrot.knowledge.ontology.mixin import OntologyRAGMixin

    class _Probe(OntologyRAGMixin):
        pass

    probe = _Probe(tenant_manager=None)
    envelope = await probe.ontology_process(
        query="anything",
        user_context={"user_id": "u1"},
        tenant_id="wiki",
    )
    # Degraded but well-defined — never an exception.
    assert envelope.state in {"not_configured", "disabled", "vector_only"}
