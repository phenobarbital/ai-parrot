# TASK-5555: Read-only migration status and postcondition checks

**Feature**: FEAT-884 — Packaged PostgreSQL migrations
**Spec**: `sdd/specs/db-upgrade.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-5554
**Assigned-to**: unassigned


---

## Context

Implement M2 read path in checks.py, independent of runner mutations. Validate ownership, ledger history/checksums and live postconditions using SELECT-only transactions.

---

## Scope

Implement M2 read path in checks.py, independent of runner mutations. Validate ownership, ledger history/checksums and live postconditions using SELECT-only transactions.

**NOT in scope**: application-model/loader refactors, Studio or task-memory migration ownership changes, new dependencies, production database execution. Implement only declared targets.

**Parallelism**: Consumes MigrationSet, MigrationFile, MigrationReport and catalog.load_migrations from TASK-5554.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/migrations/checks.py` | CREATE | No import of runner.py. Missing objects are pending/drift; inaccessible objects must not be reported healthy. Share verification mechanics with mutation callers without acquiring locks here. |
| `packages/ai-parrot/tests/migrations/test_checks.py` | CREATE | Missing ledger/all pending; matched hashes but failed checks; changed body/check separately; unknown selected rows; unselected rows ignored; target identity mismatch; malformed check shapes; SELECT-only/no lock/no DDL; permission failures; connection close and cancellation |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from typing import TYPE_CHECKING
import asyncpg
from .models import MigrationFile, MigrationReport, MigrationSet
from .catalog import load_migrations, render_sql
import pytest
from parrot.migrations.checks import status, verify_postconditions
```

Standard-library imports are available on supported Python 3.11–3.13. Pydantic and Click are declared in core pyproject.toml at lines 54 and 149; asyncpg is already supplied through asyncdb (line 137). Pytest is the existing test runner. Relative/new `parrot.migrations` imports above are declared by this task or its dependencies, **not existing base-branch APIs**. Imports inside TYPE_CHECKING or callbacks must remain lazy where specified.

### Existing Signatures to Use

- `packages/ai-parrot/src/parrot/conf.py` — default_dsn line 71 and PARROT_SCHEMA/PARROT_BOTS_TABLE line 121; resolve names once per call.

### Dependency interfaces

- `TASK-5554` creates the files/APIs described in its blueprint; read its completion and verify signatures before use.

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
      "path": "packages/ai-parrot/src/parrot/migrations/checks.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/tests/migrations/test_checks.py",
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

### `packages/ai-parrot/src/parrot/migrations/checks.py` (CREATE)

```python
"""SELECT-only migration inspection, shared by status, doctor and startup."""
from __future__ import annotations
from typing import TYPE_CHECKING

from .models import MigrationFile, MigrationReport, MigrationSet
from .catalog import load_migrations, render_sql

if TYPE_CHECKING:
    import asyncpg


async def status(dsn: str, *, sets: tuple[MigrationSet, ...], connect_timeout: float = 5.0,
                 statement_timeout: float = 60.0) -> MigrationReport:
    """Read selected ledger/check state without creating objects or taking a write lock."""
    # FILL IN: lazy asyncpg import; snapshot configured target once, open dedicated connection.
    # Validate identifiers before connect. Bound connect/statement time, close in finally.
    # Inspect pg_catalog before selecting missing ledger/relations; permission denial is an error.
    # Classify PENDING/APPLIED/CHANGED; unknown selected filenames or target mismatch fail.
    # Read-only transaction; safe SQLSTATE/category diagnostics; propagate cancellation.


async def verify_postconditions(conn: asyncpg.Connection, migrations: tuple[MigrationFile, ...],
                                *, schema: str, bots_table: str) -> tuple[str, ...]:
    """Return failed identities; every check must yield exactly one boolean column and row."""
    # FILL IN: resolve each set's owned relations from catalog metadata; bound catalog values.
    # Missing relations yield failed identities before parsing check SQL naming those relations.
    # Enforce read-only execution, exact bool (not None/int), one row/column, full-file SQL.
```

**Why**: No import of runner.py. Missing objects are pending/drift; inaccessible objects must not be reported healthy. Share verification mechanics with mutation callers without acquiring locks here.

---

### `packages/ai-parrot/tests/migrations/test_checks.py` (CREATE)

```python
"""Missing ledger/all pending."""
from __future__ import annotations

import pytest
from parrot.migrations.checks import status, verify_postconditions


async def test_checks_contract() -> None:
    """Verify the behavioral matrix listed in this task."""
    # FILL IN: replace this starting test with parameterized cases and fixtures
    # bounded by the Test Specification; assert observable outcomes, not implementation details.
    pytest.fail("Complete the behavioral matrix before finalizing this task")
```

**Why**: Missing ledger/all pending; matched hashes but failed checks; changed body/check separately; unknown selected rows; unselected rows ignored; target identity mismatch; malformed check shapes; SELECT-only/no lock/no DDL; permission failures; connection close and cancellation

---

### FILL IN checklist

- [ ] `packages/ai-parrot/src/parrot/migrations/checks.py` — No import of runner.py. Missing objects are pending/drift; inaccessible objects must not be reported healthy. Share verification mechanics with mutation callers without acquiring locks here.
- [ ] `packages/ai-parrot/tests/migrations/test_checks.py` — Missing ledger/all pending; matched hashes but failed checks; changed body/check separately; unknown selected rows; unselected rows ignored; target identity mismatch; malformed check shapes; SELECT-only/no lock/no DDL; permission failures; connection close and cancellation
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

- `pytest packages/ai-parrot/tests/migrations/test_checks.py -q`

---

## Test Specification

- Missing ledger/all pending; matched hashes but failed checks; changed body/check separately; unknown selected rows; unselected rows ignored; target identity mismatch; malformed check shapes; SELECT-only/no lock/no DDL; permission failures; connection close and cancellation

---

## Agent Instructions

1. Use `$sdd-start TASK-5555` to provision the feature worktree; do not implement on dev.
2. Read the full spec and confirm predecessor tasks are done.
3. Reverify existing anchors and new dependency signatures before implementing.
4. Complete the blueprint within its acceptance criteria, then run the task validation commands.
5. Commit only declared implementation files and finalize with `parrot sdd task finalize` using real TaskCompletionEvidence and the implementation HEAD; it owns Completion Note and active-to-completed movement.

## Completion Note

Populated by the task finalizer after verified implementation.
