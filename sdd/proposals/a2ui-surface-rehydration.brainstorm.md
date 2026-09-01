---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Brainstorm: A2UI Surface Rehydration — persistent serving of dashboards, infographics & widgets

**Date**: 2026-09-01
**Author**: Jesus Lara
**Status**: exploration
**Recommended Option**: A

---

## Problem Statement

A2UI today has full **interaction** and **refresh** support (FEAT-469
`A2UIHandler`: envelope dispatch, SSE stream, capabilities; FEAT-324/326
recipes + `RecipeRunner` deterministic replay), but **no serving/rehydration
lane**: a generated surface (dashboard, infographic, widget/KPI) lives only in
`ConversationMemorySurfaceStore` (conversation memory) and reaches the
frontend exclusively inside the turn response (`a2ui_envelope`) or via the
session's SSE stream.

Consequences:
- A user cannot bookmark a dashboard URL and open it later (or after a page
  reload) — there is no `GET` that returns the persisted A2UI object by id.
- The frontend renderer cannot cold-mount a previously generated surface
  outside the originating conversation/session.
- Deep-links (FEAT-273/469) do NOT cover this: they are **single-use,
  15-minute TTL action-resume tokens** bound to an existing session, and
  their result is an agent turn — not the surface object.
- FEAT-491 (flex-agent-infographic-a2ui) is an example agent and explicitly
  ships "No new server handlers", so this gap stays open without a dedicated
  feature.

Affected users: frontend developers (navigator renderer), end users
(bookmarks, shared dashboards), and agents that publish durable dashboards.

## Constraints & Requirements

- New endpoint `GET /api/v1/ui/surfaces/{id}` returning the persisted A2UI
  object at any time — including from a bookmarked URL, outside the original
  session. *(user decision)*
- Also a GET-by-id route on `A2UIHandler` (`/api/v1/agents/{agent_id}/a2ui/...`)
  for renderer-side symmetry. *(user decision)*
- Content negotiation: `Accept: application/json` → rehydratable A2UI
  envelope; `Accept: text/html` → server-side rendered HTML (open the
  bookmark directly in a browser without the frontend). *(user decision)*
- Persistence in **Postgres**, table **`navigator.ui_surfaces`**, structured
  lookup, uuid key, envelope structure generated the way
  `persist_envelope()` dumps it (`CreateSurface.model_dump(by_alias=True,
  mode="json")`). The store module must **auto-create the table if it does
  not exist**. *(user decision)*
- Refresh must work exactly like
  `examples/agents/a2ui/deterministic_refresh_dashboard.py`:
  `callAgentFunction → refresh_dashboard` semantics — re-run the recipe with
  fresh data / param overrides via `RecipeRunner`. Stored surface row carries
  `recipe_ref` (agent_id + recipe name/owner + params) and refresh **updates
  the row in place** (`updated_at`); the bookmark always shows the latest.
  *(user decision)*
- Writers (v1): an **agent tool** (`publish_surface`) AND a **frontend POST**
  ("pin/save" any chat result). *(user decision)*
- Sharing: **opaque tokens stored in DB** (revocable, optional TTL, listable
  by owner) granting **read + refresh** — refresh under a share token runs
  with the OWNER's `PermissionContext` restricted to the recipe replay; no
  edit/delete/re-share. *(user decision)*
- HTML lane rendered **on-the-fly** with the `interactive-html` renderer
  (ai-parrot-visualizations) — always consistent with the JSON. *(user decision)*
- Auth default: `is_authenticated` + owner match (deny-by-default
  `PermissionContext`, same posture as `A2UIHandler`).
- No new external dependencies: `asyncdb` (`pg` driver) is already a core dep;
  ai-parrot-visualizations is an existing workspace satellite (optional
  import with actionable `ImportError`, same degradation the recipes render
  profile already uses).

---

## Options Explored

### Option A: Dedicated `ui_surfaces` plane — Pg store + `UISurfacesHandler` + A2UIHandler GET

A new small persistence module (`PgUISurfaceStore`) owning the
`navigator.ui_surfaces` table (auto-`CREATE TABLE IF NOT EXISTS`, the exact
pattern of `handlers/models/bots.py`) plus a share-token table
(`navigator.ui_surface_shares`). A new REST handler (`UISurfacesHandler`,
`navigator.views.BaseView` like `DashboardHandler`) exposes:

- `GET /api/v1/ui/surfaces/{surface_id}` — negotiated JSON envelope / HTML
  (owner session, or `?share=<token>`).
