# TASK-2912: graphindex — honour per-edge payload weights in community detection

**Feature**: FEAT-533 — Bookstore Conceptual Relations
**Spec**: `sdd/specs/wikitoolkit-bookstore-conceptual-relations.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 0. Bookstore will cluster its book graph with
`graphindex.communities.detect_communities` and wants relation types to
carry different weights (`influenced_by` 1.0 … `same_language` 0.1).
Today both conversion loops (`_to_undirected_networkx`, `_to_igraph`)
ignore the rustworkx edge payload entirely and use weight 1.0 unless a
FEAT-190 `signal_config` is supplied, and `GraphAssembler.add_edge`
does not copy `UniversalEdge.domain_tags` into the payload at all. This
task closes both gaps without changing wikitoolkit behaviour (its edges
carry no weight, so the default stays 1.0).

---

## Scope

- In `GraphAssembler.add_edge`, add `"weight": float(edge.domain_tags["weight"])`
  to the payload **only when** `domain_tags` carries a numeric `weight`;
  otherwise leave the payload keys exactly as today.
- In `_to_undirected_networkx` and `_to_igraph`: when `weight_fn is None`,
  use `w = float(_payload.get("weight", 1.0))` if the payload is a dict,
  else `1.0`. When `weight_fn` is set (signal config), signal weights
  still win. Keep the "max weight wins on collapsed pairs" rule.
- In `detect_communities` (both the Leiden and the Louvain return paths)
  and `detect_hierarchical_communities`, set
  `weighted = signal_config is not None or <any payload weight != 1.0>`.
  Compute the payload flag once with a small helper
  (`_has_payload_weights(graph) -> bool`).
- Docstrings: document the payload `weight` contract on the three
  functions and on `add_edge`.
- Tests in `packages/ai-parrot/tests/knowledge/graphindex/test_communities.py`
  (and `test_assemble.py` if it exists — check) per the Test Specification.

**NOT in scope**: anything under `parrot/knowledge/bookstore/`; changing
`compute_inter_community_graph` (it already reads `payload["weight"]`);
wikitoolkit's `_load_graphindex_nodes_edges`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/graphindex/communities.py` | MODIFY | payload weight in both loops + `weighted` flag + helper |
| `packages/ai-parrot/src/parrot/knowledge/graphindex/assemble.py` | MODIFY | copy numeric `domain_tags["weight"]` into the edge payload |
| `packages/ai-parrot/tests/knowledge/graphindex/test_communities.py` | MODIFY | new tests; existing unweighted tests must keep passing unchanged |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.knowledge.graphindex.communities import detect_communities, detect_hierarchical_communities, _to_undirected_networkx, _to_igraph, _build_weight_fn, CommunitiesResult  # communities.py:505, 662, 210, 306, 267, 85
from parrot.knowledge.graphindex.assemble import GraphAssembler   # assemble.py:24
from parrot.knowledge.graphindex.schema import NodeKind, EdgeKind, Provenance, UniversalNode, UniversalEdge  # schema.py:36, 64, ~28, 149, 184
import rustworkx, networkx as nx
```

### Existing Signatures to Use
```python
# graphindex/communities.py
class CommunitiesResult(BaseModel):   # line 85 — modularity, resolution, seed, weighted: bool (line 97), communities, node_to_community, algorithm; frozen
def _to_undirected_networkx(graph, nodes, signal_config=None, embedder=None) -> nx.Graph   # line 210
    # loop (lines ~248-262):
    #   weight_fn = _build_weight_fn(graph, nodes, signal_config, embedder)   # None when no signal_config
    #   for src_idx, tgt_idx, _payload in graph.edge_index_map().values():
    #       ...; w = weight_fn(a, b) if weight_fn is not None else 1.0     # <-- change here
    #       collapsed pairs keep max(existing, w)
def _to_igraph(graph, nodes, signal_config=None, embedder=None)   # line 306 — same loop (lines ~355-373); ig_graph.es["weight"] = list(edge_weight.values())
def _run_leiden(...) -> list[set[str]] | None   # line 381 — None when leidenalg/igraph not importable
def detect_communities(graph, nodes, resolution=1.0, seed=42, signal_config=None, embedder=None, write_back_to_nodes=True, algorithm="leiden") -> CommunitiesResult   # line 505
    # weighted=signal_config is not None   at lines 575 and 639  <-- change both
def detect_hierarchical_communities(graph, nodes, resolutions=None, seed=42, signal_config=None, embedder=None)   # line 662

# graphindex/assemble.py
class GraphAssembler:                                   # line 24
    def add_edge(self, edge: UniversalEdge) -> Optional[int]   # line 77
        # payload = {"source_id", "target_id", "kind", "provenance", "confidence"}   (lines 100-106) — NO domain_tags, NO weight today
        # idx = self.graph.add_edge(src_idx, tgt_idx, payload)                        (line 109)

# graphindex/schema.py
class UniversalEdge(BaseModel): source_id, target_id, kind, provenance, confidence: float | None, assertion, domain_tags: dict   # line 184; confidence set IFF provenance == INFERRED

