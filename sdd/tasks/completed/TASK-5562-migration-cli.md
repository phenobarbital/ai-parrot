# TASK-5562: Migration CLI, DSN precedence and doctor wiring

**Feature**: FEAT-884 — Packaged PostgreSQL migrations
**Spec**: `sdd/specs/db-upgrade.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-5554, TASK-5555, TASK-5556, TASK-5563
**Assigned-to**: unassigned


---

## Context

Implement M5 Click verbs and lazy self registration. Add optional admin DSN, distinguish read-only and mutating precedence, append informational doctor results outside runtime-only scope.

---

## Scope

Implement M5 Click verbs and lazy self registration. Add optional admin DSN, distinguish read-only and mutating precedence, append informational doctor results outside runtime-only scope.

**NOT in scope**: application-model/loader refactors, Studio or task-memory migration ownership changes, new dependencies, production database execution. Implement only declared targets.

**Parallelism**: Consumes catalog selection/scaffold from TASK-5554, status from TASK-5555, upgrade/baseline from TASK-5556, and migration_doctor_check from TASK-5563. Owns self_/cli.py and its existing CLI tests exclusively.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/migrations/cli.py` | CREATE | Keep asyncpg and server imports out of help. Handle configuration failures as 3 and database failures as 2; Click parse errors for these migration options must conform to spec exit contract. |
| `packages/ai-parrot/src/parrot/conf.py` | MODIFY | Insert PARROT_ADMIN_DSN = config.get("PARROT_ADMIN_DSN") under Main Database; leave default_dsn construction unchanged. |
| `packages/ai-parrot/src/parrot/self_/cli.py` | MODIFY | Register lightweight migration subgroup before self = self_group, keeping imports lazy on execution. In doctor, directly after checks = run_doctor(resolved.root, scope=scope, install_root=resolved), append asyncio.run(migration_doctor_check(default_dsn)) only if not runtime_only. Leave synchronous run_doctor unchanged. Preserve all current commands. |
| `packages/ai-parrot/tests/self_/test_self_cli.py` | MODIFY | Extend registration expectation with migration; cover lazy help and informational doctor append/runtime-only exclusion. Mock checks/DSNs to prevent real network access. |
| `packages/ai-parrot/tests/migrations/test_cli.py` | CREATE | Four verbs/options after verb; default bots/repeated set/all conflict; unknown set with install hint; exact exits 0/1/2/3; DSN precedence with no credential leaks; positive timeouts; new no connection; lazy help without asyncpg/server; baseline explicit set/prefix and no force |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
import asyncio
import logging
from pathlib import Path
import click
from .models import MigrationConfigurationError
from parrot.conf import PARROT_ADMIN_DSN, default_dsn
from parrot.migrations.cli import migration_group
from parrot.migrations.startup import migration_doctor_check
import pytest
from click.testing import CliRunner
```

Standard-library imports are available on supported Python 3.11–3.13. Pydantic and Click are declared in core pyproject.toml at lines 54 and 149; asyncpg is already supplied through asyncdb (line 137). Pytest is the existing test runner. Relative/new `parrot.migrations` imports above are declared by this task or its dependencies, **not existing base-branch APIs**. Imports inside TYPE_CHECKING or callbacks must remain lazy where specified.

### Existing Signatures to Use

- `packages/ai-parrot/src/parrot/conf.py` — anchor at line 63, one exact occurrence: `# Main Database:`
- `packages/ai-parrot/src/parrot/self_/cli.py` — anchor at line 132, one exact occurrence: `self = self_group`
- `packages/ai-parrot/src/parrot/self_/doctor.py` — DoctorCheck line 39: name,ok,detail="",fix="",informational=False; run_doctor(root: Path, *, scope: DoctorScope="full", install_root: InstallRoot | None=None) -> list[DoctorCheck] line 766.
- `packages/ai-parrot/src/parrot/self_/doctor.py` — run_doctor is synchronous, never call asyncio.run within this reusable library.
- `packages/ai-parrot/tests/self_/test_self_cli.py` — anchor at line 13, one exact occurrence: `def test_self_is_registered() -> None:`

### Dependency interfaces

- `TASK-5554` creates the files/APIs described in its blueprint; read its completion and verify signatures before use.
- `TASK-5555` creates the files/APIs described in its blueprint; read its completion and verify signatures before use.
- `TASK-5556` creates the files/APIs described in its blueprint; read its completion and verify signatures before use.
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
      "path": "packages/ai-parrot/src/parrot/migrations/cli.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/src/parrot/conf.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/self_/cli.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/self_/test_self_cli.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/migrations/test_cli.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/self_/doctor.py#DoctorCheck",
    "sym:packages/ai-parrot/src/parrot/self_/doctor.py#run_doctor"
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

### `packages/ai-parrot/src/parrot/migrations/cli.py` (CREATE)

