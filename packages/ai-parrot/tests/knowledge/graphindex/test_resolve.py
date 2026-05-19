"""Unit tests for parrot.knowledge.graphindex.resolve."""

import pytest
import numpy as np
from unittest.mock import MagicMock

from parrot.knowledge.graphindex.resolve import (
    ResolutionConfig,
    resolve_cross_domain,
    _get_extractor_domain,
)
from parrot.knowledge.graphindex.schema import (
    EdgeKind,
    NodeKind,
    Provenance,
    UniversalEdge,
    UniversalNode,
)


def make_node(
    node_id: str,
    kind: NodeKind = NodeKind.DOCUMENT,
    title: str = "test",
    embedding_ref: str | None = "faiss:0",
) -> UniversalNode:
    """Create a test UniversalNode with an optional embedding_ref."""
    return UniversalNode(
        node_id=node_id,
        kind=kind,
        title=title,
        source_uri="test.txt",
        embedding_ref=embedding_ref,
    )


def make_embedder(similarity_map: dict[tuple[str, str], float]) -> MagicMock:
    """Create a mock embedder that returns configured similarity values.

    The embedder returns unit vectors such that dot product == sim.

    Args:
        similarity_map: Mapping of (node_id_a, node_id_b) → cosine similarity.
    """
    vecs: dict[str, np.ndarray] = {}
    for (a, b), sim in similarity_map.items():
        # Create vectors with known cosine similarity
        if a not in vecs:
            vecs[a] = np.array([1.0, 0.0, 0.0], dtype=np.float32)
        if b not in vecs:
            # b = sim*a + sqrt(1-sim^2)*perp
            perp = np.array([0.0, 1.0, 0.0], dtype=np.float32)
            vecs[b] = sim * vecs[a] + np.sqrt(max(0, 1 - sim**2)) * perp
            # Normalise
            norm = np.linalg.norm(vecs[b])
            if norm > 0:
                vecs[b] /= norm

    embedder = MagicMock()
    embedder.get_embedding.side_effect = lambda node_id: vecs.get(node_id)
    return embedder


class TestDomainClassification:
    def test_symbol_is_code(self):
        assert _get_extractor_domain(make_node("x", kind=NodeKind.SYMBOL)) == "code"

    def test_rationale_is_code(self):
        assert _get_extractor_domain(make_node("x", kind=NodeKind.RATIONALE)) == "code"

    def test_document_is_document(self):
        assert _get_extractor_domain(make_node("x", kind=NodeKind.DOCUMENT)) == "document"

    def test_section_is_document(self):
        assert _get_extractor_domain(make_node("x", kind=NodeKind.SECTION)) == "document"

    def test_skill_is_skill(self):
        assert _get_extractor_domain(make_node("x", kind=NodeKind.SKILL)) == "skill"


