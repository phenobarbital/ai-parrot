# TASK-5447: Implement authoritative storage routing and deletion resolution

**Feature**: FEAT-860 — Postgres CrewDefinition Storage
**Spec**: `sdd/specs/postgres-crew-storage.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2–4h)
**Depends-on**: TASK-5445, TASK-5446
**Assigned-to**: unassigned

## Context

Implement the approved revision 0.2 contracts for implement authoritative storage routing and deletion resolution.
Spec §§2–5 are authoritative; §6 records baseline source, not old error-policy requirements.
This task is part of the four review resolutions recorded in spec §9.

## Scope

- Implement ping() -> bool, close() -> None and health-only initialize — configuration, not last ping, controls authority.
- Add save_crew(crew) -> bool; load_crew(name, tenant=None) and load_crew_by_id(crew_id, tenant=None) -> CrewDefinition | None — PG errors must never unlock Redis fallback.
- Add list_all_crews() -> list[dict[str,str]] and get_all_crews(tenant=None) -> list[CrewDefinition] from one complete Redis-first snapshot algorithm — incomplete views cannot drive eviction.
- Implement resolver and delete with typed failures — a durable tombstone is needed even for Redis-only definitions.
- Keep migration flag/report shape ready but add no fake migration implementation — TASK-5448 adds the sweep and initialization hook before manager integration.

**NOT in scope**: files outside the table; changing CrewDefinition model fields, execution-result storage,
creation.sql, _load_database_bots, dependency manifests or introducing new services.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/handlers/crew/definition_storage.py` | CREATE | Expose typed failures and tombstone resolution while keeping Redis-only delegation intact. |
| `packages/ai-parrot-server/tests/unit/test_crew_definition_storage.py` | CREATE | Use stateful fakes/AsyncMock and assert retained data, suppression by name and ID, retries, and failure propagation. |

## Codebase Contract (Anti-Hallucination)

Verified at `0cfa595cb2` on `dev`; re-check after dependencies land.

### Verified Imports

```python
import logging
from typing import Literal
from pydantic import BaseModel, Field
from parrot.handlers.crew.models import CrewDefinition, AgentDefinition, FlowRelation, ToolNodeDefinition
import pytest
```

Standard-library imports resolve under the project Python runtime; pytest/Pydantic/asyncdb are already declared in workspace pyproject.toml files. Crew model re-exports are verified in handlers/crew/models.py:17–23. Relative imports of new modules in blueprints are dependency contracts below, not claims of pre-existing code.

### Existing Signatures to Use

- `sym:packages/ai-parrot/src/parrot/models/crew_definition.py#CrewDefinition` — `class CrewDefinition(BaseModel):` (packages/ai-parrot/src/parrot/models/crew_definition.py:178).
- `sym:packages/ai-parrot/src/parrot/models/crew_definition.py#AgentDefinition` — `class AgentDefinition(BaseModel):` (packages/ai-parrot/src/parrot/models/crew_definition.py:31).
- `sym:packages/ai-parrot-server/src/parrot/handlers/crew/redis_persistence.py#CrewRedis` — `class CrewRedis:` (packages/ai-parrot-server/src/parrot/handlers/crew/redis_persistence.py:17).

### Dependency Imports and New Symbols

Consumes CrewRedisSnapshot/strict helpers from TASK-5445 and CrewPostgres row APIs from TASK-5446.

Exact blueprint imports (stdlib/existing references above; new symbols require the named prerequisite):

```python
from .models import CrewDefinition
from .postgres_persistence import CrewPostgres
from .redis_persistence import CrewRedis
from __future__ import annotations
from parrot.handlers.crew.definition_storage import CrewDefinitionStorage, CrewStorageUnavailable, CrewStorageConflict
from parrot.handlers.crew.models import CrewDefinition, AgentDefinition, FlowRelation, ToolNodeDefinition
from pydantic import BaseModel, Field
from typing import Literal
import logging
import pytest
```
Blueprint imports from `definition_codec`, `postgres_persistence`, `definition_storage`, and new Redis types are permitted only after their producer task completes; inspect those exact declarations before implementation. New symbols defined by this task are declared in its blueprint.

### Does NOT Exist