- `GET /api/v1/ui/surfaces` — list the owner's surfaces.
- `POST /api/v1/ui/surfaces` — frontend "pin/save" (envelope inline, or the
  `artifact_id` of a source envelope already persisted via ArtifactStore).
- `POST /api/v1/ui/surfaces/{surface_id}/refresh` — merge request params over
  stored `recipe_params`, run `RecipeRunner.run(recipe, params, pctx)`,
  update the row in place, return the refreshed object (negotiated).
- `POST .../share` / `DELETE .../share/{token}` — mint / revoke share tokens.

`A2UIHandler` gains `GET /api/v1/agents/{agent_id}/a2ui/surfaces/{surface_id}`
delegating to the same store/service (returned with the A2UI media type).
The agent-side writer is a `publish_surface` tool (mirroring how the
deterministic example pairs `publish_recipe` + `RefreshDashboardTool`).

✅ **Pros:**
- Structured lookup, ownership, sharing and refresh metadata are first-class
  columns — exactly what the bookmark/share/refresh semantics need.
- Cleanly separated from conversation state; `ConversationMemorySurfaceStore`
  stays untouched (live sessions keep working as today).
- Matches every user decision directly (Pg, auto-create, negotiated GET,
  share tokens, in-place refresh).
- Reuses the whole FEAT-324/326×469 refresh machinery verbatim.

❌ **Cons:**
- New table + handler + routes + tool = the largest surface area of the
  three options.
- Envelope JSON is duplicated between `navigator.ui_surfaces.envelope` and
  any ArtifactStore copy made by `persist_envelope` (acceptable: different
  planes, different lifecycles).

📊 **Effort:** Medium-High

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `asyncdb` (`pg`) | Pg access + auto-create DDL | already a core dep (`AsyncDB("pg", dsn=...)`, comm_center.py:80) |
| `ai-parrot-visualizations` | `InteractiveHTMLRenderer` for the HTML lane | workspace satellite; optional import, actionable ImportError |

🔗 **Existing Code to Reuse:**
- `packages/ai-parrot-server/src/parrot/handlers/a2ui.py` — `A2UIHandler` (auth/session resolution, media type, route style)
- `packages/ai-parrot/src/parrot/tools/infographic_recipes/runner.py` — `RecipeRunner.run()` (refresh lane)
- `packages/ai-parrot/src/parrot/outputs/a2ui/baking.py` — `persist_envelope()` (envelope dump shape)
- `packages/ai-parrot-server/src/parrot/handlers/models/bots.py` — `CREATE TABLE IF NOT EXISTS navigator.*` auto-create pattern
- `packages/ai-parrot/src/parrot/auth/permission.py` — `build_principal_context()`
- `examples/agents/a2ui/deterministic_refresh_dashboard.py` — `RefreshDashboardTool` param-merge precedence

---

### Option B: Extend the existing ArtifactStore plane

Surfaces are already persistable as artifacts: `persist_envelope()` saves the
`CreateSurface` as `ArtifactType.INTERACTIVE` with the envelope in
`definition`. This option adds a public GET on the artifacts handler
(`handlers/artifacts.py`) + metadata to `Artifact` for sharing/refresh, and
skips the new table entirely.

✅ **Pros:**
- Zero new persistence plane; smallest schema footprint.
- `persist_envelope()` already produces the stored record.

❌ **Cons:**
- ArtifactStore is blob-oriented (inline/S3 overflow via `definition_ref`),
  not a structured-lookup plane — owner listing, share tokens, recipe_ref and
  in-place refresh metadata would be bolted onto a model shared by every
  other artifact type.
- Contradicts the explicit user decision (Postgres `navigator.ui_surfaces`
  with structured lookup).
- Mixing "UI bookmark" semantics into artifact CRUD muddies both APIs.

📊 **Effort:** Medium

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| — | no new deps | |

🔗 **Existing Code to Reuse:**
- `packages/ai-parrot/src/parrot/storage/artifacts.py` — `ArtifactStore`
- `packages/ai-parrot/src/parrot/outputs/a2ui/baking.py` — `persist_envelope()`
- `packages/ai-parrot-server/src/parrot/handlers/artifacts.py` — artifact CRUD handler

---

### Option C (unconventional): Recipe-first virtual surfaces — replay on every GET

