# TASK-4322: Capability consumers: pin.py, contracts/temporal.py, GraphIndexToolkit use isinstance

**Feature**: FEAT-540 — GraphIndex Core Seams
**Spec**: `sdd/specs/graphindex-core-seams.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4319
**Assigned-to**: unassigned

---

## Context

Spec §3 M7 + §8 Q4. `pin.py:416` reads `persistence._db_path(ctx)`; `contracts/temporal.py:361-375` calls the Postgres temporal surface untyped; `parrot_tools/graphindex/toolkit.py:306,1326` probe with `hasattr`.

---

## Scope

- `pin.py`: `check_pin_coherence(..., persistence: SourceCoherencePersistence, ...)`; read `await persistence.file_hashes(ctx)`; non-capable → `CapabilityUnavailable` before any git call; delete `_read_files_table_sample`'s sqlite access.
- `contracts/temporal.py`: type `TemporalGraphPersistence`; raise `CapabilityUnavailable` otherwise.
- `GraphIndexToolkit`: `isinstance(persistence, TemporalGraphPersistence/HybridRetrievalPersistence)`.
- Tests.

**NOT in scope**: Postgres/SQLite implementations (TASK-4319).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/retrieval/pin.py` | MODIFY | capability |
| `packages/ai-parrot/src/parrot/knowledge/contracts/temporal.py` | MODIFY | typed temporal |
| `packages/ai-parrot-tools/src/parrot_tools/graphindex/toolkit.py` | MODIFY | isinstance |
| `packages/ai-parrot/tests/knowledge/retrieval/test_pin_capability.py` | CREATE | capability tests |

---

## Codebase Contract (Anti-Hallucination)

> Verified against `dev` @ `cf6316096` on 2026-10-14. Re-verify before writing code.

### Verified Imports
```python
from parrot.knowledge.graphindex.protocols import CapabilityUnavailable, HybridRetrievalPersistence, SourceCoherencePersistence, TemporalGraphPersistence  # TASK-4302
```

### Existing Signatures to Use
```python
# pin.py: import SQLitePersistence :24; _read_files_table_sample(db_path) ~:333; check_pin_coherence(pin, persistence: SQLitePersistence, ctx, repo, repo_path, *, sample, allow_stale) :376; db_path = persistence._db_path(ctx) :416
# contracts/temporal.py: persistence.as_of :361; .history :365; .diff :375
# parrot_tools/graphindex/toolkit.py: hasattr(persistence, 'as_of') :306; hasattr(..., 'hybrid_retrieve') :1326
```

### Does NOT Exist
- ~~`file_hashes` on any backend before TASK-4319~~

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/retrieval/pin.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/contracts/temporal.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-tools/src/parrot_tools/graphindex/toolkit.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/retrieval/test_pin_capability.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/retrieval/pin.py#check_pin_coherence"
  ]
}
```

---

## Implementation Notes

Keep `_select_deterministic_sample` unchanged — it relies on the sorted order, which `file_hashes` guarantees.

### Key Constraints
- Async-first; Pydantic v2; `self.logger` / `logging.getLogger(__name__)`; Google docstrings; strict type hints; 120 cols.
- Never import `requests`/`httpx`/`langchain`; no `print`. Hard cuts for renamed internals (no external consumers).
- Touch only the files listed above.

---

## Implementation Blueprint

### Steps (in order)
1. pin.py capability — *why*: Q4.
2. temporal typing — *why*: G7.
3. toolkit isinstance — *why*: G7.
4. Tests.

### `packages/ai-parrot/src/parrot/knowledge/retrieval/pin.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'db_path = persistence._db_path(ctx)' parrot/knowledge/retrieval/pin.py)
# AFTER/AT — anchor `db_path = persistence._db_path(ctx)` (verified: pin.py:416)
# REPLACE with:
    if not isinstance(persistence, SourceCoherencePersistence):
        raise CapabilityUnavailable(type(persistence).__name__, "source_coherence")
    all_rows = await persistence.file_hashes(ctx)
