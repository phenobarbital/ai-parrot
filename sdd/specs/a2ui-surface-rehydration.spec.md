---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Feature Specification: A2UI Surface Rehydration (persistent serving of dashboards, infographics & widgets)

**Feature ID**: FEAT-492
**Date**: 2026-09-01
**Author**: Jesus Lara
**Status**: draft
**Target version**: 1.x

---

## 1. Motivation & Business Requirements

### Problem Statement

A2UI has full **interaction** and **refresh** support (FEAT-469 `A2UIHandler`:
envelope dispatch, SSE stream, capabilities; FEAT-324/326 recipes +
`RecipeRunner` deterministic replay), but **no serving/rehydration lane**: a
generated surface (dashboard, infographic, widget/KPI) lives only in
`ConversationMemorySurfaceStore` (conversation memory) and reaches the
frontend exclusively inside the turn response (`a2ui_envelope`) or via the
session's SSE stream.

Consequences:
- A user cannot bookmark a dashboard URL and open it later (or after a page
  reload) — there is no `GET` that returns the persisted A2UI object by id.
- The frontend renderer cannot cold-mount a previously generated surface
  outside the originating conversation/session.
- Deep-links (FEAT-273/469) do NOT cover this: single-use, 15-minute-TTL
  action-resume tokens bound to an existing session; their result is an agent
  turn, not the surface object.
- FEAT-491 (flex-agent-infographic-a2ui) is an example agent that explicitly
  ships "No new server handlers", so the gap stays open without this feature.

### Goals

- G1 — `GET /api/v1/ui/surfaces/{surface_id}` returns the persisted A2UI
  object at any time (bookmarkable, outside the original session), with
  content negotiation: `Accept: application/json` → rehydratable A2UI
  envelope + surface metadata; `Accept: text/html` → server-side rendered
  interactive HTML.
- G2 — Persistence in Postgres, table `navigator.ui_surfaces`, structured
  lookup by uuid; the store module auto-creates schema/table when missing
  (`CREATE TABLE IF NOT EXISTS`).
- G3 — Refresh: a stored `recipe_ref` (recipe name/owner + params +
  agent_id) lets `POST .../refresh` (and the renderer's
  `callAgentFunction → refresh_dashboard` lane) re-run the recipe via
  `RecipeRunner` with fresh data / param overrides, **updating the row in
  place** — the bookmark always shows the latest data.
- G4 — Dual writers: an agent-side `publish_surface` (mixin method +
  LLM-invocable tool wrapper) and a frontend `POST /api/v1/ui/surfaces`
  ("pin/save").
- G5 — Sharing: opaque tokens stored in DB (revocable, optional TTL,
  listable by owner) granting **read + refresh** — refresh under a share
  token runs with the OWNER's `PermissionContext`; no edit/delete/re-share.
- G6 — `A2UIHandler` gains the mirror route
  `GET /api/v1/agents/{agent_id}/a2ui/surfaces/{surface_id}` with the SAME
  JSON/HTML content negotiation (resolved Open Question: the mirror route is
  NOT protocol-strict — both routes share one negotiation service).
- G7 — HTML lane rendered **on-the-fly** with `InteractiveHTMLRenderer`
  (ai-parrot-visualizations), guarded import with actionable degradation.
- G8 — `RecipeRunner` exposes the assembled envelope on its result
  (minimal extension) so the refresh path never needs a second ArtifactStore
  round-trip.

### Non-Goals (explicitly out of scope)

- Surface versioning/history — refresh is in-place (versioned refresh was
  rejected in brainstorm; see `sdd/proposals/a2ui-surface-rehydration.brainstorm.md`).
- Replay-on-every-GET ("virtual surfaces", brainstorm Option C) — rejected:
  read-amplifies the data plane and cannot pin non-recipe surfaces.
- Extending the ArtifactStore plane instead of a dedicated table (brainstorm
  Option B) — rejected by user decision (Pg structured store).
- Editing surface components through this API (rehydrate + refresh only).
- Anonymous/public surfaces without a share token.
- Changes to deep-links, `ConversationMemorySurfaceStore`, or the A2UI
  protocol models.
- Envelope size caps or ArtifactStore overflow mirroring — **no size limit
  in v1** (resolved Open Question); rely on the endpoint body cap.
- DocumentDB/Mongo persistence (that is `dashboard_handler.py`'s separate,
  untouched plane).

---

## 2. Architectural Design

### Overview

A new, self-contained **ui_surfaces plane** in the server package:

1. **`PgUISurfaceStore`** owns two Postgres tables (auto-created on first
   use via `AsyncDB("pg", dsn=default_dsn)`):
   - `navigator.ui_surfaces` — `surface_id uuid PK`, `kind`
     (`dashboard|infographic|widget`), `title`, `envelope jsonb` (the exact
     `CreateSurface.model_dump(by_alias=True, mode="json")` shape that
     `persist_envelope()` produces), `catalog_id`, `agent_id`, `user_id`,
     `session_id`, `recipe_name`, `recipe_owner`, `recipe_params jsonb`,
     `created_at`, `updated_at`.
   - `navigator.ui_surface_shares` — `token PK` (opaque,
     `secrets.token_urlsafe(32)`), `surface_id FK`, `permissions`
     (fixed `read+refresh` in v1), `expires_at NULL`, `revoked bool`,
     `created_at`.
