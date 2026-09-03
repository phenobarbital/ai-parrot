# TASK-2765: `PostgresPersistence` — parity surface with bitemporal writes

**Feature**: FEAT-520 — GraphIndex Postgres Backend
**Spec**: `sdd/specs/graphindex-postgres-backend.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: XL (> 8h)
**Depends-on**: TASK-2764
**Assigned-to**: unassigned

---

## Context

Module 2 of FEAT-520: the third GraphIndex backend. Public API mirrors
`GraphIndexPersistence` (`persist.py`) exactly — duck-typed like
`SQLitePersistence` — so `GraphPublisher` and the builder pipeline work
unchanged. Reads are current-time only in this task (temporal API is
TASK-2767), but the WRITE path is bitemporal from day one: corrections
close-and-insert, never UPDATE (spec D2).

---

## Scope

- Implement in `packages/ai-parrot/src/parrot/knowledge/graphindex/persist_postgres.py`:
  - `class PostgresPersistence` with `__init__(self, dsn, *, pool=None, schema="graphindex")`
    calling `ensure_schema` lazily on first use.
  - `persist_graph(ctx, nodes, edges) -> dict` — upsert `UniversalNode`s:
    identity row into `nodes` (concept_id := `node.node_id`, category :=
    `kind.value`, lang via `resolve_regconfig(namespace)`), state row into
    `node_versions` (close current version + insert when `content_hash`
    differs; no-op when identical). Edges into `edges` (close-and-insert on
    change). `fts` populated in the INSERT with
    `to_tsvector($regconfig::regconfig, title || ' ' || summary || ' ' || coalesce(body,''))`.
  - `replace_document_slice(ctx, document_uri, nodes, edges) -> dict` — ONE
    transaction: close validity of versions+edges whose `source_id` matches,
    then upsert the new slice (spec: atomic, a concurrent reader never sees a
    partial state).
  - `is_stale(ctx, source_uri, mtime, sha1) -> bool` — `files` table, parity
    with `persist_sqlite.py:464`.
  - `load_graph(ctx) -> (nodes, edges)` — CURRENT versions/edges only
    (`upper_inf(validity)` partial indexes), rehydrating `UniversalNode` /
    `UniversalEdge` with the same skip-and-warn tolerance as the siblings.
  - Map `provenance`, `assertion` (jsonb), `domain_tags` (jsonb),
    `evidence_ref` passthrough (write when the edge carries one — the
    `{"body_ref": ..., "byte_offset": ...}` shape from spec U3).
- Port the `test_persist.py` behavioral scenarios to Postgres (live-gated).

**NOT in scope**: commit protocol (TASK-2766), `as_of`/`history`/`diff`
(TASK-2767), embeddings API (TASK-2769), hybrid retrieval (TASK-2771), wiki
store (TASK-2768).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/graphindex/persist_postgres.py` | CREATE | `PostgresPersistence` parity surface |
| `packages/ai-parrot/tests/knowledge/graphindex/test_persist_postgres.py` | CREATE | ported parity tests, live-gated |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.knowledge.graphindex.schema import (   # graphindex/schema.py
    AssertionMeta,     # :100
    EdgeKind,          # :64
    NodeKind,          # :36
    Provenance,        # :18
    UniversalEdge,     # :184 — validator :217: confidence set iff provenance INFERRED
    UniversalNode,     # :149 — fields incl. content_ref, embedding_ref, source_uri, domain_tags, parent_id
)
from parrot.knowledge.ontology.schema import TenantContext   # same import as persist.py / persist_sqlite.py
from parrot.knowledge.graphindex.pg_schema import (          # created by TASK-2764
    ensure_schema, create_pg_pool, resolve_regconfig, PG_SCHEMA_VERSION,
)
```

### Existing Signatures to MIRROR (duck-type identical)
```python
# packages/ai-parrot/src/parrot/knowledge/graphindex/persist.py — the API contract
class GraphIndexPersistence:
    async def persist_graph(self, ctx: TenantContext, nodes: list[UniversalNode],
                            edges: list[UniversalEdge]) -> dict[str, Any]
        # returns {"nodes_persisted": int, "edges_persisted": int}
    async def replace_document_slice(self, ctx, document_uri: str, nodes, edges) -> dict[str, Any]
        # returns {"nodes_replaced": int, "edges_replaced": int}
    async def load_graph(self, ctx) -> tuple[list[UniversalNode], list[UniversalEdge]]
        # unreachable store → ([], []) with error log (read parity rule)

