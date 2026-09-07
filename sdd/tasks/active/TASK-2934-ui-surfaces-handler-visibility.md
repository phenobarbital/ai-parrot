# TASK-2934: Handler — scope-aware access rule, visible listing, visibility on save, `PATCH`, metadata

**Feature**: FEAT-535 — Tenant-aware, permission-based visibility for UI surfaces
**Spec**: `sdd/specs/ui-surfaces-tenant-visibility.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-2932, TASK-2933
**Assigned-to**: unassigned

---

## Context

Implements **Module 3** for the REST lane (`UISurfacesHandler`). The store
(TASK-2932) can list by scope and the resolver (TASK-2933) can produce one;
this task makes the handler use both: owner → scope → token access order,
one union list with `access` tags, `visibility`/`allowed_groups` on save with
the server-set `tenant`, a new `PATCH` verb, and richer metadata (including
the `recipe_name`/`recipe_params` FieldSync's FEAT-559 review asked for).

---

## Scope

`packages/ai-parrot-server/src/parrot/handlers/ui_surfaces.py`:
- `resolve_surface_access(store, surface_id, user_id, token, *, scope: SurfaceScope | None = None)` — after the owner check and BEFORE the token branch: `if scope is not None and scope_grants(record, scope): return record, None`. Docstring: order and why (a token still works for a foreign tenant).
- `PublishSurfaceRequest`: `visibility: SurfaceVisibility = SurfaceVisibility.private`, `allowed_groups: list[str] = Field(default_factory=list)`. No `tenant` field (pydantic default `extra` ignores a body `tenant`).
- `class PatchVisibilityRequest(BaseModel)`: `visibility: SurfaceVisibility`, `allowed_groups: list[str] = Field(default_factory=list)`.
- `UISurfacesHandler`:
  - `async def _scope(self) -> SurfaceScope`: `await get_scope_resolver(self.request.app).resolve(self.request)`; used by `get`, `post`, `patch`.
  - `_resolve_surface_for_access(...)` passes `scope=`.
  - `_get_list(user_id, scope)`: `visible = await self.store.list_visible(scope, kind=kind)`; `shared = await self.store.list_shared_with(user_id)` (filtered by kind as today); dedupe by `surface_id` — tag `owner` when `record.user_id == user_id`, else `tenant` for anything from `list_visible`, else `shared`; a surface present in both lists appears once (visible wins).
  - `_pin_save`: `visibility`/`allowed_groups` from the body; `tenant=scope.tenant`; if `req.visibility is not private and scope.tenant is None` → `self._error("visibility requires a tenant scope", status=422)`; `400` on an invalid visibility value (pydantic `ValidationError` path already returns 400 — confirm).
  - `async def patch(self) -> web.Response` → `_patch_visibility()`: `surface_id` from `match_info` (`400` if absent), `user_id` (`401` if none), body → `PatchVisibilityRequest` (`400` on validation error); if `visibility != private` the STORED record's `tenant` must be non-null else `422`; `ok = await self.store.update_visibility(surface_id, user_id, visibility, allowed_groups)`; `404` when `False` (no oracle); `200` with `{"status": "success", "metadata": _surface_metadata(updated)}`.
  - `_surface_metadata(record)`: add `tenant`, `visibility` (`.value`), `allowed_groups`, `recipe_name`, `recipe_params`.
  - `_refresh`: no rule change beyond the scope-aware access (viewers may refresh; owner pctx stays — assert in a test that `build_principal_context(record.user_id, ...)` is what runs).
- Tests (`tests/handlers/test_ui_surfaces_handler.py`): extend `fake_store` with `list_visible`/`update_visibility` `AsyncMock`s; install a stub resolver on the app dict (`app["ui_surfaces_scope_resolver"] = _StubResolver(scope)`); add: list union + tags + dedupe; `422` on tenant-less non-private publish and `201` with `record.tenant == scope.tenant` (inspect `store.save.call_args`); body `tenant` ignored; `PATCH` owner `200` / non-owner `404` / bad body `400` / `422` rule; viewer `GET` JSON+HTML `200`, viewer `refresh` `200` with owner pctx, viewer `DELETE` `404`, viewer share-mint `404`; metadata fields present. Mutation check: make `scope_grants` return `False` → viewer tests RED.

**NOT in scope**: `A2UIHandler` mirror and the e2e test (TASK-2935); docs (TASK-2936).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/handlers/ui_surfaces.py` | MODIFY | access rule kwarg, request models, `_scope`, list union, save fields, `patch`, metadata |
| `packages/ai-parrot-server/tests/handlers/test_ui_surfaces_handler.py` | MODIFY | fixtures + new tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.handlers.ui_surfaces_scope import SurfaceScope, get_scope_resolver, scope_grants, EMPTY_SCOPE   # TASK-2933
from parrot.handlers.models.ui_surfaces import PgUISurfaceStore, UISurfaceRecord, UISurfaceKind, SurfaceVisibility   # TASK-2932
from pydantic import BaseModel, Field, ValidationError                 # already imported (ui_surfaces.py:33)
from parrot.auth.permission import build_principal_context             # ui_surfaces.py:28
```

### Existing Signatures to Use
```python
# packages/ai-parrot-server/src/parrot/handlers/ui_surfaces.py (origin/dev 3d03bb2cd)
class PublishSurfaceRequest(BaseModel)          # :58-77  kind, title, envelope, source_artifact_id, agent_id, session_id, recipe_name, recipe_owner, recipe_params
class RefreshSurfaceRequest(BaseModel)          # :79-82
class MintShareRequest(BaseModel)               # :85-89
async def _get_user_id(request) -> str | None   # :97-124
def _surface_metadata(record) -> dict           # :127-136  EXTEND
async def resolve_surface_access(store, surface_id, user_id, token) -> tuple[UISurfaceRecord | None, tuple[str, int] | None]   # :138-167  owner → ok (:158); token → resolve_share/claim_share or 410 (:160-166); else 404 (:167)
class SurfaceNegotiationService                 # :175  negotiate(request) -> str ; respond(record, accept) -> web.Response
@is_authenticated() @user_session() class UISurfacesHandler(BaseView)   # :270-272
    store / negotiation properties               # :287-300  (app.get(...) with lazy creation)
    async def _user_id(self)                     # :310
    def _error(self, message, *, status=400)     # :313-327  ALWAYS use this (BaseView.error() whitelist landmine)
    async def get(self) / post(self) / delete(self)   # :329-354  add `patch` beside them
    async def _resolve_surface_for_access(self, surface_id, user_id, token)   # :356-378  wraps resolve_surface_access → add scope
    async def _get_one(self, surface_id, user_id)     # :379-386  ?share= token
    async def _get_list(self, user_id)                # :388-410  today: owned + shared, tags "owner"/"shared"
    async def _pin_save(self)                         # :412-490  UISurfaceRecord(...) built at :471-483 — add tenant/visibility/allowed_groups
    async def _refresh(self)                          # :491-560  merged_params (:520); owner_pctx = build_principal_context(record.user_id, channel="ui_surfaces") (:533)
    async def _mint_share / _delete_surface / _revoke_share   # :561-620  owner-only via record.user_id != user_id → 404 (keep)
    self.query_parameters(self.request)          # BaseView helper used at :380, :390
    self.json_response(...)                      # BaseView helper

