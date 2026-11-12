# TASK-5554: Migration catalog, immutable models and core provider

**Feature**: FEAT-884 — Packaged PostgreSQL migrations
**Spec**: `sdd/specs/db-upgrade.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned


---

## Context

Implement M1: immutable models, sorted entry-point discovery, exact-byte checksums, validated paired resources, token rendering and exclusive local scaffolding. Add the core provider and packaging registration. No database connection or server import is permitted during discovery/help.

---

## Scope

Implement M1: immutable models, sorted entry-point discovery, exact-byte checksums, validated paired resources, token rendering and exclusive local scaffolding. Add the core provider and packaging registration. No database connection or server import is permitted during discovery/help.

**NOT in scope**: application-model/loader refactors, Studio or task-memory migration ownership changes, new dependencies, production database execution. Implement only declared targets.

**Parallelism**: Exclusive: edits packages/ai-parrot/pyproject.toml, a shared distribution manifest. No predecessor symbols are required.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/migrations/models.py` | CREATE | Freeze all four models; keep every field/type from spec M1; error/report payloads must never hold driver exceptions or secrets. |
| `packages/ai-parrot/src/parrot/migrations/__init__.py` | CREATE | Keep import-time behavior lightweight; do not import runner, asyncpg or server modules. |
| `packages/ai-parrot/src/parrot/migrations/providers.py` | CREATE | Resolve configuration lazily; validation belongs in catalog before any connection. |
| `packages/ai-parrot/src/parrot/migrations/catalog.py` | CREATE | Use importlib.resources, not repository-relative paths. Missing required providers are configuration errors. SQL token contexts must be documented for downstream authors. |
| `packages/ai-parrot/pyproject.toml` | MODIFY | Add [project.entry-points."parrot.migrations"] bots = "parrot.migrations.providers:bots_set" as its own TOML table, and "parrot.migrations" = ["sql/*/*.sql"] under the existing package-data table. Do not add dependencies or change uv.lock. |
| `packages/ai-parrot/tests/migrations/test_catalog.py` | CREATE | Discovery ordering/duplicates/provider name mismatch; missing resources/UTF-8/sequence gaps/orphan checks; immutable models and exact byte hashes; JSON braces unchanged and bad identifiers rejected; scaffolding max+1/traversal/no overwrite/partial pair failure/no DB contact |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from typing import Literal
from pydantic import BaseModel, ConfigDict
from hashlib import sha256
from importlib import metadata, resources
from pathlib import Path
import re
from parrot.conf import PARROT_SCHEMA, PARROT_BOTS_TABLE
from .models import MigrationConfigurationError, MigrationFile, MigrationSet
from .models import MigrationSet
import pytest
from parrot.migrations.catalog import discover_sets, load_migrations, render_sql, scaffold
```

Standard-library imports are available on supported Python 3.11–3.13. Pydantic and Click are declared in core pyproject.toml at lines 54 and 149; asyncpg is already supplied through asyncdb (line 137). Pytest is the existing test runner. Relative/new `parrot.migrations` imports above are declared by this task or its dependencies, **not existing base-branch APIs**. Imports inside TYPE_CHECKING or callbacks must remain lazy where specified.

### Existing Signatures to Use

- `packages/ai-parrot/pyproject.toml` — anchor at line 1010, one exact occurrence: `[tool.setuptools.package-data]`
- `packages/ai-parrot/src/parrot/conf.py` — PARROT_BOTS_TABLE line 121, PARROT_SCHEMA line 122; lazily read only.

### Dependency interfaces



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
      "path": "packages/ai-parrot/src/parrot/migrations/models.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/src/parrot/migrations/__init__.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/src/parrot/migrations/providers.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/src/parrot/migrations/catalog.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/pyproject.toml",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/migrations/test_catalog.py",
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

### `packages/ai-parrot/src/parrot/migrations/models.py` (CREATE)

```python
"""Immutable migration metadata and safe reports."""
from typing import Literal
from pydantic import BaseModel, ConfigDict

