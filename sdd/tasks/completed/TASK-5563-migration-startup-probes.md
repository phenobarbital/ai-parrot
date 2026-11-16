# TASK-5563: Bounded read-only startup and doctor probes

**Feature**: FEAT-884 — Packaged PostgreSQL migrations
**Spec**: `sdd/specs/db-upgrade.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-5554, TASK-5555
**Assigned-to**: unassigned


---

## Context

Implement M5 probes and enabled database-bot startup hook. Probe failures warn without blocking loading; cancellation still propagates.

---

## Scope

Implement M5 probes and enabled database-bot startup hook. Probe failures warn without blocking loading; cancellation still propagates.

**NOT in scope**: application-model/loader refactors, Studio or task-memory migration ownership changes, new dependencies, production database execution. Implement only declared targets.

**Parallelism**: Consumes bots_set from TASK-5554 and checks.status from TASK-5555. Doctor CLI attachment is owned by the CLI task, which consumes this API.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/migrations/startup.py` | CREATE | No mutation imports, ledger creation or migration advisory lock. Budget is total time, not only connect timeout. |
| `packages/ai-parrot-server/src/parrot/manager/manager.py` | MODIFY | Inside if self.enable_database_bots, locally import warn_pending_migrations and await warn_pending_migrations(default_dsn, logger=self.logger) immediately before unchanged await self._load_database_bots(app). Do not touch _load_database_bots. |
| `packages/ai-parrot/tests/migrations/test_startup.py` | CREATE | Unconfigured no connect; pending/changed/drift/unavailable distinctions; 2s startup and 5s doctor total bounds; cancellation; sanitized output; SELECT-only and no mutation imports |
| `packages/ai-parrot-server/tests/migrations/test_startup.py` | CREATE | Disabled database bots never probe; enabled probe runs before unchanged loader; timeout/failure still loads; cancellation propagates; same runtime DSN and configured target |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
import asyncio
import logging
from typing import TYPE_CHECKING
from parrot.self_.doctor import DoctorCheck
from parrot.migrations.startup import warn_pending_migrations
from parrot.conf import default_dsn
import pytest
from parrot.migrations.startup import warn_pending_migrations, migration_doctor_check
from unittest.mock import AsyncMock
```

Standard-library imports are available on supported Python 3.11–3.13. Pydantic and Click are declared in core pyproject.toml at lines 54 and 149; asyncpg is already supplied through asyncdb (line 137). Pytest is the existing test runner. Relative/new `parrot.migrations` imports above are declared by this task or its dependencies, **not existing base-branch APIs**. Imports inside TYPE_CHECKING or callbacks must remain lazy where specified.

### Existing Signatures to Use

- `packages/ai-parrot/src/parrot/self_/doctor.py` — DoctorCheck at line 39 has informational flag and string detail/fix.
- `packages/ai-parrot-server/src/parrot/manager/manager.py` — anchor at line 502, one exact occurrence: `        # Step 4: Load database bots`
- `packages/ai-parrot-server/src/parrot/manager/manager.py` — BotManager.load_bots(self, app: web.Application) -> None async at line 464; frozen loader async at line 689.

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
      "path": "packages/ai-parrot/src/parrot/migrations/startup.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-server/src/parrot/manager/manager.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/migrations/test_startup.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-server/tests/migrations/test_startup.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/self_/doctor.py#DoctorCheck",
    "sym:packages/ai-parrot-server/src/parrot/manager/manager.py#BotManager.load_bots"
  ]
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

### `packages/ai-parrot/src/parrot/migrations/startup.py` (CREATE)

```python
"""Bounded informational schema diagnostics; never apply migrations."""
from __future__ import annotations
import asyncio
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from parrot.self_.doctor import DoctorCheck


async def warn_pending_migrations(dsn: str | None, *, logger: logging.Logger) -> None:
    """Bound bots-only SELECT probes to two seconds, then warn and allow startup."""
    # FILL IN: local checks.status/providers.bots_set imports; runtime DSN only.
    # timeout encloses total operation; missing/unavailable/drift are distinct safe warnings.
    # Propagate CancelledError; close resources via status cancellation cleanup.


async def migration_doctor_check(dsn: str | None) -> DoctorCheck:
    """Return a five-second informational check with explicit unconfigured state."""
    from parrot.self_.doctor import DoctorCheck
    # FILL IN: same read-only path; unconfigured does not connect; never admin fallback.
    # All returned checks informational=True; preserve cancellation.
```

**Why**: No mutation imports, ledger creation or migration advisory lock. Budget is total time, not only connect timeout.

---

