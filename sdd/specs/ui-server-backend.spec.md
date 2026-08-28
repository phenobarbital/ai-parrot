---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Feature Specification: UI Server Backend — Embedded Admin UI Foundation

**Feature ID**: FEAT-468
**Date**: 2026-08-27
**Author**: Jesus Lara
**Status**: approved
**Target version**: ai-parrot-server 0.28.0

> Source brainstorm: `sdd/proposals/ui-server-backend.brainstorm.md`
> (Recommended Option A). Consolidates `sdd/proposals/admin_ui.proposal.md`
> (framework decision) and absorbs the list-view design of
> `sdd/proposals/ui-agent-management.brainstorm.md`. First of a series:
> subsequent specs add admin/feature modules on top of this foundation.

---

## 1. Motivation & Business Requirements

### Problem Statement

ai-parrot only ships backend. At corporate level (TROC) a full Svelte 5 UI
exists (`navigator-frontend-next`), but an external open-source adopter who
runs ai-parrot in `server`, `autonomous`, dev-loop, AgentCrew or AgentsFlow
mode has **no administration surface at all**: no login page, no way to see
what agents are registered, no server health view — everything requires raw
API calls.

Dangling references already assume an admin UI exists:
`parrot-formdesigner`'s injected auth script redirects browsers to `/admin`
on missing/expired token
(`packages/parrot-formdesigner/src/parrot_formdesigner/ui/templates.py:157,176`)
— a route nothing serves today — and `navigator_auth` defaults
`AUTH_LOGIN_FAILED_URI` to `/login`, also unregistered.

This spec builds the FOUNDATION: authentication/login, app shell
(layout + router + theming), home, a status dashboard, the
build/packaging/serving pipeline, Pydantic→TS type codegen, and one
read-only module (agents listing) that validates the module pattern.

### Goals

- `pip install ai-parrot-server` (wheel) is sufficient to get a working
  Admin UI at `/admin/` — Node is required only for UI development and CI.
- Authentication exclusively via **navigator-auth** (already a core
  dependency); any authenticated user may enter. No parallel auth system.
- The UI is a **Svelte 5 + Vite SPA (no SvelteKit)** with maximal copy-in
  reuse from `navigator-frontend-next` (shadcn primitives, Tailwind v4
  tokens, navauth, `http.ts`, svelte5-structural patterns).
- Serving is **library-owned** (`setup_admin_ui(app)` called from
  `BotManager.setup()`), always active when the compiled `dist/` is present
  in the installed package, gracefully absent otherwise.
- `dist/` is built by release CI and shipped as package-data — **never
  committed to git**.
- TypeScript types for every API payload the UI consumes are **generated
  from Pydantic JSON Schema** from day one.
- Dashboard v1 shows server status + inventory: version, uptime, counts of
  registered agents/crews, dependency health (Postgres, Redis, configured
  vector store) — only data the server already knows.
- The agents module is **read-only** (list + detail) over the existing
  `GET /api/v1/bots`, validating the module pattern for the feature series.

### Non-Goals (explicitly out of scope)

- Agent create/edit/delete UI — the tabbed-wizard form from
  `ui-agent-management.brainstorm.md` is the NEXT spec in the series.
- Crews, dev-loop console migration, and any other feature modules — later
  specs on this foundation.
- The `/api/v1/astudio/*` management API (`agentstudio-management`
  brainstorm) — complementary backend work; this UI consumes today's
  endpoints and migrates later.
- New telemetry/metrics pipelines (usage counts, token spend).
- Per-module fine-grained authorization in the UI (PBAC already filters
  API responses; client-side authz comes later).
- A separate `ai-parrot-ui` distribution (brainstorm Option B, rejected),
  a no-build vanilla HTML console (Option C, rejected), and a
  custom-elements-first architecture (Option D, kept only as a documented
  evolution path).
- Serving the UI at `/` root or behind an enable flag — decided: `/admin/`,
  always active when dist is present.

---

## 2. Architectural Design

### Overview

Two halves, one package:

**Python half** (`packages/ai-parrot-server/src/parrot/server/ui/`): a new
`ui` subpackage of the already-regular `parrot.server` package. It contains
`serving.py` — `setup_admin_ui(app)` following the established
`setup_*_routes(app)` pattern — plus `status.py` (the
`GET /api/v1/admin/status` view and its Pydantic response models) and the
shipped `dist/` directory (package-data, gitignored). `setup_admin_ui`
resolves `dist/` package-relative via `__file__` (same trick as the
Telegram static mount in `app.py:94-102`); if absent it logs a warning once
and registers nothing. Otherwise it mounts the hashed assets via
`router.add_static('/admin/assets/', ...)`, registers a catch-all
`GET /admin{tail:.*}` returning `index.html` (SPA history-router fallback;
no-cache on index, long-cache on hashed assets), and registers `/admin*` in
navigator-auth's exclude list so the HTML shell is reachable pre-login —
auth enforcement lives entirely in the JSON API. `BotManager.setup()` calls
it so every deployment gets the UI without touching `app.py`.

