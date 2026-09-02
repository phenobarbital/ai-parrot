# TASK-2702: SurfaceNegotiationService + UISurfacesHandler (REST lane)

**Feature**: FEAT-492 — A2UI Surface Rehydration
**Spec**: `sdd/specs/a2ui-surface-rehydration.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-2700, TASK-2701
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 3 — the heart of the feature: the shared JSON/HTML negotiation
service (consumed later by the A2UIHandler mirror route, TASK-2703) and the
`UISurfacesHandler` REST lane: bookmarkable GET, owner list **including
shared-with-me** (spec §8 resolution), pin/save, deterministic refresh
in-place, share mint/revoke, delete.

---

## Scope

- Implement `packages/ai-parrot-server/src/parrot/handlers/ui_surfaces.py`:
  - `SurfaceNegotiationService`:
    - `negotiate(request) -> str` — `?format=json|html` wins over `Accept`;
      default `application/json`.
    - `respond(record, accept) -> web.Response` — JSON: envelope + metadata
      (`surface_id`, `kind`, `title`, `refreshable`, `created_at`,
      `updated_at`, `catalog_id`, `agent_id`); HTML: guarded import of
      `InteractiveHTMLRenderer`, `render(CreateSurface.model_validate(
      record.envelope))`, serve `artifact.content` as `text/html`; when
      ai-parrot-visualizations is absent → 501 with install hint (JSON lane
      unaffected).
  - `UISurfacesHandler(BaseView)` with `@is_authenticated()`/`@user_session()`:
    - `GET /api/v1/ui/surfaces/{surface_id}` — owner session OR valid
      `?share=<token>`; on authenticated share access call
      `store.claim_share(token, user_id)`; foreign/missing id → 404;
      revoked/expired/missing token → 410 (no oracle).
    - `GET /api/v1/ui/surfaces` — owned + shared-with-me
      (`store.list(user_id)` ∪ `store.list_shared_with(user_id)`), each item
      tagged `"access": "owner" | "shared"`; optional `?kind=` filter.
    - `POST /api/v1/ui/surfaces` — pin/save: `PublishSurfaceRequest` body,
      inline `envelope` XOR `source_artifact_id` (copy the envelope from
      ArtifactStore) — both/neither → 400; envelope validated via
      `CreateSurface.model_validate`; 201 with `surface_id`.
    - `POST /api/v1/ui/surfaces/{surface_id}/refresh` — owner or share
      bearer; 409 when `recipe_name` is NULL; merge params (request >
      stored `recipe_params` > recipe defaults); build the **OWNER's**
      `PermissionContext` via `build_principal_context(principal=owner_user_id,
      channel="ui_surfaces")`; `RecipeRunner.run(recipe_name, params=merged,
      pctx=owner_pctx, recipe_owner=stored, include_envelope=True)`; take
      `artifact.metadata["source_envelope"]`; `store.update_envelope(...)`;
      respond negotiated. `RecipeRunException` → 422 naming the stage (data
      fetch failures may map 502) — never a raw 500.
    - `POST /api/v1/ui/surfaces/{surface_id}/share` — owner only; body may
      carry `expires_at` or `ttl: true` (→ 90-day default); returns the token.
    - `DELETE /api/v1/ui/surfaces/{surface_id}` — owner only.
    - `DELETE /api/v1/ui/surfaces/{surface_id}/share/{token}` — owner only.
  - Dispatch on `match_info` inside `get`/`post`/`delete` (the
    `InfographicTalk`/`AgentTalk` idiom) — one handler class.
- Unit tests in
  `packages/ai-parrot-server/tests/handlers/test_ui_surfaces_handler.py`
  (store and runner mocked).

**NOT in scope**: route registration in `manager.py` and the A2UIHandler
mirror branch (TASK-2703); the store itself (TASK-2700); the runner flag
(TASK-2701); mixin/tool writers (TASK-2704).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/handlers/ui_surfaces.py` | CREATE | Service + handler |
| `packages/ai-parrot-server/tests/handlers/test_ui_surfaces_handler.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

> Verified 2026-09-01 against `dev`.

### Verified Imports
```python
from aiohttp import web
from navigator.views import BaseView                              # verified: dashboard_handler.py
from navigator_auth.decorators import is_authenticated, user_session   # verified: handlers/agent.py:21-31
from parrot.outputs.a2ui.models import CreateSurface              # verified: outputs/a2ui/models.py:446
from parrot.tools.infographic_recipes.runner import RecipeRunner  # verified: runner.py:204
from parrot.auth.permission import build_principal_context        # verified: auth/permission.py:166
from parrot.storage.artifacts import ArtifactStore                # verified: infographic_render.py imports it
# From TASK-2700 (verify it landed first):
from parrot.handlers.models.ui_surfaces import (
    PgUISurfaceStore, UISurfaceRecord, UISurfaceShare, UISurfaceKind,
)
# HTML lane — GUARDED import (may be absent):
#   from parrot.outputs.a2ui_renderers.interactive_html import InteractiveHTMLRenderer
#   verified path: packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/interactive_html.py:295
```

### Existing Signatures to Use
```python
# packages/ai-parrot-visualizations/.../a2ui_renderers/interactive_html.py:295-298
class InteractiveHTMLRenderer(AbstractA2UIRenderer):
    async def render(self, envelope: CreateSurface, *, bake: bool = True) -> RenderedArtifact: ...
