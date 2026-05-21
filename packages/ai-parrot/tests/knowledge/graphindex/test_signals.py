"""Unit + integration tests for parrot.knowledge.graphindex.signals (FEAT-190)."""
from __future__ import annotations

import logging
import math
from typing import Optional

import numpy as np
import pytest
import rustworkx

from parrot.knowledge.graphindex.schema import (
    EdgeKind,
    NodeKind,
    UniversalNode,
)
from parrot.knowledge.graphindex.signals import (
    SignalRelevance,
    SignalRelevanceConfig,
    _adamic_adar_signal,
    _canonical_pair,
    _default_type_affinity,
    _direct_signal,
    _effective_weights,
    _embedding_signal,
    _invalidate_nx_cache,
    _source_overlap_signal,
    _type_affinity_signal,
    compute_pairwise_signals,
    relevance_neighborhood,
    signal_relevance,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _node_payload(
    node_id: str,
    kind: NodeKind = NodeKind.SECTION,
    title: str = "",
    source_uri: str = "doc.md",
    domain_tags: Optional[dict] = None,
) -> dict:
    return {
        "node_id": node_id,
        "kind": kind.value,
        "title": title or node_id,
        "source_uri": source_uri,
        "domain_tags": domain_tags or {},
    }


def _add_node(graph: rustworkx.PyDiGraph, **kwargs) -> int:
    return graph.add_node(_node_payload(**kwargs))


def _add_edge(
    graph: rustworkx.PyDiGraph,
    src: int,
    tgt: int,
    kind: EdgeKind = EdgeKind.REFERENCES,
) -> int:
    return graph.add_edge(src, tgt, {"kind": kind.value})


def _build_simple_graph() -> tuple[rustworkx.PyDiGraph, dict[str, int]]:
    """Return (graph, name->idx) for a tiny 4-node graph used by many tests."""
    g = rustworkx.PyDiGraph()
    idxs = {
        "a": _add_node(g, node_id="a", kind=NodeKind.CONCEPT, source_uri="doc1.md"),
        "b": _add_node(g, node_id="b", kind=NodeKind.SECTION, source_uri="doc1.md"),
        "c": _add_node(g, node_id="c", kind=NodeKind.SECTION, source_uri="doc2.md"),
        "d": _add_node(g, node_id="d", kind=NodeKind.SYMBOL, source_uri="src/x.py"),
    }
    yield_graph = (g, idxs)
    _invalidate_nx_cache(g)  # ensure no leftover from previous tests
    return yield_graph


class _StubEmbedder:
    """Minimal GraphIndexEmbedder stand-in: returns vectors from a dict."""

    def __init__(self, vectors: dict[str, np.ndarray]):
        self._vectors = vectors

    def get_embedding(self, node_id: str) -> Optional[np.ndarray]:
        return self._vectors.get(node_id)


# ---------------------------------------------------------------------------
# Module 1 — config + models
# ---------------------------------------------------------------------------


class TestConfig:
    def test_default_config_weights_sum_to_one(self):
        c = SignalRelevanceConfig()
        total = (
            c.w_direct + c.w_source_overlap + c.w_adamic_adar
            + c.w_type_affinity + c.w_embedding
        )
        assert abs(total - 1.0) < 1e-6

    def test_config_weights_must_sum_to_one(self):
        with pytest.raises(ValueError):
            SignalRelevanceConfig(w_direct=0.5, w_source_overlap=0.5,
                                  w_adamic_adar=0.5, w_type_affinity=0.5,
                                  w_embedding=0.5)

    def test_config_frozen(self):
        c = SignalRelevanceConfig()
        with pytest.raises(Exception):
            c.w_direct = 0.99

    def test_default_type_affinity_symmetric(self):
        matrix = _default_type_affinity()
        for (a, b), v in matrix.items():
            assert matrix[(a, b)] == matrix[_canonical_pair(b, a)]


# ---------------------------------------------------------------------------
# Module 2 — direct + source overlap
# ---------------------------------------------------------------------------


class TestDirectSignal:
    def test_no_edges_returns_zero(self):
        g, idxs = _build_simple_graph()
        score, edges = _direct_signal(
            g, idxs["a"], idxs["b"], SignalRelevanceConfig().edge_kind_weights,
        )
        assert score == 0.0
        assert edges == []

    def test_single_references_edge(self):
        g, idxs = _build_simple_graph()
        _add_edge(g, idxs["a"], idxs["b"], EdgeKind.REFERENCES)
        weights = SignalRelevanceConfig().edge_kind_weights
        score, edges = _direct_signal(g, idxs["a"], idxs["b"], weights)
        max_w = max(weights.values())
        assert score == pytest.approx(weights[EdgeKind.REFERENCES] / max_w)
        assert len(edges) == 1
        assert edges[0]["kind"] == "references"

    def test_bidirectional_edges_both_counted(self):
        g, idxs = _build_simple_graph()
        _add_edge(g, idxs["a"], idxs["b"], EdgeKind.REFERENCES)
        _add_edge(g, idxs["b"], idxs["a"], EdgeKind.REFERENCES)
        weights = SignalRelevanceConfig().edge_kind_weights
        score, edges = _direct_signal(g, idxs["a"], idxs["b"], weights)
        # Two REFERENCES edges at weight 1.0 each, max weight 1.0 → capped at 1.0.
        assert score == 1.0
        assert len(edges) == 2


class TestSourceOverlap:
    def test_identical_source(self):
        a = _node_payload("a", source_uri="same.md")
        b = _node_payload("b", source_uri="same.md")
        score, shared = _source_overlap_signal(a, b)
        assert score == 1.0
        assert shared == ["same.md"]

    def test_disjoint_sources_zero(self):
        a = _node_payload("a", source_uri="x.md")
        b = _node_payload("b", source_uri="y.md")
        score, shared = _source_overlap_signal(a, b)
        assert score == 0.0
        assert shared == []

    def test_empty_sources_yield_zero(self):
        a = _node_payload("a", source_uri="")
        b = _node_payload("b", source_uri="")
        score, _ = _source_overlap_signal(a, b)
        assert score == 0.0

    def test_multi_source_via_domain_tags(self):
        a = _node_payload("a", source_uri="x.md",
                          domain_tags={"sources": ["y.md", "z.md"]})
        b = _node_payload("b", source_uri="y.md",
                          domain_tags={"sources": ["w.md"]})
        score, shared = _source_overlap_signal(a, b)
        # a has {x, y, z}; b has {y, w}; intersection {y}; union {x,y,z,w}
        assert score == pytest.approx(1.0 / 4.0)
        assert shared == ["y.md"]


# ---------------------------------------------------------------------------
# Module 3 — Adamic-Adar
# ---------------------------------------------------------------------------


class TestAdamicAdar:
    def test_no_shared_neighbours_zero(self):
        g, idxs = _build_simple_graph()
        score, neighbours = _adamic_adar_signal(g, "a", "c", cap=4.0)
        assert score == 0.0
        assert neighbours == []

    def test_one_shared_neighbour_positive(self):
        g, idxs = _build_simple_graph()
        # a-b, c-b → shared neighbour b
        _add_edge(g, idxs["a"], idxs["b"], EdgeKind.REFERENCES)
        _add_edge(g, idxs["c"], idxs["b"], EdgeKind.REFERENCES)
        _invalidate_nx_cache(g)
        score, neighbours = _adamic_adar_signal(g, "a", "c", cap=4.0)
        # b has degree 2 (after collapse) → AA = 1/log(2) ≈ 1.44; clipped/4 ≈ 0.36
        assert score > 0.0
        assert score == pytest.approx((1.0 / math.log(2)) / 4.0, rel=1e-3)
        assert "b" in neighbours

    def test_score_clipped_at_cap(self):
        g = rustworkx.PyDiGraph()
        idxs = {n: _add_node(g, node_id=n) for n in ("a", "c")}
        # 20 shared neighbours each of degree 2 → AA huge → clipped to 1.0
        for i in range(20):
            shared = _add_node(g, node_id=f"s{i}")
            _add_edge(g, idxs["a"], shared)
            _add_edge(g, idxs["c"], shared)
        _invalidate_nx_cache(g)
        score, _ = _adamic_adar_signal(g, "a", "c", cap=4.0)
        assert score == 1.0

    def test_nx_cache_reused(self, monkeypatch):
        g, idxs = _build_simple_graph()
        _add_edge(g, idxs["a"], idxs["b"], EdgeKind.REFERENCES)
        _invalidate_nx_cache(g)
        # First call builds the cache.
        _adamic_adar_signal(g, "a", "b", cap=4.0)
        # Patch the cache key away — second call would have to rebuild.
        # We assert by reading the cache instance is the same object.
        from parrot.knowledge.graphindex.signals import _NX_CACHE
        cached_first = _NX_CACHE[id(g)][0]
        _adamic_adar_signal(g, "a", "b", cap=4.0)
        cached_second = _NX_CACHE[id(g)][0]
        assert cached_first is cached_second


# ---------------------------------------------------------------------------
# Module 3b — embedding signal
# ---------------------------------------------------------------------------


class TestEmbeddingSignal:
    def test_uses_embedder(self):
        vec_a = np.array([1.0, 0.0, 0.0], dtype=np.float32)
        vec_b = np.array([1.0, 0.0, 0.0], dtype=np.float32)
        emb = _StubEmbedder({"a": vec_a, "b": vec_b})
        score, available = _embedding_signal(emb, "a", "b")
        assert available is True
        assert score == pytest.approx(1.0)

    def test_orthogonal_returns_zero(self):
        vec_a = np.array([1.0, 0.0], dtype=np.float32)
        vec_b = np.array([0.0, 1.0], dtype=np.float32)
        emb = _StubEmbedder({"a": vec_a, "b": vec_b})
        score, available = _embedding_signal(emb, "a", "b")
        assert available is True
        assert score == pytest.approx(0.0, abs=1e-6)

    def test_missing_embedding_returns_zero_unavailable(self):
        emb = _StubEmbedder({"a": np.array([1.0, 0.0], dtype=np.float32)})
        score, available = _embedding_signal(emb, "a", "b")
        assert score == 0.0
        assert available is False

    def test_no_embedder_returns_zero_unavailable(self):
        score, available = _embedding_signal(None, "a", "b")
        assert score == 0.0
        assert available is False

    def test_negative_cosine_clamped_to_zero(self):
        vec_a = np.array([1.0, 0.0], dtype=np.float32)
        vec_b = np.array([-1.0, 0.0], dtype=np.float32)
        emb = _StubEmbedder({"a": vec_a, "b": vec_b})
        score, available = _embedding_signal(emb, "a", "b")
        assert score == 0.0
        assert available is True


# ---------------------------------------------------------------------------
# Module 4 — type affinity + effective weights + combined
# ---------------------------------------------------------------------------


class TestTypeAffinity:
    def test_concept_concept_high(self):
        matrix = _default_type_affinity()
        a = _node_payload("a", kind=NodeKind.CONCEPT)
        b = _node_payload("b", kind=NodeKind.CONCEPT)
        assert _type_affinity_signal(a, b, matrix) == 1.00

    def test_order_independent(self):
        matrix = _default_type_affinity()
        a = _node_payload("a", kind=NodeKind.SECTION)
        b = _node_payload("b", kind=NodeKind.CONCEPT)
        ab = _type_affinity_signal(a, b, matrix)
        ba = _type_affinity_signal(b, a, matrix)
        assert ab == ba == 0.85

    def test_unlisted_pair_default(self):
        matrix = _default_type_affinity()
        a = _node_payload("a", kind=NodeKind.SKILL)
        b = _node_payload("b", kind=NodeKind.CONCEPT)
        # SKILL × CONCEPT is unlisted in defaults → 0.30
        assert _type_affinity_signal(a, b, matrix) == 0.30


class TestEffectiveWeights:
    def test_pass_through_when_embedding_available(self):
        cfg = SignalRelevanceConfig()
        w = _effective_weights(cfg, embedding_available=True)
        assert w == (cfg.w_direct, cfg.w_source_overlap, cfg.w_adamic_adar,
                     cfg.w_type_affinity, cfg.w_embedding)

    def test_renormalise_when_embedding_absent(self):
        cfg = SignalRelevanceConfig()  # w_embedding=0.25 by default
        w = _effective_weights(cfg, embedding_available=False)
        # Remaining 4 should sum to 1.0
        assert abs(sum(w) - 1.0) < 1e-9
        # w_embedding slot should be 0
        assert w[4] == 0.0
        # Ratio preserved: w[0] / (cfg.w_direct + cfg.w_source_overlap +
        #                          cfg.w_adamic_adar + cfg.w_type_affinity) == 1 / 0.75
        expected_scale = 1.0 / (1.0 - cfg.w_embedding)
        assert w[0] == pytest.approx(cfg.w_direct * expected_scale)
        assert w[1] == pytest.approx(cfg.w_source_overlap * expected_scale)
        assert w[2] == pytest.approx(cfg.w_adamic_adar * expected_scale)
        assert w[3] == pytest.approx(cfg.w_type_affinity * expected_scale)


# ---------------------------------------------------------------------------
# Public scorer
# ---------------------------------------------------------------------------


class TestSignalRelevance:
    def test_returns_decomposed_output(self):
        g, idxs = _build_simple_graph()
        _add_edge(g, idxs["a"], idxs["b"], EdgeKind.REFERENCES)
        _invalidate_nx_cache(g)
        result = signal_relevance(g, [], "a", "b")
        assert isinstance(result, SignalRelevance)
        assert result.node_a == "a" and result.node_b == "b"
        # All sub-scores in [0, 1]
        for f in ("direct", "source_overlap", "adamic_adar",
                  "type_affinity", "embedding", "combined"):
            v = getattr(result, f)
            assert 0.0 <= v <= 1.0
        assert isinstance(result.direct_edges, list)
        assert isinstance(result.shared_sources, list)
        assert isinstance(result.aa_neighbours, list)

    def test_unknown_node_raises_keyerror(self):
        g, _ = _build_simple_graph()
        with pytest.raises(KeyError):
            signal_relevance(g, [], "a", "ghost")

    def test_self_pair_raises_keyerror(self):
        g, _ = _build_simple_graph()
        with pytest.raises(KeyError):
            signal_relevance(g, [], "a", "a")

    def test_embedder_populates_embedding_signal(self):
        g, idxs = _build_simple_graph()
        emb = _StubEmbedder({
            "a": np.array([1.0, 0.0, 0.0], dtype=np.float32),
            "b": np.array([1.0, 0.0, 0.0], dtype=np.float32),
        })
        result = signal_relevance(g, [], "a", "b", embedder=emb)
        assert result.embedding_available is True
        assert result.embedding == pytest.approx(1.0)

    def test_no_embedder_marks_unavailable_and_renormalises(self):
        g, idxs = _build_simple_graph()
        _add_edge(g, idxs["a"], idxs["b"], EdgeKind.REFERENCES)
        _invalidate_nx_cache(g)
        # With embedder: combined uses 5 weights
        emb = _StubEmbedder({
            "a": np.array([1.0, 0.0], dtype=np.float32),
            "b": np.array([1.0, 0.0], dtype=np.float32),
        })
        with_emb = signal_relevance(g, [], "a", "b", embedder=emb)
        # Without embedder: 4-weight renormalisation
        without_emb = signal_relevance(g, [], "a", "b", embedder=None)
        assert with_emb.embedding_available is True
        assert without_emb.embedding_available is False
        # Both combined scores in [0, 1]
        assert 0.0 <= with_emb.combined <= 1.0
        assert 0.0 <= without_emb.combined <= 1.0

    def test_all_one_subscores_produce_combined_one(self):
        """With embedder + a graph carefully constructed so each signal
        evaluates to 1.0, the combined score must equal 1.0."""
        g = rustworkx.PyDiGraph()
        idx_a = _add_node(g, node_id="a", kind=NodeKind.CONCEPT,
                          source_uri="shared.md")
        idx_b = _add_node(g, node_id="b", kind=NodeKind.CONCEPT,
                          source_uri="shared.md")
        # Direct: REFERENCES (max weight) edge
        _add_edge(g, idx_a, idx_b, EdgeKind.REFERENCES)
        # AA: add enough shared neighbours to clip
        for i in range(20):
            shared = _add_node(g, node_id=f"s{i}", kind=NodeKind.SECTION)
            _add_edge(g, idx_a, shared)
            _add_edge(g, idx_b, shared)
        _invalidate_nx_cache(g)
        # Embedding: identical vectors
        emb = _StubEmbedder({
            "a": np.array([1.0, 0.0], dtype=np.float32),
            "b": np.array([1.0, 0.0], dtype=np.float32),
        })
        result = signal_relevance(g, [], "a", "b", embedder=emb)
        assert result.direct == pytest.approx(1.0)
        assert result.source_overlap == pytest.approx(1.0)
        assert result.adamic_adar == pytest.approx(1.0)
        assert result.type_affinity == pytest.approx(1.0)
        assert result.embedding == pytest.approx(1.0)
        assert result.combined == pytest.approx(1.0)

    def test_compute_pairwise_signals_returns_unweighted(self):
        g, idxs = _build_simple_graph()
        _add_edge(g, idxs["a"], idxs["b"], EdgeKind.REFERENCES)
        _invalidate_nx_cache(g)
        d = compute_pairwise_signals(g, [], "a", "b")
        for key in ("direct", "source_overlap", "adamic_adar",
                    "type_affinity", "embedding"):
            assert key in d
            assert 0.0 <= d[key] <= 1.0


class TestRelevanceNeighborhood:
    def test_sorted_descending_by_combined(self):
        g = rustworkx.PyDiGraph()
        idx_center = _add_node(g, node_id="center", kind=NodeKind.CONCEPT,
                               source_uri="x.md")
        idx_near = _add_node(g, node_id="near", kind=NodeKind.CONCEPT,
                             source_uri="x.md")
        idx_far = _add_node(g, node_id="far", kind=NodeKind.SECTION,
                            source_uri="y.md")
        _add_edge(g, idx_center, idx_near, EdgeKind.REFERENCES)
        _invalidate_nx_cache(g)
        results = relevance_neighborhood(g, [], "center", top_k=5)
        scores = [r.combined for r in results]
        assert scores == sorted(scores, reverse=True)
        assert results[0].node_b == "near"

    def test_top_k_respected(self):
        g = rustworkx.PyDiGraph()
        _add_node(g, node_id="center", kind=NodeKind.CONCEPT)
        for i in range(8):
            _add_node(g, node_id=f"n{i}", kind=NodeKind.SECTION)
        _invalidate_nx_cache(g)
        results = relevance_neighborhood(g, [], "center", top_k=3)
        assert len(results) == 3

    def test_skips_self(self):
        g, idxs = _build_simple_graph()
        results = relevance_neighborhood(g, [], "a", top_k=10)
        assert all(r.node_b != "a" for r in results)

    def test_candidate_pool_respected(self):
        g, idxs = _build_simple_graph()
        results = relevance_neighborhood(g, [], "a", top_k=10,
                                         candidate_pool=["b", "c"])
        returned = {r.node_b for r in results}
        assert returned == {"b", "c"}

    def test_top_k_zero_returns_empty(self):
        g, idxs = _build_simple_graph()
        assert relevance_neighborhood(g, [], "a", top_k=0) == []


# ---------------------------------------------------------------------------
# Integration tests
# ---------------------------------------------------------------------------


class TestBuilderIntegration:
    """Module 6: builder accepts the optional kwarg and stores it."""

    def test_builder_accepts_signal_config_kwarg(self, tmp_path):
        from unittest.mock import MagicMock
        from parrot.knowledge.graphindex.builder import GraphIndexBuilder

        persistence = MagicMock()
        embedder = MagicMock()
        cfg = SignalRelevanceConfig()
        builder = GraphIndexBuilder(
            persistence=persistence,
            embedder=embedder,
            output_dir=tmp_path,
            signal_config=cfg,
        )
        assert builder.signal_config is cfg

    def test_builder_default_signal_config_is_none(self, tmp_path):
        from unittest.mock import MagicMock
        from parrot.knowledge.graphindex.builder import GraphIndexBuilder

        builder = GraphIndexBuilder(
            persistence=MagicMock(),
            embedder=MagicMock(),
            output_dir=tmp_path,
        )
        assert builder.signal_config is None


class TestIntegration:
    def test_signals_on_assembled_graph(self):
        """Build a small graph via the real GraphAssembler and score
        three pairs against hand-computed expectations."""
        from parrot.knowledge.graphindex.assemble import GraphAssembler
        from parrot.knowledge.graphindex.schema import (
            UniversalEdge, UniversalNode, Provenance,
        )

        assembler = GraphAssembler(tenant_id="t")
        nodes = [
            UniversalNode(node_id="doc1", kind=NodeKind.DOCUMENT,
                          title="Doc 1", source_uri="d1.md"),
            UniversalNode(node_id="s1", kind=NodeKind.SECTION,
                          title="S1", source_uri="d1.md"),
            UniversalNode(node_id="s2", kind=NodeKind.SECTION,
                          title="S2", source_uri="d1.md"),
            UniversalNode(node_id="c1", kind=NodeKind.CONCEPT,
                          title="Compliance", source_uri="d1.md"),
        ]
        for n in nodes:
            assembler.add_node(n)
        edges = [
            UniversalEdge(source_id="doc1", target_id="s1", kind=EdgeKind.CONTAINS),
            UniversalEdge(source_id="doc1", target_id="s2", kind=EdgeKind.CONTAINS),
            UniversalEdge(source_id="s1", target_id="c1", kind=EdgeKind.REFERENCES),
            UniversalEdge(source_id="s2", target_id="c1", kind=EdgeKind.REFERENCES),
        ]
        for e in edges:
            assembler.add_edge(e)
        _invalidate_nx_cache(assembler.graph)

        # s1 and s2 share a source AND share a neighbour (c1) AND share a
        # neighbour (doc1) → AA should be > 0, source_overlap = 1.0.
        result = signal_relevance(assembler.graph, nodes, "s1", "s2")
        assert result.source_overlap == 1.0
        assert result.adamic_adar > 0.0
        assert "c1" in result.aa_neighbours
        assert "doc1" in result.aa_neighbours
        # Type affinity: SECTION × SECTION = 0.60 by default
        assert result.type_affinity == 0.60

    def test_neighborhood_finds_expected_top_results(self):
        from parrot.knowledge.graphindex.assemble import GraphAssembler
        from parrot.knowledge.graphindex.schema import (
            UniversalEdge, UniversalNode,
        )

        assembler = GraphAssembler(tenant_id="t")
        # Concept connected to 3 sections sharing 'd1.md'; one Symbol
        # on a different source with no edges.
        for i in range(3):
            assembler.add_node(UniversalNode(
                node_id=f"s{i}", kind=NodeKind.SECTION,
                title=f"S{i}", source_uri="d1.md",
            ))
        assembler.add_node(UniversalNode(
            node_id="c1", kind=NodeKind.CONCEPT,
            title="Compliance", source_uri="d1.md",
        ))
        assembler.add_node(UniversalNode(
            node_id="sym", kind=NodeKind.SYMBOL,
            title="foo()", source_uri="src/x.py",
        ))
        for i in range(3):
            assembler.add_edge(UniversalEdge(
                source_id="c1", target_id=f"s{i}", kind=EdgeKind.REFERENCES,
            ))
        _invalidate_nx_cache(assembler.graph)

        results = relevance_neighborhood(assembler.graph, [], "c1", top_k=3)
        returned = {r.node_b for r in results}
        # The three sections should appear; the symbol shouldn't make top-3.
        assert returned == {"s0", "s1", "s2"}
        # Symbol with source d1 mismatch is filtered out by relevance
        sym_score = next(
            (r for r in relevance_neighborhood(
                assembler.graph, [], "c1", top_k=10) if r.node_b == "sym"),
            None,
        )
        # Sym does appear (any other node makes it), but with lower score.
        assert sym_score is not None
        for r in results:
            assert r.combined >= sym_score.combined

    def test_aa_parity_with_networkx_reference(self):
        """AA wrapper must match nx.adamic_adar_index for the same pair."""
        import networkx as nx
        from parrot.knowledge.graphindex.signals import _to_undirected_networkx

        g = rustworkx.PyDiGraph()
        ids = ["a", "b", "c", "d", "e"]
        idxs = {n: _add_node(g, node_id=n) for n in ids}
        edges = [("a", "c"), ("a", "d"), ("b", "c"), ("b", "d"), ("b", "e")]
        for s, t in edges:
            _add_edge(g, idxs[s], idxs[t])
        _invalidate_nx_cache(g)

        # Reference AA via direct networkx
        ref_nx = nx.Graph()
        ref_nx.add_nodes_from(ids)
        ref_nx.add_edges_from(edges)
        [(_, _, ref_score)] = list(nx.adamic_adar_index(ref_nx, [("a", "b")]))

        # Our wrapper returns clipped/cap value. Reverse the normalisation.
        cap = 4.0
        score, _ = _adamic_adar_signal(g, "a", "b", cap=cap)
        recovered = score * cap
        assert recovered == pytest.approx(min(ref_score, cap), rel=1e-9)
