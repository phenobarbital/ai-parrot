---
type: Wiki Overview
title: 'Feature Specification: GraphIndex Louvain Community Detection'
id: doc:sdd-specs-feat-191-graphindex-louvain-communities-spec-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: GraphIndex assembles a knowledge graph from documents, code, and skills
relates_to:
- concept: mod:parrot.knowledge.graphindex.assemble
  rel: mentions
- concept: mod:parrot.knowledge.graphindex.communities
  rel: mentions
- concept: mod:parrot.knowledge.graphindex.persist
  rel: mentions
- concept: mod:parrot.knowledge.graphindex.schema
  rel: mentions
- concept: mod:parrot.knowledge.graphindex.signals
  rel: mentions
---

---
# SDD flow type and base branch (FEAT-145).
type: feature
base_branch: dev
---

# Feature Specification: GraphIndex Louvain Community Detection

**Feature ID**: FEAT-191
**Date**: 2026-05-21
**Author**: Jesús Lara
**Status**: approved
**Target version**: 0.x (GraphIndex is pre-production; no compat guarantees)

---

## 1. Motivation & Business Requirements

### Problem Statement

GraphIndex assembles a knowledge graph from documents, code, and skills
into a `rustworkx.PyDiGraph` (`assemble.py:24`). The current analytics
stage extracts "god-nodes" via betweenness/eigenvector centrality
(`analytics.py:_compute_god_nodes`) and "surprising connections" via
inferred-edge ranking (`analytics.py:_rank_surprising_connections`).
But it answers one question and not the obvious next one:

> *"Which clusters of nodes form coherent topics?"*

For an LLM-Wiki agent, knowing the **communities** matters more than
knowing the most-central node. A wiki has *topics*; an agent that wants
to write the "AWS Security Trust Services Criterion" entity page needs
to find every Section / Concept node clustered around that topic, not
just the highest-betweenness node in the whole graph. For a code +
docs + skills graph, communities tend to map to feature areas (e.g.
"the auth flow" — code symbols, design docs, and onboarding skills all
form a cluster).

The standard tool for this is **Louvain community detection**
(Blondel et al. 2008): maximises modularity over partitions, runs in
near-linear time, returns a flat partition + a global modularity
score. The standard quality scalar **per community** is **cohesion**
— the ratio of internal edges to total edges incident to the
community. Together, modularity gives global quality; cohesion gives
per-community quality and lets a consumer rank communities by
"tightness" before showing them to an LLM.

Two facts make this a clean additive layer:

1. **`rustworkx` 0.17 does not ship Louvain** (verified by reading
   `dir(rustworkx)` on 2026-05-21: no `louvain`, `modularity`, or
   `community` symbols). It supports the algorithms FEAT-189/-190
   need (centrality, dijkstra, eigenvector) but not community
   detection.
2. **`networkx` ≥ 3.0 ships both** `networkx.community.louvain_communities`
   AND `networkx.community.modularity`, and is already a project
   dependency (`pyproject.toml:205`). The pattern of rustworkx →
   networkx conversion for a specific algorithm is already used in
   `concept_catalog/service.py:20`.

This spec therefore adds a thin module that runs Louvain via
networkx, writes a stable `community_id` onto each node's
`domain_tags`, computes per-community cohesion, and exposes a public
`CommunitiesResult` for downstream consumers (FEAT-192 toolkit
methods, the wiki orchestrator, the report generator).

### Goals

- Detect communities over the assembled `rustworkx.PyDiGraph` using
  networkx Louvain.
- Compute modularity (global) and cohesion (per-community).
- Write a deterministic `community_id` (16-char hex of the sorted
  member node_ids) into each node's `domain_tags["community_id"]`,
  so the assignment round-trips through persistence (ArangoDB
  `_node_to_doc` already dumps `domain_tags` wholesale —
  `persist.py:49`).
- Identify each community's **centroid node** — the member with the
  highest in-community degree — to give downstream consumers a
  natural "entry point" per cluster.
