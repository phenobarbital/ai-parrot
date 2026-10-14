# TASK-4319: graphindex/backends.py registry, NullPersistence, file_hashes capability, conformance suite

**Feature**: FEAT-540 — GraphIndex Core Seams
**Spec**: `sdd/specs/graphindex-core-seams.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-4302, TASK-4312
**Assigned-to**: unassigned

---

## Context

Spec §2 backends.py + §3 M7 + §8 Q4. One composition root: `GraphBackendSpec`, `register_graph_backend`, `create_graph_persistence`; built-ins sqlite, null, postgres, arangodb. SQLite and Postgres gain `close()`/`file_hashes()`.

---

## Scope

- Create `backends.py` per spec §2 (lazy `module:callable` factories, required options, capabilities, extra, project_options).
- Move `_NullPersistence` (graphindex/loader.py:44) here as `NullPersistence` satisfying `GraphPersistence`.
- `SQLitePersistence`: add no-op `close()`, `file_hashes(ctx)` (sorted files table), use `edge_key`.
- `PostgresPersistence`: add `file_hashes(ctx)` reading `{schema}.files`.
- Create `tests/knowledge/graphindex/persistence_conformance.py` (reusable case functions) + `test_graph_backends.py` running them for sqlite/null/fake, Postgres/Arango behind existing skipif gates.

**NOT in scope**: Dispatch-site rewiring (TASK-4321); ArangoPersistence (TASK-4320 — the registry entry points at its lazy path).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/graphindex/backends.py` | CREATE | registry + NullPersistence |
| `packages/ai-parrot/src/parrot/knowledge/graphindex/persist_sqlite.py` | MODIFY | close + file_hashes |
| `packages/ai-parrot/src/parrot/knowledge/graphindex/persist_postgres.py` | MODIFY | file_hashes |
| `packages/ai-parrot/tests/knowledge/graphindex/persistence_conformance.py` | CREATE | reusable conformance cases |
| `packages/ai-parrot/tests/knowledge/graphindex/test_graph_backends.py` | CREATE | registry + conformance tests |

---

## Codebase Contract (Anti-Hallucination)

> Verified against `dev` @ `cf6316096` on 2026-10-14. Re-verify before writing code.

### Verified Imports
```python
from parrot.knowledge.graphindex.protocols import GraphPersistence, IncrementalPersistence, SourceCoherencePersistence, edge_key  # TASK-4302
from parrot.knowledge.graphindex.persist_sqlite import SQLitePersistence  # persist_sqlite.py:138
from parrot.knowledge.graphindex.pg_schema import resolve_pg_settings  # TASK-4312
from parrot._imports import lazy_import  # _imports.py:110
```

### Existing Signatures to Use
```python
# persist_sqlite.py: class SQLitePersistence :138; __init__(db_dir) :153; _db_path :161; _edge_key :133; files DDL :41
# persist_postgres.py: class PostgresPersistence :207; __init__(dsn=None, *, pool=None, schema='graphindex') :226; close :256; files table pg_schema.py:256
# graphindex/loader.py:44 class _NullPersistence (persist_graph, replace_document_slice)
```

