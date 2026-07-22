# TASK-1872: RecipeHandler REST + scheduler callback (ai-parrot-server)

**Feature**: FEAT-324 — Infographic Builder — Recipe-Driven, Replayable A2UI Infographics
**Spec**: `sdd/specs/infographic-builder.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1869
**Assigned-to**: unassigned

---

## Context

Module 8 of FEAT-324 — the REST and scheduled triggers (spec G6). CRUD + run endpoint for
recipes, plus a job callback registered on the EXISTING APScheduler-based
`AgentSchedulerManager` so replays are schedulable through the existing `SchedulerJobsHandler`
CRUD. Scheduled runs execute under the recipe's stored `schedule.principal` (G8). Touches
ONLY ai-parrot-server.

---

## Scope

- Implement `packages/ai-parrot-server/src/parrot/handlers/infographic_recipes.py`:
  - `RecipeHandler(BaseView)` following the `DatasetManagerHandler` pattern:
    - `GET /api/v1/infographic_recipes` — store `list()` (owner-scoped from request auth);
    - `GET /api/v1/infographic_recipes/{name}` — full recipe;
    - `PUT /api/v1/infographic_recipes/{name}` — validate body as `InfographicRecipe`, save
      (overwrite semantics);
    - `DELETE /api/v1/infographic_recipes/{name}`;
    - `POST /api/v1/infographic_recipes/{name}/run` — optional `params` body override →
      `RecipeRunner.run()`; success returns artifact metadata (id, filename, mime, size,
      storage ref); `RecipeRunException` → **422** with `RecipeRunError.model_dump()`;
      unknown recipe → 404 listing available names.
  - Route registration wherever the server registers handler routes (mirror how
    `DatasetManagerHandler` / `SchedulerJobsHandler` routes are wired — find and follow the
    existing registration site).
- Scheduler integration:
  - Register a `run_infographic_recipe` job callback on `AgentSchedulerManager` (follow the
    existing callback-registration mechanism — read how `SchedulerCallbacksHandler` discovers
    callbacks, `handlers/scheduler.py:29` `list_callbacks`).
  - The callback loads the recipe, REQUIRES `recipe.schedule.principal`, resolves that
    principal's permission context and runs under it; a missing/deprovisioned principal fails
    the run with the standard permission diagnostic — NEVER falls back to a server identity
    (spec G8 + §7 risk).
  - Optional post-run delivery via the recipe's `render.delivery` (runner handles it).
- Tests: handler CRUD + run (mocked runner/store), 422 shape on drift, 404 shape,
  scheduler callback principal enforcement.

**NOT in scope**: creating scheduler jobs themselves (users do that via the existing
`SchedulerJobsHandler`), the runner internals, docs (TASK-1873).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/handlers/infographic_recipes.py` | CREATE | RecipeHandler + scheduler callback |
| (server route-registration module — locate the existing site) | MODIFY | register RecipeHandler routes + callback |
| `packages/ai-parrot-server/tests/handlers/test_infographic_recipes.py` | CREATE | handler + callback tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.outputs.a2ui.recipes.models import InfographicRecipe, RecipeRunError  # TASK-1865
from parrot.outputs.a2ui.recipes.store import AbstractRecipeStore, DBRecipeStore  # TASK-1868
from parrot.tools.infographic_recipes.runner import RecipeRunner, RecipeRunException  # TASK-1869
# BaseView import: read packages/ai-parrot-server/src/parrot/handlers/datasets.py header
# for the exact import path used by DatasetManagerHandler (line 141) and copy it verbatim.
```

### Existing Signatures to Use
```python
# packages/ai-parrot-server/src/parrot/handlers/datasets.py — HANDLER PATTERN
class DatasetManagerHandler(BaseView):        # line 141 — read post_init/auth/error style

# packages/ai-parrot-server/src/parrot/handlers/scheduler.py — SCHEDULER REST (existing)
class SchedulerCatalogHelper(BaseHandler):    # line 14
    def list_callbacks() -> list[dict[str, Any]]:  # line 29 — how callbacks are discovered
class SchedulerJobsHandler(BaseView):         # line 52 — get:70 post:90 patch:119 delete:141
class SchedulerCallbacksHandler(BaseView):    # line 33

