# TASK-5445: Add strict Redis snapshots and conditional cleanup

**Feature**: FEAT-860 — Postgres CrewDefinition Storage
**Spec**: `sdd/specs/postgres-crew-storage.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2–4h)
**Depends-on**: TASK-5443
**Assigned-to**: unassigned

## Context

Implement the approved revision 0.2 contracts for add strict redis snapshots and conditional cleanup.
Spec §§2–5 are authoritative; §6 records baseline source, not old error-policy requirements.
This task is part of the four review resolutions recorded in spec §9.

## Scope

- Introduce typed snapshots and strict reads — existing methods deliberately swallow failures and cannot prove a complete inventory.
- Implement one conditional Lua cleanup — separate GET/DELETE calls cannot protect concurrent writes.
- Add deterministic fake tests for mismatch and ownership branches — live Redis validation is separately assigned.

**NOT in scope**: files outside the table; changing CrewDefinition model fields, execution-result storage,
creation.sql, _load_database_bots, dependency manifests or introducing new services.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/handlers/crew/redis_persistence.py` | MODIFY | Exact raw-state comparison protects edits made after snapshot capture. |
| `packages/ai-parrot-server/tests/unit/test_crew_redis_snapshot.py` | CREATE | Cover both raw states, legacy conflicts, mapped IDs, membership cleanup and strict errors; live Lua proof belongs to TASK-5451. |

## Codebase Contract (Anti-Hallucination)

Verified at `0cfa595cb2` on `dev`; re-check after dependencies land.

### Verified Imports

```python
from enum import Enum
from pydantic import BaseModel, Field
from typing import List, Dict, Optional
from parrot.handlers.crew.models import CrewDefinition, AgentDefinition, FlowRelation, ToolNodeDefinition
import pytest
```

Standard-library imports resolve under the project Python runtime; pytest/Pydantic/asyncdb are already declared in workspace pyproject.toml files. Crew model re-exports are verified in handlers/crew/models.py:17–23. Relative imports of new modules in blueprints are dependency contracts below, not claims of pre-existing code.

### Existing Signatures to Use

- `sym:packages/ai-parrot-server/src/parrot/handlers/crew/redis_persistence.py#CrewRedis` — `class CrewRedis:` (packages/ai-parrot-server/src/parrot/handlers/crew/redis_persistence.py:17).
- `sym:packages/ai-parrot-server/src/parrot/handlers/crew/redis_persistence.py#CrewRedis.list_all_crews` — `async def list_all_crews(self) -> List[Dict[str, str]]:` (packages/ai-parrot-server/src/parrot/handlers/crew/redis_persistence.py:397).
- `sym:packages/ai-parrot-server/src/parrot/handlers/crew/redis_persistence.py#CrewRedis.delete_crew` — `async def delete_crew(self, name: str, tenant: Optional[str] = None) -> bool:` (packages/ai-parrot-server/src/parrot/handlers/crew/redis_persistence.py:328).
- `sym:packages/ai-parrot/src/parrot/models/crew_definition.py#CrewDefinition` — `class CrewDefinition(BaseModel):` (packages/ai-parrot/src/parrot/models/crew_definition.py:178).
- `sym:packages/ai-parrot/src/parrot/models/crew_definition.py#AgentDefinition` — `class AgentDefinition(BaseModel):` (packages/ai-parrot/src/parrot/models/crew_definition.py:31).

### Dependency Imports and New Symbols

Consumes codec delegates from TASK-5443 and serializes the overlapping redis_persistence.py edits.

Exact blueprint imports (stdlib/existing references above; new symbols require the named prerequisite):

```python
from __future__ import annotations
from enum import Enum
from parrot.handlers.crew.redis_persistence import CrewRedis, CrewRedisSnapshot, CrewRedisCleanupResult
from pydantic import BaseModel, Field
import pytest
```
Blueprint imports from `definition_codec`, `postgres_persistence`, `definition_storage`, and new Redis types are permitted only after their producer task completes; inspect those exact declarations before implementation. New symbols defined by this task are declared in its blueprint.

