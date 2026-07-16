---
type: Wiki Overview
title: 'TASK-1260: Persistence — ArangoDB via OntologyGraphStore + pgvector'
id: doc:sdd-tasks-completed-task-1260-graphindex-persistence-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Persistence is responsible for durably storing the assembled knowledge graph
  and its embeddings. Nodes go to ArangoDB (via the existing `OntologyGraphStore`
  abstraction), edges go to ArangoDB edge collections, and embeddings go to pgvector.
  This task also implements atomic per-do
relates_to:
- concept: mod:parrot.knowledge.graphindex.schema
  rel: mentions
- concept: mod:parrot.knowledge.ontology.graph_store
  rel: mentions
- concept: mod:parrot.knowledge.ontology.schema
  rel: mentions
---

# TASK-1260: Persistence — ArangoDB via OntologyGraphStore + pgvector

**Feature**: FEAT-187 — GraphIndex — Structured Knowledge Graph Indexing
**Spec**: `sdd/specs/graphindex.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1253
**Assigned-to**: unassigned

---

## Context

Persistence is responsible for durably storing the assembled knowledge graph and its embeddings. Nodes go to ArangoDB (via the existing `OntologyGraphStore` abstraction), edges go to ArangoDB edge collections, and embeddings go to pgvector. This task also implements atomic per-document replacement for incremental refresh — soft-delete-then-upsert — and per-tenant locking for concurrent safety.

This task can run in parallel with other tasks since it only depends on the core schema (TASK-1253).

Implements: Spec §3 Module 6 (Persistence).

---

## Scope

- Write nodes to ArangoDB via `OntologyGraphStore.upsert_nodes` using per-kind vertex collections: `documents`, `sections`, `symbols`, `concepts`, `rationales`, `skills`
- Write edges via `OntologyGraphStore.create_edges` using 5 edge collections (one per `EdgeKind`)
- Write embeddings to pgvector using the tenant's `pgvector_schema` namespace
- Support atomic per-document replacement for incremental refresh:
  - Soft-delete the document's slice via `soft_delete_nodes(ctx, collection, keys)` — uses `_key` values, NOT `key_field`!
  - Re-upsert the new nodes (which sets `_active: true`)
- Per-tenant lock (`asyncio.Lock` keyed by tenant ID) for concurrent safety
- Write unit tests for all persistence logic

**NOT in scope**: graph assembly, analytics, report generation, FAISS index management

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/graphindex/persist.py` | CREATE | Persistence layer: ArangoDB upsert, pgvector write, soft-delete-and-replace, tenant locking |
| `packages/ai-parrot/tests/knowledge/graphindex/test_persist.py` | CREATE | Unit tests for persistence logic |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.knowledge.ontology.graph_store import OntologyGraphStore, UpsertResult
from parrot.knowledge.ontology.schema import TenantContext, MergedOntology
from parrot.knowledge.graphindex.schema import (
    UniversalNode, UniversalEdge, NodeKind, EdgeKind, Provenance,
)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/ontology/graph_store.py
class OntologyGraphStore:
    async def upsert_nodes(self, ctx: TenantContext, collection: str, nodes: list[dict]) -> UpsertResult:
        """Upsert nodes into a vertex collection. Sets _active: true."""
        ...

    async def create_edges(self, ctx: TenantContext, edge_collection: str, edges: list[dict]) -> int:
        """Create edges in an edge collection."""
        ...

    async def soft_delete_nodes(self, ctx: TenantContext, collection: str, keys: list[str]) -> int:
        """Soft-delete nodes by _key values (NOT key_field!). Sets _active: false."""
        ...

    async def get_all_nodes(self, ctx: TenantContext, collection: str, ...) -> list[dict]:
        """Get all active nodes. Filters by _active != false."""
        ...

# packages/ai-parrot/src/parrot/knowledge/ontology/schema.py
class TenantContext(BaseModel):
    tenant_id: str
    pgvector_schema: str  # pgvector namespace for this tenant
    ...
```

### Does NOT Exist
- ~~`OntologyGraphStore.hard_delete_nodes()`~~ — only `soft_delete_nodes` exists
- ~~`OntologyGraphStore.transaction()`~~ — ArangoDB transactions must be managed directly if needed
- ~~`OntologyGraphStore.delete_edges()`~~ — edge cleanup may require direct AQL queries
- ~~pgvector ORM model~~ — use raw pgvector operations via the tenant's schema

---

## Implementation Notes

### Pattern to Follow
```python
import asyncio
from collections import defaultdict

