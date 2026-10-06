# TASK-4108: HTTP endpoint `POST /api/v1/ui/surfaces/{surface_id}/sources/{key}/data`

**Feature**: FEAT-636 — Linked A2UI surfaces — server-executed Python recipe transformers
**Spec**: `sdd/specs/linked-a2ui-recipes-transforms.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4107
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 5. The renderer's dynamic fetch lane for python-transformed sources. The handler resolves access and
picks the identity; execution is `LinkedSurfaceService.fetch_source` (TASK-4107). Identity rule (proposal U1/U4, codex S3):

| How access was granted (`resolve_surface_access` order: owner → scope → share token) | pctx used |
|---|---|
| caller is the owner (`record.user_id == user_id`) | caller (= owner) |
| caller granted by scope (`scope_grants(record, scope)`) | **caller** (viewer) |
| granted ONLY by a share token | **owner** (`record.user_id`) — same rule as `_refresh` (`ui_surfaces.py:645-647`) |

`UISurfacesHandler` is `@is_authenticated()` (line 313), so a share viewer here always has a session user;
`resolve_surface_access` does not expose which branch granted access, so the handler re-derives it with the same
predicates, in the same order.

**Spec correction**: spec §6 Edit Sites lists `handlers/models/ui_surfaces.py` for the request model (marked
unverified). `RefreshSurfaceRequest` actually lives in `handlers/ui_surfaces.py:96`; `SourceDataRequest` goes beside
it, and `handlers/models/ui_surfaces.py` is NOT touched.

---

## Scope

- Add `SourceDataRequest` (params only — S2) beside `RefreshSurfaceRequest`.
- Dispatch `path.endswith("/data")` in `post()` to a new `_source_data()`.
- Implement `_source_data()`: access → identity rule → `fetch_source` → error mapping → JSON response.
- Register the route in `manager.py`.
- Write the auth/error matrix tests.

**NOT in scope**: the renderer (TASK-4111); persistence (the endpoint never writes).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/handlers/ui_surfaces.py` | MODIFY | `SourceDataRequest`, `post()` dispatch, `_source_data()` |
| `packages/ai-parrot-server/src/parrot/manager/manager.py` | MODIFY | route registration |
| `packages/ai-parrot-server/tests/handlers/test_ui_surfaces_source_data.py` | CREATE | auth/error matrix |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# already imported in packages/ai-parrot-server/src/parrot/handlers/ui_surfaces.py:
from parrot.auth.exceptions import AuthorizationRequired                 # line 30
from parrot.auth.permission import build_principal_context              # line 31
from parrot.handlers.ui_surfaces_scope import SurfaceScope, get_scope_resolver, scope_grants  # line 39-43
from parrot.outputs.a2ui.linked import has_data_sources                 # line 46
from parrot.outputs.a2ui.linked.service import LinkedGuardRequired, LinkedSurfaceService, SnapshotError  # line 47
from pydantic import BaseModel, Field, ValidationError                  # line 50
# tests:
from parrot.outputs.a2ui.linked.service import SourceFetchOutcome       # created by TASK-4107
```

### Existing Signatures to Use
```python
# packages/ai-parrot-server/src/parrot/handlers/ui_surfaces.py
class RefreshSurfaceRequest(BaseModel): params: dict[str, Any] = Field(default_factory=dict)   # line 96-99
async def resolve_surface_access(store, surface_id, user_id, token, *, scope=None)             # line 167; owner→scope→token→404; bad token 410
class UISurfacesHandler(BaseView):                                         # line 313 (@is_authenticated, @user_session)
    def _linked_service(self) -> LinkedSurfaceService                      # line 346 (app["linked_surface_service"] cache)
    async def _user_id(self) -> str | None                                 # line 365
    async def _scope(self) -> SurfaceScope                                 # line 368
    def _error(self, message: str, *, status: int = 400) -> web.Response   # line 377 (any status; never BaseView.error)
    async def post(self) -> web.Response                                   # line 402-409: endswith("/refresh") | ("/share") | pin_save
    async def _resolve_surface_for_access(self, surface_id, user_id, token, scope=None)  # line 430 → (record, None) | (None, response)
    async def _refresh(self)                                               # line 617; token from self.query_parameters(self.request).get("share") at 624-625
    async def _refresh_linked(...)                                         # line 688; LinkedGuardRequired→403, AuthorizationRequired→403 at 697-704