- Composition classes and exceptions do not exist before this task.
- PG and strict Redis helpers are provided only by the listed prerequisites.

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-server/src/parrot/handlers/crew/definition_storage.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-server/tests/unit/test_crew_definition_storage.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/models/crew_definition.py#CrewDefinition",
    "sym:packages/ai-parrot/src/parrot/models/crew_definition.py#AgentDefinition",
    "sym:packages/ai-parrot-server/src/parrot/handlers/crew/redis_persistence.py#CrewRedis"
  ]
}
```

## Implementation Notes

Use async I/O, Pydantic v2 models, strict type hints and Google-style docstrings. Format with black (120 columns); lint with ruff. No new dependencies. Logs belong under artifacts/logs/.

## Implementation Blueprint

### Steps (in order)

1. Implement ping() -> bool, close() -> None and health-only initialize — configuration, not last ping, controls authority.
2. Add save_crew(crew) -> bool; load_crew(name, tenant=None) and load_crew_by_id(crew_id, tenant=None) -> CrewDefinition | None — PG errors must never unlock Redis fallback.
3. Add list_all_crews() -> list[dict[str,str]] and get_all_crews(tenant=None) -> list[CrewDefinition] from one complete Redis-first snapshot algorithm — incomplete views cannot drive eviction.
4. Implement resolver and delete with typed failures — a durable tombstone is needed even for Redis-only definitions.
5. Keep migration flag/report shape ready but add no fake migration implementation — TASK-5448 adds the sweep and initialization hook before manager integration.

### `packages/ai-parrot-server/src/parrot/handlers/crew/definition_storage.py` (CREATE)

```python
"""Authoritative crew definition routing and migration results."""
from __future__ import annotations
import logging
from typing import Literal
from pydantic import BaseModel, Field
from .models import CrewDefinition
from .redis_persistence import CrewRedis
from .postgres_persistence import CrewPostgres

class CrewStorageUnavailable(RuntimeError):
    """A required storage operation failed without a trustworthy answer."""
class CrewStorageConflict(ValueError):
    """An authoritative identity conflicts with the requested mutation."""
class CrewDeletionResolution(BaseModel):
    """Tombstone-aware result used for idempotent manager removal."""
    state: Literal["active", "deleted", "absent"]
    definition: CrewDefinition | None = None
class CrewMigrationReport(BaseModel):
    """Per-sweep outcomes; tenant:name keys and predicted outcomes in dry runs."""
    dry_run: bool = False
    lock_acquired: bool = True
    skipped_reason: str | None = None
    migrated: list[str] = Field(default_factory=list)
    already_present: list[str] = Field(default_factory=list)
    deleted_sources: list[str] = Field(default_factory=list)
    conflicts: list[str] = Field(default_factory=list)
    failed: dict[str, str] = Field(default_factory=dict)
    redis_cleanup_failed: list[str] = Field(default_factory=list)
class CrewDefinitionStorage:
    """Configured primary never changes because a health check fails."""
    def __init__(self, redis: CrewRedis, postgres: CrewPostgres | None = None, *, migration: bool = False) -> None:
        self.redis = redis
        self.postgres = postgres
        self.migration = migration
        self._postgres_active = False
        self.logger = logging.getLogger(__name__)
    @property
    def postgres_active(self) -> bool:
        """Last observed health; never use this property to choose a backend."""
        return self._postgres_active
    async def initialize(self) -> CrewMigrationReport | None:
        """Probe Redis then Postgres; startup logs failures instead of raising."""
        # FILL IN: connectivity only in this task; migration hook added by TASK-5448.
        raise NotImplementedError
    async def resolve_for_delete(self, identifier: str, tenant: str | None = None) -> CrewDeletionResolution:
        """Resolve active/deleted/absent by name then ID, propagating failures."""
        # FILL IN: AC3, use PG row APIs even when normal loads return None.
        raise NotImplementedError
    async def delete_crew(self, crew: CrewDefinition) -> bool:
        """Commit tombstone before best-effort source cleanup; delegate in Redis mode."""
        # FILL IN: AC3/AC4.
        raise NotImplementedError
    async def ping(self) -> bool:
        """FILL IN AC1: return configured primary health, never substitute Redis."""
    async def close(self) -> None:
        """FILL IN: close both configured stores without leaking resources."""
    async def save_crew(self, crew: CrewDefinition) -> bool:
        """FILL IN AC1: write only configured primary, translate failures."""
    async def load_crew(self, name: str, tenant: str | None = None) -> CrewDefinition | None:
        """FILL IN AC2: authorize fallback by both name and ID."""
    async def load_crew_by_id(self, crew_id: str, tenant: str | None = None) -> CrewDefinition | None:
        """FILL IN AC2: reject stale alias and tombstone fallback."""
    async def list_all_crews(self) -> list[dict[str, str]]:
        """FILL IN AC5: complete Redis-first union, suppressed by both identities."""
    async def get_all_crews(self, tenant: str | None = None) -> list[CrewDefinition]:
        """FILL IN AC5: return validated union models or raise on incomplete view."""
