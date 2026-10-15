# TASK-4318: Relocate GraphIndexLoader to parrot/loaders/graphindex.py with explicit backend precedence

**Feature**: FEAT-540 — GraphIndex Core Seams
**Spec**: `sdd/specs/graphindex-core-seams.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-4317, TASK-4311, TASK-4319, TASK-4320, TASK-4303, TASK-4328
**Assigned-to**: unassigned

---

## Context

Spec §3 M6/M7 + absorbed FEAT-670 S4. `GraphIndexLoader` (graphindex/loader.py:96) subclasses `AbstractLoader`, builds framework providers, picks sqlite vs Arango implicitly (:288-313) and reads navconfig inline (:337).

---

## Scope

- Move `GraphIndexLoader` (and its helpers) to `parrot/loaders/graphindex.py`; `graphindex/loader.py` becomes a lazy re-export.
- Add keyword-only `backend: str | None = None`; precedence: explicit backend wins; `sqlite_dir` alone ⇒ sqlite; arango params alone ⇒ arangodb; `persist_enabled=False` ⇒ null; conflicts ⇒ `ValueError`.
- `_make_persistence` → `create_graph_persistence(backend, **options)`; Arango store via `create_ontology_graph_store("arangodb", ...)`.
- Inline navconfig block → `resolve_setting`.
- `to_graph_document` / `from_graph_document` conversions.
- Update `tests/knowledge/graphindex/test_loader.py` patch targets to the new module.

**NOT in scope**: Registry itself (TASK-4319).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/loaders/graphindex.py` | CREATE | relocated loader |
| `packages/ai-parrot/src/parrot/knowledge/graphindex/loader.py` | MODIFY | lazy re-export |
| `packages/ai-parrot/tests/knowledge/graphindex/test_loader.py` | MODIFY | patch targets |
| `packages/ai-parrot/tests/knowledge/graphindex/test_loader_precedence.py` | CREATE | precedence tests |

---

## Codebase Contract (Anti-Hallucination)

> Verified against `dev` @ `cf6316096` on 2026-10-14. Re-verify before writing code.

### Verified Imports
```python
from parrot.loaders.abstract import AbstractLoader  # abstract.py:100
from parrot.stores.models import Document  # models.py:19
from parrot.knowledge.graphindex.models import GraphDocument  # TASK-4317
from parrot.knowledge.graphindex.backends import create_graph_persistence  # TASK-4319
from parrot.knowledge.wiki.project import resolve_setting  # TASK-4311
from parrot.knowledge.ontology.contracts import create_ontology_graph_store  # TASK-4327/4328
```

### Existing Signatures to Use
```python
# graphindex/loader.py: imports :31-41; class _NullPersistence :44 (moves to backends.py in TASK-4319); class GraphIndexLoader(AbstractLoader) :96; __init__ :130
#   _arango_params :180; persist_enabled :189; _sqlite_dir :190; _make_persistence :288-313; navconfig block :337
```

### Does NOT Exist
- ~~`parrot.loaders.graphindex` (created here)~~
- ~~a `backend=` kwarg on GraphIndexLoader today~~

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/loaders/graphindex.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/graphindex/loader.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/graphindex/test_loader.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/graphindex/test_loader_precedence.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/graphindex/loader.py#GraphIndexLoader",
    "sym:packages/ai-parrot/src/parrot/loaders/abstract.py#AbstractLoader"
  ]
}
```

---

## Implementation Notes

Constructor and `load()` behaviour stay identical for existing argument combinations; only conflicting combinations newly raise.

### Key Constraints
- Async-first; Pydantic v2; `self.logger` / `logging.getLogger(__name__)`; Google docstrings; strict type hints; 120 cols.
- Never import `requests`/`httpx`/`langchain`; no `print`. Hard cuts for renamed internals (no external consumers).
- Touch only the files listed above.

---

## Implementation Blueprint

### Steps (in order)
1. Move class — *why*: framework side.
2. Precedence rule — *why*: S4 absorbed.
3. Registry-based persistence — *why*: one composition root.
4. Fix test patch targets.

### `packages/ai-parrot/src/parrot/loaders/graphindex.py` (CREATE)
```python
"""GraphIndexLoader — framework loader over the GraphIndex builder (moved from parrot.knowledge.graphindex.loader)."""
from __future__ import annotations

from parrot.loaders.abstract import AbstractLoader
from parrot.stores.models import Document
from parrot.knowledge.graphindex.models import GraphDocument


def to_graph_document(doc: Document) -> GraphDocument:
    """Framework Document -> GraphDocument (page_content + metadata only)."""
    return GraphDocument(page_content=doc.page_content, metadata=dict(doc.metadata))


def from_graph_document(doc: GraphDocument) -> Document:
    """GraphDocument -> framework Document."""
    return Document(page_content=doc.page_content, metadata=dict(doc.metadata))

# FILL IN: move GraphIndexLoader verbatim; add `backend: str | None = None` kw-only; resolve precedence in __init__;
#          _make_persistence -> await create_graph_persistence(self._backend, **options)
```
**Why**: Conversions preserve content+metadata only (spec §3).

### `packages/ai-parrot/src/parrot/knowledge/graphindex/loader.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'async def _make_persistence(self) -> Any:' parrot/knowledge/graphindex/loader.py)
# AFTER/AT — anchor `async def _make_persistence(self) -> Any:` (verified: loader.py:288)
# REPLACE the module body with a PEP 562 re-export of GraphIndexLoader from parrot.loaders.graphindex
```
**Why**: Old path keeps working.

### `packages/ai-parrot/tests/knowledge/graphindex/test_loader.py` (MODIFY)
```python
# occurrences: n/a — re-grep `parrot.knowledge.graphindex.loader` patch targets in this test
# FILL IN: re-verify with grep -c once the file exists; quote the anchor before editing
# FILL IN: change patch targets 'parrot.knowledge.graphindex.loader.X' -> 'parrot.loaders.graphindex.X'
```
**Why**: Tests follow the move.

### `packages/ai-parrot/tests/knowledge/graphindex/test_loader_precedence.py` (CREATE)
```python
"""GraphIndexLoader backend precedence (FEAT-540 M6/M7)."""
import pytest

# FILL IN: explicit backend wins; sqlite_dir alone -> sqlite; arango params alone -> arangodb;
# persist disabled -> null; sqlite_dir + backend='postgres' -> ValueError; sqlite_dir + arango params -> ValueError
```
**Why**: Spec §4 test_loader_backend_precedence.

### FILL IN checklist
- [ ] verbatim move
- [ ] precedence resolution
- [ ] registry options per backend
- [ ] test patch targets
- [ ] precedence tests

---

## Acceptance Criteria

- [ ] `from parrot.knowledge.graphindex.loader import GraphIndexLoader` and the new path return the same class
- [ ] precedence rule enforced
- [ ] existing loader tests pass

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/graphindex/test_loader_precedence.py -q`
- `pytest packages/ai-parrot/tests/knowledge/graphindex/test_loader.py -q`

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
9. **Close** with `scripts/sdd/close_task.sh TASK-4318 graphindex-core-seams verified`
10. **Fill in the Completion Note**, then commit the staged SDD state

---

## Completion Note

**Completed by**: codex gpt-5.6-terra (attempt 43ba8e2f), consolidated by sdd-worker
**Date**: 2026-10-15
**Notes**: GraphIndexLoader moved to parrot/loaders/graphindex.py (framework loader, 283 lines); graphindex/loader.py is now a lazy backward-compatible re-export via module __getattr__ (ruff F822 on `__all__` is a false positive for that lazy export). The previous direct SQLitePersistence( construction in the loader is gone — `grep SQLitePersistence(` outside persist_sqlite.py/backends.py is now empty, closing the TASK-4321 gap. New test_loader_precedence.py; test_loader.py updated. Verification `partial`: graphindex+ontology+loaders = 1123 passed excluding Postgres-dependent tests; 4 failures (edge-kind enum tests) pre-existing on clean c57431a06; 4 test_pg_schema errors and hybrid_retrieve failures are Postgres-unreachable. No review corrections.

**Deviations from spec**: none.
