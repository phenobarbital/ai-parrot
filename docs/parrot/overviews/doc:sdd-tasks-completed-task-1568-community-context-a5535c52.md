---
type: Wiki Overview
title: 'TASK-1568: Phase 3+4 — Community Context and Result Assembly'
id: doc:sdd-tasks-completed-task-1568-community-context-assembly-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Phase 3 annotates expanded nodes with community information (community_id,
  cohesion)
relates_to:
- concept: mod:parrot.knowledge.graphindex.communities
  rel: mentions
- concept: mod:parrot.knowledge.graphindex.retriever
  rel: mentions
---

# TASK-1568: Phase 3+4 — Community Context and Result Assembly

**Feature**: FEAT-217 — Graph-Expanded Retrieval Pipeline
**Spec**: `sdd/specs/FEAT-217-graph-expanded-retrieval.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1567
**Assigned-to**: unassigned

---

## Context

Phase 3 annotates expanded nodes with community information (community_id, cohesion)
and optionally includes community centroid nodes. Phase 4 assembles the final result:
sorts by combined_score, applies token budget, and produces `GraphRetrievalResult`.

This task also wires the public `search()` method that chains all 4 phases into a
single pipeline.

Implements spec Section 2 (Phases 3 and 4) and Section 3 (Module 4).

---

## Scope

- Implement `_annotate_communities()` private method on `GraphExpandedRetriever`
  - Annotate each node's `community_id` and `community_cohesion` from `CommunitiesResult.node_to_community`
  - When `include_community_centroids=True`, add centroid nodes not already in results
- Implement `_assemble_results()` private method
  - Sort nodes by `combined_score` descending
  - Apply token budget: estimate tokens = len(nodes) * `tokens_per_node_estimate`, truncate if over `max_tokens`
  - Set `truncated=True` on result when budget exceeded
  - Populate `GraphRetrievalResult` metadata (total_candidates, nodes_expanded, communities_touched, etc.)
- Wire the public `async def search()` method that:
  1. Calls `_seed_search()` (TASK-1566)
  2. Calls `_expand()` (TASK-1567)
  3. Calls `_annotate_communities()` (this task)
  4. Calls `_assemble_results()` (this task)
  5. Returns `GraphRetrievalResult`
- Remove the `NotImplementedError` stub from `search()` (TASK-1565)

**NOT in scope**: Toolkit integration (TASK-1569)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/graphindex/retriever.py` | MODIFY | Add `_annotate_communities()`, `_assemble_results()`, wire `search()` |
| `packages/ai-parrot/tests/knowledge/graphindex/test_retriever.py` | MODIFY | Add community, budget, sorting, and full pipeline tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: Use these exact imports and signatures. Do not guess alternatives.

### Verified Imports

```python
# verified: packages/ai-parrot/src/parrot/knowledge/graphindex/communities.py
from parrot.knowledge.graphindex.communities import (
    CommunitiesResult,      # line 69
    Community,              # line 39
)
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/knowledge/graphindex/communities.py:69
class CommunitiesResult(BaseModel):
    modularity: float          # line 72
    resolution: float          # line 73
    seed: int                  # line 74
    weighted: bool             # line 75
    communities: list[Community]  # line 76
    node_to_community: dict[str, str]  # line 77
    # KEY: node_to_community maps node_id -> community_id

# packages/ai-parrot/src/parrot/knowledge/graphindex/communities.py:39
class Community(BaseModel):
    community_id: str          # line 58
    size: int                  # line 59
    member_node_ids: list[str] # line 60
    centroid_node_id: str      # line 61
    cohesion: float            # line 62
    modularity_contribution: float  # line 63
    top_titles: list[str]      # line 64
```

### Does NOT Exist

- ~~`CommunitiesResult.get_community(node_id)`~~ — no such method; use `node_to_community[node_id]` to get community_id, then find community in `communities` list
- ~~`Community.centroid`~~ — field is `centroid_node_id` (str), not a node object
- ~~`ScoredNode.annotate()`~~ — no such method; create a new ScoredNode or mutate fields directly (Pydantic v2 allows assignment)

---

## Implementation Notes

### Community Annotation Logic

