---
type: Wiki Overview
title: 'TASK-1568: Toolkit Gap Detection & Insight Management Tools'
id: doc:sdd-tasks-completed-task-1568-toolkit-gap-and-insight-tools-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'from parrot.tools.toolkit import AbstractToolkit # base class'
relates_to:
- concept: mod:parrot.knowledge.graphindex.analytics
  rel: mentions
- concept: mod:parrot.knowledge.graphindex.assemble
  rel: mentions
- concept: mod:parrot.knowledge.graphindex.embed
  rel: mentions
- concept: mod:parrot.knowledge.graphindex.schema
  rel: mentions
- concept: mod:parrot.knowledge.graphindex.signals
  rel: mentions
- concept: mod:parrot.tools.toolkit
  rel: mentions
- concept: mod:parrot_tools.graphindex.toolkit
  rel: mentions
---

# TASK-1568: Toolkit Gap Detection & Insight Management Tools

**Feature**: FEAT-215 — GraphIndex Analytics Insights
**Spec**: `sdd/specs/FEAT-215-graphindex-analytics-insights.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1565, TASK-1566, TASK-1567
**Assigned-to**: unassigned

---

## Context

> Implements Module 5 of FEAT-215. Adds 5 new agent-facing tools to
> `GraphIndexToolkit`: 3 for knowledge gap detection (`find_isolated_nodes`,
> `find_sparse_communities`, `find_bridge_nodes`) and 2 for insight management
> (`dismiss_insight`, `list_unreviewed_insights`). These tools delegate to
> the analytics functions created in TASK-1565, TASK-1566, and TASK-1567.

---

## Scope

- Add `async def find_isolated_nodes(self, max_degree: int = 1) -> list[dict]` to `GraphIndexToolkit`
- Add `async def find_sparse_communities(self, min_size: int = 3, max_cohesion: float = 0.15) -> list[dict]`
- Add `async def find_bridge_nodes(self, min_communities: int = 3) -> list[dict]`
- Add `async def dismiss_insight(self, insight_id: str) -> dict`
- Add `async def list_unreviewed_insights(self) -> list[dict]`
- Store `AnalyticsResult` on the toolkit instance for dismissal state persistence across calls
- Write toolkit integration tests

**NOT in scope**: analytics functions (TASK-1565/1566/1567), report generation changes (TASK-1567)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/graphindex/toolkit.py` | MODIFY | Add 5 new async tool methods |
| `packages/ai-parrot-tools/tests/graphindex/test_toolkit.py` | MODIFY | Add toolkit integration tests for new tools |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase.

### Verified Imports
```python
# verified: toolkit.py:45
from parrot.tools.toolkit import AbstractToolkit  # base class

# verified: toolkit.py:51-55 (TYPE_CHECKING block)
from parrot.knowledge.graphindex.assemble import GraphAssembler
from parrot.knowledge.graphindex.embed import GraphIndexEmbedder
from parrot.knowledge.graphindex.schema import UniversalNode
from parrot.knowledge.graphindex.signals import SignalRelevanceConfig

# Will need (from TASK-1565/1566/1567):
from parrot.knowledge.graphindex.analytics import (
    AnalyticsResult,
    KnowledgeGaps,
    DismissedInsights,
    find_isolated_nodes,
    find_sparse_communities,
    find_bridge_nodes,
    compute_analytics,
    dismiss_insight,
    list_unreviewed_insights,
)
```

### Existing Signatures to Use
```python
# toolkit.py:60-116 — GraphIndexToolkit.__init__
class GraphIndexToolkit(AbstractToolkit):
    def __init__(
        self,
        graph: rustworkx.PyDiGraph,
        faiss_index: faiss.Index,
        node_map: dict[str, int],
        node_id_list: list[str],
        client=None,
        assembler: Optional["GraphAssembler"] = None,
        embedder: Optional["GraphIndexEmbedder"] = None,
        nodes: Optional[list["UniversalNode"]] = None,
        signal_config: Optional["SignalRelevanceConfig"] = None,
    ) -> None:
        # self.graph = graph          (line 105)
        # self.nodes = nodes          (line 112)
        # self.signal_config = ...    (line 113)
        # self._community_cache = ... (line 114)

    # toolkit.py:963-980 — existing community helper pattern
    def _get_or_compute_communities(self):
        # Lazy-computes and caches CommunitiesResult
        # Returns None if communities module not available

    # toolkit.py:935-948 — existing tool pattern for community tools
    async def list_communities(self, min_size: int = 2) -> list[dict]:
        cached = self._get_or_compute_communities()
        if cached is None:
            return [{"error": "..."}]
        return [c.model_dump() for c in cached.communities if c.size >= min_size]
```