### Does NOT Exist

- CrewRedisSnapshot, CrewRedisCleanupResult and strict snapshot helpers do not exist before this task.

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-server/src/parrot/handlers/crew/redis_persistence.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-server/tests/unit/test_crew_redis_snapshot.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-server/src/parrot/handlers/crew/redis_persistence.py#CrewRedis",
    "sym:packages/ai-parrot-server/src/parrot/handlers/crew/redis_persistence.py#CrewRedis.list_all_crews",
    "sym:packages/ai-parrot-server/src/parrot/handlers/crew/redis_persistence.py#CrewRedis.delete_crew",
    "sym:packages/ai-parrot/src/parrot/models/crew_definition.py#CrewDefinition",
    "sym:packages/ai-parrot/src/parrot/models/crew_definition.py#AgentDefinition"
  ]
}
```

## Implementation Notes

Use async I/O, Pydantic v2 models, strict type hints and Google-style docstrings. Format with black (120 columns); lint with ruff. No new dependencies. Logs belong under artifacts/logs/.

## Implementation Blueprint

### Steps (in order)

1. Introduce typed snapshots and strict reads — existing methods deliberately swallow failures and cannot prove a complete inventory.
2. Implement one conditional Lua cleanup — separate GET/DELETE calls cannot protect concurrent writes.
3. Add deterministic fake tests for mismatch and ownership branches — live Redis validation is separately assigned.

### `packages/ai-parrot-server/src/parrot/handlers/crew/redis_persistence.py` (MODIFY)

```python
# Anchor: class CrewRedis:
# occurrences: 1; verified packages/ai-parrot-server/src/parrot/handlers/crew/redis_persistence.py:17 at 0cfa595cb2
# Anchor:     async def list_all_crews(self) -> List[Dict[str, str]]:
# occurrences: 1; verified packages/ai-parrot-server/src/parrot/handlers/crew/redis_persistence.py:397 at 0cfa595cb2
# Add module-level Pydantic/Enum types and extend CrewRedis, preserving legacy methods.
from enum import Enum
from pydantic import BaseModel, Field

class CrewRedisSnapshot(BaseModel):
    """Exact source states and parsed definition captured for one tenant/name."""
    tenant: str
    name: str
    namespaced_raw: str | None
    legacy_raw: str | None
    definition: CrewDefinition
    mapping_ids: list[str] = Field(default_factory=list)

class CrewRedisCleanupResult(str, Enum):
    """Outcome of an atomic source cleanup attempt."""
    deleted = "deleted"
    source_changed = "source_changed"
    already_absent = "already_absent"

# INSERT the following methods inside CrewRedis:
async def snapshot_crew(self, name: str, tenant: Optional[str] = None) -> Optional[CrewRedisSnapshot]:
    """Read both raw key states; propagate Redis and parse failures."""
    # FILL IN: capture both states together; reject differing global legacy payloads (AC1).
    raise NotImplementedError

async def delete_snapshot(self, snapshot: CrewRedisSnapshot) -> CrewRedisCleanupResult:
    """Atomically compare all source states before deleting keys or memberships."""
    # FILL IN: one Lua operation, including mapping ownership checks (AC2-AC4).
    raise NotImplementedError

async def list_all_crews_strict(self) -> List[Dict[str, str]]:
    """List tenant/name identities without converting backend errors to empty lists."""
    # FILL IN: strict tenant and legacy inventory; do not call swallowing list methods.
    raise NotImplementedError
```

**Why**: Exact raw-state comparison protects edits made after snapshot capture.

### `packages/ai-parrot-server/tests/unit/test_crew_redis_snapshot.py` (CREATE)

```python
"""FEAT-860 regression tests; use isolated fakes unless explicitly live."""
from __future__ import annotations
import pytest
from parrot.handlers.crew.redis_persistence import CrewRedis, CrewRedisSnapshot, CrewRedisCleanupResult

