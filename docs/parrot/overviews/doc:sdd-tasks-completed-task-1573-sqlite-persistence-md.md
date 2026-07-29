---
type: Wiki Overview
title: 'TASK-1573: SQLitePersistence Backend'
id: doc:sdd-tasks-completed-task-1573-sqlite-persistence-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: The SQLite persistence backend is a new component that materializes the
relates_to:
- concept: mod:parrot.knowledge.graphindex.persist_sqlite
  rel: mentions
- concept: mod:parrot.knowledge.graphindex.schema
  rel: mentions
---

# TASK-1573: SQLitePersistence Backend

**Feature**: FEAT-240 — GraphIndex Odoo-aware Extractor + SQLite Persistence + Graph Reader
**Spec**: `sdd/specs/odoo-graphindex-code.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-1571
**Assigned-to**: unassigned

---

## Context

The SQLite persistence backend is a new component that materializes the
GraphIndex graph into a per-tenant SQLite artefact. It parallels the ArangoDB
`GraphIndexPersistence` with the same public API, plus an `is_stale()` method
for incremental builds. The SQLite artefact is what `SQLiteGraphReader`
(TASK-1575) reads.

Implements Spec §3 Module 3.

---

## Scope

- Create `SQLitePersistence` class with:
  - `__init__(self, db_dir: Path)` — directory where `<tenant_id>.db` files live
  - `persist_graph(ctx, nodes, edges)` — full persist with schema creation
  - `replace_document_slice(ctx, document_uri, nodes, edges)` — atomic DELETE+INSERT per document
  - `is_stale(ctx, source_uri, mtime, sha1)` — returns True if file changed
- SQL schema: `files`, `nodes`, `edges` tables + `nodes_fts` FTS5 virtual table
- WAL journal mode for concurrent read/write
- `domain_tags` stored as JSON (orjson)
- Per-tenant isolation: one `.db` file per `ctx.tenant_id`
- Write comprehensive tests

**NOT in scope**: OdooCodeExtractor, SQLiteGraphReader, builder wiring

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/graphindex/persist_sqlite.py` | CREATE | SQLitePersistence class |
| `packages/ai-parrot/tests/knowledge/graphindex/test_persist_sqlite.py` | CREATE | Tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.knowledge.graphindex.schema import (
    EdgeKind,        # verified: schema.py:53
    NodeKind,        # verified: schema.py:33
    Provenance,      # verified: schema.py:18
    UniversalNode,   # verified: schema.py:71
    UniversalEdge,   # verified: schema.py:102
)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/graphindex/persist.py
# Reference for API parity — match these signatures:
class GraphIndexPersistence:  # line 101
    async def persist_graph(
        self, ctx: TenantContext,
        nodes: list[UniversalNode],
        edges: list[UniversalEdge],
    ) -> dict[str, Any]:  # line 121
    # Returns: {"nodes_persisted": N, "edges_persisted": N}

    async def replace_document_slice(
        self, ctx: TenantContext, document_uri: str,
        nodes: list[UniversalNode],
        edges: list[UniversalEdge],
    ) -> dict[str, Any]:  # line 157
    # Returns: {"nodes_replaced": N, "edges_replaced": N}

# UniversalNode fields for serialization:
class UniversalNode(BaseModel):  # schema.py:71
    node_id: str                                       # line 90
    kind: NodeKind                                     # line 91
    title: str                                         # line 92
    source_uri: str                                    # line 93
    content_ref: Optional[str] = None                  # line 94
    summary: Optional[str] = None                      # line 95
    embedding_ref: Optional[str] = None                # line 96
    domain_tags: dict = Field(default_factory=dict)    # line 97
    parent_id: Optional[str] = None                    # line 98
    provenance: Provenance = Provenance.EXTRACTED       # line 99
```

### Does NOT Exist
- ~~`SQLitePersistence`~~ — this task creates it
- ~~`GraphIndexPersistence.is_stale()`~~ — no such method on the ArangoDB backend
- ~~`persist_sqlite.py`~~ — file does not exist yet

---

## Implementation Notes

### SQL Schema

```sql
PRAGMA journal_mode = WAL;

CREATE TABLE IF NOT EXISTS files (
    source_uri  TEXT PRIMARY KEY,
    mtime       REAL NOT NULL,
    sha1        TEXT NOT NULL,
    indexed_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS nodes (
    node_id       TEXT PRIMARY KEY,
    kind          TEXT NOT NULL,
    title         TEXT NOT NULL,
    source_uri    TEXT NOT NULL,
    parent_id     TEXT,
    summary       TEXT,
    content_ref   TEXT,
    embedding_ref TEXT,
    provenance    TEXT NOT NULL,
    domain_tags   TEXT  -- JSON via orjson
);
CREATE INDEX IF NOT EXISTS idx_nodes_source_uri ON nodes(source_uri);
CREATE INDEX IF NOT EXISTS idx_nodes_parent     ON nodes(parent_id);
CREATE INDEX IF NOT EXISTS idx_nodes_kind       ON nodes(kind);

CREATE TABLE IF NOT EXISTS edges (
    source_id   TEXT NOT NULL,
    target_id   TEXT NOT NULL,
    kind        TEXT NOT NULL,
    provenance  TEXT NOT NULL,
    confidence  REAL,
    source_uri  TEXT,
    PRIMARY KEY (source_id, target_id, kind)
);
CREATE INDEX IF NOT EXISTS idx_edges_kind       ON edges(kind, source_id);
CREATE INDEX IF NOT EXISTS idx_edges_source_uri ON edges(source_uri);

CREATE VIRTUAL TABLE IF NOT EXISTS nodes_fts USING fts5(
    node_id UNINDEXED, title, summary, tokenize = 'unicode61'
);
```

### Key Constraints
- `replace_document_slice` MUST be atomic: DELETE + INSERT in ONE transaction
- `mtime`/`sha1` harvested from the module node's `domain_tags` (not passed separately to persist)
- Canonical model nodes (`source_uri` starting with `odoo-model://`) must NOT be deleted by `replace_document_slice`
- Edges stamped with `source_uri` of the source node for slice-based purge
- Use `orjson.dumps(node.domain_tags).decode()` for JSON serialization

### References in Codebase
- `packages/ai-parrot/src/parrot/knowledge/graphindex/persist.py` — API parity reference
- `packages/ai-parrot/src/parrot/storage/backends/sqlite.py` — aiosqlite usage pattern

---

## Acceptance Criteria

- [ ] `persist_graph` creates the DB, tables, indexes, and FTS5 table
- [ ] `persist_graph` returns `{"nodes_persisted": N, "edges_persisted": N}`
- [ ] `replace_document_slice` atomically replaces nodes/edges for one document
- [ ] `replace_document_slice` does NOT delete canonical nodes (`odoo-model://` URIs)
- [ ] `is_stale` returns `False` when mtime matches
- [ ] `is_stale` returns `True` when sha1 differs
- [ ] FTS5 index is populated (title + summary searchable)
- [ ] Per-tenant isolation: `<tenant_id>.db`
- [ ] WAL mode enabled
- [ ] All tests pass: `pytest packages/ai-parrot/tests/knowledge/graphindex/test_persist_sqlite.py -v`

---

## Test Specification

```python
import pytest
from pathlib import Path
from parrot.knowledge.graphindex.persist_sqlite import SQLitePersistence
from parrot.knowledge.graphindex.schema import (
    UniversalNode, UniversalEdge, NodeKind, EdgeKind, Provenance,
)

@pytest.fixture
def persistence(tmp_path):
    return SQLitePersistence(db_dir=tmp_path)

@pytest.fixture
def sample_nodes():
    return [
        UniversalNode(
            node_id="n1", kind=NodeKind.SYMBOL, title="MyClass",
            source_uri="mod/file.py", domain_tags={"symbol_type": "module", "sha1": "abc", "mtime": 100.0},
        ),
        UniversalNode(
            node_id="n2", kind=NodeKind.SYMBOL, title="res.partner",
            source_uri="odoo-model://res.partner",
            domain_tags={"symbol_type": "odoo_model", "model_name": "res.partner"},
        ),
    ]

class TestSQLitePersistence:
    async def test_persist_roundtrip(self, persistence, sample_nodes):
        ...

    async def test_replace_slice_preserves_canonical(self, persistence, sample_nodes):
        ...

    async def test_is_stale_mtime_match(self, persistence, ...):
        ...

    async def test_is_stale_sha1_differs(self, persistence, ...):
        ...

    async def test_fts5_search(self, persistence, sample_nodes):
        ...
```

---

## Completion Note

Created `SQLitePersistence` in `persist_sqlite.py` with `_connect()` as an
`@asynccontextmanager` using `async with aiosqlite.connect(...)` for proper
thread lifecycle management (avoids the "threads can only be started once"
error from re-using `async with conn` on an already-opened connection). Schema
includes WAL, `files`, `nodes`, `edges` tables with indexes, and `nodes_fts`
FTS5 virtual table with `unicode61` tokenizer. `domain_tags` serialized via
`orjson`. Canonical `odoo-model://` nodes are preserved through
`replace_document_slice`. Per-tenant isolation via `<tenant_id>.db`. All 14
tests pass: DB creation, roundtrip read-back, edge storage, FTS5 search,
canonical node preservation, node replacement, is_stale (not indexed/mtime
match/sha1 mismatch/mtime mismatch), per-tenant isolation, WAL mode, and
return-value shape.
