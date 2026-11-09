# TASK-5450: Propagate storage failures and atomic updates through HTTP

**Feature**: FEAT-860 — Postgres CrewDefinition Storage
**Spec**: `sdd/specs/postgres-crew-storage.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2–4h)
**Depends-on**: TASK-5449
**Assigned-to**: unassigned

## Context

Implement the approved revision 0.2 contracts for propagate storage failures and atomic updates through http.
Spec §§2–5 are authoritative; §6 records baseline source, not old error-policy requirements.
This task is part of the four review resolutions recorded in spec §9.

## Scope

- Add typed error handlers before all broad catches — nested PUT catches otherwise convert storage failures to 400.
- Use persist_crew_update for PG updates and direct remove_crew for PG delete — preserves durable state and retry semantics.
- Test response statuses together with unchanged backing state — success codes alone cannot prove persistence ordering.

**NOT in scope**: files outside the table; changing CrewDefinition model fields, execution-result storage,
creation.sql, _load_database_bots, dependency manifests or introducing new services.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/handlers/crew/handler.py` | MODIFY | Otherwise get_crew errors become 404 and tombstone retries never reach the manager. |
| `packages/ai-parrot-server/tests/handlers/test_crew_storage_errors.py` | CREATE | Drive handlers with request/session fakes and a stateful manager/storage fake; test inner and outer catches. |

## Codebase Contract (Anti-Hallucination)

Verified at `0cfa595cb2` on `dev`; re-check after dependencies land.

### Verified Imports

```python
from parrot.handlers.crew.handler import CrewHandler
from aiohttp import web
import pytest
```

Standard-library imports resolve under the project Python runtime; pytest/Pydantic/asyncdb are already declared in workspace pyproject.toml files. Crew model re-exports are verified in handlers/crew/models.py:17–23. Relative imports of new modules in blueprints are dependency contracts below, not claims of pre-existing code.

### Existing Signatures to Use

- `sym:packages/ai-parrot-server/src/parrot/handlers/crew/handler.py#CrewHandler` — `class CrewHandler(BaseView):` (packages/ai-parrot-server/src/parrot/handlers/crew/handler.py:27).
- `sym:packages/ai-parrot-server/src/parrot/handlers/crew/handler.py#CrewHandler.put` — `async def put(self):` (packages/ai-parrot-server/src/parrot/handlers/crew/handler.py:272).
- `sym:packages/ai-parrot-server/src/parrot/handlers/crew/handler.py#CrewHandler.get` — `async def get(self):` (packages/ai-parrot-server/src/parrot/handlers/crew/handler.py:379).
- `sym:packages/ai-parrot-server/src/parrot/handlers/crew/handler.py#CrewHandler.delete` — `async def delete(self):` (packages/ai-parrot-server/src/parrot/handlers/crew/handler.py:472).

### Dependency Imports and New Symbols

Consumes BotManager.persist_crew_update, backend selection and error propagation from TASK-5449.

Exact blueprint imports (stdlib/existing references above; new symbols require the named prerequisite):

```python
from .definition_storage import CrewStorageUnavailable, CrewStorageConflict
from __future__ import annotations
from parrot.handlers.crew.definition_storage import CrewStorageUnavailable, CrewStorageConflict
from parrot.handlers.crew.handler import CrewHandler
import pytest
```
Blueprint imports from `definition_codec`, `postgres_persistence`, `definition_storage`, and new Redis types are permitted only after their producer task completes; inspect those exact declarations before implementation. New symbols defined by this task are declared in its blueprint.

### Does NOT Exist