2. **`SurfaceNegotiationService`** (shared module): given a stored row and an
   `Accept` header / `?format=` override, returns either the JSON body
   (envelope + metadata incl. `refreshable`) or on-the-fly HTML via
   `InteractiveHTMLRenderer.render(CreateSurface.model_validate(envelope))`.
   Used by BOTH handlers so negotiation behavior cannot drift.
3. **`UISurfacesHandler`** (`navigator.views.BaseView`, `@is_authenticated`/
   `@user_session` like `AgentTalk`) exposes the REST lane
   (routes in §3 Module 4).
4. **`A2UIHandler`** GET dispatch grows a `/surfaces/{surface_id}` branch
   delegating to the same store + negotiation service (resolved: negotiates
   HTML exactly like the REST lane).
5. **Refresh**: merge params (request > stored `recipe_params` > recipe
   defaults — the `RefreshDashboardTool` precedence), call
   `RecipeRunner.run(recipe_name, params=merged, pctx=owner_pctx,
   recipe_owner=..., include_envelope=True)`; the assembled envelope comes
   back on the result (G8, Module 2); UPDATE the row (`envelope`,
   `recipe_params`, `updated_at`); respond negotiated. Share-token refresh
   builds the OWNER's context via `build_principal_context` — bearer
   identity is never used for data access. Rows without `recipe_ref` → 409.
6. **Writers**: `InfographicAuthoringMixin.publish_surface()` (programmatic
   API next to `publish_recipe`) + a thin `PublishSurfaceTool` in
   `parrot_tools` that wraps it (resolved: BOTH lanes) — plus the frontend
   `POST /api/v1/ui/surfaces` accepting an inline envelope or a source
   `artifact_id` to copy from ArtifactStore.

### Component Diagram

```
Frontend / Browser / Renderer
    │
    ├── GET  /api/v1/ui/surfaces/{id}[?share=<token>]      ┐
    ├── GET  /api/v1/ui/surfaces                            │
    ├── POST /api/v1/ui/surfaces            (pin/save)      ├─ UISurfacesHandler
    ├── POST /api/v1/ui/surfaces/{id}/refresh               │        │
    ├── POST /api/v1/ui/surfaces/{id}/share                 │        │
    └── DELETE /api/v1/ui/surfaces/{id}/share/{token}      ┘        │
                                                                     │
    GET /api/v1/agents/{agent_id}/a2ui/surfaces/{id} ── A2UIHandler ─┤
                                                                     ▼
                          SurfaceNegotiationService ──→ InteractiveHTMLRenderer (HTML lane, guarded)
                                     │
                                     ▼
                            PgUISurfaceStore ──→ navigator.ui_surfaces / ui_surface_shares
                                     ▲
        refresh: RecipeRunner.run(include_envelope=True) ──→ envelope → UPDATE in place
                                     ▲
Agent lane: InfographicAuthoringMixin.publish_surface() ←── PublishSurfaceTool (parrot_tools)
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `A2UIHandler` (`handlers/a2ui.py`) | extends | GET dispatch grows `/surfaces/{surface_id}` branch; POST/SSE/capabilities untouched |
| `BotManager.setup_app` (`manager/manager.py`) | modifies | register `/api/v1/ui/surfaces*` routes + the a2ui sub-route (near the FEAT-469 block, lines ~2043-2050) |
| `RecipeRunner` (`tools/infographic_recipes/runner.py`) | extends (minimal) | `include_envelope` exposure of the assembled `CreateSurface` (Module 2) |
| `InfographicAuthoringMixin` (`bots/mixins/infographic_authoring.py`) | extends | new `publish_surface()` next to `publish_recipe()` (line 279) |
| `parrot_tools` (ai-parrot-tools) | new tool | `PublishSurfaceTool` thin wrapper over the mixin method |
| `InteractiveHTMLRenderer` (ai-parrot-visualizations) | uses (optional) | HTML lane; guarded import, 501 + install hint when absent |
| `build_principal_context` (`auth/permission.py`) | uses | owner context for refresh (deny-by-default) |
| `persist_envelope` (`outputs/a2ui/baking.py`) | convention | envelope dump shape reused verbatim; function itself unchanged |
| `ArtifactStore` (`storage/artifacts.py`) | uses (read-only) | `POST /surfaces` may copy a source envelope by `artifact_id` |
| `ConversationMemorySurfaceStore` | none | untouched — live-session plane stays as is |
| deep-links (FEAT-273) | none | complementary; unchanged |
| `DashboardHandler` (Mongo) | none | separate legacy plane, untouched |

### Data Models

```python
# New Pydantic models (server package, ui_surfaces plane)

class UISurfaceKind(str, Enum):
    dashboard = "dashboard"
    infographic = "infographic"
    widget = "widget"

class UISurfaceRecord(BaseModel):
    """Row shape of navigator.ui_surfaces."""
    surface_id: str                      # uuid4 hex
    kind: UISurfaceKind
    title: str
    envelope: dict[str, Any]             # CreateSurface.model_dump(by_alias=True, mode="json")
    catalog_id: Optional[str] = None
    agent_id: str
    user_id: str
    session_id: Optional[str] = None
    recipe_name: Optional[str] = None    # refresh lane (recipe_ref)
    recipe_owner: Optional[str] = None
    recipe_params: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime

    @property
    def refreshable(self) -> bool: ...   # recipe_name is not None