# tests/knowledge/graphindex/test_communities.py helpers
def _node(node_id, kind=NodeKind.SECTION, title="", source_uri="d.md") -> UniversalNode   # line 39
def _add(graph, n: UniversalNode) -> int                                                    # line 47 — graph.add_node({node_id, kind, title, source_uri, domain_tags})
def _build_two_cliques() -> tuple[rustworkx.PyDiGraph, list[UniversalNode]]                # line 57 — two K5 cliques + bridge A0↔B0; edges added as g.add_edge(i, j, {"kind": ...})
class ...: test_unweighted_edges_have_weight_one (line 182), test_signal_weighted_uses_signal_relevance (205), test_weighted_flag_reflects_signal_config (382), test_unweighted_flag_when_no_signal_config (390)
```

### Does NOT Exist
- ~~`payload["weight"]` handling in `_to_undirected_networkx` / `_to_igraph`~~ — `_payload` is currently an unused loop variable.
- ~~`GraphAssembler.add_edge` copying `domain_tags`~~ — payload has five fixed keys.
- ~~`UniversalEdge.weight`~~ — no such field; weight lives in `domain_tags["weight"]` by convention (this task).
- ~~`CommunitiesResult.weighted` derived from the graph~~ — today it is literally `signal_config is not None`.

---

## Implementation Notes

### Pattern to Follow
```python
# communities.py — inside both loops, replacing `w = weight_fn(a, b) if weight_fn is not None else 1.0`
if weight_fn is not None:
    w = weight_fn(a, b)
else:
    w = float(_payload.get("weight", 1.0)) if isinstance(_payload, dict) else 1.0
```
```python
# assemble.py add_edge — after building `payload`
raw_weight = edge.domain_tags.get("weight") if edge.domain_tags else None
if isinstance(raw_weight, (int, float)) and not isinstance(raw_weight, bool):
    payload["weight"] = float(raw_weight)
```

### Key Constraints
- Zero behaviour change for payload-less edges: the three existing unweighted tests are the guard.
- Non-numeric / negative weights: ignore (fall back to 1.0) and log at debug — never raise inside the conversion loop.
- `compute_inter_community_graph` (`inter_community.py:94`) already reads `payload["weight"]`; after this task the assembler feeds it too — add one assertion that `total_weight` reflects the tag.

### References in Codebase
- `packages/ai-parrot/src/parrot/knowledge/graphindex/communities.py:210-262, 306-380, 560-580, 630-645`
- `packages/ai-parrot/src/parrot/knowledge/graphindex/inter_community.py:94` — existing payload-weight reader (consistency target)

---

## Acceptance Criteria

- [ ] Edge payload `{"weight": 0.2}` yields nx edge weight 0.2 and igraph `es["weight"]` 0.2 when `signal_config is None`
- [ ] With `signal_config`, payload weights are ignored (signal wins)
- [ ] `CommunitiesResult.weighted` is `True` when any payload weight ≠ 1.0, `False` for payload-less graphs, `True` with `signal_config` (existing tests)
- [ ] `GraphAssembler.add_edge` payload gains `weight` only when `domain_tags["weight"]` is numeric
- [ ] `pytest packages/ai-parrot/tests/knowledge/graphindex/ -q` green
- [ ] `ruff check packages/ai-parrot/src/parrot/knowledge/graphindex/`

---

## Test Specification

```python
# packages/ai-parrot/tests/knowledge/graphindex/test_communities.py (append)
class TestPayloadWeights:
    def test_payload_weight_used_without_signal_config(self):
        g = rustworkx.PyDiGraph(); a, b = _node("a"), _node("b")
        ia, ib = _add(g, a), _add(g, b)
        g.add_edge(ia, ib, {"kind": "references", "weight": 0.2})
        nx_graph = _to_undirected_networkx(g, [a, b])
        assert nx_graph["a"]["b"]["weight"] == 0.2

    def test_payload_weight_max_wins_on_collapse(self): ...   # 0.2 one way, 0.9 reverse → 0.9

    def test_payload_weight_ignored_with_signal_config(self): ...   # reuse the signal_config fixture pattern from test_signal_weighted_uses_signal_relevance

    def test_weighted_flag_true_with_payload_weights(self): ...   # detect_communities(...).weighted is True

    def test_non_numeric_payload_weight_falls_back_to_one(self): ...

    def test_assembler_copies_numeric_weight_tag(self):
        asm = GraphAssembler(tenant_id="t"); asm.add_nodes([_node("a"), _node("b")])
        idx = asm.add_edge(UniversalEdge(source_id="a", target_id="b", kind=EdgeKind.REFERENCES,
                                         provenance=Provenance.EXTRACTED, domain_tags={"weight": 0.7}))
        assert asm.graph.get_edge_data_by_index(idx)["weight"] == 0.7

    def test_assembler_omits_weight_when_tag_absent(self): ...
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — none
3. **Verify the Codebase Contract** — confirm the line numbers above still match before editing; update the contract first if not
4. **Update status** in `sdd/tasks/index/wikitoolkit-bookstore-conceptual-relations.json` → `"in-progress"`
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-2912-graphindex-payload-edge-weights.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