```python
"""Migration commands in the active Python environment."""
from __future__ import annotations
import asyncio
import logging
from pathlib import Path
import click
from .models import MigrationConfigurationError

logger = logging.getLogger(__name__)

@click.group(name="migration")
def migration_group() -> None:
    """Manage database schemas; self update updates software instead."""

def resolve_dsn(explicit: str | None, *, mutating: bool) -> str:
    """Resolve mode-specific precedence; configuration failures map to exit 3."""
    # FILL IN: explicit/admin/runtime for mutations, explicit/runtime for reads.

@migration_group.command(name="status")
@click.option("--set", "set_names", multiple=True)
@click.option("--all", "all_sets", is_flag=True)
@click.option("--dsn")
@click.option("--connect-timeout", type=float, default=5.0)
@click.option("--statement-timeout", type=float, default=60.0)
def status_command(set_names: tuple[str, ...], all_sets: bool, dsn: str | None,
                   connect_timeout: float, statement_timeout: float) -> None:
    """Report selected catalog and schema state without writes."""
    # FILL IN: local checks.status import, asyncio.run, safe output and exact exit codes.

@migration_group.command(name="upgrade")
@click.option("--set", "set_names", multiple=True)
@click.option("--all", "all_sets", is_flag=True)
@click.option("--dsn")
@click.option("--fail-fast", is_flag=True)
@click.option("--reapply-changed", is_flag=True)
@click.option("--connect-timeout", type=float, default=5.0)
@click.option("--lock-timeout", type=float, default=30.0)
@click.option("--statement-timeout", type=float, default=60.0)
def upgrade_command(set_names: tuple[str, ...], all_sets: bool, dsn: str | None,
                    fail_fast: bool, reapply_changed: bool, connect_timeout: float,
                    lock_timeout: float, statement_timeout: float) -> None:
    """Apply pending files; changed files require explicit repair."""
    # FILL IN: local runner.upgrade import and spec §2 precedence/exit mapping.

@migration_group.command(name="baseline")
@click.option("--set", "set_name", required=True)
@click.option("--through", type=int, required=True)
@click.option("--dsn")
@click.option("--connect-timeout", type=float, default=5.0)
@click.option("--lock-timeout", type=float, default=30.0)
@click.option("--statement-timeout", type=float, default=60.0)
def baseline_command(set_name: str, through: int, dsn: str | None,
                     connect_timeout: float, lock_timeout: float, statement_timeout: float) -> None:
    """Verify and record one explicit prefix without executing bodies."""
    # FILL IN: local runner.baseline import; reject repeated sets and invalid prefixes.

@migration_group.command(name="new")
@click.argument("set_name")
@click.argument("name")
@click.option("--directory", type=click.Path(path_type=Path), required=True)
@click.option("--dsn")
def new_command(set_name: str, name: str, directory: Path, dsn: str | None) -> None:
    """Create a source body/check pair locally; dsn is accepted but unused."""
    # FILL IN: local catalog.scaffold import; no connection; report partial creation safely.

# FILL IN: common safe configuration mapping (exit 3), positive-timeout checks,
# default bots/selection conflicts, exact status/upgrade exits, selected targets and ledger.
# Handle Click argument/option configuration failures as 3 per spec, without tracebacks.
```

**Why**: Keep asyncpg and server imports out of help. Handle configuration failures as 3 and database failures as 2; Click parse errors for these migration options must conform to spec exit contract.

---

### `packages/ai-parrot/src/parrot/conf.py` (MODIFY)

```python
# Anchor (exact full line): # Main Database:
# occurrences: 1; verified at packages/ai-parrot/src/parrot/conf.py:63
# FILL IN: Insert PARROT_ADMIN_DSN = config.get("PARROT_ADMIN_DSN") under Main Database; leave default_dsn construction unchanged.
```

**Why**: Insert PARROT_ADMIN_DSN = config.get("PARROT_ADMIN_DSN") under Main Database; leave default_dsn construction unchanged.

---

### `packages/ai-parrot/src/parrot/self_/cli.py` (MODIFY)

```python
# Anchor: self = self_group; occurrences: 1, verified self_/cli.py:132.
# BEFORE that anchor, register the lazy subgroup:
class _MigrationGroup(click.Group):
    """Defer migration implementation imports until subgroup dispatch."""

    def list_commands(self, ctx: click.Context) -> list[str]:
        """List commands without importing the database driver or server."""
        return ["baseline", "new", "status", "upgrade"]

    def get_command(self, ctx: click.Context, cmd_name: str) -> click.Command | None:
        """Resolve a lightweight command adapter when requested."""
        from parrot.migrations.cli import migration_group
        return migration_group.get_command(ctx, cmd_name)

@self_group.group(name="migration", cls=_MigrationGroup)
def migration() -> None:
    """Manage packaged PostgreSQL schemas in this Python environment."""

# Additional anchor: checks = run_doctor(resolved.root, scope=scope, install_root=resolved)
# occurrences: 1; verified self_/cli.py:74 (retain indentation inside doctor).
# AFTER that call:
    if not runtime_only:
        import asyncio
        from parrot.conf import default_dsn
        from parrot.migrations.startup import migration_doctor_check
        checks.append(asyncio.run(migration_doctor_check(default_dsn)))
```

