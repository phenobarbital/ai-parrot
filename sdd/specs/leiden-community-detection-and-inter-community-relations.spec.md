---
# SDD flow type and base branch (FEAT-145).
type: feature
base_branch: dev
---

# Feature Specification: Leiden Community Detection & Inter-Community Relations

**Feature ID**: FEAT-401
**Date**: 2026-08-01
**Author**: Jesús Lara
**Status**: approved
**Target version**: 0.x (GraphIndex is pre-production; no compat guarantees)

---

## 1. Motivation & Business Requirements

### Problem Statement

FEAT-191 introduced Louvain community detection into GraphIndex
(`communities.py`). Louvain maximises modularity and runs in near-linear
time, but it has a well-documented defect: **it can produce internally
disconnected communities** (Traag, Waltman & van Eck 2019). In practice
this means a community may contain two sub-groups with no internal path
between them, which degrades the quality of community labels, cohesion
scores, and downstream retrieval that scopes by community.

The **Leiden algorithm** (Traag et al. 2019) fixes this with a
refinement phase that **guarantees well-connectedness** within every
community, converges faster (skipping already-well-placed nodes), and
empirically produces higher modularity scores — especially at
non-default resolutions.

Additionally, the current analytics layer treats communities as isolated
units. Bridge nodes and cross-community surprise scoring exist
(`find_bridge_nodes`, `SurpriseFactors.cross_community`), but there is
no model of the **relationships between communities themselves**: which
topic clusters are tightly coupled, which are independent, how
information flows between them, and whether communities nest
hierarchically. This inter-community structure is essential for an
LLM-Wiki agent to navigate topic areas and answer questions like *"how
do the auth and payment subsystems relate?"*.

### Goals

- **G1**: Add Leiden as the default community detection algorithm, with
  Louvain as an automatic fallback when `leidenalg` is not installed.
- **G2**: Model inter-community relations as a meta-graph (community
  nodes + weighted directed edges), exposing coupling ratios and edge
  flow direction.
- **G3**: Expose hierarchical / multi-resolution communities via
  Leiden's native recursive refinement.
- **G4**: Integrate inter-community data into `GRAPH_REPORT.md` and the
  interactive HTML export.
- **G5**: Keep `leidenalg` + `python-igraph` as optional dependencies
  (`pip install ai-parrot[leiden]`), with clear install instructions.

### Non-Goals (explicitly out of scope)

- Replacing the `rustworkx` graph backend with `igraph` globally. The
  conversion to igraph is scoped to community detection only.
- LLM-polished community descriptions (planned for a separate feature).
- Persisting inter-community relations to ArangoDB (the meta-graph is
  computed in-memory and rendered into reports/exports; persistence is a
  future feature if demand warrants).

---

## 2. Architectural Design

### Overview

The feature touches three layers:

1. **Algorithm layer** (`communities.py`): a new `_to_igraph()` converter
   and a Leiden code path inside `detect_communities()`, selected by an
   `algorithm` parameter (`"leiden"` | `"louvain"`). When
   `algorithm="leiden"` and `leidenalg` is not importable, the function
   falls back to Louvain with a logged warning. A new
   `detect_hierarchical_communities()` function runs Leiden at multiple
   resolutions and returns nested partitions.

2. **Inter-community layer** (new file `inter_community.py`): a
   `compute_inter_community_graph()` function that takes a
   `CommunitiesResult` + the assembled `PyDiGraph` and returns an
   `InterCommunityGraph` — a list of `InterCommunityRelation` edges plus
   summary statistics. Each relation captures: source/target community
   IDs, directed edge count, total edge weight, and a coupling ratio
   (cross-edges / total incident edges for the pair).

3. **Reporting layer** (`analytics.py`, `export_html.py`): the report
   gets a new `## Inter-Community Relations` section; the HTML export
   gets an optional meta-graph overlay or a summary table.

### Component Diagram

