---
type: Wiki Overview
title: 'TASK-1567: Phase 2 — Graph Expansion Engine'
id: doc:sdd-tasks-completed-task-1567-graph-expansion-engine-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Phase 2 is the core of the graph-expanded retrieval pipeline. Starting from
  seed
relates_to:
- concept: mod:parrot.knowledge.graphindex.signals
  rel: mentions
---

# TASK-1567: Phase 2 — Graph Expansion Engine

**Feature**: FEAT-217 — Graph-Expanded Retrieval Pipeline
**Spec**: `sdd/specs/FEAT-217-graph-expanded-retrieval.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-1566
**Assigned-to**: unassigned

---

## Context

Phase 2 is the core of the graph-expanded retrieval pipeline. Starting from seed
nodes (Phase 1), it traverses the graph N hops outward, scoring each neighbor
using `signal_relevance()` and applying configurable exponential decay per hop.
This is where recall improves from ~58% to ~71% based on nashsu/llm_wiki benchmarks.

Implements spec Section 2 (Phase 2: Graph Expansion) and Section 3 (Module 3).

---

## Scope

- Implement `_expand()` private method on `GraphExpandedRetriever`
- For each seed node, call `relevance_neighborhood()` at depth 1..`max_hops`
- Apply exponential decay: `combined_score = search_score * decay_base^hop * signal_relevance.combined`
- For hop > 1: the "search_score" propagated is the best `combined_score` of the parent node from the previous hop
- Deduplicate by `node_id`: if a node is reachable via multiple paths, keep the highest `combined_score`
- Enforce `min_signal_threshold`: skip neighbors with `signal_relevance.combined < threshold`
- Enforce `max_expanded_nodes`: stop expansion when cap reached
- Cap `candidate_pool` size for high-degree nodes (>100 neighbors) to avoid expensive computation
- Return merged list of `ScoredNode` (seeds + expanded nodes)

**NOT in scope**: Community annotation (TASK-1568), result assembly (TASK-1568)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/graphindex/retriever.py` | MODIFY | Add `_expand()` method |
| `packages/ai-parrot/tests/knowledge/graphindex/test_retriever.py` | MODIFY | Add expansion tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: Use these exact function signatures. Do not invent alternatives.

### Verified Imports

```python
# verified: packages/ai-parrot/src/parrot/knowledge/graphindex/signals.py
from parrot.knowledge.graphindex.signals import (
    SignalRelevance,        # line 138 — Pydantic model
    signal_relevance,       # line 460 — pairwise function
    relevance_neighborhood, # line 550 — batch neighborhood function
    SignalRelevanceConfig,  # line 89
)
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/knowledge/graphindex/signals.py:550
def relevance_neighborhood(
    graph: rustworkx.PyDiGraph,
    nodes: list[UniversalNode],
    node_id: str,
    top_k: int = 10,
    config: Optional[SignalRelevanceConfig] = None,
    candidate_pool: Optional[Iterable[str]] = None,
    embedder: Optional["GraphIndexEmbedder"] = None,
) -> list[SignalRelevance]:
    """Returns list of SignalRelevance objects for node_id's neighbors,
    sorted by combined score descending. Each has .node_b (neighbor id)
    and .combined (float in [0, 1])."""

# packages/ai-parrot/src/parrot/knowledge/graphindex/signals.py:138
class SignalRelevance(BaseModel):
    node_a: str               # line 140
    node_b: str               # line 141
    direct: float             # line 142
    source_overlap: float     # line 143
    adamic_adar: float        # line 144
    type_affinity: float      # line 145
    embedding: float          # line 146
    combined: float           # line 147
    # ... other fields
```

### Does NOT Exist

- ~~`signal_relevance.neighborhood()`~~ — function is `relevance_neighborhood()`, standalone
- ~~`SignalRelevance.score`~~ — field is `.combined`, not `.score`
- ~~`relevance_neighborhood(depth=...)`~~ — no `depth` parameter; it returns 1-hop neighbors only. Multi-hop requires iterative calls.
- ~~`GraphExpandedRetriever._expand_hop()`~~ — does not exist yet; this task may create it as a helper

---

## Implementation Notes

### Multi-Hop Expansion Algorithm

`relevance_neighborhood()` returns 1-hop neighbors only. For multi-hop expansion,
iterate: hop 1 seeds → neighbors → those become seeds for hop 2.

