---
type: Wiki Overview
title: 'TASK-1565: Knowledge Gap Detection Functions'
id: doc:sdd-tasks-completed-task-1565-knowledge-gap-detection-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: from parrot.knowledge.graphindex.schema import (
relates_to:
- concept: mod:parrot.knowledge.graphindex.analytics
  rel: mentions
- concept: mod:parrot.knowledge.graphindex.communities
  rel: mentions
- concept: mod:parrot.knowledge.graphindex.schema
  rel: mentions
---

# TASK-1565: Knowledge Gap Detection Functions

**Feature**: FEAT-215 — GraphIndex Analytics Insights
**Spec**: `sdd/specs/FEAT-215-graphindex-analytics-insights.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

> Implements Module 1 of FEAT-215. GraphIndex analytics currently computes
> god-nodes and surprising connections but has no way to find isolated nodes,
> sparse communities, or bridge nodes. This task adds three knowledge gap
> detection functions, the `KnowledgeGaps` data model, extends
> `AnalyticsResult` with new fields, and wires the new functions into
> `compute_analytics()`.

---

## Scope

- Add `KnowledgeGaps` Pydantic model in `analytics.py`
- Implement `find_isolated_nodes(graph, nodes, max_degree=1, exclude_kinds=None)`
- Implement `find_sparse_communities(communities_result, min_size=3, max_cohesion=0.15)`
- Implement `find_bridge_nodes(graph, nodes, communities_result, min_communities=3)`
- Extend `AnalyticsResult` with `knowledge_gaps: Optional[KnowledgeGaps] = None`
- Extend `compute_analytics()` to call the three gap functions when `CommunitiesResult` is available (bridge nodes and sparse communities need it; isolated nodes can always run)
- Write unit tests for all three functions

**NOT in scope**: composite surprise scoring (TASK-1566), insight dismissal (TASK-1567), GRAPH_REPORT.md changes (TASK-1567), toolkit tools (TASK-1568)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/graphindex/analytics.py` | MODIFY | Add KnowledgeGaps model, 3 gap-detection functions, extend AnalyticsResult + compute_analytics |
| `packages/ai-parrot/tests/knowledge/graphindex/test_analytics.py` | MODIFY | Add unit tests for gap detection |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase.
> The implementing agent MUST use these exact imports, class names, and method signatures.
> **DO NOT** invent, guess, or assume any import, attribute, or method not listed here.
> If you need something not listed, VERIFY it exists first with `grep` or `read`.

### Verified Imports
```python
# verified: packages/ai-parrot/src/parrot/knowledge/graphindex/analytics.py:20-26
from parrot.knowledge.graphindex.schema import (
    EdgeKind,       # line 21
    NodeKind,       # line 22 — enum: DOCUMENT, SECTION, SYMBOL, CONCEPT, RATIONALE, SKILL
    Provenance,     # line 23
    UniversalEdge,  # line 24
    UniversalNode,  # line 25
)

# verified: analytics.py:31 (lazy import, try/except)
from parrot.knowledge.graphindex.communities import CommunitiesResult  # line 31

# verified: communities.py:39-66
from parrot.knowledge.graphindex.communities import Community  # line 39
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/graphindex/analytics.py:48-69
@dataclass
class AnalyticsResult:
    god_nodes: list[dict] = field(default_factory=list)              # line 66
    surprising_connections: list[dict] = field(default_factory=list)  # line 67
    suggested_questions: list[str] = field(default_factory=list)      # line 68
    communities: Optional["CommunitiesResult"] = None                # line 69

# packages/ai-parrot/src/parrot/knowledge/graphindex/analytics.py:77-82
def compute_analytics(
    graph: rustworkx.PyDiGraph,
    nodes: list[UniversalNode],
    edges: list[UniversalEdge],
    top_k: int = 10,
) -> AnalyticsResult:

# packages/ai-parrot/src/parrot/knowledge/graphindex/communities.py:69-79
class CommunitiesResult(BaseModel):
    modularity: float          # line 72
    resolution: float          # line 73
    seed: int                  # line 74
    weighted: bool             # line 75
    communities: list[Community]  # line 76
    node_to_community: dict[str, str]  # line 77

# packages/ai-parrot/src/parrot/knowledge/graphindex/communities.py:39-66
class Community(BaseModel):
    community_id: str              # line 58
    size: int                      # line 59
    member_node_ids: list[str]     # line 60
    centroid_node_id: str          # line 61
    cohesion: float                # line 62
    modularity_contribution: float # line 63
    top_titles: list[str]          # line 64

# packages/ai-parrot/src/parrot/knowledge/graphindex/schema.py:89-98
class UniversalNode(BaseModel):
    node_id: str                                         # line 89
    kind: NodeKind                                       # line 90
    title: str                                           # line 91
    source_uri: str                                      # line 92
    domain_tags: dict = Field(default_factory=dict)      # line 96
    provenance: Provenance = Provenance.EXTRACTED         # line 98

# packages/ai-parrot/src/parrot/knowledge/graphindex/schema.py:32-49
class NodeKind(str, Enum):
    DOCUMENT = "document"   # line 44
    SECTION = "section"     # line 45
    SYMBOL = "symbol"       # line 46
    CONCEPT = "concept"     # line 47
    RATIONALE = "rationale" # line 48
    SKILL = "skill"         # line 49
```

### Does NOT Exist
- ~~`analytics.find_isolated_nodes()`~~ — does not exist yet (this task creates it)
- ~~`analytics.find_sparse_communities()`~~ — does not exist yet
- ~~`analytics.find_bridge_nodes()`~~ — does not exist yet
- ~~`analytics.KnowledgeGaps`~~ — does not exist yet
- ~~`AnalyticsResult.knowledge_gaps`~~ — field does not exist yet
- ~~`AnalyticsResult.isolated_nodes`~~ — NOT a field; gaps are grouped under `knowledge_gaps`
- ~~`Community.is_sparse`~~ — not a method; check `cohesion` field directly
- ~~`CommunitiesResult.bridge_nodes`~~ — not a field; bridge detection is done externally

---

## Implementation Notes

### Pattern to Follow
```python
# Follow the existing _compute_god_nodes() pattern: private helper → public via compute_analytics()
# analytics.py:113-159

def _compute_god_nodes(
    graph: rustworkx.PyDiGraph, top_k: int
) -> list[dict]:
    if graph.num_nodes() == 0:
        return []
    # ... compute and return list[dict]
```

### Key Constraints
- `find_isolated_nodes` uses `rustworkx.PyDiGraph` — get degree with `graph.in_degree(idx) + graph.out_degree(idx)` (rustworkx API, not networkx)
- `find_sparse_communities` operates on `CommunitiesResult.communities` list — filter by `cohesion < max_cohesion` and `size >= min_size`
- `find_bridge_nodes` needs `CommunitiesResult.node_to_community` to check how many distinct communities a node's neighbors belong to
- Node payloads in the graph are dicts with keys: `node_id`, `kind`, `title` (see `_compute_god_nodes` pattern at line 144-156)
- Default `exclude_kinds` for `find_isolated_nodes` should be `{NodeKind.DOCUMENT}` — structural root nodes are expected to have low out-degree
- `KnowledgeGaps` is Pydantic `BaseModel` (consistent with project conventions)
- `AnalyticsResult` is a `@dataclass` — add `knowledge_gaps` as `Optional[KnowledgeGaps] = None` for backward compatibility
- In `compute_analytics()`, call gap functions AFTER god_nodes/surprising_connections; pass `communities=` result if available

### References in Codebase
- `analytics.py:113-159` — `_compute_god_nodes()` as pattern for the three new functions
- `analytics.py:77-110` — `compute_analytics()` as integration point
- `communities.py:69-79` — `CommunitiesResult` model consumed by sparse communities and bridge nodes
- `schema.py:32-49` — `NodeKind` enum for `exclude_kinds` parameter

---

## Acceptance Criteria

- [ ] `find_isolated_nodes()` returns nodes with degree <= max_degree; DOCUMENT kind excluded by default
- [ ] `find_sparse_communities()` returns communities with cohesion < threshold and size >= min_size
- [ ] `find_bridge_nodes()` returns nodes connecting >= min_communities distinct communities
- [ ] `AnalyticsResult` has a `knowledge_gaps` field populated by `compute_analytics()`
- [ ] Gap detection gracefully handles missing CommunitiesResult (sparse_communities and bridge_nodes return empty lists)
- [ ] All existing analytics tests still pass (backward compatible)
- [ ] New unit tests pass: `pytest packages/ai-parrot/tests/knowledge/graphindex/test_analytics.py -v -k "isolated or sparse or bridge or gap"`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/knowledge/graphindex/analytics.py`

---

## Test Specification

```python
# packages/ai-parrot/tests/knowledge/graphindex/test_analytics.py
import pytest
import rustworkx
from parrot.knowledge.graphindex.analytics import (
    AnalyticsResult,
    KnowledgeGaps,
    find_isolated_nodes,
    find_sparse_communities,
    find_bridge_nodes,
)
from parrot.knowledge.graphindex.schema import NodeKind, UniversalNode


@pytest.fixture
def graph_with_gaps():
    """Graph with isolated nodes, sparse communities, and bridge nodes.

    3 communities: A (tight, cohesion > 0.5), B (sparse, cohesion < 0.15), C (tight)
    1 bridge node connecting A, B, C
    2 isolated nodes (degree 0 and degree 1)
    """
    ...


class TestFindIsolatedNodes:
    def test_basic(self, graph_with_gaps):
        """Nodes with degree <= 1 are returned."""
        result = find_isolated_nodes(graph_with_gaps["graph"], graph_with_gaps["nodes"])
        assert len(result) >= 2

    def test_excludes_document_kind(self, graph_with_gaps):
        """DOCUMENT root nodes excluded by default."""
        result = find_isolated_nodes(graph_with_gaps["graph"], graph_with_gaps["nodes"])
        assert all(r["kind"] != "document" for r in result)

    def test_custom_exclude_kinds(self, graph_with_gaps):
        """Custom exclude_kinds is respected."""
        result = find_isolated_nodes(
            graph_with_gaps["graph"], graph_with_gaps["nodes"],
            exclude_kinds={NodeKind.SKILL},
        )
        assert all(r["kind"] != "skill" for r in result)


class TestFindSparseCommunities:
    def test_sparse_flagged(self, graph_with_gaps):
        """Low-cohesion communities returned."""
        result = find_sparse_communities(graph_with_gaps["communities"])
        assert len(result) >= 1
        assert all(c["cohesion"] < 0.15 for c in result)

    def test_min_size_filter(self, graph_with_gaps):
        """Communities below min_size not flagged."""
        result = find_sparse_communities(graph_with_gaps["communities"], min_size=100)
        assert len(result) == 0


class TestFindBridgeNodes:
    def test_bridge_found(self, graph_with_gaps):
        """Node connecting 3+ communities identified."""
        result = find_bridge_nodes(
            graph_with_gaps["graph"], graph_with_gaps["nodes"],
            graph_with_gaps["communities"], min_communities=3,
        )
        assert len(result) >= 1

    def test_two_community_skipped(self, graph_with_gaps):
        """Nodes in only 2 communities not returned when min_communities=3."""
        result = find_bridge_nodes(
            graph_with_gaps["graph"], graph_with_gaps["nodes"],
            graph_with_gaps["communities"], min_communities=3,
        )
        assert all(r["community_count"] >= 3 for r in result)
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — this task has no dependencies
3. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source)
   - Confirm every class/method in "Existing Signatures" still has the listed attributes
   - If anything has changed, update the contract FIRST, then implement
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
4. **Update status** in `sdd/tasks/index/graphindex-analytics-insights.json` → `"in-progress"` with your session ID
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-1565-knowledge-gap-detection.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (Claude Sonnet 4.6)
**Date**: 2026-06-16
**Notes**: Implemented KnowledgeGaps Pydantic model, find_isolated_nodes(), find_sparse_communities(), and find_bridge_nodes() in analytics.py. Extended AnalyticsResult with knowledge_gaps field. Updated compute_analytics() to always run isolated-node detection and populate knowledge_gaps. Added 18 new unit tests (44 total pass). Linting clean.

**Deviations from spec**: none