class UISurfaceShare(BaseModel):
    """Row shape of navigator.ui_surface_shares."""
    token: str                           # secrets.token_urlsafe(32)
    surface_id: str
    permissions: Literal["read+refresh"] = "read+refresh"
    expires_at: Optional[datetime] = None
    revoked: bool = False
    created_at: datetime

class PublishSurfaceRequest(BaseModel):
    """Body of POST /api/v1/ui/surfaces (frontend pin/save)."""
    kind: UISurfaceKind
    title: str
    envelope: Optional[dict[str, Any]] = None   # inline CreateSurface dump
    source_artifact_id: Optional[str] = None    # XOR: copy from ArtifactStore
    agent_id: Optional[str] = None
    recipe_name: Optional[str] = None
    recipe_owner: Optional[str] = None
    recipe_params: dict[str, Any] = Field(default_factory=dict)

class RefreshSurfaceRequest(BaseModel):
    """Body of POST /api/v1/ui/surfaces/{id}/refresh."""
    params: dict[str, Any] = Field(default_factory=dict)   # merged over stored recipe_params
```

DDL sketch (auto-created by the store — `CREATE SCHEMA IF NOT EXISTS
navigator;` then `CREATE TABLE IF NOT EXISTS navigator.ui_surfaces (...)` /
`navigator.ui_surface_shares (...)`; indexes on `user_id`, `(user_id,
kind)`, `ui_surface_shares.surface_id`). No `envelope` size constraint in v1
(resolved Open Question).

### New Public Interfaces

```python
# Module 1 — packages/ai-parrot-server/src/parrot/handlers/models/ui_surfaces.py
class PgUISurfaceStore:
    """Postgres store for persisted A2UI surfaces + share tokens."""
    def __init__(self, dsn: Optional[str] = None) -> None: ...   # defaults to parrot.conf.default_dsn
    async def ensure_schema(self) -> None: ...                   # CREATE SCHEMA/TABLE IF NOT EXISTS (idempotent)
    async def save(self, record: UISurfaceRecord, *, overwrite: bool = False) -> str: ...
    async def get(self, surface_id: str) -> Optional[UISurfaceRecord]: ...
    async def list(self, user_id: str, *, kind: Optional[UISurfaceKind] = None) -> list[UISurfaceRecord]: ...
    async def update_envelope(self, surface_id: str, envelope: dict, recipe_params: dict) -> None: ...
    async def delete(self, surface_id: str, user_id: str) -> bool: ...
    async def mint_share(self, surface_id: str, *, expires_at: Optional[datetime] = None) -> UISurfaceShare: ...
    async def resolve_share(self, token: str) -> Optional[UISurfaceShare]: ...   # None when missing/revoked/expired (no oracle)
    async def revoke_share(self, token: str, surface_id: str) -> bool: ...
    async def list_shares(self, surface_id: str) -> list[UISurfaceShare]: ...

# Module 3 — packages/ai-parrot-server/src/parrot/handlers/ui_surfaces.py
class SurfaceNegotiationService:
    """Shared JSON/HTML negotiation over a stored surface (used by BOTH handlers)."""
    def negotiate(self, request: web.Request) -> str: ...        # "application/json" | "text/html" (?format= wins)
    async def respond(self, record: UISurfaceRecord, accept: str) -> web.Response: ...

@is_authenticated()
@user_session()
class UISurfacesHandler(BaseView):
    _logger_name: str = "Parrot.UISurfaces"
    async def get(self) -> web.Response: ...      # {id} → negotiated | no id → owner list
    async def post(self) -> web.Response: ...     # pin/save | .../refresh | .../share (dispatch on match_info)
    async def delete(self) -> web.Response: ...   # surface delete | share revoke

# Module 2 — RecipeRunner extension (packages/ai-parrot/src/parrot/tools/infographic_recipes/runner.py)
async def run(self, name: str, *, params=None, pctx=None, recipe_owner=None,
              include_envelope: bool = False) -> RenderedArtifact:
    """When include_envelope=True, the assembled CreateSurface dump is attached
    at RenderedArtifact.metadata['source_envelope'] (non-breaking; default False)."""

# Module 5 — InfographicAuthoringMixin (packages/ai-parrot/src/parrot/bots/mixins/infographic_authoring.py)
async def publish_surface(self, *, kind: str, title: str,
                          envelope: "CreateSurface | dict",
                          recipe_name: Optional[str] = None,
                          recipe_owner: Optional[str] = None,
                          recipe_params: Optional[dict] = None,
                          overwrite: bool = False) -> str:
    """Validate + persist a surface to PgUISurfaceStore; returns surface_id."""

# Module 5 — parrot_tools (packages/ai-parrot-tools/src/parrot_tools/ui_surfaces.py)
class PublishSurfaceTool(AbstractTool):
    name = "publish_surface"   # thin wrapper delegating to the mixin/store
```

Routes (Module 4, registered in `BotManager.setup_app`):

```
GET    /api/v1/ui/surfaces                          — owner's surfaces (list)
GET    /api/v1/ui/surfaces/{surface_id}             — negotiated JSON/HTML (owner or ?share=)
POST   /api/v1/ui/surfaces                          — pin/save (frontend writer)
POST   /api/v1/ui/surfaces/{surface_id}/refresh     — recipe replay, update in place
POST   /api/v1/ui/surfaces/{surface_id}/share       — mint share token
DELETE /api/v1/ui/surfaces/{surface_id}             — delete surface (owner)
DELETE /api/v1/ui/surfaces/{surface_id}/share/{token} — revoke token (owner)
GET    /api/v1/agents/{agent_id}/a2ui/surfaces/{surface_id} — A2UIHandler mirror (same negotiation)
```

---

## 3. Module Breakdown

### Module 1: PgUISurfaceStore + DDL
- **Path**: `packages/ai-parrot-server/src/parrot/handlers/models/ui_surfaces.py`
- **Responsibility**: `UISurfaceRecord`/`UISurfaceShare` models, DDL constants
  (`CREATE SCHEMA/TABLE IF NOT EXISTS navigator.ui_surfaces / ui_surface_shares`
  — the `handlers/models/bots.py:29` pattern), `PgUISurfaceStore` CRUD +
  share-token mint/resolve/revoke over `AsyncDB("pg", dsn=default_dsn)`.
  `ensure_schema()` is idempotent and called lazily on first store use.
- **Depends on**: `asyncdb` (core dep), `parrot.conf.default_dsn`.

### Module 2: RecipeRunner envelope exposure
- **Path**: `packages/ai-parrot/src/parrot/tools/infographic_recipes/runner.py`
- **Responsibility**: add `include_envelope: bool = False` to `run()`; when
  True, attach `envelope.model_dump(by_alias=True, mode="json")` (the value
  produced by `_assemble_envelope_or_raise`, line 607) at
  `RenderedArtifact.metadata["source_envelope"]` before returning.
  Non-breaking: default False leaves every existing caller byte-identical.
- **Depends on**: nothing new (envelope already assembled internally).

### Module 3: SurfaceNegotiationService + UISurfacesHandler
- **Path**: `packages/ai-parrot-server/src/parrot/handlers/ui_surfaces.py`
- **Responsibility**: shared negotiation (JSON envelope+metadata / on-the-fly
  HTML via guarded `InteractiveHTMLRenderer` import → 501 with install hint
  when ai-parrot-visualizations is absent); the REST handler: auth (owner
  session OR `?share=` token), list, pin/save (inline envelope XOR
  `source_artifact_id` copied from ArtifactStore), refresh (param merge →
  `RecipeRunner.run(include_envelope=True)` with the OWNER's
  `build_principal_context` → `update_envelope` in place → negotiated
  response; 409 when not refreshable), share mint/revoke/list, delete.
- **Depends on**: Modules 1, 2; `parrot.auth.permission`;
  ai-parrot-visualizations (optional).

### Module 4: A2UIHandler mirror route + route registration
- **Path**: `packages/ai-parrot-server/src/parrot/handlers/a2ui.py` +
  `packages/ai-parrot-server/src/parrot/manager/manager.py`
- **Responsibility**: extend `A2UIHandler.get()` dispatch with a
  `/surfaces/{surface_id}` branch delegating to `SurfaceNegotiationService`
  (same JSON/HTML negotiation — resolved decision); register the literal
  sub-route BEFORE the bare `{agent_id}/a2ui` pattern (mirroring the
  existing `/capabilities` ordering comment at manager.py:2043); register
  all `/api/v1/ui/surfaces*` routes.
- **Depends on**: Module 3.

### Module 5: publish_surface — mixin method + parrot_tools wrapper
- **Paths**: `packages/ai-parrot/src/parrot/bots/mixins/infographic_authoring.py`
  (method next to `publish_recipe`, line 279) and
  `packages/ai-parrot-tools/src/parrot_tools/ui_surfaces.py` (new
  `PublishSurfaceTool(AbstractTool)` thin wrapper).
- **Responsibility**: programmatic publish API (validate envelope via
  `CreateSurface.model_validate`, derive `recipe_ref` when the surface came
  from a recipe, upsert via `PgUISurfaceStore`) + the LLM-invocable tool
  delegating to it. NOTE: the store lives in the server package —
  the mixin must receive/resolve the store via injection (constructor kwarg
  or lazy import guard) to respect the core→server one-way import rule; the
  exact injection seam is decided at implementation (see §8).
- **Depends on**: Modules 1, 2.

### Module 6: Tests
- **Paths**: `packages/ai-parrot-server/tests/handlers/test_ui_surfaces.py`,
  `packages/ai-parrot/tests/tools/test_recipe_runner_envelope.py`
- **Responsibility**: unit + integration tests per §4.
- **Depends on**: Modules 1–5.

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_store_ensure_schema_idempotent` | 1 | Two `ensure_schema()` calls succeed; tables exist |
| `test_store_save_get_roundtrip` | 1 | Saved `UISurfaceRecord` round-trips (envelope jsonb intact) |
| `test_store_list_by_owner_and_kind` | 1 | List filters by `user_id` and optional `kind` |
| `test_store_update_envelope_in_place` | 1 | `update_envelope` bumps `updated_at`, replaces envelope + recipe_params |
| `test_store_share_mint_resolve_revoke` | 1 | Mint → resolve; revoked/expired/missing all resolve to `None` (no oracle) |
| `test_runner_include_envelope_attaches_dump` | 2 | `run(include_envelope=True)` puts the CreateSurface dump at `metadata["source_envelope"]` |
| `test_runner_default_unchanged` | 2 | `run()` without the flag → no `source_envelope` key (non-breaking) |
| `test_negotiation_json_default` | 3 | No Accept → JSON envelope + metadata (`refreshable` flag present) |
| `test_negotiation_html_accept` | 3 | `Accept: text/html` → HTML body via InteractiveHTMLRenderer |
| `test_negotiation_format_param_wins` | 3 | `?format=html` overrides Accept |
| `test_negotiation_html_501_without_visualizations` | 3 | Renderer import guarded → 501 + install hint |
| `test_get_owner_ok_foreign_404` | 3 | Owner gets 200; another user's id → 404 (no existence oracle) |
| `test_get_with_valid_share_token` | 3 | `?share=<token>` grants read without owner session |
| `test_get_with_revoked_share_410` | 3 | Revoked/expired token → 410 |
| `test_post_pin_inline_envelope` | 3 | POST with inline envelope validates via `CreateSurface.model_validate`, persists |
| `test_post_pin_source_artifact` | 3 | POST with `source_artifact_id` copies the envelope from ArtifactStore |
| `test_post_pin_envelope_xor_artifact_400` | 3 | Both or neither of envelope/source_artifact_id → 400 |
| `test_refresh_merges_params_and_updates_row` | 3 | request > stored > defaults precedence; row updated in place |
| `test_refresh_share_token_uses_owner_pctx` | 3 | Bearer refresh builds the OWNER's `PermissionContext` |
| `test_refresh_not_refreshable_409` | 3 | Row without `recipe_name` → 409 machine-readable |
| `test_refresh_recipe_error_422` | 3 | `RecipeRunException` maps to 422 naming the stage, never 500 |
| `test_a2ui_mirror_route_negotiates` | 4 | `/a2ui/surfaces/{id}` returns JSON and HTML per Accept — same service |
| `test_mixin_publish_surface_returns_id` | 5 | Mixin validates + persists, returns surface_id |
| `test_publish_surface_tool_delegates` | 5 | Tool wrapper calls the mixin/store; docstring present |