# RenderedArtifact.content: bytes | None  (artifacts.py:54 — content XOR path)

# packages/ai-parrot/src/parrot/tools/infographic_recipes/runner.py:242
async def run(self, name, *, params=None, pctx=None, recipe_owner=None,
              include_envelope: bool = False) -> RenderedArtifact   # flag from TASK-2701
# RecipeRunner.__init__(store, dataset_manager, *, artifact_store=None, owner=None, narrator=None)  # line 226
# Errors: RecipeRunException (stage-tagged) — runner.py:93

# packages/ai-parrot/src/parrot/auth/permission.py:166
def build_principal_context(principal, channel, ...): ...   # deny-by-default roles

# BaseView helpers used throughout AgentTalk/DashboardHandler:
#   self.json_response(data, status=...), self.error(response={...}, status=...),
#   self.query_parameters(self.request), self.request.match_info.get("...")

# Param-merge precedence to replicate (examples/agents/a2ui/deterministic_refresh_dashboard.py:376+):
#   explicit request params → stored recipe_params → recipe defaults
```

### Does NOT Exist
- ~~`SurfaceNegotiationService`, `UISurfacesHandler`~~ — THIS task creates them
- ~~routes under `/api/v1/ui/`~~ — registered in TASK-2703, NOT here
- ~~`PgUISurfaceStore`~~ before TASK-2700 lands — verify the import resolves
- ~~`include_envelope`~~ before TASK-2701 lands — verify before use
- ~~`AgentTalk._check_pbac_agent_access` on BaseView~~ — that helper is
  AgentTalk's; this handler does NOT inherit AgentTalk (no agent resolution
  needed) — auth is decorator + owner/share checks only
- ~~a server-wide RecipeRunner singleton~~ — construct/inject per handler
  (store + DatasetManager wiring documented in Implementation Notes)

---

## Implementation Notes

### Pattern to Follow
- Handler dispatch on `match_info` — copy the shape of
  `handlers/infographic.py` (`InfographicTalk.post/get` dispatch) and
  `dashboard_handler.py` (BaseView CRUD, `_user_id()` helper reading
  `self.request.get("user_id")` / session).
- Negotiation: replicate `InfographicTalk._negotiate_accept()` semantics
  (`?format=` wins; default here is **JSON**, unlike infographic's HTML).
- RecipeRunner wiring: accept the runner (or a factory) via handler
  `post_init`/app context so tests can inject a stub; resolve the recipe
  store the way `handlers/infographic_recipes.py` does (read that file
  before implementing — it already wires stores for the recipes REST lane).

### Key Constraints
- Share bearer NEVER supplies `recipe_name`/`recipe_owner`/identity — always
  from the stored row; owner pctx built from the row's `user_id`.
- 404 vs 410 discipline: unknown id → 404; bad token → 410; never reveal
  which of revoked/expired/missing occurred.
- HTML lane must not import ai-parrot-visualizations at module level — import
  inside `respond()` under try/except ImportError → 501.
- All wire bodies are Pydantic models (`PublishSurfaceRequest`,
  `RefreshSurfaceRequest` from spec §2) — validation errors → 400 with a
  clear body, never 500.

### References in Codebase
- `packages/ai-parrot-server/src/parrot/handlers/infographic.py` — dispatch + negotiation idiom
- `packages/ai-parrot-server/src/parrot/handlers/infographic_recipes.py` — recipes store/runner wiring
- `packages/ai-parrot-server/src/parrot/handlers/dashboard_handler.py` — BaseView CRUD idiom
- `packages/ai-parrot-server/src/parrot/handlers/infographic_render.py` — error-mapping style (400/413/422)

---

## Acceptance Criteria

- [ ] GET by id: owner 200; foreign 404; share token 200 (+ claim recorded);
      revoked/expired 410
- [ ] GET negotiation: default JSON (envelope + metadata incl. `refreshable`);
      `Accept: text/html` and `?format=html` → HTML; 501 without visualizations
- [ ] GET list: owned ∪ shared-with-me with `access` tag; `?kind=` filter works
- [ ] POST pin/save: inline XOR source_artifact_id enforced (400); envelope
      validated; 201 + surface_id
- [ ] POST refresh: param precedence correct; row updated in place; owner
      pctx used for share bearers; 409 non-refreshable; 422 on RecipeRunException
- [ ] Share mint/revoke: owner-only; ttl:true → 90-day expiry
- [ ] All tests pass: `pytest packages/ai-parrot-server/tests/handlers/test_ui_surfaces_handler.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot-server/src/parrot/handlers/ui_surfaces.py`

---

## Test Specification

```python
# packages/ai-parrot-server/tests/handlers/test_ui_surfaces_handler.py
# aiohttp.test_utils.TestClient fixtures (see tests/handlers/ existing style);
# PgUISurfaceStore and RecipeRunner mocked/stubbed.