- Provide an optional FEAT-190 signal weighting: when a
  `SignalRelevanceConfig` is supplied, run Louvain on a weighted
  graph where edge weights come from `signal_relevance(a, b).combined`
  so community boundaries respect the signal model rather than just
  the raw edge count.
- Integrate as an optional pipeline stage in `GraphIndexBuilder`,
  default-off so existing build flows are unaffected.

### Non-Goals (explicitly out of scope)

- **Hierarchical / multi-resolution communities** (Leiden, Infomap,
  multi-level Louvain). v1 is single-resolution Louvain only. The
  `resolution` parameter is exposed but no recursive nesting is
  built.
- **LLM-generated community labels** — the centroid title and the
  top-5 member titles are returned for human/LLM consumption, but
  no automatic naming. A downstream consumer can ask an LLM to
  label a community; that's a wiki-orchestrator concern.
- **Overlapping communities** — Louvain is a strict partition.
  Fuzzy / multi-membership detection is out of scope.
- **Temporal / streaming detection** — communities are computed
  over the snapshot graph the build produces. Incremental
  re-detection on `ingest_document` is a follow-up if profiling
  warrants it.
- **Persisting community metadata as separate ArangoDB documents** —
  the `community_id` rides on `UniversalNode.domain_tags`; we do not
  create a `communities` collection. (If a future feature wants to,
  it can read `domain_tags["community_id"]` and aggregate.)
- **Toolkit exposure** — agent-facing tools for "list communities" /
  "find my community" live in FEAT-192. This spec produces the data;
  FEAT-192 exposes it.

---

## 2. Architectural Design

### Overview

One new module —
`parrot.knowledge.graphindex.communities` — that takes the assembled
graph + node list, runs Louvain via networkx, and returns a
`CommunitiesResult` Pydantic model carrying:

- The global modularity scalar.
- A list of `Community` records (id, members, size, cohesion,
  centroid_node_id, top member titles).
- The mapping `node_id → community_id` for convenient lookups.

As a side effect, the function **mutates** `domain_tags["community_id"]`
on every node in the input list. This is the only mutation; nothing
else in the input is touched. (Mutation is opt-in via the
`write_back_to_nodes: bool = True` flag — set to False to compute
without mutating.)

### Component Diagram

```
                ┌───────────────────────────────────┐
                │ GraphIndexBuilder.build           │
                │ (assemble + resolve done)         │
                └───────────────┬───────────────────┘
                                │
        ┌───────────────────────┼───────────────────────┐
        ▼                       ▼                       ▼
  ┌──────────┐         ┌────────────────┐       ┌─────────────┐
  │ analytics│         │  communities   │       │   signals   │
  │(existing)│         │   (NEW)        │       │ (FEAT-190)  │
  └──────────┘         └───────┬────────┘       └─────────────┘
                               │
                  detect_communities(graph, nodes, …)
                               │
                               ▼
                  networkx.community.louvain_communities
                               │
                               ▼
                  CommunitiesResult
                    ├ modularity: float
                    ├ communities: list[Community]
                    └ node_to_community: dict[str, str]
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `rustworkx.PyDiGraph` (from `GraphAssembler.graph`) | reuse | Read-only. Converted to a weighted/unweighted `networkx.Graph` once per call. |
| `UniversalNode.domain_tags` | mutate (opt-in) | Writes `community_id` and (optionally) `community_centroid: bool`. |
| `GraphIndexBuilder` | optional pipeline stage | New `detect_communities: bool = False` flag on the builder; when set, the stage runs between resolve and persist. |
| `GraphIndexPersistence._node_to_doc` (`persist.py:31`) | implicit | `domain_tags` is dumped wholesale (`persist.py:49`), so `community_id` flows to ArangoDB automatically. No persist.py change needed. |
| `signals.SignalRelevanceConfig` (FEAT-190) | optional input | When supplied, edge weights come from `signal_relevance(a, b).combined`. |
| `networkx.community.louvain_communities` | direct call | Single API call; deterministic when `seed=` is set. |
| `analytics.AnalyticsResult` | sibling | Not modified. Communities are a separate output. |

### Data Models

```python
# parrot/knowledge/graphindex/communities.py