```python
def _annotate_communities(self, nodes: list[ScoredNode]) -> list[ScoredNode]:
    if self.communities is None:
        return nodes  # Phase 3 gracefully skipped

    # Build community lookup
    community_map = {c.community_id: c for c in self.communities.communities}

    for node in nodes:
        cid = self.communities.node_to_community.get(node.node_id)
        if cid:
            node.community_id = cid
            community = community_map.get(cid)
            if community:
                node.community_cohesion = community.cohesion

    # Optional: include centroids not already in results
    # (only when ExpansionConfig.include_community_centroids is True)
    ...
    return nodes
```

### Token Budget Logic

```python
def _assemble_results(
    self, nodes: list[ScoredNode], query: str,
    budget: BudgetConfig, total_candidates: int,
) -> GraphRetrievalResult:
    sorted_nodes = sorted(nodes, key=lambda n: n.combined_score, reverse=True)
    max_nodes = budget.max_tokens // budget.tokens_per_node_estimate
    truncated = len(sorted_nodes) > max_nodes
    final_nodes = sorted_nodes[:max_nodes]
    ...
```

### Key Constraints
- `_annotate_communities()` is SYNC (no async needed — just dict lookups)
- `_assemble_results()` is SYNC
- `search()` is `async` (calls async `_seed_search`)
- When `communities` is None, Phase 3 is a no-op (return nodes unchanged)
- `communities_touched` = number of distinct community_ids in the final result set

---

## Acceptance Criteria

- [ ] `_annotate_communities()` annotates nodes with `community_id` and `community_cohesion`
- [ ] Centroid nodes included when `include_community_centroids=True` and not already in results
- [ ] Phase 3 gracefully skips when `CommunitiesResult` is None
- [ ] `_assemble_results()` sorts by `combined_score` descending
- [ ] Token budget enforced: truncates results when exceeded, sets `truncated=True`
- [ ] `GraphRetrievalResult` metadata populated correctly
- [ ] Public `search()` wires all 4 phases into a single pipeline
- [ ] Full pipeline test passes: query → seeds → expand → community → result
- [ ] Tests pass: `pytest packages/ai-parrot/tests/knowledge/graphindex/test_retriever.py -v -k "community or budget or sort or pipeline"`
- [ ] No linting errors

---

## Test Specification

```python
# packages/ai-parrot/tests/knowledge/graphindex/test_retriever.py (append)
import pytest
from parrot.knowledge.graphindex.retriever import (
    ScoredNode, GraphRetrievalResult, BudgetConfig,
)


class TestCommunityAnnotation:
    def test_community_annotation(self):
        """Nodes annotated with community_id and cohesion."""
        # Setup CommunitiesResult with known mapping
        # Call _annotate_communities
        # Assert community_id and community_cohesion set
        ...

    def test_community_centroid_inclusion(self):
        """Centroid nodes added when include_community_centroids=True."""
        ...

    def test_no_communities_graceful(self):
        """Phase 3 skipped when no CommunitiesResult."""
        ...


class TestResultAssembly:
    def test_budget_truncation(self):
        """Results truncated when token budget exceeded."""
        ...

    def test_budget_no_truncation(self):
        """All results returned when within budget."""
        ...

    def test_result_sorting(self):
        """Results sorted by combined_score descending."""
        nodes = [
            ScoredNode(node_id="a", title="A", kind="document", combined_score=0.3),
            ScoredNode(node_id="b", title="B", kind="document", combined_score=0.9),
            ScoredNode(node_id="c", title="C", kind="document", combined_score=0.6),
        ]
        # After assembly, order should be b, c, a
        ...


class TestFullPipeline:
    @pytest.mark.asyncio
    async def test_full_pipeline(self):
        """End-to-end: query -> seed -> expand -> community -> result."""
        # Mock all components, run search(), verify GraphRetrievalResult
        ...
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/FEAT-217-graph-expanded-retrieval.spec.md` for full context
2. **Check dependencies** — verify TASK-1565, TASK-1566, TASK-1567 are in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — confirm `CommunitiesResult` and `Community` fields
4. **Update status** in `sdd/tasks/index/FEAT-217-graph-expanded-retrieval.json` → `"in-progress"`
5. **Implement** following the scope and codebase contract above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-1568-community-context-assembly.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: 
**Date**: 
**Notes**: 

**Deviations from spec**: 
