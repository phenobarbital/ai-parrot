# TASK-2064: Leiden Algorithm Integration

**Feature**: FEAT-401 — Leiden Community Detection & Inter-Community Relations
**Spec**: `sdd/specs/leiden-community-detection-and-inter-community-relations.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

This is the foundational task for FEAT-401. It adds Leiden as the default
community detection algorithm in GraphIndex, with Louvain as an automatic
fallback when `leidenalg` is not installed. It also adds
`detect_hierarchical_communities()` for multi-resolution partitions.

Implements Spec §2 (Algorithm layer) and §3 Module 1.

---

## Scope

- Add `_to_igraph()` conversion function in `communities.py` (mirrors
  `_to_undirected_networkx()`): collapse directed edges to undirected,
  apply weights from `signal_config`, include isolated nodes.
- Add `algorithm` parameter (`"leiden"` | `"louvain"`) to
  `detect_communities()` with `"leiden"` as default.
- When `algorithm="leiden"` and `leidenalg` is importable: convert the
  rustworkx graph via `_to_igraph()`, run
  `leidenalg.find_partition(ig_graph, leidenalg.RBConfigurationVertexPartition,
  resolution_parameter=resolution, seed=seed)`, convert the partition
  result back into the existing `Community` / `CommunitiesResult` models.
- When `algorithm="leiden"` and `leidenalg` is NOT importable: log a
  warning and fall back to the existing Louvain / networkx code path.
- When `algorithm="louvain"`: use the existing networkx code path
  unchanged (backward compatibility).
- Add `algorithm: str = "louvain"` field to `CommunitiesResult` (and
  populate it with the algorithm that actually ran — `"leiden"` or
  `"louvain"`).
- Add `HierarchicalCommunitiesResult` model and
  `detect_hierarchical_communities()` function: runs `detect_communities`
  at each resolution in the list, returns one `CommunitiesResult` per
  resolution. Default resolutions: `[0.25, 0.5, 1.0, 2.0, 4.0]`;
  short-circuits to `[1.0]` when graph has <20 nodes.
- Write comprehensive unit tests.

**NOT in scope**:
- Inter-community relations (TASK-2065)
- Builder/analytics integration (TASK-2066)
- HTML export changes (TASK-2067)
- pyproject.toml extras / docs (TASK-2068)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/graphindex/communities.py` | MODIFY | Add `_to_igraph()`, `algorithm` param, Leiden code path, `detect_hierarchical_communities()` |
| `packages/ai-parrot/tests/knowledge/graphindex/test_communities.py` | MODIFY | Add Leiden-specific tests, fallback test, hierarchical tests |

---

## Codebase Contract (Anti-Hallucination)

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
    _centroid_for_community,    # verified: communities.py:300 (private)
    _order_members,             # verified: communities.py:317 (private)
    _write_back,                # verified: communities.py:457 (private)
    _total_edge_weight,         # verified: communities.py:432 (private)
    _community_modularity_contribution,  # verified: communities.py:440 (private)
)

from parrot.knowledge.graphindex.schema import (
    UniversalNode,              # verified: schema.py:143
)

# Signals (FEAT-190, lazy import)
from parrot.knowledge.graphindex.signals import SignalRelevanceConfig
```

### Existing Signatures to Use

```python
# communities.py — current detect_communities signature (line 330)
def detect_communities(
    graph: rustworkx.PyDiGraph,
    nodes: list[UniversalNode],
    resolution: float = 1.0,
    seed: int = 42,
    signal_config: Optional["SignalRelevanceConfig"] = None,
    embedder: Optional[object] = None,
    write_back_to_nodes: bool = True,
) -> CommunitiesResult: ...

# communities.py — CommunitiesResult (line 72)
class CommunitiesResult(BaseModel):
    modularity: float
    resolution: float
    seed: int
    weighted: bool
    communities: list[Community]
    node_to_community: dict[str, str]
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