class Community(BaseModel):
    """A single community in the partition."""

    community_id: str               # 16-char hex of sorted member node_ids
    size: int                       # number of member nodes
    member_node_ids: list[str]      # ordered: centroid first, then desc by degree
    centroid_node_id: str           # member with highest in-community degree
    cohesion: float                 # in [0, 1], internal_edges / total_incident
    modularity_contribution: float  # the community's contribution to global Q
    top_titles: list[str]           # titles of the first ≤5 members (for display)

    model_config = ConfigDict(frozen=True)


class CommunitiesResult(BaseModel):
    """Full Louvain partition + per-community metadata."""

    modularity: float                # global Q score in (-1, 1)
    resolution: float                # the gamma used (echo of input)
    seed: int                        # echo of the rng seed used
    weighted: bool                   # whether edges were weighted (FEAT-190)
    communities: list[Community]     # sorted: largest first
    node_to_community: dict[str, str]  # node_id → community_id

    model_config = ConfigDict(frozen=True)
```

### New Public Interfaces

```python
# parrot/knowledge/graphindex/communities.py

def detect_communities(
    graph: rustworkx.PyDiGraph,
    nodes: list[UniversalNode],
    resolution: float = 1.0,
    seed: int = 42,
    signal_config: Optional["SignalRelevanceConfig"] = None,
    write_back_to_nodes: bool = True,
) -> CommunitiesResult:
    """Run Louvain community detection on the assembled graph.

    When ``signal_config`` is supplied (FEAT-190 dependency), edges
    are weighted by ``signal_relevance(a, b).combined`` before being
    handed to networkx. Otherwise the graph is treated as unweighted.

    Side effect (when ``write_back_to_nodes=True``): every node in
    ``nodes`` gets ``domain_tags['community_id'] = <id>``. The centroid
    of each community additionally gets ``domain_tags['community_centroid']
    = True``.

    Args:
        graph: The assembled PyDiGraph.
        nodes: The UniversalNode list; mutated in-place when
            ``write_back_to_nodes=True``.
        resolution: Louvain γ resolution parameter. >1.0 finds smaller
            communities; <1.0 finds larger ones.
        seed: RNG seed for deterministic results across builds.
        signal_config: Optional FEAT-190 config; when set, edges are
            signal-weighted before Louvain runs.
        write_back_to_nodes: When True (default), writes community_id
            into ``UniversalNode.domain_tags``.

    Returns:
        CommunitiesResult with modularity, per-community records,
        and a node_id → community_id lookup.
    """


def cohesion_for_community(
    nx_graph: "networkx.Graph",
    members: set[int],
) -> float:
    """internal_edges / (internal_edges + boundary_edges).

    Pure function over a networkx Graph; exported so callers can
    re-score a custom partition without re-running Louvain.
    """


def _stable_community_id(member_node_ids: Iterable[str]) -> str:
    """16-char SHA-1 prefix of sorted member ids — same scheme as
    ``LoaderExtractor._make_node_id`` for cross-feature consistency."""
