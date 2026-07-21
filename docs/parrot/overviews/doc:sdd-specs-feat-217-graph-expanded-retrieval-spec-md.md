---
type: Wiki Overview
title: 'Feature Specification: Graph-Expanded Retrieval Pipeline'
id: doc:sdd-specs-feat-217-graph-expanded-retrieval-spec-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: PageIndex hybrid search (FEAT-237) operates within a single document tree
  -- it does BM25 + optional vec_rank + embedding_walk but never crosses document
  boundaries via graph topology. GraphIndex toolkit has `get_neighborhood()` and `neighborhood_by_relevance()`
  but these are sta
relates_to:
- concept: mod:parrot.knowledge.graphindex.communities
  rel: mentions
- concept: mod:parrot.knowledge.graphindex.embed
  rel: mentions
- concept: mod:parrot.knowledge.graphindex.schema
  rel: mentions
- concept: mod:parrot.knowledge.graphindex.signals
  rel: mentions
- concept: mod:parrot.knowledge.pageindex.hybrid_search
  rel: mentions
---

---
type: feature
base_branch: dev
---

# Feature Specification: Graph-Expanded Retrieval Pipeline

**Feature ID**: FEAT-217
**Date**: 2026-06-16
**Author**: Jesus Lara
**Status**: approved
**Target version**: 0.next
**Related**: FEAT-190 (signal-relevance), FEAT-191 (louvain-communities), FEAT-237 (pageindex-embedding-router)

---

## 1. Motivation & Business Requirements

### Problem Statement

PageIndex hybrid search (FEAT-237) operates within a single document tree -- it does BM25 + optional vec_rank + embedding_walk but never crosses document boundaries via graph topology. GraphIndex toolkit has `get_neighborhood()` and `neighborhood_by_relevance()` but these are standalone tools, not integrated into a retrieval pipeline.

nashsu/llm_wiki demonstrates the value of graph-expanded retrieval: seed nodes from keyword/vector search, 2-hop traversal using signal relevance, decay per hop, budget-controlled result assembly. This pattern improved recall from 58.2% to 71.4% in their benchmarks.

AI-Parrot has all the building blocks (hybrid search, signal relevance, community detection) but no coordinator that chains them into a unified retrieval pipeline.

### Goals

- New `GraphExpandedRetriever` class that composes existing search + signal + community components (resolved design decision Q2: separate class, not integrated into hybrid_search.py)
- 4-phase retrieval: seed search, graph expansion, community context, result assembly
- Configurable exponential decay per hop: `score * 0.7^hop` by default (resolved Q3)
- Budget control: cap total tokens, allocate proportionally
- Community annotations on results (community_id, cohesion)
- Decomposed scoring: each result carries search_score, signal_score, decay_factor, combined_score

### Non-Goals (explicitly out of scope)

- Not modifying HybridPageIndexSearch (FEAT-237) -- this composes it
- Not modifying signal_relevance() (FEAT-190) -- this calls it
- Not adding new graph algorithms -- this chains existing ones
- Cross-index search (searching across multiple PageIndex trees simultaneously) -- future scope

---

## 2. Architectural Design

### Overview

A new `GraphExpandedRetriever` class in `packages/ai-parrot/src/parrot/knowledge/graphindex/retriever.py` that orchestrates a 4-phase retrieval pipeline:

```
Phase 1: Seed Search
  Input: query string + search config
  Action: Run HybridPageIndexSearch.search() OR GraphIndexEmbedder.search_similar()
  Output: Top-K seed nodes with search_score in [0, 1]

Phase 2: Graph Expansion
  Input: seed nodes + expansion config
  Action: For each seed, compute signal_relevance() to neighbors at depth 1..max_hops
  Apply: decay_factor = decay_base ^ hop_distance (default 0.7^hop)
  Score: combined = search_score * decay_factor * signal_relevance.combined
  Merge: Deduplicate by node_id, keep highest combined score
  Output: Expanded node list with decomposed scores

Phase 3: Community Context (optional)
  Input: expanded nodes + CommunitiesResult (if available)
  Action: Annotate each node with community_id, cohesion
  Optionally: Include community centroid nodes if not already in results
  Output: Annotated node list

Phase 4: Result Assembly
  Input: annotated nodes + budget config
  Action: Sort by combined score, apply token budget, format results
  Output: GraphRetrievalResult with ranked nodes + metadata
```