# communities.py — _to_undirected_networkx (line 164)
# This is the PATTERN to follow for _to_igraph()
def _to_undirected_networkx(
    graph: rustworkx.PyDiGraph,
    nodes: list[UniversalNode],
    signal_config: Optional["SignalRelevanceConfig"] = None,
    embedder: Optional[object] = None,
) -> nx.Graph: ...
```

### Does NOT Exist

- ~~`leidenalg`~~ — not installed; not in any existing extras
- ~~`python-igraph`~~ — not installed; not in any existing extras
- ~~`networkx.community.leiden_communities`~~ — does NOT exist in networkx 3.4.2
- ~~`rustworkx.community_louvain`~~ — does NOT exist in rustworkx 0.17
- ~~`CommunitiesResult.algorithm`~~ — field does not exist yet (to be added)
- ~~`HierarchicalCommunitiesResult`~~ — class does not exist yet (to be created)
- ~~`detect_hierarchical_communities()`~~ — function does not exist yet

---

## Implementation Notes

### Pattern to Follow

```python
# Follow the existing _to_undirected_networkx pattern for _to_igraph:
def _to_igraph(
    graph: rustworkx.PyDiGraph,
    nodes: list[UniversalNode],
    signal_config: Optional["SignalRelevanceConfig"] = None,
    embedder: Optional[object] = None,
) -> "igraph.Graph":
    """Build an undirected igraph view of ``graph``.

    Same semantics as _to_undirected_networkx: directed a→b and b→a
    collapse into one undirected edge (max weight wins); isolated nodes
    are added explicitly.
    """
    import igraph  # lazy — optional dependency
    # ... build edge list, create igraph.Graph from edges + vertices
```

### Key Constraints

- **Lazy imports**: `leidenalg` and `igraph` MUST be imported inside
  `detect_communities()` / `_to_igraph()` with try/except ImportError,
  NOT at module level. This keeps `communities.py` importable without
  the optional dependency.
- **Use `RBConfigurationVertexPartition`**, NOT `ModularityVertexPartition`,
  to match Louvain's resolution parameter semantics.
- `CommunitiesResult` is frozen (`ConfigDict(frozen=True)`). Adding
  `algorithm` as a field with a default is backward-compatible.
- Leiden's partition result is a `leidenalg.VertexPartition` object;
  convert via `.membership` (list of community indices per vertex) and
  build the same `set[str]` partition structure as Louvain.
- The `seed` parameter maps to `leidenalg.find_partition(..., seed=seed)`.
- `detect_hierarchical_communities` can call `detect_communities` in a
  loop — no need for a separate partition mechanism.

### References in Codebase

- `communities.py:164` — `_to_undirected_networkx()` (pattern for `_to_igraph()`)
- `communities.py:330` — `detect_communities()` (function to modify)
- `communities.py:279` — `cohesion_for_community()` (reused for both algorithms)

---

## Acceptance Criteria

- [ ] `detect_communities(algorithm="leiden")` produces well-connected communities when `leidenalg` installed
- [ ] `detect_communities(algorithm="leiden")` falls back to Louvain with warning when `leidenalg` not installed
- [ ] `detect_communities(algorithm="louvain")` produces identical results to pre-FEAT-401 behaviour
- [ ] `CommunitiesResult.algorithm` field records which algorithm was used
- [ ] `_to_igraph()` preserves node count, edge count, and weights from rustworkx graph
- [ ] `detect_hierarchical_communities()` returns one partition per resolution
- [ ] Hierarchical detection short-circuits to `[1.0]` for graphs <20 nodes
- [ ] All tests pass: `pytest packages/ai-parrot/tests/knowledge/graphindex/test_communities.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/knowledge/graphindex/communities.py`

---

## Test Specification

```python
# tests/knowledge/graphindex/test_communities.py (additions)
import pytest
from unittest.mock import patch
from parrot.knowledge.graphindex.communities import (
    detect_communities,
    detect_hierarchical_communities,
    _to_igraph,
    CommunitiesResult,
    HierarchicalCommunitiesResult,
)


class TestLeidenAlgorithm:
    def test_detect_communities_leiden(self, two_clique_graph, sample_nodes):
        """Leiden produces well-connected communities."""
        result = detect_communities(
            two_clique_graph, sample_nodes, algorithm="leiden"
        )
        assert result.algorithm == "leiden"
        assert len(result.communities) >= 2
        # Verify each community is internally connected
        # (no disconnected sub-components within a community)

    def test_detect_communities_leiden_fallback(self, two_clique_graph, sample_nodes):
        """Falls back to Louvain when leidenalg not installed."""
        with patch.dict("sys.modules", {"leidenalg": None, "igraph": None}):
            result = detect_communities(
                two_clique_graph, sample_nodes, algorithm="leiden"
            )
            assert result.algorithm == "louvain"

    def test_detect_communities_louvain_explicit(self, two_clique_graph, sample_nodes):
        """algorithm='louvain' uses networkx path."""
        result = detect_communities(
            two_clique_graph, sample_nodes, algorithm="louvain"
        )
        assert result.algorithm == "louvain"

    def test_to_igraph_conversion(self, two_clique_graph, sample_nodes):
        """rustworkx → igraph preserves topology."""
        ig = _to_igraph(two_clique_graph, sample_nodes)
        # Verify node and edge counts match

    def test_leiden_weighted_edges(self, two_clique_graph, sample_nodes):
        """Signal-weighted edges forwarded to Leiden correctly."""
        # Test with a mock signal_config


