# TASK-4855: MetricDefinitionsHandler — /api/v1/metrics REST lane

**Feature**: FEAT-756 — Metric Definition Registry
**Spec**: `sdd/specs/metric-definition-registry.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4848
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 9 / G8 / D5. This is a minimal tenant-scoped REST lane over `PgMetricDefinitionStore` (TASK-4848):
- `GET` list / schema / one;
- `POST` create and `PUT` replace, gated by `RequestScope.may_author`.

The tenant always comes from the scope and never from the body. Open questions Q3 and Q4 were resolved to the
spec defaults: writes ship now, and a global (`tenant=None`) definition needs `is_superuser`.

---

## Scope

- Implement `UpsertMetricRequest` and `MetricDefinitionsHandler(BaseView)` with `get`/`post`/`put`, dispatching on `match_info` and the path.
- Write unit tests using the `test_ui_surfaces_handler.py` idiom (`__new__`, unwrap `__wrapped__`, fake request, AsyncMock store).

**NOT in scope**: route registration in `manager.py` (TASK-4856), `DELETE`, bulk import, and any edit to `handlers/ui_surfaces.py`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/handlers/metric_definitions.py` | CREATE | handler + request model |
| `packages/ai-parrot-server/tests/handlers/test_metric_definitions_handler.py` | CREATE | handler unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from aiohttp import web                                       # verified: handlers/ui_surfaces.py:25
from navigator.views import BaseView                          # verified: handlers/ui_surfaces.py:26
from navigator_auth.decorators import is_authenticated, user_session   # verified: handlers/ui_surfaces.py:28
from parrot.handlers.scope import RequestScope, get_scope_resolver     # verified: handlers/scope.py:40, :142
from parrot.handlers.ui_surfaces import _get_user_id          # verified: handlers/ui_surfaces.py:134 (module-level private helper; importable)
from parrot.handlers.models.metric_definitions import PgMetricDefinitionStore   # created by TASK-4848
from parrot.metrics import MetricDefinition                   # created by TASK-4843 (json_schema_v1 classmethod)
from pydantic import BaseModel, ValidationError
```

### Existing Signatures to Use
```python
# packages/ai-parrot-server/src/parrot/handlers/ui_surfaces.py (PATTERN)
@is_authenticated()
@user_session()
class UISurfacesHandler(BaseView):                 # L326-328
    _logger_name: str = "Parrot.UISurfaces"        # L336
    def post_init(self, *args, **kwargs): self.logger = logging.getLogger(self._logger_name)   # L338
    @property
    def store(self): app.get("ui_surfaces_store") or create + cache   # L344
    async def _scope(self): return await get_scope_resolver(self.request.app).resolve(self.request)   # L381
    def _error(self, message, *, status=400): return self.json_response({"status": "error", "message": message}, status=status)   # L390 — BaseView.error() status whitelist landmine
    async def get(self) L406; async def post(self) L415
# handlers/scope.py:40-59 RequestScope(user_id, tenant, groups, is_superuser=False, may_author=True, may_administer=False)
# PgMetricDefinitionStore (TASK-4848): get(metric_id, *, tenant), save(definition, *, overwrite) (ValueError on dup), list_visible(scope, *, program)
```

### Does NOT Exist
- ~~`PublishSurfaceRequest`-style tenant field~~ — the body must not carry `tenant`/`owner` (422 when present).
- ~~`MetricDefinitionsHandler.delete`~~ — DELETE is deferred (D5).
- ~~`BaseView.error(status=409/422)`~~ — the whitelist falls back to 400; use `_error`.
- ~~`/api/v1/metrics` routes in `manager.py`~~ — added by TASK-4856.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-server/src/parrot/handlers/metric_definitions.py", "action": "CREATE"},
    {"path": "packages/ai-parrot-server/tests/handlers/test_metric_definitions_handler.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-server/src/parrot/handlers/ui_surfaces.py#UISurfacesHandler",
    "sym:packages/ai-parrot-server/src/parrot/handlers/ui_surfaces.py#_get_user_id",
    "sym:packages/ai-parrot-server/src/parrot/handlers/scope.py#get_scope_resolver",
    "sym:packages/ai-parrot-server/src/parrot/handlers/scope.py#RequestScope"
  ]
}
```

---

## Implementation Notes

- Status codes (AC-10):
  - 401 when there is no user id;
  - 403 when `not scope.may_author` on a write;
  - 404 for a GET of a missing or invisible metric (never 403 — existence is not disclosed);
  - 409 on a duplicate POST;
  - 422 on `tenant`/`owner` in the body or on a validation error;
  - 201 for a create and 200 for a replace.
- Server-set fields: `tenant := scope.tenant` and `owner := user_id`. A global definition (`scope.tenant is None`) requires `scope.is_superuser`, otherwise 403.
- PUT: 404 when the definition is absent in the scope's tenant; 403 unless the caller is the owner or `scope.may_administer`; bump `version`.
- GET one: resolve visibility through `list_visible(scope)` filtered by id, so the store's single PBAC rule applies.

---

## Implementation Blueprint

### Steps (in order)
1. Create the handler module. *Why*: one `BaseView` dispatching on the path, the same idiom as UISurfacesHandler (spec §7).
2. Write the tests with fake request/app objects. *Why*: they need no aiohttp middleware.

