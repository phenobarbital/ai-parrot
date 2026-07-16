---
type: Wiki Overview
title: 'TASK-1263: GraphIndex Toolkit — Agent-Facing Tools'
id: doc:sdd-tasks-completed-task-1263-graphindex-toolkit-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: The GraphIndex Toolkit exposes the knowledge graph to AI agents as a set
  of callable tools. It extends `AbstractToolkit`, which auto-discovers public async
  methods and registers them as tools. The toolkit provides 8 methods for querying,
  traversing, and explaining the knowledge g
relates_to:
- concept: mod:parrot.clients.base
  rel: mentions
- concept: mod:parrot.embeddings
  rel: mentions
- concept: mod:parrot.knowledge.graphindex.schema
  rel: mentions
- concept: mod:parrot.tools.toolkit
  rel: mentions
---

# TASK-1263: GraphIndex Toolkit — Agent-Facing Tools

**Feature**: FEAT-187 — GraphIndex — Structured Knowledge Graph Indexing
**Spec**: `sdd/specs/graphindex.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-1253, TASK-1257, TASK-1258
**Assigned-to**: unassigned

---

## Context

The GraphIndex Toolkit exposes the knowledge graph to AI agents as a set of callable tools. It extends `AbstractToolkit`, which auto-discovers public async methods and registers them as tools. The toolkit provides 8 methods for querying, traversing, and explaining the knowledge graph. Hot queries use the in-memory rustworkx graph and FAISS index; cold-start hydration loads state from ArangoDB on first access.

Implements: Spec §5 Toolkit Interface.

---

## Scope

- Implement `GraphIndexToolkit(AbstractToolkit)` with 8 agent-facing methods:
  1. `find_node(query)` — semantic search via FAISS for closest node
  2. `find_references(node_id)` — return all edges where node_id is source or target
  3. `get_neighborhood(node_id, depth=2)` — BFS subgraph around a node
  4. `traverse(from_id, relation, to_kind=None)` — walk edges of a specific relation type, optionally filtered by target kind
  5. `search_hybrid(query, top_k=10)` — combine FAISS similarity with graph proximity
  6. `find_central_nodes(top_k=10, metric="betweenness")` — return top-K central nodes by specified metric
  7. `shortest_path(from_id, to_id)` — shortest path between two nodes via rustworkx
  8. `explain(node_id)` — LLM-generated summary of a node's role using `AbstractClient.ask()`
- Hot queries read from rustworkx PyDiGraph + FAISS index (in-memory)
- Cold-start hydration from ArangoDB on first access (lazy initialization)
- `explain()` uses `AbstractClient.ask()` for LLM summary generation
- Write unit tests for all toolkit methods

**NOT in scope**: Flowtask integration, report generation, community detection, graph mutation (read-only toolkit)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/graphindex/toolkit.py` | CREATE | GraphIndexToolkit with 8 agent-facing methods |
| `packages/ai-parrot-tools/src/parrot_tools/graphindex/__init__.py` | CREATE | Package init with public exports |
| `packages/ai-parrot-tools/tests/graphindex/__init__.py` | CREATE | Test package init |
| `packages/ai-parrot-tools/tests/graphindex/test_toolkit.py` | CREATE | Unit tests for all 8 toolkit methods |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.tools.toolkit import AbstractToolkit
# AbstractToolkit: base class for tool collections
# Public async methods are auto-discovered and registered as tools
# No need to call register_tool() — discovery is automatic

from parrot.clients.base import AbstractClient
# AbstractClient.ask(prompt, model, ...) -> MessageResponse
# AbstractClient.complete() -> str
# Used by explain() for LLM-generated summaries

from parrot.knowledge.graphindex.schema import (
    UniversalNode, UniversalEdge, NodeKind, EdgeKind, Provenance,
)
import rustworkx  # PyDiGraph, dijkstra_shortest_paths, bfs_successors
import faiss  # faiss-cpu; IndexFlatIP for similarity search
```

### Does NOT Exist
- ~~`AbstractClient.embed()`~~ — use `parrot.embeddings` for embedding computation, not AbstractClient
- ~~`AbstractToolkit.register_tool()`~~ — tools are auto-discovered from public async methods
- ~~`get_communities()`~~ — community detection deferred to v1.5
- ~~`GraphIndexToolkit.mutate_graph()`~~ — toolkit is read-only

---

## Implementation Notes

### Pattern to Follow
```python
import logging
from typing import Optional