class TestHierarchicalCommunities:
    def test_hierarchical_basic(self, hierarchical_graph, sample_nodes):
        """Multi-resolution returns one partition per resolution."""
        result = detect_hierarchical_communities(
            hierarchical_graph, sample_nodes,
            resolutions=[0.5, 1.0, 2.0],
        )
        assert len(result.levels) == 3
        assert result.resolutions == [0.5, 1.0, 2.0]

    def test_hierarchical_nesting(self, hierarchical_graph, sample_nodes):
        """Lower resolution → fewer (larger) communities."""
        result = detect_hierarchical_communities(
            hierarchical_graph, sample_nodes,
            resolutions=[0.5, 2.0],
        )
        assert len(result.levels[0].communities) <= len(result.levels[1].communities)

    def test_hierarchical_tiny_graph_shortcircuit(self, tiny_graph, tiny_nodes):
        """Graphs <20 nodes short-circuit to [1.0]."""
        result = detect_hierarchical_communities(tiny_graph, tiny_nodes)
        assert result.resolutions == [1.0]
        assert len(result.levels) == 1
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — this task has no dependencies
3. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists
   - Confirm `CommunitiesResult` and `detect_communities` signatures match
   - If anything has changed, update the contract FIRST, then implement
4. **Update status** in `sdd/tasks/index/leiden-community-detection-and-inter-community-relations.json` → `"in-progress"`
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-2064-leiden-algorithm-integration.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (autonomous)
**Date**: 2026-08-01
**Notes**: Implemented `_to_igraph()` (rustworkx → igraph, mirrors
`_to_undirected_networkx`), `_run_leiden()` helper (lazy `leidenalg`
import, `RBConfigurationVertexPartition`, falls back to `None` on
`ImportError` with a logged warning naming the missing package),
`algorithm` param on `detect_communities()` (default `"leiden"`,
`"louvain"` unchanged/backward-compatible), `CommunitiesResult.algorithm`
field (default `"louvain"`), `HierarchicalCommunitiesResult` model, and
`detect_hierarchical_communities()` (fixed default resolutions
`[0.25, 0.5, 1.0, 2.0, 4.0]`, short-circuits to `[1.0]` for graphs with
<20 nodes unless resolutions are explicit). Added 16 new tests
(`TestLeidenAlgorithm`, `TestHierarchicalCommunities`) plus new
`_build_hierarchical_graph()` / `_build_tiny_graph()` test fixtures
following the existing `_build_two_cliques()` helper pattern (no pytest
fixtures named in the task's illustrative Test Specification exist in
this repo's `conftest.py` — followed the codebase's actual helper-function
convention instead). Installed `leidenalg`/`python-igraph` into the shared
`.venv` to exercise the real Leiden path in tests (adding them to
`pyproject.toml[leiden]` extra is TASK-2068's scope, not touched here).
Pinned `algorithm="louvain"` explicitly on 2 pre-existing tests whose
names claim Louvain-specific behaviour, since the default flipped to
`"leiden"`. Ran `ruff check --fix` on both files; fixed 2 new PERF102
occurrences the new `_to_igraph()` inherited from mirroring
`_to_undirected_networkx`'s pre-existing pattern. `ruff check` is clean
except 2 pre-existing `B017` findings in `TestPydanticModels` (confirmed
via `git stash` to predate this task — out of scope). All 51 relevant
tests pass; 2 pre-existing `TestBuilderIntegration` failures
(`ModuleNotFoundError: parrot.utils.types`) also confirmed pre-existing
via `git stash` — a known worktree/compiled-extension environment issue
unrelated to this task.

**Deviations from spec**: none.