class GraphIndexPersistence:
    """Persists GraphIndex nodes, edges, and embeddings."""

    _tenant_locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

    def __init__(self, graph_store: OntologyGraphStore):
        self.graph_store = graph_store

    async def persist_graph(
        self, ctx: TenantContext, nodes: list[UniversalNode], edges: list[UniversalEdge],
    ) -> dict:
        """Persist all nodes and edges to ArangoDB + embeddings to pgvector."""
        ...

    async def replace_document_slice(
        self, ctx: TenantContext, document_uri: str,
        nodes: list[UniversalNode], edges: list[UniversalEdge],
    ) -> dict:
        """Atomic per-document replacement: soft-delete old, upsert new."""
        async with self._tenant_locks[ctx.tenant_id]:
            # 1. Collect _key values for old nodes belonging to this document
            # 2. soft_delete_nodes for each affected collection
            # 3. upsert_nodes with new data
            # 4. create_edges with new edges
            ...
```

### Key Constraints
- Async-first, type-hinted, Google-style docstrings
- `soft_delete_nodes` takes `_key` values, NOT `key_field` values — this is a critical distinction
- `upsert_nodes` automatically sets `_active: true` on upserted documents
- Per-tenant lock prevents concurrent writes from corrupting the soft-delete-then-upsert sequence
- Vertex collections map 1:1 to `NodeKind` values: document->documents, section->sections, etc.
- Edge collections map 1:1 to `EdgeKind` values: contains, references, defines, mentions, explains

---

## Acceptance Criteria

- [ ] Nodes persisted to correct per-kind ArangoDB vertex collections
- [ ] Edges persisted to correct per-kind ArangoDB edge collections
- [ ] Embeddings written to pgvector under the tenant's schema
- [ ] Atomic per-document replacement works: soft-delete then upsert
- [ ] `soft_delete_nodes` called with `_key` values (not `key_field`)
- [ ] Per-tenant locking prevents concurrent race conditions
- [ ] All tests pass: `pytest packages/ai-parrot/tests/knowledge/graphindex/test_persist.py -v`

---

## Test Specification

```python
import pytest
from unittest.mock import AsyncMock, MagicMock
from parrot.knowledge.graphindex.schema import (
    UniversalNode, UniversalEdge, NodeKind, EdgeKind, Provenance,
)

class TestGraphIndexPersistence:
    def test_nodes_routed_to_correct_collections(self):
        """Each NodeKind maps to the correct ArangoDB vertex collection."""
        # Setup: nodes of different kinds
        # Assert: upsert_nodes called with correct collection names

    def test_edges_routed_to_correct_collections(self):
        """Each EdgeKind maps to the correct ArangoDB edge collection."""
        # Setup: edges of different kinds
        # Assert: create_edges called with correct edge collection names

    def test_soft_delete_uses_key_not_key_field(self):
        """soft_delete_nodes must be called with _key values, not key_field."""
        # Setup: mock graph_store, call replace_document_slice
        # Assert: soft_delete_nodes args are _key values

    def test_atomic_replace_sequence(self):
        """Replace must soft-delete before upserting."""
        # Setup: mock graph_store with call order tracking
        # Assert: soft_delete called before upsert

    def test_tenant_locking(self):
        """Concurrent calls for same tenant must serialize."""
        # Setup: two concurrent replace_document_slice calls
        # Assert: no interleaving of soft-delete and upsert across calls

    def test_empty_nodes_no_op(self):
        """Empty node list should not call upsert."""
        # Assert: upsert_nodes not called
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/graphindex.spec.md` for full context
2. **Check dependencies** — TASK-1253 (core schema) must be done
3. **Verify the Codebase Contract** — confirm `OntologyGraphStore`, `TenantContext` signatures, especially `soft_delete_nodes` parameter semantics
4. **Update status** in `sdd/tasks/index/graphindex.json` -> `"in-progress"`
5. **Implement** following the scope and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-1260-graphindex-persistence.md`
8. **Update index** -> `"done"`

---

## Completion Note

*(Agent fills this in when done)*