### Integration Tests

| Test | Description |
|---|---|
| `test_e2e_publish_get_json_get_html` | publish via mixin → GET JSON (envelope matches) → GET HTML (`<html`, ECharts script for a chart surface) |
| `test_e2e_pin_then_bookmark_new_session` | POST pin → GET from a DIFFERENT session/user context (owner auth) → 200 with envelope |
| `test_e2e_refresh_flow` | publish recipe-backed surface → refresh with param override → GET returns refreshed dataModel, `updated_at` advanced |
| `test_e2e_share_lifecycle` | mint share → GET with token (200) → refresh with token (200, owner pctx) → revoke → GET 410 |
| `test_integration_routes_registered` | After `BotManager.setup_app()`, all eight routes resolve; `/a2ui/surfaces/{id}` matches before bare `{agent_id}/a2ui` |

### Test Data / Fixtures

```python
@pytest.fixture
def sample_envelope() -> dict:
    """A minimal valid CreateSurface dump (persist_envelope shape)."""
    from parrot.outputs.a2ui.models import CreateSurface
    return CreateSurface(
        surfaceId="surface-test-1",
        components=[...],          # one Card + one chart component from the basic catalog
        dataModel={"filters": {"window": "all", "plan": "All"}},
    ).model_dump(by_alias=True, mode="json")

@pytest.fixture
async def pg_store(tmp_pg_dsn):
    """PgUISurfaceStore against the test database; ensure_schema() run once."""

@pytest.fixture
def mock_recipe_runner(monkeypatch):
    """RecipeRunner.run stub returning a RenderedArtifact whose
    metadata['source_envelope'] carries a refreshed envelope dump."""
```

---

## 5. Acceptance Criteria

- [ ] All unit tests pass (`pytest packages/ai-parrot-server/tests/handlers/test_ui_surfaces.py packages/ai-parrot/tests/tools/test_recipe_runner_envelope.py -v`)
- [ ] All integration tests pass
- [ ] `GET /api/v1/ui/surfaces/{id}` returns the persisted envelope as JSON
      (`Accept: application/json`) and interactive HTML (`Accept: text/html`)
      for the authenticated owner — including from a fresh session (bookmark)
- [ ] `navigator.ui_surfaces` and `navigator.ui_surface_shares` are
      auto-created by `ensure_schema()` when absent; second call is a no-op
- [ ] The stored envelope is byte-shape-identical to
      `CreateSurface.model_dump(by_alias=True, mode="json")` (the
      `persist_envelope` convention) and rehydrates via
      `CreateSurface.model_validate`
- [ ] `POST .../refresh` re-runs the recipe via `RecipeRunner` with param
      precedence request > stored > recipe defaults, and updates the SAME row
      (`updated_at` advances; no new row)
- [ ] Refresh on a surface without `recipe_ref` returns 409; JSON metadata
      carries `refreshable: false`
- [ ] Share tokens: opaque, DB-stored, revocable, optional expiry; grant
      read + refresh only; refresh under a token runs with the OWNER's
      `PermissionContext`; revoked/expired/missing → 410 with no oracle
- [ ] `A2UIHandler` serves `GET .../a2ui/surfaces/{surface_id}` with the SAME
      negotiation (shared service — no duplicated logic), and its existing
      POST/SSE/capabilities behavior is unchanged
- [ ] `RecipeRunner.run(include_envelope=True)` exposes the assembled
      envelope at `metadata["source_envelope"]`; default call path unchanged
- [ ] `publish_surface` exists as BOTH a mixin method (next to
      `publish_recipe`) and a documented `parrot_tools` tool
- [ ] `POST /api/v1/ui/surfaces` accepts inline envelope XOR
      `source_artifact_id` (400 otherwise)
- [ ] HTML lane degrades to 501 with an actionable message when
      ai-parrot-visualizations is not installed — JSON lane unaffected