```
detect_communities(algorithm="leiden")
        │
        ├─ leidenalg installed? ──yes──→ _to_igraph() → leidenalg.find_partition()
        │                                                     │
        │                         no──→ _to_undirected_networkx() → nx.community.louvain_communities()
        │                                                     │
        │                              ┌──────────────────────┘
        ▼                              ▼
   CommunitiesResult  ◄────────── (same model for both algorithms)
        │
        ├──→ compute_inter_community_graph()  →  InterCommunityGraph
        │                                              │
        ├──→ _render_report() adds §Communities        │
        │    + §Inter-Community Relations  ◄───────────┘
        │
        └──→ export_graph() adds meta-graph overlay  ◄─┘

detect_hierarchical_communities(resolutions=[0.5, 1.0, 2.0])
        │
        └──→ HierarchicalCommunitiesResult (list of CommunitiesResult per resolution)
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `communities.detect_communities()` | modifies | Add `algorithm` param; add `_to_igraph()` converter |
| `communities.CommunitiesResult` | extends | Add optional `algorithm` field |
| `builder.GraphIndexBuilder` | modifies | Add `community_algorithm` param; pass to `detect_communities()` |
| `analytics.compute_analytics()` | extends | Compute inter-community graph when communities present |
| `analytics.AnalyticsResult` | extends | Add `inter_community` field |
| `analytics._render_report()` | extends | Render inter-community section |
| `export_html.export_graph()` | extends | Pass inter-community data to payload |
| `export_html.build_export_payload()` | extends | Include inter-community edges in JSON |

### Data Models

```python
# --- communities.py (extended) ---

class Community(BaseModel):
    # ... existing fields ...
    algorithm: str = "louvain"  # "leiden" | "louvain"

class CommunitiesResult(BaseModel):
    # ... existing fields ...
    algorithm: str = "louvain"  # which algorithm produced this partition

class HierarchicalCommunitiesResult(BaseModel):
    """Multi-resolution Leiden partitions."""
    resolutions: list[float]
    levels: list[CommunitiesResult]  # one per resolution, sorted ascending


# --- inter_community.py (new) ---

class InterCommunityRelation(BaseModel):
    """A directed relationship between two communities."""
    source_community_id: str
    target_community_id: str
    source_label: str
    target_label: str
    directed_edge_count: int       # edges from source → target
    reverse_edge_count: int        # edges from target → source
    total_weight: float            # sum of edge weights (source → target)
    reverse_weight: float          # sum of edge weights (target → source)
    coupling_ratio: float          # cross-edges / total incident edges for the pair

class InterCommunityGraph(BaseModel):
    """Meta-graph of community-to-community relationships."""
    relations: list[InterCommunityRelation]
    community_count: int
    connected_pairs: int           # how many community pairs have ≥1 edge
    total_possible_pairs: int      # C(n, 2)
    density: float                 # connected_pairs / total_possible_pairs
```

### New Public Interfaces

```python
# communities.py
def detect_communities(
    graph: rustworkx.PyDiGraph,
    nodes: list[UniversalNode],
    resolution: float = 1.0,
    seed: int = 42,
    signal_config: Optional[SignalRelevanceConfig] = None,
    embedder: Optional[object] = None,
    write_back_to_nodes: bool = True,
    algorithm: str = "leiden",          # NEW — "leiden" | "louvain"
) -> CommunitiesResult: ...

def detect_hierarchical_communities(
    graph: rustworkx.PyDiGraph,
    nodes: list[UniversalNode],
    resolutions: list[float] | None = None,  # default: [0.25, 0.5, 1.0, 2.0, 4.0]
                                             # short-circuits to [1.0] when <20 nodes
    seed: int = 42,
    signal_config: Optional[SignalRelevanceConfig] = None,
    embedder: Optional[object] = None,
) -> HierarchicalCommunitiesResult: ...