### `packages/ai-parrot-server/src/parrot/manager/manager.py` (MODIFY)

```python
# Anchor (exact full line):         # Step 4: Load database bots
# occurrences: 1; verified at packages/ai-parrot-server/src/parrot/manager/manager.py:502
# FILL IN: Inside if self.enable_database_bots, locally import warn_pending_migrations and await warn_pending_migrations(default_dsn, logger=self.logger) immediately before unchanged await self._load_database_bots(app). Do not touch _load_database_bots.
```

**Why**: Inside if self.enable_database_bots, locally import warn_pending_migrations and await warn_pending_migrations(default_dsn, logger=self.logger) immediately before unchanged await self._load_database_bots(app). Do not touch _load_database_bots.

---

### `packages/ai-parrot/tests/migrations/test_startup.py` (CREATE)

```python
"""Unconfigured no connect."""
from __future__ import annotations

import pytest
from parrot.migrations.startup import warn_pending_migrations, migration_doctor_check


async def test_startup_contract() -> None:
    """Verify the behavioral matrix listed in this task."""
    # FILL IN: replace this starting test with parameterized cases and fixtures
    # bounded by the Test Specification; assert observable outcomes, not implementation details.
    pytest.fail("Complete the behavioral matrix before finalizing this task")
```

**Why**: Unconfigured no connect; pending/changed/drift/unavailable distinctions; 2s startup and 5s doctor total bounds; cancellation; sanitized output; SELECT-only and no mutation imports

---

### `packages/ai-parrot-server/tests/migrations/test_startup.py` (CREATE)

```python
"""Disabled database bots never probe."""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock


async def test_startup_contract() -> None:
    """Verify the behavioral matrix listed in this task."""
    # FILL IN: replace this starting test with parameterized cases and fixtures
    # bounded by the Test Specification; assert observable outcomes, not implementation details.
    pytest.fail("Complete the behavioral matrix before finalizing this task")
```

**Why**: Disabled database bots never probe; enabled probe runs before unchanged loader; timeout/failure still loads; cancellation propagates; same runtime DSN and configured target

---

### FILL IN checklist

- [ ] `packages/ai-parrot/src/parrot/migrations/startup.py` — No mutation imports, ledger creation or migration advisory lock. Budget is total time, not only connect timeout.
- [ ] `packages/ai-parrot-server/src/parrot/manager/manager.py` — Inside if self.enable_database_bots, locally import warn_pending_migrations and await warn_pending_migrations(default_dsn, logger=self.logger) immediately before unchanged await self._load_database_bots(app). Do not touch _load_database_bots.
- [ ] `packages/ai-parrot/tests/migrations/test_startup.py` — Unconfigured no connect; pending/changed/drift/unavailable distinctions; 2s startup and 5s doctor total bounds; cancellation; sanitized output; SELECT-only and no mutation imports
- [ ] `packages/ai-parrot-server/tests/migrations/test_startup.py` — Disabled database bots never probe; enabled probe runs before unchanged loader; timeout/failure still loads; cancellation propagates; same runtime DSN and configured target
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

- `pytest packages/ai-parrot/tests/migrations/test_startup.py -q`
- `pytest packages/ai-parrot-server/tests/migrations/test_startup.py -q`

---

## Test Specification

- Unconfigured no connect; pending/changed/drift/unavailable distinctions; 2s startup and 5s doctor total bounds; cancellation; sanitized output; SELECT-only and no mutation imports
- Disabled database bots never probe; enabled probe runs before unchanged loader; timeout/failure still loads; cancellation propagates; same runtime DSN and configured target

---

## Agent Instructions

1. Use `$sdd-start TASK-5563` to provision the feature worktree; do not implement on dev.
2. Read the full spec and confirm predecessor tasks are done.
3. Reverify existing anchors and new dependency signatures before implementing.
4. Complete the blueprint within its acceptance criteria, then run the task validation commands.
5. Commit only declared implementation files and finalize with `parrot sdd task finalize` using real TaskCompletionEvidence and the implementation HEAD; it owns Completion Note and active-to-completed movement.

## Completion Note


- Task: TASK-5563
- Feature: db-upgrade
- Implementation SHA: 7e7d1a8a403c90c07255674ddabc10d3d49f208c
- Closed at (UTC): 2026-11-12T23:48:20+00:00
- Fix commits: none

| Metric | Value |
|---|---|
| validation_refs | 1 |
| fix_commits | 0 |
| seat_summary | Seat: gpt-5.6-sol · Backend: codex · Model: gpt-5.6-sol · Attempts: 1 · Duration: 351s · Tokens: n/a |
