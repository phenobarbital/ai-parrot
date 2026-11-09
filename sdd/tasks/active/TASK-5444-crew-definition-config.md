# TASK-5444: Add opt-in crew definition storage configuration

**Feature**: FEAT-860 — Postgres CrewDefinition Storage
**Spec**: `sdd/specs/postgres-crew-storage.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (1–2h)
**Depends-on**: none
**Assigned-to**: unassigned

## Context

Implement the approved revision 0.2 contracts for add opt-in crew definition storage configuration.
Spec §§2–5 are authoritative; §6 records baseline source, not old error-policy requirements.
This task is part of the four review resolutions recorded in spec §9.

## Scope

- Insert the three declarations at the verified result-storage boundary — keeps related settings discoverable.
- Test defaults and overrides using an isolated configuration harness — avoid reloading shared config with real secrets.

**NOT in scope**: files outside the table; changing CrewDefinition model fields, execution-result storage,
creation.sql, _load_database_bots, dependency manifests or introducing new services.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/conf.py` | MODIFY | Defaults keep Redis-only deployments unchanged and reuse the existing DSN resolution. |
| `packages/ai-parrot-server/tests/unit/test_crew_definition_config.py` | CREATE | Test isolated config evaluation with absent/present settings; never expose real DSNs. |

## Codebase Contract (Anti-Hallucination)

Verified at `0cfa595cb2` on `dev`; re-check after dependencies land.

### Verified Imports

```python
from parrot import conf
from navconfig import config
import pytest
```

Standard-library imports resolve under the project Python runtime; pytest/Pydantic/asyncdb are already declared in workspace pyproject.toml files. Crew model re-exports are verified in handlers/crew/models.py:17–23. Relative imports of new modules in blueprints are dependency contracts below, not claims of pre-existing code.

### Existing Signatures to Use

Configuration-only changes use existing `config` and `default_dsn` in conf.py.

### Dependency Imports and New Symbols

Independent configuration declarations in conf.py and isolated tests; no dependency on new storage classes.

Exact blueprint imports (stdlib/existing references above; new symbols require the named prerequisite):

```python
from __future__ import annotations
from parrot import conf
import pytest
```
Blueprint imports from `definition_codec`, `postgres_persistence`, `definition_storage`, and new Redis types are permitted only after their producer task completes; inspect those exact declarations before implementation. New symbols defined by this task are declared in its blueprint.

### Does NOT Exist

- CREW_DEFINITION_STORAGE, CREW_DEFINITION_PG_DSN, CREW_DEFINITION_MIGRATION are absent before this task.

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/conf.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-server/tests/unit/test_crew_definition_config.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": []
}
```

## Implementation Notes

Use async I/O, Pydantic v2 models, strict type hints and Google-style docstrings. Format with black (120 columns); lint with ruff. No new dependencies. Logs belong under artifacts/logs/.

## Implementation Blueprint

### Steps (in order)

1. Insert the three declarations at the verified result-storage boundary — keeps related settings discoverable.
2. Test defaults and overrides using an isolated configuration harness — avoid reloading shared config with real secrets.

### `packages/ai-parrot/src/parrot/conf.py` (MODIFY)

```python
# Anchor: CREW_RESULT_STORAGE_REDIS_TTL = int(config.get("CREW_RESULT_STORAGE_REDIS_TTL", fallback=604800))
# occurrences: 1; verified packages/ai-parrot/src/parrot/conf.py:316 at 0cfa595cb2
# AFTER the verified CREW_RESULT_STORAGE_REDIS_TTL anchor:
# Crew definition storage (FEAT-860)
CREW_DEFINITION_STORAGE = config.get("CREW_DEFINITION_STORAGE", fallback="redis")
CREW_DEFINITION_PG_DSN = config.get("CREW_DEFINITION_PG_DSN", fallback=default_dsn)
CREW_DEFINITION_MIGRATION = config.getboolean("CREW_DEFINITION_MIGRATION", fallback=False)
```

**Why**: Defaults keep Redis-only deployments unchanged and reuse the existing DSN resolution.

### `packages/ai-parrot-server/tests/unit/test_crew_definition_config.py` (CREATE)

```python
"""FEAT-860 regression tests; use isolated fakes unless explicitly live."""
from __future__ import annotations
import pytest
from parrot import conf

def test_default_backend_and_migration() -> None:
    """Assert the state transition specified in this task, including failures."""
    # FILL IN: arrange fixtures and assert outcomes per AC and Test Specification.
    raise NotImplementedError

def test_configured_values_and_dsn_fallback() -> None:
    """Assert the state transition specified in this task, including failures."""
    # FILL IN: arrange fixtures and assert outcomes per AC and Test Specification.
    raise NotImplementedError
```

**Why**: Test isolated config evaluation with absent/present settings; never expose real DSNs.

### FILL IN checklist

- [ ] `packages/ai-parrot/src/parrot/conf.py` — complete the bounded logic described above; satisfy all task acceptance criteria and retain unrelated content.
- [ ] `packages/ai-parrot-server/tests/unit/test_crew_definition_config.py` — complete the bounded logic described above; satisfy all task acceptance criteria and retain unrelated content.
- [ ] Replace all blueprint gaps with complete working code/tests; no placeholders in implementation files.

## Acceptance Criteria

- [ ] AC1: Three settings use the exact spec names and defaults.
- [ ] AC2: Explicit PG DSN wins over default_dsn; absent DSN remains None.
- [ ] AC3: Tests isolate environment/config reads and restore state; no live database or Redis used.

## Validation Commands

- `pytest packages/ai-parrot-server/tests/unit/test_crew_definition_config.py -q`

## Test Specification

Each test block above is an executor starting point, not an implementation. Build fixtures locally in the declared test files; do not modify shared conftest.py. Assert observable state and error behavior from every acceptance criterion. Avoid network/LLM calls except the explicitly gated live tests in TASK-5451.

## Agent Instructions

Implement in the feature worktree provisioned by sdd-start, never on dev. Check the dependency states
in `sdd/tasks/index/postgres-crew-storage.json` first. Verify source anchors and dependency-created APIs before editing.
Complete only declared files, run narrow validation commands, and commit scoped code. Finalize with
`parrot sdd task finalize` and real TaskCompletionEvidence for the implementation HEAD; do not manually
move the task, stamp completion, or run legacy task-close helpers.

## Completion Note

Pending; populated by the task finalizer after implementation and validation.