### Component Diagram

```
                    +-------------------------------+
                    |   GraphExpandedRetriever       |
                    |                               |
                    |   search(query, config)        |
                    |     -> Phase 1 (seed)          |
                    |     -> Phase 2 (expand)        |
                    |     -> Phase 3 (community)     |
                    |     -> Phase 4 (assemble)      |
                    +---+----------+-----------+----+
                        |          |           |
          +-------------v--+  +---v------+  +-v-----------------+
          | HybridPageIndex|  | signal_  |  | detect_           |
          | Search (237)   |  | relevance|  | communities       |
          | OR             |  | (190)    |  | (191)             |
          | GraphIndex     |  |          |  |                   |
          | Embedder       |  |          |  |                   |
          +----------------+  +----------+  +-------------------+
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `HybridPageIndexSearch.search()` | composes | Phase 1 seed search (PageIndex path) |
| `GraphIndexEmbedder.search_similar()` | composes | Phase 1 seed search (GraphIndex path) |
| `signals.signal_relevance()` | calls | Phase 2 pairwise signal computation |
| `signals.relevance_neighborhood()` | calls | Phase 2 efficient neighborhood scoring |
| `communities.CommunitiesResult` | reads | Phase 3 community annotation |
| `schema.UniversalNode` | reads | Node metadata access |
| `GraphIndexToolkit` | extends | New `search_with_expansion()` tool |

### Data Models

```python
from pydantic import BaseModel, Field
from typing import Optional


class ExpansionConfig(BaseModel):
    """Configuration for graph expansion phase."""
    max_hops: int = Field(default=2, ge=1, le=4)
    decay_base: float = Field(default=0.7, gt=0.0, le=1.0)
    min_signal_threshold: float = Field(default=0.1, ge=0.0)
    max_expanded_nodes: int = Field(default=50, ge=1)
    include_community_centroids: bool = False


class BudgetConfig(BaseModel):
    """Token budget for result assembly."""
    max_tokens: int = Field(default=8000, ge=100)
    tokens_per_node_estimate: int = Field(default=200, ge=10)


class ScoredNode(BaseModel):
    """A node with decomposed retrieval scores."""
    node_id: str
    title: str
    kind: str
    search_score: float = 0.0
    signal_score: float = 0.0
    decay_factor: float = 1.0
    combined_score: float = 0.0
    hop_distance: int = 0
    community_id: Optional[str] = None
    community_cohesion: Optional[float] = None
    is_seed: bool = False
    source_uri: Optional[str] = None
    summary: Optional[str] = None


class GraphRetrievalResult(BaseModel):
    """Complete retrieval result with metadata."""
    query: str
    nodes: list[ScoredNode]
    total_candidates: int = 0
    nodes_expanded: int = 0
    communities_touched: int = 0
    budget_used: int = 0
    budget_limit: int = 0
    truncated: bool = False
```

### New Public Interfaces

```python
class GraphExpandedRetriever:
    def __init__(
        self,
        graph: rustworkx.PyDiGraph,
        nodes: list[UniversalNode],
        embedder: Optional[GraphIndexEmbedder] = None,
        hybrid_search: Optional[HybridPageIndexSearch] = None,
        signal_config: Optional[SignalRelevanceConfig] = None,
        communities: Optional[CommunitiesResult] = None,
    ) -> None: ...

    async def search(
        self,
        query: str,
        seed_top_k: int = 10,
        expansion: Optional[ExpansionConfig] = None,
        budget: Optional[BudgetConfig] = None,
    ) -> GraphRetrievalResult: ...