**UI half** (`packages/ai-parrot-server/ui/`, not shipped in the wheel): a
pnpm + Vite + Svelte 5 project (`base: '/admin/'`), TypeScript, Tailwind v4
CSS-first tokens copied from navigator-frontend-next, vendored shadcn
primitives + `cn()`, adapted `navauth` (BasicAuth form + provider buttons
rendered from `GET /api/v1/auth/methods` discovery), the copied axios
wrapper `http.ts`, and rune-class stores (`AuthStore`, `ThemeStore`,
`Router`) per the svelte5-structural doctrine. Routing is a **hand-rolled
~100-line history-mode router class** (zero dependencies, auth guard
redirects to the login route when no token). Login POSTs
`POST /api/v1/login` with `X-Auth-Method: BasicAuth`; the token + user
payload are stored in `localStorage` under **`ai_parrot_token`** /
`ai_parrot_session` — the exact keys `parrot-formdesigner` already expects —
and every API call carries `Authorization: Bearer`. Any 401 clears storage
and returns to login preserving the intended route.

**Type codegen**: `scripts/generate_ts_types.py` exports
`model_json_schema()` of the response models the UI consumes (status, bots
list) to JSON Schema files; `json-schema-to-typescript` compiles them to
`ui/src/lib/types/generated/` during `pnpm generate` (pre-build step).
Drift between Python models and UI code becomes a `tsc` failure.

**Build/release**: `pnpm build` outputs to
`src/parrot/server/ui/dist/`; `[tool.setuptools.package-data]` gains the
dist globs; the release pipeline builds the UI before `uv build` and a
wheel-content check (both a `@pytest.mark.wheel_build` test and a release
workflow assert) blocks publishing a UI-less wheel.

### Component Diagram

```
                       browser
                          │
            GET /admin/*  │  /api/v1/* (Bearer + session cookie)
                          ▼
 ┌────────────────────── aiohttp Application ──────────────────────┐
 │                                                                 │
 │  setup_admin_ui(app)  ◄── called by BotManager.setup()          │
 │   ├─ add_static('/admin/assets/', <pkg>/ui/dist/assets)         │
 │   ├─ GET /admin{tail:.*} → FileResponse(dist/index.html)        │
 │   └─ AuthHandler exclude list ← '/admin*'                       │
 │                                                                 │
 │  GET /api/v1/admin/status ── AdminStatusHandler (new)           │
 │   └─ app['bot_manager'] → get_bots()/registry/list_crews()      │
 │        + health probes: Postgres · Redis · vector store         │
 │  GET /api/v1/bots ────────── ChatbotHandler (existing)          │
 │  POST /api/v1/login etc. ─── navigator-auth (existing)          │
 └─────────────────────────────────────────────────────────────────┘

 build time (CI / UI dev only):
 scripts/generate_ts_types.py → *.schema.json → json-schema-to-typescript
   → ui/src/lib/types/generated/*.ts → pnpm build → src/parrot/server/ui/dist/
   → uv build (package-data) → wheel-content check
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `BotManager.setup()` (`manager.py:1686`) | modified | adds one call to `setup_admin_ui(self.app)` alongside `setup_credentials_routes` etc. (`:2039-2043`) |
| `parrot.server` package | extended | new `ui/` subpackage (`serving.py`, `status.py`, `dist/`); `parrot/server/__init__.py` already exists and is allowed by `test_wheel_layout.py` |
| navigator-auth `AuthHandler` | depends on | login/logout/methods endpoints consumed by the SPA; `add_exclude_list('/admin*')` for the HTML shell; static assets auto-excluded (see Contract) |
| `ChatbotHandler` `GET /api/v1/bots` (`bots.py:424`) | consumed | agents read-only module; response `{"agents": [...], "total": N}` with `source` field, PBAC-filtered server-side |
| `packages/ai-parrot-server/pyproject.toml` | modified | `[tool.setuptools.package-data]` gains `"parrot.server.ui" = ["dist/*", "dist/assets/*"]` (globs non-recursive per key) |
| `packages/ai-parrot-server/tests/test_wheel_layout.py` | extended | wheel-content assertion: built wheel contains `parrot/server/ui/dist/index.html` |
| Release CI / Makefile publish | modified | Node 24 LTS + pnpm 9 stage before `uv build` + wheel assert. Workflow-file pushes require the SSH remote (gh token lacks `workflow` scope) |
| `parrot-formdesigner` `/admin` redirect | fixed by | its dangling redirect target starts existing; shares `ai_parrot_token` storage key |
| `.gitignore` | modified | ignore `packages/ai-parrot-server/src/parrot/server/ui/dist/` |
| Future `agentstudio-management` | coordinated | agents module migrates `GET /api/v1/bots` → `GET /api/v1/astudio/agents` when that feature lands |

### Data Models

```python
# parrot/server/ui/status.py (new) — response models, also the TS-codegen source
class DependencyHealth(BaseModel):
    status: Literal["ok", "unreachable", "unconfigured"]
    detail: str | None = None
    latency_ms: float | None = None