# packages/ai-parrot/src/parrot/knowledge/graphindex/persist_sqlite.py — structural template
class SQLitePersistence:            # :138
    async def persist_graph(...)    # :263
    async def replace_document_slice(...)  # :341
    async def is_stale(self, ctx, source_uri, mtime, sha1)  # :464 — files-table semantics
    async def load_graph(...)       # :574
# _doc/_row conversion helpers with skip-and-warn on unknown enums — copy that tolerance
# (_doc_to_node/_doc_to_edge in persist.py; equivalents in persist_sqlite.py)
```

### Does NOT Exist
- ~~`persist_postgres.py`~~ — created by this task.
- ~~a graphindex backend ABC/registry~~ — backends are duck-typed; do NOT
  invent a base class.
- ~~`UPDATE` on `node_versions` content~~ — forbidden by design (D2);
  corrections close the range and insert.
- ~~temporal read methods here~~ — `as_of/history/diff` are TASK-2767.
- ~~`parrot.stores.postgres` / SQLAlchemy~~ — excluded (spec U4/D8).
- ~~`versions[]` embedded array~~ — `node_versions` rows ARE the truth; any
  projection is read-time only.

---

## Implementation Notes

### Pattern to Follow
```python
# close-and-insert (the ONLY correction path, one transaction):
async with conn.transaction():
    await conn.execute(
        "UPDATE graphindex.node_versions SET validity = tstzrange(lower(validity), now())"
        " WHERE concept_id = $1 AND upper_inf(validity) AND content_hash <> $2", cid, h)
    # NOTE: this UPDATE touches ONLY the validity range — never content columns.
    await conn.execute("INSERT INTO graphindex.node_versions (...) VALUES (...)", ...)
```

### Key Constraints
- `ExclusionViolationError` must propagate as an explicit, logged ingest
  error — never swallowed, never auto-widened (spec risk table).
- `content_hash` computed the same way for graph nodes (hash of
  title+summary+content_ref) — stable no-op detection.
- Skip-and-warn on unknown enum values at read time (forward compat, sibling
  parity).
- asyncpg only; Google docstrings; `self.logger`.

### References in Codebase
- `tests/knowledge/graphindex/test_persist.py` — the scenarios to port.
- `persist_sqlite.py:341-463` — slice-replacement transaction shape.

---

## Acceptance Criteria

- [ ] `persist_graph` → `load_graph` roundtrip: model-equal nodes/edges (test).
- [ ] Re-persisting a changed node closes the old version and inserts a new
      one; unchanged content is a no-op (test: version count).
- [ ] `replace_document_slice` is atomic (concurrent-reader test or
      transaction-visibility assertion).
- [ ] `is_stale` semantics match `persist_sqlite.py:464` (test parity).
- [ ] Overlap rejection surfaces as an explicit error (test).
- [ ] `evidence_ref` roundtrip on edges (test — spec AC).
- [ ] FTS row populated with the namespace's regconfig (test with `legal:` →
      spanish stemming hit).
- [ ] Zero SQLAlchemy imports; `ruff check` clean; suite green (live-gated):
      `timeout -s KILL 300 pytest packages/ai-parrot/tests/knowledge/graphindex/test_persist_postgres.py -v`

---

## Test Specification

```python
# packages/ai-parrot/tests/knowledge/graphindex/test_persist_postgres.py
# Port the structure of tests/knowledge/graphindex/test_persist.py against
# PostgresPersistence, plus:
async def test_append_only_correction(pg_persistence, ctx): ...
async def test_no_op_on_identical_content(pg_persistence, ctx): ...
async def test_replace_document_slice_atomic(pg_persistence, ctx): ...
async def test_exclusion_violation_is_explicit(pg_persistence, ctx): ...
async def test_evidence_ref_roundtrip(pg_persistence, ctx): ...
async def test_fts_lang_per_namespace(pg_persistence, ctx): ...
```

---

## Agent Instructions

1. Read spec §2 (Overview + U1 mapping + DDL) and §7 before coding.
2. Verify the Codebase Contract (files may have moved since 2026-09-03).
3. Status updates in `sdd/tasks/index/graphindex-postgres-backend.json`.
4. Move to `sdd/tasks/completed/` + Completion Note when done.

---

## Completion Note

*(Agent fills this in when done)*
