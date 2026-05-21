---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Feature Specification: GraphIndex Signal Relevance Model

**Feature ID**: FEAT-190
**Date**: 2026-05-21
**Author**: Jesús Lara
**Status**: draft
**Target version**: 0.x (GraphIndex is pre-production; no compat guarantees)

---

## 1. Motivation & Business Requirements

### Problem Statement

GraphIndex today answers *"is this node similar to that one?"* with a single
signal: cosine similarity of FAISS embeddings (`resolve.py:_compute_similarity`),
plus a binary cross-domain gate (`resolve.py:_get_extractor_domain`). That's
enough for "infer some MENTIONS edges" but it is **not** a relevance model —
it cannot answer the questions an LLM-Wiki agent and a Karpathy-style
"signal knowledge graph" actually need:

- *"Why are these two nodes connected?"* — there's no decomposed score, no
  "they share 3 source documents, have 2 Adamic-Adar neighbours, and both
  are Concepts."
- *"Rank the top-k nodes most relevant to X by graph signal, not just
  embedding distance."* — the closest thing is `GraphIndexToolkit.search_hybrid`
  which blends FAISS distance with raw degree (`toolkit.py:255-258`). Degree
  is a single signal; FAISS uses a placeholder hash encoder (`toolkit.py:402`).
- *"How strongly does this kind-pair tend to relate?"* — the schema has 6
  `NodeKind` values and 5 `EdgeKind` values, but `resolve.py:_KIND_TO_DOMAIN`
  collapses them to 4 buckets and applies a binary gate. There is no
  affinity matrix.

The **Signal Knowledge Graph** model fixes this with four explicit signals
combined into a transparent, decomposed relevance score:

1. **Direct links** — the existence and kind of edges between the two
   nodes (REFERENCES, CONTAINS, EXPLAINS, MENTIONS, DEFINES).
2. **Source overlap** — how many source documents the two nodes share
   (computed from `UniversalNode.source_uri`).
3. **Adamic-Adar** — graph-similarity from shared neighbours, weighting
   rare connectors more than hubs. Standard formula:
   `AA(u,v) = Σ_{w ∈ N(u) ∩ N(v)} 1 / log |N(w)|`.
