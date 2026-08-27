---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Brainstorm: UI Server Backend — Embedded Admin UI Foundation

**Date**: 2026-08-27
**Author**: Jesus Lara
**Status**: exploration
**Recommended Option**: A

> First of a series of features giving `ai-parrot-server` a self-distributed
> administrative UI. This spec builds the FOUNDATION: authentication/login,
> app shell (layout + router + theming), home, a status dashboard, the
> build/packaging/serving pipeline, Pydantic→TS type codegen, and one
> read-only module (agents listing) that validates the module pattern.
> Subsequent specs add feature/admin modules on top of this base.
>
> Consolidates three prior documents:
> - `sdd/proposals/admin_ui.proposal.md` (2026-08-27) — framework decision:
>   Svelte 5 + Vite, no SvelteKit; bundle pre-compiled into the
>   `ai-parrot-server` build.
> - `sdd/proposals/ui-agent-management.brainstorm.md` (2026-03-18) — agent
>   list view + tabbed-wizard form design; the list view is absorbed into
>   this spec's read-only module, the tabbed CRUD form is deferred to the
>   follow-up module spec (its `flowbite-svelte` choice is superseded by
>   Bits UI + shadcn-svelte per the admin_ui proposal).
> - `sdd/proposals/agentstudio-management.brainstorm.md` (2026-08-27) — the
>   `/api/v1/astudio/*` management API is this UI's natural backend
>   counterpart; v1 consumes today's endpoints and migrates when astudio
>   lands.

---

## Problem Statement

ai-parrot only ships backend. At corporate level (TROC) a full Svelte 5 UI
exists (`navigator-frontend-next`), but an external open-source adopter who
runs ai-parrot in `server`, `autonomous`, dev-loop, AgentCrew or AgentsFlow
mode has **no administration surface at all**: no login page, no way to see
what agents are registered, no server health view. Everything requires raw
API calls.

Worse, dangling references already assume an admin UI exists:
`parrot-formdesigner`'s injected auth script redirects browsers to `/admin`
on missing/expired token (`packages/parrot-formdesigner/src/parrot_formdesigner/ui/templates.py:157,176`)
— a route nothing serves today. `navigator_auth` defaults
`AUTH_LOGIN_FAILED_URI` to `/login`, also unregistered.

