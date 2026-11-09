# TASK-5451: Validate Postgres constraints and Redis migration races live

**Feature**: FEAT-860 — Postgres CrewDefinition Storage
**Spec**: `sdd/specs/postgres-crew-storage.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2–4h)
**Depends-on**: TASK-5448
**Assigned-to**: unassigned

## Context

Implement the approved revision 0.2 contracts for validate postgres constraints and redis migration races live.
Spec §§2–5 are authoritative; §6 records baseline source, not old error-policy requirements.
This task is part of the four review resolutions recorded in spec §9.

## Scope

- Build per-test disposable identities and explicit environment gates — accidental production cleanup is unacceptable.
- Exercise SQL against PG and Lua against Redis — mocks cannot validate atomicity or constraint selection.
- Use asyncio.Event barriers and compare persisted values before/after failure — timing sleeps do not reproduce the race deterministically.
- Capture logs under artifacts/logs and disclose skipped checks — do not fabricate live validation.

**NOT in scope**: files outside the table; changing CrewDefinition model fields, execution-result storage,
creation.sql, _load_database_bots, dependency manifests or introducing new services.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/tests/handlers/test_crew_postgres_store_live.py` | CREATE | Module skipif NAVIGATOR_PG_DSN absent; unique fixture tenant; cleanup rows only, never drop shared schema/table. |
| `packages/ai-parrot-server/tests/handlers/test_crew_migration_live.py` | CREATE | Require both NAVIGATOR_PG_DSN and explicit disposable CREW_MIGRATION_TEST_REDIS_URL; unique tenant/key prefix; no FLUSHDB. |

## Codebase Contract (Anti-Hallucination)

Verified at `0cfa595cb2` on `dev`; re-check after dependencies land.

### Verified Imports

```python
import pytest
import os
import uuid
import asyncio
from asyncdb import AsyncDB
from parrot.handlers.crew.models import CrewDefinition, AgentDefinition, FlowRelation, ToolNodeDefinition
```

Standard-library imports resolve under the project Python runtime; pytest/Pydantic/asyncdb are already declared in workspace pyproject.toml files. Crew model re-exports are verified in handlers/crew/models.py:17–23. Relative imports of new modules in blueprints are dependency contracts below, not claims of pre-existing code.

### Existing Signatures to Use

- `sym:packages/ai-parrot/src/parrot/models/crew_definition.py#CrewDefinition` — `class CrewDefinition(BaseModel):` (packages/ai-parrot/src/parrot/models/crew_definition.py:178).
- `sym:packages/ai-parrot/src/parrot/models/crew_definition.py#AgentDefinition` — `class AgentDefinition(BaseModel):` (packages/ai-parrot/src/parrot/models/crew_definition.py:31).
- `sym:packages/ai-parrot-server/src/parrot/handlers/models/ui_surfaces.py#PgUISurfaceStore` — `class PgUISurfaceStore:` (packages/ai-parrot-server/src/parrot/handlers/models/ui_surfaces.py:457).

### Dependency Imports and New Symbols

Consumes complete migrate_from_redis and reports from TASK-5448. Exclusive: live ensure_schema applies shared navigator DDL outside declared files.

Exact blueprint imports (stdlib/existing references above; new symbols require the named prerequisite):

```python
from __future__ import annotations
from asyncdb import AsyncDB
from parrot.handlers.crew.definition_storage import CrewDefinitionStorage
from parrot.handlers.crew.models import CrewDefinition, AgentDefinition, FlowRelation, ToolNodeDefinition
from parrot.handlers.crew.postgres_persistence import CrewPostgres
from parrot.handlers.crew.redis_persistence import CrewRedis
import asyncio
import os
import pytest
import uuid
```
Blueprint imports from `definition_codec`, `postgres_persistence`, `definition_storage`, and new Redis types are permitted only after their producer task completes; inspect those exact declarations before implementation. New symbols defined by this task are declared in its blueprint.

### Does NOT Exist