4. **Type affinity** — a configurable `NodeKind × NodeKind` weight that
   captures domain knowledge ("a Concept linked to a Section is more
   meaningful than a Section linked to a Section").
5. **Embedding similarity** — cosine similarity between the two nodes'
   FAISS-backed embeddings (via the existing
   `GraphIndexEmbedder.get_embedding`). The signal-graph is *structural*
   by default, but composing structure with semantic similarity is the
   natural ensemble for an LLM-Wiki retriever — added in response to
   open question §8.3 resolved YES.

This spec also unblocks two downstream features:

- FEAT-191 (Louvain communities) needs a signal-weighted graph view so
  modularity isn't dominated by structural CONTAINS edges.
- FEAT-192 (write tools on `GraphIndexToolkit`) wants an LLM-callable
  `relevance(node_a, node_b)` and `neighborhood_by_relevance(node_id)`
  tool, both of which need this module.

### Goals

- Implement five orthogonal signal scorers, each callable independently
  and returning a value in `[0, 1]` after normalisation.
- Combine them into a single `SignalRelevance` Pydantic model that
  carries the five sub-scores AND the combined weighted score, so an
  LLM consumer (or the report generator) can explain *why*.
- Make the embedding signal **opt-in via dependency injection**: when
  no `GraphIndexEmbedder` is passed, the embedding signal is treated as
  absent and the remaining four weights are auto-renormalised to sum
  to 1.0. Callers don't need to twiddle weights to "disable" embeddings.
- Provide a configurable `NodeKind × NodeKind` type-affinity matrix
  with a sane default that reflects the wiki/code/skill domains.
- Expose three public functions:
  - `signal_relevance(graph, nodes, a, b, config)` — pairwise.
  - `relevance_neighborhood(graph, nodes, node_id, top_k, config)` —
    top-k most relevant nodes to a given one.
  - `compute_pairwise_signals(graph, nodes, a, b)` — raw signals
    without combination (for debugging / lint).
- All computations are pure functions over the in-memory rustworkx
  graph + the `UniversalNode` list; no DB calls, no FAISS calls.
- O(deg(u) + deg(v)) per pair for AA and source overlap; O(V) once
  for the global "degree of every node" cache that AA reuses.

### Non-Goals (explicitly out of scope)

- **Adding new EdgeKinds** — the four direct-link weights operate on
  the existing 5 `EdgeKind` values. (A new `RELATED_TO` for wiki
  cross-references is a FEAT-192 concern.)
- **Persistence of signal scores** — these are computed on demand
  from the assembled in-memory graph. No new ArangoDB collections.
- **Replacing `resolve.py`'s cross-domain inference** — `resolve.py`
  produces the *edges* this module then scores. Different layer.
- **LLM-driven affinity learning** — the default affinity matrix is
  hand-tuned. Learning weights from feedback is a follow-up.
- **Persistent caching of AA / source-overlap results** — caching is
  per-call (top-k uses one shared cache); a process-lifetime LRU is
  follow-up if profiling shows hot-paths.

---

## 2. Architectural Design

### Overview

Add a single new module — `parrot.knowledge.graphindex.signals` — that
operates on the *already assembled* `rustworkx.PyDiGraph` and the
flat `UniversalNode` list (the same inputs `analytics.py` takes today).
The module exports pure functions plus two Pydantic models
(`SignalRelevanceConfig`, `SignalRelevance`). Nothing else in
GraphIndex changes; new code only.

### Component Diagram

```
                ┌────────────────────────────────┐
                │  GraphIndexBuilder.build       │
                │  (assemble + resolve done)     │
                └───────────────┬────────────────┘
                                │
              ┌─────────────────┼─────────────────┐
              ▼                 ▼                 ▼
       ┌────────────┐   ┌────────────┐    ┌──────────────┐
       │ analytics  │   │  signals   │    │ communities  │
       │ (existing) │   │   (NEW)    │    │   (FEAT-191) │
       └────────────┘   └─────┬──────┘    └──────────────┘
                              │
                  ┌───────────┴──────────┐
                  ▼                      ▼
         signal_relevance(a,b)   relevance_neighborhood(x, top_k)
                  │                      │
                  ▼                      ▼
        SignalRelevance Pydantic model (decomposed)
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `rustworkx.PyDiGraph` (from `assemble.GraphAssembler.graph`) | reuse | Passed in as the canonical graph reference. No mutation. |
| `UniversalNode` list (from `BuildResult` / builder pipeline) | reuse | Read `source_uri`, `kind`, `node_id` only. |
| `UniversalEdge.kind` (`schema.EdgeKind`) | reuse | Direct-link signal reads the kind off edge payloads in the graph. |
| `analytics.py` | sibling | This module sits next to it in the same directory. No imports between them; both are read-only over the graph. |
| `GraphIndexBuilder` | optional | Builder gets an opt-in `compute_signal_relevance: bool = False` flag that runs `signal_relevance` for a sample to populate analytics — but the *default is off* (cost concern). Default invocation is by FEAT-192 toolkit methods, not the builder. |
| `networkx` | reuse | Already a project dep (`pyproject.toml:205`). Used here only for Adamic-Adar via `nx.adamic_adar_index` to avoid hand-rolling the formula. Conversion from rustworkx → networkx happens *only when AA is requested* and is cached for top-k calls. |

### Data Models

```python
# parrot/knowledge/graphindex/signals.py

from pydantic import BaseModel, Field, ConfigDict
from parrot.knowledge.graphindex.schema import EdgeKind, NodeKind


class SignalRelevanceConfig(BaseModel):
    """Configuration for the five-signal relevance scorer.

    Weights sum to 1.0 in the default configuration so the combined
    score lies in [0, 1] when each signal is normalised to [0, 1].
    The validator enforces ``abs(sum(weights) - 1.0) < 1e-6`` so
    misconfigured callers fail loudly.

    When ``signal_relevance(...)`` is invoked WITHOUT a
    ``GraphIndexEmbedder``, the embedding signal is dropped and the
    remaining four weights are auto-renormalised inside the scorer
    (the config itself is unchanged — immutable, frozen).
    """

    w_direct: float = Field(0.30, ge=0.0, le=1.0)
    w_source_overlap: float = Field(0.15, ge=0.0, le=1.0)
    w_adamic_adar: float = Field(0.20, ge=0.0, le=1.0)
    w_type_affinity: float = Field(0.10, ge=0.0, le=1.0)
    w_embedding: float = Field(0.25, ge=0.0, le=1.0)

    # Per-edge-kind weight for the direct-link signal. Missing kinds
    # default to 0.0. Caller can override (e.g. boost EXPLAINS to 1.0
    # for code-rationale workflows).
    edge_kind_weights: dict[EdgeKind, float] = Field(
        default_factory=lambda: {
            EdgeKind.CONTAINS: 0.30,
            EdgeKind.REFERENCES: 1.00,
            EdgeKind.DEFINES: 0.80,
            EdgeKind.MENTIONS: 0.70,
            EdgeKind.EXPLAINS: 0.90,
        }
    )

    # Symmetric NodeKind × NodeKind affinity in [0, 1]. The default
    # encodes "Concept↔Concept and Section↔Concept are strongly
    # related; Symbol↔Section less so". Order-independent: the
    # scorer looks up min(a, b)→max(a, b) before reading.
    type_affinity: dict[tuple[NodeKind, NodeKind], float] = Field(
        default_factory=lambda: _default_type_affinity()
    )

    # AA normalisation cap. Raw AA grows unboundedly with shared-neighbour
    # count; we clip at this value and divide. 4.0 was the median 95th
    # percentile across the smoke fixture during design.
    adamic_adar_cap: float = 4.0

    # Maximum source-overlap denominator floor (so a single shared
    # source between two single-source nodes doesn't dominate).
    source_overlap_min_denom: int = 1

    model_config = ConfigDict(extra="forbid", frozen=True)


class SignalRelevance(BaseModel):
    """Decomposed pairwise relevance result.

    Combined score is the weighted sum of the normalised signals
    using ``config.w_*`` (with weights auto-renormalised when the
    embedding signal is absent). All sub-scores are in [0, 1] so an
    LLM consumer can read this verbatim ("connected because they
    share 0.83 of source overlap, have embedding sim 0.71, and type
    affinity 0.6").
    """

    node_a: str
    node_b: str
    direct: float                # in [0, 1]
    source_overlap: float        # in [0, 1] — Jaccard over source_uri sets
    adamic_adar: float           # in [0, 1] — AA / cap, clipped
    type_affinity: float         # in [0, 1]
    embedding: float             # in [0, 1] — cosine similarity (0.0 if no embedder)
    combined: float              # weighted sum

    # Raw sub-signal data so consumers (especially the LLM) can read
    # "why" without re-running the scorer.
    direct_edges: list[dict]     # [{"kind": ..., "direction": ...}, ...]
    shared_sources: list[str]    # source_uris common to both nodes
    aa_neighbours: list[str]     # node_ids that contributed to AA
    embedding_available: bool    # whether an embedder was supplied AND
                                 # both nodes had embeddings

    model_config = ConfigDict(frozen=True)
```

### New Public Interfaces

```python
# parrot/knowledge/graphindex/signals.py

def signal_relevance(
    graph: rustworkx.PyDiGraph,
    nodes: list[UniversalNode],
    node_a: str,
    node_b: str,
    config: Optional[SignalRelevanceConfig] = None,
    embedder: Optional[GraphIndexEmbedder] = None,
) -> SignalRelevance:
    """Pairwise five-signal relevance.

    When ``embedder`` is None (or when either node has no embedding),
    the embedding signal is treated as absent: its weight is dropped
    from the combination and the remaining four weights are
    auto-renormalised. ``SignalRelevance.embedding`` is 0.0 in that
    case and ``embedding_available`` is False.

    Raises:
        KeyError: If either node_id is not in the graph.
    """


def relevance_neighborhood(
    graph: rustworkx.PyDiGraph,
    nodes: list[UniversalNode],
    node_id: str,
    top_k: int = 10,
    config: Optional[SignalRelevanceConfig] = None,
    candidate_pool: Optional[list[str]] = None,
    embedder: Optional[GraphIndexEmbedder] = None,
) -> list[SignalRelevance]:
    """Top-k most relevant nodes to ``node_id`` by combined score.

    Candidate pool defaults to every other node in the graph; callers
    that pre-filter (e.g. "only Concept nodes") pass an explicit pool.
    """


def compute_pairwise_signals(
    graph: rustworkx.PyDiGraph,
    nodes: list[UniversalNode],
    node_a: str,
    node_b: str,
    embedder: Optional[GraphIndexEmbedder] = None,
) -> dict[str, float]:
    """Raw five signals without combination. Cheap building block.

    Returned dict has keys ``direct``, ``source_overlap``,
    ``adamic_adar``, ``type_affinity``, ``embedding``. Same
    normalisation as the full scorer; just no weighting / no
    Pydantic wrapper. ``embedding`` is 0.0 when no embedder is
    supplied or when either node lacks an embedding.
    """


def _default_type_affinity() -> dict[tuple[NodeKind, NodeKind], float]:
    """Default NodeKind × NodeKind affinity matrix.

    Encoded for the wiki/code/skill mix already in the schema:
      CONCEPT × CONCEPT       = 1.00
      CONCEPT × SECTION       = 0.85
      CONCEPT × DOCUMENT      = 0.70
      SECTION × SECTION       = 0.60
      DOCUMENT × DOCUMENT     = 0.50
      SECTION × DOCUMENT      = 0.70
      SYMBOL  × SYMBOL        = 0.80
      SYMBOL  × RATIONALE     = 0.95
      SYMBOL  × SECTION       = 0.50   # code-to-doc bridge
      SKILL   × SECTION       = 0.60
      SKILL   × SKILL         = 0.70
      …all unlisted pairs     = 0.30
    """
```

---

## 3. Module Breakdown

### Module 1: `signals` module skeleton + Pydantic models
- **Path**: `packages/ai-parrot/src/parrot/knowledge/graphindex/signals.py` (new)
- **Responsibility**: Define `SignalRelevanceConfig`, `SignalRelevance`,
  `_default_type_affinity`, and the public function signatures. No
  computation logic yet.
- **Depends on**: nothing new; reads `schema.EdgeKind`, `schema.NodeKind`.

### Module 2: Direct-link + source-overlap signals
- **Path**: same file (added incrementally).
- **Responsibility**:
  - `_direct_signal(graph, node_idx_a, node_idx_b, weights)` — scan
    out-edges of `a` for edges to `b` and vice-versa; sum the
    per-kind weights from config; normalise by the maximum possible
    weight (sum of all kind weights) so the result sits in [0, 1].
  - `_source_overlap_signal(node_a, node_b)` — Jaccard over the
    `source_uri` set of each node (single-element set for the
    typical case; consumers can extend this by setting a multi-source
    domain_tag in the future).
- **Depends on**: Module 1.

### Module 3: Adamic-Adar via networkx bridge
- **Path**: same file.
- **Responsibility**:
  - `_to_networkx(graph)` — one-shot conversion of the rustworkx
    PyDiGraph to a `networkx.Graph` (undirected for AA), cached on
    the graph object via a `WeakKeyDictionary` keyed by `id(graph)`.
  - `_adamic_adar_signal(nx_graph, node_a, node_b, cap)` — call
    `nx.adamic_adar_index(G, [(a, b)])` (returns an iterator),
    take the score, clip at `cap`, divide by `cap`.
- **Depends on**: Module 1.

### Module 3b: Embedding similarity signal
- **Path**: same file.
- **Responsibility**:
  - `_embedding_signal(embedder, node_id_a, node_id_b)` — calls
    `embedder.get_embedding(node_id_a)` and `(node_id_b)`; returns
    `(score, available)` where `score = max(0.0, cosine_sim)` and
    `available = True` iff both embeddings were resolvable.
  - Returns `(0.0, False)` when `embedder is None` or either node
    has no embedding (matches the `embedding_available` contract on
    `SignalRelevance`).
  - Same math as `resolve.py:_compute_similarity`
    (`resolve.py:157-189`) but synchronous — `get_embedding` is sync
    (`embed.py:157`) and there's no reason to await.
- **Depends on**: Module 1.

### Module 4: Type affinity lookup + combined scorer
- **Path**: same file.
- **Responsibility**:
  - `_type_affinity(node_a, node_b, matrix)` — order-independent
    lookup; default 0.30 for unlisted pairs.
  - `_effective_weights(config, embedding_available)` — when the
    embedding signal isn't available, redistribute `w_embedding`
    proportionally across the other four weights so they still sum
    to 1.0. When it IS available, return `config.w_*` as-is.
  - `signal_relevance(...)` — combine all five; build `SignalRelevance`
    with sub-scores + raw signal data (shared sources list,
    AA contributing neighbours, edge list) + `embedding_available`.
  - `compute_pairwise_signals(...)` — same path without weights.
- **Depends on**: Modules 1-3b.

### Module 5: Neighborhood top-k
- **Path**: same file.
- **Responsibility**: `relevance_neighborhood(...)` — iterate the
  candidate pool, call `signal_relevance` for each pair, sort by
  combined score, return top-k. AA reuses the same cached networkx
  view across the loop. Embedder (if any) is passed straight through.
- **Depends on**: Module 4.

### Module 6: Optional builder integration (default-off)
- **Path**: `packages/ai-parrot/src/parrot/knowledge/graphindex/builder.py` (modify)
- **Responsibility**: Add optional `signal_config:
  Optional[SignalRelevanceConfig] = None` ctor parameter. **No
  automatic invocation** — the builder just stores it so downstream
  code (analytics report, FEAT-192 toolkit) can read the configured
  weights without re-instantiating defaults. Default behaviour
  unchanged.
- **Depends on**: Module 1.

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_config_weights_must_sum_to_one` | 1 | Mis-weighted config raises `ValidationError`. |
| `test_config_frozen` | 1 | Mutating a built config raises (immutability). |
| `test_default_type_affinity_symmetric` | 1 | `affinity[(A, B)] == affinity[(B, A)]` for every key. |
| `test_direct_signal_no_edges_returns_zero` | 2 | Two nodes with no edges between them → direct=0. |
| `test_direct_signal_single_references_edge` | 2 | One REFERENCES edge → normalised to its weight / max-weight. |
| `test_direct_signal_bidirectional_counts_once` | 2 | A↔B with one REFERENCES edge each way is scored once, not double. |
| `test_source_overlap_jaccard_identical` | 2 | Same source_uri on both → 1.0. |
| `test_source_overlap_no_overlap_zero` | 2 | Different source_uris → 0.0. |
| `test_adamic_adar_no_shared_neighbours_zero` | 3 | Two disconnected nodes → AA=0. |
| `test_adamic_adar_shared_neighbour_positive` | 3 | One shared neighbour with degree 2 → AA = 1/log(2) > 0. |
| `test_adamic_adar_clipped_to_cap` | 3 | Many shared neighbours → AA clipped to 1.0. |
| `test_adamic_adar_networkx_cache_reused` | 3 | Two calls on the same graph instance do NOT rebuild the networkx view (mock to assert call count). |
| `test_type_affinity_concept_concept_high` | 4 | Default matrix returns 1.0 for CONCEPT-CONCEPT. |
| `test_type_affinity_order_independent` | 4 | `(SECTION, CONCEPT) == (CONCEPT, SECTION)`. |
| `test_type_affinity_unlisted_pair_default` | 4 | Unknown pair → 0.30 (configurable default). |
| `test_embedding_signal_uses_embedder` | 3b | With a stub embedder returning known vectors, the signal equals their cosine similarity. |
| `test_embedding_signal_missing_embedding_returns_zero` | 3b | When one node has no embedding, score=0.0 and available=False. |
| `test_embedding_signal_no_embedder_returns_zero` | 3b | `embedder=None` → score=0.0 and available=False (no exception). |
| `test_effective_weights_renormalise_when_no_embedding` | 4 | When embedding is absent, the other four weights are scaled by `1 / (1 - w_embedding)` so they sum to 1.0. |
| `test_effective_weights_pass_through_when_embedding_available` | 4 | When embedding IS available, all five weights are used as-is. |
| `test_signal_relevance_combines_with_config_weights` | 4 | All-1 sub-scores → combined == 1.0 with default weights (with embedder). |
| `test_signal_relevance_decomposed_output` | 4 | Returned `SignalRelevance` carries the raw `direct_edges`, `shared_sources`, `aa_neighbours`, and `embedding_available`. |
| `test_signal_relevance_unknown_node_raises_keyerror` | 4 | Missing node_id raises clean `KeyError`, not a downstream crash. |
| `test_compute_pairwise_signals_returns_unweighted` | 4 | Raw signals match the inputs to the weighted combination. |
| `test_compute_pairwise_signals_includes_embedding` | 4 | Returned dict has the `embedding` key. |
| `test_relevance_neighborhood_top_k_sorted` | 5 | Top-k results sorted by combined desc, length ≤ k. |
| `test_relevance_neighborhood_candidate_pool_respected` | 5 | When `candidate_pool=[X, Y]`, only X and Y are scored. |
| `test_relevance_neighborhood_skips_self` | 5 | Node never returned as relevant to itself. |
| `test_builder_accepts_signal_config_kwarg` | 6 | `GraphIndexBuilder(signal_config=...)` stores the config. |

### Integration Tests

| Test | Description |
|---|---|
| `test_signals_on_assembled_graph` | Build a tiny 6-node mixed-kind graph via `GraphAssembler`; run `signal_relevance` between three pairs; assert the per-signal values match hand-computed expectations to within 1e-6. |
| `test_neighborhood_finds_expected_top_3` | Fixture: 1 Concept node + 3 Section nodes with shared sources + 1 unrelated Symbol; `relevance_neighborhood(concept_id, top_k=3)` returns the three sections in source-overlap order. |
| `test_signals_match_networkx_reference` | For 20 random Erdős-Rényi edges, the AA values from our wrapper match `nx.adamic_adar_index` on the same nodes within 1e-9 (sanity check the cache + clipping logic doesn't drift). |
| `test_signals_with_embedder_match_resolve_similarity` | Stub a tiny embedder; assert the embedding sub-score for two known nodes matches `resolve._compute_similarity(a, b, embedder)` to within 1e-9 (parity with existing cross-domain inference). |

### Test Data / Fixtures

```python
# tests/knowledge/graphindex/fixtures/signal_graph.py

@pytest.fixture
def tiny_signal_graph() -> tuple[rustworkx.PyDiGraph, list[UniversalNode]]:
    """6 nodes: Concept(c1), Section(s1, s2, s3 — shared source 'doc.md'),
    Section(s4 — source 'other.md'), Symbol(sym1).

    Edges:
        c1 --REFERENCES--> s1
        c1 --REFERENCES--> s2
        s1 --CONTAINS-->  s2
        sym1 --EXPLAINS--> s4
    """
    ...

@pytest.fixture
def signal_config_uniform() -> SignalRelevanceConfig:
    """All weights at 0.25 so each signal contributes equally —
    makes unit-test assertions easier to read."""
    ...
```

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] `parrot.knowledge.graphindex.signals` exists with the public
      surface defined in §2 — three functions, two Pydantic models,
      `_default_type_affinity`.
- [ ] `SignalRelevanceConfig` rejects misweighted configs at validation
      time (sum of `w_*` must equal 1.0 ± 1e-6).
- [ ] `signal_relevance(graph, nodes, a, b)` returns a fully-populated
      `SignalRelevance` with all five sub-scores in [0, 1] and the
      combined score = the weighted sum of the five (or four, with
      auto-renormalisation, when no embedder is supplied).
- [ ] `signal_relevance(..., embedder=...)` populates the embedding
      sub-score from `GraphIndexEmbedder.get_embedding`; sets
      `embedding_available=True` iff both nodes have embeddings.
- [ ] When `embedder=None` or either node has no embedding, the four
      remaining weights are auto-renormalised so the combined score
      still lies in [0, 1] and the result is interpretable.
- [ ] `relevance_neighborhood(graph, nodes, x, top_k=10)` returns
      results sorted by combined score descending, length ≤ top_k,
      never includes `x` itself.
- [ ] Each `SignalRelevance` carries the raw `direct_edges`,
      `shared_sources`, `aa_neighbours`, and `embedding_available`
      for downstream "why" consumption.
- [ ] AA is computed via `networkx.adamic_adar_index`; the
      rustworkx → networkx conversion is cached per-graph so a top-k
      call does NOT rebuild it for every pair.
- [ ] Default type-affinity matrix is symmetric and covers all 6
      `NodeKind × NodeKind` self-pairs plus the documented bridges.
- [ ] `GraphIndexBuilder` accepts `signal_config=` kwarg (default
      `None`); no behavioural change when omitted.
- [ ] All unit + integration tests pass:
      `pytest tests/knowledge/graphindex/test_signals.py -v`.
- [ ] No new external dependencies (networkx is already at
      `pyproject.toml:205`; rustworkx already present).
- [ ] All previously-passing tests under
      `tests/knowledge/graphindex/` still pass.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> Every entry here was verified by reading the file at the cited line
> on 2026-05-21.

### Verified Imports

```python
# Available today on the feature branch:
from parrot.knowledge.graphindex.schema import (
    EdgeKind,                 # schema.py:52
    NodeKind,                 # schema.py:32
    UniversalEdge,            # schema.py:101
    UniversalNode,            # schema.py:70
)
from parrot.knowledge.graphindex.assemble import GraphAssembler       # assemble.py:24
from parrot.knowledge.graphindex.embed import GraphIndexEmbedder      # embed.py:22
import rustworkx                                                       # assemble.py:17
import networkx as nx           # used elsewhere (concept_catalog/service.py:20)
```

### Existing Class Signatures

```python
# packages/ai-parrot/src/parrot/knowledge/graphindex/schema.py
class NodeKind(str, Enum):           # line 32
    DOCUMENT = "document"
    SECTION = "section"
    SYMBOL = "symbol"
    CONCEPT = "concept"
    RATIONALE = "rationale"
    SKILL = "skill"

class EdgeKind(str, Enum):           # line 52
    CONTAINS = "contains"
    REFERENCES = "references"
    DEFINES = "defines"
    MENTIONS = "mentions"
    EXPLAINS = "explains"

class UniversalNode(BaseModel):      # line 70
    node_id: str
    kind: NodeKind
    title: str
    source_uri: str                  # line 92 — read by source-overlap signal
    summary: Optional[str] = None
    domain_tags: dict = Field(default_factory=dict)

class UniversalEdge(BaseModel):      # line 101
    source_id: str
    target_id: str
    kind: EdgeKind                   # line 119
```

```python
# packages/ai-parrot/src/parrot/knowledge/graphindex/assemble.py
class GraphAssembler:                # line 24
    self.graph: rustworkx.PyDiGraph  # line 37
    self._node_index_map: dict[str, int]  # line 38

    def add_node(self, node: UniversalNode) -> int: ...   # line 45
    def add_edge(self, edge: UniversalEdge) -> Optional[int]: ...  # line 77
    # Node payload stored in graph[idx]: dict with node_id, kind, title,
    # source_uri, content_ref, summary, embedding_ref, domain_tags,
    # parent_id, provenance (see assemble.py:54-65).
    # Edge payload stored in graph.out_edges()[..][2]: dict with
    # source_id, target_id, kind, provenance, confidence
    # (see assemble.py:100-106).
```

```python
# packages/ai-parrot/src/parrot/knowledge/graphindex/builder.py
class GraphIndexBuilder:             # line 49
    def __init__(
        self,
        persistence: GraphIndexPersistence,
        embedder: GraphIndexEmbedder,
        output_dir: Path,
        ignore_file: Optional[Path] = None,
        resolution_config: Optional[ResolutionConfig] = None,
        pageindex_toolkit: Optional[PageIndexToolkit] = None,   # line 82
    ) -> None: ...                   # line 75
```

```python
# packages/ai-parrot/src/parrot/knowledge/graphindex/embed.py
class GraphIndexEmbedder:            # line 22
    def get_embedding(
        self, node_id: str,
    ) -> Optional[np.ndarray]: ...   # line 157
    # Returns the L2-normalised vector for node_id, or None when
    # the node hasn't been embedded. Synchronous.
```

```python
# packages/ai-parrot/src/parrot/knowledge/graphindex/resolve.py
# Reference for the cosine-similarity math we mirror (NOT imported
# from there; signals.py keeps its own sync copy to avoid coupling).
async def _compute_similarity(
    node_id_a: str,
    node_id_b: str,
    embedder: object,
) -> Optional[float]: ...           # resolve.py:157
```

```python
# Third-party (verified at runtime, version pin from pyproject.toml:205):
import networkx as nx
nx.adamic_adar_index(G, ebunch=None) -> Iterator[tuple[node, node, float]]
# Requires an undirected nx.Graph; we convert from rustworkx.PyDiGraph
# with edges collapsed (a→b and b→a become a single undirected edge).
```

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `signal_relevance(...)` | `GraphAssembler.graph` | Reads node payloads via `graph[idx]`, edges via `graph.out_edges(idx)` | `assemble.py:54, 100` |
| `_source_overlap_signal` | `UniversalNode.source_uri` | Field read | `schema.py:92` |
| `_type_affinity` | `UniversalNode.kind` | Field read | `schema.py:90` |
| `_adamic_adar_signal` | `networkx.adamic_adar_index` | function call | `pyproject.toml:205` |
| `GraphIndexBuilder.signal_config` | Storage only — no auto-invocation | constructor kwarg | `builder.py:75` |

### Does NOT Exist (Anti-Hallucination)

- ~~`parrot.knowledge.graphindex.signals`~~ — this spec creates it.
- ~~`SignalRelevance`, `SignalRelevanceConfig`~~ — new in this spec.
- ~~`rustworkx.adamic_adar_index`~~ — not in rustworkx 0.17 (verified
  via `dir(rustworkx)`). Use `networkx.adamic_adar_index` instead.
- ~~`rustworkx.community.*`~~ — community detection is FEAT-191, not
  this spec; rustworkx 0.17 has no community module anyway.
- ~~`UniversalNode.related_node_ids`~~ — no such field; relations live
  on edges, not on the node payload.
- ~~`GraphIndexBuilder.compute_signals()`~~ — no auto-invocation in
  this spec; the builder only stores the config.
- ~~`SignalRelevanceConfig.embedding_weight`~~ — embeddings are NOT a
  signal here; cosine similarity stays in `resolve.py`.

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- **Pure functions over `(graph, nodes, ...)`** — same shape as
  `analytics.compute_analytics` (`analytics.py:66`). No instance state.
- **Pydantic models for the public contract** — matches FEAT-189
  conventions and the rest of the codebase.
- **`frozen=True` config models** — so callers can pass them across
  async boundaries without aliasing concerns.
- **`logging.getLogger(__name__)` per module** — same pattern as
  `analytics.py:28` and `resolve.py:28`.
- **Defensive normalisation** — every signal returns a value in
  [0, 1]; the combination is therefore in [0, 1] as long as weights
  sum to 1 (enforced).

### Known Risks / Gotchas

- **AA on large graphs is O(V × E) in the worst case** — the
  per-top-k loop calls AA `|candidate_pool|` times. For a 10k-node
  graph with default candidate_pool=all-nodes this is ~10k AA calls.
  We accept this for v1 because (a) graphs are typically <2k nodes
  per tenant today, (b) the networkx implementation is C-backed.
  Mitigation knob: callers pre-filter `candidate_pool`. Profiling
  hook documented as a follow-up.
- **Multi-edge collapsing** — `_to_networkx` converts a directed
  multi-graph to an undirected simple graph. Two REFERENCES edges
  between the same pair (different provenance) collapse into one
  networkx edge. AA doesn't care about kind, so this is fine — but
  callers expecting AA to distinguish edge kinds are wrong, and
  the docstring says so explicitly.
- **NodeKind enum value vs. enum object** — when reading
  `graph[idx]["kind"]` the value is the string ("section"), not the
  `NodeKind` instance. The type-affinity lookup must accept both
  via a small `NodeKind(s)` cast at the boundary.
- **Source overlap for synthetic nodes** — `make_folder_node`
  (PageIndex `tree_ops.py:24`) creates nodes with empty
  `source_uri`. Two such nodes would have full Jaccard overlap on
  the empty set; we explicitly return 0.0 when both sources are
  falsy to avoid this trap.
- **Zero-weight signals** — a caller can disable a signal by setting
  its weight to 0. The validator allows this. When all four are
  zero the validator rejects (`sum != 1.0`).
- **AA returns 0.0 for nodes not in the networkx graph** — can
  happen if a node has no edges at all (rustworkx keeps it; networkx
  drops isolated nodes during conversion if we don't `add_node`
  them explicitly). Mitigation: always `add_node` every rustworkx
  index into the networkx graph during conversion.

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| `networkx` | `>=3.0` (already pinned at `pyproject.toml:205`) | Adamic-Adar via `nx.adamic_adar_index`. |
| `rustworkx` | already a transitive dep | In-memory graph (no new pin). |

No new dependencies.

---

## 8. Open Questions

- [ ] **Default `w_*` weights** — *Owner: implementation*. Spec proposes
      0.40/0.20/0.25/0.15. These were eyeballed; tune against the
      FEAT-189 compliance demo if early UX feedback says "too much
      direct" or "AA dominates."
- [ ] **Default `type_affinity` for SKILL × other kinds** — *Owner:
      implementation*. SKILL-CONCEPT, SKILL-DOCUMENT not in the listed
      defaults; document the fallback (0.30) and revisit if the skills
      demo wants them.
- [x] **Should we expose a `with_embeddings` hook to compose external
      cosine similarity?** — *Resolved YES, in scope*: embeddings are
      now the fifth signal (`w_embedding=0.25` default), opt-in via
      a `GraphIndexEmbedder` passed to the scorer. When omitted, the
      remaining four weights auto-renormalise to 1.0 so the combined
      score stays interpretable.

---

## Worktree Strategy

- **Default isolation**: `per-spec` — single worktree at
  `.claude/worktrees/feat-190-graphindex-signal-relevance`.
- **Why not parallel**: every module after Module 1 reads the
  Pydantic models defined there; the conversion cache in Module 3
  is consumed by Modules 4-5. Parallel tasks would contend on the
  same file.
- **Cross-feature dependencies**: none. Greenfield module.
- **Suggested task order**: Modules 1 → 2 → 3 → 4 → 5 → 6.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-05-21 | Jesús Lara | Initial draft. |