```

---

## 3. Module Breakdown

### Module 1: Core Retriever Class
- **Path**: `packages/ai-parrot/src/parrot/knowledge/graphindex/retriever.py` (new)
- **Responsibility**: `GraphExpandedRetriever` class with 4-phase pipeline, `ExpansionConfig`, `BudgetConfig`, `ScoredNode`, `GraphRetrievalResult` models
- **Depends on**: existing signals.py, communities.py, schema.py

### Module 2: Phase 1 -- Seed Search Adapters
- **Path**: `packages/ai-parrot/src/parrot/knowledge/graphindex/retriever.py` (part of class)
- **Responsibility**: Abstract over HybridPageIndexSearch and GraphIndexEmbedder for seed node selection
- **Depends on**: Module 1, existing hybrid_search.py, embed.py

### Module 3: Phase 2 -- Graph Expansion Engine
- **Path**: `packages/ai-parrot/src/parrot/knowledge/graphindex/retriever.py` (part of class)
- **Responsibility**: N-hop expansion with signal_relevance scoring and configurable decay
- **Depends on**: Module 1, existing signals.py (signal_relevance, relevance_neighborhood)

### Module 4: Phase 3+4 -- Community Context & Result Assembly
- **Path**: `packages/ai-parrot/src/parrot/knowledge/graphindex/retriever.py` (part of class)
- **Responsibility**: Community annotation, centroid inclusion, budget-controlled assembly
- **Depends on**: Module 3, existing communities.py

### Module 5: Toolkit Integration
- **Path**: `packages/ai-parrot-tools/src/parrot_tools/graphindex/toolkit.py` (extend)
- **Responsibility**: New `search_with_expansion()` async tool on GraphIndexToolkit
- **Depends on**: Module 1-4

### Module 6: Tests
- **Path**: `packages/ai-parrot/tests/knowledge/graphindex/test_retriever.py` (new) + `packages/ai-parrot-tools/tests/graphindex/test_toolkit.py` (extend)
- **Responsibility**: Unit tests for all phases + integration test for full pipeline
- **Depends on**: Module 1-5

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_seed_search_faiss` | 2 | Phase 1 via GraphIndexEmbedder returns scored seed nodes |
| `test_seed_search_hybrid` | 2 | Phase 1 via HybridPageIndexSearch returns scored seed nodes |
| `test_expansion_one_hop` | 3 | Single-hop expansion finds direct neighbors with signal scores |
| `test_expansion_two_hops` | 3 | Two-hop expansion applies decay correctly (score * 0.7 * 0.7 for hop 2) |
| `test_expansion_deduplication` | 3 | Same node reachable via two paths keeps highest combined score |
| `test_expansion_min_threshold` | 3 | Nodes below min_signal_threshold excluded |
| `test_expansion_max_nodes_cap` | 3 | Expansion stops at max_expanded_nodes |
| `test_decay_exponential` | 3 | Default decay: 0.7^1 = 0.7, 0.7^2 = 0.49, 0.7^3 = 0.343 |
| `test_decay_configurable` | 3 | Custom decay_base applied correctly |
| `test_community_annotation` | 4 | Nodes annotated with community_id and cohesion |
| `test_community_centroid_inclusion` | 4 | Centroid nodes added when include_community_centroids=True |
| `test_budget_truncation` | 4 | Results truncated when token budget exceeded |
| `test_budget_no_truncation` | 4 | All results returned when within budget |
| `test_result_sorting` | 4 | Results sorted by combined_score descending |
| `test_full_pipeline` | 1-4 | End-to-end: query to seed to expand to community to result |
| `test_no_embedder_fallback` | 2 | When no embedder provided, uses graph-only seed selection |
| `test_no_communities_graceful` | 4 | Phase 3 skipped when no CommunitiesResult |

### Integration Tests

| Test | Description |
|---|---|
| `test_toolkit_search_with_expansion` | Toolkit tool returns GraphRetrievalResult dict |

### Test Data / Fixtures

```python
@pytest.fixture
def retriever_with_graph():
    """GraphExpandedRetriever with a test graph of 20 nodes, 3 communities."""
    # Build a test graph with known structure:
    # Community A: 5 tightly connected nodes
    # Community B: 5 tightly connected nodes
    # Community C: 5 tightly connected nodes
    # 3 bridge nodes connecting communities
    # 2 isolated nodes
    ...
```

