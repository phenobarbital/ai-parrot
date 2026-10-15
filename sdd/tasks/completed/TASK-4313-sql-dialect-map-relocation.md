# TASK-4313: Move the SQL dialect map to knowledge/common; repoint wiki consumers

**Feature**: FEAT-540 — GraphIndex Core Seams
**Spec**: `sdd/specs/graphindex-core-seams.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-4311
**Assigned-to**: unassigned

---

## Context

Spec §3 M4. `wiki/cli.py:46`, `schema/render.py:14`, `schema/producers/ddl.py:13` import a plain dict through `parrot.tools.sql_dialects`, booting the tools package.

---

## Scope

- Create `parrot/knowledge/common/sql_dialects.py` holding the mapping (moved from `parrot/tools/sql_dialects.py`).
- `parrot/tools/sql_dialects.py` re-exports from the new module (same object).
- Repoint the three wiki consumers.
- Test: same object; render/DDL output identical for every alias.

**NOT in scope**: Adding dialects.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/common/sql_dialects.py` | CREATE | dialect map |
| `packages/ai-parrot/src/parrot/tools/sql_dialects.py` | MODIFY | re-export |
| `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py` | MODIFY | import |
| `packages/ai-parrot/src/parrot/knowledge/wiki/schema/render.py` | MODIFY | import |
| `packages/ai-parrot/src/parrot/knowledge/wiki/schema/producers/ddl.py` | MODIFY | import |
| `packages/ai-parrot/tests/knowledge/common/test_sql_dialects.py` | CREATE | identity tests |

---

## Codebase Contract (Anti-Hallucination)

> Verified against `dev` @ `cf6316096` on 2026-10-14. Re-verify before writing code.

### Verified Imports
```python
from parrot.tools.sql_dialects import _SQLGLOT_DIALECT_MAP  # sql_dialects.py:27 (= SQLGLOT_DIALECT_MAP)
```

### Existing Signatures to Use
```python
# parrot/tools/sql_dialects.py:27 `_SQLGLOT_DIALECT_MAP = SQLGLOT_DIALECT_MAP`
# consumers: wiki/cli.py:46 (+ click.Choice :3599, :3648); schema/render.py:14 (:47); schema/producers/ddl.py:13 (:219)
```

### Does NOT Exist
- ~~`parrot.knowledge.common.sql_dialects` (created here; `knowledge/common/` exists with provenance.py/validation.py)~~

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/common/sql_dialects.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/src/parrot/tools/sql_dialects.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/wiki/cli.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/wiki/schema/render.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/wiki/schema/producers/ddl.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/common/test_sql_dialects.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

Read `parrot/tools/sql_dialects.py` fully — move `SQLGLOT_DIALECT_MAP` and any helper the wiki uses; leave tools-only helpers in place.

### Key Constraints
- Async-first; Pydantic v2; `self.logger` / `logging.getLogger(__name__)`; Google docstrings; strict type hints; 120 cols.
- Never import `requests`/`httpx`/`langchain`; no `print`. Hard cuts for renamed internals (no external consumers).
- Touch only the files listed above.

---

## Implementation Blueprint

### Steps (in order)
1. Move the dict — *why*: plain data must not boot parrot.tools.
2. Re-export — *why*: tools consumers unchanged.
3. Repoint three imports.
4. Test.

### `packages/ai-parrot/src/parrot/knowledge/common/sql_dialects.py` (CREATE)
```python
"""SQL dialect alias map shared by wiki schema and tools (FEAT-540 M4)."""

# FILL IN: move SQLGLOT_DIALECT_MAP (and its docstring) verbatim from parrot/tools/sql_dialects.py
_SQLGLOT_DIALECT_MAP = SQLGLOT_DIALECT_MAP  # noqa: F821 — defined above once moved
```
**Why**: Neutral home.