# inter_community.py
def compute_inter_community_graph(
    graph: rustworkx.PyDiGraph,
    communities_result: CommunitiesResult,
) -> InterCommunityGraph: ...
```

---

## 3. Module Breakdown

### Module 1: Leiden Algorithm Integration

- **Path**: `packages/ai-parrot/src/parrot/knowledge/graphindex/communities.py`
- **Responsibility**: Add `_to_igraph()` conversion, Leiden detection path,
  `algorithm` parameter on `detect_communities()`, and the
  `detect_hierarchical_communities()` function.
- **Depends on**: None (modifies existing module)

### Module 2: Inter-Community Relations

- **Path**: `packages/ai-parrot/src/parrot/knowledge/graphindex/inter_community.py`
- **Responsibility**: New module with `InterCommunityRelation`,
  `InterCommunityGraph` models and `compute_inter_community_graph()`.
- **Depends on**: Module 1 (uses `CommunitiesResult`)

### Module 3: Builder & Analytics Integration

- **Path**: `packages/ai-parrot/src/parrot/knowledge/graphindex/builder.py`,
  `packages/ai-parrot/src/parrot/knowledge/graphindex/analytics.py`
- **Responsibility**: Wire `algorithm` param through builder; compute
  inter-community graph in analytics; add `inter_community` field to
  `AnalyticsResult`; render new report section.
- **Depends on**: Module 1, Module 2

### Module 4: HTML Export & Report Enhancement

- **Path**: `packages/ai-parrot/src/parrot/knowledge/graphindex/export_html.py`,
  `packages/ai-parrot/src/parrot/knowledge/graphindex/analytics.py`
- **Responsibility**: Add inter-community relations to `graph.json` payload
  and render a **collapsible summary table panel** in `graph.html` (columns:
  community pair, edge count, weight, coupling ratio, direction arrow). Add
  `## Inter-Community Relations` section to `GRAPH_REPORT.md`.
- **Depends on**: Module 2, Module 3

### Module 5: Optional Dependency, CLI & Install Instructions

- **Path**: `packages/ai-parrot/pyproject.toml`,
  `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py`, `docs/`
- **Responsibility**: Add `leiden` optional extra; add install instructions
  to docstrings / docs. Add `wikitoolkit communities --inter` CLI subcommand
  (or equivalent flag) so agents can query inter-community relations
  on-demand without regenerating the full report.
- **Depends on**: Module 2 (for `InterCommunityGraph` model)

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_detect_communities_leiden` | Module 1 | Leiden produces well-connected communities (no disconnected components within a community) |
| `test_detect_communities_leiden_fallback` | Module 1 | When `leidenalg` is not importable, falls back to Louvain with warning |
| `test_detect_communities_louvain_explicit` | Module 1 | `algorithm="louvain"` uses the existing networkx Louvain path |
| `test_to_igraph_conversion` | Module 1 | rustworkx → igraph conversion preserves node count, edge count, and weights |
| `test_leiden_weighted_edges` | Module 1 | Signal-weighted edges are forwarded to Leiden correctly |
| `test_hierarchical_communities` | Module 1 | Multi-resolution sweep returns one partition per resolution, sorted |
| `test_hierarchical_communities_nesting` | Module 1 | Lower resolution produces fewer (larger) communities than higher resolution |
| `test_inter_community_graph_basic` | Module 2 | Two communities with cross-edges produce the expected relation |
| `test_inter_community_graph_directed` | Module 2 | Directed edge counts distinguish A→B from B→A |
| `test_inter_community_graph_coupling_ratio` | Module 2 | Coupling ratio is correct for a known topology |
| `test_inter_community_graph_isolated` | Module 2 | Communities with no cross-edges have no relations |
| `test_inter_community_density` | Module 2 | Density = connected_pairs / C(n,2) |
| `test_analytics_inter_community_field` | Module 3 | `AnalyticsResult.inter_community` populated when communities present |
| `test_report_inter_community_section` | Module 4 | `_render_report` includes `## Inter-Community Relations` when data present |
| `test_export_json_inter_community` | Module 4 | `graph.json` payload includes inter-community relations |
| `test_algorithm_field_roundtrip` | Module 1 | `CommunitiesResult.algorithm` survives serialization |

### Integration Tests

| Test | Description |
|---|---|
| `test_builder_leiden_end_to_end` | Full build with `community_algorithm="leiden"` produces communities and inter-community graph |
| `test_builder_leiden_fallback_end_to_end` | Full build with Leiden requested but unavailable falls back gracefully |

### Test Data / Fixtures

