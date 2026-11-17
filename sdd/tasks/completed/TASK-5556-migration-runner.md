# TASK-5556: Transactional upgrade and verified baseline runner

**Feature**: FEAT-884 — Packaged PostgreSQL migrations
**Spec**: `sdd/specs/db-upgrade.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-5554, TASK-5555
**Assigned-to**: unassigned


---

## Context

Implement M2 mutation lifecycle and safe reports. Honor per-file transactions, global advisory lock, sequence-dependent failure handling and verified adoption.

---

## Scope

Implement M2 mutation lifecycle and safe reports. Honor per-file transactions, global advisory lock, sequence-dependent failure handling and verified adoption.

**NOT in scope**: application-model/loader refactors, Studio or task-memory migration ownership changes, new dependencies, production database execution. Implement only declared targets.

**Parallelism**: Consumes catalog/models from TASK-5554 and checks.verify_postconditions from TASK-5555.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/migrations/runner.py` | CREATE | Implement exact ledger columns/PK/operation values from spec §2. Never use asyncdb error-as-value API. Baseline must not create a ledger before verification succeeds. |
| `packages/ai-parrot/tests/migrations/test_runner.py` | CREATE | Lock before ledger snapshot/create; bounded contention; rollback body/check/ledger together; failure skips successors; fail_fast and independent sets; baseline all-prefix verification before any write/no bodies; changed/unknown/target mismatch rejection; reapply whole-set recheck; cancellation/unlock/close; secrets absent from errors |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
import asyncio
import time
from .catalog import load_migrations, render_sql
from .checks import verify_postconditions
from .models import MigrationReport, MigrationSet
import asyncpg
import pytest
from parrot.migrations.runner import upgrade, baseline
```

Standard-library imports are available on supported Python 3.11–3.13. Pydantic and Click are declared in core pyproject.toml at lines 54 and 149; asyncpg is already supplied through asyncdb (line 137). Pytest is the existing test runner. Relative/new `parrot.migrations` imports above are declared by this task or its dependencies, **not existing base-branch APIs**. Imports inside TYPE_CHECKING or callbacks must remain lazy where specified.

### Existing Signatures to Use

- `packages/ai-parrot/pyproject.toml` — asyncdb>=2.16.2 line 137 supplies asyncpg; existing extras explicitly use asyncpg>=0.29. No new driver.

### Dependency interfaces

- `TASK-5554` creates the files/APIs described in its blueprint; read its completion and verify signatures before use.
- `TASK-5555` creates the files/APIs described in its blueprint; read its completion and verify signatures before use.

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
      "path": "packages/ai-parrot/src/parrot/migrations/runner.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/tests/migrations/test_runner.py",
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

### `packages/ai-parrot/src/parrot/migrations/runner.py` (CREATE)

```python
"""Explicit deployment-time upgrades and verified adoption."""
from __future__ import annotations
import asyncio
import time

from .catalog import load_migrations, render_sql
from .checks import verify_postconditions
from .models import MigrationReport, MigrationSet


async def upgrade(dsn: str, *, sets: tuple[MigrationSet, ...], fail_fast: bool = False,
                  reapply_changed: bool = False, connect_timeout: float = 5.0,
                  lock_timeout: float = 30.0, statement_timeout: float = 60.0) -> MigrationReport:
    """Apply ordered bodies and ledger records atomically under a bounded session lock."""
    # FILL IN: connect lazily; pg_try_advisory_lock(884000001), asyncio retry/monotonic deadline.
    # Under lock: create ledger if needed, re-read state, reject target changes/unknown history.
    # One body + check + stamp transaction; 5s DDL-lock timeout, configured statement timeout.
    # Stop failed/changed set successors; continue independent sets unless fail_fast.
    # Reapply only explicitly; update hashes only on success; recheck whole selected set.
    # finally unlock and close even during cancellation; report only SQLSTATE/safe category.


async def baseline(dsn: str, *, migration_set: MigrationSet, through: int,
                   connect_timeout: float = 5.0, lock_timeout: float = 30.0,
                   statement_timeout: float = 60.0) -> MigrationReport:
    """Verify and stamp an explicit prefix without executing any body SQL."""
    # FILL IN: same lock; reject changed/unknown rows; verify entire prefix read-only first.
    # Then atomically create ledger and insert new rows in one write transaction.
    # Hold lock across both phases, recheck identity before commit, identical rows are no-op.
```

**Why**: Implement exact ledger columns/PK/operation values from spec §2. Never use asyncdb error-as-value API. Baseline must not create a ledger before verification succeeds.

---

### `packages/ai-parrot/tests/migrations/test_runner.py` (CREATE)

```python
"""Lock before ledger snapshot/create."""
from __future__ import annotations

import pytest
from parrot.migrations.runner import upgrade, baseline


async def test_runner_contract() -> None:
    """Verify the behavioral matrix listed in this task."""
    # FILL IN: replace this starting test with parameterized cases and fixtures
    # bounded by the Test Specification; assert observable outcomes, not implementation details.
    pytest.fail("Complete the behavioral matrix before finalizing this task")
```

**Why**: Lock before ledger snapshot/create; bounded contention; rollback body/check/ledger together; failure skips successors; fail_fast and independent sets; baseline all-prefix verification before any write/no bodies; changed/unknown/target mismatch rejection; reapply whole-set recheck; cancellation/unlock/close; secrets absent from errors

---

### FILL IN checklist

- [ ] `packages/ai-parrot/src/parrot/migrations/runner.py` — Implement exact ledger columns/PK/operation values from spec §2. Never use asyncdb error-as-value API. Baseline must not create a ledger before verification succeeds.
- [ ] `packages/ai-parrot/tests/migrations/test_runner.py` — Lock before ledger snapshot/create; bounded contention; rollback body/check/ledger together; failure skips successors; fail_fast and independent sets; baseline all-prefix verification before any write/no bodies; changed/unknown/target mismatch rejection; reapply whole-set recheck; cancellation/unlock/close; secrets absent from errors
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

- `pytest packages/ai-parrot/tests/migrations/test_runner.py -q`

---

## Test Specification

- Lock before ledger snapshot/create; bounded contention; rollback body/check/ledger together; failure skips successors; fail_fast and independent sets; baseline all-prefix verification before any write/no bodies; changed/unknown/target mismatch rejection; reapply whole-set recheck; cancellation/unlock/close; secrets absent from errors

---

## Agent Instructions

1. Use `$sdd-start TASK-5556` to provision the feature worktree; do not implement on dev.
2. Read the full spec and confirm predecessor tasks are done.
3. Reverify existing anchors and new dependency signatures before implementing.
4. Complete the blueprint within its acceptance criteria, then run the task validation commands.
5. Commit only declared implementation files and finalize with `parrot sdd task finalize` using real TaskCompletionEvidence and the implementation HEAD; it owns Completion Note and active-to-completed movement.

## Completion Note


- Task: TASK-5556
- Feature: db-upgrade
- Implementation SHA: 7e7d1a8a403c90c07255674ddabc10d3d49f208c
- Closed at (UTC): 2026-11-12T23:48:18+00:00
- Fix commits: none

| Metric | Value |
|---|---|
| validation_refs | 1 |
| fix_commits | 0 |
| seat_summary | Seat: gpt-5.6-terra · Backend: codex · Model: gpt-5.6-terra · Attempts: 1 · Duration: 507s · Tokens: n/a |