### Does NOT Exist
- ~~`GraphBackendSpec`, `register_graph_backend`, `create_graph_persistence`, `NullPersistence` (created here)~~
- ~~`SQLitePersistence.close` / `file_hashes` (added here)~~

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/graphindex/backends.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/graphindex/persist_sqlite.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/graphindex/persist_postgres.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/graphindex/persistence_conformance.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/graphindex/test_graph_backends.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/graphindex/persist_sqlite.py#SQLitePersistence",
    "sym:packages/ai-parrot/src/parrot/knowledge/graphindex/persist_postgres.py#PostgresPersistence"
  ]
}
```

---

## Implementation Notes

Built-in arangodb factory path: the Arango factory string (module and `create_arango_persistence` are created by TASK-4320; only the dotted string is stored, never imported here) (created by TASK-4320) — the registry only stores the string. Unknown backend → ValueError listing names; missing option → ValueError naming it; missing driver → lazy_import message with the extra.

### Key Constraints
- Async-first; Pydantic v2; `self.logger` / `logging.getLogger(__name__)`; Google docstrings; strict type hints; 120 cols.
- Never import `requests`/`httpx`/`langchain`; no `print`. Hard cuts for renamed internals (no external consumers).
- Touch only the files listed above.

---

## Implementation Blueprint

### Steps (in order)
1. Registry module — *why*: single composition root (S3).
2. NullPersistence — *why*: the loader's implicit fourth backend becomes explicit.
3. SQLite/Postgres capability methods — *why*: Q4 + base contract `close()`.
4. Conformance suite — *why*: S2/S12, reusable by FEAT-670.

### `packages/ai-parrot/src/parrot/knowledge/graphindex/backends.py` (CREATE)
```python
"""GraphIndex persistence backend registry — the only composition root (FEAT-540 M7)."""
from __future__ import annotations

import importlib
from typing import Any

from pydantic import BaseModel

from parrot.knowledge.graphindex.protocols import GraphPersistence


class GraphBackendSpec(BaseModel):
    """Registry entry: lazy factory path, required options, capabilities."""

    name: str
    factory: str
    required_options: tuple[str, ...] = ()
    capabilities: tuple[str, ...] = ()
    extra: str | None = None
    project_options: str | None = None


_REGISTRY: dict[str, GraphBackendSpec] = {}


def register_graph_backend(spec: GraphBackendSpec) -> None:
    """Register or replace a backend spec."""
    _REGISTRY[spec.name] = spec


def graph_backend_names() -> tuple[str, ...]:
    return tuple(_REGISTRY)


def graph_backend_spec(name: str) -> GraphBackendSpec:
    try:
        return _REGISTRY[name]
    except KeyError:
        raise ValueError(f"Unknown graph backend {name!r}; known: {', '.join(_REGISTRY)}") from None


async def create_graph_persistence(backend: str, **options: Any) -> GraphPersistence:
    """Resolve and build a backend."""
    spec = graph_backend_spec(backend)
    missing = [o for o in spec.required_options if options.get(o) is None]
    if missing:
        raise ValueError(f"graph backend {backend!r} requires option(s): {', '.join(missing)}")
    # FILL IN: import spec.factory (module:callable) translating ImportError via lazy_import(extra=spec.extra); await if coroutine
    raise NotImplementedError


class NullPersistence:
    """In-memory no-op backend (was graphindex/loader.py:_NullPersistence)."""

    # FILL IN: every GraphPersistence method; load_graph -> ([], []); apply_update returns a CommitReceipt with monotonic seq


# FILL IN: register built-ins: sqlite (required db_dir, capabilities incremental+source_coherence), null, postgres (temporal, embeddings,
#          hybrid, incremental, source_coherence; extra 'graphindex-postgres'), arangodb (factory string supplied by TASK-4320's module, stored lazily)
```
**Why**: Spec §2 is authoritative for every name and option.

### `packages/ai-parrot/src/parrot/knowledge/graphindex/persist_sqlite.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'class SQLitePersistence:' parrot/knowledge/graphindex/persist_sqlite.py)
# AFTER/AT — anchor `class SQLitePersistence:` (verified: persist_sqlite.py:138)
# ADD methods to the class:
    async def close(self) -> None:
        """No-op: connections are per call."""

    async def file_hashes(self, ctx: TenantContext) -> list[tuple[str, str]]:
        """Every (source_uri, sha1) from the files table, sorted by source_uri."""
        # FILL IN: SELECT source_uri, sha1 FROM files ORDER BY source_uri on self._db_path(ctx)
        raise NotImplementedError