Do not persist envelopes at all. A surface row is just
`(surface_id, recipe_ref, params, metadata)`; every `GET` replays the recipe
deterministically via `RecipeRunner` and returns the freshly assembled
envelope (optionally memoized). "Refresh" becomes a no-op concept — every
read IS a refresh.

✅ **Pros:**
- Never stale; single source of truth (the recipe); tiny storage.
- Deterministic replay is exactly what FEAT-324/326 was built for.

❌ **Cons:**
- GET latency = full data fetch + transform + assemble on every bookmark open;
  DatasetManager and the data plane must be up just to *view*.
- Cannot pin non-recipe surfaces (an ad-hoc chart from a chat turn has no
  recipe) — breaks the "frontend pin/save" writer decision.
- Puts read-amplified load on the data plane for what is usually a view.

📊 **Effort:** Medium

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| — | no new deps | |

🔗 **Existing Code to Reuse:**
- `packages/ai-parrot/src/parrot/tools/infographic_recipes/runner.py` — `RecipeRunner`
- `packages/ai-parrot/src/parrot/outputs/a2ui/recipes/store.py` — recipe stores

---

## Recommendation

**Option A** is recommended because:

- It is the only option satisfying every recorded user decision (Pg
  structured store with auto-create, negotiated GET, owner+share auth,
  in-place refresh, dual writers).
- It composes the best parts of the others instead of competing with them:
  the stored envelope uses **B's** `persist_envelope()` dump shape verbatim,
  and the refresh lane is **C's** deterministic replay — triggered on demand
  (refresh button / `POST /refresh` / `callAgentFunction`), not on every read,
  so bookmarks stay fast and the data plane isn't read-amplified.
- Surfaces without a `recipe_ref` (pinned ad-hoc chat results) degrade
  gracefully: servable snapshot, refresh returns 409/422 "not refreshable" —
  impossible under Option C.
- Tradeoff accepted: more moving parts (table, handler, tool, routes) and a
  second copy of the envelope JSON. Both are bounded and local to the new
  plane.

---

## Feature Description

### User-Facing Behavior

- A user opens `GET /api/v1/ui/surfaces/{surface_id}` (bookmark, reload, new
  tab, months later). Authenticated owner → the object; browser hit with
  `Accept: text/html` → a self-contained interactive HTML page; frontend hit
  with `Accept: application/json` → the rehydratable A2UI envelope
  (`createSurface` shape: `surfaceId`, `components`, `dataModel`,
  `catalogId`, plus surface metadata: kind, title, timestamps, refreshable
  flag) which the navigator renderer cold-mounts.
- A "Refresh" action (frontend button → `POST .../refresh`, or the A2UI
  renderer's `callAgentFunction → refresh_dashboard`) re-runs the recipe with
  fresh data; optional param overrides (e.g. `window=h2`, `plan=Enterprise`)
  produce a filtered variant, same as the deterministic example. The stored
  surface is updated in place — the next bookmark open shows the refreshed data.
- The owner can mint a share link (`POST .../share`) → an opaque token URL
  (`?share=<token>`) that grants read + refresh (no edit/delete/re-share),
  listable and revocable at any time; optional expiry.
- Agents durably publish dashboards via a `publish_surface` tool; users pin
  any chat-generated surface from the frontend via `POST /api/v1/ui/surfaces`.

### Internal Behavior

1. **Store**: `PgUISurfaceStore` owns `navigator.ui_surfaces`
   (`surface_id uuid PK`, `kind` (dashboard|infographic|widget), `title`,
   `envelope jsonb` (the `persist_envelope()` dump shape), `catalog_id`,
   `agent_id`, `user_id`, `session_id`, `recipe_name`, `recipe_owner`,
   `recipe_params jsonb`, `created_at`, `updated_at`) and
   `navigator.ui_surface_shares` (`token PK`, `surface_id FK`, `permissions`,
   `expires_at`, `revoked`, `created_at`). A `ensure_schema()` method runs
   `CREATE SCHEMA/TABLE IF NOT EXISTS` on first use (pattern:
   `handlers/models/bots.py`), via `AsyncDB("pg", dsn=default_dsn)`.
2. **Read path**: handler resolves auth (owner session OR valid share token),
   loads the row, negotiates: JSON → envelope + metadata; HTML →
   `InteractiveHTMLRenderer.render(CreateSurface.model_validate(envelope))`
   on the fly (import guarded; 501 with actionable message if the
   visualizations package is absent).
3. **Refresh path**: request params are merged over stored `recipe_params`
   (request > stored > recipe defaults — same precedence as
   `RefreshDashboardTool`); `RecipeRunner.run(recipe_name, params=merged,
   pctx=owner_pctx, recipe_owner=...)` replays; the resulting envelope
   replaces `envelope`, `recipe_params` and `updated_at` in the row; response
   returns the refreshed object. Share-token refresh builds the OWNER's
   `PermissionContext` (via `build_principal_context`) — bearer identity is
   never used for data access. Rows without `recipe_ref` → 409 not refreshable.
4. **A2UIHandler leg**: `GET /api/v1/agents/{agent_id}/a2ui/surfaces/{surface_id}`
   reuses the store through the same service, responds with the A2UI media
   type; the renderer's `callAgentFunction → refresh_dashboard` keeps working
   through the existing POST dispatch (the tool now also updates the
   persisted row when the surface is a published one).
5. **Writers**: `publish_surface` tool (agent lane) validates the envelope,
   derives `recipe_ref` when the surface came from a recipe, inserts/upserts;
   `POST /api/v1/ui/surfaces` (frontend lane) accepts an inline envelope or a
   `source artifact_id` to copy from ArtifactStore.

### Edge Cases & Error Handling

- Unknown/foreign `surface_id` → 404 (no owner-existence oracle across users).
- Expired/revoked share token → 410, indistinguishable from missing (mirrors
  the deep-link "no oracle" posture).
- Refresh with invalid params → 422 naming the offending param (RecipeRunner's
  stage-tagged `RecipeRunException` mapped, never a 500).
- Refresh race (two concurrent refreshes) → last-write-wins on the row;
  UPDATE is a single statement, no partial state.
- Non-refreshable surface (no `recipe_ref`) → 409 with a machine-readable
  reason; the JSON metadata carries `refreshable: false` so the frontend can
  hide the button.
- HTML lane without ai-parrot-visualizations installed → 501 + install hint
  (same degradation contract as the recipe render profile's ImportError).
- Oversized envelopes: jsonb comfortably holds typical surfaces; >200 KB
  envelopes already have the ArtifactStore overflow convention — an open
  question below decides whether ui_surfaces mirrors it or caps size.

---

## Capabilities

### New Capabilities
- `a2ui-surface-rehydration`: persistent Pg-backed serving of A2UI surfaces
  by id — negotiated GET, pin/publish writers, share tokens, deterministic
  refresh in place.

### Modified Capabilities
- `a2ui-agent-functions` (FEAT-469): `A2UIHandler` gains the GET-by-id
  surfaces route; runtime behavior otherwise untouched.

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/handlers/a2ui.py` | extends | new GET surfaces sub-route dispatch |
| `packages/ai-parrot-server/src/parrot/manager/manager.py` | modifies | register `/api/v1/ui/surfaces*` routes + the a2ui sub-route (near lines 2043-2050) |
| new: `packages/ai-parrot-server/src/parrot/handlers/ui_surfaces.py` | new | `UISurfacesHandler` (BaseView) |
| new: Pg surface store module (server pkg) | new | `navigator.ui_surfaces` + `navigator.ui_surface_shares`, auto-create |
| `parrot/tools/` (core or parrot_tools) | new tool | `publish_surface` (agent writer lane) |
| `parrot/tools/infographic_recipes/runner.py` | depends on | refresh replay; envelope-access question below |
| `parrot/outputs/a2ui/baking.py` | depends on | envelope dump shape (`persist_envelope` convention) |
| `ai-parrot-visualizations` `InteractiveHTMLRenderer` | depends on (optional) | HTML lane, guarded import |
| `ConversationMemorySurfaceStore` | none | untouched; live-session plane stays as is |
| deep-links (FEAT-273) | none | complementary; a future deep-link could resolve to a surface URL |

No breaking changes. No new external dependencies.

---

## Code Context

### User-Provided Code

*(none — user referenced `persist_envelope()` and
`examples/agents/a2ui/deterministic_refresh_dashboard.py` by name; both
verified below)*

### Verified Codebase References

#### Classes & Signatures
```python
# From packages/ai-parrot-server/src/parrot/handlers/a2ui.py (verified 2026-09-01)
class A2UIHandler(AgentTalk):
    def _resolution_data(self) -> dict[str, Any]: ...
    async def _authenticate(self, data) -> tuple: ...            # (agent, user_id, session_id, err)
    @staticmethod
    def _build_runtime(agent, user_id) -> tuple[A2UIRuntime, ConversationMemorySurfaceStore]: ...
    async def post(self) -> web.Response: ...                    # envelope dispatch
    async def get(self) -> web.StreamResponse: ...               # SSE | /capabilities
# Routes registered at packages/ai-parrot-server/src/parrot/manager/manager.py:2045-2046

# From packages/ai-parrot/src/parrot/tools/infographic_recipes/runner.py:204,242
class RecipeRunner:
    def __init__(self, store: AbstractRecipeStore, dataset_manager: DatasetManager,
                 *, artifact_store: Any = None, owner: Any = None,
                 narrator: Optional[Narrator] = None) -> None: ...
    async def run(self, name: str, *, params: dict[str, Any] | None = None,
                  pctx: Any | None = None,
                  recipe_owner: Optional[str] = None) -> RenderedArtifact: ...

# From packages/ai-parrot/src/parrot/outputs/a2ui/recipes/store.py:175,230,304
class AbstractRecipeStore(ABC): ...   # save/get/list/delete, keyed by (name, owner)
class FileRecipeStore(AbstractRecipeStore): ...
class DBRecipeStore(AbstractRecipeStore): ...   # Redis-backed (NOT Postgres)

# From packages/ai-parrot/src/parrot/outputs/a2ui/baking.py:399
async def persist_envelope(envelope: CreateSurface, store: Any, *,
                           user_id: str, agent_id: str, session_id: str,
                           artifact_id: str | None = None,
                           title: str = "A2UI envelope") -> str:
    # persists ArtifactType.INTERACTIVE with
    # definition=envelope.model_dump(by_alias=True, mode="json")

# From packages/ai-parrot/src/parrot/outputs/a2ui/models.py:446
class CreateSurface(A2UIMessageBase):
    surface_id: str = Field(alias="surfaceId")
    catalog_id: str | None = Field(default=None, alias="catalogId")
    send_data_model: bool = Field(default=False, alias="sendDataModel")
    components: list[Component] = Field(default_factory=list)
    data_model: dict[str, Any] = Field(default_factory=dict, alias="dataModel")
    metadata: SurfaceMetadata | None = None

# From packages/ai-parrot/src/parrot/outputs/a2ui/artifacts.py:54
class RenderedArtifact(BaseModel):
    artifact_id: str; mime_type: str
    content: bytes | None; path: Path | None      # exactly one set
    source_envelope_ref: str | None = None        # ArtifactStore id of the source envelope
    deep_links: list[DeepLink]; metadata: dict[str, Any]

# From packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/interactive_html.py:295-298
class InteractiveHTMLRenderer(AbstractA2UIRenderer):
    async def render(self, envelope: CreateSurface, *, bake: bool = True) -> RenderedArtifact: ...

# From packages/ai-parrot/src/parrot/outputs/a2ui/deeplink.py:92,123,171
class DeepLinkService:      # single-use, TTL(900s) Redis opaque tokens — action resume ONLY
    async def mint(...) -> DeepLink: ...
    async def consume(self, token: str) -> ResumePayload: ...

# From examples/agents/a2ui/deterministic_refresh_dashboard.py:376+
class RefreshDashboardTool(AbstractTool):
    name = "refresh_dashboard"
    # precedence: explicit args → surface_state dataModel.filters → recipe defaults
    # runs: await self._runner.run(RECIPE_NAME, params=params, pctx=self._pctx)

# From packages/ai-parrot/src/parrot/auth/permission.py:166
def build_principal_context(principal, channel, ...): ...   # deny-by-default roles

# Pg access pattern — packages/ai-parrot-server/src/parrot/handlers/comm_center.py:72-80
def _get_db() -> AsyncDB:
    return AsyncDB("pg", dsn=default_dsn)
# Auto-create pattern — packages/ai-parrot-server/src/parrot/handlers/models/bots.py:29
#   "CREATE TABLE IF NOT EXISTS navigator.ai_bots (...)"

# From packages/ai-parrot-server/src/parrot/handlers/dashboard_handler.py
class DashboardHandler(BaseView): ...   # BaseView CRUD idiom to mirror (NOT A2UI — Mongo dashboards/tabs)
```

#### Verified Imports
```python
from parrot.handlers.agent import AgentTalk                       # handlers/a2ui.py:47
from parrot.outputs.a2ui.models import CreateSurface              # outputs/a2ui/models.py:446
from parrot.outputs.a2ui.baking import persist_envelope           # outputs/a2ui/baking.py:36 (__all__)
from parrot.outputs.a2ui.artifacts import RenderedArtifact, DeepLink
from parrot.outputs.a2ui.runtime.adapters import ConversationMemorySurfaceStore, ToolManagerExecutor
from parrot.tools.infographic_recipes.runner import RecipeRunner
from parrot.auth.permission import build_principal_context
from asyncdb import AsyncDB                                       # core dep (bots.py:5)
from navigator.views import BaseView
```

#### Key Attributes & Constants
- `A2UI_MEDIA_TYPE` → `parrot.a2a.models` (used by A2UIHandler responses)
- `ArtifactType.INTERACTIVE` → `parrot.storage.models` (envelope persistence type)
- Deep-link TTL: `_DEFAULT_TTL_SECONDS = 15 * 60` (deeplink.py:42) — why deep-links can't serve bookmarks

### Does NOT Exist (Anti-Hallucination)
- ~~`navigator.ui_surfaces` table~~ — does not exist anywhere; this feature creates it
- ~~`/api/v1/ui/surfaces*` routes~~ — no route under `/api/v1/ui/` exists
- ~~a persistent (non-conversation) SurfaceStore~~ — only `ConversationMemorySurfaceStore` exists (runtime/adapters.py)
- ~~GET-by-surface-id on `A2UIHandler`~~ — GET is only SSE stream + `/capabilities`
- ~~`DBRecipeStore` on Postgres~~ — it is **Redis**-backed (store.py:314); do not assume a Pg recipe store
- ~~share/bookmark tokens~~ — `DeepLinkService` tokens are single-use action-resume, unusable for rehydration
- ~~an envelope-returning `RecipeRunner.run()` variant~~ — `run()` returns `RenderedArtifact` only; the envelope is internal (`_assemble_envelope_or_raise`) or reachable via `source_envelope_ref` in ArtifactStore (see Open Questions)
- ~~`RenderedArtifact.persist_envelope()`~~ — `persist_envelope` is a module-level function in `baking.py`, NOT a method on `RenderedArtifact`

---

## Parallelism Assessment

- **Internal parallelism**: moderate — the Pg store module and the share-token
  mechanics are independent of the HTML render lane; but handler → routes →
  A2UIHandler leg → tool form a mostly linear dependency chain on the store.
- **Cross-feature independence**: FEAT-491 (flex example agent) touches only
  `examples/` + recipes and declares "no new server handlers" — no conflict.
  `manager.py` route registration is a shared hotspot with many features —
  keep that diff minimal.
- **Recommended isolation**: `per-spec` (single worktree, sequential tasks).
- **Rationale**: one new plane with a linear build order; splitting worktrees
  would only create merge friction on `manager.py` and the store interface.

---

## Open Questions

- [ ] How does the refresh path obtain the **envelope** (not the rendered
  artifact)? Options: (a) read `RenderedArtifact.source_envelope_ref` back
  from ArtifactStore after `run()`; (b) add a minimal envelope-returning hook
  to `RecipeRunner` (e.g. expose the assembled envelope on the result); (c) a
  render-profile that emits the envelope as the artifact. — *Owner: spec/implementer*
- [ ] Envelope size policy for `navigator.ui_surfaces.envelope` (jsonb): cap,
  or mirror ArtifactStore's >200 KB overflow (`definition_ref`)? — *Owner: Jesus Lara*
- [ ] Where does the `publish_surface` tool live — core `parrot/tools/` base
  machinery vs `parrot_tools` (ai-parrot-tools) vs an authoring-mixin method
  next to `publish_recipe`? — *Owner: Jesus Lara*
- [ ] Share-token default TTL: none (live until revoked) vs a default expiry
  (e.g. 90 days)? — *Owner: Jesus Lara*
- [ ] Should `GET /api/v1/ui/surfaces` (list) include shared-with-me surfaces
  in v1, or owner-only? — *Owner: Jesus Lara*
- [ ] DSN/config source for the Pg store: same `default_dsn` used by
  comm_center/bots handlers, or a dedicated `UI_SURFACES_DSN` override? —
  *Owner: Jesus Lara*
- [ ] Should the `A2UIHandler` mirror route
  (`GET /api/v1/agents/{agent_id}/a2ui/surfaces/{surface_id}`) also honour
  `Accept: text/html` content negotiation, or stay protocol-strict (A2UI
  media type envelope only), leaving the HTML lane exclusively to
  `GET /api/v1/ui/surfaces/{id}`? — *Owner: Jesus Lara*
