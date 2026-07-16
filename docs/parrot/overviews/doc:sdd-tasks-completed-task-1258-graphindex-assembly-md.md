---
type: Wiki Overview
title: 'TASK-1258: Graph Assembly — rustworkx PyDiGraph Construction'
id: doc:sdd-tasks-completed-task-1258-graphindex-assembly-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: This task implements the **graph assembly** stage of the GraphIndex pipeline.
  After extractors produce streams of `UniversalNode` and `UniversalEdge`, this stage
  constructs a `rustworkx.PyDiGraph` — the in-memory knowledge graph. Node payloads
  contain IDs and metadata only (sourc
relates_to:
- concept: mod:parrot.knowledge.graphindex.assemble
  rel: mentions
- concept: mod:parrot.knowledge.graphindex.schema
  rel: mentions
- concept: mod:parrot.knowledge.ontology
  rel: mentions
---

# TASK-1258: Graph Assembly — rustworkx PyDiGraph Construction

**Feature**: FEAT-187 — GraphIndex — Structured Knowledge Graph Indexing
**Spec**: `sdd/specs/graphindex.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1253
**Assigned-to**: unassigned

---

## Context

This task implements the **graph assembly** stage of the GraphIndex pipeline. After extractors produce streams of `UniversalNode` and `UniversalEdge`, this stage constructs a `rustworkx.PyDiGraph` — the in-memory knowledge graph. Node payloads contain IDs and metadata only (source bodies are referenced via `content_ref`, not stored in the graph). The graph supports per-tenant isolation, consistent with the existing `OntologyGraphStore` pattern.

Implements: Spec §3 Module 4 (Graph Assembly).

---

## Scope

- Build a `rustworkx.PyDiGraph` from streams of `UniversalNode` and `UniversalEdge`
- Node payloads: IDs + metadata only (source bodies via `content_ref`, not stored in graph)
- Provide query methods: `get_node()`, `get_neighbors()`, `get_edges_for_node()`
- Per-tenant graph instances (consistent with `OntologyGraphStore` isolation model)
- Handle duplicate node IDs gracefully (update existing node, log warning)
- Handle edges referencing missing nodes gracefully (log warning, skip edge)

**NOT in scope**: cross-domain resolution, persistence to database, analytics, FAISS index, embedding, extractors, toolkit

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/graphindex/assemble.py` | CREATE | PyDiGraph construction, query methods, per-tenant isolation |
| `packages/ai-parrot/tests/knowledge/graphindex/test_assemble.py` | CREATE | Unit tests for graph assembly |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.knowledge.graphindex.schema import UniversalNode, UniversalEdge
import rustworkx  # new dependency in [graphindex] extra
```

### Existing Patterns to Follow
```python
# Per-tenant isolation pattern from parrot.knowledge.ontology
# OntologyGraphStore uses tenant_id to namespace graph operations
# Follow the same pattern: one GraphAssembler instance per tenant
```

### Does NOT Exist
- ~~`rustworkx` in pyproject.toml~~ — new `[graphindex]` extra needed (handled by TASK-1264)
- ~~`parrot.knowledge.graphindex.assemble`~~ — does not exist yet; this task creates it
- ~~`rustworkx.PyDiGraph.get_node_by_id()`~~ — no such method; must maintain internal ID mapping

---

## Implementation Notes

### Pattern to Follow
```python
import logging
from typing import Optional
import rustworkx

from parrot.knowledge.graphindex.schema import UniversalNode, UniversalEdge

logger = logging.getLogger(__name__)

class GraphAssembler:
    """Build and query a rustworkx PyDiGraph from UniversalNode/UniversalEdge streams.

    Maintains per-tenant graph isolation. Node payloads are lightweight
    metadata dicts (IDs, kind, title, domain_tags); source content is
    referenced via content_ref, not stored in the graph.

    Args:
        tenant_id: Tenant identifier for graph isolation.
    """

    def __init__(self, tenant_id: str) -> None:
        self.tenant_id = tenant_id
        self.graph: rustworkx.PyDiGraph = rustworkx.PyDiGraph()
        self._node_index_map: dict[str, int] = {}  # node_id -> rustworkx index

    def add_node(self, node: UniversalNode) -> int:
        """Add a node to the graph. Updates existing if duplicate node_id.

        Args:
            node: UniversalNode to add.

        Returns:
            The rustworkx index for the node.
        """
        ...

    def add_edge(self, edge: UniversalEdge) -> Optional[int]:
        """Add an edge to the graph. Skips if source/target missing.

        Args:
            edge: UniversalEdge to add.

        Returns:
            The rustworkx edge index, or None if skipped.
        """
        ...

    def add_nodes(self, nodes: list[UniversalNode]) -> list[int]:
        """Batch-add nodes to the graph."""
        return [self.add_node(n) for n in nodes]

    def add_edges(self, edges: list[UniversalEdge]) -> list[Optional[int]]:
        """Batch-add edges to the graph."""
        return [self.add_edge(e) for e in edges]

    def get_node(self, node_id: str) -> Optional[dict]:
        """Get node payload by node_id.

        Returns:
            Node payload dict, or None if not found.
        """
        ...

    def get_neighbors(
        self, node_id: str, direction: str = "outgoing"
    ) -> list[dict]:
        """Get neighboring node payloads.

        Args:
            node_id: The node to query neighbors for.
            direction: "outgoing", "incoming", or "both".

        Returns:
            List of neighbor node payload dicts.
        """
        ...

    def get_edges_for_node(
        self, node_id: str, direction: str = "both"
    ) -> list[dict]:
        """Get edge payloads connected to a node.

        Args:
            node_id: The node to query edges for.
            direction: "outgoing", "incoming", or "both".

        Returns:
            List of edge payload dicts.
        """
        ...

    @property
    def node_count(self) -> int:
        """Number of nodes in the graph."""
        return self.graph.num_nodes()

    @property
    def edge_count(self) -> int:
        """Number of edges in the graph."""
        return self.graph.num_edges()
```

### Key Constraints
- Async-first interfaces where appropriate, but rustworkx operations are synchronous (CPU-bound, fast)
- Type-hinted, Google-style docstrings
- Node payloads stored in graph are lightweight dicts: `{"node_id": ..., "kind": ..., "title": ..., "domain_tags": ..., "content_ref": ...}`
- Do NOT store full source content in the graph — only `content_ref`
- `_node_index_map` is critical: rustworkx uses integer indices internally; this maps `node_id` strings to those indices
- Duplicate `node_id` on `add_node()`: update the existing node's payload, log a warning
- Missing source/target on `add_edge()`: skip the edge, log a warning
- Per-tenant isolation: each `GraphAssembler` instance is scoped to a single tenant

---

## Acceptance Criteria

- [ ] `rustworkx.PyDiGraph` constructed from `UniversalNode` and `UniversalEdge` streams
- [ ] Node payloads contain IDs + metadata only (no source bodies)
- [ ] `get_node()` retrieves node payload by `node_id`
- [ ] `get_neighbors()` returns neighboring nodes (outgoing, incoming, both)
- [ ] `get_edges_for_node()` returns edges connected to a node
- [ ] Duplicate node IDs handled gracefully (update + warning)
- [ ] Missing edge endpoints handled gracefully (skip + warning)
- [ ] Per-tenant graph isolation via `tenant_id`
- [ ] All tests pass: `pytest packages/ai-parrot/tests/knowledge/graphindex/test_assemble.py -v`
- [ ] Import works: `from parrot.knowledge.graphindex.assemble import GraphAssembler`

---

## Test Specification

```python
import pytest
from parrot.knowledge.graphindex.assemble import GraphAssembler
from parrot.knowledge.graphindex.schema import (
    UniversalNode, UniversalEdge, NodeKind, EdgeKind, Provenance,
)


def make_node(node_id: str, title: str, kind: NodeKind = NodeKind.DOCUMENT) -> UniversalNode:
    return UniversalNode(
        node_id=node_id, kind=kind, title=title, source_uri="test.txt",
    )


def make_edge(
    source_id: str, target_id: str, kind: EdgeKind = EdgeKind.CONTAINS
) -> UniversalEdge:
    return UniversalEdge(source_id=source_id, target_id=target_id, kind=kind)


class TestGraphAssembler:
    @pytest.fixture
    def assembler(self):
        return GraphAssembler(tenant_id="test-tenant")

    def test_add_node(self, assembler):
        idx = assembler.add_node(make_node("n1", "Node 1"))
        assert isinstance(idx, int)
        assert assembler.node_count == 1

    def test_add_edge(self, assembler):
        assembler.add_node(make_node("n1", "Node 1"))
        assembler.add_node(make_node("n2", "Node 2"))
        idx = assembler.add_edge(make_edge("n1", "n2"))
        assert isinstance(idx, int)
        assert assembler.edge_count == 1

    def test_get_node(self, assembler):
        assembler.add_node(make_node("n1", "Node 1"))
        payload = assembler.get_node("n1")
        assert payload is not None
        assert payload["node_id"] == "n1"
        assert payload["title"] == "Node 1"

    def test_get_node_missing(self, assembler):
        assert assembler.get_node("nonexistent") is None

    def test_get_neighbors_outgoing(self, assembler):
        assembler.add_node(make_node("n1", "Node 1"))
        assembler.add_node(make_node("n2", "Node 2"))
        assembler.add_node(make_node("n3", "Node 3"))
        assembler.add_edge(make_edge("n1", "n2"))
        assembler.add_edge(make_edge("n1", "n3"))
        neighbors = assembler.get_neighbors("n1", direction="outgoing")
        assert len(neighbors) == 2

    def test_get_neighbors_incoming(self, assembler):
        assembler.add_node(make_node("n1", "Node 1"))
        assembler.add_node(make_node("n2", "Node 2"))
        assembler.add_edge(make_edge("n1", "n2"))
        neighbors = assembler.get_neighbors("n2", direction="incoming")
        assert len(neighbors) == 1
        assert neighbors[0]["node_id"] == "n1"

    def test_get_edges_for_node(self, assembler):
        assembler.add_node(make_node("n1", "Node 1"))
        assembler.add_node(make_node("n2", "Node 2"))
        assembler.add_edge(make_edge("n1", "n2", EdgeKind.CONTAINS))
        edges = assembler.get_edges_for_node("n1")
        assert len(edges) == 1
        assert edges[0]["kind"] == EdgeKind.CONTAINS.value

    def test_duplicate_node_updates(self, assembler):
        assembler.add_node(make_node("n1", "Original"))
        assembler.add_node(make_node("n1", "Updated"))
        assert assembler.node_count == 1
        payload = assembler.get_node("n1")
        assert payload["title"] == "Updated"

    def test_edge_missing_source_skipped(self, assembler):
        assembler.add_node(make_node("n2", "Node 2"))
        idx = assembler.add_edge(make_edge("missing", "n2"))
        assert idx is None
        assert assembler.edge_count == 0

    def test_edge_missing_target_skipped(self, assembler):
        assembler.add_node(make_node("n1", "Node 1"))
        idx = assembler.add_edge(make_edge("n1", "missing"))
        assert idx is None
        assert assembler.edge_count == 0

    def test_per_tenant_isolation(self):
        a1 = GraphAssembler(tenant_id="tenant-a")
        a2 = GraphAssembler(tenant_id="tenant-b")
        a1.add_node(make_node("n1", "A's node"))
        a2.add_node(make_node("n1", "B's node"))
        assert a1.get_node("n1")["title"] == "A's node"
        assert a2.get_node("n1")["title"] == "B's node"

    def test_batch_add(self, assembler):
        nodes = [make_node(f"n{i}", f"Node {i}") for i in range(5)]
        assembler.add_nodes(nodes)
        assert assembler.node_count == 5
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/graphindex.spec.md` for full context
2. **Check dependencies** — TASK-1253 must be completed (provides `UniversalNode`, `UniversalEdge`)
3. **Verify the Codebase Contract** — confirm schema imports work; verify `rustworkx` is installable
4. **Update status** in `sdd/tasks/index/graphindex.json` → `"in-progress"`
5. **Implement** following the scope and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-1258-graphindex-assembly.md`
8. **Update index** → `"done"`

---

## Completion Note

*(Agent fills this in when done)*