# FILL IN: replace the module-local _edge_key body with `return edge_key(...)` from protocols
```
**Why**: Q4 capability; pin.py stops reading `_db_path` (TASK-4322).

### `packages/ai-parrot/src/parrot/knowledge/graphindex/persist_postgres.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'class PostgresPersistence:' parrot/knowledge/graphindex/persist_postgres.py)
# AFTER/AT — anchor `class PostgresPersistence:` (verified: persist_postgres.py:207)
# ADD:
    async def file_hashes(self, ctx: TenantContext) -> list[tuple[str, str]]:
        """Every (source_uri, sha1) from {schema}.files, sorted by source_uri."""
        # FILL IN: pool = await self._ensure_pool(); fetch ORDER BY source_uri
        raise NotImplementedError
```
**Why**: Same capability; v1 schema is not tenant-partitioned (document it in the docstring).

### `packages/ai-parrot/tests/knowledge/graphindex/persistence_conformance.py` (CREATE)
```python
"""Reusable GraphPersistence conformance cases (FEAT-540 M7). Import and call from per-backend tests."""
from __future__ import annotations

from typing import Any


async def case_apply_and_revert(persistence: Any, ctx: Any) -> None:
    """apply_update then revert restores pre-images; revert is a new commit."""
    # FILL IN


# FILL IN: case_seq_monotonic, case_edge_key_identity, case_incident_edge_preimages, case_revert_conflict,
#          case_slice_atomic_idempotent, case_missing_store_reads_empty, case_errors_propagate
ALL_CASES = []  # FILL IN: list every case function
```
**Why**: Exported so FEAT-670 can parametrise with its backends.

### `packages/ai-parrot/tests/knowledge/graphindex/test_graph_backends.py` (CREATE)
```python
"""Registry + conformance (FEAT-540 M7)."""
import pytest

from parrot.knowledge.graphindex.backends import create_graph_persistence, graph_backend_names


def test_builtin_names() -> None:
    assert graph_backend_names() == ("sqlite", "null", "postgres", "arangodb")


@pytest.mark.asyncio
async def test_unknown_backend() -> None:
    with pytest.raises(ValueError, match="known"):
        await create_graph_persistence("nope")

# FILL IN: missing option named; parametrise ALL_CASES over sqlite (tmp_path) and null; file_hashes sorted
```
**Why**: Spec §4 test_registry_dispatch + conformance.

### FILL IN checklist
- [ ] factory import + lazy_import mapping
- [ ] NullPersistence methods
- [ ] built-in registrations
- [ ] file_hashes bodies
- [ ] conformance cases

---

## Acceptance Criteria

- [ ] `graph_backend_names()` == sqlite, null, postgres, arangodb
- [ ] conformance passes for sqlite and null
- [ ] SQLite/Postgres implement `SourceCoherencePersistence`

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/graphindex/test_graph_backends.py -q`
- `pytest packages/ai-parrot/tests/knowledge/graphindex/test_persist_sqlite.py -q`

---

## Test Specification

```python
# see block
```

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `dev`
   (`python -m scripts.sdd.ensure_worktree --slug graphindex-core-seams --feature-id FEAT-540 --spec sdd/specs/graphindex-core-seams.spec.md --index sdd/tasks/index/graphindex-core-seams.json`)
2. **Read the spec** (`sdd/specs/graphindex-core-seams.spec.md`) — at least §2 and the module this task implements
3. **Check dependencies** — every `Depends-on` task must be `"done"` in `sdd/tasks/index/graphindex-core-seams.json`
4. **Verify the Codebase Contract** — re-run `grep -c` for every anchor in the blueprint; a changed count means the
   anchor moved: re-locate it and fix the blueprint line before editing. A count of 0 means drift — stop and report.
5. **Update status** → `"in-progress"` (`started_at`) and commit only the index file
6. **Implement** from the Implementation Blueprint, completing every `# FILL IN:`; never change a fixed signature or path
7. **Validate** — `ruff check --fix <changed files>` and the Validation Commands with
   `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-tools/src` (worktrees: the shared venv points at the main checkout)
8. **Commit code** — stage only the files listed above (never `git add .` / `-A`)
9. **Close** with `scripts/sdd/close_task.sh TASK-4319 graphindex-core-seams verified`
10. **Fill in the Completion Note**, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none | describe if any
