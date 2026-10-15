# TASK-4321: Route every persistence construction through the registry; persistence_for_project

**Feature**: FEAT-540 — GraphIndex Core Seams
**Spec**: `sdd/specs/graphindex-core-seams.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4319, TASK-4303, TASK-4313
**Assigned-to**: unassigned

---

## Context

Spec §2/§3 M7 + absorbed FEAT-670 S1/S4. Seven sites construct persistence directly: factory.py:249-261, wiki/runtime.py:91, wiki/cli.py:4011/4108/4561/4623, flows/dev_loop/graph_memory.py:142.

---

## Scope

- `build_graph_memory_toolkit`: dispatch via `create_graph_persistence`; precedence rule (explicit backend wins; `db_dir` alone ⇒ sqlite; conflicts ⇒ ValueError).
- `GraphPublisher.__init__(persistence: GraphPersistence, ...)`.
- Add `persistence_for_project(config, root, *, tenant_id=None)` to `wiki/runtime.py`; use it at runtime.py:91 and the four cli.py sites.
- graph_memory.py → `create_graph_persistence("sqlite", db_dir=...)`.
- Tests.

**NOT in scope**: Capability consumers (TASK-4322).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/graphindex/factory.py` | MODIFY | registry dispatch |
| `packages/ai-parrot/src/parrot/knowledge/graphindex/publish.py` | MODIFY | typed persistence |
| `packages/ai-parrot/src/parrot/knowledge/wiki/runtime.py` | MODIFY | persistence_for_project |
| `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py` | MODIFY | 4 sites |
| `packages/ai-parrot/src/parrot/flows/dev_loop/graph_memory.py` | MODIFY | registry |
| `packages/ai-parrot/tests/knowledge/graphindex/test_persistence_dispatch.py` | CREATE | dispatch tests |

---

## Codebase Contract (Anti-Hallucination)

> Verified against `dev` @ `cf6316096` on 2026-10-14. Re-verify before writing code.

### Verified Imports
```python
from parrot.knowledge.graphindex.backends import create_graph_persistence, graph_backend_spec  # TASK-4319
from parrot.knowledge.graphindex.protocols import GraphPersistence  # TASK-4302
from parrot.knowledge.wiki.project import WikiProjectConfig  # project.py:561
```

### Existing Signatures to Use
```python
# factory.py: build_graph_memory_toolkit(..., backend='sqlite', dsn=None, schema='graphindex') :197; dispatch :249-261
# publish.py:47 def __init__(self, persistence: Any, ctx: TenantContext)
# wiki/runtime.py:82 import, :91 construction
# wiki/cli.py: SQLitePersistence(config.graph_path(root)) at :4017 and :4629 (8-space), :4567 (16-space), GraphPublisher(...) :4114 (re-verified at task time)
# flows/dev_loop/graph_memory.py:142 SQLitePersistence(Path(db_dir)); WikiProjectConfig.graph_path :721
```

### Does NOT Exist
- ~~`persistence_for_project` (created here)~~

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/graphindex/factory.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/graphindex/publish.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/wiki/runtime.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/wiki/cli.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/flows/dev_loop/graph_memory.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/graphindex/test_persistence_dispatch.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/graphindex/factory.py#build_graph_memory_toolkit",
    "sym:packages/ai-parrot/src/parrot/knowledge/graphindex/publish.py#GraphPublisher"
  ]
}
```

---

## Implementation Notes

`create_graph_persistence` is async; the four CLI sites run inside async helpers already (`_run(...)`) — verify each; wrap if not.

### Key Constraints
- Async-first; Pydantic v2; `self.logger` / `logging.getLogger(__name__)`; Google docstrings; strict type hints; 120 cols.
- Never import `requests`/`httpx`/`langchain`; no `print`. Hard cuts for renamed internals (no external consumers).
- Touch only the files listed above.

---

## Implementation Blueprint

### Steps (in order)
1. Factory dispatch + precedence.
2. Typed publisher.
3. persistence_for_project + call sites.
4. graph_memory.
5. Tests.

### `packages/ai-parrot/src/parrot/knowledge/graphindex/factory.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'if backend == "sqlite":' parrot/knowledge/graphindex/factory.py)
# AFTER/AT — anchor `if backend == "sqlite":` (verified: factory.py:249)
# REPLACE the if/elif/else (:249-261) with:
#   persistence = await create_graph_persistence(backend, **_backend_options(backend, db_dir=db_dir, dsn=dsn, schema=schema))
# FILL IN: _backend_options + precedence (db_dir given and backend explicitly non-sqlite -> ValueError)
```
**Why**: One composition root.

### `packages/ai-parrot/src/parrot/knowledge/graphindex/publish.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'def __init__(self, persistence: Any, ctx: TenantContext) -> None:' parrot/knowledge/graphindex/publish.py)
# AFTER/AT — anchor `def __init__(self, persistence: Any, ctx: TenantContext) -> None:` (verified: publish.py:47)
# REPLACE with:
    def __init__(self, persistence: "GraphPersistence", ctx: TenantContext) -> None:
# FILL IN: TYPE_CHECKING import of GraphPersistence
```
**Why**: Typed contract.

### `packages/ai-parrot/src/parrot/knowledge/wiki/runtime.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'persistence = SQLitePersistence(config.graph_path(root))' parrot/knowledge/wiki/runtime.py)
# AFTER/AT — anchor `persistence = SQLitePersistence(config.graph_path(root))` (verified: runtime.py:91)
# REPLACE with:
        persistence = await persistence_for_project(config, root)
# ADD module-level:
# async def persistence_for_project(config: WikiProjectConfig, root: Path, *, tenant_id: str | None = None) -> GraphPersistence:
#     """create_graph_persistence(config.backend, **spec.project_options(config, root, tenant)) — sqlite -> db_dir=config.graph_path(root)."""
```
**Why**: Single project-config bridge (S1/S4 absorbed).

### `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py` (MODIFY)
```python
# occurrences: 2 (verified: grep -c 'persistence = SQLitePersistence(config.graph_path(root))' parrot/knowledge/wiki/cli.py)
# FILL IN: disambiguate — occurrences at lines [4017, 4629]; the target one is the occurrence after `from parrot.knowledge.graphindex.persist_sqlite import SQLitePersistence` at :4001 and :4623 — replace both
# REPLACE both occurrences with `persistence = await persistence_for_project(config, root)` (or _run(...) in sync helpers)
```
**Why**: Same bridge.

### `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'publisher = GraphPublisher(SQLitePersistence(config.graph_path(root)), ctx)' parrot/knowledge/wiki/cli.py)
# AFTER/AT — anchor `publisher = GraphPublisher(SQLitePersistence(config.graph_path(root)), ctx)` (verified: cli.py:4114)
# REPLACE with publisher = GraphPublisher(await persistence_for_project(config, root), ctx)
```
**Why**: Same.

### `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'persistence = SQLitePersistence(config.graph_path(root))' parrot/knowledge/wiki/cli.py)
# AFTER/AT — anchor `persistence = SQLitePersistence(config.graph_path(root))` (verified: cli.py:4567)
# REPLACE with persistence_for_project
```
**Why**: Same.

### `packages/ai-parrot/src/parrot/flows/dev_loop/graph_memory.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'persistence = SQLitePersistence(Path(db_dir))' parrot/flows/dev_loop/graph_memory.py)
# AFTER/AT — anchor `persistence = SQLitePersistence(Path(db_dir))` (verified: graph_memory.py:142)
# REPLACE with:
        persistence = await create_graph_persistence("sqlite", db_dir=Path(db_dir))
```
**Why**: No project config here.

### `packages/ai-parrot/tests/knowledge/graphindex/test_persistence_dispatch.py` (CREATE)
```python
"""Dispatch through the registry (FEAT-540 M7)."""
import pytest

# FILL IN: persistence_for_project sqlite -> SQLitePersistence at graph_path; unknown project_options -> ValueError;
# build_graph_memory_toolkit precedence; AST: no `SQLitePersistence(` outside backends.py/persist_sqlite.py/tests
```
**Why**: Spec §4.

### FILL IN checklist
- [ ] _backend_options + precedence
- [ ] persistence_for_project
- [ ] async wrapping at cli sites
- [ ] tests

---

## Acceptance Criteria

- [ ] no direct `SQLitePersistence(` outside backends.py, persist_sqlite.py, tests
- [ ] `persistence_for_project` used by runtime + CLI
- [ ] existing factory/cli/dev-loop graph-memory tests pass

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/graphindex/test_persistence_dispatch.py -q`
- `pytest packages/ai-parrot/tests/knowledge/graphindex/test_cli.py -q`
- `pytest packages/ai-parrot/tests/knowledge/wiki/test_ingest_runtime.py -q`

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
9. **Close** with `scripts/sdd/close_task.sh TASK-4321 graphindex-core-seams verified`
10. **Fill in the Completion Note**, then commit the staged SDD state

---

## Completion Note

**Completed by**: native sonnet (attempt a87e7710), consolidated by sdd-worker
**Date**: 2026-10-15
**Notes**: build_graph_memory_toolkit now dispatches through create_graph_persistence (backend defaults None; db_dir alone => sqlite; db_dir + non-sqlite backend raises ValueError); GraphPublisher takes GraphPersistence (TYPE_CHECKING import); wiki/runtime.py persistence_for_project(config, root, *, tenant_id=None) used by build_novelty_scorer and the 4 wiki/cli.py sites (fallback to the sqlite plane when a backend has no project_options); dev_loop/graph_memory.py uses create_graph_persistence("sqlite", ...). OPEN: graphindex/loader.py:293 `_make_persistence` still constructs SQLitePersistence directly (not in this task's file list) so the "no direct SQLitePersistence( outside backends/persist_sqlite/tests" criterion is not fully met; the AST test exempts loader.py — to be migrated by a later task. Residual ruff B905 at factory.py:191 left as style debt. review coder-review:fce8cebe3e2f407a6ac07008, no corrections. Verification `partial` (same pre-existing failure set as TASK-4315).

**Deviations from spec**: loader.py not migrated (out of declared scope).