- No live crew-definition tests exist yet.
- No automatic service provisioning or shared Redis flush is authorized.

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-server/tests/handlers/test_crew_postgres_store_live.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-server/tests/handlers/test_crew_migration_live.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/models/crew_definition.py#CrewDefinition",
    "sym:packages/ai-parrot/src/parrot/models/crew_definition.py#AgentDefinition",
    "sym:packages/ai-parrot-server/src/parrot/handlers/models/ui_surfaces.py#PgUISurfaceStore"
  ]
}
```

## Implementation Notes

Use async I/O, Pydantic v2 models, strict type hints and Google-style docstrings. Format with black (120 columns); lint with ruff. No new dependencies. Logs belong under artifacts/logs/.

## Implementation Blueprint

### Steps (in order)

1. Build per-test disposable identities and explicit environment gates — accidental production cleanup is unacceptable.
2. Exercise SQL against PG and Lua against Redis — mocks cannot validate atomicity or constraint selection.
3. Use asyncio.Event barriers and compare persisted values before/after failure — timing sleeps do not reproduce the race deterministically.
4. Capture logs under artifacts/logs and disclose skipped checks — do not fabricate live validation.

### `packages/ai-parrot-server/tests/handlers/test_crew_postgres_store_live.py` (CREATE)

```python
"""FEAT-860 regression tests; use isolated fakes unless explicitly live."""
from __future__ import annotations
import pytest
import os
import uuid
from asyncdb import AsyncDB
from parrot.handlers.crew.postgres_persistence import CrewPostgres
from parrot.handlers.crew.models import CrewDefinition, AgentDefinition, FlowRelation, ToolNodeDefinition

@pytest.mark.asyncio
async def test_live_round_trip_tombstone_and_id_collision() -> None:
    """Assert the state transition specified in this task, including failures."""
    # FILL IN: arrange fixtures and assert outcomes per AC and Test Specification.
    raise NotImplementedError

@pytest.mark.asyncio
async def test_live_lock_exclusion_and_release() -> None:
    """Assert the state transition specified in this task, including failures."""
    # FILL IN: arrange fixtures and assert outcomes per AC and Test Specification.
    raise NotImplementedError
```

**Why**: Module skipif NAVIGATOR_PG_DSN absent; unique fixture tenant; cleanup rows only, never drop shared schema/table.

### `packages/ai-parrot-server/tests/handlers/test_crew_migration_live.py` (CREATE)

```python
"""FEAT-860 regression tests; use isolated fakes unless explicitly live."""
from __future__ import annotations
import pytest
import asyncio
import os
import uuid
from parrot.handlers.crew.redis_persistence import CrewRedis
from parrot.handlers.crew.postgres_persistence import CrewPostgres
from parrot.handlers.crew.definition_storage import CrewDefinitionStorage
from parrot.handlers.crew.models import CrewDefinition, AgentDefinition, FlowRelation, ToolNodeDefinition

@pytest.mark.asyncio
async def test_live_changed_redis_snapshot_is_preserved() -> None:
    """Assert the state transition specified in this task, including failures."""
    # FILL IN: arrange fixtures and assert outcomes per AC and Test Specification.
    raise NotImplementedError

@pytest.mark.asyncio
async def test_live_legacy_and_reassigned_mapping_survive() -> None:
    """Assert the state transition specified in this task, including failures."""
    # FILL IN: arrange fixtures and assert outcomes per AC and Test Specification.
    raise NotImplementedError

@pytest.mark.asyncio
async def test_live_rerun_dry_run_and_conflicts() -> None:
    """Assert the state transition specified in this task, including failures."""
    # FILL IN: arrange fixtures and assert outcomes per AC and Test Specification.
    raise NotImplementedError
```

**Why**: Require both NAVIGATOR_PG_DSN and explicit disposable CREW_MIGRATION_TEST_REDIS_URL; unique tenant/key prefix; no FLUSHDB.

### FILL IN checklist

- [ ] `packages/ai-parrot-server/tests/handlers/test_crew_postgres_store_live.py` — complete the bounded logic described above; satisfy all task acceptance criteria and retain unrelated content.
- [ ] `packages/ai-parrot-server/tests/handlers/test_crew_migration_live.py` — complete the bounded logic described above; satisfy all task acceptance criteria and retain unrelated content.
- [ ] Replace all blueprint gaps with complete working code/tests; no placeholders in implementation files.

## Acceptance Criteria

- [ ] AC1: Real PG verifies two uniqueness constraints, name-targeted conflict, timestamp/JSONB round trip, tombstones and lock lifecycle.
- [ ] AC2: Real Redis Lua runs with event barriers (no sleeps) to interleave a write between snapshot and cleanup; changed data/indexes survive.
- [ ] AC3: Cover global legacy key appearance/change, mapping reassignment, differing conflict reruns and dry-run nonmutation.
- [ ] AC4: Fixtures close resources and remove only owned rows/keys even on failure; skipped services are explicitly reported.
- [ ] AC5: Production migration remains blocked until actual live evidence exists; skipped tests are not proof of safety.

## Validation Commands

- `pytest packages/ai-parrot-server/tests/handlers/test_crew_postgres_store_live.py packages/ai-parrot-server/tests/handlers/test_crew_migration_live.py -q`

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
