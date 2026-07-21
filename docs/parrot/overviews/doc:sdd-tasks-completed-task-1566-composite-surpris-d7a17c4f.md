---
type: Wiki Overview
title: 'TASK-1566: Composite Surprise Scoring'
id: doc:sdd-tasks-completed-task-1566-composite-surprise-scoring-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: and compute composite scores using the 5-signal system
relates_to:
- concept: mod:parrot.knowledge.graphindex.analytics
  rel: mentions
- concept: mod:parrot.knowledge.graphindex.communities
  rel: mentions
- concept: mod:parrot.knowledge.graphindex.schema
  rel: mentions
---

# TASK-1566: Composite Surprise Scoring

**Feature**: FEAT-215 — GraphIndex Analytics Insights
**Spec**: `sdd/specs/FEAT-215-graphindex-analytics-insights.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1565
**Assigned-to**: unassigned

---

## Context

> Implements Module 2 of FEAT-215. Surprising connections are currently ranked
> by confidence alone. This task replaces that with a composite scoring system
> using 5 signals (cross-community, cross-type, peripheral-hub, weak-but-present,
> high-confidence). Each connection carries a decomposed `SurpriseFactors` model
> explaining *why* it is surprising.

---

## Scope

- Add `SurpriseFactors` Pydantic model in `analytics.py`
- Modify `_rank_surprising_connections()` to accept `communities_result` parameter
  and compute composite scores using the 5-signal system
- Add the graph + degree context needed for peripheral-hub detection
- Threshold: only surface connections with `composite_score >= 3`
- Each connection dict now includes `surprise_factors` (serialized SurpriseFactors) and
  `composite_score` alongside existing fields
- Write unit tests for composite scoring

**NOT in scope**: knowledge gap detection (TASK-1565), insight dismissal (TASK-1567), report changes (TASK-1567), toolkit tools (TASK-1568)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/graphindex/analytics.py` | MODIFY | Add SurpriseFactors model, rewrite _rank_surprising_connections with composite scoring |
| `packages/ai-parrot/tests/knowledge/graphindex/test_analytics.py` | MODIFY | Add composite scoring unit tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase.
> The implementing agent MUST use these exact imports, class names, and method signatures.
> **DO NOT** invent, guess, or assume any import, attribute, or method not listed here.

### Verified Imports
```python
# verified: analytics.py:20-26
from parrot.knowledge.graphindex.schema import (
    EdgeKind,       # line 21 — CONTAINS, REFERENCES, DEFINES, MENTIONS, EXPLAINS
    NodeKind,       # line 22 — DOCUMENT, SECTION, SYMBOL, CONCEPT, RATIONALE, SKILL
    Provenance,     # line 23 — EXTRACTED, INFERRED
    UniversalEdge,  # line 24
    UniversalNode,  # line 25
)

# verified: analytics.py:31 (lazy import)
from parrot.knowledge.graphindex.communities import CommunitiesResult  # line 31
```

### Existing Signatures to Use
```python
# analytics.py:162-195 — the function to MODIFY
def _rank_surprising_connections(
    edges: list[UniversalEdge],
    nodes: list[UniversalNode],
    top_k: int,
) -> list[dict]:
    # Filters for MENTIONS + INFERRED edges
    # Currently sorts by confidence descending
    # Each dict has: source_id, target_id, confidence, source_kind, target_kind

# analytics.py:77-110 — caller that passes result to this function
def compute_analytics(
    graph: rustworkx.PyDiGraph,
    nodes: list[UniversalNode],
    edges: list[UniversalEdge],
    top_k: int = 10,
) -> AnalyticsResult:
    # line 101: surprising_connections = _rank_surprising_connections(edges, nodes, top_k)

# communities.py:69-79
class CommunitiesResult(BaseModel):
    node_to_community: dict[str, str]  # line 77 — maps node_id → community_id

# schema.py:101-121 — UniversalEdge fields
class UniversalEdge(BaseModel):
    source_id: str         # line 117
    target_id: str         # line 118
    kind: EdgeKind         # line 119
    provenance: Provenance # line 120
    confidence: Optional[float] = None  # line 121
```

### Does NOT Exist
- ~~`analytics.SurpriseFactors`~~ — does not exist yet (this task creates it)
- ~~`UniversalEdge.surprise_score`~~ — not a field; composite score is computed externally
- ~~`CommunitiesResult.get_community_for_node()`~~ — use `node_to_community[node_id]` dict lookup
- ~~`NodeKind.distance_to()`~~ — no such method; compute type distance manually

---

## Implementation Notes

### Composite Scoring System

| Signal | Points | Logic |
|---|---|---|
| Cross-community edge | +3 | `communities_result.node_to_community[source_id] != communities_result.node_to_community[target_id]` |
| Cross-type edge | +1 to +2 | Different `NodeKind`; distant pairs (SKILL↔DOCUMENT, SYMBOL↔RATIONALE, etc.) score +2, adjacent pairs +1 |
| Peripheral-to-hub coupling | +2 | Source or target degree <= 2, other degree >= 50th-percentile |
| Weak-but-present | +1 | `confidence < 0.5` |
| High confidence inferred | +1 | `confidence >= 0.7` |