### Does NOT Exist
- ~~`GraphIndexToolkit.find_isolated_nodes()`~~ — does not exist yet (this task creates it)
- ~~`GraphIndexToolkit.find_sparse_communities()`~~ — does not exist yet
- ~~`GraphIndexToolkit.find_bridge_nodes()`~~ — does not exist yet
- ~~`GraphIndexToolkit.dismiss_insight()`~~ — does not exist yet
- ~~`GraphIndexToolkit.list_unreviewed_insights()`~~ — does not exist yet
- ~~`GraphIndexToolkit._analytics_result`~~ — does not exist yet; you'll need to add it
- ~~`GraphIndexToolkit.edges`~~ — NOT stored on toolkit; the toolkit has `self.graph` and `self.nodes` but not edges

---

## Implementation Notes

### Tool Pattern
Follow the existing `list_communities` / `find_community` pattern at toolkit.py:935-961:
```python
async def find_isolated_nodes(self, max_degree: int = 1) -> list[dict]:
    """Find nodes with few connections (knowledge gaps)."""
    from parrot.knowledge.graphindex.analytics import find_isolated_nodes as _find
    return _find(self.graph, self.nodes, max_degree=max_degree)
```

### Analytics Result Caching
The toolkit needs to cache an `AnalyticsResult` for dismissal state persistence.
Add `self._analytics_cache: Optional[AnalyticsResult] = None` to `__init__`.

Add a helper:
```python
def _get_or_compute_analytics(self) -> AnalyticsResult:
    if self._analytics_cache is not None:
        return self._analytics_cache
    from parrot.knowledge.graphindex.analytics import compute_analytics
    # Build edges list from graph for compute_analytics
    edges = self._extract_edges_from_graph()
    result = compute_analytics(self.graph, self.nodes, edges)
    # Attach communities if available
    result.communities = self._get_or_compute_communities()
    self._analytics_cache = result
    return result
```

### Edge Extraction
The toolkit doesn't store edges directly. Extract from the graph:
```python
def _extract_edges_from_graph(self) -> list:
    """Build UniversalEdge-like objects from graph edge data."""
    # Graph edge payloads are dicts; convert as needed
    ...
```
Alternatively, the gap detection tools can work directly with the graph without needing the full analytics pipeline.

### Dismissal Tools
```python
async def dismiss_insight(self, insight_id: str) -> dict:
    """Mark an insight as dismissed so it won't appear in future reports."""
    from parrot.knowledge.graphindex.analytics import dismiss_insight as _dismiss
    analytics = self._get_or_compute_analytics()
    _dismiss(analytics, insight_id)
    return {"dismissed": insight_id, "total_dismissed": len(analytics.dismissed.dismissed_ids)}

async def list_unreviewed_insights(self) -> list[dict]:
    """List all insights not yet dismissed."""
    from parrot.knowledge.graphindex.analytics import list_unreviewed_insights as _list
    analytics = self._get_or_compute_analytics()
    return _list(analytics)
```

### Key Constraints
- All tools are `async def` (required by AbstractToolkit auto-discovery)
- Return `list[dict]` or `dict` (consistent with existing toolkit tools)
- Lazy-import analytics functions (follow `_get_or_compute_communities` pattern)
- Invalidate `_analytics_cache` when write tools run (add `self._analytics_cache = None` alongside `self._community_cache = None` in write tool reset logic)
- Each tool needs a docstring — it becomes the LLM's tool description

### References in Codebase
- `toolkit.py:935-980` — `list_communities` / `find_community` / `_get_or_compute_communities` as patterns
- `toolkit.py:483-590` — write tool pattern (for cache invalidation reference)