- No new PATCH endpoint is required.
- persist_crew_update is supplied by TASK-5449, not an existing API at planning time.

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-server/src/parrot/handlers/crew/handler.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-server/tests/handlers/test_crew_storage_errors.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-server/src/parrot/handlers/crew/handler.py#CrewHandler",
    "sym:packages/ai-parrot-server/src/parrot/handlers/crew/handler.py#CrewHandler.put",
    "sym:packages/ai-parrot-server/src/parrot/handlers/crew/handler.py#CrewHandler.get",
    "sym:packages/ai-parrot-server/src/parrot/handlers/crew/handler.py#CrewHandler.delete"
  ]
}
```

## Implementation Notes

Use async I/O, Pydantic v2 models, strict type hints and Google-style docstrings. Format with black (120 columns); lint with ruff. No new dependencies. Logs belong under artifacts/logs/.

## Implementation Blueprint

### Steps (in order)

1. Add typed error handlers before all broad catches — nested PUT catches otherwise convert storage failures to 400.
2. Use persist_crew_update for PG updates and direct remove_crew for PG delete — preserves durable state and retry semantics.
3. Test response statuses together with unchanged backing state — success codes alone cannot prove persistence ordering.

### `packages/ai-parrot-server/src/parrot/handlers/crew/handler.py` (MODIFY)

```python
# Anchor:     async def put(self):
# occurrences: 1; verified packages/ai-parrot-server/src/parrot/handlers/crew/handler.py:272 at 0cfa595cb2
# Anchor:     async def get(self):
# occurrences: 1; verified packages/ai-parrot-server/src/parrot/handlers/crew/handler.py:379 at 0cfa595cb2
# Anchor:     async def delete(self):
# occurrences: 1; verified packages/ai-parrot-server/src/parrot/handlers/crew/handler.py:472 at 0cfa595cb2
from .definition_storage import CrewStorageUnavailable, CrewStorageConflict
# FILL IN: map storage unavailable to 503, identity conflict to 409 before
# broad catches in put/get/delete (including nested create catch in put).
# In PG mode, PUT update calls await bot_manager.persist_crew_update(...)
# rather than remove_crew + add_crew. Preserve existing Redis-only behavior.
# In PG mode, DELETE calls remove_crew directly; False => 404, True => success.
# Keep session tenant resolution and web.HTTPError propagation unchanged.
# Use crew_storage_backend == "postgres", never postgres_active, to choose behavior.
```

**Why**: Otherwise get_crew errors become 404 and tombstone retries never reach the manager.

### `packages/ai-parrot-server/tests/handlers/test_crew_storage_errors.py` (CREATE)

```python
"""FEAT-860 regression tests; use isolated fakes unless explicitly live."""
from __future__ import annotations
import pytest
from parrot.handlers.crew.handler import CrewHandler
from parrot.handlers.crew.definition_storage import CrewStorageUnavailable, CrewStorageConflict

@pytest.mark.asyncio
async def test_storage_failure_is_503_not_404() -> None:
    """Assert the state transition specified in this task, including failures."""
    # FILL IN: arrange fixtures and assert outcomes per AC and Test Specification.
    raise NotImplementedError

@pytest.mark.asyncio
async def test_identity_conflict_is_409() -> None:
    """Assert the state transition specified in this task, including failures."""
    # FILL IN: arrange fixtures and assert outcomes per AC and Test Specification.
    raise NotImplementedError

@pytest.mark.asyncio
async def test_deleted_retry_succeeds_and_absent_is_404() -> None:
    """Assert the state transition specified in this task, including failures."""
    # FILL IN: arrange fixtures and assert outcomes per AC and Test Specification.
    raise NotImplementedError

@pytest.mark.asyncio
async def test_update_uses_single_persistence_and_rejects_rename() -> None:
    """Assert the state transition specified in this task, including failures."""
    # FILL IN: arrange fixtures and assert outcomes per AC and Test Specification.
    raise NotImplementedError
```

**Why**: Drive handlers with request/session fakes and a stateful manager/storage fake; test inner and outer catches.

### FILL IN checklist

- [ ] `packages/ai-parrot-server/src/parrot/handlers/crew/handler.py` — complete the bounded logic described above; satisfy all task acceptance criteria and retain unrelated content.
- [ ] `packages/ai-parrot-server/tests/handlers/test_crew_storage_errors.py` — complete the bounded logic described above; satisfy all task acceptance criteria and retain unrelated content.
- [ ] Replace all blueprint gaps with complete working code/tests; no placeholders in implementation files.

## Acceptance Criteria

- [ ] AC1: Typed storage failures produce 503/409 for PUT, GET and DELETE without leaking driver messages or credentials.
- [ ] AC2: PG PUT preserves ID/time and uses one manager persistence call; failed update leaves row/cache unchanged.
- [ ] AC3: PG DELETE has no active-only precheck: empty-cache tombstone retry succeeds, true absence is 404, outage is 503.
- [ ] AC4: PG rename returns 409 before mutation; Redis-only behavior, tenant resolution and authentication remain unchanged.

## Validation Commands

- `pytest packages/ai-parrot-server/tests/handlers/test_crew_storage_errors.py -q`

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
