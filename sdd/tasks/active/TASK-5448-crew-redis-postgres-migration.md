# TASK-5448: Implement verified Redis migration and dry-run reporting

**Feature**: FEAT-860 — Postgres CrewDefinition Storage
**Spec**: `sdd/specs/postgres-crew-storage.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2–4h)
**Depends-on**: TASK-5447
**Assigned-to**: unassigned

## Context

Implement the approved revision 0.2 contracts for implement verified redis migration and dry-run reporting.
Spec §§2–5 are authoritative; §6 records baseline source, not old error-policy requirements.
This task is part of the four review resolutions recorded in spec §9.

## Scope

- Use the composition and report from TASK-5447 — do not redefine its authority policy.
- Implement advisory locking, strict snapshots, targeted insert and re-read comparison — destructive cleanup must follow durable verification.
- Use delete_snapshot rather than unconditional delete_crew — only raw-state CAS protects intervening writes.
- Add dry-run and cancellation branches before side effects — direct dry-run cannot call schema-creating ping.
- Append migration tests to the existing module — serialize ownership and preserve routing regressions.

**NOT in scope**: files outside the table; changing CrewDefinition model fields, execution-result storage,
creation.sql, _load_database_bots, dependency manifests or introducing new services.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/handlers/crew/definition_storage.py` | MODIFY | Only the verified sweep may trigger conditional deletion; predecessor owns routing and report types. |
| `packages/ai-parrot-server/tests/unit/test_crew_definition_storage.py` | MODIFY | Append to the composition test module only after TASK-5447 completes; no overlapping writers. |

## Codebase Contract (Anti-Hallucination)

Verified at `0cfa595cb2` on `dev`; re-check after dependencies land.

### Verified Imports

```python
import pytest
from parrot.handlers.crew.models import CrewDefinition, AgentDefinition, FlowRelation, ToolNodeDefinition
from parrot.handlers.crew.redis_persistence import CrewRedis
```

Standard-library imports resolve under the project Python runtime; pytest/Pydantic/asyncdb are already declared in workspace pyproject.toml files. Crew model re-exports are verified in handlers/crew/models.py:17–23. Relative imports of new modules in blueprints are dependency contracts below, not claims of pre-existing code.

### Existing Signatures to Use

- `sym:packages/ai-parrot-server/src/parrot/handlers/crew/redis_persistence.py#CrewRedis` — `class CrewRedis:` (packages/ai-parrot-server/src/parrot/handlers/crew/redis_persistence.py:17).
- `sym:packages/ai-parrot/src/parrot/models/crew_definition.py#CrewDefinition` — `class CrewDefinition(BaseModel):` (packages/ai-parrot/src/parrot/models/crew_definition.py:178).
- `sym:packages/ai-parrot/src/parrot/models/crew_definition.py#AgentDefinition` — `class AgentDefinition(BaseModel):` (packages/ai-parrot/src/parrot/models/crew_definition.py:31).

### Dependency Imports and New Symbols

Consumes CrewDefinitionStorage/CrewMigrationReport from TASK-5447 and serializes modifications of definition_storage.py and test_crew_definition_storage.py.

Exact blueprint imports (stdlib/existing references above; new symbols require the named prerequisite):

```python

```
Blueprint imports from `definition_codec`, `postgres_persistence`, `definition_storage`, and new Redis types are permitted only after their producer task completes; inspect those exact declarations before implementation. New symbols defined by this task are declared in its blueprint.

### Does NOT Exist