# packages/ai-parrot-server/src/parrot/scheduler/manager.py — SCHEDULER CORE (existing)
class ScheduleType(Enum):                     # line 52 — ONCE/DAILY/.../CRONTAB
def schedule(schedule_type=..., *, success_callback=None, send_result=None,
             callbacks=None, **schedule_config):  # line 63 — decorator attaching _schedule_config
class AgentSchedulerManager:                  # line 284
    def __init__(self, bot_manager: Any = None, **kwargs):  # line 296
    def _prepare_call_arguments(self, ...):   # line 336
# READ manager.py 280-450 before wiring: how jobs bind callbacks and how the manager is
# attached to the aiohttp app (find where AgentSchedulerManager is instantiated in the
# server startup — grep "AgentSchedulerManager(" in ai-parrot-server).
```

### Does NOT Exist
- ~~`RecipeHandler` / recipe routes~~ — created by THIS task
- ~~A recipe-specific scheduler~~ — jobs are ordinary AgentSchedulerManager jobs pointing at
  the new callback; do NOT create scheduling models/tables
- ~~`ScheduleSpec` cron fields~~ — the recipe's `ScheduleSpec` holds ONLY `principal`
  (spec §2 Data Models); cron/interval config lives in the scheduler job, not the recipe
- ~~Server-identity fallback for scheduled runs~~ — explicitly forbidden (G8 acceptance
  criterion); missing principal = failed run

---

## Implementation Notes

### Key Constraints
- Error responses use the handler pattern's error helper (see
  `SchedulerJobsHandler._error_response`, scheduler.py:67) — 422 body is exactly
  `RecipeRunError.model_dump()` plus `status: "error"` envelope consistent with sibling
  handlers.
- Owner scoping: derive owner/user from the request session the same way
  `DatasetManagerHandler` does — read its auth extraction and copy it.
- The scheduler callback must be discoverable in `SchedulerCallbacksHandler` listing
  (that is the operator's way to wire a job to it).
- Async throughout; `self.logger` on every request/run.

### References in Codebase
- `packages/ai-parrot-server/src/parrot/handlers/datasets.py` — BaseView CRUD pattern
- `packages/ai-parrot-server/src/parrot/handlers/scheduler.py` + `scheduler/manager.py` —
  callback registration + job binding
- `sdd/specs/infographic-builder.spec.md` §3 Module 8 — normative scope

---

## Acceptance Criteria

- [ ] CRUD + run endpoints implemented and route-registered
- [ ] `test_recipe_handler_run_422_on_drift` — 422 with structured `RecipeRunError`
- [ ] Unknown recipe → 404 listing available names
- [ ] `test_scheduler_callback_uses_principal` — callback runs under `schedule.principal`;
      missing principal fails, NEVER falls back to server identity
- [ ] Callback appears in `SchedulerCallbacksHandler` listing
- [ ] All tests pass: `pytest packages/ai-parrot-server/tests/handlers/test_infographic_recipes.py -v`
- [ ] `ruff check` clean

---

## Test Specification

```python
# packages/ai-parrot-server/tests/handlers/test_infographic_recipes.py
class TestRecipeHandler:
    async def test_put_get_list_delete_roundtrip(self, client, mocked_store): ...
    async def test_run_returns_artifact_metadata(self, client, mocked_runner): ...
    async def test_recipe_handler_run_422_on_drift(self, client, mocked_runner): ...
    async def test_run_unknown_recipe_404_lists_available(self, client): ...

class TestSchedulerCallback:
    async def test_scheduler_callback_uses_principal(self, ...): ...
    async def test_missing_principal_fails_no_fallback(self, ...): ...
```

---

## Agent Instructions

1. **Read the spec** (§3 Module 8, G6/G8) and the two scheduler files before wiring anything
2. **Check dependencies** — TASK-1869 completed; read the real runner API
3. **Verify the Codebase Contract** — locate the actual route-registration site and
   AgentSchedulerManager instantiation before modifying
4. **Update status** in `sdd/tasks/index/infographic-builder.json` → `"in-progress"`
5. **Implement**, **verify** acceptance criteria
6. **Move this file** to `sdd/tasks/completed/`, update index → `"done"`, fill Completion Note

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**:
