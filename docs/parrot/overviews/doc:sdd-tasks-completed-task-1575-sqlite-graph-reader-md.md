---
type: Wiki Overview
title: 'TASK-1575: SQLiteGraphReader'
id: doc:sdd-tasks-completed-task-1575-sqlite-graph-reader-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: The SQLiteGraphReader is the read-side navigator. It loads the graph topology
relates_to:
- concept: mod:parrot.knowledge.graphindex.persist_sqlite
  rel: mentions
- concept: mod:parrot.knowledge.graphindex.schema
  rel: mentions
- concept: mod:parrot.knowledge.graphindex.sqlite_reader
  rel: mentions
---

# TASK-1575: SQLiteGraphReader

**Feature**: FEAT-240 — GraphIndex Odoo-aware Extractor + SQLite Persistence + Graph Reader
**Spec**: `sdd/specs/odoo-graphindex-code.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-1573
**Assigned-to**: unassigned

---

## Context

The SQLiteGraphReader is the read-side navigator. It loads the graph topology
from a SQLite artefact (produced by SQLitePersistence) into an in-memory
`rustworkx.PyDiGraph` for instant deterministic navigation, and provides
async methods for FTS5/BM25 lexical search and disk-based source resolution.

Implements Spec §3 Module 5. Reference implementation in brainstorm §6.

---

## Scope

- Create `SQLiteGraphReader` class with:
  - `__init__(db_path, *, repo_root=None, body_cache_size=256)`
  - `async load()` — read all nodes/edges into rustworkx graph + build model index
  - `async close()` — close aiosqlite connection
  - HOT sync navigation:
    - `get_node(node_id)` → node payload dict
    - `list_models()` → sorted list of model names
    - `children(node_id, *, symbol_type=None)` → CONTAINS children
    - `who_extends(model_name, *, include_definers=False)` → classes with EXTENDS/DEFINES edges
    - `find_model(model_name)` → aggregate view with all contributors, fields, methods
  - COLD async I/O:
    - `search_symbols(query, *, limit=20)` → FTS5/BM25 results
    - `get_source(node_id)` → line-span slice from disk, LRU-cached
- `_require_loaded()` guard on all navigation methods
- LRU body cache with configurable size
- Write comprehensive tests

**NOT in scope**: Builder wiring, OdooCodeExtractor, OKF projection for reader output

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/graphindex/sqlite_reader.py` | CREATE | SQLiteGraphReader class |
| `packages/ai-parrot/tests/knowledge/graphindex/test_sqlite_reader.py` | CREATE | Tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
import rustworkx as rx      # verified: assemble.py:17, pyproject.toml:159 (>=0.15)
import aiosqlite             # verified: storage/backends/sqlite.py:25 (transitive via asyncdb)
import orjson                # verified: used in tools, outputs, security modules
from pathlib import Path
from collections import OrderedDict
```

### Existing Signatures to Use

The reader reads from the SQLite schema created by `SQLitePersistence` (TASK-1573):
- `nodes` table: `node_id`, `kind`, `title`, `source_uri`, `parent_id`, `summary`, `content_ref`, `provenance`, `domain_tags` (JSON)
- `edges` table: `source_id`, `target_id`, `kind`, `provenance`, `confidence`, `source_uri`
- `nodes_fts` virtual table: `node_id` (UNINDEXED), `title`, `summary`

```python
# rustworkx usage pattern (from assemble.py):
graph = rx.PyDiGraph()         # assemble.py:37
idx = graph.add_node(payload)  # returns int index
graph.add_edge(u, v, kind)     # u, v are int indexes
graph.out_edges(idx)           # returns list of (u, v, data) tuples
graph.in_edges(idx)            # returns list of (u, v, data) tuples
graph[idx]                     # returns node payload
graph.num_nodes()
graph.num_edges()
```

### Does NOT Exist
- ~~`SQLiteGraphReader`~~ — this task creates it
- ~~`sqlite_reader.py`~~ — file does not exist yet
- ~~`GraphIndexLoader` read methods for SQLite~~ — loader only supports ArangoDB

---

## Implementation Notes

### Design (from brainstorm §6)

The brainstorm provides a complete reference implementation. Key points:

1. **`load()`**: Open DB read-only (`file:...?mode=ro`). Iterate all nodes,
   build `_idx_by_id` (node_id → rustworkx index), `_payload_by_id`
   (node_id → dict), and `_model_index` (model_name → canonical node_id).
   Then iterate edges and add to graph.

2. **HOT methods** (sync, in-memory):
   - `children()`: Follow `out_edges` where `kind == "contains"`, optionally filter by `symbol_type`
   - `who_extends()`: Follow `in_edges` of canonical node where `kind in {"extends"} | {"defines"}`
   - `find_model()`: Combine `who_extends(include_definers=True)` with `children()` of each contributor

3. **COLD methods** (async):
   - `search_symbols()`: FTS5 MATCH query with BM25 scoring
   - `get_source()`: Read line span from disk via `_read_span()` in thread; LRU cache

4. **LRU cache**: `OrderedDict` with `move_to_end` + `popitem(last=False)` for eviction

### Key Constraints
- Open DB in read-only mode (`file:...?mode=ro`, `uri=True`)
- `_require_loaded()` MUST be called at the start of every navigation method
- `_module_of()` heuristic: top path segment of `source_uri`; empty for synthetic URIs
- `get_source()` falls back to `summary` when `repo_root` is not set or file is missing
- BM25 scores from FTS5 are negative (lower = better match); sort ascending

---

## Acceptance Criteria

- [ ] After `load()`, `list_models()` returns sorted model names
- [ ] `who_extends('res.partner')` lists all EXTENDS contributors with `module`
- [ ] `find_model('res.partner')` aggregates fields/methods from all contributors
- [ ] `search_symbols('reconcile')` returns BM25-ordered results (best first)
- [ ] `get_source(node_id)` with `repo_root` returns exact line slice
- [ ] `get_source(node_id)` without `repo_root` returns summary
- [ ] LRU cache respects `body_cache_size`
- [ ] Calling navigation methods before `load()` raises `RuntimeError`
- [ ] Tests pass: `pytest packages/ai-parrot/tests/knowledge/graphindex/test_sqlite_reader.py -v`

---

## Test Specification

```python
import pytest
from pathlib import Path
from parrot.knowledge.graphindex.persist_sqlite import SQLitePersistence
from parrot.knowledge.graphindex.sqlite_reader import SQLiteGraphReader
from parrot.knowledge.graphindex.schema import (
    UniversalNode, UniversalEdge, NodeKind, EdgeKind,
)

@pytest.fixture
async def populated_db(tmp_path):
    """Build a small graph via SQLitePersistence, return db_path."""
    p = SQLitePersistence(db_dir=tmp_path)
    nodes = [...]  # canonical + class + field + method nodes
    edges = [...]  # DEFINES, EXTENDS, CONTAINS edges
    ctx = ...      # mock TenantContext
    await p.persist_graph(ctx, nodes, edges)
    return tmp_path / f"{ctx.tenant_id}.db"

class TestSQLiteGraphReader:
    async def test_load_counts(self, populated_db):
        reader = SQLiteGraphReader(populated_db)
        await reader.load()
        assert len(reader.list_models()) > 0
        await reader.close()

    async def test_who_extends(self, populated_db):
        reader = SQLiteGraphReader(populated_db)
        await reader.load()
        result = reader.who_extends("res.partner")
        assert len(result) >= 1
        assert all("module" in r for r in result)
        await reader.close()

    async def test_find_model_aggregates(self, populated_db):
        reader = SQLiteGraphReader(populated_db)
        await reader.load()
        model = reader.find_model("res.partner")
        assert model is not None
        assert "fields" in model
        assert "methods" in model
        await reader.close()

    async def test_search_symbols(self, populated_db):
        reader = SQLiteGraphReader(populated_db)
        await reader.load()
        results = await reader.search_symbols("partner")
        assert len(results) > 0
        await reader.close()

    async def test_get_source_with_repo(self, populated_db, tmp_path):
        # Write a dummy source file, then verify get_source reads it
        ...

    async def test_lru_eviction(self, populated_db):
        reader = SQLiteGraphReader(populated_db, body_cache_size=2)
        await reader.load()
        # Access 3 sources, verify cache size stays at 2
        ...

    def test_not_loaded_raises(self):
        reader = SQLiteGraphReader(Path("/nonexistent.db"))
        with pytest.raises(RuntimeError, match="load"):
            reader.list_models()
```

---

## Completion Note

Created `SQLiteGraphReader` in `sqlite_reader.py`. `load()` opens the DB
read-only (`file:...?mode=ro, uri=True`) and builds `_idx_by_id`,
`_payload_by_id`, and `_model_index` from the `nodes` table, then adds all
`edges` to the `rustworkx.PyDiGraph`. HOT sync navigation:
`list_models()`(sorted), `get_node()`, `children()` (CONTAINS edges with
optional `symbol_type` filter), `who_extends()` (in-edges of canonical node,
`include_definers` flag), `find_model()` (aggregate: contributors + fields +
methods). COLD async: `search_symbols()` (FTS5/BM25 over `nodes_fts`),
`get_source()` (line span from disk via `asyncio.to_thread` + LRU cache,
falls back to summary). `_require_loaded()` guard on all HOT methods. LRU
eviction via `OrderedDict.popitem(last=False)`. All 26 tests pass.
