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

Read `factory.py` and `toolkit.py` in full before modifying, per
instructions.

**Factory**: extended `build_graph_memory_toolkit` additively — `db_dir`
became `Optional[Path | str] = None` (raises `ValueError` when
`backend="sqlite"` and omitted, preserving existing positional/keyword
callers unchanged) and added `backend: str = "sqlite"`, `dsn`, `schema`
kwargs. `backend="postgres"` lazily imports `PostgresPersistence` (keeps
the sqlite-only path free of an asyncpg/pgvector dependency, same lazy
-import seam as the existing `GraphIndexToolkit` import). Zero breaking
changes — verified by re-running every existing caller
(`test_context_builder.py`, `test_grounding.py`, `test_llm_extractor.py`,
`test_memory.py`, `test_toolkit_persistence.py`): all green.

**Toolkit naming collision found and resolved**: the task's suggested
tool name `graph_history(concept_id)` ALREADY EXISTS on
`GraphIndexToolkit` — it lists durable WRITE commits (`publisher.
list_commits`), not per-concept bitemporal version history. Defining a
second method with the same name would have silently shadowed the
existing tool (illegal duplicate in Python, and a real behavioral
regression for `list_commits`-based callers). Renamed to
`graph_concept_history` — documented in the module docstring, the tool's
own docstring, and here. `graph_as_of`/`graph_diff`/`graph_hybrid_retrieve`
had no collisions and kept the task's suggested names.

**Feature-detection mechanism decision**: `AbstractToolkit._generate_tools()`
inspects `dir(self)` + `self.exclude_tools` at INSTANCE construction time
(read the base class first) — so "registered ONLY when the bound
persistence exposes the temporal surface" is implemented by computing
`self.exclude_tools = (*self.exclude_tools, *_TEMPORAL_TOOL_NAMES)` in
`__init__` when `_temporal_persistence()` (hasattr-based, spec D5) returns
`None`. This EXCLUDES the tools from generation entirely (not merely
returning an error) — the stronger, correct reading of the AC. Each tool
also independently guards against direct method calls that bypass
`exclude_tools` (defensive, matching the existing `graph_history`/
`revert_write` pattern of returning `{"error": ...}`).

`graph_hybrid_retrieve`'s tool schema exposes only `query`/`seeds` —
weights/limit/reranker are fixed module-level constants
(`_HYBRID_RETRIEVE_WEIGHTS`/`_HYBRID_RETRIEVE_LIMIT`), verified via
`inspect.signature`. The semantic/KNN leg is NOT wired from this tool
(embedding generation is a separate concern, out of scope) — documented
in the docstring; the tool wraps the graph+FTS legs only.

Docs: added Temporal API + Hybrid Retrieval sections, a 3-row backend
matrix (bitemporal/hybrid columns), the FEAT-520 config keys table, the
`backend="postgres"` factory example, and the 4-tool toolkit table
section to `docs/graphindex.md`. CHANGELOG `[Unreleased]` entry added.

All 5 new toolkit tests pass (absent-on-sqlite via `list_tool_names()`,
schema-has-no-weights via signature inspection, present-on-postgres,
`graph_diff`/`graph_concept_history`/`graph_as_of` smoke over a live
store, direct-call defensive error). Ran the full regression sweep: 132
passed in `packages/ai-parrot` (all touched graphindex-postgres suites +
every existing `build_graph_memory_toolkit` caller), 79 passed in
`packages/ai-parrot-tools` (33 errors + 1 failure are pre-existing —
confirmed byte-identical on the unmodified main repo: an
`asyncio.get_event_loop()` fixture bug in `test_toolkit_write_and_
signals.py` when run outside the full suite, and a `rustworkx`
extras-check test unrelated to graphindex-postgres). `ruff check` clean
on every touched file; zero SQLAlchemy imports (grep-verified).

FEAT-520 — all 10 tasks complete.
