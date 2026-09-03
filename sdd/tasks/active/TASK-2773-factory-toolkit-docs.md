# TASK-2773: Factory wiring, temporal toolkit tools, docs

**Feature**: FEAT-520 — GraphIndex Postgres Backend
**Spec**: `sdd/specs/graphindex-postgres-backend.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2767, TASK-2768, TASK-2771
**Assigned-to**: unassigned

---

## Context

Module 9 of FEAT-520 — the last mile: make the backend constructible from
the graphindex factory, expose the temporal/hybrid capabilities as
mono-purpose agent tools (spec D5: separate tools, NEVER modal parameters on
a generic tool), and document the backend matrix.

---

## Scope

- **Factory**: extend `graphindex/factory.py` with a Postgres construction
  path (mirror how `build_graph_memory_toolkit` builds
  `SQLitePersistence(Path(db_dir))` + `GraphPublisher` at :239-240; selection
  via an explicit parameter or navconfig key — follow the factory's existing
  configuration style, read the whole file first).
- **Toolkit** (`packages/ai-parrot-tools/src/parrot_tools/graphindex/toolkit.py`):
  add mono-purpose tools, registered ONLY when the bound persistence exposes
  the temporal surface (feature-detect via `hasattr(persistence, "as_of")` —
  duck-typing rule from spec §2):
  - `graph_as_of(timestamp)` — snapshot summary.
  - `graph_history(concept_id)` — version list.
  - `graph_diff(concept_id, t1, t2)` — structured diff.
  - `graph_hybrid_retrieve(...)` — thin wrapper over `hybrid_retrieve` with
    fixed configuration (weights/limits from config, not from the LLM — "el
    agente elige tools, nunca pesos ni modos", brainstorm D6).
  Every tool: full docstring (it becomes the LLM description), Pydantic args.
- **Docs**: `docs/graphindex.md` — backend matrix row (SQLite / Arango /
  Postgres capabilities incl. temporal + hybrid columns), temporal API
  section, hybrid retrieval section, config keys table (spec §7). CHANGELOG
  entry.
- Tests: toolkit tool registration (temporal tools absent when bound to
  `SQLitePersistence`, present with `PostgresPersistence`), tool execution
  smoke over a live store.

**NOT in scope**: legal-specific tools (`legal_search`, `article_in_force` —
legal-wiki feature), MCP registration changes, `wikitoolkit` CLI.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/graphindex/factory.py` | MODIFY | Postgres construction path |
| `packages/ai-parrot-tools/src/parrot_tools/graphindex/toolkit.py` | MODIFY | 4 mono-purpose tools, feature-detected |
| `packages/ai-parrot-tools/tests/graphindex/test_toolkit_temporal.py` | CREATE | registration + smoke tests |
| `docs/graphindex.md` | MODIFY | backend matrix + new sections |
| `CHANGELOG.md` (repo convention — locate first) | MODIFY | entry |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.knowledge.graphindex.persist_postgres import PostgresPersistence  # TASK-2765+
from parrot.knowledge.graphindex.persist_sqlite import SQLitePersistence      # persist_sqlite.py:138
from parrot.knowledge.graphindex.publish import GraphPublisher                # consumed by factory :240
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/graphindex/factory.py
async def build_graph_memory_toolkit(...)   # :203 — READ THE FULL SIGNATURE;
    # instantiates SQLitePersistence(Path(db_dir)) at :239 and
    # GraphPublisher(persistence, ctx) at :240 — extend this construction style.
# make_stub_tenant_context(tenant_id) -> TenantContext   # factory.py:45

# packages/ai-parrot-tools/src/parrot_tools/graphindex/toolkit.py — existing toolkit:
#   find_references :293, traverse :373, ground_claim :1168 — follow the same
#   AbstractToolkit tool-method conventions (docstrings become LLM descriptions).
# parrot/tools — AbstractToolkit base (see CLAUDE.md Tool-Centric Architecture:
#   lifecycle hook names _open/_close/_ensure_open are RESERVED — do not define
#   them for other purposes).

# TASK-2767 temporal signatures (normative in spec §2):
#   as_of(ctx, t) / history(ctx, concept_id) / diff(ctx, concept_id, t1, t2)
# TASK-2771: hybrid_retrieve(ctx, *, query_embedding, fts_terms, seeds, as_of,
#   weights, limit, reranker, rerank_top_k) -> list[HybridCandidate]
```

### Does NOT Exist
- ~~temporal methods on `SQLitePersistence`/`GraphIndexPersistence`~~ —
  that absence IS the feature-detection test case.
- ~~a generic `graph_query(mode=...)` tool~~ — forbidden by D5 (mono-purpose
  tools only).
- ~~toolkit exposing RRF weights to the LLM~~ — weights come from config.
- ~~`parrot.tools.graphindex` as the canonical import~~ — concrete toolkits
  live in `parrot_tools.graphindex` (the meta_path shim redirects legacy
  paths; use the explicit `parrot_tools` import in new code).

---

## Implementation Notes

### Key Constraints
- Tool docstrings: purpose, parameters, return — they are the LLM contract.
- Feature detection with `hasattr`, not `isinstance` (backends are
  duck-typed).
- Docs must state clearly: temporal + hybrid are Postgres-only in v1; other
  backends unchanged.

### References in Codebase
- `packages/ai-parrot-tools/tests/graphindex/test_toolkit.py` — existing
  toolkit test conventions.

---

## Acceptance Criteria

- [ ] Factory builds a Postgres-backed toolkit end-to-end (live-gated test).
- [ ] Temporal tools registered iff the persistence has the surface (test
      both directions).
- [ ] `graph_hybrid_retrieve` exposes NO weight/mode parameters to the LLM
      (assert tool schema in test).
- [ ] Docs backend matrix updated; CHANGELOG entry present.
- [ ] `ruff check` clean; existing toolkit tests still green.

---

## Test Specification

```python
# packages/ai-parrot-tools/tests/graphindex/test_toolkit_temporal.py
async def test_temporal_tools_absent_on_sqlite(...): ...
async def test_temporal_tools_present_on_postgres(...): ...
async def test_hybrid_tool_schema_has_no_weights(...): ...
async def test_graph_diff_tool_smoke(...): ...
```

---

## Agent Instructions

1. Read `factory.py` and the toolkit file fully before modifying.
2. Verify contract references; update index status; completed + note when done.

---

## Completion Note

*(Agent fills this in when done)*