---

## 5. Acceptance Criteria

- [ ] `GraphExpandedRetriever` composes existing search, signal, and community components
- [ ] Phase 1 supports both HybridPageIndexSearch and GraphIndexEmbedder as seed sources
- [ ] Phase 2 applies configurable exponential decay: `score * decay_base^hop`
- [ ] Phase 2 deduplicates by node_id, keeping highest combined score
- [ ] Phase 2 respects `max_expanded_nodes` and `min_signal_threshold` limits
- [ ] Phase 3 annotates results with community_id and cohesion when available
- [ ] Phase 3 gracefully skips when CommunitiesResult is None
- [ ] Phase 4 applies token budget, setting `truncated=True` when exceeded
- [ ] Results sorted by `combined_score` descending
- [ ] Each ScoredNode carries decomposed scores (search, signal, decay, combined)
- [ ] New `search_with_expansion()` toolkit tool auto-registered
- [ ] All existing tests still pass
- [ ] All new tests pass: `pytest tests/knowledge/graphindex/test_retriever.py -v`

---

## 6. Codebase Contract

> **CRITICAL -- Anti-Hallucination Anchor**
> This section is the single source of truth for what exists in the codebase.
> Implementation agents MUST NOT reference imports, attributes, or methods
> not listed here without first verifying they exist via `grep` or `read`.

### Verified Imports

```python
# verified: packages/ai-parrot/src/parrot/knowledge/graphindex/__init__.py
from parrot.knowledge.graphindex.schema import (
    UniversalNode,   # line 89 of schema.py
    UniversalEdge,   # line 101 of schema.py
    NodeKind,        # line 32 of schema.py
)
from parrot.knowledge.graphindex.signals import (
    SignalRelevanceConfig,  # line 89 of signals.py
    SignalRelevance,        # line 138 of signals.py
    signal_relevance,       # line 460 of signals.py
    relevance_neighborhood, # line 550 of signals.py
)
from parrot.knowledge.graphindex.communities import (
    CommunitiesResult,      # line 69 of communities.py
    Community,              # line 39 of communities.py
)
from parrot.knowledge.graphindex.embed import GraphIndexEmbedder  # embed.py
from parrot.knowledge.pageindex.hybrid_search import HybridPageIndexSearch  # hybrid_search.py
```

### Existing Class Signatures

```python
# packages/ai-parrot/src/parrot/knowledge/graphindex/signals.py
def signal_relevance(
    graph: rustworkx.PyDiGraph,
    nodes: list[UniversalNode],
    node_a: str,
    node_b: str,
    config: Optional[SignalRelevanceConfig] = None,
    embedder: Optional["GraphIndexEmbedder"] = None,
) -> SignalRelevance:  # line 460-467

def relevance_neighborhood(
    graph: rustworkx.PyDiGraph,
    nodes: list[UniversalNode],
    node_id: str,
    top_k: int = 10,
    config: Optional[SignalRelevanceConfig] = None,
    candidate_pool: Optional[Iterable[str]] = None,
    embedder: Optional["GraphIndexEmbedder"] = None,
) -> list[SignalRelevance]:  # line 550-558

# packages/ai-parrot/src/parrot/knowledge/graphindex/communities.py
class CommunitiesResult(BaseModel):
    modularity: float          # line 72
    resolution: float          # line 73
    seed: int                  # line 74
    weighted: bool             # line 75
    communities: list[Community]  # line 76
    node_to_community: dict[str, str]  # line 77

class Community(BaseModel):
    community_id: str          # line 58
    size: int                  # line 59
    member_node_ids: list[str] # line 60
    centroid_node_id: str      # line 61
    cohesion: float            # line 62

# packages/ai-parrot/src/parrot/knowledge/graphindex/embed.py
class GraphIndexEmbedder:
    # line 206
    def search_similar(self, query_embedding: np.ndarray, top_k: int = 10) -> list[tuple[str, float]]:
        ...
    def encode_nodes(self, texts: list[str]) -> np.ndarray:
        ...
    def get_embedding(self, node_id: str) -> Optional[np.ndarray]:
        ...

# packages/ai-parrot/src/parrot/knowledge/pageindex/hybrid_search.py
class HybridPageIndexSearch:
    async def search(
        self,
        query: str,
        top_k: int = 10,
        use_bm25: bool = True,
        use_llm_walk: bool = True,
        use_vec: bool = False,
        use_embedding_walk: Optional[bool] = None,
        rerank: bool = False,
    ) -> list[dict[str, Any]]:  # line 288-411
        ...

# packages/ai-parrot-tools/src/parrot_tools/graphindex/toolkit.py
class GraphIndexToolkit(AbstractToolkit):  # line 60
    def __init__(
        self,
        graph: rustworkx.PyDiGraph,
        faiss_index: faiss.Index,
        node_map: dict[str, int],
        node_id_list: list[str],
        client=None,
        assembler=None,
        embedder=None,
        nodes=None,
        signal_config=None,
    ) -> None:  # line 92-103
        ...
```