async def test_get_owner_json_default(): ...
async def test_get_html_accept_and_format_param(): ...
async def test_get_html_501_without_visualizations(): ...
async def test_get_foreign_id_404(): ...
async def test_get_share_token_ok_and_claims(): ...
async def test_get_share_token_revoked_410(): ...
async def test_list_owned_union_shared_with_access_tag(): ...
async def test_post_pin_inline_xor_artifact_400(): ...
async def test_post_pin_inline_valid_201(): ...
async def test_refresh_param_precedence_and_inplace_update(): ...
async def test_refresh_share_bearer_uses_owner_pctx(): ...
async def test_refresh_not_refreshable_409(): ...
async def test_refresh_recipe_error_422(): ...
async def test_share_mint_ttl_true_90_days(): ...
async def test_share_revoke_owner_only(): ...
```

---

## Agent Instructions

1. **Read the spec** (§2 Overview/Data Models/Interfaces, §3 Module 3, §7).
2. **Check dependencies** — TASK-2700 and TASK-2701 must be in `sdd/tasks/completed/`.
3. **Verify the Codebase Contract** — especially the TASK-2700/2701 imports.
4. **Update status** in `sdd/tasks/index/a2ui-surface-rehydration.json` → `"in-progress"`.
5. **Implement**, **verify**, **move to completed**, update index, fill Completion Note.

---

## Completion Note

**Completed by**: sdd-worker (Claude)
**Date**: 2026-09-01
**Notes**:
Implemented `SurfaceNegotiationService` (negotiate/respond, `?format=` wins
over `Accept`, default JSON, guarded `InteractiveHTMLRenderer` import → 501
with install hint) and `UISurfacesHandler` (`BaseView` +
`@is_authenticated()`/`@user_session()`, path/match_info dispatch) in
`packages/ai-parrot-server/src/parrot/handlers/ui_surfaces.py`. Reuses the
process-wide `RecipeRunner` wired by `register_recipe_routes()`
(`parrot.handlers.infographic_recipes.get_recipe_runner()`) rather than
constructing a second one. Refresh builds the OWNER's `PermissionContext`
via `build_principal_context(record.user_id, channel="ui_surfaces")`
regardless of caller identity; `RecipeRunException` maps to 422 (or 502 for
`stage="data"`), never a raw 500. 404-vs-410 discipline implemented via a
shared `_resolve_surface_for_access()` helper (unknown/foreign-without-token
→ 404; bad/revoked/expired token → 410, no oracle).

27 unit tests in `test_ui_surfaces_handler.py`, all mocking
`PgUISurfaceStore`/`RecipeRunner`, following `test_infographic_recipes.py`'s
established idiom for this exact handler shape (`BaseView` +
`@is_authenticated()`/`@user_session()`): construct via
`UISurfacesHandler.__new__`, set `_request` to a lightweight fake, and fully
unwrap both decorator layers via `__wrapped__` chains to test the handler's
own request-handling logic (auth enforcement itself is out of this task's
scope — it needs real aiohttp session/auth middleware). All pass; also
reran `test_infographic_recipes.py` + `test_ui_surfaces_store.py` alongside
(54 total) to confirm no collateral breakage, and the wider
`tests/handlers/` suite (442/444 — the 2 failures are
`test_agent_a2ui_stream.py`'s source-text assertions against `agent.py`,
confirmed pre-existing/unrelated: that file is untouched by this task and
the failures reproduce identically with this task's two new files absent
from the tree). `ruff check` is clean.

**Bug caught and fixed during implementation**: `BaseView.error()`
(`navigator/views/base.py`) only recognizes a status whitelist
(400/401/403/404/406/412/428) and silently downgrades any other status to
400 — the same landmine `handlers/comm_center.py::_map_error`'s docstring
already documents. My first draft used `self.error(status=410/500/503)` for
share-expiry/runner-missing/artifact-store-missing, which would have
silently shipped as 400s. Fixed by adding a `_error()` helper that always
goes through `self.json_response(...)` directly (mirrors
`RecipeHandler._error_response` in the sibling `infographic_recipes.py`)
for every status this handler needs. Caught because `self.error()` also
needs `self._json` (set by `BaseView.__init__`, skipped by the `__new__`
test construction) — the AttributeError surfaced it immediately during
test-writing, not silently in production.

**Deviations from spec**:
- `PublishSurfaceRequest` gained a `session_id: Optional[str] = None` field
  beyond the spec's Data Models block — copying from `ArtifactStore`
  requires the full `(user_id, agent_id, session_id, artifact_id)`
  composite key (`storage/artifacts.py`); `user_id` comes from the
  authenticated session but `session_id` has no other source. Optional and
  additive; inline-envelope publishes never need it.
- Added a local `MintShareRequest` Pydantic model (not named in the spec's
  New Public Interfaces block, which only prescribes the store's
  `mint_share` signature) to validate the share-mint POST body
  (`expires_at`/`ttl`) per the "all wire bodies are Pydantic models" key
  constraint.
- List endpoint items carry the shared `_surface_metadata()` block (surface_id,
  kind, title, refreshable, created_at, updated_at, catalog_id, agent_id) +
  `access`, omitting the full `envelope` for list efficiency — the spec's
  route table only says "each item tagged access", not the exact item shape.