class MigrationConfigurationError(ValueError):
    """Invalid migration configuration; CLI exit code 3."""

class MigrationSet(BaseModel):
    """Resource owner: name, package, resource_dir, and tuple of qualified target tables."""
    model_config = ConfigDict(frozen=True)
    name: str
    package: str
    resource_dir: str
    tables: tuple[str, ...]

class MigrationFile(BaseModel):
    """Loaded immutable body/check pair with SHA256 values and sequence."""
    model_config = ConfigDict(frozen=True)
    migration_set: str
    filename: str
    sequence: int
    sql: str
    check_sql: str
    checksum: str
    check_checksum: str

class MigrationItem(BaseModel):
    """One file's APPLIED/PENDING/CHANGED state, postcondition result and safe diagnostic."""
    model_config = ConfigDict(frozen=True)
    migration_set: str
    filename: str
    state: Literal["APPLIED", "PENDING", "CHANGED"]
    postcondition_ok: bool | None
    diagnostic: str | None

class MigrationReport(BaseModel):
    """Safe structured result; never stores credentials or raw driver errors."""
    model_config = ConfigDict(frozen=True)
    items: list[MigrationItem]
    applied: list[str]
    failed: list[str]
    skipped: list[str]
    diagnostics: list[str]
    exit_code: Literal[0, 1, 2, 3]
```

**Why**: Freeze all four models; keep every field/type from spec M1; error/report payloads must never hold driver exceptions or secrets.

---

### `packages/ai-parrot/src/parrot/migrations/__init__.py` (CREATE)

```python
"""Packaged PostgreSQL migrations; importing this package performs no database I/O."""
```

**Why**: Keep import-time behavior lightweight; do not import runner, asyncpg or server modules.

---

### `packages/ai-parrot/src/parrot/migrations/providers.py` (CREATE)

```python
"""Core distribution migration metadata."""
from .models import MigrationSet


def bots_set() -> MigrationSet:
    """Resolve configured bots ownership without importing application models."""
    from parrot.conf import PARROT_SCHEMA, PARROT_BOTS_TABLE
    return MigrationSet(name="bots", package="parrot.migrations", resource_dir="sql/bots",
                        tables=(f"{PARROT_SCHEMA}.{PARROT_BOTS_TABLE}",))
```

**Why**: Resolve configuration lazily; validation belongs in catalog before any connection.

---

### `packages/ai-parrot/src/parrot/migrations/catalog.py` (CREATE)

```python
"""Deterministic migration discovery, loading, rendering and local authoring."""
from __future__ import annotations

from hashlib import sha256
from importlib import metadata, resources
from pathlib import Path
import re

from .models import MigrationConfigurationError, MigrationFile, MigrationSet


def discover_sets() -> tuple[MigrationSet, ...]:
    """Load sorted parrot.migrations entry points; reject ambiguous providers."""
    # FILL IN: enforce spec §2 discovery rules and entry-point-name equality.


def load_migrations(migration_set: MigrationSet) -> tuple[MigrationFile, ...]:
    """Validate contiguous body/check pairs and checksum their exact UTF-8 bytes."""
    # FILL IN: reject gaps, duplicates, orphan checks, missing resources and bad encoding.


def render_sql(sql: str, *, schema: str, bots_table: str) -> str:
    """Replace exact configured identifier tokens while preserving JSON braces."""
    # FILL IN: enforce [a-z_][a-z0-9_]{0,62}; use token-specific quoted identifier/literal contexts.


def scaffold(set_name: str, name: str, *, directory: Path) -> tuple[Path, Path]:
    """Exclusively create the next body/check pair in an explicit source directory."""
    # FILL IN: validate names/directory, allocate max+1; x-mode creates, never overwrite.
    # Body: descriptive comment. Check: SELECT FALSE plus authoring guidance.
    # Retain a partial pair and report its paths safely if the second create fails.