- migrate_from_redis is intentionally not created by TASK-5447; this task adds it.
- No migration CLI or existing Redis-to-Postgres helper exists.

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-server/src/parrot/handlers/crew/definition_storage.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-server/tests/unit/test_crew_definition_storage.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-server/src/parrot/handlers/crew/redis_persistence.py#CrewRedis",
    "sym:packages/ai-parrot/src/parrot/models/crew_definition.py#CrewDefinition",
    "sym:packages/ai-parrot/src/parrot/models/crew_definition.py#AgentDefinition"
  ]
}
```

## Implementation Notes

Use async I/O, Pydantic v2 models, strict type hints and Google-style docstrings. Format with black (120 columns); lint with ruff. No new dependencies. Logs belong under artifacts/logs/.

## Implementation Blueprint

### Steps (in order)

1. Use the composition and report from TASK-5447 — do not redefine its authority policy.
2. Implement advisory locking, strict snapshots, targeted insert and re-read comparison — destructive cleanup must follow durable verification.
3. Use delete_snapshot rather than unconditional delete_crew — only raw-state CAS protects intervening writes.
4. Add dry-run and cancellation branches before side effects — direct dry-run cannot call schema-creating ping.
5. Append migration tests to the existing module — serialize ownership and preserve routing regressions.

### `packages/ai-parrot-server/src/parrot/handlers/crew/definition_storage.py` (MODIFY)

```python
# Dependency-created anchor: class CrewDefinitionStorage:
# Expected occurrences: 1; TASK-5447 creates it. Verify at execution after dependency lands.
# Add inside CrewDefinitionStorage:
async def migrate_from_redis(self, *, dry_run: bool = False) -> CrewMigrationReport:
    """Copy, verify and conditionally clean sources under one session advisory lock."""
    # FILL IN: spec section 2 steps 1-6; classify conflicts without deleting them.
    raise NotImplementedError
# Extend initialize() to call this only when configured, migration enabled and both pings pass.
# Dry-run direct calls must not route through ensure_schema/ping that applies DDL.
```

**Why**: Only the verified sweep may trigger conditional deletion; predecessor owns routing and report types.

### `packages/ai-parrot-server/tests/unit/test_crew_definition_storage.py` (MODIFY)

```python
# Dependency-created module: TASK-5447. Append unique tests; retain its routing coverage.
@pytest.mark.asyncio
async def test_migration_preserves_different_and_changed_sources() -> None:
    """Different authoritative documents and changed Redis snapshots remain intact."""
    # FILL IN: controlled interleaving and repeated sweep, per AC2/AC3.
    raise NotImplementedError

@pytest.mark.asyncio
async def test_dry_run_and_lock_failure_mutate_nothing() -> None:
    """No DDL/data mutation on dry run, held lock, or inventory failure."""
    # FILL IN: assert SQL/Redis mutation spies remain untouched, per AC4/AC5.
    raise NotImplementedError
```

**Why**: Append to the composition test module only after TASK-5447 completes; no overlapping writers.

### FILL IN checklist

- [ ] `packages/ai-parrot-server/src/parrot/handlers/crew/definition_storage.py` — complete the bounded logic described above; satisfy all task acceptance criteria and retain unrelated content.
- [ ] `packages/ai-parrot-server/tests/unit/test_crew_definition_storage.py` — complete the bounded logic described above; satisfy all task acceptance criteria and retain unrelated content.
- [ ] Replace all blueprint gaps with complete working code/tests; no placeholders in implementation files.

## Acceptance Criteria

- [ ] AC1: initialize invokes migration only after both pings; lock-not-acquired and precondition failures produce explicit report outcomes.
- [ ] AC2: Targeted insert ID collisions preserve Redis; existing differing rows and differing global legacy payloads stay as conflicts across reruns.
- [ ] AC3: Re-read PG and compare complete normalized documents excluding timestamps; only equal verified snapshots or tombstoned sources reach atomic delete_snapshot.
- [ ] AC4: Dry runs neither create schema nor mutate rows/Redis; missing schema reported; no inserted/migrated success for failed cleanup.
- [ ] AC5: Session lock released on failure/cancellation; cancellation propagates; per-crew failures isolated and inventory failure never becomes empty success.
- [ ] AC6: All four ledger scenarios map to regression cases: rejected outage writes, ID collisions, tombstones and concurrent cleanup.

## Validation Commands

- `pytest packages/ai-parrot-server/tests/unit/test_crew_definition_storage.py -q`

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
