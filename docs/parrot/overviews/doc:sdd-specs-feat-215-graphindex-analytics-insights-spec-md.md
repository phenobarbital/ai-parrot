---
type: Wiki Overview
title: 'Feature Specification: GraphIndex Analytics Insights'
id: doc:sdd-specs-feat-215-graphindex-analytics-insights-spec-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'GraphIndex analytics currently computes god-nodes (betweenness/eigenvector
  centrality) and surprising connections (confidence-only ranking of inferred edges).
  Three capabilities are missing:'
relates_to:
- concept: mod:parrot.knowledge.graphindex.analytics
  rel: mentions
- concept: mod:parrot.knowledge.graphindex.communities
  rel: mentions
- concept: mod:parrot.knowledge.graphindex.schema
  rel: mentions
- concept: mod:parrot.knowledge.graphindex.signals
  rel: mentions
---

---
type: feature
base_branch: dev
---

# Feature Specification: GraphIndex Analytics Insights

**Feature ID**: FEAT-215
**Date**: 2026-06-16
**Author**: Jesus Lara
**Status**: approved
**Target version**: 0.next
**Related**: FEAT-190 (signal-relevance), FEAT-191 (louvain-communities), FEAT-192 (toolkit-write-and-signals)

---

## 1. Motivation & Business Requirements

### Problem Statement

GraphIndex analytics currently computes god-nodes (betweenness/eigenvector centrality) and surprising connections (confidence-only ranking of inferred edges). Three capabilities are missing:

1. **Knowledge Gap Detection** — no way to find isolated nodes (degree <= 1), sparse communities (cohesion < 0.15 with >= 3 members), or bridge nodes (connecting >= 3 communities). These are the most actionable insights for an LLM-Wiki agent that needs to find under-connected knowledge areas.

2. **Composite Surprise Scoring** — surprising connections are ranked by confidence alone. A composite score incorporating cross-community edges (+3), cross-type edges (+1 to +2), peripheral-to-hub coupling (+2), and weak-but-present edges (+1) provides richer "why is this surprising?" explanations.

3. **Insight Dismissal** — no way to mark insights as reviewed/dismissed so they don't reappear in GRAPH_REPORT.md.

### Goals

- Add `find_isolated_nodes()`, `find_sparse_communities()`, `find_bridge_nodes()` to analytics
- Replace confidence-only surprise ranking with composite scoring
- Add dismissal state for insights
- Extend GRAPH_REPORT.md to include knowledge gaps section
- Add 3 new toolkit tools for gap detection + 2 for insight management

### Non-Goals (explicitly out of scope)

- Not modifying the signal relevance model (FEAT-190) — this is additive analytics
- Not modifying community detection (FEAT-191) — this consumes CommunitiesResult
- OKF lint operations — that's FEAT-216

---

## 2. Architectural Design

### Overview

Three additive layers on top of existing `analytics.py`:

**Layer 1: Knowledge Gap Detection** — three new functions in `analytics.py`:
- `_find_isolated_nodes(graph, nodes, min_degree=1)` — list of node dicts with degree info
- `_find_sparse_communities(communities_result, min_size=3, max_cohesion=0.15)` — list of Community objects
- `_find_bridge_nodes(graph, nodes, communities_result, min_communities=3)` — list of node dicts with community membership info

All three feed into `AnalyticsResult` via new fields.

**Layer 2: Composite Surprise Scoring** — replace `_rank_surprising_connections()` scoring logic:

| Signal | Points | Description |
|---|---|---|
| Cross-community edge | +3 | Source and target in different Louvain communities |
| Cross-type edge | +1 to +2 | Different NodeKind; distant pairs (SKILL<->DOCUMENT) score +2 |
| Peripheral-to-hub coupling | +2 | Low-degree node (<= 2) linked to high-degree node (>= 50th percentile) |
| Weak-but-present | +1 | Edge confidence below 0.5 |
| High confidence inferred | +1 | Confidence >= 0.7 |

Threshold: `score >= 3` to surface. Each surprising connection carries a decomposed `surprise_factors: list[str]` explaining why.

**Layer 3: Insight Dismissal** — a `DismissedInsights` model tracking dismissed insight IDs. Stored in `domain_tags` on the graph-level metadata (not per-node). `GRAPH_REPORT.md` filters them out.

### Component Diagram