```

---

## 3. Module Breakdown

### Module 1: Pydantic models + module skeleton
- **Path**: `packages/ai-parrot/src/parrot/knowledge/graphindex/communities.py` (new)
- **Responsibility**: Define `Community`, `CommunitiesResult`,
  function signatures, the `_stable_community_id` helper.
- **Depends on**: nothing new.

### Module 2: rustworkx → networkx conversion + edge-weight builder
- **Path**: same file.
- **Responsibility**:
  - `_to_networkx(graph, signal_config)` — convert PyDiGraph to
    undirected networkx.Graph. When `signal_config` is None, edges
    are weight=1.0. When set, weight = `signals.signal_relevance(a, b).combined`
    for the pair (lazy import of `signals` module to keep FEAT-191
    runnable even if FEAT-190 ships later).
  - Conversion handles directed → undirected by collapsing
    a→b and b→a into one edge (max weight kept).
- **Depends on**: Module 1. Optionally imports FEAT-190 `signals` lazily.

### Module 3: Louvain detection + modularity
- **Path**: same file.
- **Responsibility**:
  - Call `networkx.community.louvain_communities(nx_graph, resolution=…, seed=…, weight='weight')`.
  - Compute global modularity via `networkx.community.modularity`.
  - Map networkx nodes back to UniversalNode ids.
- **Depends on**: Module 2.

### Module 4: Per-community cohesion + centroid identification
- **Path**: same file.
- **Responsibility**:
  - `cohesion_for_community(nx_graph, members)` — counts internal
    edges (both endpoints in `members`) and boundary edges (exactly
    one endpoint in `members`); returns
    `internal / (internal + boundary)` with a 0-edge guard.
  - For each community, identify the centroid as the member with
    the highest *in-community* degree (ties broken by node_id for
    determinism).
  - Compute `modularity_contribution` per community as
    `(internal_weight / total_weight) - (degree_sum / (2 * total_weight))^2`
    (textbook Louvain contribution term).
- **Depends on**: Module 3.

### Module 5: Pydantic assembly + node mutation
- **Path**: same file.
- **Responsibility**:
  - Build the `CommunitiesResult` from Module 4 outputs.
  - When `write_back_to_nodes=True`, iterate `nodes` and set
    `node.domain_tags["community_id"]`. Also set
    `domain_tags["community_centroid"] = True` on each centroid.
  - Sort communities by size descending; within each community,
    order `member_node_ids` with the centroid first, then by
    in-community degree desc.
- **Depends on**: Modules 1-4.

### Module 6: Optional builder pipeline integration
- **Path**: `packages/ai-parrot/src/parrot/knowledge/graphindex/builder.py` (modify)
- **Responsibility**:
  - Add `detect_communities: bool = False` and
    `community_resolution: float = 1.0` ctor parameters.
  - When `detect_communities=True`, run `detect_communities(...)`
    in the build pipeline immediately after `resolve_cross_domain`
    and immediately before `persist`. Store the result on
    `self.last_community_result` so report generation (FEAT-192 +
    follow-up analytics) can read it.
  - **Default off** — current callers see no behavioural change.
- **Depends on**: Modules 1-5.

### Module 7: Analytics report extension (additive)
- **Path**: `packages/ai-parrot/src/parrot/knowledge/graphindex/analytics.py` (modify)
- **Responsibility**:
  - Extend `AnalyticsResult` with an optional
    `communities: Optional[CommunitiesResult] = None` field.
  - When the field is set, `generate_report`/`_render_report`
    append a new section "## Communities" listing the top-K
    communities by size with their centroid title and cohesion.
  - **Backward compat**: when `communities=None`, report renders
    identically to today.
- **Depends on**: Modules 1, 5. Schema field is optional.

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_community_id_deterministic` | 1 | Same member set → same id; different order → same id. |
| `test_community_pydantic_frozen` | 1 | Mutating a built `Community` raises. |
| `test_to_networkx_unweighted` | 2 | Without signal_config, all edges have weight=1.0. |
| `test_to_networkx_signal_weighted` | 2 | With `signal_config`, edge weights match `signal_relevance(...).combined` (mock the signals function). |
| `test_to_networkx_collapses_directed_edges` | 2 | a→b + b→a in PyDiGraph becomes one undirected edge in nx with max weight. |
| `test_to_networkx_isolated_nodes_included` | 2 | Nodes with no edges still appear in the networkx graph (otherwise Louvain drops them silently). |
| `test_detect_communities_deterministic_with_seed` | 3 | Two runs with the same seed produce identical partitions. |
| `test_detect_communities_modularity_in_range` | 3 | Returned `modularity` is in (-1, 1). |
| `test_cohesion_pure_clique` | 4 | A clique of size 4 with no boundary edges → cohesion=1.0. |
| `test_cohesion_isolated_pair` | 4 | Two-node community with one internal edge, no boundary → cohesion=1.0. |
| `test_cohesion_no_edges_at_all` | 4 | Single-node community with no edges → cohesion=0.0 (guarded division). |
| `test_centroid_is_highest_in_community_degree` | 4 | Centroid id matches the manually-computed top-degree member. |
| `test_modularity_contributions_sum_to_global` | 4 | Σ contributions == global Q within 1e-6. |
| `test_writeback_sets_domain_tag` | 5 | After `detect_communities(write_back_to_nodes=True)`, every node has `domain_tags['community_id']` set. |
| `test_writeback_centroid_flag` | 5 | Centroids carry `domain_tags['community_centroid'] = True`; non-centroids do not. |
| `test_writeback_disabled_does_not_mutate` | 5 | `write_back_to_nodes=False` leaves `domain_tags` untouched. |
| `test_communities_sorted_largest_first` | 5 | `communities` list is sorted by `size` desc. |
| `test_builder_detect_communities_flag` | 6 | `GraphIndexBuilder(detect_communities=True)` populates `last_community_result`. |
| `test_builder_default_off_no_invocation` | 6 | Default builder does NOT invoke detection (mock to confirm no call). |
| `test_analytics_renders_communities_section_when_present` | 7 | `_render_report` includes the "## Communities" section when `analytics.communities` is set. |
| `test_analytics_no_communities_section_when_absent` | 7 | Report unchanged when `analytics.communities is None`. |

