# TASK-5565: Live runtime-set convergence and ownership tests

**Feature**: FEAT-884 — Packaged PostgreSQL migrations
**Spec**: `sdd/specs/db-upgrade.spec.md`
**Status**: done
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-5555, TASK-5556, TASK-5560, TASK-5561
**Assigned-to**: unassigned


---

## Context

Implement M6 live five-set verification on isolated disposable PostgreSQL databases. Compare fresh and pre-existing runtime schemas, constraints, indexes and data.

---

## Scope

Implement M6 live five-set verification on isolated disposable PostgreSQL databases. Compare fresh and pre-existing runtime schemas, constraints, indexes and data.

**NOT in scope**: application-model/loader refactors, Studio or task-memory migration ownership changes, new dependencies, production database execution. Implement only declared targets.

**Parallelism**: Consumes checks.status from TASK-5555, runner from TASK-5556, UI/crew providers/resources from TASK-5560, and remaining runtime SQL from TASK-5561. Exclusive: fixtures execute DDL and roles on a dedicated PostgreSQL test instance.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/tests/migrations/test_runtime_db.py` | CREATE | All five fresh and existing baselines converge; UI old tenant columns catch up before index; crew keys/tombstones retained; metric global partial uniqueness and visibility check; recipes fixed navigator; scheduler fields/defaults; incompatible schemas fail without loss; defaults semantically equivalent; direct replay idempotence; runtime fallback never stamps ledger; Studio/task-memory tables/ledger unchanged; separate crew DB selection explicit |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
import pytest
from parrot.migrations.runner import upgrade, baseline
from parrot.server.migrations import providers
```

Standard-library imports are available on supported Python 3.11–3.13. Pydantic and Click are declared in core pyproject.toml at lines 54 and 149; asyncpg is already supplied through asyncdb (line 137). Pytest is the existing test runner. Relative/new `parrot.migrations` imports above are declared by this task or its dependencies, **not existing base-branch APIs**. Imports inside TYPE_CHECKING or callbacks must remain lazy where specified.

### Existing Signatures to Use

- No existing application callable is consumed; use the new dependency interfaces below.

### Dependency interfaces

- `TASK-5555` creates the files/APIs described in its blueprint; read its completion and verify signatures before use.
- `TASK-5556` creates the files/APIs described in its blueprint; read its completion and verify signatures before use.
- `TASK-5560` creates the files/APIs described in its blueprint; read its completion and verify signatures before use.
- `TASK-5561` creates the files/APIs described in its blueprint; read its completion and verify signatures before use.

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
      "path": "packages/ai-parrot-server/tests/migrations/test_runtime_db.py",
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

### `packages/ai-parrot-server/tests/migrations/test_runtime_db.py` (CREATE)

```python
"""All five fresh and existing baselines converge."""
from __future__ import annotations

import pytest
from parrot.migrations.runner import upgrade, baseline
from parrot.server.migrations import providers


async def test_runtime_db_contract() -> None:
    """Verify the behavioral matrix listed in this task."""
    # FILL IN: replace this starting test with parameterized cases and fixtures
    # bounded by the Test Specification; assert observable outcomes, not implementation details.
    pytest.fail("Complete the behavioral matrix before finalizing this task")
```

**Why**: All five fresh and existing baselines converge; UI old tenant columns catch up before index; crew keys/tombstones retained; metric global partial uniqueness and visibility check; recipes fixed navigator; scheduler fields/defaults; incompatible schemas fail without loss; defaults semantically equivalent; direct replay idempotence; runtime fallback never stamps ledger; Studio/task-memory tables/ledger unchanged; separate crew DB selection explicit

---

### FILL IN checklist

- [ ] `packages/ai-parrot-server/tests/migrations/test_runtime_db.py` — All five fresh and existing baselines converge; UI old tenant columns catch up before index; crew keys/tombstones retained; metric global partial uniqueness and visibility check; recipes fixed navigator; scheduler fields/defaults; incompatible schemas fail without loss; defaults semantically equivalent; direct replay idempotence; runtime fallback never stamps ledger; Studio/task-memory tables/ledger unchanged; separate crew DB selection explicit
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

- `pytest packages/ai-parrot-server/tests/migrations/test_runtime_db.py -q`

---

## Test Specification

- All five fresh and existing baselines converge; UI old tenant columns catch up before index; crew keys/tombstones retained; metric global partial uniqueness and visibility check; recipes fixed navigator; scheduler fields/defaults; incompatible schemas fail without loss; defaults semantically equivalent; direct replay idempotence; runtime fallback never stamps ledger; Studio/task-memory tables/ledger unchanged; separate crew DB selection explicit

---

## Agent Instructions

1. Use `$sdd-start TASK-5565` to provision the feature worktree; do not implement on dev.
2. Read the full spec and confirm predecessor tasks are done.
3. Reverify existing anchors and new dependency signatures before implementing.
4. Complete the blueprint within its acceptance criteria, then run the task validation commands.
5. Commit only declared implementation files and finalize with `parrot sdd task finalize` using real TaskCompletionEvidence and the implementation HEAD; it owns Completion Note and active-to-completed movement.

## Completion Note


- Task: TASK-5565
- Feature: db-upgrade
- Implementation SHA: fef9e4da7bd599f139c8793e526cbe413570eac2
- Closed at (UTC): 2026-11-13T00:06:02+00:00
- Fix commits: none

| Metric | Value |
|---|---|
| validation_refs | 1 |
| fix_commits | 0 |
| seat_summary | Seat: glm (retry after glm5 timeout) · Backend: nova · Model: zai.glm-4.7-flash · Attempts: 2 · Duration: 965s · Tokens: 2410760/10152 |
