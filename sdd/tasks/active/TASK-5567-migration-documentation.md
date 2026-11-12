# TASK-5567: Documentation — wiki/deployment/database-migrations.md

**Feature**: FEAT-884 — Packaged PostgreSQL migrations
**Spec**: `sdd/specs/db-upgrade.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-5559, TASK-5561, TASK-5562, TASK-5563
**Assigned-to**: unassigned


---

## Context

Create the required operator/API wiki page from sdd/templates/techwiki-page.md, covering every topic in spec §10 with runnable command shapes and honest adoption limits.

---

## Scope

Create the required operator/API wiki page from sdd/templates/techwiki-page.md, covering every topic in spec §10 with runnable command shapes and honest adoption limits.

**NOT in scope**: application-model/loader refactors, Studio or task-memory migration ownership changes, new dependencies, production database execution. Implement only declared targets.

**Parallelism**: Consumes preserved manual operations from TASK-5559, complete optional set inventory from TASK-5561, CLI/DSN/doctor wiring from TASK-5562, and bounded probe behavior from TASK-5563. These paths transitively depend on all documented catalog/runner/check symbols.

---

The maintainer approved using a scoped pytest wrapper for the required techwiki command on 2026-11-13. The wrapper creates no documentation and propagates checker failures.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/tests/migrations/test_documentation.py` | CREATE | Invoke the required techwiki check and fail on a nonzero result. |
| `wiki/deployment/database-migrations.md` | CREATE | Fill the template sections with spec §10 coverage; link real API symbols and existing related pages, not invented commands. |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from pathlib import Path
import subprocess
```

Standard-library imports are available on supported Python 3.11–3.13. Pydantic and Click are declared in core pyproject.toml at lines 54 and 149; asyncpg is already supplied through asyncdb (line 137). Pytest is the existing test runner. Relative/new `parrot.migrations` imports above are declared by this task or its dependencies, **not existing base-branch APIs**. Imports inside TYPE_CHECKING or callbacks must remain lazy where specified.

### Existing Signatures to Use

- `sdd/templates/techwiki-page.md` — Required frontmatter and six section headings, ref: API links.

### Dependency interfaces

- `TASK-5559` creates the files/APIs described in its blueprint; read its completion and verify signatures before use.
- `TASK-5561` creates the files/APIs described in its blueprint; read its completion and verify signatures before use.
- `TASK-5562` creates the files/APIs described in its blueprint; read its completion and verify signatures before use.
- `TASK-5563` creates the files/APIs described in its blueprint; read its completion and verify signatures before use.

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
      "path": "wiki/deployment/database-migrations.md",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/tests/migrations/test_documentation.py",
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

### `wiki/deployment/database-migrations.md` (CREATE)

```markdown
---
title: PostgreSQL database migrations
summary: Deploy and verify packaged schemas, adopt existing databases, and keep migration ownership explicit.
---

# PostgreSQL database migrations

## Purpose

## Public API

- [Catalog](ref:parrot.migrations.catalog)
- [Runner](ref:parrot.migrations.runner)
- [Read-only checks](ref:parrot.migrations.checks)

## Configuration & Parameters

## Usage Examples

## Gotchas

## Related
```

**Why**: Fill the template sections with spec §10 coverage; link real API symbols and existing related pages, not invented commands.

---

### `packages/ai-parrot/tests/migrations/test_documentation.py` (CREATE)

```python
"""Validate the database migration operator guide through the required CLI."""
from pathlib import Path
import subprocess


def test_database_migrations_techwiki() -> None:
    """Require the spec-scoped techwiki check to succeed in this checkout."""
    root = Path(__file__).resolve().parents[4]
    result = subprocess.run(
        [
            "parrot", "sdd", "techwiki", "check",
            "--spec", "sdd/specs/db-upgrade.spec.md", "--root", ".",
        ],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
```

**Why**: The registered pytest runner executes the exact required techwiki command. Missing executables, timeouts and checker failures fail validation rather than skip. Run with the activated project environment.

### FILL IN checklist

- [ ] `wiki/deployment/database-migrations.md` — Fill the template sections with spec §10 coverage; link real API symbols and existing related pages, not invented commands.
- [ ] `packages/ai-parrot/tests/migrations/test_documentation.py` — retain the exact spec-scoped command and assert successful completion.
- [ ] Replace all planning markers with complete working code/tests; no placeholders may remain in implementation files.

---

## Acceptance Criteria

- [ ] Page follows the techwiki template and documents every topic listed in spec §10.
- [ ] API links resolve against catalog, runner and checks after their dependencies land.
- [ ] Examples match exact verbs/options/exits and distinguish bots, optional stores, Studio and task memory.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/migrations/test_documentation.py -q`

---

## Test Specification

- Verify deployment order (backup/stop writers/upgrade/status/restart), DSN roles/grants, active environment, default bots/explicit optional sets, separate crew DSN, fresh/partial adoption, baseline limits, changed-file repair, authoring/scaffolding/wheels, manual split operations and independent Studio/task-memory ownership.
- The pytest wrapper must execute `parrot sdd techwiki check --spec sdd/specs/db-upgrade.spec.md --root .`; it must fail on nonzero exit, timeout or missing CLI. No new runner registration is required.

---

## Agent Instructions

1. Use `$sdd-start TASK-5567` to provision the feature worktree; do not implement on dev.
2. Read the full spec and confirm predecessor tasks are done.
3. Reverify existing anchors and new dependency signatures before implementing.
4. Complete the blueprint within its acceptance criteria, then run the task validation commands.
5. Commit only declared implementation files and finalize with `parrot sdd task finalize` using real TaskCompletionEvidence and the implementation HEAD; it owns Completion Note and active-to-completed movement.

## Completion Note

Populated by the task finalizer after verified implementation.