```python
async def _expand(self, seeds: list[ScoredNode], config: ExpansionConfig) -> list[ScoredNode]:
    all_nodes: dict[str, ScoredNode] = {s.node_id: s for s in seeds}
    frontier = [s for s in seeds]

    for hop in range(1, config.max_hops + 1):
        decay = config.decay_base ** hop
        next_frontier = []

        for parent in frontier:
            if len(all_nodes) >= config.max_expanded_nodes:
                break

            neighbors = relevance_neighborhood(
                self.graph, self.nodes, parent.node_id,
                top_k=20,
                config=self.signal_config,
                embedder=self.embedder,
            )

            for sr in neighbors:
                if sr.combined < config.min_signal_threshold:
                    continue
                combined = parent.combined_score * decay * sr.combined
                # ... deduplicate, create ScoredNode, add to next_frontier
        frontier = next_frontier

    return list(all_nodes.values())
```

### Key Constraints
- `relevance_neighborhood()` is SYNC (not async) — call it directly, no `await`
- For seeds, `combined_score` starts as `search_score` (from Phase 1)
- Decay formula: `parent.combined_score * decay_base^hop * signal_relevance.combined`
  - For hop 1 from a seed: `seed.search_score * 0.7 * sr.combined`
  - For hop 2: `hop1_node.combined_score * 0.49 * sr.combined`
- High-degree cap: if a node has >100 neighbors, limit `candidate_pool` to the top-100 by some heuristic (e.g., first 100 from graph adjacency)

### References in Codebase
- `packages/ai-parrot/src/parrot/knowledge/graphindex/signals.py` — `relevance_neighborhood()` implementation
- `packages/ai-parrot/src/parrot/knowledge/graphindex/schema.py` — `UniversalNode` for metadata

---

## Acceptance Criteria

- [ ] `_expand()` method implemented on `GraphExpandedRetriever`
- [ ] Single-hop expansion finds direct neighbors with signal scores
- [ ] Two-hop expansion applies decay correctly (`score * 0.7 * 0.7` for hop 2)
- [ ] Deduplication: same node via two paths keeps highest combined score
- [ ] `min_signal_threshold` exclusion works
- [ ] `max_expanded_nodes` cap enforced
- [ ] Configurable `decay_base` applied correctly
- [ ] High-degree nodes don't cause excessive computation
- [ ] Tests pass: `pytest packages/ai-parrot/tests/knowledge/graphindex/test_retriever.py -v -k "expansion or decay"`
- [ ] No linting errors

---

## Test Specification

```python
# packages/ai-parrot/tests/knowledge/graphindex/test_retriever.py (append)
import pytest
from unittest.mock import patch, MagicMock
import rustworkx


@pytest.fixture
def small_graph():
    """Build a 10-node graph with known topology for expansion tests.
    
    Structure:
      n0 (seed) -> n1 -> n3
      n0 -> n2 -> n3 (n3 reachable via two paths)
      n1 -> n4
      n2 -> n5
    """
    g = rustworkx.PyDiGraph()
    # Add nodes and edges to create the above topology
    # ... (agent implements this)
    return g


class TestGraphExpansion:
    @pytest.mark.asyncio
    async def test_expansion_one_hop(self, small_graph):
        """Single-hop expansion finds direct neighbors with signal scores."""
        # Mock relevance_neighborhood to return known scores
        ...

    @pytest.mark.asyncio
    async def test_expansion_two_hops(self):
        """Two-hop expansion applies decay: score * 0.7 * 0.7 for hop 2."""
        ...

    @pytest.mark.asyncio
    async def test_expansion_deduplication(self):
        """Same node reachable via two paths keeps highest combined score."""
        ...

    @pytest.mark.asyncio
    async def test_expansion_min_threshold(self):
        """Nodes below min_signal_threshold excluded."""
        ...

    @pytest.mark.asyncio
    async def test_expansion_max_nodes_cap(self):
        """Expansion stops at max_expanded_nodes."""
        ...

    def test_decay_exponential(self):
        """Default decay: 0.7^1 = 0.7, 0.7^2 = 0.49, 0.7^3 = 0.343."""
        assert abs(0.7 ** 1 - 0.7) < 1e-9
        assert abs(0.7 ** 2 - 0.49) < 1e-9
        assert abs(0.7 ** 3 - 0.343) < 1e-9

    @pytest.mark.asyncio
    async def test_decay_configurable(self):
        """Custom decay_base=0.5 applied: 0.5^1=0.5, 0.5^2=0.25."""
        ...
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/FEAT-217-graph-expanded-retrieval.spec.md` for full context
2. **Check dependencies** — verify TASK-1565 and TASK-1566 are in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — confirm `relevance_neighborhood()` signature (it's SYNC, not async)
4. **Update status** in `sdd/tasks/index/FEAT-217-graph-expanded-retrieval.json` → `"in-progress"`
5. **Implement** following the scope and codebase contract above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-1567-graph-expansion-engine.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: 
**Date**: 
**Notes**: 

**Deviations from spec**: 
