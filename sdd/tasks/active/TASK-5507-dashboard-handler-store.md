# TASK-5507: Dashboard handlers on top of `DashboardStore`

**Feature**: FEAT-878 — Redis user stores (MongoDB-free local installs)
**Spec**: `sdd/specs/redis-user-stores.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-5506
**Assigned-to**: unassigned

---

## Context

Spec §2 "Dashboards", §3 Module 10 (handler half), AC10. With `DashboardStore` available (TASK-5506),
`DashboardHandler` and `DashboardTabHandler` stop opening DocumentDB and call `get_dashboard_store()`.
URLs, request bodies, response bodies and status codes stay the same, plus `409` on a duplicate create.
`_ensure_dashboard_indexes` delegates to `store.ensure_indexes()`, so startup does not contact MongoDB when
dashboards live in Redis (its call site in `manager.py:3238` is unchanged).

---

## Scope

- Replace the 13 `async with DocumentDb() as db:` blocks with `DashboardStore` calls (one store per request via `get_dashboard_store()`).
- `post` (dashboard) and tab `post`: answer `409` with `{"message": "Dashboard '<id>' already exists"}` /
  `{"message": "Tab '<id>' already exists"}` when `create_*` returns `False`.
- `_ensure_dashboard_indexes(app)` → `await get_dashboard_store().ensure_indexes()` inside the existing try/except.
- Remove the `DocumentDb` import and the module-level collection constants only if nothing else uses them.
- Handler tests with an in-memory/Redis store.

**NOT in scope**: the stores (TASK-5506), `manager.py` route registration.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/handlers/dashboard_handler.py` | MODIFY | handlers use `DashboardStore`; 409 on duplicates |
| `packages/ai-parrot-server/tests/unit/test_dashboard_handler_store.py` | CREATE | handler tests (Redis store, db 15) |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.handlers.dashboard_store import get_dashboard_store   # TASK-5506 (relative: from .dashboard_store import get_dashboard_store)
```

### Existing Signatures to Use
```python
# packages/ai-parrot-server/src/parrot/handlers/dashboard_handler.py
from ..interfaces.documentdb import DocumentDb                           # line 30 — remove
DASHBOARDS_COLLECTION = "dashboards"; TABS_COLLECTION = "dashboard_tabs"  # lines 33-34
async def _ensure_dashboard_indexes(app: web.Application) -> None:       # line 37 — wraps index creation in try/except → logger.warning
class DashboardHandler(BaseView):                                        # line 74
    def _dashboard_id(self) -> Optional[str]:                            # line 85
    def _user_id(self) -> Optional[str]:                                 # line 89
    async def get(self) -> web.Response:                                 # line 99
    async def _get_one(self, dashboard_id: str) -> web.Response:         # line 111 — 404 {"message": "Dashboard '<id>' not found"}; body = dashboard + "tabs"
    async def _get_list(self) -> web.Response:                           # line 138 — {"dashboards": [...], "total": n}
    async def post(self) -> web.Response:                                # line 164 — dashboard_id = data.get("dashboard_id") or uuid4().hex; 201
    async def put(self) -> web.Response:                                 # line 208
    async def patch(self) -> web.Response:                               # line 259
    async def delete(self) -> web.Response:                              # line 312
class DashboardTabHandler(BaseView):                                     # line 341
    async def get(self) -> web.Response:                                 # line 367
    async def _get_one_tab(self, dashboard_id: str, tab_id: str) -> web.Response:  # line 385
    async def _get_tabs(self, dashboard_id: str) -> web.Response:        # line 400
    async def post(self) -> web.Response:                                # line 418 — 404 when parent missing; next index = len(existing tabs)
    async def put(self) -> web.Response:                                 # line 495
    async def patch(self) -> web.Response:                               # line 552
    async def delete(self) -> web.Response:                              # line 607
# `async with DocumentDb() as db:` occurs 13× (first at line 45) → disambiguate by method.

# packages/ai-parrot-server/src/parrot/manager/manager.py
#   line 74 imports _ensure_dashboard_indexes; line 3238 `await _ensure_dashboard_indexes(app)` (inside `if ENABLE_DASHBOARDS:`) — unchanged
```

### Does NOT Exist
- ~~`DocumentDb` in `parrot.handlers.dashboard_handler` after this task~~.
- ~~Existing dashboard handler tests~~ — none exist today; this task adds the first.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-server/src/parrot/handlers/dashboard_handler.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-server/tests/unit/test_dashboard_handler_store.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-server/src/parrot/handlers/dashboard_handler.py#DashboardHandler",
    "sym:packages/ai-parrot-server/src/parrot/handlers/dashboard_handler.py#DashboardTabHandler",
    "sym:packages/ai-parrot-server/src/parrot/handlers/dashboard_handler.py#_ensure_dashboard_indexes"
  ]
}
```

---

## Implementation Blueprint

### Steps (in order)
1. Rewrite `_ensure_dashboard_indexes` — *why*: no MongoDB contact at startup on Redis (AC10).
2. Rewrite each handler method's data access, one method at a time, keeping its validation and response code — *why*: HTTP contract unchanged.
3. Add the two 409 branches — *why*: spec §2 duplicate create.
4. Remove the `DocumentDb` import; write handler tests.