---

## Acceptance Criteria

- [ ] 5 new toolkit tools are callable: find_isolated_nodes, find_sparse_communities, find_bridge_nodes, dismiss_insight, list_unreviewed_insights
- [ ] `find_isolated_nodes` delegates to analytics function and returns list[dict]
- [ ] `find_sparse_communities` delegates to analytics function and returns list[dict]
- [ ] `find_bridge_nodes` delegates to analytics function and returns list[dict]
- [ ] `dismiss_insight` persists dismissal in cached AnalyticsResult
- [ ] `list_unreviewed_insights` excludes dismissed insights
- [ ] `dismiss_insight` → `list_unreviewed_insights` round-trip works
- [ ] Cache invalidated when write tools run
- [ ] Tools return `{"error": ...}` when communities module not available (for sparse/bridge)
- [ ] All existing toolkit tests still pass
- [ ] New tests pass: `pytest packages/ai-parrot-tools/tests/graphindex/test_toolkit.py -v -k "isolated or sparse or bridge or dismiss or unreviewed"`
- [ ] No linting errors: `ruff check packages/ai-parrot-tools/src/parrot_tools/graphindex/toolkit.py`

---

## Test Specification

```python
# packages/ai-parrot-tools/tests/graphindex/test_toolkit.py
import pytest
from parrot_tools.graphindex.toolkit import GraphIndexToolkit


@pytest.fixture
def toolkit_with_gaps(graph_with_gaps):
    """GraphIndexToolkit initialized with a graph containing knowledge gaps."""
    ...


class TestToolkitGapDetection:
    @pytest.mark.asyncio
    async def test_find_isolated_nodes(self, toolkit_with_gaps):
        """Toolkit returns isolated nodes from the graph."""
        result = await toolkit_with_gaps.find_isolated_nodes()
        assert isinstance(result, list)
        assert len(result) > 0

    @pytest.mark.asyncio
    async def test_find_sparse_communities(self, toolkit_with_gaps):
        """Toolkit returns sparse communities."""
        result = await toolkit_with_gaps.find_sparse_communities()
        assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_find_bridge_nodes(self, toolkit_with_gaps):
        """Toolkit returns bridge nodes."""
        result = await toolkit_with_gaps.find_bridge_nodes()
        assert isinstance(result, list)


class TestToolkitInsightManagement:
    @pytest.mark.asyncio
    async def test_dismiss_insight(self, toolkit_with_gaps):
        """Dismiss returns confirmation dict."""
        result = await toolkit_with_gaps.dismiss_insight("surprise:a:b")
        assert result["dismissed"] == "surprise:a:b"

    @pytest.mark.asyncio
    async def test_dismiss_then_list(self, toolkit_with_gaps):
        """Dismissed insight excluded from unreviewed list."""
        await toolkit_with_gaps.dismiss_insight("surprise:a:b")
        unreviewed = await toolkit_with_gaps.list_unreviewed_insights()
        ids = [i["id"] for i in unreviewed]
        assert "surprise:a:b" not in ids
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify TASK-1565, TASK-1566, TASK-1567 are in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — confirm all prior task changes are present in the codebase
4. **Update status** in `sdd/tasks/index/graphindex-analytics-insights.json` → `"in-progress"`
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-1568-toolkit-gap-and-insight-tools.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (Claude Sonnet 4.6)
**Date**: 2026-06-16
**Notes**: Added 5 new async agent tools to GraphIndexToolkit: find_isolated_nodes,
find_sparse_communities, find_bridge_nodes, dismiss_insight, list_unreviewed_insights.
Added _extract_edges_from_graph() and _get_or_compute_analytics() private helpers for
lazy AnalyticsResult caching. _analytics_cache cleared on community cache invalidation.
Added 10 new integration tests (TestToolkitGapDetection + TestToolkitInsightManagement)
covering gap detection list returns, isolated node filtering, DOCUMENT exclusion, caching,
and dismiss/list round-trip. All 40 toolkit tests pass. Linting clean.

**Deviations from spec**: none
