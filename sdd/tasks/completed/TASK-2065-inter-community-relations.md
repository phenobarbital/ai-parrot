# TASK-2065: Inter-Community Relations Model

**Feature**: FEAT-401 — Leiden Community Detection & Inter-Community Relations
**Spec**: `sdd/specs/leiden-community-detection-and-inter-community-relations.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2064
**Assigned-to**: unassigned

---

## Context

This task creates the inter-community relations layer — a meta-graph that
models relationships between communities as directed, weighted edges. This
is the core data model that downstream tasks (analytics, report, HTML
export, CLI) consume.

Implements Spec §2 (Inter-community layer) and §3 Module 2.

---

## Scope

- Create new module `inter_community.py` in the graphindex package.
- Implement `InterCommunityRelation` Pydantic model with fields:
  `source_community_id`, `target_community_id`, `source_label`,
  `target_label`, `directed_edge_count`, `reverse_edge_count`,
  `total_weight`, `reverse_weight`, `coupling_ratio`.
- Implement `InterCommunityGraph` Pydantic model with fields:
  `relations`, `community_count`, `connected_pairs`,
  `total_possible_pairs`, `density`.
- Implement `compute_inter_community_graph(graph, communities_result)`
  function that:
  1. Iterates all edges in the rustworkx `PyDiGraph`.
  2. For each edge where source and target are in different communities,
     accumulates directed edge counts and weights per community pair.
  3. Computes `coupling_ratio` per pair: cross-edges between the pair /
     total incident edges for both communities in the pair.
  4. Computes graph-level density: connected_pairs / C(n, 2).
  5. Populates community labels from `CommunitiesResult.communities`.
- Write comprehensive unit tests.

**NOT in scope**:
- Analytics/report integration (TASK-2066)
- HTML export (TASK-2067)
- CLI subcommand (TASK-2068)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/graphindex/inter_community.py` | CREATE | Models + compute function |
| `packages/ai-parrot/tests/knowledge/graphindex/test_inter_community.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from parrot.knowledge.graphindex.communities import (
    CommunitiesResult,          # verified: communities.py:72
    Community,                  # verified: communities.py:37
)

from parrot.knowledge.graphindex.schema import (
    UniversalNode,              # verified: schema.py:143
)

import rustworkx                # verified: used throughout graphindex
from pydantic import BaseModel, ConfigDict, Field  # verified: used in communities.py
```

### Existing Signatures to Use

```python
# communities.py — CommunitiesResult (line 72)
class CommunitiesResult(BaseModel):
    modularity: float
    resolution: float
    seed: int
    weighted: bool
    communities: list[Community]
    node_to_community: dict[str, str]
    algorithm: str = "louvain"  # added by TASK-2064
    model_config = ConfigDict(frozen=True)

# communities.py — Community (line 37)
class Community(BaseModel):
    community_id: str
    size: int
    member_node_ids: list[str]
    centroid_node_id: str
    cohesion: float
    modularity_contribution: float
    top_titles: list[str]
    label: str = ""
    model_config = ConfigDict(frozen=True)

# rustworkx.PyDiGraph — graph node/edge access
# graph.node_indices() → list of int indices
# graph[idx] → dict payload with "node_id", "kind", "title"
# graph.edge_index_map() → dict[int, (src_idx, tgt_idx, payload)]
```

### Does NOT Exist

- ~~`parrot.knowledge.graphindex.inter_community`~~ — module does not exist yet (to be created)
- ~~`InterCommunityRelation`~~ — class does not exist yet
- ~~`InterCommunityGraph`~~ — class does not exist yet
- ~~`compute_inter_community_graph()`~~ — function does not exist yet
- ~~`CommunitiesResult.inter_community_graph`~~ — no such field

---

## Implementation Notes

### Pattern to Follow

```python
# Follow the same Pydantic + pure-function style as communities.py
from pydantic import BaseModel, ConfigDict, Field

class InterCommunityRelation(BaseModel):
    """A directed relationship between two communities."""
    source_community_id: str
    target_community_id: str
    source_label: str
    target_label: str
    directed_edge_count: int
    reverse_edge_count: int
    total_weight: float
    reverse_weight: float
    coupling_ratio: float
    model_config = ConfigDict(frozen=True)

def compute_inter_community_graph(
    graph: rustworkx.PyDiGraph,
    communities_result: CommunitiesResult,
) -> InterCommunityGraph:
    # 1. Build idx→node_id and node_id→community_id lookups
    # 2. Iterate graph.edge_index_map() — for cross-community edges,
    #    accumulate (src_cid, tgt_cid) → count, weight
    # 3. For coupling_ratio: count all edges incident to either community
    #    (internal + cross), then coupling = cross / total_incident
    # 4. Build InterCommunityRelation per community pair
    # 5. Compute density = connected_pairs / C(n, 2)
```

### Key Constraints

- Use the same `graph[idx]` dict-payload pattern used in
  `communities.py:_to_undirected_networkx` and `analytics.py:find_bridge_nodes`.
- Edge weights come from `graph.edge_index_map()` payload — the dict may
  have a `"weight"` key; default to 1.0 when absent.