### `packages/ai-parrot/src/parrot/tools/sql_dialects.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '_SQLGLOT_DIALECT_MAP = SQLGLOT_DIALECT_MAP' parrot/tools/sql_dialects.py)
# AFTER/AT — anchor `_SQLGLOT_DIALECT_MAP = SQLGLOT_DIALECT_MAP` (verified: sql_dialects.py:27)
# REPLACE the map definition with:
from parrot.knowledge.common.sql_dialects import SQLGLOT_DIALECT_MAP, _SQLGLOT_DIALECT_MAP  # noqa: F401
```
**Why**: Same object for existing consumers.

### `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'from parrot.tools.sql_dialects import _SQLGLOT_DIALECT_MAP' parrot/knowledge/wiki/cli.py)
# AFTER/AT — anchor `from parrot.tools.sql_dialects import _SQLGLOT_DIALECT_MAP` (verified: cli.py:46)
# REPLACE with:
from parrot.knowledge.common.sql_dialects import _SQLGLOT_DIALECT_MAP
```
**Why**: No tools boot.

### `packages/ai-parrot/src/parrot/knowledge/wiki/schema/render.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'from parrot.tools.sql_dialects import _SQLGLOT_DIALECT_MAP' parrot/knowledge/wiki/schema/render.py)
# AFTER/AT — anchor `from parrot.tools.sql_dialects import _SQLGLOT_DIALECT_MAP` (verified: render.py:14)
# REPLACE with:
from parrot.knowledge.common.sql_dialects import _SQLGLOT_DIALECT_MAP
```
**Why**: Same.

### `packages/ai-parrot/src/parrot/knowledge/wiki/schema/producers/ddl.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'from parrot.tools.sql_dialects import _SQLGLOT_DIALECT_MAP' parrot/knowledge/wiki/schema/producers/ddl.py)
# AFTER/AT — anchor `from parrot.tools.sql_dialects import _SQLGLOT_DIALECT_MAP` (verified: ddl.py:13)
# REPLACE with:
from parrot.knowledge.common.sql_dialects import _SQLGLOT_DIALECT_MAP
```
**Why**: Same.

### `packages/ai-parrot/tests/knowledge/common/test_sql_dialects.py` (CREATE)
```python
"""Dialect map relocation (FEAT-540 M4)."""


def test_same_object() -> None:
    from parrot.knowledge.common.sql_dialects import _SQLGLOT_DIALECT_MAP as new
    from parrot.tools.sql_dialects import _SQLGLOT_DIALECT_MAP as old

    assert old is new

# FILL IN: probe 'parrot.knowledge.wiki.schema.render' -> 'parrot.tools' not loaded; render/DDL output equal for every alias
```
**Why**: Identity + behaviour.

### FILL IN checklist
- [ ] move map verbatim
- [ ] probe + render equality tests

---

## Acceptance Criteria

- [ ] same object from both paths
- [ ] wiki schema modules no longer import `parrot.tools`
- [ ] render/DDL output unchanged

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/common/test_sql_dialects.py -q`

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
9. **Close** with `scripts/sdd/close_task.sh TASK-4313 graphindex-core-seams verified`
10. **Fill in the Completion Note**, then commit the staged SDD state

---

## Completion Note

**Completed by**: codex gpt-5.6-terra, consolidated by sdd-worker
**Date**: 2026-10-15
**Notes**: SQL dialect map moved to parrot/knowledge/common/sql_dialects.py; parrot/tools/sql_dialects.py re-exports the same object; cli.py, schema/render.py and schema/producers/ddl.py repointed (import-only change, correct). Its own tests failed on delivery and were fixed in 8640f08f5: the probe over-asserted (render.py still imports parrot.bots, which boots parrot.tools transitively - out of this task's scope, so the probe now asserts parrot.tools.sql_dialects is not loaded); loaded_at clock comparison; render_ddl treats the target 'tsql' generically because it is not a key of the map (pre-existing behaviour, now documented in the test). feedback coder-feedback:966cf8ede4c391712d3dab9b (recurrence of untested-test-fixtures-and-clock-equality); review coder-review:0627ce2acaaa5f3b151e0dbf. NOTE for the owner: AC 'wiki schema modules no longer import parrot.tools' holds for the dialect map only; render.py's `from parrot.bots.database.models import TableMetadata` still loads parrot.tools via parrot.bots. Verification is `partial`: the engine merge-tier sandbox cannot reach Postgres and has pre-existing reds. With GRAPHINDEX_PG_DSN on local docker-postgres-1, tests/knowledge + tests/embeddings (4294 passed in the chunk run) showed no failure absent from the clean origin/dev baseline other than TASK-4313's own two test failures, fixed in 8640f08f5 (test-only, 3 consecutive green runs); ai-parrot-tools wiki tests 22 passed.

**Deviations from spec**: AC 'no parrot.tools import' met for the dialect map only (see Notes)