### `packages/ai-parrot-server/src/parrot/handlers/dashboard_handler.py` (MODIFY — startup + imports)
```python
# occurrences: 1 (verified: grep -c 'from ..interfaces.documentdb import DocumentDb' .../handlers/dashboard_handler.py)
# REPLACE line 30 with:
from .dashboard_store import get_dashboard_store
# occurrences: 1 (verified: grep -c 'async def _ensure_dashboard_indexes(app: web.Application) -> None:' .../dashboard_handler.py)
# REPLACE the body of _ensure_dashboard_indexes (line 37) with:
    logger = logging.getLogger("Parrot.DashboardHandler")
    try:
        await get_dashboard_store().ensure_indexes()
    except Exception as exc:  # noqa: BLE001 — startup must not fail on index creation (unchanged behaviour)
        logger.warning("Failed to create dashboard indexes: %s", exc)
```

### `packages/ai-parrot-server/src/parrot/handlers/dashboard_handler.py` (MODIFY — handlers)
```python
# occurrences: 13 (verified: grep -c 'async with DocumentDb() as db:' .../dashboard_handler.py) — disambiguate by method:
# _get_one (111):
        store = get_dashboard_store()
        dashboard = await store.get_dashboard(dashboard_id)
        if not dashboard:
            return self.error(response={"message": f"Dashboard '{dashboard_id}' not found"}, status=404)
        dashboard["tabs"] = await store.list_tabs(dashboard_id)
        return self.json_response(dashboard)
# post (164): replace `async with DocumentDb() as db: await db.write(DASHBOARDS_COLLECTION, doc)` with
        if not await get_dashboard_store().create_dashboard(doc):
            return self.error(response={"message": f"Dashboard '{dashboard_id}' already exists"}, status=409)
# FILL IN: _get_list (138) → list_dashboards(module_id=..., user_id=...); put (208)/patch (259) → update_dashboard
#   returning 404 when False; delete (312) → delete_dashboard (404 when False); tab handlers (385, 400, 418, 495, 552, 607)
#   → get_tab / list_tabs / dashboard_exists + list_tabs + create_tab (409 "Tab '<id>' already exists") / update_tab /
#   delete_tab. Keep every existing validation branch, message and status verbatim.
```
**Why**: one `get_dashboard_store()` per request picks up `DASHBOARDS_STORE` at call time, like every other FEAT-878 dispatcher.

### FILL IN checklist
- [ ] 11 remaining method rewrites with unchanged messages/status codes
- [ ] tab `post` 409
- [ ] unused constants/imports removed (check `grep -c DASHBOARDS_COLLECTION` first)

---

## Acceptance Criteria

- [ ] `dashboard_handler.py` has no `DocumentDb` reference
- [ ] Dashboards CRUD over HTTP works on Redis with identical URLs/bodies; duplicate create → 409 (AC10)
- [ ] `_ensure_dashboard_indexes` makes no DocumentDB call when `DASHBOARDS_STORE` resolves to `redis` (AC10)
- [ ] `ruff check` clean

---

## Validation Commands
- `pytest packages/ai-parrot-server/tests/unit/test_dashboard_handler_store.py -q`

---

## Test Specification

```python
# packages/ai-parrot-server/tests/unit/test_dashboard_handler_store.py
import pytest
from aiohttp import web

from parrot.handlers.dashboard_handler import DashboardHandler, DashboardTabHandler, _ensure_dashboard_indexes
from parrot.userstore.testing import redis_test_settings


@pytest.fixture
async def client(aiohttp_client, monkeypatch):
    monkeypatch.delenv("DASHBOARDS_STORE", raising=False)
    monkeypatch.delenv("PARROT_USER_STORE", raising=False)
    async with redis_test_settings(monkeypatch):
        app = web.Application()
        app.router.add_view("/api/v1/dashboards", DashboardHandler)
        app.router.add_view("/api/v1/dashboards/{dashboard_id}", DashboardHandler)
        app.router.add_view("/api/v1/dashboards/{dashboard_id}/tabs", DashboardTabHandler)
        app.router.add_view("/api/v1/dashboards/{dashboard_id}/tabs/{tab_id}", DashboardTabHandler)
        # FILL IN: if BaseView needs session/auth stubs, copy the minimal setup other handler tests use
        yield await aiohttp_client(app)


async def test_dashboard_crud_redis(client): ...          # POST 201 → GET one (tabs []) → PATCH → GET list → DELETE → GET 404
async def test_dashboard_duplicate_create_409(client): ...
async def test_tab_crud_and_order(client): ...
async def test_ensure_indexes_no_documentdb(monkeypatch): ...  # DocumentDb patched to fail if constructed
```

---

## Agent Instructions

1. **Work in the feature worktree** — `parrot sdd worktree ensure --slug redis-user-stores --feature-id FEAT-878`
2. **Read the spec** (§2 Dashboards, §3 M10, AC10)
3. **Check dependencies** — TASK-5506 must be `done`
4. **Verify the Codebase Contract** (re-run each `grep -c`)
5. **Update status** → `"in-progress"`, commit only the index file
6. **Implement** from the blueprint, complete every `# FILL IN:`
7. **Verify** — Validation Commands with `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-server/src`
8. **Commit the code** — only the files listed above
9. **Close the task** — `parrot sdd task close TASK-5507 redis-user-stores verified`
10. **Fill in the Completion Note**, commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