class GraphIndexToolkit(AbstractToolkit):
    """Agent-facing tools for querying the GraphIndex knowledge graph.

    Provides semantic search, graph traversal, centrality queries,
    and LLM-powered explanations over the knowledge graph.
    """

    def __init__(
        self,
        graph: rustworkx.PyDiGraph,
        faiss_index: faiss.Index,
        node_map: dict[str, int],  # node_id -> rustworkx index
        client: Optional[AbstractClient] = None,  # for explain()
    ):
        super().__init__()
        self.graph = graph
        self.faiss_index = faiss_index
        self.node_map = node_map
        self.client = client
        self.logger = logging.getLogger(__name__)
        self._hydrated = False

    async def find_node(self, query: str) -> dict:
        """Find the most semantically similar node to the query.

        Args:
            query: Natural language search query.

        Returns:
            Dict with node details and similarity score.
        """
        ...

    async def find_references(self, node_id: str) -> list[dict]:
        """Return all edges where node_id is source or target.

        Args:
            node_id: The node to find references for.

        Returns:
            List of edge dicts with source, target, kind, and confidence.
        """
        ...

    async def get_neighborhood(self, node_id: str, depth: int = 2) -> dict:
        """BFS subgraph around a node up to given depth.

        Args:
            node_id: Center node.
            depth: Maximum traversal depth (default 2).

        Returns:
            Dict with nodes and edges in the neighborhood.
        """
        ...

    async def traverse(self, from_id: str, relation: str, to_kind: Optional[str] = None) -> list[dict]:
        """Walk edges of a specific relation type from a node.

        Args:
            from_id: Starting node.
            relation: Edge kind to follow (e.g., 'contains', 'references').
            to_kind: Optional filter for target node kind.

        Returns:
            List of reached node dicts.
        """
        ...

    async def search_hybrid(self, query: str, top_k: int = 10) -> list[dict]:
        """Combine FAISS similarity with graph proximity for hybrid search.

        Args:
            query: Natural language search query.
            top_k: Number of results to return.

        Returns:
            List of node dicts ranked by combined score.
        """
        ...

    async def find_central_nodes(self, top_k: int = 10, metric: str = "betweenness") -> list[dict]:
        """Return top-K most central nodes by specified centrality metric.

        Args:
            top_k: Number of top nodes to return.
            metric: Centrality metric ('betweenness' or 'eigenvector').

        Returns:
            List of node dicts with centrality scores.
        """
        ...

    async def shortest_path(self, from_id: str, to_id: str) -> list[dict]:
        """Find the shortest path between two nodes.

        Args:
            from_id: Source node.
            to_id: Target node.

        Returns:
            Ordered list of node dicts forming the path.
        """
        ...

    async def explain(self, node_id: str) -> str:
        """LLM-generated summary of a node's role in the knowledge graph.

        Args:
            node_id: The node to explain.

        Returns:
            Natural language explanation of the node's significance.
        """
        ...
```

### Key Constraints
- Async-first, type-hinted, Google-style docstrings on every method
- All public methods are auto-discovered by `AbstractToolkit` as agent tools
- `explain()` requires `AbstractClient` — must handle gracefully if client is None
- Cold-start hydration from ArangoDB is lazy (on first method call if graph not loaded)
- All methods are read-only — no graph mutation
- Node lookups must handle missing node_id gracefully (return empty or raise descriptive error)

---

## Acceptance Criteria

- [ ] `GraphIndexToolkit` extends `AbstractToolkit` correctly
- [ ] All 8 methods implemented and auto-discovered as tools
- [ ] `find_node()` returns semantically closest node via FAISS
- [ ] `find_references()` returns all edges for a given node
- [ ] `get_neighborhood()` returns BFS subgraph up to specified depth
- [ ] `traverse()` follows edges of specified relation type with optional kind filter
- [ ] `search_hybrid()` combines FAISS similarity with graph proximity
- [ ] `find_central_nodes()` returns top-K by betweenness or eigenvector centrality
- [ ] `shortest_path()` returns shortest path via rustworkx
- [ ] `explain()` uses AbstractClient.ask() for LLM summary
- [ ] `explain()` handles missing client gracefully
- [ ] All tests pass: `pytest packages/ai-parrot-tools/tests/graphindex/test_toolkit.py -v`

---

## Test Specification

```python
import pytest
from unittest.mock import AsyncMock, MagicMock
from parrot.knowledge.graphindex.schema import (
    UniversalNode, UniversalEdge, NodeKind, EdgeKind,
)

class TestGraphIndexToolkit:
    async def test_find_node_returns_closest(self):
        """find_node returns the semantically closest node from FAISS."""
        # Setup: mock FAISS index with known vectors
        # Assert: correct node returned with similarity score

    async def test_find_references_both_directions(self):
        """find_references returns edges where node is source OR target."""
        # Setup: graph with edges in both directions
        # Assert: both incoming and outgoing edges returned

    async def test_get_neighborhood_respects_depth(self):
        """get_neighborhood BFS stops at specified depth."""
        # Setup: linear graph A->B->C->D, depth=2 from A
        # Assert: A, B, C included; D excluded

    async def test_traverse_filters_by_relation(self):
        """traverse follows only edges of specified relation type."""
        # Setup: node with 'contains' and 'references' edges
        # Assert: only 'contains' targets returned when relation='contains'

    async def test_traverse_filters_by_kind(self):
        """traverse with to_kind filters target nodes by kind."""
        # Setup: edges to nodes of different kinds
        # Assert: only nodes matching to_kind returned

    async def test_search_hybrid_combines_scores(self):
        """search_hybrid blends FAISS similarity and graph proximity."""
        # Setup: mock FAISS and graph
        # Assert: results ranked by combined score

    async def test_find_central_nodes_betweenness(self):
        """find_central_nodes with betweenness metric returns correct ranking."""
        # Setup: graph with known topology
        # Assert: most central node ranked first

    async def test_shortest_path_found(self):
        """shortest_path returns correct path between connected nodes."""
        # Setup: graph A->B->C
        # Assert: path is [A, B, C]

    async def test_shortest_path_no_path(self):
        """shortest_path handles disconnected nodes gracefully."""
        # Setup: disconnected nodes
        # Assert: empty list or appropriate error

    async def test_explain_uses_client(self):
        """explain calls AbstractClient.ask() with node context."""
        # Setup: mock client
        # Assert: client.ask() called, result returned

    async def test_explain_no_client(self):
        """explain without client returns fallback message."""
        # Setup: toolkit with client=None
        # Assert: graceful fallback, no exception
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/graphindex.spec.md` for full context
2. **Check dependencies** — TASK-1253 (schema), TASK-1257 (FAISS), TASK-1258 (graph assembly) must be done
3. **Verify the Codebase Contract** — confirm `AbstractToolkit`, `AbstractClient` interfaces
4. **Update status** in `sdd/tasks/index/graphindex.json` -> `"in-progress"`
5. **Implement** following the scope and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-1263-graphindex-toolkit.md`
8. **Update index** -> `"done"`

---

## Completion Note

*(Agent fills this in when done)*
