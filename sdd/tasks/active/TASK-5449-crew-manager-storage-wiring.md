# TASK-5449: Wire manager persistence ordering and tombstone retries

**Feature**: FEAT-860 — Postgres CrewDefinition Storage
**Spec**: `sdd/specs/postgres-crew-storage.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2–4h)
**Depends-on**: TASK-5448
**Assigned-to**: unassigned

## Context

Implement the approved revision 0.2 contracts for wire manager persistence ordering and tombstone retries.
Spec §§2–5 are authoritative; §6 records baseline source, not old error-policy requirements.
This task is part of the four review resolutions recorded in spec §9.

## Scope

- Wire stores and flags using existing construction anchors — disabled crews must not allocate PG resources.
- Change mutation ordering only in PG mode — keep Redis backward compatibility explicit.
- Add tombstone-aware retry and typed exception propagation — absence must not hide primary errors.
- Provide persist_crew_update as the HTTP seam — do not break the synchronous update_crew API.
- Add cache-state tests and flags coverage — verify failure states, not just delegated method calls.

**NOT in scope**: files outside the table; changing CrewDefinition model fields, execution-result storage,
creation.sql, _load_database_bots, dependency manifests or introducing new services.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/manager/manager.py` | MODIFY | Persistence must finish before cache mutation; a failed operation cannot look successful to HTTP. |
| `packages/ai-parrot/tests/test_botmanager_flags.py` | MODIFY | Existing flag regressions must continue to cover backward compatibility. |
| `packages/ai-parrot-server/tests/manager/test_crew_storage_wiring.py` | CREATE | Use fake crews and storage; assert cache contents on failures, canonical keys, idempotent removal and no false absence. |

## Codebase Contract (Anti-Hallucination)

Verified at `0cfa595cb2` on `dev`; re-check after dependencies land.

### Verified Imports

```python
from parrot.manager.manager import BotManager
from parrot.bots.flows.crew import AgentCrew
from parrot.handlers.crew.models import CrewDefinition, AgentDefinition, FlowRelation, ToolNodeDefinition
from typing import Optional
from unittest.mock import AsyncMock, patch
import pytest
```

Standard-library imports resolve under the project Python runtime; pytest/Pydantic/asyncdb are already declared in workspace pyproject.toml files. Crew model re-exports are verified in handlers/crew/models.py:17–23. Relative imports of new modules in blueprints are dependency contracts below, not claims of pre-existing code.

### Existing Signatures to Use

- `sym:packages/ai-parrot-server/src/parrot/manager/manager.py#BotManager` — `class BotManager:` (packages/ai-parrot-server/src/parrot/manager/manager.py:217).
- `sym:packages/ai-parrot-server/src/parrot/manager/manager.py#BotManager.add_crew` — `async def add_crew(self, name: str, crew: AgentCrew, crew_def: CrewDefinition) -> None:` (packages/ai-parrot-server/src/parrot/manager/manager.py:3255).
- `sym:packages/ai-parrot-server/src/parrot/manager/manager.py#BotManager.get_crew` — `async def get_crew(` (packages/ai-parrot-server/src/parrot/manager/manager.py:3294).
- `sym:packages/ai-parrot-server/src/parrot/manager/manager.py#BotManager.remove_crew` — `async def remove_crew(self, identifier: str, tenant: Optional[str] = None) -> bool:` (packages/ai-parrot-server/src/parrot/manager/manager.py:3383).
- `sym:packages/ai-parrot/src/parrot/models/crew_definition.py#CrewDefinition` — `class CrewDefinition(BaseModel):` (packages/ai-parrot/src/parrot/models/crew_definition.py:178).
- `sym:packages/ai-parrot/src/parrot/models/crew_definition.py#AgentDefinition` — `class AgentDefinition(BaseModel):` (packages/ai-parrot/src/parrot/models/crew_definition.py:31).

### Dependency Imports and New Symbols

Consumes initialized composition, migration hook and deletion resolver completed by TASK-5448; its transitive prerequisites provide config/PG helpers.

Exact blueprint imports (stdlib/existing references above; new symbols require the named prerequisite):

```python
from ..handlers.crew.definition_storage import CrewDefinitionStorage, CrewStorageUnavailable, CrewStorageConflict
from ..handlers.crew.postgres_persistence import CrewPostgres
from __future__ import annotations
from parrot.handlers.crew.definition_storage import CrewStorageUnavailable, CrewStorageConflict
from parrot.manager.manager import BotManager
import pytest
```
Blueprint imports from `definition_codec`, `postgres_persistence`, `definition_storage`, and new Redis types are permitted only after their producer task completes; inspect those exact declarations before implementation. New symbols defined by this task are declared in its blueprint.