### Does NOT Exist (Anti-Hallucination)

- ~~`graphindex.retriever`~~ -- module does not exist yet (this spec creates it)
- ~~`GraphExpandedRetriever`~~ -- class does not exist yet
- ~~`GraphIndexToolkit.search_with_expansion()`~~ -- tool does not exist yet
- ~~`HybridPageIndexSearch.search_with_graph()`~~ -- no such method
- ~~`GraphIndexEmbedder.search()`~~ -- method is named `search_similar()` not `search()`
- ~~`signal_relevance.neighborhood()`~~ -- function is `relevance_neighborhood()` not `.neighborhood()`

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- Composition over inheritance: `GraphExpandedRetriever` holds references to existing components, does not subclass them
- New Pydantic models for config and results (consistent with project convention)
- Async `search()` method (consistent with HybridPageIndexSearch.search())
- Toolkit tool follows existing `async def method(self, ...) -> dict/list` pattern
- Lazy/optional dependencies: `hybrid_search` and `embedder` are both Optional; at least one must be provided

### Known Risks / Gotchas

- `relevance_neighborhood()` computes signal_relevance for all neighbors -- for nodes with high degree (>100 neighbors), this could be expensive. Consider capping candidate pool size.
- `HybridPageIndexSearch` is tree-scoped while `GraphIndexEmbedder` is graph-scoped. The retriever must normalize scores to [0, 1] regardless of source.
- Token budget estimation uses `tokens_per_node_estimate` as a rough heuristic. Actual token counts depend on node content length.
- When both `hybrid_search` and `embedder` are None, raise a clear error at init time.

### External Dependencies

No new external dependencies. Uses existing rustworkx, networkx, numpy, pydantic.

---

## 8. Open Questions

- [x] **Should graph-expanded retrieval be a separate class or integrated into hybrid_search.py?** -- *Resolved in proposal*: Separate `GraphExpandedRetriever` class to keep concerns separated.
- [x] **What decay function for graph expansion hops?** -- *Resolved in proposal*: Configurable, default exponential (`score * 0.7^hop`).
- [x] **Should the retriever cache signal_relevance results across queries?** -- Recommendation: No caching for v1. Signal scores depend on the graph state which may change between queries. Cache in v2 with TTL if profiling shows it's needed: no caching
- [x] **Should Phase 1 support combining both seed sources (FAISS + hybrid)?** -- Recommendation: Yes, with RRF fusion (same pattern as HybridPageIndexSearch._rrf_fuse). But defer to v2; v1 uses one or the other: Yes, based on recommendation

---

## Worktree Strategy

- **Isolation unit**: per-spec (sequential tasks in one worktree)
- **Cross-feature dependencies**: Requires FEAT-190, FEAT-191, FEAT-237 merged (all are merged). FEAT-215 (analytics insights) is independent -- no dependency.
- Modules are sequential within the retriever class: core, seed, expand, assemble, toolkit, tests

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-06-16 | Jesus Lara | Initial draft from FEAT-215 proposal |