```python
@pytest.fixture
def two_clique_graph():
    """Two 4-node cliques connected by a single bridge edge.
    Ideal for testing: clear community boundary, one inter-community edge,
    deterministic partition regardless of algorithm."""
    ...

@pytest.fixture
def hierarchical_graph():
    """Three-level nested community structure (2 super-communities,
    each containing 2 sub-communities of 3 nodes)."""
    ...

@pytest.fixture
def mock_leidenalg_unavailable(monkeypatch):
    """Patch the leidenalg import to raise ImportError."""
    ...
```

---

## 5. Acceptance Criteria

- [x] All unit tests pass: `pytest tests/knowledge/graphindex/test_communities.py tests/knowledge/graphindex/test_inter_community.py -v`
- [ ] Integration tests pass with `leidenalg` installed
- [ ] Integration tests pass without `leidenalg` installed (Louvain fallback)
- [ ] `detect_communities(algorithm="leiden")` guarantees every community is
      internally connected (verified by test)
- [ ] `detect_communities(algorithm="louvain")` produces identical results to
      current FEAT-191 behaviour (backward compatibility)
- [ ] `InterCommunityGraph` correctly computes directed edge counts, weights,
      and coupling ratios
- [ ] `GRAPH_REPORT.md` includes a new `## Inter-Community Relations` section
      when inter-community data is available
- [ ] `graph.json` includes inter-community relations in export payload
- [ ] `pyproject.toml` has a `leiden` optional extra with `leidenalg` and
      `python-igraph`
- [ ] No breaking changes to existing `detect_communities()` callers (default
      behaviour unchanged when `leidenalg` is not installed)
- [ ] `CommunitiesResult.algorithm` field records which algorithm was used

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**

### Verified Imports

```python
# Community detection (FEAT-191)
from parrot.knowledge.graphindex.communities import (
    Community,                  # verified: communities.py:37
    CommunitiesResult,          # verified: communities.py:72
    detect_communities,         # verified: communities.py:330
    cohesion_for_community,     # verified: communities.py:279
    derive_community_label,     # verified: communities.py:120
    _to_undirected_networkx,    # verified: communities.py:164 (private)
    _build_weight_fn,           # verified: communities.py:222 (private)
    _stable_community_id,       # verified: communities.py:153 (private)
)

# Schema types
from parrot.knowledge.graphindex.schema import (
    UniversalNode,              # verified: schema.py:143
    UniversalEdge,              # verified: schema.py:178
    BuildResult,                # verified: schema.py:320
    NodeKind,                   # verified: schema.py (enum)
    Provenance,                 # verified: schema.py (enum)
)

# Analytics
from parrot.knowledge.graphindex.analytics import (
    AnalyticsResult,            # verified: analytics.py:155 (dataclass)
    KnowledgeGaps,              # verified: analytics.py:50
    compute_analytics,          # verified: analytics.py:188
    generate_report,            # verified: analytics.py:755
    find_bridge_nodes,          # verified: analytics.py:599
    find_sparse_communities,    # verified: analytics.py:555
)

# Builder
from parrot.knowledge.graphindex.builder import (
    GraphIndexBuilder,          # verified: builder.py (class)
)

# HTML export
from parrot.knowledge.graphindex.export_html import (
    export_graph,               # verified: export_html.py:530
    build_export_payload,       # verified: export_html.py:208
    GraphExportPayload,         # verified: export_html.py (Pydantic model)
    GraphExportNode,            # verified: export_html.py (Pydantic model)
    GraphExportEdge,            # verified: export_html.py (Pydantic model)
)

# Signals (FEAT-190, lazy)
from parrot.knowledge.graphindex.signals import SignalRelevanceConfig
```

### Existing Class Signatures