**Why**: Register lightweight migration subgroup before self = self_group, keeping imports lazy on execution. In doctor, directly after checks = run_doctor(resolved.root, scope=scope, install_root=resolved), append asyncio.run(migration_doctor_check(default_dsn)) only if not runtime_only. Leave synchronous run_doctor unchanged. Preserve all current commands.

---

### `packages/ai-parrot/tests/self_/test_self_cli.py` (MODIFY)

```python
# Anchor (exact full line): def test_self_is_registered() -> None:
# occurrences: 1; verified at packages/ai-parrot/tests/self_/test_self_cli.py:13
# FILL IN: Extend registration expectation with migration; cover lazy help and informational doctor append/runtime-only exclusion. Mock checks/DSNs to prevent real network access.
```

**Why**: Extend registration expectation with migration; cover lazy help and informational doctor append/runtime-only exclusion. Mock checks/DSNs to prevent real network access.

---

### `packages/ai-parrot/tests/migrations/test_cli.py` (CREATE)

```python
"""Four verbs/options after verb."""
from __future__ import annotations

import pytest
from click.testing import CliRunner
from parrot.migrations.cli import migration_group


def test_cli_contract() -> None:
    """Verify the behavioral matrix listed in this task."""
    # FILL IN: replace this starting test with parameterized cases and fixtures
    # bounded by the Test Specification; assert observable outcomes, not implementation details.
    pytest.fail("Complete the behavioral matrix before finalizing this task")
```

**Why**: Four verbs/options after verb; default bots/repeated set/all conflict; unknown set with install hint; exact exits 0/1/2/3; DSN precedence with no credential leaks; positive timeouts; new no connection; lazy help without asyncpg/server; baseline explicit set/prefix and no force

---

### FILL IN checklist

- [ ] `packages/ai-parrot/src/parrot/migrations/cli.py` — Keep asyncpg and server imports out of help. Handle configuration failures as 3 and database failures as 2; Click parse errors for these migration options must conform to spec exit contract.
- [ ] `packages/ai-parrot/src/parrot/conf.py` — Insert PARROT_ADMIN_DSN = config.get("PARROT_ADMIN_DSN") under Main Database; leave default_dsn construction unchanged.
- [ ] `packages/ai-parrot/src/parrot/self_/cli.py` — Register lightweight migration subgroup before self = self_group, keeping imports lazy on execution. In doctor, directly after checks = run_doctor(resolved.root, scope=scope, install_root=resolved), append asyncio.run(migration_doctor_check(default_dsn)) only if not runtime_only. Leave synchronous run_doctor unchanged. Preserve all current commands.
- [ ] `packages/ai-parrot/tests/self_/test_self_cli.py` — Extend registration expectation with migration; cover lazy help and informational doctor append/runtime-only exclusion. Mock checks/DSNs to prevent real network access.
- [ ] `packages/ai-parrot/tests/migrations/test_cli.py` — Four verbs/options after verb; default bots/repeated set/all conflict; unknown set with install hint; exact exits 0/1/2/3; DSN precedence with no credential leaks; positive timeouts; new no connection; lazy help without asyncpg/server; baseline explicit set/prefix and no force
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

- `pytest packages/ai-parrot/tests/migrations/test_cli.py -q`
- `pytest packages/ai-parrot/tests/self_/test_self_cli.py -q`

---

## Test Specification

- Extend registration expectation with migration; cover lazy help and informational doctor append/runtime-only exclusion. Mock checks/DSNs to prevent real network access.
- Four verbs/options after verb; default bots/repeated set/all conflict; unknown set with install hint; exact exits 0/1/2/3; DSN precedence with no credential leaks; positive timeouts; new no connection; lazy help without asyncpg/server; baseline explicit set/prefix and no force

---

## Agent Instructions

1. Use `$sdd-start TASK-5562` to provision the feature worktree; do not implement on dev.
2. Read the full spec and confirm predecessor tasks are done.
3. Reverify existing anchors and new dependency signatures before implementing.
4. Complete the blueprint within its acceptance criteria, then run the task validation commands.
5. Commit only declared implementation files and finalize with `parrot sdd task finalize` using real TaskCompletionEvidence and the implementation HEAD; it owns Completion Note and active-to-completed movement.

## Completion Note


- Task: TASK-5562
- Feature: db-upgrade
- Implementation SHA: a6f8d4580b422a5fff5ae4468e2116a1a3657109
- Closed at (UTC): 2026-11-13T00:17:47+00:00
- Fix commits: none

| Metric | Value |
|---|---|
| validation_refs | 1 |
| fix_commits | 0 |
| seat_summary | Seat: gpt-5.6-sol · Backend: codex · Model: gpt-5.6-sol · Attempts: 1 · Duration: 375s · Tokens: n/a |