```
                      +---------------------------+
                      |  compute_analytics()      |
                      |  (existing entry point)   |
                      +-------------+-------------+
          +-----------------------+-+-------------------------+
          |                       |                           |
          v                       v                           |
 _compute_god_nodes()  _rank_surprising_connections()         |
 (existing)            (ENHANCED with composite               |
                        scoring)                              |
          +---------------------------------------------------+
          |                       |                           |
          v                       v                           v
 _find_isolated_nodes()  _find_sparse_communities()  _find_bridge_nodes()
 (NEW)                   (NEW, needs                 (NEW, needs
                         CommunitiesResult)            CommunitiesResult)
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `analytics.AnalyticsResult` | extends | Add 3 new fields: `isolated_nodes`, `sparse_communities`, `bridge_nodes` |
| `analytics.compute_analytics()` | extends | Call new gap-detection functions when CommunitiesResult is available |
| `analytics._rank_surprising_connections()` | modifies | Add composite scoring logic; backward-compatible (new fields are additive) |
| `analytics.generate_report()` | extends | Add "Knowledge Gaps" section to GRAPH_REPORT.md |
| `communities.CommunitiesResult` | reads | Consumed for sparse-community and bridge-node detection |
| `GraphIndexToolkit` | extends | Add 5 new tools |

### Data Models

```python
from pydantic import BaseModel, Field
from typing import Optional

class SurpriseFactors(BaseModel):
    """Decomposed explanation of why a connection is surprising."""
    cross_community: bool = False
    cross_type: bool = False
    type_distance: int = 0  # 1 or 2
    peripheral_hub: bool = False
    weak_but_present: bool = False
    high_confidence: bool = False
    composite_score: int = 0

class KnowledgeGaps(BaseModel):
    """Aggregated knowledge gap report."""
    isolated_nodes: list[dict] = Field(default_factory=list)
    sparse_communities: list[dict] = Field(default_factory=list)
    bridge_nodes: list[dict] = Field(default_factory=list)

class DismissedInsights(BaseModel):
    """Tracks dismissed insight IDs."""
    dismissed_ids: set[str] = Field(default_factory=set)
```

### New Public Interfaces

```python
# In analytics.py
def find_isolated_nodes(
    graph: rustworkx.PyDiGraph,
    nodes: list[UniversalNode],
    max_degree: int = 1,
    exclude_kinds: Optional[set[NodeKind]] = None,
) -> list[dict]: ...

def find_sparse_communities(
    communities_result: CommunitiesResult,
    min_size: int = 3,
    max_cohesion: float = 0.15,
) -> list[dict]: ...

def find_bridge_nodes(
    graph: rustworkx.PyDiGraph,
    nodes: list[UniversalNode],
    communities_result: CommunitiesResult,
    min_communities: int = 3,
) -> list[dict]: ...

# In GraphIndexToolkit
async def find_isolated_nodes(self, max_degree: int = 1) -> list[dict]: ...
async def find_sparse_communities(self, min_size: int = 3, max_cohesion: float = 0.15) -> list[dict]: ...
async def find_bridge_nodes(self, min_communities: int = 3) -> list[dict]: ...
async def dismiss_insight(self, insight_id: str) -> dict: ...
async def list_unreviewed_insights(self) -> list[dict]: ...
```

---

## 3. Module Breakdown

### Module 1: Knowledge Gap Detection Functions
- **Path**: `packages/ai-parrot/src/parrot/knowledge/graphindex/analytics.py` (extend)
- **Responsibility**: Three new gap-detection functions + new fields on AnalyticsResult
- **Depends on**: existing analytics.py, communities.CommunitiesResult

### Module 2: Composite Surprise Scoring
- **Path**: `packages/ai-parrot/src/parrot/knowledge/graphindex/analytics.py` (modify)
- **Responsibility**: Enhanced `_rank_surprising_connections()` with composite scoring + SurpriseFactors model
- **Depends on**: Module 1 (needs CommunitiesResult available), existing schema.py

### Module 3: Insight Dismissal State
- **Path**: `packages/ai-parrot/src/parrot/knowledge/graphindex/analytics.py` (extend)
- **Responsibility**: DismissedInsights model, filtering logic in generate_report()
- **Depends on**: Module 2

### Module 4: GRAPH_REPORT.md Knowledge Gaps Section
- **Path**: `packages/ai-parrot/src/parrot/knowledge/graphindex/analytics.py` (modify generate_report)
- **Responsibility**: Add "Knowledge Gaps" section with isolated nodes, sparse communities, bridge nodes
- **Depends on**: Module 1, Module 3

### Module 5: Toolkit Gap Detection & Insight Tools
- **Path**: `packages/ai-parrot-tools/src/parrot_tools/graphindex/toolkit.py` (extend)
- **Responsibility**: 5 new async tools: find_isolated_nodes, find_sparse_communities, find_bridge_nodes, dismiss_insight, list_unreviewed_insights
- **Depends on**: Module 1, Module 3

### Module 6: Tests
- **Path**: `packages/ai-parrot/tests/knowledge/graphindex/test_analytics.py` (extend) + `packages/ai-parrot-tools/tests/graphindex/test_toolkit.py` (extend)
- **Responsibility**: Unit tests for all new functions + toolkit integration tests
- **Depends on**: Module 1-5

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_find_isolated_nodes_basic` | 1 | Graph with mix of connected and isolated nodes returns correct set |
| `test_find_isolated_nodes_excludes_kinds` | 1 | DOCUMENT root nodes excluded when exclude_kinds set |
| `test_find_sparse_communities` | 1 | Low-cohesion communities (< 0.15) flagged, high-cohesion skipped |
| `test_find_sparse_communities_min_size` | 1 | Communities with < min_size members not flagged |
| `test_find_bridge_nodes` | 1 | Node connecting 3+ communities identified; 2-community nodes skipped |
| `test_composite_surprise_cross_community` | 2 | Cross-community edge gets +3 |
| `test_composite_surprise_cross_type` | 2 | Different NodeKind pairs get +1 or +2 based on distance |
| `test_composite_surprise_peripheral_hub` | 2 | Low-degree node linked to high-degree node gets +2 |
| `test_composite_surprise_threshold` | 2 | Only connections with score >= 3 surfaced |
| `test_composite_surprise_factors_decomposed` | 2 | Each connection carries explanation of contributing factors |
| `test_dismiss_insight` | 3 | Dismissed insight ID not in report output |
| `test_list_unreviewed_insights` | 3 | Only non-dismissed insights returned |
| `test_report_knowledge_gaps_section` | 4 | GRAPH_REPORT.md contains "Knowledge Gaps" section with all three gap types |
| `test_toolkit_find_isolated_nodes` | 5 | Toolkit tool returns correct nodes |
| `test_toolkit_find_bridge_nodes` | 5 | Toolkit tool returns correct bridge nodes |
| `test_toolkit_dismiss_insight` | 5 | Toolkit dismiss + list_unreviewed round-trip |