- Edges where source == target community are internal — skip them.
- `coupling_ratio` is symmetric for the pair: count ALL cross-edges
  between A and B (both directions), divided by ALL edges incident to
  A or B (including internal edges of both communities).
- Community labels come from `Community.label` in the `CommunitiesResult`.

### References in Codebase

- `communities.py:164` — `_to_undirected_networkx()` shows how to iterate `graph.edge_index_map()`
- `analytics.py:599` — `find_bridge_nodes()` shows how to iterate graph node payloads

---

## Acceptance Criteria

- [ ] `InterCommunityRelation` model has all specified fields
- [ ] `InterCommunityGraph` model has all specified fields
- [ ] `compute_inter_community_graph()` produces correct directed edge counts
- [ ] `compute_inter_community_graph()` distinguishes A→B from B→A in counts
- [ ] Coupling ratio is computed correctly for known topology
- [ ] Communities with no cross-edges produce no relations
- [ ] Density = connected_pairs / C(n, 2)
- [ ] All tests pass: `pytest packages/ai-parrot/tests/knowledge/graphindex/test_inter_community.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/knowledge/graphindex/inter_community.py`

---

## Test Specification

```python
# tests/knowledge/graphindex/test_inter_community.py
import pytest
import rustworkx
from parrot.knowledge.graphindex.inter_community import (
    InterCommunityRelation,
    InterCommunityGraph,
    compute_inter_community_graph,
)
from parrot.knowledge.graphindex.communities import (
    CommunitiesResult,
    Community,
)


@pytest.fixture
def two_community_graph_with_cross_edges():
    """Two 3-node communities with 2 directed cross-edges (A→B and B→A)."""
    graph = rustworkx.PyDiGraph()
    # ... build graph with known topology
    # ... build CommunitiesResult with known partition
    return graph, communities_result


class TestInterCommunityGraph:
    def test_basic_relation(self, two_community_graph_with_cross_edges):
        """Two communities with cross-edges produce one relation."""
        graph, communities = two_community_graph_with_cross_edges
        result = compute_inter_community_graph(graph, communities)
        assert len(result.relations) == 1
        assert result.community_count == 2
        assert result.connected_pairs == 1

    def test_directed_counts(self, two_community_graph_with_cross_edges):
        """Directed edge counts distinguish A→B from B→A."""
        graph, communities = two_community_graph_with_cross_edges
        result = compute_inter_community_graph(graph, communities)
        rel = result.relations[0]
        assert rel.directed_edge_count >= 0
        assert rel.reverse_edge_count >= 0

    def test_coupling_ratio(self, two_community_graph_with_cross_edges):
        """Coupling ratio correct for known topology."""
        graph, communities = two_community_graph_with_cross_edges
        result = compute_inter_community_graph(graph, communities)
        rel = result.relations[0]
        assert 0.0 <= rel.coupling_ratio <= 1.0

    def test_isolated_communities(self):
        """Communities with no cross-edges → no relations."""
        # Build two disconnected cliques
        # ...
        result = compute_inter_community_graph(graph, communities)
        assert len(result.relations) == 0
        assert result.density == 0.0

    def test_density(self):
        """Density = connected_pairs / C(n, 2)."""
        # Build 3 communities, only 1 pair connected
        # density = 1 / C(3,2) = 1/3
        result = compute_inter_community_graph(graph, communities)
        assert result.density == pytest.approx(1 / 3)
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify TASK-2064 is in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — confirm `CommunitiesResult` now has the `algorithm` field (added by TASK-2064)
4. **Update status** in `sdd/tasks/index/leiden-community-detection-and-inter-community-relations.json` → `"in-progress"`
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-2065-inter-community-relations.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (autonomous)
**Date**: 2026-08-01
**Notes**: Created `inter_community.py` with `InterCommunityRelation`,
`InterCommunityGraph` (both frozen Pydantic models) and
`compute_inter_community_graph()`. Iterates `graph.edge_index_map()`,
classifies each edge as internal (same community) or cross-community,
accumulates directed counts/weights per unordered (lexicographically
sorted) community-id pair, and an `incident_edges[cid]` total (internal
edges count once toward their own community; a cross edge counts once
toward each side) used as the coupling-ratio denominator:
`coupling_ratio = cross_total(A,B) / (incident(A) + incident(B))`.
Density = `connected_pairs / C(community_count, 2)`. Wrote 13 new tests
in `test_inter_community.py` with hand-constructed `CommunitiesResult`
fixtures (not going through `detect_communities`, for exact control
over partition + hand-computed expected coupling ratios/density) —
covers basic relation, directed A→B vs B→A counts, label propagation,
coupling ratio on a known topology (hand-computed 0.2), weighted edges,
isolated communities (zero relations/density), 3-community 1-pair-connected
density (1/3), single-community and empty-graph edge cases, and
deterministic ordering. `ruff check --fix` applied cleanly (import
sort + removing a now-redundant quoted forward-reference under
`from __future__ import annotations`); `ruff check` and full test run
are both clean.

**Deviations from spec**: none. The coupling-ratio "total incident
edges for the pair" denominator was under-specified in the spec beyond
prose — implemented as `incident(A) + incident(B)` (each cross edge
counted once per side, matching a standard inter-cluster bond-strength
formula) and locked in with a hand-computed test case.