### Integration Tests

| Test | Description |
|---|---|
| `test_louvain_on_two_cliques` | Build a graph with two disjoint 5-node cliques connected by a single bridge edge. Louvain must produce exactly 2 communities; each cohesion ≥ 0.9; modularity > 0.4. |
| `test_louvain_signal_weighted_finds_concept_clusters` | Fixture with 3 Concepts, 6 Sections sharing 2 source_uris, run with FEAT-190 `SignalRelevanceConfig`. The two Concept-Section clusters appear as separate communities even though there's no direct edge between them (signal weighting picks up the source overlap). |
| `test_persist_round_trips_community_id` | Build with `detect_communities=True`, persist to a stub ArangoDB; assert the dumped Document node carries `community_id` in `domain_tags`. |

### Test Data / Fixtures

```python
# tests/knowledge/graphindex/fixtures/community_graph.py

@pytest.fixture
def two_cliques_graph() -> tuple[rustworkx.PyDiGraph, list[UniversalNode]]:
    """Two K5 cliques (nodes A0..A4, B0..B4) connected by a single
    A0↔B0 bridge edge. Used by `test_louvain_on_two_cliques`."""

@pytest.fixture
def concept_section_graph() -> tuple[rustworkx.PyDiGraph, list[UniversalNode]]:
    """3 Concepts × 2 Sections-each (shared source_uri per Concept
    cluster). No direct Concept↔Section edges — only source overlap.
    Used to verify signal-weighted Louvain finds the clusters."""
```

---

## 5. Acceptance Criteria

- [ ] `parrot.knowledge.graphindex.communities` exists with the
      public surface defined in §2.
- [ ] `detect_communities(graph, nodes)` returns a
      `CommunitiesResult` with `modularity`, `communities` (sorted by
      size desc), and `node_to_community`.
- [ ] Every node receives a `community_id` (when `write_back_to_nodes`
      is True); centroids receive `community_centroid=True`.
- [ ] Each `Community` carries: `community_id`, `size`,
      `member_node_ids` (centroid first), `centroid_node_id`,
      `cohesion ∈ [0, 1]`, `modularity_contribution`, `top_titles`
      (≤ 5).
- [ ] Determinism: two runs with the same `seed` produce identical
      `community_id` values across the partition.
- [ ] Cohesion formula matches the textbook definition: internal /
      (internal + boundary), with a 0-edge guard returning 0.0.