```

**Why**: Expose typed failures and tombstone resolution while keeping Redis-only delegation intact.

### `packages/ai-parrot-server/tests/unit/test_crew_definition_storage.py` (CREATE)

```python
"""FEAT-860 regression tests; use isolated fakes unless explicitly live."""
from __future__ import annotations
import pytest
from parrot.handlers.crew.definition_storage import CrewDefinitionStorage, CrewStorageUnavailable, CrewStorageConflict
from parrot.handlers.crew.models import CrewDefinition, AgentDefinition, FlowRelation, ToolNodeDefinition

@pytest.mark.asyncio
async def test_write_failure_never_uses_redis() -> None:
    """Assert the state transition specified in this task, including failures."""
    # FILL IN: arrange fixtures and assert outcomes per AC and Test Specification.
    raise NotImplementedError

@pytest.mark.asyncio
async def test_tombstone_suppresses_all_aliases() -> None:
    """Assert the state transition specified in this task, including failures."""
    # FILL IN: arrange fixtures and assert outcomes per AC and Test Specification.
    raise NotImplementedError

@pytest.mark.asyncio
async def test_union_snapshot_order_and_incomplete_inventory() -> None:
    """Assert the state transition specified in this task, including failures."""
    # FILL IN: arrange fixtures and assert outcomes per AC and Test Specification.
    raise NotImplementedError

@pytest.mark.asyncio
async def test_delete_failure_and_retry_resolution() -> None:
    """Assert the state transition specified in this task, including failures."""
    # FILL IN: arrange fixtures and assert outcomes per AC and Test Specification.
    raise NotImplementedError
```

**Why**: Use stateful fakes/AsyncMock and assert retained data, suppression by name and ID, retries, and failure propagation.

### FILL IN checklist

- [ ] `packages/ai-parrot-server/src/parrot/handlers/crew/definition_storage.py` — complete the bounded logic described above; satisfy all task acceptance criteria and retain unrelated content.
- [ ] `packages/ai-parrot-server/tests/unit/test_crew_definition_storage.py` — complete the bounded logic described above; satisfy all task acceptance criteria and retain unrelated content.
- [ ] Replace all blueprint gaps with complete working code/tests; no placeholders in implementation files.

## Acceptance Criteria

- [ ] AC1: Redis mode delegates all seven operations; explicit PG backend never downgrades after initialization/write failure.
- [ ] AC2: PG reads distinguish absence, tombstones, malformed rows and failures; fallback checks both name and ID on every read surface.
- [ ] AC3: resolve_for_delete retains typed active/deleted/absent states; retries find tombstones with an empty manager cache.
- [ ] AC4: PG delete commits before cleanup; PG failure leaves Redis unchanged; cleanup failures warn without resurrection.
- [ ] AC5: Union captures strict Redis snapshots before PG rows; unexplained missing snapshots or either inventory failure raise.
- [ ] AC6: Exception translation preserves causes and maps integrity/stale identity to conflict, connectivity to unavailable; no DSN leakage.

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


- Task: TASK-5447
- Feature: postgres-crew-storage
- Implementation SHA: 86d97969eb4b5cf8361c6839cb05cfa8d47443f3
- Closed at (UTC): 2026-11-09T21:35:41+00:00
- Fix commits: 86d97969eb4b5cf8361c6839cb05cfa8d47443f3

| Metric | Value |
|---|---|
| validation_refs | 1 |
| fix_commits | 1 |
| seat_summary | Seat: gpt-5.6-terra · Backend: codex · Model: gpt-5.6-terra · Attempts: 1 · Duration: 373.67s · Tokens: n/a |