### Does NOT Exist

- persist_crew_update is new; existing update_crew is synchronous and cache-only.
- There is no app database pool available inside BotManager.__init__.

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-server/src/parrot/manager/manager.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/test_botmanager_flags.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-server/tests/manager/test_crew_storage_wiring.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-server/src/parrot/manager/manager.py#BotManager",
    "sym:packages/ai-parrot-server/src/parrot/manager/manager.py#BotManager.add_crew",
    "sym:packages/ai-parrot-server/src/parrot/manager/manager.py#BotManager.get_crew",
    "sym:packages/ai-parrot-server/src/parrot/manager/manager.py#BotManager.remove_crew",
    "sym:packages/ai-parrot/src/parrot/models/crew_definition.py#CrewDefinition",
    "sym:packages/ai-parrot/src/parrot/models/crew_definition.py#AgentDefinition"
  ]
}
```

## Implementation Notes

Use async I/O, Pydantic v2 models, strict type hints and Google-style docstrings. Format with black (120 columns); lint with ruff. No new dependencies. Logs belong under artifacts/logs/.

## Implementation Blueprint

### Steps (in order)

1. Wire stores and flags using existing construction anchors — disabled crews must not allocate PG resources.
2. Change mutation ordering only in PG mode — keep Redis backward compatibility explicit.
3. Add tombstone-aware retry and typed exception propagation — absence must not hide primary errors.
4. Provide persist_crew_update as the HTTP seam — do not break the synchronous update_crew API.
5. Add cache-state tests and flags coverage — verify failure states, not just delegated method calls.

### `packages/ai-parrot-server/src/parrot/manager/manager.py` (MODIFY)

```python
# Anchor: from ..handlers.crew.redis_persistence import CrewRedis
# occurrences: 1; verified packages/ai-parrot-server/src/parrot/manager/manager.py:98 at 0cfa595cb2
# Anchor:     ENABLE_CREWS,
# occurrences: 1; verified packages/ai-parrot-server/src/parrot/manager/manager.py:104 at 0cfa595cb2
# Anchor:         self.crew_redis = CrewRedis() if self.enable_crews else None
# occurrences: 1; verified packages/ai-parrot-server/src/parrot/manager/manager.py:271 at 0cfa595cb2
# Anchor:     async def add_crew(self, name: str, crew: AgentCrew, crew_def: CrewDefinition) -> None:
# occurrences: 1; verified packages/ai-parrot-server/src/parrot/manager/manager.py:3255 at 0cfa595cb2
# Anchor:     async def get_crew(
# occurrences: 1; verified packages/ai-parrot-server/src/parrot/manager/manager.py:3294 at 0cfa595cb2
# Anchor:     async def remove_crew(self, identifier: str, tenant: Optional[str] = None) -> bool:
# occurrences: 1; verified packages/ai-parrot-server/src/parrot/manager/manager.py:3383 at 0cfa595cb2
# Anchor:     async def load_crews(self) -> None:
# occurrences: 1; verified packages/ai-parrot-server/src/parrot/manager/manager.py:3457 at 0cfa595cb2
# Anchor:     async def sync_crews(self) -> None:
# occurrences: 1; verified packages/ai-parrot-server/src/parrot/manager/manager.py:3504 at 0cfa595cb2
# Add imports beside CrewRedis:
from ..handlers.crew.postgres_persistence import CrewPostgres
from ..handlers.crew.definition_storage import CrewDefinitionStorage, CrewStorageUnavailable, CrewStorageConflict
# Add CREW_DEFINITION_STORAGE and CREW_DEFINITION_MIGRATION in the existing ..conf import.
# Extend __init__ with crew_storage_backend: Optional[str] = None,
# crew_migration: Optional[bool] = None; build stores only when enable_crews.
# FILL IN: route add/get/remove/load/sync to crew_storage; preserve Redis-only behavior.
# New async method inside BotManager for HTTP updates:
async def persist_crew_update(self, identifier: str, crew: AgentCrew, crew_def: CrewDefinition) -> None:
    """Persist a same-name update once before replacing its cache entry."""
    # FILL IN: resolve existing definition; preserve ID/created_at; reject rename;
    # save once, then replace using canonical tenant:name. AC4.
    raise NotImplementedError