- [ ] Modularity contributions sum to the global Q within 1e-6.
- [ ] When `signal_config` is supplied, edges are weighted by
      FEAT-190 `signal_relevance(...).combined`; tested by a fixture
      where source overlap dictates the right partition.
- [ ] `GraphIndexBuilder(detect_communities=True)` runs the stage
      between resolve and persist and exposes the result via
      `builder.last_community_result`.
- [ ] `AnalyticsResult.communities` field is optional; when set,
      `generate_report` includes a "## Communities" section.
- [ ] `community_id` round-trips through `_node_to_doc` into the
      persisted ArangoDB Document (verified via stub test —
      `persist.py:49` dumps `domain_tags` wholesale).
- [ ] No new external dependencies (networkx already at
      `pyproject.toml:205`).
- [ ] All unit + integration tests pass:
      `pytest tests/knowledge/graphindex/test_communities.py -v`.
- [ ] All previously-passing tests under
      `tests/knowledge/graphindex/` still pass.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor** (verified 2026-05-21)

### Verified Imports

```python
from parrot.knowledge.graphindex.schema import (
    EdgeKind,                              # schema.py:52
    NodeKind,                              # schema.py:32
    UniversalEdge,                         # schema.py:101
    UniversalNode,                         # schema.py:70
)
from parrot.knowledge.graphindex.assemble import GraphAssembler  # assemble.py:24
from parrot.knowledge.graphindex.persist import GraphIndexPersistence  # persist.py:101
import rustworkx
import networkx as nx                      # pyproject.toml:205

# Verified runtime API:
import networkx.community
nx.community.louvain_communities(G, weight='weight', resolution=1.0, seed=42)
nx.community.modularity(G, communities, weight='weight', resolution=1.0)
```

### Existing Class Signatures

```python
# packages/ai-parrot/src/parrot/knowledge/graphindex/builder.py
class GraphIndexBuilder:                   # line 49
    def __init__(
        self,
        persistence: GraphIndexPersistence,
        embedder: GraphIndexEmbedder,
        output_dir: Path,
        ignore_file: Optional[Path] = None,
        resolution_config: Optional[ResolutionConfig] = None,
        pageindex_toolkit: Optional[PageIndexToolkit] = None,
    ): ...                                 # line 75
    # build() runs assemble → embed → resolve → persist → analytics.
    # FEAT-191 inserts itself between resolve and persist when
    # detect_communities=True.
```

```python
# packages/ai-parrot/src/parrot/knowledge/graphindex/persist.py
def _node_to_doc(node: UniversalNode) -> dict[str, Any]:  # line 31
    return {
        ...
        "domain_tags": node.domain_tags,   # line 49 — community_id rides here
        ...
    }
```

```python
# packages/ai-parrot/src/parrot/knowledge/graphindex/analytics.py
@dataclass
class AnalyticsResult:                     # line 42
    god_nodes: list[dict] = field(default_factory=list)
    surprising_connections: list[dict] = field(default_factory=list)
    suggested_questions: list[str] = field(default_factory=list)
    # FEAT-191 adds:
    # communities: Optional[CommunitiesResult] = field(default=None)
```

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `detect_communities` | `GraphAssembler.graph` | reads node payloads + edges | `assemble.py:73, 109` |
| `_to_networkx(...)` | `networkx.Graph` | `nx.Graph(); G.add_edge(..., weight=w)` | networkx ≥ 3.0 |
| Louvain | `networkx.community.louvain_communities` | direct call | networkx ≥ 3.0 |
| Modularity | `networkx.community.modularity` | direct call | networkx ≥ 3.0 |
| Builder integration | `GraphIndexBuilder.build` | new pipeline step between resolve and persist | `builder.py:75` |
| Persistence | `_node_to_doc` `domain_tags` field | implicit — already dumps the whole dict | `persist.py:49` |
| Signal weighting (optional) | FEAT-190 `signals.signal_relevance` | lazy import | (FEAT-190) |

### Does NOT Exist (Anti-Hallucination)

- ~~`rustworkx.community.louvain_communities`~~ — does NOT exist in

…(truncated)…