### `packages/ai-parrot-server/src/parrot/handlers/metric_definitions.py` (CREATE)
```python
"""REST lane of the FEAT-756 metric registry: /api/v1/metrics[/schema|/{metric_id}]."""
from __future__ import annotations

import logging
from typing import Any

from aiohttp import web
from navigator.views import BaseView
from navigator_auth.decorators import is_authenticated, user_session
from parrot.handlers.models.metric_definitions import PgMetricDefinitionStore
from parrot.handlers.scope import RequestScope, get_scope_resolver
from parrot.handlers.ui_surfaces import _get_user_id
from parrot.metrics import MetricDefinition
from pydantic import BaseModel, ValidationError

_SERVER_SET_FIELDS = ("tenant", "owner")


class UpsertMetricRequest(BaseModel):
    """``definition: dict`` — a ``MetricDefinition`` WITHOUT ``tenant`` / ``owner`` (server-set; 422 when present)."""

    definition: dict[str, Any]


@is_authenticated()
@user_session()
class MetricDefinitionsHandler(BaseView):
    """REST lane of the metric registry (UISurfacesHandler idiom: one view, dispatch on match_info/path)."""

    _logger_name: str = "Parrot.MetricDefinitions"

    def post_init(self, *args: Any, **kwargs: Any) -> None:
        self.logger = logging.getLogger(self._logger_name)

    @property
    def store(self) -> PgMetricDefinitionStore:
        """``app["metric_definitions_store"]`` or a lazily created ``PgMetricDefinitionStore()``."""
        store = self.request.app.get("metric_definitions_store")
        if store is None:
            store = PgMetricDefinitionStore()
            self.request.app["metric_definitions_store"] = store
        return store

    async def _scope(self) -> RequestScope:
        """Resolve once per request (ui_surfaces.py:381-388)."""
        return await get_scope_resolver(self.request.app).resolve(self.request)

    def _error(self, message: str, *, status: int = 400) -> web.Response:
        """Direct ``json_response`` (ui_surfaces.py:390-404 rationale)."""
        return self.json_response({"status": "error", "message": message}, status=status)

    async def get(self) -> web.Response:
        """``/schema`` → JSON Schema; ``{metric_id}`` → 200 | 404; list → ``store.list_visible(scope, program=)``."""
        if self.request.path.rstrip("/").endswith("/schema"):
            return self.json_response(MetricDefinition.json_schema_v1())
        # FILL IN: scope; metric_id from match_info → filter list_visible by id → 200 dump(mode="json") | 404;
        #   list → ?program= → 200 [dumps]. Bounded by AC-10.

    async def post(self) -> web.Response:
        """Create: 401/403/422 gates; tenant := scope.tenant; global needs is_superuser; 409 duplicate; 201."""
        # FILL IN: user_id = await _get_user_id(self.request) → 401; scope.may_author → 403; body → UpsertMetricRequest
        #   (ValidationError → 422); any _SERVER_SET_FIELDS key in definition → 422; build MetricDefinition with
        #   tenant/owner set (ValidationError → 422); store.save(overwrite=False) ValueError → 409; 201.

    async def put(self) -> web.Response:
        """Replace: same gates; owner or may_administer only; 404 when absent; 200."""
        # FILL IN: metric_id from match_info (body id must equal it → else 422); existing = store.get(id, tenant=scope.tenant)
        #   → 404; owner/may_administer → 403; version = existing.version + 1; save(overwrite=True); 200.
```
**Why this shape**: it is a copy of the UISurfacesHandler conventions. `_error` avoids the BaseView status whitelist, and
the tenant is never read from the body (spec §7, D3).

### `packages/ai-parrot-server/tests/handlers/test_metric_definitions_handler.py` (CREATE)
```python
"""Unit tests for MetricDefinitionsHandler (FEAT-756, TASK-4855) — test_ui_surfaces_handler.py idiom."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from parrot.handlers.metric_definitions import MetricDefinitionsHandler
from parrot.handlers.scope import RequestScope

pytestmark = pytest.mark.asyncio

# FILL IN: _make_handler(scope, store, *, path, match_info, body, user_id) — __new__, app dict with
#   "metric_definitions_store", patch _scope/_get_user_id, json_response stub returning SimpleNamespace(status, body);
#   unwrap methods via __wrapped__ (test_ui_surfaces_handler.py:71-80).


async def test_metric_handler_get_list_scope_filter() -> None:
    """list uses list_visible(scope, program=); one → 200 | 404 for invisible; /schema → schema dict."""
    # FILL IN


async def test_metric_handler_post_put_gates() -> None:
    """401 no user / 403 !may_author / 403 global without superuser / 422 tenant in body / 409 dup / 201 / PUT 404 / 403 non-owner / 200."""
    # FILL IN
```

### FILL IN checklist
- [ ] `get` one/list branches
- [ ] `post` gates in order 401 → 403 → 422 → 409 → 201
- [ ] `put` gates and version bump
- [ ] test harness and both tests

---

## Acceptance Criteria

- [ ] `GET /api/v1/metrics`, `/schema` and `/{metric_id}` plus `POST` and `PUT` behave as spec §3 M9 (401/403/404/409/422/201/200).
- [ ] The tenant is always server-set, and the body's `tenant`/`owner` are rejected with 422.
- [ ] No diff in `handlers/ui_surfaces.py` or `manager.py`.
- [ ] `ruff check` is clean.

---

## Validation Commands
- `pytest packages/ai-parrot-server/tests/handlers/test_metric_definitions_handler.py -q`

---

## Test Specification

See the blueprint test file: `test_metric_handler_get_list_scope_filter` and `test_metric_handler_post_put_gates`.

---

## Agent Instructions

1. Work in the feature worktree; confirm TASK-4848 is `done`.
2. Re-verify the contract. If `_get_user_id` has moved, copy its body locally instead of inventing an import.
3. Run with `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-server/src`.
4. Commit only the listed files, then run `scripts/sdd/close_task.sh TASK-4855 metric-definition-registry verified`.

---

## Completion Note

*(Agent fills this in when done)*
