# TASK-4320: persist.py → persist_arango.py: ArangoPersistence over GraphDocumentStore

**Feature**: FEAT-540 — GraphIndex Core Seams
**Spec**: `sdd/specs/graphindex-core-seams.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4304, TASK-4327
**Assigned-to**: unassigned

---

## Context

Spec §3 M7 + S6. `GraphIndexPersistence(graph_store: OntologyGraphStore)` (persist.py:213/225) becomes `ArangoPersistence(store: GraphDocumentStore)` in `persist_arango.py`; hard cut — callers updated.

---

## Scope

- `git mv graphindex/persist.py graphindex/persist_arango.py`; rename class; constructor `store: GraphDocumentStore`; add no-op `close()`; use `edge_key`.
- Add `create_arango_persistence(*, graph_store=None, arango_params=None, tenant_ctx=None)` factory (the registry target).
- Update callers: builder.py:43, graphindex/loader.py:40, parrot_tools/graphindex/flowtask.py:27,220, and tests test_persist.py, test_persist_commit_protocol.py, test_meta_ontology.py, test_communities.py.

**NOT in scope**: Dispatch sites (TASK-4321).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/graphindex/persist_arango.py` | CREATE | renamed module (git mv) |
| `packages/ai-parrot/src/parrot/knowledge/graphindex/persist.py` | MODIFY | removed by git mv |
| `packages/ai-parrot/src/parrot/knowledge/graphindex/builder.py` | MODIFY | import |
| `packages/ai-parrot/src/parrot/knowledge/graphindex/loader.py` | MODIFY | import |
| `packages/ai-parrot-tools/src/parrot_tools/graphindex/flowtask.py` | MODIFY | ArangoPersistence |
| `packages/ai-parrot/tests/knowledge/graphindex/test_persist.py` | MODIFY | rename |
| `packages/ai-parrot/tests/knowledge/graphindex/test_persist_commit_protocol.py` | MODIFY | rename |
| `packages/ai-parrot/tests/knowledge/graphindex/test_meta_ontology.py` | MODIFY | rename |
| `packages/ai-parrot/tests/knowledge/graphindex/test_communities.py` | MODIFY | rename |

---

## Codebase Contract (Anti-Hallucination)

> Verified against `dev` @ `cf6316096` on 2026-10-14. Re-verify before writing code.

### Verified Imports
```python
from parrot.knowledge.ontology.contracts import GraphDocumentStore  # TASK-4327 (TYPE_CHECKING)
from parrot.knowledge.graphindex.protocols import edge_key  # TASK-4302
```

### Existing Signatures to Use
```python
# persist.py: :36 OntologyGraphStore import; _edge_key :65; class GraphIndexPersistence :213; __init__(self, graph_store) :225
# builder.py:43, graphindex/loader.py:40, flowtask.py:27 import it; flowtask.py:220 constructs it with a MagicMock store
```

### Does NOT Exist
- ~~`persist_arango.py` / `ArangoPersistence` / `create_arango_persistence` (created here)~~
- ~~a compatibility alias `GraphIndexPersistence` (hard cut)~~

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/graphindex/persist_arango.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/graphindex/persist.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/graphindex/builder.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/graphindex/loader.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-tools/src/parrot_tools/graphindex/flowtask.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/graphindex/test_persist.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/graphindex/test_persist_commit_protocol.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/graphindex/test_meta_ontology.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/graphindex/test_communities.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/graphindex/persist.py#GraphIndexPersistence",
    "sym:packages/ai-parrot-tools/src/parrot_tools/graphindex/flowtask.py#GraphIndexFlowtask"
  ]
}
```

---

## Implementation Notes

Keep the `graph_store` attribute name? No — rename to `store` and update internal uses; the conformance suite tests behaviour, not attribute names. Verify `GraphIndexFlowtask` is the class name in flowtask.py before relying on the symbol id.

### Key Constraints
- Async-first; Pydantic v2; `self.logger` / `logging.getLogger(__name__)`; Google docstrings; strict type hints; 120 cols.
- Never import `requests`/`httpx`/`langchain`; no `print`. Hard cuts for renamed internals (no external consumers).
- Touch only the files listed above.

---

## Implementation Blueprint

### Steps (in order)
1. git mv + rename — *why*: hard cut, neutral naming.
2. Factory — *why*: registry target.
3. Update every caller and test.

### `packages/ai-parrot/src/parrot/knowledge/graphindex/persist.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'def __init__(self, graph_store: OntologyGraphStore) -> None:' parrot/knowledge/graphindex/persist.py)
# AFTER/AT — anchor `def __init__(self, graph_store: OntologyGraphStore) -> None:` (verified: persist.py:225)
# git mv this file to persist_arango.py, then in the moved file:
#   class ArangoPersistence:
#       def __init__(self, store: "GraphDocumentStore") -> None: ...
#       async def close(self) -> None: """No-op — the store owns its client."""
#   async def create_arango_persistence(*, graph_store=None, arango_params=None, tenant_ctx=None) -> ArangoPersistence: ...
```
**Why**: S6: the Arango persistence needs the document/edge surface only.

### `packages/ai-parrot/src/parrot/knowledge/graphindex/persist_arango.py` (CREATE)
```text
# created by `git mv` above — no new content beyond the rename/factory
```
**Why**: Rename target.

### `packages/ai-parrot/src/parrot/knowledge/graphindex/builder.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'from parrot.knowledge.graphindex.persist import GraphIndexPersistence' parrot/knowledge/graphindex/builder.py)
# AFTER/AT — anchor `from parrot.knowledge.graphindex.persist import GraphIndexPersistence` (verified: builder.py:43)
# REPLACE with (annotation only):
if TYPE_CHECKING:
    from parrot.knowledge.graphindex.protocols import GraphPersistence