@pytest.mark.asyncio
async def test_snapshot_retains_missing_and_legacy_states() -> None:
    """Assert the state transition specified in this task, including failures."""
    # FILL IN: arrange fixtures and assert outcomes per AC and Test Specification.
    raise NotImplementedError

@pytest.mark.asyncio
async def test_changed_source_mutates_nothing() -> None:
    """Assert the state transition specified in this task, including failures."""
    # FILL IN: arrange fixtures and assert outcomes per AC and Test Specification.
    raise NotImplementedError

@pytest.mark.asyncio
async def test_mapping_reassignment_is_preserved() -> None:
    """Assert the state transition specified in this task, including failures."""
    # FILL IN: arrange fixtures and assert outcomes per AC and Test Specification.
    raise NotImplementedError

@pytest.mark.asyncio
async def test_inventory_failure_raises() -> None:
    """Assert the state transition specified in this task, including failures."""
    # FILL IN: arrange fixtures and assert outcomes per AC and Test Specification.
    raise NotImplementedError
```

**Why**: Cover both raw states, legacy conflicts, mapped IDs, membership cleanup and strict errors; live Lua proof belongs to TASK-5451.

### FILL IN checklist

- [ ] `packages/ai-parrot-server/src/parrot/handlers/crew/redis_persistence.py` — complete the bounded logic described above; satisfy all task acceptance criteria and retain unrelated content.
- [ ] `packages/ai-parrot-server/tests/unit/test_crew_redis_snapshot.py` — complete the bounded logic described above; satisfy all task acceptance criteria and retain unrelated content.
- [ ] Replace all blueprint gaps with complete working code/tests; no placeholders in implementation files.

## Acceptance Criteria

- [ ] AC1: Snapshot captures both raw key states including absence and IDs; differing legacy/source definitions are retained, never silently dropped.
- [ ] AC2: One Lua call compares every expected state before any mutation; changed source leaves all keys/indexes unchanged.
- [ ] AC3: ID mappings are removed only if still owned by the name; tenant removal requires an empty namespaced list.
- [ ] AC4: Source changed, already absent and deleted are distinguished; transport errors raise. Reject unsupported Redis Cluster before mutation.
- [ ] AC5: Strict inventory propagates inner tenant failures; old public APIs and codec delegates remain compatible.

## Validation Commands

- `pytest packages/ai-parrot-server/tests/unit/test_crew_redis_snapshot.py -q`

## Test Specification

Each test block above is an executor starting point, not an implementation. Build fixtures locally in the declared test files; do not modify shared conftest.py. Assert observable state and error behavior from every acceptance criterion. Avoid network/LLM calls except the explicitly gated live tests in TASK-5451.

## Agent Instructions

Implement in the feature worktree provisioned by sdd-start, never on dev. Check the dependency states
in `sdd/tasks/index/postgres-crew-storage.json` first. Verify source anchors and dependency-created APIs before editing.
Complete only declared files, run narrow validation commands, and commit scoped code. Finalize with
`parrot sdd task finalize` and real TaskCompletionEvidence for the implementation HEAD; do not manually
move the task, stamp completion, or run legacy task-close helpers.

## Completion Note


- Task: TASK-5445
- Feature: postgres-crew-storage
- Implementation SHA: e726435ae87c174b5c1672fe7811461d21746892
- Closed at (UTC): 2026-11-09T21:24:04+00:00
- Fix commits: none

| Metric | Value |
|---|---|
| validation_refs | 1 |
| fix_commits | 0 |
| seat_summary | Seat: gpt-5.6-terra · Backend: codex · Model: gpt-5.6-terra · Attempts: 1 · Duration: 373.346s · Tokens: n/a |