```

**Why**: Use importlib.resources, not repository-relative paths. Missing required providers are configuration errors. SQL token contexts must be documented for downstream authors.

---

### `packages/ai-parrot/pyproject.toml` (MODIFY)

```toml
# Anchor (exact full line): [tool.setuptools.package-data]
# occurrences: 1; verified at packages/ai-parrot/pyproject.toml:1010
# FILL IN: Add [project.entry-points."parrot.migrations"] bots = "parrot.migrations.providers:bots_set" as its own TOML table, and "parrot.migrations" = ["sql/*/*.sql"] under the existing package-data table. Do not add dependencies or change uv.lock.
```

**Why**: Add [project.entry-points."parrot.migrations"] bots = "parrot.migrations.providers:bots_set" as its own TOML table, and "parrot.migrations" = ["sql/*/*.sql"] under the existing package-data table. Do not add dependencies or change uv.lock.

---

### `packages/ai-parrot/tests/migrations/test_catalog.py` (CREATE)

```python
"""Discovery ordering/duplicates/provider name mismatch."""
from __future__ import annotations

import pytest
from parrot.migrations.catalog import discover_sets, load_migrations, render_sql, scaffold


def test_catalog_contract() -> None:
    """Verify the behavioral matrix listed in this task."""
    # FILL IN: replace this starting test with parameterized cases and fixtures
    # bounded by the Test Specification; assert observable outcomes, not implementation details.
    pytest.fail("Complete the behavioral matrix before finalizing this task")
```

**Why**: Discovery ordering/duplicates/provider name mismatch; missing resources/UTF-8/sequence gaps/orphan checks; immutable models and exact byte hashes; JSON braces unchanged and bad identifiers rejected; scaffolding max+1/traversal/no overwrite/partial pair failure/no DB contact

---

### FILL IN checklist

- [ ] `packages/ai-parrot/src/parrot/migrations/models.py` — Freeze all four models; keep every field/type from spec M1; error/report payloads must never hold driver exceptions or secrets.
- [ ] `packages/ai-parrot/src/parrot/migrations/__init__.py` — Keep import-time behavior lightweight; do not import runner, asyncpg or server modules.
- [ ] `packages/ai-parrot/src/parrot/migrations/providers.py` — Resolve configuration lazily; validation belongs in catalog before any connection.
- [ ] `packages/ai-parrot/src/parrot/migrations/catalog.py` — Use importlib.resources, not repository-relative paths. Missing required providers are configuration errors. SQL token contexts must be documented for downstream authors.
- [ ] `packages/ai-parrot/pyproject.toml` — Add [project.entry-points."parrot.migrations"] bots = "parrot.migrations.providers:bots_set" as its own TOML table, and "parrot.migrations" = ["sql/*/*.sql"] under the existing package-data table. Do not add dependencies or change uv.lock.
- [ ] `packages/ai-parrot/tests/migrations/test_catalog.py` — Discovery ordering/duplicates/provider name mismatch; missing resources/UTF-8/sequence gaps/orphan checks; immutable models and exact byte hashes; JSON braces unchanged and bad identifiers rejected; scaffolding max+1/traversal/no overwrite/partial pair failure/no DB contact
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

- `pytest packages/ai-parrot/tests/migrations/test_catalog.py -q`

---

## Test Specification

- Discovery ordering/duplicates/provider name mismatch; missing resources/UTF-8/sequence gaps/orphan checks; immutable models and exact byte hashes; JSON braces unchanged and bad identifiers rejected; scaffolding max+1/traversal/no overwrite/partial pair failure/no DB contact

---

## Agent Instructions

1. Use `$sdd-start TASK-5554` to provision the feature worktree; do not implement on dev.
2. Read the full spec and confirm predecessor tasks are done.
3. Reverify existing anchors and new dependency signatures before implementing.
4. Complete the blueprint within its acceptance criteria, then run the task validation commands.
5. Commit only declared implementation files and finalize with `parrot sdd task finalize` using real TaskCompletionEvidence and the implementation HEAD; it owns Completion Note and active-to-completed movement.

## Completion Note

Populated by the task finalizer after verified implementation.