class AgentCounts(BaseModel):
    database: int
    registry: int
    loaded: int

class AdminStatus(BaseModel):
    name: str                      # server/app name
    version: str                   # parrot.server.version.__version__
    uptime_seconds: float
    agents: AgentCounts
    crews: int
    dependencies: dict[str, DependencyHealth]   # postgres, redis, vector_store
```

```typescript
// ui/src/lib/types/generated/  (GENERATED — never hand-edited)
// AdminStatus, AgentCounts, DependencyHealth, BotsListResponse …
// produced by scripts/generate_ts_types.py + json-schema-to-typescript
```

### New Public Interfaces

```python
# parrot/server/ui/serving.py (new)
def setup_admin_ui(app: web.Application, *, prefix: str = "/admin") -> bool:
    """Mount the embedded Admin UI if the compiled dist/ is present.

    Returns True when routes were registered, False when dist/ is absent
    (a single WARNING is logged and the app is otherwise untouched).
    """

# parrot/server/ui/status.py (new)
class AdminStatusHandler(BaseView):        # @is_authenticated() @user_session()
    async def get(self) -> web.Response:   # GET /api/v1/admin/status → AdminStatus
        ...
```

```typescript
// ui/src/lib/router.svelte.ts (new, hand-rolled — svelte5-structural)
export class Router {
  path = $state(...)          // current path under /admin
  navigate(to: string): void
  guard(): void               // redirects to login when AuthStore has no token
}
// ui/src/lib/stores/auth.svelte.ts — class AuthStore ($state token/user,
//   login(), logout(), handle401())
```

---

## 3. Module Breakdown

### Module 1: admin-ui-serving
- **Path**: `packages/ai-parrot-server/src/parrot/server/ui/serving.py` (+ `ui/__init__.py`), `manager.py` (one call), `pyproject.toml` package-data, `.gitignore`
- **Responsibility**: `setup_admin_ui(app)` — dist resolution, static mount, SPA index fallback with cache headers, navigator-auth exclusions, graceful absence, no `/api/*` shadowing.
- **Depends on**: none (a hand-placed placeholder dist can drive tests before Module 3 exists).

### Module 2: admin-ui-status-endpoint
- **Path**: `packages/ai-parrot-server/src/parrot/server/ui/status.py`
- **Responsibility**: `AdminStatusHandler` (`GET /api/v1/admin/status`, `@is_authenticated() @user_session()`), Pydantic models above, uptime tracking, individually-timeboxed try/excepted health probes for Postgres, Redis and the configured vector store; registered from `setup_admin_ui` (API part registers even when dist is absent — the endpoint is UI-agnostic).
- **Depends on**: none.

### Module 3: admin-ui-build-pipeline (UI scaffold + codegen)
- **Path**: `packages/ai-parrot-server/ui/` (package.json, vite.config.ts, tsconfig, Tailwind v4 token CSS copied from navigator-frontend-next, vendored shadcn primitives + `cn()`), `scripts/generate_ts_types.py`
- **Responsibility**: buildable Vite + Svelte 5 + TS project (`base: '/admin/'`, dev proxy `/api` → running server, pnpm 9 / Node 24 LTS), `pnpm generate` codegen step (Pydantic JSON Schema → TS via `json-schema-to-typescript`), `pnpm build` → `src/parrot/server/ui/dist/`.
- **Depends on**: Module 2 (models to generate types from).

### Module 4: admin-ui-shell (login + layout + router)
- **Path**: `packages/ai-parrot-server/ui/src/` (router.svelte.ts, stores/auth.svelte.ts, stores/theme.svelte.ts, lib/api/ adapted http.ts + auth-headers, pages/Login.svelte, App shell: sidebar, topbar, theme switcher, logout)
- **Responsibility**: hand-rolled history router with auth guard; login page (BasicAuth form + provider buttons from `GET /api/v1/auth/methods` discovery, adapted `navauth`/`ProviderButtons.svelte`); token storage under `ai_parrot_token`/`ai_parrot_session`; 401 interceptor → login with `?next=`; persistent layout with navigation registry (future modules append entries).
- **Depends on**: Module 3.

### Module 5: admin-ui-dashboard (home + dashboard)
- **Path**: `packages/ai-parrot-server/ui/src/pages/` (Home.svelte, Dashboard.svelte + tiles/cards components)
- **Responsibility**: home/welcome with server identity + navigation cards; dashboard rendering `AdminStatus` (version, uptime, agent/crew counts, dependency health) with interval auto-refresh and per-dependency degraded states.
- **Depends on**: Modules 2, 4.

### Module 6: admin-ui-agents-readonly
- **Path**: `packages/ai-parrot-server/ui/src/pages/agents/` (AgentsList.svelte, AgentDetail panel)
- **Responsibility**: read-only table over `GET /api/v1/bots` — columns name, description, role, source (database/registry), enabled — client-side search/filter, row click → read-only detail panel. Layout per the absorbed ui-agent-management list-view design.
- **Depends on**: Module 4.

### Module 7: release-integration + wheel checks + docs
- **Path**: `packages/ai-parrot-server/tests/test_wheel_layout.py` (extend), release workflow / `Makefile`, `docs/admin-ui.md`
- **Responsibility**: CI stage (Node 24 LTS, pnpm 9: `pnpm install && pnpm generate && pnpm build`) before `uv build`; wheel-content assertions in BOTH the `@pytest.mark.wheel_build` test and a release-workflow step; developer + adopter documentation (UI dev workflow, git-install caveat, auth model).
- **Depends on**: Modules 1, 3.

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_setup_admin_ui_absent_dist` | 1 | no dist → returns False, zero `/admin` routes registered, one WARNING logged |
| `test_setup_admin_ui_mounts_spa` | 1 | with dist fixture → `/admin`, `/admin/agents` (deep link) return `index.html`; `/admin/assets/*` served |
| `test_admin_index_cache_headers` | 1 | index no-cache; hashed assets immutable/long-cache |
| `test_admin_does_not_shadow_api` | 1 | `/api/v1/admin/status` resolves to the JSON handler, never the SPA fallback |
| `test_admin_exclusions_registered` | 1 | `/admin*` present in the auth exclude list when AuthHandler is installed; no crash when it is not |
| `test_status_requires_auth` | 2 | unauthenticated GET → 401 |
| `test_status_shape` | 2 | authenticated GET → `AdminStatus` schema (version, uptime, counts, dependencies) |
| `test_status_degraded_dependency` | 2 | dead Redis/vector store → `status: "unreachable"`, endpoint still 200 |
| `test_generate_ts_types_emits_schemas` | 3 | codegen script writes JSON Schema for AdminStatus + bots list models |
| `Router` vitest suite | 4 | navigate/guard/back-forward; unauthenticated → login with `?next=` |
| `AuthStore` vitest suite | 4 | login stores `ai_parrot_token`; 401 handler clears storage |
| `AgentsList` vitest suite | 6 | renders rows from mocked `{"agents": [...]}`; filter works; `source` badge |

### Integration Tests

| Test | Description |
|---|---|
| `test_admin_ui_end_to_end_serving` | aiohttp test app with BotManager.setup + dist fixture: login flow against mocked auth, fetch `/api/v1/admin/status`, deep-link refresh |
| `test_wheel_contains_admin_dist` | (`@pytest.mark.wheel_build`) built wheel contains `parrot/server/ui/dist/index.html` and at least one hashed asset |
| `test_generated_types_in_sync` | regenerate schemas from models and diff against committed generated TS inputs — drift fails |

### Test Data / Fixtures

```python
@pytest.fixture
def dist_fixture(tmp_path) -> Path:
    """Minimal fake dist/: index.html + assets/app-<hash>.js, monkeypatched
    into serving.py's dist resolution."""

@pytest.fixture
def app_with_admin_ui(dist_fixture) -> web.Application:
    """aiohttp app with a stub bot_manager (known agent/crew counts) and
    setup_admin_ui applied."""
```

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] `pip install` of the release wheel + starting the server serves the
  Admin UI login page at `/admin` with **no Node installed** on the host.
- [ ] Install-from-git without running the UI build: server starts normally,
  logs one WARNING, registers no `/admin` routes; API unaffected.
- [ ] Authentication is exclusively navigator-auth: login via
  `POST /api/v1/login` (BasicAuth form + provider buttons discovered from
  `GET /api/v1/auth/methods`); any authenticated user enters; logout works.
- [ ] Token stored under `ai_parrot_token` — the formdesigner `/admin`
  redirect round-trips (expired token → login → back).
- [ ] Deep links (`/admin/agents` etc.) survive hard refresh via SPA
  fallback; `/api/*` is never shadowed by the fallback.
- [ ] `GET /api/v1/admin/status` requires auth and returns version, uptime,
  agent counts (database/registry/loaded), crews, and per-dependency health
  for Postgres, Redis and the configured vector store; a dead dependency
  degrades its entry, never the endpoint.
- [ ] Dashboard renders all status data with auto-refresh; Home shows server
  identity + navigation.
- [ ] Agents module lists merged database+registry agents from
  `GET /api/v1/bots` (read-only: no create/edit/delete affordances).
- [ ] TS types consumed by the UI are generated from Pydantic JSON Schema
  (`pnpm generate`); hand-edits to generated files are not needed anywhere.
- [ ] `dist/` is gitignored; the release pipeline builds it (Node 24 LTS,
  pnpm 9) and BOTH the wheel-build test and a release-workflow step assert
  the wheel contains `parrot/server/ui/dist/index.html`.
- [ ] UI reuses navigator-frontend-next assets via copy-in: Tailwind v4
  token chain, ≥ the shadcn primitives needed by the shell, adapted navauth
  and `http.ts`; router is hand-rolled (no router dependency).
- [ ] All Python tests pass (`pytest packages/ai-parrot-server/tests/ -v`)
  and UI tests pass (`pnpm test`); no breaking changes to existing routes.
- [ ] `docs/admin-ui.md` documents the dev workflow (pnpm dev + API proxy),
  the git-install caveat, and the auth model.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> Verified 2026-08-27 against `dev` (spot re-checked at spec time).
> Implementation agents MUST NOT reference imports, attributes, or methods
> not listed here without first verifying via `grep`/`read`.

### Verified Imports

```python
from navigator_auth import AuthHandler            # .venv/.../navigator_auth/__init__ (installed 0.22.11)
from navigator_auth.decorators import is_authenticated, user_session  # decorators.py:144, :92
from navigator_session import get_session          # navigator_session/__init__.py:55
from navigator.views import BaseView               # pattern used across parrot/handlers/*
from parrot.registry import agent_registry         # packages/ai-parrot/src/parrot/registry/__init__.py:7
```

### Existing Class Signatures

```python
# packages/ai-parrot-server/src/parrot/manager/manager.py
class BotManager:  # :109
    def setup(self, app: web.Application) -> web.Application: ...  # :1686 (re-verified)
        # accepts web.Application or navigator Application (:1688-1690)
        # sets app['bot_manager'] = self (:1703); returns self.app (:2059)
        # module-level setup_* calls at :2039 (credentials), :2041 (mcp_helper), :2043 (thales)
        #   — setup_admin_ui(app) is added HERE, same pattern
    def get_bots(self) -> Dict[str, AbstractBot]: ...  # :918
    def list_crews(self): ...                          # :2381

# packages/ai-parrot-server/src/parrot/handlers/bots.py
class ChatbotHandler(_PBACHandlerMixin, AbstractModel):  # :424 (re-verified)
    pk: str = 'chatbot_id'          # :440
    async def get(self): ...        # :640  GET /api/v1/bots[/{id}]
    async def _get_all(self): ...   # :702  merges DB + registry.list_bots_by_priority();
                                    #       PBAC filter 'agent:list' (:725-748, fail-open)
    # response (:751-754): {"agents": [...], "total": len(agents)}
    # each agent dict: data['source'] = 'database' (:622) | 'registry' (:637)
# registered at manager.py:1952: ChatbotHandler.configure(self.app, '/api/v1/bots')

# packages/ai-parrot/src/parrot/registry/registry.py
class AgentRegistry:  # :252
    def list_agents(self) -> List[BotMetadata]: ...            # :1310
    def list_bots_by_priority(self) -> List[BotMetadata]: ...  # :1334
# reached from handlers as self.request.app['bot_manager'].registry (manager.py:150)

# .venv/.../navigator_auth/auth.py  (navigator_auth 0.22.11)
class AuthHandler:
    def __init__(self, app_name: str = "auth", secure_cookies: bool = True, **kwargs) -> None: ...  # :80
    async def api_login(self, request) -> web.Response: ...   # :398 — POST /api/v1/login (route :602),
        # JSON userdata + session loaded onto response (:428-433). JSON only — no HTML login page.
    async def api_logout(self, request) -> web.Response: ...  # :278 — GET /api/v1/logout (:603)
    # GET/POST /api/v1/auth/methods (:626-638); GET /api/v1/user/session (:617)
    def setup(self, app: web.Application) -> web.Application: ...  # :565
    def add_exclude_list(self, path: str) -> None: ...        # :728 — fnmatch patterns (:840-842)
    def register_exclusions(self, paths) -> None: ...         # :750
    async def verify_exceptions(self, request) -> bool: ...   # :833
        # :848-855 — STATIC AUTO-EXCLUSION (load-bearing):
        #   StaticResource routes and any path under /static/ bypass auth middleware.
        #   The SPA index-fallback HANDLER is a normal route → still needs
        #   explicit add_exclude_list('/admin*').

# .venv/.../navigator_auth/decorators.py
def user_session(): ...                                        # :92 (class-view form sets self.session/self.user :118-138)
def is_authenticated(content_type: str = "application/json"): ...  # :144
# usage precedent: handlers/agent.py:102-104  @is_authenticated() @user_session() class AgentTalk(BaseView)
```

### Client-side auth contract already in the wild

```javascript
// packages/parrot-formdesigner/src/parrot_formdesigner/ui/templates.py:151-157, 174-178
var token = localStorage.getItem('ai_parrot_token');
if (!token) { window.location.href = '/admin'; return; }   // ← route FEAT-468 creates
if (resp.status === 401) {
  localStorage.removeItem('ai_parrot_token');
  localStorage.removeItem('ai_parrot_session');
  window.location.href = '/admin';
}
// Login POST precedent: parrot/autonomous/admin.py:394-398 — inline page POSTs
// /api/v1/login with header X-Auth-Method: BasicAuth and stores the JWT.
```

### Packaging contract

```toml
# packages/ai-parrot-server/pyproject.toml (re-verified: package-data at :104)
# build-backend = "setuptools.build_meta"; version from parrot.server.version (0.27.0)
[tool.setuptools.packages.find]
where = ["src"]; include = ["parrot*"]; namespaces = true
[tool.setuptools.package-data]      # extend here; globs NON-recursive per key
"parrot.handlers" = ["*.sql"]
"parrot.mcp.transports" = ["*.proto"]

# HTML/JS-in-wheel precedent — packages/ai-parrot-integrations/pyproject.toml:148-150
"parrot.integrations.telegram" = ["static/*.html"]
"parrot.voice" = ["ui/*.html", "ui/*.js"]
```

- `packages/ai-parrot-server/src/parrot/server/__init__.py` exists (regular
  package, exports `__version__`; NOT in `test_wheel_layout.py`
  `FORBIDDEN_INIT_PATHS` :16-25) — the `ui/` subpackage lives under it.
- Package-relative static precedent: `app.py:94-102` —
  `Path(_tg_pkg_file).parent / 'static'` + `router.add_static('/telegram/', ...)`.
- Release publish: `Makefile:320` `uv publish dist/ai_parrot_server-*...`.

### navigator-frontend-next reuse inventory (repo `/home/jesuslara/proyectos/navigator-frontend-next`, pkg `parrot-ui` 0.1.0, `pnpm@9.15.9`)

- Versions installed: svelte **5.55.7**, vite **5.4.21**, bits-ui **2.18.1**,
  tailwindcss **4.3.0** (v4 CSS-first), typescript **5.9.3**,
  tailwind-variants 3.2.2, tailwind-merge 3.6.0, clsx 2.1.1, axios ^1.11.0.
  `shadcn-svelte` is NOT an npm dependency — components are vendored
  (`components.json`, `aliases.ui = "$lib/ui/internal/shadcn/ui"`).
- Copy-in sources:
  - `src/lib/ui/internal/shadcn/ui/` — 21 primitive families; `internal/shadcn/utils.ts` = `cn()`.
  - `src/lib/ui/components/` — wrappers (`AppDialog`, `AppTabs`, `AppDropdown`, `SimpleTable`, …); `src/lib/ui/README.md` = styling conventions.
  - Tokens: `src/app.css` (`@theme inline`, lines 21-62) + `src/lib/styles/themes/{_schema,_tokens,light,dark,midnight,warm}.css`; lint `scripts/check-theme-slots.mjs`. Root `tailwind.config.ts` is VESTIGIAL — do not port.
  - Auth: `src/lib/navauth/` (LoginForm, ProviderButtons, AuthGuard, providers/{basic,sso,google,microsoft,navigator}.ts, storage.ts, config.ts); rune store `src/lib/stores/auth.svelte.ts`.
  - API: `src/lib/api/http.ts` (ApiError, registerInterceptors, createApiClient; test http.test.ts), `auth-headers.ts`; `src/lib/config.ts`.
  - Rune-class exemplars: `src/lib/stores/theme.svelte.ts` (96 lines), `grid-state.svelte.ts`, `dashboard/domain/widget.svelte.ts`.
  - Skill doc: `.agent/skills/svelte5-structural/SKILL.md` + `references/`.
- Porting caveat: corporate code imports `$app/environment`,
  `$app/navigation`, `$env/dynamic/public` (SvelteKit) — swap for
  `import.meta.env` / shims in the SPA.
- Dev-proxy precedent: `vite.config.ts` proxies `/api`, `/ws`, `/static`.

### TS codegen pattern (specified, previously unimplemented)

- Decision text: `sdd/proposals/dev-loop-session-state-hitl.brainstorm.md:497-509`
  — `model_json_schema()` → `json-schema-to-typescript`; discriminated
  unions → TS tagged unions; drift gate = `tsc`.
- Runtime `model_json_schema()` exporter shapes:
  `handlers/flow_authoring.py:200-201`, `handlers/google_generation.py:52-56`.

### Does NOT Exist (Anti-Hallucination)

- ~~any `/admin` server route or handler~~ — only client-side JS redirect
  targets in formdesigner `templates.py:157,176`.
- ~~`static/`, `dist/`, `ui/`, `templates/` under `parrot/server/`~~ — that
  package holds exactly `__init__.py` + `version.py` today.
- ~~`add_static`/`web.static` anywhere in `packages/ai-parrot-server/src/`~~
  — zero hits; only navigator's `/static/` and app.py's `/telegram/`.
- ~~a server-status endpoint~~ — `GET /api/v1/admin/status` is NEW; nothing
  aggregates version/uptime/counts today.
- ~~a TS codegen script (`json-schema-to-typescript`, `pydantic2ts`,
  `quicktype`) in either repo~~ — spec-only until this feature.
- ~~a `/login` HTML page or `/` root route~~ — `/api/v1/login` is JSON-only;
  `AUTH_LOGIN_FAILED_URI` default `/login` is unregistered.
- ~~a shipped aiohttp app factory~~ — assembly lives in repo-root
  `app.py`/`run.py`; library mounts MUST be `setup_*(app)` functions.
- ~~frontend build tooling in the Python build~~ — root `package.json` holds
  only `chrome-devtools-mcp`; Makefile has no npm/vite target.
- ~~`GET /api/v1/astudio/agents`~~ — planned by agentstudio-management
  (exploration), not implemented.
- ~~`BotHandler.get()`~~ — `/api/v1/chatbots` is PUT-only create; use
  `/api/v1/bots` (ChatbotHandler) for listing.
- ~~`shadcn-svelte` npm package in navigator-frontend-next~~ — vendored
  components only; its `tailwind.config.ts` theme map is vestigial.
- ~~root `agentui/` / `crew-builder/` source trees~~ — contain only
  `node_modules/`/`.svelte-kit/`; nothing tracked (dead un-ignore removed
  in commit `bbc4953`).

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- `setup_admin_ui(app)` mirrors `setup_credentials_routes` /
  `setup_mcp_helper_routes` / `setup_thales_routes`
  (`handlers/credentials.py:506`, `mcp_helper.py:420`, `thales.py:248`) —
  module-level function, registered from `BotManager.setup()`.
- Handlers: `@is_authenticated() @user_session()` on a `BaseView` subclass
  (precedent `handlers/agent.py:102-104`); Pydantic models for all payloads;
  `self.logger`, never print; async throughout — health probes must be
  individually timeboxed (`asyncio.wait_for`) and try/excepted.
- Package-relative dist resolution via `Path(__file__).parent / "dist"`
  (Telegram precedent `app.py:94-102`); `show_index=False`,
  `follow_symlinks=False` on the static mount.
- UI: svelte5-structural doctrine — rune classes for state machines/stores;
  semantic tokens inside vendored primitives, scale tokens in wrappers/pages
  (per `src/lib/ui/README.md` conventions); generated types are read-only.
- Route registration order: the `/admin{tail:.*}` catch-all registers after
  API routes; add the explicit no-shadowing test.
- Commit convention `sdd: <action> for ui-server-backend`; UI build outputs
  never committed.

### Known Risks / Gotchas

- **Wheel built without the Node stage silently ships no UI** → dual
  wheel-content check (test + release-workflow assert) is mandatory, not
  optional.
- **setuptools package-data globs are non-recursive per key** → Vite output
  must keep a flat, known layout (`dist/*` + `dist/assets/*`); if Vite emits
  deeper paths, enumerate each subdirectory or flatten via build config.
- **navigator-auth exclusions**: static assets bypass auth automatically,
  but the index-fallback handler does NOT — forgetting
  `add_exclude_list('/admin*')` yields a JSON 401 instead of the login page.
  Also handle deployments where `AuthHandler` was never installed (no
  exclude-list key): degrade gracefully.
- **`AbstractModel.configure` registers a catch-all `{meta:(:.*)?}` route**
  for `/api/v1/bots` — irrelevant to `/admin` but explains surprising
  matches while testing.
- **Dist absent on git installs is expected behavior** — document it;
  formdesigner's `/admin` redirect will 404 in that case (accepted).
- **Health probes can hang** on a dead VPN/DB — short timeouts, per-probe
  isolation; a probe failure must never 500 the endpoint (dev DB timeouts
  are a known environment reality).
- **Session vs token duality**: navigator-auth sets a session cookie AND
  returns a token; the SPA uses Bearer tokens (formdesigner-compatible).
  Do not depend on the cookie for API calls from the SPA.
- **Workflow-file pushes**: branches touching `.github/workflows/*` must be
  pushed via the SSH remote (gh OAuth token lacks `workflow` scope).
- **Svelte 5 + Vite major versions**: corporate pins vite 5.4; evaluate the
  current Vite major at scaffold time — do not blind-copy the corporate
  lockfile.

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| `svelte` | `^5` | UI framework (5.55.7 proven in corporate) |
| `vite` | `^5` (evaluate current major) | build + dev server |
| `typescript` | `^5.6` | UI type checking / codegen drift gate |
| `bits-ui` | `^2.18` | headless primitives (Svelte-only) |
| `tailwindcss` | `^4` | CSS-first tokens |
| `tailwind-variants`, `tailwind-merge`, `clsx` | latest | `cn()` composition |
| `@lucide/svelte` | latest | icons |
| `axios` | `^1.11` | copied `http.ts` API layer |
| `json-schema-to-typescript` | latest | Pydantic schema → TS types (devDep) |
| `vitest` + `@testing-library/svelte` + `jsdom` | latest | UI tests |
| `pnpm` | 9 | package manager (matches corporate) |
| Node | **24 LTS** | CI + dev toolchain pin |
| *(Python)* | — | **no new Python dependencies** — navigator-auth/session already core deps |

---

## 8. Open Questions

> All blocking questions were resolved in the brainstorm
> (`sdd/proposals/ui-server-backend.brainstorm.md`); resolutions are echoed
> here for the audit trail.

- [x] Status endpoint prefix — *Resolved in brainstorm*: `/api/v1/admin/status`
  (Admin-UI-owned namespace, decoupled from astudio which is still exploration).
- [x] Login methods in v1 — *Resolved in brainstorm*: BasicAuth form always +
  SSO/provider buttons rendered from `GET /api/v1/auth/methods` discovery
  (copy `ProviderButtons.svelte` from navauth).
- [x] SPA router — *Resolved in brainstorm*: hand-rolled ~100-line
  history-mode router as a rune-class store; zero dependencies.
- [x] Stale root dirs cleanup — *Resolved in brainstorm*: separate commit on
  `dev` (done: `bbc4953` removed the dead un-ignore; physical
  `node_modules` removal is a manual local step, out of scope here).
- [x] Wheel-content check placement — *Resolved in brainstorm*: BOTH —
  extend `test_wheel_layout.py` (`@pytest.mark.wheel_build`) AND a
  release-workflow assert after the Node build.
- [x] Dashboard dependency health scope — *Resolved in brainstorm*:
  Postgres + Redis + configured vector store; individually try/excepted,
  short timeouts.
- [x] Node pin — *Resolved in brainstorm*: Node 24 LTS with pnpm 9.
- [x] Reuse of ui-agent-management — *Resolved in brainstorm*: list-view
  design absorbed into Module 6; tabbed-wizard CRUD form deferred to the
  next spec (Bits UI supersedes flowbite-svelte).
- [ ] Vector-store health probe mechanics (which client/API per configured
  backend — pgvector/milvus/arango) — decide during Module 2
  implementation; must respect the timebox/fail-soft contract. — *Owner:
  implementation*

---

## Worktree Strategy

- **Default isolation unit**: `per-spec` — all tasks sequential in one
  worktree (`.claude/worktrees/feat-468-ui-server-backend`, branched from
  `dev`).
- **Rationale**: the dist-path/package-data/serving contract threads through
  nearly every task, and UI tasks are inherently sequential
  (scaffold → shell → pages). Splitting worktrees would force constant
  cross-merges.
- **Cross-feature dependencies**: none blocking. `manager.py:setup()` is a
  hot file for many features — keep the change to a single added call.
  `agentstudio-management` (astudio API) is complementary; coordinate only
  on the future migration of Module 6's data source. No overlap with
  in-flight FEAT-466 (dev-loop-run-fidelity).

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-08-27 | Jesus Lara | Initial draft from ui-server-backend brainstorm (Option A) |