- [ ] No envelope size limit enforced in v1 (body cap only) — documented in §7
- [ ] No breaking changes to `A2UIHandler`, `RecipeRunner` existing callers,
      `ConversationMemorySurfaceStore`, deep-links, or `persist_envelope`

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> References verified 2026-09-01 against `dev` (tip `bc08c59f9`).
> Re-verify before modifying.

### Verified Imports

```python
from parrot.handlers.agent import AgentTalk                    # verified: handlers/a2ui.py:47 uses it
from parrot.outputs.a2ui.models import CreateSurface           # verified: outputs/a2ui/models.py:446
from parrot.outputs.a2ui.baking import persist_envelope        # verified: outputs/a2ui/baking.py:36 (__all__), def at :399
from parrot.outputs.a2ui.artifacts import RenderedArtifact, DeepLink   # verified: artifacts.py:54,36
from parrot.outputs.a2ui.runtime.adapters import ConversationMemorySurfaceStore, ToolManagerExecutor
                                                               # verified: handlers/a2ui.py:44-47
from parrot.tools.infographic_recipes.runner import RecipeRunner       # verified: runner.py:204
from parrot.auth.permission import build_principal_context     # verified: auth/permission.py:166
from parrot.a2a.models import A2UI_MEDIA_TYPE                  # verified: handlers/a2ui.py imports it
from asyncdb import AsyncDB                                    # verified: handlers/bots.py:5 (core dep)
from parrot.conf import default_dsn                            # verified: handlers/comm_center.py:36
from navigator.views import BaseView                           # verified: dashboard_handler.py
from navigator_auth.decorators import is_authenticated, user_session   # verified: handlers/agent.py:21-31
```

### Existing Class Signatures

```python
# packages/ai-parrot-server/src/parrot/handlers/a2ui.py (verified 2026-09-01)
class A2UIHandler(AgentTalk):
    def _resolution_data(self) -> dict[str, Any]: ...
    async def _authenticate(self, data) -> tuple: ...          # (agent, user_id, session_id, err)
    @staticmethod
    def _build_runtime(agent, user_id) -> tuple[A2UIRuntime, ConversationMemorySurfaceStore]: ...
    async def post(self) -> web.Response: ...                  # envelope dispatch — DO NOT TOUCH
    async def get(self) -> web.StreamResponse: ...             # dispatches: /capabilities → doc, else SSE
# Routes: manager/manager.py:2045-2046; literal-before-pattern ordering comment at :2043

# packages/ai-parrot/src/parrot/tools/infographic_recipes/runner.py:204,242
class RecipeRunner:
    def __init__(self, store: AbstractRecipeStore, dataset_manager: DatasetManager, *,
                 artifact_store: Any = None, owner: Any = None,
                 narrator: Optional[Narrator] = None) -> None: ...
    async def run(self, name: str, *, params: dict[str, Any] | None = None,
                  pctx: Any | None = None,
                  recipe_owner: Optional[str] = None) -> RenderedArtifact: ...
    def _assemble_envelope_or_raise(self, recipe, data_model): ...         # line 607 — envelope source for Module 2
    async def _render_or_raise(self, recipe, envelope) -> RenderedArtifact: ...  # line 631

# packages/ai-parrot/src/parrot/outputs/a2ui/baking.py:399
async def persist_envelope(envelope: CreateSurface, store: Any, *, user_id: str,
                           agent_id: str, session_id: str,
                           artifact_id: str | None = None,
                           title: str = "A2UI envelope") -> str:
    # definition=envelope.model_dump(by_alias=True, mode="json") — the stored envelope shape

# packages/ai-parrot/src/parrot/outputs/a2ui/models.py:446
class CreateSurface(A2UIMessageBase):
    surface_id: str = Field(alias="surfaceId")
    catalog_id: str | None = Field(default=None, alias="catalogId")
    send_data_model: bool = Field(default=False, alias="sendDataModel")
    components: list[Component] = Field(default_factory=list)
    data_model: dict[str, Any] = Field(default_factory=dict, alias="dataModel")
    metadata: SurfaceMetadata | None = None

# packages/ai-parrot/src/parrot/outputs/a2ui/artifacts.py:54
class RenderedArtifact(BaseModel):
    artifact_id: str; mime_type: str
    content: bytes | None; path: Path | None          # exactly one set (model_validator)
    source_envelope_ref: str | None = None
    deep_links: list[DeepLink]
    metadata: dict[str, Any]                          # Module 2 attaches "source_envelope" here

# packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/interactive_html.py:295-298
class InteractiveHTMLRenderer(AbstractA2UIRenderer):
    async def render(self, envelope: CreateSurface, *, bake: bool = True) -> RenderedArtifact: ...

# packages/ai-parrot/src/parrot/bots/mixins/infographic_authoring.py:54,279
class InfographicAuthoringMixin:
    async def publish_recipe(self, name: str, descriptor: "SectionDescriptor | str",
                             owner: Optional[str] = None, delivery: Optional[dict] = None,
                             overwrite: bool = False) -> Union[InfographicRecipe, GapReport]: ...
    # publish_surface() (Module 5) sits next to this

# packages/ai-parrot-server/src/parrot/handlers/agent.py:920
class AgentTalk(BaseView):
    async def _resolve_bot(self, data) -> tuple: ...   # used by A2UIHandler._authenticate

# Pg idioms
# handlers/comm_center.py:72-80 — def _get_db(): return AsyncDB("pg", dsn=default_dsn)
# handlers/models/bots.py:29    — "CREATE TABLE IF NOT EXISTS navigator.ai_bots (...)" auto-create pattern

# examples/agents/a2ui/deterministic_refresh_dashboard.py:376+
class RefreshDashboardTool(AbstractTool):
    name = "refresh_dashboard"
    # param precedence to replicate: explicit args → surface_state dataModel.filters → recipe defaults
```

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `PgUISurfaceStore` | `AsyncDB("pg", dsn=default_dsn)` | constructor default | `handlers/comm_center.py:72-80` |
| `PgUISurfaceStore.ensure_schema` | `CREATE TABLE IF NOT EXISTS navigator.*` | DDL exec | pattern: `handlers/models/bots.py:29` |
| `UISurfacesHandler` | `BaseView.json_response/error` | inherited helpers | `handlers/dashboard_handler.py` |
| `UISurfacesHandler` refresh | `RecipeRunner.run(...)` | method call | `tools/infographic_recipes/runner.py:242` |
| `UISurfacesHandler` refresh pctx | `build_principal_context()` | function call | `auth/permission.py:166` |
| `SurfaceNegotiationService` HTML | `InteractiveHTMLRenderer.render()` | guarded import + call | `a2ui_renderers/interactive_html.py:295-298` |
| `A2UIHandler.get` surfaces branch | `SurfaceNegotiationService` | delegation | `handlers/a2ui.py` GET dispatch |
| Route registration | `BotManager.setup_app` | `router.add_view` | `manager/manager.py:2043-2050` |
| `publish_surface` (mixin) | `CreateSurface.model_validate` | validation | `outputs/a2ui/models.py:446` |
| `PublishSurfaceTool` | mixin/store publish | delegation | `bots/mixins/infographic_authoring.py:279` (neighbor) |
| `POST /surfaces` source copy | `ArtifactStore` read | artifact lookup | `storage/artifacts.py` |
| Module 2 | `_assemble_envelope_or_raise` output | metadata attach | `runner.py:607` |