```python
# communities.py
class Community(BaseModel):
    community_id: str                    # line ~39
    size: int
    member_node_ids: list[str]
    centroid_node_id: str
    cohesion: float
    modularity_contribution: float
    top_titles: list[str]
    label: str = ""
    model_config = ConfigDict(frozen=True)

class CommunitiesResult(BaseModel):
    modularity: float                    # line ~73
    resolution: float
    seed: int
    weighted: bool
    communities: list[Community]
    node_to_community: dict[str, str]
    model_config = ConfigDict(frozen=True)

def detect_communities(
    graph: rustworkx.PyDiGraph,          # line 330
    nodes: list[UniversalNode],
    resolution: float = 1.0,
    seed: int = 42,
    signal_config: Optional["SignalRelevanceConfig"] = None,
    embedder: Optional[object] = None,
    write_back_to_nodes: bool = True,
) -> CommunitiesResult: ...

# schema.py
class UniversalNode(BaseModel):
    node_id: str                         # line 165
    kind: NodeKind
    title: str
    source_uri: str
    domain_tags: dict = Field(default_factory=dict)  # line 172

# analytics.py
@dataclass
class AnalyticsResult:
    god_nodes: list[dict]                # line 175
    surprising_connections: list[dict]
    suggested_questions: list[str]
    communities: Optional[CommunitiesResult] = None  # line 178
    knowledge_gaps: Optional[KnowledgeGaps] = None
    dismissed: Optional[DismissedInsights] = None

# builder.py — GraphIndexBuilder.__init__
def __init__(
    self,
    persistence,
    embedder,
    ...,
    detect_communities_enabled: bool = False,
    community_resolution: float = 1.0,
    ...
) -> None: ...
# builder.py — Stage 4.5 calls detect_communities() at approx line 195

# export_html.py
def export_graph(
    graph: rustworkx.PyDiGraph,          # line 530
    output_dir: Path,
    *,
    communities: Optional[Any] = None,
    analytics: Optional[Any] = None,
    ...
) -> tuple[Path, Path]: ...
```

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `_to_igraph()` | `detect_communities()` | called when `algorithm="leiden"` | `communities.py:330` |
| `InterCommunityGraph` | `AnalyticsResult` | new field `inter_community` | `analytics.py:155` |
| `compute_inter_community_graph()` | `compute_analytics()` | called after community detection | `analytics.py:188` |
| `community_algorithm` param | `GraphIndexBuilder.__init__()` | forwarded to `detect_communities()` | `builder.py` Stage 4.5 |
| Inter-community data | `_render_report()` | new report section | `analytics.py:755` |
| Inter-community data | `export_graph()` | extended payload | `export_html.py:530` |

### Does NOT Exist (Anti-Hallucination)

- ~~`parrot.knowledge.graphindex.communities._to_igraph()`~~ — does not exist yet (to be created)
- ~~`parrot.knowledge.graphindex.inter_community`~~ — module does not exist yet (to be created)
- ~~`CommunitiesResult.algorithm`~~ — field does not exist yet (to be added)
- ~~`AnalyticsResult.inter_community`~~ — field does not exist yet (to be added)
- ~~`GraphIndexBuilder.community_algorithm`~~ — param does not exist yet (to be added)
- ~~`leidenalg`~~ — not installed; not in any existing extras
- ~~`python-igraph`~~ — not installed; not in any existing extras
- ~~`networkx.community.leiden_communities`~~ — does NOT exist in networkx 3.4.2
- ~~`rustworkx.community_louvain`~~ — does NOT exist in rustworkx 0.17

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- **Lazy imports**: follow the existing FEAT-190/191 pattern — `leidenalg` and
  `igraph` are imported inside `detect_communities()` with try/except
  ImportError, not at module level. This keeps `communities.py` importable
  without the optional dependency.
- **Frozen Pydantic models**: `Community` and `CommunitiesResult` use
  `ConfigDict(frozen=True)`. Adding `algorithm` requires no config change
  since it's a field with a default.
- **Deterministic results**: Leiden supports a `seed` parameter
  (`leidenalg.find_partition(..., seed=seed)`). Pass the existing `seed`
  parameter through.
- **Write-back pattern**: the existing `_write_back()` function mutates
  `UniversalNode.domain_tags`. This is unchanged — Leiden produces the same
  partition structure (set of member sets), just with guaranteed
  well-connectedness.
- **Graph conversion**: `_to_igraph()` mirrors `_to_undirected_networkx()` —
  collapse directed edges into undirected, apply weights, include isolates.
  Use `igraph.Graph()` constructor with edge list.

### Installation Instructions

The `leidenalg` package requires the `python-igraph` C library. Install via:

```bash
# Option 1: pip extra (recommended)
pip install ai-parrot[leiden]

# Option 2: uv (within this project)
uv pip install leidenalg python-igraph

# Option 3: conda (if pip wheels fail on your platform)
conda install -c conda-forge leidenalg
```

**Platform notes:**
- **Linux/macOS**: pre-built wheels available for Python 3.10–3.12 on PyPI.
- **Windows**: pre-built wheels available on PyPI for Python 3.10–3.12.
- **ARM macOS (Apple Silicon)**: wheels available since `leidenalg>=0.10`.
- If wheels are unavailable, a C compiler and `cmake` are needed to build
  `python-igraph` from source.

### Known Risks / Gotchas

- **C dependency weight**: `python-igraph` is a C library (~15 MB installed).
  Making it optional via extras avoids bloating the default install.
- **igraph version compatibility**: `leidenalg>=0.10` requires
  `python-igraph>=0.10`. Pin `python-igraph>=0.10` in the extra.
- **Resolution parameter semantics**: Leiden's `resolution_parameter` behaves
  similarly to Louvain's `resolution` (higher → smaller communities), but
  the optimal values may differ slightly for the same graph. The spec does
  NOT change the default resolution (1.0).
- **Frozen model mutation**: `CommunitiesResult` is frozen. Adding `algorithm`
  as a field with a default value is backward-compatible — existing code that
  constructs `CommunitiesResult(...)` without passing `algorithm` gets
  `"louvain"` by default.
- **Partition quality method**: `leidenalg.find_partition()` accepts
  `leidenalg.RBConfigurationVertexPartition` for modularity optimization
  (equivalent to Louvain's objective). Use this, NOT
  `ModularityVertexPartition`, to match the resolution parameter semantics.

### External Dependencies

| Package | Version | Reason | Required? |
|---|---|---|---|
| `leidenalg` | `>=0.10` | Leiden community detection algorithm | Optional (`leiden` extra) |
| `python-igraph` | `>=0.10` | Graph library required by `leidenalg`; also used for rustworkx→igraph conversion | Optional (`leiden` extra) |

---

## 8. Open Questions

- [x] Should `detect_hierarchical_communities()` default resolutions be
      `[0.25, 0.5, 1.0, 2.0, 4.0]` or should they be auto-tuned based on
      graph size? — *Owner: Jesús* — **Resolved**: Use fixed defaults
      `[0.25, 0.5, 1.0, 2.0, 4.0]`. They are deterministic, debuggable,
      and the `resolutions` parameter already lets callers customize. For
      tiny graphs (<20 nodes), short-circuit to `[1.0]` only.
- [x] Should inter-community relations be surfaced in the `wikitoolkit`
      CLI (e.g. `wikitoolkit communities --inter`), or only in the
      report/export? — *Owner: Jesús* — **Resolved**: Both. The
      report/export provides the full picture on build, but agents need
      on-demand CLI access (`wikitoolkit communities --inter` or similar
      subcommand) to answer cross-subsystem questions without regenerating
      the report. The CLI is the primary agent interface.
- [x] Should the HTML export render inter-community edges as a separate
      force-directed meta-graph layer, or as a summary table panel?
      — *Owner: Jesús* — **Resolved**: Summary table panel. A collapsible
      table with columns (community pair, edge count, weight, coupling
      ratio, direction arrow) delivers the information with minimal ECharts
      complexity. A force-directed meta-graph overlay can be a follow-up
      if the table proves insufficient.

---

## Worktree Strategy

- **Isolation unit**: `per-spec` — all tasks run sequentially in one
  worktree. The modules build on each other (Leiden → inter-community →
  analytics integration → export).
- **Parallelizable**: Module 5 (dependency/docs) can run in parallel with
  Modules 1-4.
- **Cross-feature dependencies**: None. FEAT-191 (Louvain) and FEAT-215
  (analytics insights) are already merged.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-08-01 | Jesús Lara | Initial draft |
| 0.2 | 2026-08-01 | Jesús Lara | Resolve all open questions: fixed hierarchical defaults with tiny-graph short-circuit, CLI + report/export for inter-community, summary table panel for HTML |