# FILL IN: drop the next line that reads _read_files_table_sample; remove the SQLitePersistence import and the aiosqlite helper if unused
```
**Why**: Backend-neutral pinning.

### `packages/ai-parrot/src/parrot/knowledge/contracts/temporal.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'return await self.persistence.as_of(ctx, when)' parrot/knowledge/contracts/temporal.py)
# AFTER/AT — anchor `return await self.persistence.as_of(ctx, when)` (verified: temporal.py:361)
# INSERT before the call:
        if not isinstance(self.persistence, TemporalGraphPersistence):
            raise CapabilityUnavailable(type(self.persistence).__name__, "temporal")
# FILL IN: same guard for history/diff
```
**Why**: Explicit capability.

### `packages/ai-parrot-tools/src/parrot_tools/graphindex/toolkit.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'if persistence is not None and hasattr(persistence, "as_of"):' parrot_tools/graphindex/toolkit.py)
# AFTER/AT — anchor `if persistence is not None and hasattr(persistence, "as_of"):` (verified: toolkit.py:306)
# REPLACE with:
        if persistence is not None and isinstance(persistence, TemporalGraphPersistence):
```
**Why**: No hasattr probes.

### `packages/ai-parrot-tools/src/parrot_tools/graphindex/toolkit.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'if persistence is None or not hasattr(persistence, "hybrid_retrieve"):' parrot_tools/graphindex/toolkit.py)
# AFTER/AT — anchor `if persistence is None or not hasattr(persistence, "hybrid_retrieve"):` (verified: toolkit.py:1326)
# REPLACE with:
        if persistence is None or not isinstance(persistence, HybridRetrievalPersistence):
```
**Why**: Same.

### `packages/ai-parrot/tests/knowledge/retrieval/test_pin_capability.py` (CREATE)
```python
"""pin.py consumes SourceCoherencePersistence (FEAT-540 M7 / Q4)."""
import pytest

# FILL IN: SQLite plane -> file_hashes used, report coherent; object without file_hashes -> CapabilityUnavailable before any git call (mock read_at_rev asserts not called)
```
**Why**: Spec §4 test_pin_source_coherence_capability.

### FILL IN checklist
- [ ] pin.py cleanup
- [ ] temporal guards
- [ ] tests

---

## Acceptance Criteria

- [ ] `pin.py` no longer touches `_db_path`/aiosqlite
- [ ] no `hasattr(persistence, ...)` in toolkit/temporal
- [ ] existing pin/temporal/toolkit tests pass

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/retrieval/test_pin_capability.py -q`
- `pytest packages/ai-parrot/tests/knowledge/retrieval/test_pin_coherence.py -q`
- `pytest packages/ai-parrot/tests/knowledge/contracts/test_temporal.py -q`
- `pytest packages/ai-parrot-tools/tests/graphindex/test_toolkit_temporal.py -q`

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
9. **Close** with `scripts/sdd/close_task.sh TASK-4322 graphindex-core-seams verified`
10. **Fill in the Completion Note**, then commit the staged SDD state

---

## Completion Note

**Completed by**: codex gpt-5.6-terra (attempt 857a5921), consolidated by sdd-worker
**Date**: 2026-10-15
**Notes**: retrieval/pin.py pin capability, typed temporal in contracts/temporal.py, isinstance dispatch in parrot_tools graphindex toolkit, new test_pin_capability.py. Validation run directly: tests/knowledge/retrieval + tests/knowledge/contracts = 639 passed, 56 skipped; ai-parrot-tools test_toolkit_temporal.py 3 passed, 2 failed (test_temporal_tools_present_on_postgres, test_graph_diff_tool_smoke) with ConnectionRefusedError — Postgres is unreachable in this sandbox (environmental). Verification therefore `partial`. No review corrections.

**Deviations from spec**: none.
