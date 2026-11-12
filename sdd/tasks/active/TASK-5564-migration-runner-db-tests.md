# TASK-5564: Live runner transaction, concurrency and role matrix

**Feature**: FEAT-884 — Packaged PostgreSQL migrations
**Spec**: `sdd/specs/db-upgrade.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-5555, TASK-5556, TASK-5558
**Assigned-to**: unassigned


---

## Context

Implement M6 disposable PostgreSQL runner validation. Use only PARROT_MIGRATION_TEST_DSN and distinct temporary databases; never runtime/admin application DSNs.

---

## Scope

Implement M6 disposable PostgreSQL runner validation. Use only PARROT_MIGRATION_TEST_DSN and distinct temporary databases; never runtime/admin application DSNs.

**NOT in scope**: application-model/loader refactors, Studio or task-memory migration ownership changes, new dependencies, production database execution. Implement only declared targets.

**Parallelism**: Consumes checks.status from TASK-5555, upgrade/baseline from TASK-5556, and full bots chain from TASK-5558. Exclusive: intentional lock contention tests share a PostgreSQL database and role mutations require isolated test-instance access.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/tests/migrations/test_runner_db.py` | CREATE | Two concurrent runners apply once/create ledger safely; lock deadline; rollback body/check/stamp; cancellation lock release; set successors skipped/other sets continue/fail-fast; baseline explicit verified prefix/no bodies/no partial stamps/remaining pending; changed body/check/reapply/whole-set regression; unknown selected filenames; read-only roles and denied SELECT; target identity changes/reserved ledger collision; separate ledger schemas contend on same database lock |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
import pytest
from parrot.migrations.runner import upgrade, baseline
from parrot.migrations.checks import status
```

Standard-library imports are available on supported Python 3.11–3.13. Pydantic and Click are declared in core pyproject.toml at lines 54 and 149; asyncpg is already supplied through asyncdb (line 137). Pytest is the existing test runner. Relative/new `parrot.migrations` imports above are declared by this task or its dependencies, **not existing base-branch APIs**. Imports inside TYPE_CHECKING or callbacks must remain lazy where specified.

### Existing Signatures to Use

- No existing application callable is consumed; use the new dependency interfaces below.

### Dependency interfaces

- `TASK-5555` creates the files/APIs described in its blueprint; read its completion and verify signatures before use.
- `TASK-5556` creates the files/APIs described in its blueprint; read its completion and verify signatures before use.
- `TASK-5558` creates the files/APIs described in its blueprint; read its completion and verify signatures before use.

### Does NOT Exist

- The generic migration packages are absent at planning HEAD; only declared dependency artifacts supply the new APIs.
- No core `PARROT_ADMIN_DSN` setting exists until the CLI task; no existing generic `parrot_schema_migrations` runner may be reused.
- No root-level `parrot/` directory or server `scheduler/store.py` exists. Do not infer executable migration APIs from model docstrings.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/tests/migrations/test_runner_db.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

Follow spec §2 for all safety and exit semantics. Use black (120 columns), strict types, Google-style docstrings and module logging. No synchronous database I/O. New SQL is transaction-wrapper-free; checks run read-only. Tests inject fake DSNs or use only `PARROT_MIGRATION_TEST_DSN`. Never contact application configuration DSNs. Local live tests may skip without the test DSN; feature closeout must provide passing live evidence, not skips. Keep logs under artifacts/logs/.

---

## Implementation Blueprint

### Steps (in order)

1. Verify dependencies and the cited source/anchors — because drift must be caught before editing.
2. Apply the per-file starting points below and complete their bounded logic — because file ownership and public signatures are fixed.
3. Exercise the behavioral matrix, including failures and cleanup — because happy-path checks alone cannot establish migration safety.
4. Run Validation Commands and inspect the scoped diff — because unrelated schema/loader changes are forbidden.

---

### `packages/ai-parrot/tests/migrations/test_runner_db.py` (CREATE)

```python
"""Two concurrent runners apply once/create ledger safely."""
from __future__ import annotations

import pytest
from parrot.migrations.runner import upgrade, baseline
from parrot.migrations.checks import status


async def test_runner_db_contract() -> None:
    """Verify the behavioral matrix listed in this task."""
    # FILL IN: replace this starting test with parameterized cases and fixtures
    # bounded by the Test Specification; assert observable outcomes, not implementation details.
    pytest.fail("Complete the behavioral matrix before finalizing this task")
```

**Why**: Two concurrent runners apply once/create ledger safely; lock deadline; rollback body/check/stamp; cancellation lock release; set successors skipped/other sets continue/fail-fast; baseline explicit verified prefix/no bodies/no partial stamps/remaining pending; changed body/check/reapply/whole-set regression; unknown selected filenames; read-only roles and denied SELECT; target identity changes/reserved ledger collision; separate ledger schemas contend on same database lock

---

### FILL IN checklist

- [ ] `packages/ai-parrot/tests/migrations/test_runner_db.py` — Two concurrent runners apply once/create ledger safely; lock deadline; rollback body/check/stamp; cancellation lock release; set successors skipped/other sets continue/fail-fast; baseline explicit verified prefix/no bodies/no partial stamps/remaining pending; changed body/check/reapply/whole-set regression; unknown selected filenames; read-only roles and denied SELECT; target identity changes/reserved ledger collision; separate ledger schemas contend on same database lock
- [ ] Replace all planning markers with complete working code/tests; no placeholders may remain in implementation files.

---

## Acceptance Criteria

- [ ] All declared files implement the scope and per-file constraints above.
- [ ] Every case in Test Specification asserts observable outcomes, including failure paths.
- [ ] Existing frozen loader, BotModel DDL/shim and unrelated runtime fallback behavior remain unchanged.
- [ ] No credentials, raw driver errors, SQL bodies or parameter values leak into reports/logs.
- [ ] Declared validation succeeds; live-test skips are not release evidence.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/migrations/test_runner_db.py -q`

---

## Test Specification

- Two concurrent runners apply once/create ledger safely; lock deadline; rollback body/check/stamp; cancellation lock release; set successors skipped/other sets continue/fail-fast; baseline explicit verified prefix/no bodies/no partial stamps/remaining pending; changed body/check/reapply/whole-set regression; unknown selected filenames; read-only roles and denied SELECT; target identity changes/reserved ledger collision; separate ledger schemas contend on same database lock

---

## Agent Instructions

1. Use `$sdd-start TASK-5564` to provision the feature worktree; do not implement on dev.
2. Read the full spec and confirm predecessor tasks are done.
3. Reverify existing anchors and new dependency signatures before implementing.
4. Complete the blueprint within its acceptance criteria, then run the task validation commands.
5. Commit only declared implementation files and finalize with `parrot sdd task finalize` using real TaskCompletionEvidence and the implementation HEAD; it owns Completion Note and active-to-completed movement.

## Completion Note

Populated by the task finalizer after verified implementation.