### Does NOT Exist (Anti-Hallucination)

- ~~`navigator.ui_surfaces` / `navigator.ui_surface_shares` tables~~ — Module 1 creates them
- ~~`/api/v1/ui/*` routes~~ — no route under `/api/v1/ui/` exists; Module 4 registers them
- ~~a persistent (non-conversation) surface store~~ — only `ConversationMemorySurfaceStore` exists (`outputs/a2ui/runtime/adapters.py`)
- ~~GET-by-surface-id on `A2UIHandler`~~ — GET today is only SSE + `/capabilities`; Module 4 adds it
- ~~`RecipeRunner.run(include_envelope=...)`~~ — flag does not exist yet; Module 2 adds it
- ~~`RenderedArtifact.metadata["source_envelope"]`~~ — key not produced anywhere yet; Module 2 defines it
- ~~`InfographicAuthoringMixin.publish_surface`~~ — Module 5 creates it (only `publish_recipe` exists, line 279)
- ~~`parrot_tools.ui_surfaces` / `PublishSurfaceTool`~~ — Module 5 creates them
- ~~`DBRecipeStore` on Postgres~~ — it is **Redis**-backed (`outputs/a2ui/recipes/store.py:314`); do NOT reuse it as the surface store
- ~~`RenderedArtifact.persist_envelope()`~~ — `persist_envelope` is a module-level function in `baking.py`, NOT a method
- ~~share/bookmark capability on `DeepLinkService`~~ — deep-link tokens are single-use action-resume (15-min TTL, Redis); unusable for rehydration and NOT extended by this feature
- ~~`UISurfacesHandler`, `SurfaceNegotiationService`, `PgUISurfaceStore`, `UISurfaceRecord`, `UISurfaceShare`~~ — all new in this feature

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- Handler idiom: `BaseView` + `@is_authenticated()`/`@user_session()`
  (`AgentTalk`/`DashboardHandler` style); dispatch on `match_info` inside
  `get`/`post`/`delete` rather than one handler class per sub-path
  (`InfographicTalk` precedent, FEAT-095).
- Route ordering: register literal sub-paths (`.../a2ui/surfaces/{id}` — and
  note `surfaces` is literal relative to the bare `{agent_id}/a2ui` pattern)
  before/alongside the existing block at `manager.py:2043-2050`, mirroring
  the `/capabilities` ordering comment there.
- Negotiation: `?format=json|html` query param wins over `Accept`
  (the `InfographicTalk` convention).
- Pg: `AsyncDB("pg", dsn=default_dsn)` per call-site (`comm_center.py:72-80`);
  DDL auto-create per `handlers/models/bots.py`.
- Share tokens: `secrets.token_urlsafe(32)`, resolve-or-None with **no
  oracle** (missing = revoked = expired → same 410), mirroring the
  deep-link posture. Unlike deep-links these are multi-use and DB-stored.
- Async everywhere; Pydantic for every wire model; `self.logger`, never print.
- Core→server one-way import rule: the mixin (core) must not import the
  server store at module level — inject the store or lazy-import inside the
  method with a clear error when unavailable (same spirit as the guarded
  renderer import).

### Known Risks / Gotchas
- **Jumbo envelopes**: v1 enforces NO size limit on `envelope` jsonb
  (resolved decision) — a pathological surface can make rows large and
  reads slow. Mitigation: the endpoint body cap still bounds ingress;
  revisit with a cap or ArtifactStore overflow if it bites (tracked in §8
  as a deferred consideration only if telemetry shows it).