# UISurfaceRecord: .user_id, .envelope (dict), .recipe_name (None for linked)

# packages/ai-parrot-server/src/parrot/manager/manager.py:2420-2425 — router.add_view(..., UISurfacesHandler) block

# packages/ai-parrot/src/parrot/outputs/a2ui/linked/service.py (TASK-4107)
async def fetch_source(self, envelope, key, *, params, pctx) -> SourceFetchOutcome
class SourceFetchOutcome: key; rows; truncated; snapshot_at; warnings; error_status; error_code

# tests harness: packages/ai-parrot-server/tests/handlers/test_ui_surfaces_linked_handler.py
#   _FakeRequest(app, match_info, path, json_body, user_id, query) line 21; _handler line 37; _post line 50;
#   _decode line 58; _linked_envelope line 62; _make_record line 106; _store line 127; _app line 145
```

### Does NOT Exist
- ~~`SourceDataRequest`~~ / ~~`UISurfacesHandler._source_data`~~ / ~~the `/sources/{key}/data` route~~ — created here.
- ~~an access-mode return value from `resolve_surface_access`~~ — it returns `(record, error)` only; re-derive the mode.
- ~~unauthenticated share access in this handler~~ — the class is `@is_authenticated()`.
- ~~`handlers/models/ui_surfaces.py` changes~~ — not touched (see Spec correction).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-server/src/parrot/handlers/ui_surfaces.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-server/src/parrot/manager/manager.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-server/tests/handlers/test_ui_surfaces_source_data.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-server/src/parrot/handlers/ui_surfaces.py#UISurfacesHandler",
    "sym:packages/ai-parrot-server/src/parrot/handlers/ui_surfaces.py#UISurfacesHandler.post",
    "sym:packages/ai-parrot-server/src/parrot/handlers/ui_surfaces.py#RefreshSurfaceRequest",
    "sym:packages/ai-parrot-server/src/parrot/handlers/ui_surfaces.py#resolve_surface_access",
    "sym:packages/ai-parrot/src/parrot/outputs/a2ui/linked/service.py#LinkedSurfaceService"
  ]
}
```

---

## Implementation Blueprint

### Steps (in order)
1. Add `SourceDataRequest` below `RefreshSurfaceRequest` — *why*: S2, the body carries overrides only.
2. Add the `/data` branch FIRST in `post()` — *why*: suffix dispatch; `/data` never collides with `/refresh`/`/share`.
3. Implement `_source_data()` after `_refresh_linked` — *why*: it mirrors that method's error mapping.
4. Register the route — *why*: aiohttp needs the path; the class view dispatches by verb.
5. Write tests; run the Validation Commands.

### `packages/ai-parrot-server/src/parrot/handlers/ui_surfaces.py` (MODIFY — request model)
```python
# AFTER — insert below class RefreshSurfaceRequest (ui_surfaces.py:96-99)
class SourceDataRequest(BaseModel):
    """Body of ``POST /api/v1/ui/surfaces/{id}/sources/{key}/data`` — placeholder overrides only (FEAT-636 S2).

    Conditions are NEVER accepted from the client: the server rebuilds them from the persisted descriptor, so
    ``locked`` filters, tenant routing and ``querylimit`` cannot be tampered with.
    """

    params: dict[str, Any] = Field(default_factory=dict)
```