Threshold: `composite_score >= 3` to surface. Sort by `composite_score` descending (tie-break by confidence).

### Type Distance Matrix
Define "distant" type pairs as those spanning different domains. Suggested distant pairs (score +2):
- SKILL ↔ DOCUMENT
- SYMBOL ↔ RATIONALE
- CONCEPT ↔ SKILL

Adjacent/similar pairs (score +1): everything else that's cross-type.

### Signature Change
`_rank_surprising_connections` needs additional parameters:
```python
def _rank_surprising_connections(
    edges: list[UniversalEdge],
    nodes: list[UniversalNode],
    top_k: int,
    graph: Optional[rustworkx.PyDiGraph] = None,
    communities_result: Optional[CommunitiesResult] = None,
) -> list[dict]:
```
The new params are optional for backward compatibility. When `graph` is None, skip peripheral-hub scoring. When `communities_result` is None, skip cross-community scoring.

Update `compute_analytics()` to pass `graph` and `communities_result` (from `AnalyticsResult.communities` set by TASK-1565) to `_rank_surprising_connections()`.

### Key Constraints
- Degree computation uses rustworkx: `graph.in_degree(idx) + graph.out_degree(idx)`
- Need a `node_map` (node_id → graph index) to look up degrees; build from graph node payloads
- 50th percentile degree: use `statistics.median()` or manual computation over all node degrees
- `SurpriseFactors` is Pydantic BaseModel; serialize to dict in the connection dict

### References in Codebase
- `analytics.py:162-195` — current `_rank_surprising_connections()` implementation
- `analytics.py:77-110` — `compute_analytics()` call site
- `analytics.py:178` — existing `node_kind` dict pattern: `{n.node_id: n.kind.value for n in nodes}`

---

## Acceptance Criteria

- [ ] `SurpriseFactors` model has all 6 boolean/int fields + `composite_score`
- [ ] Cross-community edges get +3 when CommunitiesResult is available
- [ ] Cross-type edges get +1 (adjacent) or +2 (distant) based on NodeKind distance
- [ ] Peripheral-to-hub coupling detected and scored +2
- [ ] Only connections with `composite_score >= 3` surfaced
- [ ] Each connection dict includes `surprise_factors` dict and `composite_score` int
- [ ] When CommunitiesResult is None, cross-community scoring gracefully skipped
- [ ] Existing connection dict fields (`source_id`, `target_id`, `confidence`, etc.) preserved
- [ ] All existing analytics tests still pass
- [ ] New tests pass: `pytest packages/ai-parrot/tests/knowledge/graphindex/test_analytics.py -v -k "composite or surprise"`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/knowledge/graphindex/analytics.py`

---

## Test Specification

```python
# packages/ai-parrot/tests/knowledge/graphindex/test_analytics.py
import pytest
from parrot.knowledge.graphindex.analytics import (
    SurpriseFactors,
    _rank_surprising_connections,
)


class TestCompositeSurpriseScoring:
    def test_cross_community_score(self, graph_with_gaps):
        """Cross-community edge gets +3."""
        # Create edges where source and target are in different communities
        ...

    def test_cross_type_distant(self):
        """Distant NodeKind pair (e.g. SKILL↔DOCUMENT) gets +2."""
        ...

    def test_cross_type_adjacent(self):
        """Adjacent NodeKind pair (e.g. CONCEPT↔SECTION) gets +1."""
        ...

    def test_peripheral_hub_coupling(self, graph_with_gaps):
        """Low-degree node linked to high-degree node gets +2."""
        ...

    def test_threshold_filtering(self):
        """Only connections with composite_score >= 3 surfaced."""
        ...

    def test_factors_decomposed(self):
        """Each connection carries SurpriseFactors explaining why."""
        ...

    def test_backward_compat_no_communities(self):
        """Without CommunitiesResult, scoring works (skips cross-community)."""
        ...
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify TASK-1565 is in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source)
   - Check that TASK-1565's changes are present (KnowledgeGaps model, AnalyticsResult.knowledge_gaps field)
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
4. **Update status** in `sdd/tasks/index/graphindex-analytics-insights.json` → `"in-progress"`
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-1566-composite-surprise-scoring.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (Claude Sonnet 4.6)
**Date**: 2026-06-16
**Notes**: Added SurpriseFactors Pydantic model and _DISTANT_TYPE_PAIRS constant. Rewrote _rank_surprising_connections() with 5-signal composite scoring (cross_community +3, cross_type +1/+2, peripheral_hub +2, weak_but_present +1, high_confidence +1). Only connections with composite_score >= 3 surface. Added 10 new tests. Updated 3 existing tests that used node kind pairs producing score < 3 under the new system. All 54 tests pass. Linting clean.

**Deviations from spec**: Updated 3 existing tests (test_inferred_mentions_included, test_ranked_by_confidence_descending, test_result_contains_kind_info) to use node kinds compatible with composite scoring threshold, since the old confidence-only ranking is replaced.