- **Refresh race**: two concurrent refreshes — last-write-wins on a single
  UPDATE statement; no partial state. Documented, not locked, in v1.
- **Share-token refresh authority**: the bearer triggers work executed with
  the OWNER's `PermissionContext` restricted to the stored recipe replay —
  never widen this to arbitrary params of other recipes; `recipe_name`/
  `recipe_owner` come from the ROW, never the request.
- **Renderer absence**: ai-parrot-visualizations is optional; the HTML lane
  must degrade to 501 + install hint without breaking the JSON lane
  (ImportError-guard pattern used by the recipes render profile).
- **manager.py hotspot**: many in-flight features touch `setup_app` — keep
  the registration diff minimal and localized to the FEAT-469 block.
- **A2UIHandler GET is a StreamResponse path**: the new surfaces branch must
  return a regular `web.Response` BEFORE the SSE stream preparation —
  dispatch on path first, exactly like the existing `/capabilities` branch.
- **`RecipeRunException` mapping**: refresh maps stage-tagged runner errors
  to 422 (bad params) / 502 (data-fetch) style responses — never a raw 500
  with a stack trace.

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| `asyncdb` (`pg`) | already in core deps | Pg store + auto-create DDL |
| `ai-parrot-visualizations` | workspace satellite (optional) | `InteractiveHTMLRenderer` HTML lane |

No new third-party dependencies.

---

## Worktree Strategy

- **Default isolation**: `per-spec` — all tasks sequential in one worktree
  (store → runner extension → handler/service → routes/mirror → writers →
  tests form a mostly linear chain; splitting would only create merge
  friction on `manager.py` and the store interface).
- **Cross-feature dependencies**: none blocking. FEAT-491
  (flex-agent-infographic-a2ui) touches only `examples/` + recipes and ships
  no server handlers — no conflict. `manager.py` is a shared hotspot —
  keep the diff minimal.
- **Recommended branch / worktree**:
  ```bash
  git checkout dev && git pull origin dev
  git worktree add -b feat-492-a2ui-surface-rehydration \
    .claude/worktrees/feat-492-a2ui-surface-rehydration HEAD
  ```

---

## 8. Open Questions

- [x] How does the refresh path obtain the envelope (not the rendered
      artifact)? — *Resolved 2026-09-01 (Jesus Lara)*: expose it on the
      result — minimal `RecipeRunner` extension attaching the assembled
      `CreateSurface` dump at `RenderedArtifact.metadata["source_envelope"]`
      behind `include_envelope=True` (Module 2). One `run()`, no extra I/O.
- [x] Where does the `publish_surface` tool live? — *Resolved 2026-09-01
      (Jesus Lara)*: BOTH — a method on `InfographicAuthoringMixin` next to
      `publish_recipe` (programmatic API) AND a thin tool wrapper in
      `parrot_tools` (Module 5).
- [x] Does the `A2UIHandler` mirror route also honour `Accept: text/html`? —
      *Resolved 2026-09-01 (Jesus Lara)*: YES — both routes share the same
      `SurfaceNegotiationService`; the mirror route is not protocol-strict.
- [x] Envelope size policy for `navigator.ui_surfaces.envelope` (jsonb)? —
      *Resolved 2026-09-01 (Jesus Lara)*: no limit in v1; rely on the
      endpoint body cap. Revisit only if telemetry shows jumbo rows.
- [x] Payload of the bookmark GET — *Resolved in brainstorm*: JSON + HTML
      content negotiation (`Accept`, `?format=` override).
- [x] Persistence backend — *Resolved in brainstorm*: Postgres,
      `navigator.ui_surfaces`, uuid key, auto-create table, envelope in the
      `persist_envelope()` dump shape.
- [x] Auth/ownership — *Resolved in brainstorm*: authenticated owner +
      opaque DB share tokens granting read+refresh (refresh with the owner's
      PermissionContext); no edit/delete/re-share for bearers.
- [x] Refresh semantics — *Resolved in brainstorm*: `recipe_ref` stored on
      the row; `RecipeRunner` replay with request > stored > defaults param
      precedence; update in place (no versioning).
- [x] Writers — *Resolved in brainstorm*: agent tool + frontend POST (both
      lanes in v1).
- [x] HTML production — *Resolved in brainstorm*: on-the-fly render with
      `InteractiveHTMLRenderer` (no pre-baked HTML, no cache in v1).
- [ ] Share-token default TTL: none (live until revoked) vs a default expiry
      (e.g. 90 days)? Implementation default: `expires_at NULL` (no expiry)
      with the column ready — *Owner: Jesus Lara*
- [ ] Should `GET /api/v1/ui/surfaces` (list) include shared-with-me surfaces
      in v1, or owner-only? Implementation default: owner-only —
      *Owner: Jesus Lara*
- [ ] DSN/config source: same `parrot.conf.default_dsn` used by
      comm_center/bots handlers, or a dedicated `UI_SURFACES_DSN` override?
      Implementation default: `default_dsn` — *Owner: Jesus Lara*
- [ ] Exact injection seam for the store in the core-side mixin
      (constructor kwarg vs lazy import) — decide at implementation
      respecting the one-way import rule — *Owner: implementer*

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-09-01 | Jesus Lara | Initial draft from sdd/proposals/a2ui-surface-rehydration.brainstorm.md |