### `packages/ai-parrot-server/src/parrot/handlers/ui_surfaces.py` (MODIFY — dispatch)
```python
# occurrences: 1 (verified: grep -c 'if path.endswith("/refresh"):' handlers/ui_surfaces.py)
# BEFORE — insert immediately above `if path.endswith("/refresh"):` (ui_surfaces.py:405)
        if path.endswith("/data"):
            return await self._source_data()
```
Also update `post()`'s docstring to list `/sources/{key}/data`.

### `packages/ai-parrot-server/src/parrot/handlers/ui_surfaces.py` (MODIFY — _source_data)
```python
# AFTER — insert below _refresh_linked (ends ui_surfaces.py:734)
    async def _source_data(self) -> web.Response:
        """``POST /api/v1/ui/surfaces/{surface_id}/sources/{key}/data`` — guarded one-source fetch (FEAT-636).

        Returns ``{"status", "key", "rows", "truncated", "snapshot_at", "warnings"}``; never persists.
        Identity: owner/scope access → the caller's pctx; access granted ONLY by a share token → the owner's pctx.
        """
        surface_id = self.request.match_info.get("surface_id")
        key = self.request.match_info.get("key")
        if not surface_id or not key:
            return self._error("surface_id and key are required", status=400)
        user_id = await self._user_id()
        scope = await self._scope()
        token = self.query_parameters(self.request).get("share")
        record, err = await self._resolve_surface_for_access(surface_id, user_id, token, scope)
        if err is not None:
            return err
        if record.recipe_name is not None or not has_data_sources(record.envelope):
            return self._error("Surface has no linked data sources", status=404)
        try:
            body = await self.request.json()
        except Exception:  # noqa: BLE001
            body = {}
        try:
            req = SourceDataRequest.model_validate(body if isinstance(body, dict) else {})
        except ValidationError as exc:
            return self._error(f"Invalid request: {exc.errors()[0]['msg']}", status=400)

        # FILL IN: share_only = token is truthy AND record.user_id != user_id AND NOT (scope and scope_grants(record, scope));
        #   pctx = build_principal_context(record.user_id if share_only else user_id, channel="ui_surfaces")
        #   — bounded by U1/U4/AC8 (the identity table in this task's Context)
        pctx = None
        try:
            outcome = await self._linked_service().fetch_source(record.envelope, key, params=req.params, pctx=pctx)
        except LinkedGuardRequired:
            return self.json_response(
                {"status": "error", "message": "Linked surfaces require a data-plane guard"}, status=403
            )
        except AuthorizationRequired:
            return self.json_response({"status": "error", "message": "Data source not permitted"}, status=403)
        # FILL IN: outcome.error_status set → json_response({"status": "error", "message": "Data source unavailable",
        #   "code": outcome.error_code}, status=outcome.error_status) (404 stays "unavailable", never "denied" — FEAT-598 §7);
        #   else json_response({"status": "success", "key": key, "rows": outcome.rows, "truncated": outcome.truncated,
        #   "snapshot_at": outcome.snapshot_at.isoformat() if outcome.snapshot_at else None, "warnings": outcome.warnings})
        raise NotImplementedError
```
**Why**: the share-only predicate mirrors `resolve_surface_access`'s order exactly (owner → scope → token), so the handler
can never pick owner identity for a caller that also has scope access. Recipe surfaces (`recipe_name` set) have no
descriptors — 404, not a RecipeRunner call (spec §6 Does NOT Exist).

### `packages/ai-parrot-server/src/parrot/manager/manager.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'router.add_view("/api/v1/ui/surfaces/{surface_id}/refresh", UISurfacesHandler)' manager/manager.py)
# AFTER — insert below that line (manager.py:2422)
        router.add_view("/api/v1/ui/surfaces/{surface_id}/sources/{key}/data", UISurfacesHandler)