**Who is affected**: OSS adopters (primary — "pip install and you get an
admin console"), TROC operators running bare ai-parrot deployments, and the
framework itself (every future admin feature needs this base to exist once,
not per-feature ad-hoc HTML like `autonomous/admin.py` or the dev-loop
example consoles).

**Why now**: the Agent Studio management API (`agentstudio-management`
brainstorm, same date) is being designed; building its UI counterpart's
foundation in parallel means modules land on a ready shell instead of each
inventing serving/auth/build plumbing.

## Constraints & Requirements

Decisions fixed during interactive discovery (Rounds 0–3):

- **Flow**: `type: feature`, `base_branch: dev`.
- **Framework**: Svelte 5 + Vite, **no SvelteKit** — SPA with a lightweight
  client router (decision inherited from `admin_ui.proposal.md`; enables
  direct reuse of Bits UI / shadcn-svelte / rune-class patterns).
- **Auth**: **navigator-auth always** (already a core dependency:
  `navigator-auth>0.20.9`, `navigator-session>=0.6.5` in
  `packages/ai-parrot/pyproject.toml:72-73`). No parallel auth system.
  **Any authenticated user** may enter; fine-grained per-module authorization
  comes later (PBAC already filters what the API returns).
- **Reuse**: **copy-in, shadcn style** from
  `/home/jesuslara/proyectos/navigator-frontend-next` — components, tokens
  and patterns are copied and may diverge; no shared npm package.
- **Location**: source AND compiled `dist/` live **inside
  `packages/ai-parrot-server/`** (UI source outside `src/`, dist inside the
  `parrot.server` package as package-data).
- **Mount**: served under **`/admin/`**, **always active** when the dist is
  present in the installed package (no enable flag); JSON API is same-origin
  (no CORS).
- **Build**: `dist/` is **NOT committed to git**; the release CI builds the
  Node bundle and injects it into the wheel. Installs from git require Node
  to get the UI; the server must degrade gracefully (log + skip mount) when
  dist is absent.
- **Dashboard v1**: server status + inventory — version, uptime, counts of
  registered agents/crews, dependency health (DB/Redis) — only data the
  server already knows; no new telemetry pipeline.
- **TS types**: Pydantic JSON Schema → TypeScript codegen **from the start**
  (`model_json_schema()` → `json-schema-to-typescript`, the pattern already
  specified — but never implemented — in
  `sdd/proposals/dev-loop-session-state-hitl.brainstorm.md:497-509`).
- Async-first: no blocking work in the aiohttp handlers; `uv` for Python,
  Node tooling only for UI development/CI.
- Security: SPA assets are public by design (navigator-auth auto-excludes
  static resources — see Code Context); everything sensitive stays behind
  the authenticated `/api/v1/*` surface.

---

## Options Explored

### Option A: Embedded SPA in `ai-parrot-server` — Vite source tree + CI-built dist as package-data, mounted by a `setup_admin_ui(app)` module

The `ai-parrot-server` package gains a UI source tree
(`packages/ai-parrot-server/ui/` — Vite project, not shipped) and a runtime
asset home (`packages/ai-parrot-server/src/parrot/server/ui/dist/` —
shipped via `[tool.setuptools.package-data]`, gitignored). A new
`parrot/server/ui/serving.py` exposes `setup_admin_ui(app)` following the
established `setup_*_routes(app)` pattern (`credentials.py:506`,
`mcp_helper.py:420`, `thales.py:248`): it resolves the dist dir
package-relative via `__file__` (same trick as the Telegram static mount,
`app.py:94-102`), mounts `add_static('/admin/assets/', ...)`, registers a
catch-all `GET /admin{tail:.*}` → `FileResponse(index.html)` for the SPA
router, registers the paths in navigator-auth's exclude list, and logs +
skips when dist is missing. `BotManager.setup()` calls it so every
deployment gets the UI without touching `app.py`.

The SPA itself: login page posting `POST /api/v1/login` (navigator-auth,
JSON + session cookie + token), token stored in `localStorage` under
`ai_parrot_token` (the key `parrot-formdesigner` already expects), an axios
wrapper copied from `navigator-frontend-next/src/lib/api/http.ts`, shell
with sidebar navigation, home, dashboard fed by one new
`GET /api/v1/admin/status` endpoint, and an agents list module consuming
the existing `GET /api/v1/bots` (merged DB + registry, PBAC-filtered).
A `scripts/generate_ts_types.py` + npm step emits TS interfaces from the
Pydantic response models at UI build time.

✅ **Pros:**
- Matches every locked decision; zero new distributions, zero new deps for
  the Python side.
- `pip install ai-parrot-server` (wheel) suffices — Node only for UI devs
  and CI, exactly the `parrot.integrations.telegram` / `parrot.voice`
  packaging precedent generalized.
- `setup_admin_ui(app)` is library-owned: works in `server`, `autonomous`
  and custom deployments, not only the repo's `app.py`.
- Fixes the dangling `/admin` redirect in parrot-formdesigner for free.
- Copy-in reuse gives day-one access to 21 vendored shadcn primitives, the
  Tailwind v4 token chain, `navauth` providers and the rune-class patterns.

❌ **Cons:**
- Release pipeline gets a Node stage; a wheel built without it silently
  ships no UI (mitigated by a CI check that the wheel contains
  `index.html`).
- Installs from git (`pip install git+…`) have no UI unless the user runs
  the build — accepted in discovery.
- setuptools `package-data` globs are non-recursive per key, so Vite output
  layout must be flattened or enumerated per subdirectory.

📊 **Effort:** High (but it's the foundation for a feature series)

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `svelte` ^5 | UI framework | 5.55.7 installed in navigator-frontend-next |
| `vite` ^5/^7 | build tool + dev server | 5.4.21 in corporate; evaluate current major at scaffold time |
| `bits-ui` ^2.18 | headless component primitives | Svelte-only; 2.18.1 in corporate |
| `tailwindcss` ^4 | styling, CSS-first tokens | 4.3.0 in corporate; `@theme` in CSS, no JS config |
| `tailwind-variants`, `tailwind-merge`, `clsx` | class composition (`cn()`) | 3.2.2 / 3.6.0 / 2.1.1 |
| `@lucide/svelte` | icons | ^0.561.0 in corporate |
| `axios` | API client (copied `http.ts` uses it) | ^1.11.0; or port wrapper to `fetch` |
| SPA router (e.g. `svelte-spa-router` or hand-rolled) | client routing | corporate has none (SvelteKit); pick lightest that supports guards |
| `json-schema-to-typescript` | Pydantic JSON Schema → TS interfaces | pattern from dev-loop-session-state brainstorm; devDependency |
| `pnpm` 9 | package manager | matches corporate (`pnpm@9.15.9`) |
| `typescript` ^5.6 | type checking | 5.9.3 in corporate |

🔗 **Existing Code to Reuse:**
- `navigator-frontend-next/src/lib/ui/internal/shadcn/ui/` — 21 vendored shadcn-svelte primitives (button, card, dialog, select, …) + `utils.ts` (`cn()`); copy-in.
- `navigator-frontend-next/src/lib/ui/components/` — bits-ui wrappers (AppDialog, AppTabs, AppDropdown, SimpleTable, …); copy the ones the shell needs.
- `navigator-frontend-next/src/app.css` + `src/lib/styles/themes/{_schema,_tokens,light,dark,midnight,warm}.css` — Tailwind v4 token chain (the root `tailwind.config.ts` there is vestigial — do NOT port it).
- `navigator-frontend-next/src/lib/navauth/` — portable auth lib (LoginForm, providers/basic.ts, storage.ts, config.ts); adapt swapping `$env/dynamic/public` → `import.meta.env`.
- `navigator-frontend-next/src/lib/api/http.ts` — axios wrapper (`ApiError`, `registerInterceptors`, `createApiClient`) + `auth-headers.ts`.
- `navigator-frontend-next/src/lib/stores/theme.svelte.ts` — smallest clean rune-class store; template for `auth.svelte.ts`-style stores without SvelteKit.
- `navigator-frontend-next/.agent/skills/svelte5-structural/SKILL.md` (+ references/) — the class-based `$state` doctrine; copy into this repo's UI docs.
- `packages/ai-parrot-server/src/parrot/handlers/bots.py:424-751` — `ChatbotHandler` (`GET /api/v1/bots` → `{"agents": [...], "total": N}` with `source: database|registry`) — consumed as-is by the agents module.
- `packages/ai-parrot-server/src/parrot/manager/manager.py:1686` (`BotManager.setup`), `:918` (`get_bots`), `:2381` (`list_crews`) + `parrot/registry/registry.py:1310` (`list_agents`) — data for the status endpoint.
- `app.py:94-102` — package-relative static dir precedent (Telegram).
- `packages/ai-parrot-integrations/pyproject.toml:148-150` — package-data HTML/JS shipping precedent.
- `sdd/proposals/ui-agent-management.brainstorm.md` — agent list columns (name, description, role, enabled/source) and future tabbed-form UX conventions.

---

### Option B: Separate satellite distribution `ai-parrot-ui`

A new `packages/ai-parrot-ui/` holding the Vite source and shipping only
the dist as package-data (contributing e.g. `parrot.ui`); `ai-parrot-server`
detects it via `importlib` and mounts it when installed (optional extra
`ai-parrot-server[ui]`).

✅ **Pros:**
- Clean separation: server releases don't need Node unless the UI changed;
  UI can version/release independently.
- Matches the workspace's satellite-package architecture (FEAT-201 style).

❌ **Cons:**
- A tenth workspace package, new release/version choreography for something
  that is conceptually part of the server product.
- Discovery/optionality logic ("is the UI installed?") adds a failure mode
  the always-active decision explicitly avoids.
- Rejected in discovery: user chose source + dist inside `ai-parrot-server`.

📊 **Effort:** High (Option A + packaging/discovery overhead)

📦 **Libraries / Tools:** same as A plus setuptools namespace wiring.

🔗 **Existing Code to Reuse:** same as A; `packages/ai-parrot-embeddings/`
as the satellite blueprint.

---

### Option C: No-build server-rendered/vanilla HTML console

Extend the proven zero-build patterns: static hand-written HTML/JS pages in
the dev-loop-console style (`examples/dev_loop/static/index.html`, vanilla
JS, self-contained) or Python f-string templates
(`parrot_formdesigner/ui/templates.py`, `autonomous/admin.py`), served
directly by aiohttp.

✅ **Pros:**
- Zero Node anywhere: git installs get the full UI; no CI stage, no
  package-data subtleties.
- Two working precedents in-repo; the dev-loop console proves non-trivial
  UIs are feasible this way.

❌ **Cons:**
- Abandons the entire reuse thesis: no Bits UI, no shadcn tokens, no
  TS types, no component model — every future module hand-rolls DOM code.
- The dev-loop consoles are 80–90 KB single files precisely because of
  this; it does not scale to a module series.
- Contradicts the approved `admin_ui.proposal.md` decision.

📊 **Effort:** Low (foundation) / Very High (every subsequent module)

📦 **Libraries / Tools:** none (that's the point).

🔗 **Existing Code to Reuse:**
- `examples/dev_loop/server.py:1156-1689` — FileResponse + add_static + JSON API wiring.
- `packages/parrot-formdesigner/src/parrot_formdesigner/ui/` — f-string page shell + `is_authenticated(content_type="text/html")` decoration.

---

### Option D (unconventional): Custom-elements component library, pages assembled server-side

Compile each UI module as a Svelte custom element
(`<svelte:options customElement>`); the server serves tiny server-rendered
HTML shells that drop `<parrot-agents-list>`, `<parrot-dashboard>` etc. into
the page. No SPA router — navigation is plain server pages; the elements are
also embeddable in third-party apps (the evolution note in
`admin_ui.proposal.md`).

✅ **Pros:**
- Embeddability from day one — corporate or external apps can reuse the
  exact same elements.
- No client router to write; auth can use the existing
  `is_authenticated(content_type="text/html")` page pattern per route.

❌ **Cons:**
- Custom-element boundaries fight the copy-in reuse: shadcn/Bits components
  assume one app context (portals, focus traps, Tailwind cascade cross
  shadow-DOM is painful).
- Shared state (auth store, theme) across isolated elements needs a bespoke
  bridge; the rune-class store pattern doesn't cross shadow roots for free.
- Still needs the whole Node build pipeline — pays A's cost without A's SPA
  cohesion.

📊 **Effort:** High, with elevated unknowns

📦 **Libraries / Tools:** same as A minus router.

🔗 **Existing Code to Reuse:** same token/`navauth` set as A; custom-element
compilation is additive later — kept as a documented evolution path of A,
not the foundation.

---

## Recommendation

**Option A** — embedded SPA in `ai-parrot-server`, CI-built dist as
package-data, mounted by a library-owned `setup_admin_ui(app)`.

It is the only option satisfying all locked constraints (navigator-auth,
`/admin/` always-on, source+dist in the server package, CI-built dist, full
component reuse). Option B repackages A with extra choreography the user
already declined. Option C is cheaper today and bankrupt by module three —
this spec exists precisely because the f-string/vanilla approach stopped
scaling. Option D's embeddability is worth keeping as an evolution path
(compile selected components as custom elements later), but as a foundation
it multiplies unknowns.

What we trade off, knowingly: (1) git installs lack the UI without Node —
acceptable for an admin console targeting released versions; (2) the
release pipeline gains a Node stage — mitigated by a wheel-content check;
(3) SPA assets are publicly fetchable — by design, all data flows through
the authenticated JSON API.

---

## Feature Description

### User-Facing Behavior

- Browsing to `http://<server>/admin` (or being redirected there by
  formdesigner's expired-token script) loads the Admin UI.
- **Login**: unauthenticated visitors see a login page (theme-aware, ShadCN
  tokens). Submitting credentials calls `POST /api/v1/login` with
  `X-Auth-Method: BasicAuth` (methods discoverable via
  `GET /api/v1/auth/methods`); on success the token + user payload are
  stored (localStorage `ai_parrot_token`, matching formdesigner) and the
  session cookie is set by the server. On failure an inline error shows.
- **Shell**: after login, a persistent layout — sidebar navigation (Home,
  Dashboard, Agents; future modules append here), top bar with user
  identity, theme switcher (light/dark), logout (calls
  `GET /api/v1/logout`, clears storage, returns to login).
- **Home**: welcome page with server identity (name, version) and
  navigation cards.
- **Dashboard**: cards/tiles showing version, uptime, counts (registered
  agents by source, loaded bots, crews), and dependency health (DB, Redis)
  from `GET /api/v1/admin/status`; auto-refresh on an interval.
- **Agents (read-only module)**: table of agents from `GET /api/v1/bots` —
  name, description, role, source (database/registry), enabled — with
  client-side search/filter. Row click opens a read-only detail panel.
  Create/edit (the ui-agent-management tabbed wizard) is the NEXT spec.
- **Session expiry**: any 401 from the API clears the token and returns to
  the login page preserving the intended route.
- **Deep links**: `/admin/agents` etc. work on hard refresh (SPA fallback
  serves `index.html`; the client router resolves the path).

### Internal Behavior

- **Serving** (`parrot/server/ui/serving.py`): `setup_admin_ui(app)`
  resolves `Path(__file__).parent / 'dist'`; if missing → `logger.warning`
  and return (always-active-when-present semantics). Otherwise: static
  route for hashed assets, catch-all `/admin{tail:.*}` returning
  `index.html` (no-cache headers on index, immutable on hashed assets),
  and registration of `/admin*` in navigator-auth's exclude list so the
  HTML shell is reachable pre-login (auth enforcement lives in the JSON
  API; static resources are auto-excluded by navigator-auth anyway).
  Called from `BotManager.setup()`.
- **Status endpoint** (`parrot/server/ui/status.py` or
  `handlers/admin_status.py`): `@is_authenticated() @user_session()` view
  `GET /api/v1/admin/status` assembling `{version, uptime_seconds,
  agents: {database, registry, loaded}, crews, dependencies: {postgres,
  redis}}` from `app['bot_manager']` (`get_bots`, `registry.list_agents`,
  `list_crews`) and cheap health pings. Pydantic response model → feeds the
  TS codegen.
- **UI architecture**: Vite project at `packages/ai-parrot-server/ui/`;
  rune-class stores (`AuthStore`, `ThemeStore`) per the svelte5-structural
  skill; API layer = copied `http.ts` + generated types; router with an
  auth guard (redirect to `/admin/login` when no token). `base: '/admin/'`
  in Vite config; dev mode proxies `/api` to a running server (same pattern
  as navigator-frontend-next's `vite.config.ts`).
- **Type codegen**: a script exports `model_json_schema()` of the response
  models consumed by the UI (status, bots list) to JSON Schema files;
  `json-schema-to-typescript` compiles them to `ui/src/lib/types/generated/`
  during `pnpm generate` (pre-build step). Drift = `tsc` failure.
- **Build/packaging**: `pnpm build` outputs to
  `src/parrot/server/ui/dist/` (gitignored); `[tool.setuptools.package-data]`
  gains the dist globs; the release workflow builds the UI before
  `uv build` and asserts the wheel contains `parrot/server/ui/dist/index.html`.

### Edge Cases & Error Handling

- **Dist absent** (git install, dev without build): warning logged once; no
  `/admin` routes registered; API unaffected. Formdesigner's `/admin`
  redirect then 404s — acceptable, documented.
- **401 mid-session**: interceptor clears `ai_parrot_token`, routes to
  login with `?next=` (mirrors formdesigner's script and corporate
  `SessionExpiredModal` behavior).
- **navigator-auth not configured / DB down at login**: login page surfaces
  the JSON error from `/api/v1/login`; the shell never renders without a
  session.
- **Status endpoint degradation**: dependency checks are individually
  try/excepted — a dead Redis yields `redis: "unreachable"`, never a 500.
- **PBAC**: `/api/v1/bots` already batch-filters by `agent:list`
  (fail-open); the UI renders whatever the API returns — no client-side
  authorization logic.
- **Route collisions**: `/admin{tail:.*}` must be registered AFTER API
  routes and must never shadow `/api/*` (it is anchored at `/admin`);
  add a test asserting `/api/v1/admin/status` resolves to the JSON handler.
- **Caching**: `index.html` served no-cache so releases take effect;
  hashed assets long-cache.

---

## Capabilities

### New Capabilities

- `admin-ui-shell`: Svelte 5 + Vite SPA foundation — login, layout, router
  with auth guard, theme system, rune-class stores, copied component/token
  base.
- `admin-ui-serving`: `setup_admin_ui(app)` aiohttp mount — static assets,
  SPA index fallback under `/admin/`, auth-exclusion wiring, graceful
  absence.
- `admin-ui-status-endpoint`: authenticated `GET /api/v1/admin/status`
  (version, uptime, inventory counts, dependency health) with Pydantic
  response models.
- `admin-ui-dashboard`: home + dashboard pages rendering the status data.
- `admin-ui-agents-readonly`: read-only agents listing module over
  `GET /api/v1/bots` (validates the module pattern; absorbs the list-view
  design from ui-agent-management).
- `admin-ui-build-pipeline`: pnpm/Vite build, Pydantic→TS codegen script,
  package-data wiring, release-workflow Node stage + wheel-content check.

### Modified Capabilities

- `manager-setup` (BotManager.setup): calls `setup_admin_ui(app)`.
- Release workflow (`.github/workflows/*` / `Makefile` publish targets):
  gains the UI build stage. (Reminder: pushing workflow-file changes
  requires the SSH remote — gh OAuth token lacks `workflow` scope.)

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/manager/manager.py` | modifies | `setup()` calls `setup_admin_ui(app)` (pattern of `setup_credentials_routes` at `:2039`) |
| `packages/ai-parrot-server/src/parrot/server/` | extends | new `ui/` subpackage: `serving.py`, `status.py` (or handler module), `dist/` package-data. `parrot/server` is already a regular package (`__init__.py` exists, allowed by `test_wheel_layout.py`) |
| `packages/ai-parrot-server/pyproject.toml` | modifies | `[tool.setuptools.package-data]` gains `"parrot.server.ui" = ["dist/*", "dist/assets/*"]` (globs are non-recursive per key) |
| `packages/ai-parrot-server/ui/` | new | Vite/Svelte source tree (not shipped in wheel) |
| `packages/ai-parrot-server/tests/` | extends | serving tests (fallback, absence, no-shadowing), status endpoint tests, wheel-content assertion |
| navigator-auth exclude list | depends on | `AuthHandler.add_exclude_list` / `register_exclusions` (`navigator_auth/auth.py:728,750`) for `/admin*` HTML shell |
| `parrot-formdesigner` `/admin` redirect | fixed by | dangling target starts existing; shares `ai_parrot_token` storage key |
| Release CI / `Makefile` | modifies | Node build stage before `uv build`; SSH push for workflow files |
| `.gitignore` | modifies | ignore `src/parrot/server/ui/dist/`; consider cleaning stale root `agentui/`, `crew-builder/` (only `node_modules`/`.svelte-kit`, no source) and the `.gitignore:283` un-ignore of a nonexistent path |
| Future `agentstudio-management` (astudio API) | consumed later | agents module migrates `GET /api/v1/bots` → `GET /api/v1/astudio/agents` when it lands |

No breaking changes: all new routes are additive; `/api/v1/*` untouched
except the new status endpoint.

---

## Code Context

### User-Provided Code

None — user provided pointers to `sdd/proposals/admin_ui.proposal.md`,
`sdd/proposals/ui-agent-management.brainstorm.md`, and the reuse repo
`/home/jesuslara/proyectos/navigator-frontend-next`.

### Verified Codebase References

#### Classes & Signatures — ai-parrot (server side)

```python
# From packages/ai-parrot-server/src/parrot/manager/manager.py
class BotManager:  # :109
    def __init__(self, enable_database_bots: bool = ENABLE_DATABASE_BOTS,
                 enable_crews: bool = ENABLE_CREWS,
                 enable_registry_bots: bool = ENABLE_REGISTRY_BOTS,
                 enable_swagger_api: bool = ENABLE_SWAGGER) -> None: ...  # :118
    def setup(self, app: web.Application) -> web.Application: ...  # :1686
        # accepts web.Application or navigator Application (:1688-1690)
        # sets app['bot_manager'] = self (:1703); returns self.app (:2059)
    def get_bots(self) -> Dict[str, AbstractBot]: ...  # :918
    def list_crews(self): ...  # :2381
# module-level setup pattern to imitate:
# setup_credentials_routes(app) handlers/credentials.py:506, called manager.py:2039
# setup_mcp_helper_routes(app)  handlers/mcp_helper.py:420,  called manager.py:2041
# setup_thales_routes(app)      handlers/thales.py:248,      called manager.py:2043

# From packages/ai-parrot-server/src/parrot/handlers/bots.py
class ChatbotHandler(_PBACHandlerMixin, AbstractModel):  # :424
    model = BotModel
    pk: str = 'chatbot_id'  # :440
    async def get(self): ...       # :640  GET /api/v1/bots[/{id}]
    async def _get_all(self): ...  # :702  merges DB + registry.list_bots_by_priority(),
                                   #       PBAC filter_resources 'agent:list' (:725-748, fail-open)
    # response (:751-754): {"agents": [...], "total": len(agents)}
    # each dict carries data['source'] = 'database' (:622) | 'registry' (:637)
# registered at manager.py:1952: ChatbotHandler.configure(self.app, '/api/v1/bots')

# From packages/ai-parrot/src/parrot/registry/registry.py
class AgentRegistry:  # :252
    def list_agents(self) -> List[BotMetadata]: ...           # :1310
    def list_bots_by_priority(self) -> List[BotMetadata]: ... # :1334
# reached from handlers as self.request.app['bot_manager'].registry (manager.py:150)

# From app.py (repo root — NOT shipped; assembly reference only)
class Main(AppHandler):  # app.py:67 (navigator.handlers.types.AppHandler)
    enable_static: bool = True   # :72
    staticdir: str = STATIC_DIR  # :74
# auth wiring: AuthHandler() / auth.setup(self.app)  app.py:301-302
# package-relative static precedent (Telegram)  app.py:94-102:
#   telegram_static = Path(_tg_pkg_file).parent / 'static'
#   self.app.router.add_static('/telegram/', path=telegram_static,
#                              name='telegram_static', show_index=False,
#                              follow_symlinks=False)
```

#### Classes & Signatures — navigator-auth / navigator-session (installed: navigator_auth 0.22.11, navigator_session 0.10.1, navigator_api 3.2.2)

```python
# From .venv/.../navigator_auth/auth.py
class AuthHandler:
    def __init__(self, app_name: str = "auth", secure_cookies: bool = True, **kwargs) -> None: ...  # :80
    async def api_login(self, request: web.Request) -> web.Response: ...  # :398
        # POST /api/v1/login (route :602) — returns JSON userdata,
        # loads session onto the response (:428-433). JSON only, no HTML page.
    async def api_logout(self, request: web.Request) -> web.Response: ...  # :278  GET /api/v1/logout (:603)
    # GET/POST /api/v1/auth/methods (:626-638); GET /api/v1/user/session (:617)
    def setup(self, app: web.Application) -> web.Application: ...  # :565
    def add_exclude_list(self, path: str) -> None: ...       # :728 (fnmatch patterns, :840-842)
    def register_exclusions(self, paths: Iterable[str]) -> None: ...  # :750
    async def verify_exceptions(self, request) -> bool: ...  # :833
        # :848-855 — STATIC AUTO-EXCLUSION (load-bearing for the SPA):
        #   if isinstance(request.match_info.route.resource, StaticResource): return True
        #   if request.path.startswith("/static/"): return True
        # => add_static-served assets bypass auth middleware unconditionally;
        #    the index-fallback HANDLER is a normal route and still needs
        #    explicit exclusion via add_exclude_list('/admin*').

# From .venv/.../navigator_auth/decorators.py
def user_session() -> Callable[[F], F]: ...            # :92  (class-view form sets self.session/self.user :118-138)
def is_authenticated(content_type: str = "application/json") -> Callable[[F], F]: ...  # :144
def is_superuser(content_type=...): ...                # :263
def allowed_groups(groups: list, content_type=...): ...  # :360
# usage precedent: handlers/agent.py:102-104  @is_authenticated() @user_session() class AgentTalk(BaseView)

# From .venv/.../navigator_session/
async def get_session(request, userdata=None, new=False, ignore_cookie=True) -> Optional[SessionData]  # __init__.py:55-60
# AUTH_LOGIN_FAILED_URI fallback "/login" (navigator_auth/conf.py:149) — unregistered in this repo
```

#### Client-side auth contract already in the wild

```javascript
// From packages/parrot-formdesigner/src/parrot_formdesigner/ui/templates.py:151-157, 174-178
var token = localStorage.getItem('ai_parrot_token');
if (!token) { window.location.href = '/admin'; return; }   // ← route this spec creates
if (resp.status === 401) {
  localStorage.removeItem('ai_parrot_token');
  localStorage.removeItem('ai_parrot_session');
  window.location.href = '/admin';
}
// Login POST precedent: parrot/autonomous/admin.py:394-398 serves an inline page
// that POSTs /api/v1/login with header X-Auth-Method: BasicAuth and stores the JWT.
```

#### Packaging (verified)

```toml
# packages/ai-parrot-server/pyproject.toml
# build-backend = "setuptools.build_meta" (:1-4); version from parrot.server.version (:91-92)
[tool.setuptools.packages.find]        # :94-97
where = ["src"]; include = ["parrot*"]; namespaces = true
[tool.setuptools.package-data]         # :99-104 — extend here; globs NON-recursive per key
"parrot.handlers" = ["*.sql"]
"parrot.mcp.transports" = ["*.proto"]

# HTML/JS-in-wheel precedent — packages/ai-parrot-integrations/pyproject.toml:148-150
"parrot.integrations.telegram" = ["static/*.html"]
"parrot.voice" = ["ui/*.html", "ui/*.js"]
```

- `packages/ai-parrot-server/src/parrot/server/__init__.py` exists (regular
  package, exports `__version__`; NOT in `test_wheel_layout.py`'s
  `FORBIDDEN_INIT_PATHS` :16-25) — safe home for the `ui/` subpackage.
- Release publish: `Makefile:320` `uv publish dist/ai_parrot_server-*...`.

#### navigator-frontend-next inventory (verified paths, repo `/home/jesuslara/proyectos/navigator-frontend-next`, pkg `parrot-ui` 0.1.0, `pnpm@9.15.9`)

- Versions installed: svelte **5.55.7**, vite **5.4.21**, bits-ui **2.18.1**,
  tailwindcss **4.3.0**, typescript **5.9.3**, tailwind-variants 3.2.2,
  tailwind-merge 3.6.0, clsx 2.1.1, axios ^1.11.0. `shadcn-svelte` is NOT a
  dependency — components are vendored via `components.json`
  (`aliases.ui = "$lib/ui/internal/shadcn/ui"`). No router lib, no external
  state lib.
- `src/lib/ui/internal/shadcn/ui/` — 21 primitive families (accordion alert
  avatar badge button calendar card checkbox command dialog input label
  popover progress radio-group select separator sheet skeleton slider
  textarea); `internal/shadcn/utils.ts` = `cn()`.
- `src/lib/ui/components/` — public wrappers incl. `AppDialog`, `AppTabs`,
  `AppDropdown`, `SimpleTable`, `SchemaFormField`. `src/lib/ui/README.md`
  (12.4 KB) is the styling convention bible — copy it.
- Tokens: `src/app.css` (`@theme inline` map, lines 21-62) importing
  `src/lib/styles/themes/index.css` → `_schema.css`, `_tokens.css`,
  `light.css` (`--radius: 0.625rem` + Tier-1 vars), `dark.css`,
  `midnight.css`, `warm.css`; lint `scripts/check-theme-slots.mjs`
  (`pnpm check:themes`). Root `tailwind.config.ts` is vestigial (Tailwind v4
  CSS-first; no `@config` anywhere) — do not port.
- Auth: `src/lib/navauth/` (LoginForm.svelte, ProviderButtons.svelte,
  AuthGuard.svelte, providers/{base,basic,sso,google,microsoft,navigator,
  registry}.ts, store.svelte.ts, storage.ts, config.ts, types.ts); rune
  store `src/lib/stores/auth.svelte.ts`; login page
  `src/routes/login/+page.svelte` (~455 lines).
- API layer: `src/lib/api/http.ts` (ApiError, safeRaw, registerInterceptors,
  createApiClient; test http.test.ts), `auth-headers.ts`, `stream.ts`;
  config `src/lib/config.ts` (only SvelteKit coupling is
  `$env/dynamic/public` → swap for `import.meta.env`).
- Rune-class exemplars: `src/lib/stores/theme.svelte.ts` (`class ThemeStore`,
  96 lines), `grid-state.svelte.ts` (`class GridState`),
  `src/lib/dashboard/domain/widget.svelte.ts` (`class Widget`, ~25-class
  hierarchy). 37 files combine `class` + `$state`.
- Skill doc: `.agent/skills/svelte5-structural/SKILL.md` (268 lines) +
  `references/{patterns,state-matchines,widgets}.md`.
- Porting caveat: corporate stores import `$app/environment`,
  `$app/navigation`, `$env/dynamic/public` — need shims in the no-SvelteKit
  SPA.
- Dev proxy precedent: `vite.config.ts` proxies `/api`, `/ws`, `/static` to
  `PUBLIC_API_URL`, `envDir: ./env`.

#### TS codegen pattern (specified, unimplemented)

- Decision text: `sdd/proposals/dev-loop-session-state-hitl.brainstorm.md:497-509`
  — `model_json_schema()` → `json-schema-to-typescript`; discriminated
  unions (`oneOf` + `discriminator`) → TS tagged unions; drift gate =
  `tsc` exhaustiveness. Echoed in
  `sdd/specs/agent-host-protocol-session-state.spec.md` (~:503, :752).
- Runtime-only `model_json_schema()` precedents (reusable exporter shape):
  `handlers/flow_authoring.py:200-201`, `handlers/google_generation.py:52-56`.

### Does NOT Exist (Anti-Hallucination)

- ~~any `/admin` server route or handler~~ — only client-side JS redirect
  targets in formdesigner `templates.py:157,176`; nothing serves it.
- ~~a shipped SPA / any `.svelte` source in ai-parrot~~ — root `agentui/`
  and `crew-builder/` contain ONLY `node_modules/` + `.svelte-kit/` (no
  `src/`, no `package.json`); `.gitignore:283` un-ignores a nonexistent
  path.
- ~~`static/`, `dist/`, `ui/`, `templates/` under `parrot/server/`~~ — that
  package holds exactly `__init__.py` + `version.py`.
- ~~`add_static`/`web.static` anywhere in `packages/ai-parrot-server/src/`~~
  — zero hits; only navigator's `/static/` and app.py's `/telegram/`.
- ~~a TS codegen script (`json-schema-to-typescript`, `pydantic2ts`,
  `quicktype`) in either repo~~ — spec-only; `scripts/` has no TS
  generator. navigator-frontend-next has NO AHP codegen either (its
  `src/lib/types/` are hand-written; `component-catalog.svelte.ts` does a
  runtime schema transform, not build-time codegen).
- ~~a `/login` HTML page or `/` root route~~ — `/api/v1/login` is JSON-only;
  `AUTH_LOGIN_FAILED_URI` default `/login` is unregistered.
- ~~a shipped aiohttp app factory~~ — assembly lives in repo-root
  `app.py`/`run.py` only; library mounts must be `setup_*(app)` functions.
- ~~frontend build tooling in the Python build~~ — root `package.json` holds
  only `chrome-devtools-mcp`; Makefile has no npm/vite target.
- ~~a server-status endpoint~~ — nothing aggregates version/uptime/counts
  today; `GET /api/v1/admin/status` is new.
- ~~`GET /api/v1/astudio/agents`~~ — planned by agentstudio-management
  (brainstorm, exploration status), not implemented.
- ~~`ChatbotHandler` HTML mode / `BotHandler.get()`~~ — `/api/v1/chatbots`
  is PUT-only create; no `get()` defined.
- ~~`shadcn-svelte` as an npm dependency in navigator-frontend-next~~ —
  vendored components only; and its `tailwind.config.ts` theme map is
  vestigial (Tailwind v4 CSS-first).

---

## Parallelism Assessment

- **Internal parallelism**: moderate. Three lanes could proceed in
  parallel — (1) backend serving + status endpoint (Python), (2) UI
  scaffold + shell + modules (Node), (3) CI/packaging — but they share two
  contracts (dist path + generated types) and the UI lane dominates the
  critical path. Within one worktree, backend tasks can be implemented
  first, UI tasks sequentially after the scaffold task.
- **Cross-feature independence**: touches `manager.py:setup()` (a hot file
  for many features — keep the change to one added call), server
  `pyproject.toml`, and release workflow. No overlap with in-flight
  `dev-loop-run-fidelity` (FEAT-466). `agentstudio-management` is
  complementary (API side) — coordinate only on the eventual astudio
  migration of the agents module.
- **Recommended isolation**: `per-spec` — one worktree, tasks sequential in
  dependency order.
- **Rationale**: the dist-path/package-data/serving contract threads through
  nearly every task; splitting worktrees would force constant cross-merges
  for a feature whose UI tasks are inherently sequential (scaffold → shell
  → modules).

---

## Open Questions

- [ ] Status endpoint prefix: keep `GET /api/v1/admin/status` or reserve it
  under the future `astudio` namespace (`/api/v1/astudio/status`) to avoid
  a later rename? — *Owner: Jesus*
- [ ] Login methods surfaced in v1: BasicAuth only, or render whatever
  `GET /api/v1/auth/methods` reports (SSO buttons via copied
  `ProviderButtons.svelte`)? — *Owner: Jesus*
- [ ] SPA router choice: `svelte-spa-router` (hash or history), `tinro`, or
  a hand-rolled ~100-line history router per the svelte5-structural
  doctrine? — *Owner: spec/implementation*
- [ ] Clean up stale root `agentui/` and `crew-builder/` directories (and
  `.gitignore:283`) as part of this feature or separately? — *Owner: Jesus*
- [ ] Wheel-content check placement: extend
  `packages/ai-parrot-server/tests/test_wheel_layout.py`
  (`@pytest.mark.wheel_build`) or a release-workflow step? — *Owner: spec*
- [ ] Dashboard dependency health: which dependencies exactly (Postgres,
  Redis — anything else, e.g. vector store)? Probe strategy must be cheap
  and non-blocking. — *Owner: Jesus*
- [ ] Node version pin for CI (corporate uses pnpm 9; Node 20 LTS vs 22)?
  — *Owner: spec*
- [x] Do we reuse ui-agent-management.brainstorm.md? — *Owner: Jesus*: yes —
  its agent-list design is absorbed into `admin-ui-agents-readonly`; its
  tabbed-wizard form becomes the follow-up module spec (flowbite-svelte
  superseded by Bits UI + shadcn-svelte).
