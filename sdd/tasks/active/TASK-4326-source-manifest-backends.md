# TASK-4326: SourceManifestBackend contract; SourceCollectionManager delegates (sqlite/json/arangodb)

**Feature**: FEAT-540 — GraphIndex Core Seams
**Spec**: `sdd/specs/graphindex-core-seams.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-4309
**Assigned-to**: unassigned

---

## Context

Spec §2 sources_backend.py + §3 M7 + codex S10. `SourceCollectionManager` has 25 `backend ==` branches and an AQL path (sources.py:1289-1425); `LLMWikiToolkit` picks the source backend by name.

---

## Scope

- Create `wiki/sources_backend.py` (Protocol, `register_source_backend`, `create_source_backend`, built-ins sqlite/json/arangodb).
- Create `wiki/arango_sources.py` moving the eleven Arango operations verbatim.
- SQLite/JSON implementations wrap the existing in-class code; the manager holds one backend and keeps its sync `_run_async` bridge.
- `SourceCollectionManager.backend` → `str` validated by the source registry; `LLMWikiToolkit` uses `create_source_backend`.
- Parity tests.

**NOT in scope**: Making the manager async.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/sources_backend.py` | CREATE | contract + registry |
| `packages/ai-parrot/src/parrot/knowledge/wiki/arango_sources.py` | CREATE | Arango backend |
| `packages/ai-parrot/src/parrot/knowledge/wiki/sources.py` | MODIFY | delegate |
| `packages/ai-parrot-tools/src/parrot_tools/wiki/toolkit.py` | MODIFY | selection |
| `packages/ai-parrot/tests/knowledge/wiki/test_source_backends.py` | CREATE | parity |

---

## Codebase Contract (Anti-Hallucination)

> Verified against `dev` @ `cf6316096` on 2026-10-14. Re-verify before writing code.

### Verified Imports
```python
from parrot.knowledge.wiki.models import SourceManifestEntry  # used by sources.py
```

### Existing Signatures to Use
```python
# sources.py: __init__ :144 (backend Literal :148, validation :184); _run_async :1224; _resolve_arango_db :1289; _arango_query :1303; _arango_execute :1319;
#   _async_upsert :1366 · _async_upsert_many :1377 · _async_list_sources :1387 · _async_get_source :1395 · _async_remove_source :1403 · _async_find_id_by_uri :1411 · _async_find_by_external_id :1419
#   sync callers of _arango_query :323 :363 :868 :907
```

### Does NOT Exist
- ~~`SourceManifestBackend` / `create_source_backend` (created here)~~

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/wiki/sources_backend.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/wiki/arango_sources.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/wiki/sources.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-tools/src/parrot_tools/wiki/toolkit.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/wiki/test_source_backends.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/sources.py#SourceCollectionManager"
  ]
}
```

---

## Implementation Notes

Behaviour must be identical; parity tests compare the three backends on the eleven operations (Arango via a fake db double).

### Key Constraints
- Async-first; Pydantic v2; `self.logger` / `logging.getLogger(__name__)`; Google docstrings; strict type hints; 120 cols.
- Never import `requests`/`httpx`/`langchain`; no `print`. Hard cuts for renamed internals (no external consumers).
- Touch only the files listed above.

---

## Implementation Blueprint

### Steps (in order)
1. Contract + registry.
2. Arango backend (verbatim AQL).
3. Manager delegation.
4. Toolkit selection.
5. Parity tests incl. AST no `backend ==` left.

### `packages/ai-parrot/src/parrot/knowledge/wiki/sources_backend.py` (CREATE)
```python
"""Source manifest backend contract + registry (FEAT-540 M7)."""
from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

# FILL IN: SourceManifestBackend Protocol (11 async methods, spec §2), register_source_backend, create_source_backend, built-ins sqlite/json/arangodb (lazy paths)
```
**Why**: Spec §2.

### `packages/ai-parrot/src/parrot/knowledge/wiki/arango_sources.py` (CREATE)
```python
"""ArangoDB SourceManifestBackend (AQL moved verbatim from sources.py)."""
from __future__ import annotations

# FILL IN: ArangoSourceBackend with the eleven operations
```
**Why**: AQL verbatim.

### `packages/ai-parrot/src/parrot/knowledge/wiki/sources.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'backend: Literal["sqlite", "json", "arangodb"] = "sqlite",' parrot/knowledge/wiki/sources.py)
# AFTER/AT — anchor `backend: Literal["sqlite", "json", "arangodb"] = "sqlite",` (verified: sources.py:148)
# REPLACE with backend: str = "sqlite"; FILL IN: self._store = create_source_backend(backend, ...) and delegate every public method
```
**Why**: S10.

### `packages/ai-parrot/src/parrot/knowledge/wiki/sources.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'async def _arango_query(self, aql: str, bind_vars: dict[str, Any]) -> list[Any]:' parrot/knowledge/wiki/sources.py)
# AFTER/AT — anchor `async def _arango_query(self, aql: str, bind_vars: dict[str, Any]) -> list[Any]:` (verified: sources.py:1303)
# FILL IN: delete _arango_query/_arango_execute/_async_* after moving them
```
**Why**: Moved.

### `packages/ai-parrot-tools/src/parrot_tools/wiki/toolkit.py` (MODIFY)
```python
# occurrences: n/a — parrot_tools/wiki/toolkit.py is created by TASK-4309 (originally wiki/toolkit.py:139-161)
# FILL IN: re-verify with grep -c once the file exists; quote the anchor before editing
# FILL IN: SourceCollectionManager(sources_dir, backend=<registry name>, ...) without name branches
```
**Why**: Selection through the registry.

### `packages/ai-parrot/tests/knowledge/wiki/test_source_backends.py` (CREATE)
```python
"""Source backend parity (FEAT-540 M7)."""
import pytest

# FILL IN: parametrise sqlite/json/arango-fake over the eleven operations; AST: no `backend ==` in sources.py
```
**Why**: Spec §4 test_source_backend_parity.

### FILL IN checklist
- [ ] contract + registry
- [ ] Arango backend
- [ ] manager delegation
- [ ] toolkit selection
- [ ] parity tests

---

## Acceptance Criteria

- [ ] no `backend ==` branch in sources.py
- [ ] parity across sqlite/json/arango-fake
- [ ] existing sources/ingest tests pass

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/wiki/test_source_backends.py -q`
- `pytest packages/ai-parrot/tests/knowledge/wiki/test_ingest_attrs.py -q`

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
9. **Close** with `scripts/sdd/close_task.sh TASK-4326 graphindex-core-seams verified`
10. **Fill in the Completion Note**, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none | describe if any