```

### `packages/ai-parrot-server/tests/handlers/test_ui_surfaces_source_data.py` (CREATE)
```python
"""FEAT-636 TASK-4108 — POST /api/v1/ui/surfaces/{id}/sources/{key}/data: identity + error matrix."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from parrot.auth.exceptions import AuthorizationRequired
from parrot.outputs.a2ui.linked.service import LinkedGuardRequired, SourceFetchOutcome

from .test_ui_surfaces_linked_handler import _app, _decode, _handler, _linked_service, _make_record, _post, _store

pytestmark = pytest.mark.asyncio
PATH = "/api/v1/ui/surfaces/surface-1/sources/activity/data"


def _service(outcome: SourceFetchOutcome | None = None):
    service = _linked_service()
    service.fetch_source = AsyncMock(return_value=outcome or SourceFetchOutcome(key="activity", rows=[{"a": 1}]))
    return service


async def test_owner_gets_rows_with_own_pctx():
    service = _service()
    response = await _post(_handler(_app(_store(_make_record()), service),
                                    match_info={"surface_id": "surface-1", "key": "activity"},
                                    path=PATH, json_body={"params": {"window": "30d"}}))
    assert response.status == 200
    assert (await _decode(response))["rows"] == [{"a": 1}]
    kwargs = service.fetch_source.call_args.kwargs
    assert kwargs["params"] == {"window": "30d"} and kwargs["pctx"].user_id == "user-1"


# FILL IN (AC8 matrix): share-token-only viewer (user_id="viewer-9", query={"share": "tok"}, store.resolve_share
#   returning a share for surface-1) → pctx.user_id == record owner; scope-granted viewer → own pctx;
#   no access → 404; bad token → 410
# FILL IN: LinkedGuardRequired → 403; AuthorizationRequired → 403
# FILL IN: SourceFetchOutcome(error_status=404, error_code="source_not_found") → 404 "unavailable";
#   error_status=422 code "transform_failed" → 422 (AC5)
# FILL IN: recipe surface (recipe_name set) → 404; body with "conditions" key is ignored — only params reach the service (AC7)
```

### FILL IN checklist
- [ ] identity predicate + pctx — U1/U4/AC8
- [ ] outcome → response mapping — AC5/AC8
- [ ] four test groups (matrix, guard/auth, error codes, recipe/body)

---

## Acceptance Criteria

- [ ] AC7 (spec): only `params` reach the service; client conditions are ignored.
- [ ] AC8 (spec): owner/scope → caller pctx; share-only → owner pctx; no guard → 403; PBAC denial → 403; unknown key/surface → 404; bad token → 410.
- [ ] AC5 (spec, HTTP half): transform-stage codes surface as 422.
- [ ] Existing handler suites unchanged (`test_ui_surfaces_linked_handler.py`, `test_ui_surfaces_handler.py`).
- [ ] `ruff check` clean.

---

## Validation Commands

- `pytest packages/ai-parrot-server/tests/handlers/test_ui_surfaces_source_data.py -q`
- `pytest packages/ai-parrot-server/tests/handlers/test_ui_surfaces_linked_handler.py -q`
- `pytest packages/ai-parrot-server/tests/handlers/test_ui_surfaces_handler.py -q`

---

## Agent Instructions

1. Work in the feature worktree (`python -m scripts.sdd.ensure_worktree --slug linked-a2ui-recipes-transforms --feature-id FEAT-636`), with `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-server/src`.
2. Confirm TASK-4107 is `done` in the per-spec index.
3. Verify the Codebase Contract; start from the blueprint; complete every `FILL IN` (remove the `raise NotImplementedError`).
4. Run the Validation Commands; commit only the listed files.
5. Close with `scripts/sdd/close_task.sh TASK-4108 linked-a2ui-recipes-transforms verified` and fill the Completion Note
   (record the Spec correction above under "Deviations from spec").

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: `SourceDataRequest` lives in `handlers/ui_surfaces.py` (beside `RefreshSurfaceRequest`), not `handlers/models/ui_surfaces.py`.