# store (TASK-2932): list_visible(scope, *, kind=None) ; update_visibility(surface_id, user_id, visibility, allowed_groups) -> bool
# tests/handlers/test_ui_surfaces_handler.py: fake_store fixture (:131-145, MagicMock + AsyncMocks), _app(store, runner, artifact_store) -> dict (:153-160); handlers are built with UISurfacesHandler.__new__ + fake request (see file's _handler helper / e2e's _FakeRequest :218-232)
```

### Does NOT Exist
- ~~`patch` on the handler~~ — new; aiohttp `View` dispatches by method name, no route change (`manager.py:2061` already maps `/{surface_id}`).
- ~~a `tenant` field on `PublishSurfaceRequest`~~ — deliberately absent; the server sets it.
- ~~`access` values other than `owner|tenant|shared`~~.
- ~~viewer delete/share~~ — owner-only stays (`404`, no oracle).
- ~~`BaseView.error()` for 410/422~~ — whitelist landmine; `self._error` only.

---

## Implementation Notes

### Key Constraints
- Access order in `resolve_surface_access`: owner → scope → token → 404. Keep the function framework-agnostic (returns tuples), since `A2UIHandler` shares it (TASK-2935).
- Resolve the scope ONCE per request (`self._scope()`), never per store call.
- Keep `_get_list`'s `401` when `user_id` is missing.
- Function length ≤ 60 lines / complexity ≤ 10: split `_get_list` into `_collect_visible` and `_tag_and_merge`.

### References in Codebase
- `handlers/infographic_recipes.py` — sibling handler with the same `_error` approach.
- `tests/handlers/test_ui_surfaces_handler.py:292-311` — `test_list_owned_union_shared_with_access_tag` (extend, do not replace).

---

## Acceptance Criteria

- [ ] All pre-existing handler tests pass unchanged in intent
- [ ] List returns owned ∪ visible ∪ shared with `access ∈ owner|tenant|shared`, deduplicated
- [ ] Publish: `tenant` from scope; `422` when non-private without tenant; body `tenant` ignored
- [ ] `PATCH`: owner `200`, non-owner `404`, bad body `400`, tenant rule `422`
- [ ] Viewer: `GET` JSON+HTML `200`, `refresh` `200` under owner pctx, `DELETE`/share `404`
- [ ] Metadata exposes `tenant`, `visibility`, `allowed_groups`, `recipe_name`, `recipe_params`
- [ ] Mutation: `scope_grants → False` turns the viewer tests RED (evidence in Completion Note); `ruff check` clean

---

## Test Specification

```python
# tests/handlers/test_ui_surfaces_handler.py (excerpt)
class _StubResolver:
    def __init__(self, scope): self._scope = scope
    async def resolve(self, request): return self._scope

VIEWER = SurfaceScope("u-viewer", "epson", frozenset({"epson_fieldsync_manager"}), False)

async def test_viewer_get_json_200(fake_store):
    rec = _record(user_id="u-owner", tenant="epson", visibility=SurfaceVisibility.tenant)
    fake_store.get = AsyncMock(return_value=rec)
    app = _app(fake_store); app["ui_surfaces_scope_resolver"] = _StubResolver(VIEWER)
    resp = await _unwrap(UISurfacesHandler.get)(_handler(app, match_info={"surface_id": rec.surface_id}, user_id="u-viewer"))
    assert resp.status == 200
```

---

## Agent Instructions

1. Read spec §2 (Overview item 3, HTTP contract table), §3 Module 3, §6, §7.
2. Verify the contract; implement; `pytest packages/ai-parrot-server/tests/handlers/test_ui_surfaces_handler.py -v`; `ruff check`.
3. Index → `in-progress` → `done`; move to `completed/`; Completion Note with the mutation evidence.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