### Test Data / Fixtures

```python
@pytest.fixture
def graph_with_gaps():
    """Graph with isolated nodes, sparse communities, and bridge nodes.

    3 communities: A (tight), B (sparse), C (tight)
    1 bridge node connecting A, B, C
    2 isolated nodes (degree 0 and 1)
    """
    ...
```

---

## 5. Acceptance Criteria

- [ ] `find_isolated_nodes()` returns nodes with degree <= max_degree; structural root nodes (DOCUMENT kind) excluded by default
- [ ] `find_sparse_communities()` returns communities with cohesion < threshold and size >= min_size
- [ ] `find_bridge_nodes()` returns nodes connecting >= min_communities distinct communities
- [ ] Surprising connections use composite scoring with decomposed SurpriseFactors
- [ ] Only connections with composite_score >= 3 surfaced by default
- [ ] `dismiss_insight()` persists dismissal state; `list_unreviewed_insights()` excludes dismissed
- [ ] GRAPH_REPORT.md includes "Knowledge Gaps" section with all three gap types
- [ ] 5 new toolkit tools are auto-registered and callable by agents
- [ ] All existing analytics tests still pass (backward compatible)
- [ ] All new unit tests pass: `pytest tests/knowledge/graphindex/test_analytics.py -v`
- [ ] Toolkit tests pass: `pytest packages/ai-parrot-tools/tests/graphindex/test_toolkit.py -v`

---

## 6. Codebase Contract

> **CRITICAL -- Anti-Hallucination Anchor**
> This section is the single source of truth for what exists in the codebase.
> Implementation agents MUST NOT reference imports, attributes, or methods
> not listed here without first verifying they exist via `grep` or `read`.

### Verified Imports

```python
# verified: packages/ai-parrot/src/parrot/knowledge/graphindex/__init__.py:1-43
from parrot.knowledge.graphindex.schema import (
    UniversalNode,   # line 89 of schema.py
    UniversalEdge,   # line 101 of schema.py
    NodeKind,        # line 32 of schema.py
    EdgeKind,        # line 52 of schema.py
    Provenance,      # line 17 of schema.py
)

# verified: communities.py:69-79
from parrot.knowledge.graphindex.communities import (
    Community,           # line 39
    CommunitiesResult,   # line 69
    detect_communities,  # line 274
    cohesion_for_community,  # line 199
)

# verified: signals.py:89-162
from parrot.knowledge.graphindex.signals import (
    SignalRelevanceConfig,  # line 89
    SignalRelevance,        # line 138
    signal_relevance,       # line 460
    relevance_neighborhood, # line 550
)

# verified: analytics.py:48-82
from parrot.knowledge.graphindex.analytics import (
    AnalyticsResult,       # line 48
    compute_analytics,     # line 77
    generate_report,       # line 268
)
```

### Existing Class Signatures