class TestResolveCrossDomain:
    @pytest.mark.asyncio
    async def test_empty_input(self):
        embedder = MagicMock()
        result = await resolve_cross_domain([], embedder)
        assert result == []

    @pytest.mark.asyncio
    async def test_single_node_returns_empty(self):
        embedder = MagicMock()
        result = await resolve_cross_domain(
            [make_node("n1", kind=NodeKind.DOCUMENT)], embedder
        )
        assert result == []

    @pytest.mark.asyncio
    async def test_emits_edge_above_threshold(self):
        """Two nodes from different domains with high similarity → mentions edge."""
        node_a = make_node("a", kind=NodeKind.SYMBOL, embedding_ref="faiss:0")
        node_b = make_node("b", kind=NodeKind.DOCUMENT, embedding_ref="faiss:1")
        embedder = make_embedder({("a", "b"): 0.92})
        config = ResolutionConfig(threshold=0.75)

        result = await resolve_cross_domain([node_a, node_b], embedder, config)
        assert len(result) == 1
        edge = result[0]
        assert edge.kind == EdgeKind.MENTIONS
        assert edge.provenance == Provenance.INFERRED
        assert edge.confidence is not None
        assert edge.confidence > 0.75

    @pytest.mark.asyncio
    async def test_skips_below_threshold(self):
        """Pairs with sim < threshold produce no edges."""
        node_a = make_node("a", kind=NodeKind.SYMBOL, embedding_ref="faiss:0")
        node_b = make_node("b", kind=NodeKind.DOCUMENT, embedding_ref="faiss:1")
        embedder = make_embedder({("a", "b"): 0.30})
        config = ResolutionConfig(threshold=0.75)

        result = await resolve_cross_domain([node_a, node_b], embedder, config)
        assert result == []

    @pytest.mark.asyncio
    async def test_skips_same_domain(self):
        """Nodes from the same domain (both code) are not compared."""
        node_a = make_node("a", kind=NodeKind.SYMBOL, embedding_ref="faiss:0")
        node_b = make_node("b", kind=NodeKind.RATIONALE, embedding_ref="faiss:1")
        embedder = make_embedder({("a", "b"): 0.99})
        config = ResolutionConfig(threshold=0.75)

        result = await resolve_cross_domain([node_a, node_b], embedder, config)
        assert result == []

    @pytest.mark.asyncio
    async def test_confidence_equals_similarity(self):
        """confidence field must equal the actual cosine similarity."""
        node_a = make_node("a", kind=NodeKind.SYMBOL, embedding_ref="faiss:0")
        node_b = make_node("b", kind=NodeKind.SKILL, embedding_ref="faiss:1")
        # Use vectors that have exact similarity
        v_a = np.array([1.0, 0.0, 0.0], dtype=np.float32)
        v_b = np.array([1.0, 0.0, 0.0], dtype=np.float32)  # identical → sim=1.0
        embedder = MagicMock()
        embedder.get_embedding.side_effect = lambda nid: v_a if nid == "a" else v_b
        config = ResolutionConfig(threshold=0.75)

        result = await resolve_cross_domain([node_a, node_b], embedder, config)
        assert len(result) == 1
        assert abs(result[0].confidence - 1.0) < 0.01

    @pytest.mark.asyncio
    async def test_nodes_without_embeddings_skipped(self):
        """Nodes with embedding_ref=None are excluded from resolution."""
        node_a = make_node("a", kind=NodeKind.SYMBOL, embedding_ref=None)
        node_b = make_node("b", kind=NodeKind.DOCUMENT, embedding_ref="faiss:1")
        embedder = MagicMock()
        embedder.get_embedding.return_value = np.ones(3, dtype=np.float32)
        config = ResolutionConfig(threshold=0.5)

        result = await resolve_cross_domain([node_a, node_b], embedder, config)
        assert result == []

    @pytest.mark.asyncio
    async def test_max_edges_per_node_capped(self):
        """max_edges_per_node limits the number of inferred edges per source node."""
        # 1 code node vs 5 doc nodes with high similarity
        code_node = make_node("code_0", kind=NodeKind.SYMBOL, embedding_ref="faiss:0")
        doc_nodes = [
            make_node(f"doc_{i}", kind=NodeKind.DOCUMENT, embedding_ref=f"faiss:{i+1}")
            for i in range(5)
        ]
        v = np.array([1.0, 0.0, 0.0], dtype=np.float32)
        embedder = MagicMock()
        embedder.get_embedding.return_value = v
        config = ResolutionConfig(threshold=0.5, max_edges_per_node=2)

        result = await resolve_cross_domain([code_node] + doc_nodes, embedder, config)
        # code_0 → max 2 edges
        edges_from_code = [e for e in result if e.source_id == "code_0"]
        assert len(edges_from_code) <= 2

    @pytest.mark.asyncio
    async def test_all_same_domain_returns_empty(self):
        """All nodes from code domain → no cross-domain edges."""
        nodes = [
            make_node("a", kind=NodeKind.SYMBOL, embedding_ref="faiss:0"),
            make_node("b", kind=NodeKind.SYMBOL, embedding_ref="faiss:1"),
            make_node("c", kind=NodeKind.RATIONALE, embedding_ref="faiss:2"),
        ]
        v = np.ones(3, dtype=np.float32)
        embedder = MagicMock()
        embedder.get_embedding.return_value = v
        result = await resolve_cross_domain(nodes, embedder)
        assert result == []