# Keep existing synchronous update_crew unchanged for other callers.
# Postgres get_crew must re-raise typed errors before its existing broad catch.
# remove_crew must use resolve_for_delete after cache miss, without active-only precheck.
```

**Why**: Persistence must finish before cache mutation; a failed operation cannot look successful to HTTP.

### `packages/ai-parrot/tests/test_botmanager_flags.py` (MODIFY)

```python
# Anchor: def test_enable_crews_true_creates_crew_redis():
# occurrences: 1; verified packages/ai-parrot/tests/test_botmanager_flags.py:186 at 0cfa595cb2
# Extend the existing enabled test with default Redis composition assertions.
# Add disabled/no-PG construction, postgres backend, unknown backend warning,
# and explicit kwargs override tests using patch/AsyncMock already imported.
# FILL IN: isolate config defaults so environment cannot flip assertions (AC1).
```

**Why**: Existing flag regressions must continue to cover backward compatibility.

### `packages/ai-parrot-server/tests/manager/test_crew_storage_wiring.py` (CREATE)

```python
"""FEAT-860 regression tests; use isolated fakes unless explicitly live."""
from __future__ import annotations
import pytest
from parrot.manager.manager import BotManager
from parrot.handlers.crew.definition_storage import CrewStorageUnavailable, CrewStorageConflict

@pytest.mark.asyncio
async def test_persistence_precedes_cache_mutation() -> None:
    """Assert the state transition specified in this task, including failures."""
    # FILL IN: arrange fixtures and assert outcomes per AC and Test Specification.
    raise NotImplementedError

@pytest.mark.asyncio
async def test_delete_retry_with_empty_cache() -> None:
    """Assert the state transition specified in this task, including failures."""
    # FILL IN: arrange fixtures and assert outcomes per AC and Test Specification.
    raise NotImplementedError

@pytest.mark.asyncio
async def test_update_is_one_upsert_and_no_delete() -> None:
    """Assert the state transition specified in this task, including failures."""
    # FILL IN: arrange fixtures and assert outcomes per AC and Test Specification.
    raise NotImplementedError

@pytest.mark.asyncio
async def test_incomplete_sync_preserves_cache() -> None:
    """Assert the state transition specified in this task, including failures."""
    # FILL IN: arrange fixtures and assert outcomes per AC and Test Specification.
    raise NotImplementedError
```

**Why**: Use fake crews and storage; assert cache contents on failures, canonical keys, idempotent removal and no false absence.

### FILL IN checklist

- [ ] `packages/ai-parrot-server/src/parrot/manager/manager.py` — complete the bounded logic described above; satisfy all task acceptance criteria and retain unrelated content.
- [ ] `packages/ai-parrot/tests/test_botmanager_flags.py` — complete the bounded logic described above; satisfy all task acceptance criteria and retain unrelated content.
- [ ] `packages/ai-parrot-server/tests/manager/test_crew_storage_wiring.py` — complete the bounded logic described above; satisfy all task acceptance criteria and retain unrelated content.
- [ ] Replace all blueprint gaps with complete working code/tests; no placeholders in implementation files.

## Acceptance Criteria

- [ ] AC1: Enable flags/defaults preserved; unknown backend warns; explicit PG missing DSN does not select Redis.
- [ ] AC2: PG adds/deletes publish/evict only after persistence; failure preserves old cache and propagates typed errors.
- [ ] AC3: PG get_crew failures propagate; remove resolves deleted/absent with empty cache; stale cached IDs cannot delete recreated crew.
- [ ] AC4: persist_crew_update preserves identity/time, rejects rename, performs one upsert and replaces canonical cache only after success.
- [ ] AC5: Startup initializes then loads; incomplete sync skips eviction; existing Redis-only methods retain behavior.
- [ ] AC6: creation.sql and _load_database_bots remain byte-identical; run the existing storage gate as a supplementary verification.

## Validation Commands

- `pytest packages/ai-parrot/tests/test_botmanager_flags.py packages/ai-parrot-server/tests/manager/test_crew_storage_wiring.py -q`

## Test Specification

Each test block above is an executor starting point, not an implementation. Build fixtures locally in the declared test files; do not modify shared conftest.py. Assert observable state and error behavior from every acceptance criterion. Avoid network/LLM calls except the explicitly gated live tests in TASK-5451.

Supplementary frozen-source check: `pytest packages/ai-parrot-server/tests/studio/storage/test_storage_gates.py::test_load_database_bots_untouched -q`. This existing gate is read-only and not owned by this task.

## Agent Instructions

Implement in the feature worktree provisioned by sdd-start, never on dev. Check the dependency states
in `sdd/tasks/index/postgres-crew-storage.json` first. Verify source anchors and dependency-created APIs before editing.
Complete only declared files, run narrow validation commands, and commit scoped code. Finalize with
`parrot sdd task finalize` and real TaskCompletionEvidence for the implementation HEAD; do not manually
move the task, stamp completion, or run legacy task-close helpers.

## Completion Note

Pending; populated by the task finalizer after implementation and validation.