# FILL IN: `persistence: "GraphPersistence"` in __init__
```
**Why**: Builder depends on the contract.

### `packages/ai-parrot/src/parrot/knowledge/graphindex/loader.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'from .persist import GraphIndexPersistence' parrot/knowledge/graphindex/loader.py)
# AFTER/AT — anchor `from .persist import GraphIndexPersistence` (verified: loader.py:40)
# REPLACE with:
from .persist_arango import ArangoPersistence
# FILL IN: constructor call :313 -> ArangoPersistence(self.graph_store)
```
**Why**: Minimal edit — TASK-4318 rewrites the module.

### `packages/ai-parrot-tools/src/parrot_tools/graphindex/flowtask.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'return GraphIndexPersistence(graph_store=store)' parrot_tools/graphindex/flowtask.py)
# AFTER/AT — anchor `return GraphIndexPersistence(graph_store=store)` (verified: flowtask.py:220)
# REPLACE with:
        return ArangoPersistence(store=store)
# FILL IN: import at :27 and return annotation :201
```
**Why**: Hard cut.

### `packages/ai-parrot/tests/knowledge/graphindex/test_persist.py` (MODIFY)
```python
# occurrences: n/a — re-grep GraphIndexPersistence in this file
# FILL IN: re-verify with grep -c once the file exists; quote the anchor before editing
# FILL IN: GraphIndexPersistence -> ArangoPersistence, module path persist -> persist_arango, graph_store= -> store=
```
**Why**: Follow rename.

### `packages/ai-parrot/tests/knowledge/graphindex/test_persist_commit_protocol.py` (MODIFY)
```python
# occurrences: n/a — re-grep GraphIndexPersistence in this file
# FILL IN: re-verify with grep -c once the file exists; quote the anchor before editing
# FILL IN: same rename
```
**Why**: Follow rename.

### `packages/ai-parrot/tests/knowledge/graphindex/test_meta_ontology.py` (MODIFY)
```python
# occurrences: n/a — re-grep GraphIndexPersistence in this file
# FILL IN: re-verify with grep -c once the file exists; quote the anchor before editing
# FILL IN: same rename
```
**Why**: Follow rename.

### `packages/ai-parrot/tests/knowledge/graphindex/test_communities.py` (MODIFY)
```python
# occurrences: n/a — re-grep GraphIndexPersistence in this file
# FILL IN: re-verify with grep -c once the file exists; quote the anchor before editing
# FILL IN: same rename
```
**Why**: Follow rename.

### FILL IN checklist
- [ ] class/factory rename
- [ ] every caller + test
- [ ] `grep -rn GraphIndexPersistence packages/` returns only docs

---

## Acceptance Criteria

- [ ] no `GraphIndexPersistence` code reference remains
- [ ] Arango persistence tests pass
- [ ] `create_arango_persistence` importable

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/graphindex/test_persist.py -q`
- `pytest packages/ai-parrot/tests/knowledge/graphindex/test_persist_commit_protocol.py -q`
- `pytest packages/ai-parrot/tests/knowledge/graphindex/test_meta_ontology.py -q`
- `pytest packages/ai-parrot/tests/knowledge/graphindex/test_communities.py -q`
- `pytest packages/ai-parrot-tools/tests/graphindex/test_flowtask.py -q`

---

## Test Specification

```python
# existing tests updated
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
9. **Close** with `scripts/sdd/close_task.sh TASK-4320 graphindex-core-seams verified`
10. **Fill in the Completion Note**, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none | describe if any