```python
# packages/ai-parrot/src/parrot/knowledge/graphindex/analytics.py
@dataclass
class AnalyticsResult:
    god_nodes: list[dict] = field(default_factory=list)                # line 66
    surprising_connections: list[dict] = field(default_factory=list)    # line 67
    suggested_questions: list[str] = field(default_factory=list)        # line 68
    communities: Optional["CommunitiesResult"] = None                  # line 69

def compute_analytics(
    graph: rustworkx.PyDiGraph,
    nodes: list[UniversalNode],
    edges: list[UniversalEdge],
    top_k: int = 10,
) -> AnalyticsResult:  # line 77-82

def generate_report(
    analytics: AnalyticsResult,
    output_dir: Path,
    llm_polish: bool = False,
) -> Path:  # line 268-272

def _rank_surprising_connections(
    edges: list[UniversalEdge],
    nodes: list[UniversalNode],
    top_k: int,
) -> list[dict]:  # line 162-166

# packages/ai-parrot/src/parrot/knowledge/graphindex/communities.py
class CommunitiesResult(BaseModel):
    modularity: float          # line 72
    resolution: float          # line 73
    seed: int                  # line 74
    weighted: bool             # line 75
    communities: list[Community]  # line 76
    node_to_community: dict[str, str]  # line 77

# packages/ai-parrot/src/parrot/knowledge/graphindex/schema.py
class UniversalNode(BaseModel):
    node_id: str                            # line 89
    kind: NodeKind                          # line 90
    title: str                              # line 91
    source_uri: str                         # line 92
    domain_tags: dict = Field(default_factory=dict)  # line 96
    provenance: Provenance = Provenance.EXTRACTED     # line 98

class UniversalEdge(BaseModel):
    source_id: str                          # line 117
    target_id: str                          # line 118
    kind: EdgeKind                          # line 119
    provenance: Provenance = Provenance.EXTRACTED  # line 120
    confidence: Optional[float] = None      # line 121

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
```

### Does NOT Exist (Anti-Hallucination)

- ~~`analytics.find_isolated_nodes()`~~ — does not exist yet (this spec creates it)
- ~~`analytics.find_sparse_communities()`~~ — does not exist yet
- ~~`analytics.find_bridge_nodes()`~~ — does not exist yet
- ~~`analytics.SurpriseFactors`~~ — does not exist yet
- ~~`analytics.KnowledgeGaps`~~ — does not exist yet
- ~~`analytics.DismissedInsights`~~ — does not exist yet
- ~~`GraphIndexToolkit.find_isolated_nodes()`~~ — does not exist yet
- ~~`GraphIndexToolkit.dismiss_insight()`~~ — does not exist yet
- ~~`GraphIndexToolkit.list_unreviewed_insights()`~~ — does not exist yet
- ~~`AnalyticsResult.isolated_nodes`~~ — field does not exist yet
- ~~`AnalyticsResult.knowledge_gaps`~~ — field does not exist yet

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- Extend `AnalyticsResult` dataclass with new optional fields (backward compatible)
- Follow existing `_compute_god_nodes()` pattern: private helper -> public via `compute_analytics()`
- New Pydantic models for SurpriseFactors and KnowledgeGaps (consistent with project convention)
- Toolkit tools follow existing `async def method(self, ...) -> dict/list` pattern
- `domain_tags` is already a free-form dict — use it for dismissal state without schema changes

### Known Risks / Gotchas

- Bridge node detection requires CommunitiesResult — if communities not computed, skip gracefully
- Composite surprise scoring adds ~5 fields per surprising connection dict — ensure GRAPH_REPORT.md formatting handles wider rows
- Dismissal state in domain_tags is per-graph-instance; not persisted to ArangoDB unless the graph is re-persisted. This is acceptable for v1 (dismissals are session-scoped).

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| `rustworkx` | `>=0.15` | Already a dependency; used for degree computation |
| `networkx` | `>=3.0` | Already a dependency; used for Louvain (FEAT-191) |

---

## 8. Open Questions

- [x] **Does the composite scoring replace or supplement confidence-based ranking?** — *Resolved in proposal*: Replaces the sort key. Confidence is one of the 5 factors; the composite score is the new primary sort key.
- [x] **Should dismissal state persist to ArangoDB?** — *Resolved*: No for v1. Session-scoped via domain_tags. Persistence deferred to v2 if needed.
- [x] **Should `exclude_kinds` for isolated-node detection be configurable per-toolkit-call or set at toolkit init?** — Recommendation: per-call parameter with a sensible default (exclude DOCUMENT root nodes): per-call as recommended

---

## Worktree Strategy

- **Isolation unit**: per-spec (sequential tasks in one worktree)
- **Cross-feature dependencies**: Requires FEAT-190, FEAT-191, FEAT-192 merged (all are merged)
- Tasks are sequential because Module 2 depends on Module 1, Module 3 on Module 2, etc.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-06-16 | Jesus Lara | Initial draft from FEAT-215 proposal |
