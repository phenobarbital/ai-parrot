# Admin UI (FEAT-468)

**Feature**: FEAT-468 — UI Server Backend — Embedded Admin UI Foundation
**Status**: shipped
**Affects**: anyone running `ai-parrot-server`, and anyone developing the
Admin UI itself.

## What it is

`ai-parrot-server` embeds a small single-page Admin UI, served at `/admin`
by the same aiohttp application that serves the API. It gives operators a
login page, a status dashboard, and a read-only agent inventory without
standing up a separate frontend deployment.

- **Home** (`/admin/home`) — server identity + navigation.
- **Dashboard** (`/admin/dashboard`) — `GET /api/v1/admin/status`: version,
  uptime, agent counts (database/registry/loaded), crews, and per-dependency
  health (Postgres, Redis, the configured vector store), auto-refreshed.
- **Agents** (`/admin/agents`) — table over `GET /api/v1/bots` (merged
  database + registry agents), plus full CRUD for **database** agents
  (FEAT-475 — see [Agent management](#agent-management) below). Registry
  (YAML/code) agents stay read-only.

## Auth model

Authentication is exclusively **navigator-auth** — there is no parallel
auth system for the Admin UI.

- Login: `POST /api/v1/login` with a `BasicAuth` username/password form.
  Any other configured auth backend (`GET /api/v1/auth/methods` discovers
  them) shows up as an extra sign-in option on the login page.
- Any authenticated user may enter — the Admin UI does not layer its own
  authorization on top of navigator-auth.
- The SPA authenticates its own API calls with a **Bearer token** (stored
  under the `ai_parrot_token` localStorage key — the same key
  `parrot/autonomous/admin.py`'s inline admin page and
  `parrot-formdesigner` use, so a redirect between them round-trips
  correctly), not the session cookie navigator-auth also sets. A `401`
  response clears the stored session and redirects to `/admin/login`,
  preserving the page you were on via `?next=`.
- Logout: `GET /api/v1/logout`.

## Agent management

**Feature**: FEAT-475 — UI Agent Management — Admin UI Agent CRUD

The Agents page (`/admin/agents`) gets a **Create Agent** button, per-row
**Edit**/**Delete** actions, and a **Show disabled** toggle. Every
mutating affordance is **database-agent-only** (`source: "database"`) —
registry (YAML/code) rows never get an Edit or Delete action, matching
FEAT-468's original read-only design for that source.

### Registry agents stay read-only

Agents loaded from the repository's YAML/code registry (`source:
"registry"`) cannot be created, edited, or deleted from the Admin UI —
there is no affordance for it in the list, the detail dialog, or the
form. Attempting to `DELETE` a repo-committed registry agent via the API
directly returns `403` (`"...is a repo YAML/code agent and cannot be
deleted via this endpoint."`); only **database** agents are managed here.

### Creating and editing: the form

`/admin/agents/new` (create) and `/admin/agents/<name>` (edit) open a
six-tab form covering every user-editable `BotModel` field:

| Tab | Fields |
|---|---|
| **General** | `chatbot_id` (edit only, read-only), `name` (read-only in edit — see below), `description`, `avatar`, `enabled`, `timezone`, `language`, `disclaimer` |
| **Behavior** | `role`, `goal`, `backstory`, `rationale`, `capabilities`, `pre_instructions`, `system_prompt_template`, `human_prompt_template`, `prompt_config` |
| **AI** | `llm` (from the catalog), plus `model`/`temperature`/`max_tokens`/`top_p`/`top_k` (stored inside `model_config`), and the raw `model_config` JSON |
| **Capabilities** | `tools_enabled`, `auto_tool_detection`, `tool_threshold`, `tools` (checkbox list from `/api/v1/agent_tools` + a fallback text list for names not in the catalog), `operation_mode` (from the catalog), `use_kb`, `kb`, `custom_kbs` (suggestions from the catalog's knowledge-base classes) |
| **Data & Memory** | `use_vector`, `vector_store_config`, `reranker_config`, `parent_searcher_config`, `context_search_limit`, `context_score_threshold`, `memory_type` (from the catalog), `memory_config`, `max_context_turns`, `use_conversation_history` |
| **Advanced** | `bot_class` (plain text, default `BasicBot`), `permissions` (JSON — a dict or a list of rule objects) |

Every JSONB field (`model_config`, `prompt_config`, `vector_store_config`,
`reranker_config`, `parent_searcher_config`, `memory_config`,
`permissions`) is edited through a validated JSON text editor — malformed
JSON blocks Save with an inline error; there is no external JSON-editor
dependency. Save is sticky across every tab, and a tab with an invalid
field shows a red badge with its error count.

#### Name slugification — read this before scripting against the API

`name` is the agent's identity (it appears in the URL and in
`BotManager`'s internal registration key). On **create**, the server
**slugifies and deduplicates** whatever you type:

- `PUT /api/v1/bots` with `name: "My Bot"` creates an agent named
  `my-bot`, not `My Bot`. If `my-bot` is already taken, the server tries
  `my-bot-2`, `my-bot-3`, etc.
- The Admin UI **always navigates to the name the server actually
  returned** (`response.name`), never the name you typed, and shows a
  brief notice when the two differ.
- **Renaming an existing agent is not supported** by the UI (v1) — `name`
  is rendered read-only in the edit form and is never included in the
  update request. The backend itself would technically apply a `name` key
  sent via `POST /api/v1/bots/{name}`, but the UI deliberately never sends
  one.

### Disabled agents and "Show disabled"

By default, `GET /api/v1/bots` — and therefore the Agents list — only
returns **enabled** database agents (`enabled: true`), exactly as before
FEAT-475. Toggling **Show disabled** on the list page adds
`?include_disabled=true` to the request, which returns every database
agent regardless of its `enabled` flag; disabled rows are shown with a
muted style and a "disabled" badge. This lets you find and re-enable (or
delete) an agent you previously toggled off from the form's General tab.

### The catalog endpoint (`GET /api/v1/admin/catalog`)

The form never hardcodes its option lists. `GET /api/v1/admin/catalog`
(authenticated, like every other Admin UI JSON endpoint) returns:

```json
{
  "llm_providers": ["anthropic", "google", "groq", "..."],
  "operation_modes": ["conversational", "agentic", "adaptive"],
  "memory_types": ["memory", "file", "redis"],
  "knowledge_bases": [
    {"class_path": "parrot.stores.kb.redis.RedisKnowledgeBase", "name": "RedisKnowledgeBase"}
  ],
  "bot_class_default": "BasicBot"
}
```

- `llm_providers` is deduplicated by resolved client class (`SUPPORTED_CLIENTS`
  has many alias keys — `claude`/`anthropic`, `claude-agent`/`claude-code`,
  etc. — for the same underlying client; only the first alias per client
  is listed). An agent's stored `llm` value is still shown/kept even when
  it holds an alias absent from this list.
- `knowledge_bases` lists the importable `AbstractKnowledgeBase`
  subclasses (`RedisKnowledgeBase` always; `LocalKB` only when
  `ai-parrot-embeddings` is installed — its absence degrades the catalog
  gracefully rather than raising).
- Like `/api/v1/admin/status`, this endpoint registers **unconditionally**
  (even when the compiled `dist/` is absent) — it is UI-agnostic JSON, not
  part of the SPA shell.

### Tools list is now library-owned

`GET /api/v1/agent_tools` (the tools picker's data source) is registered
by **`BotManager.setup()`** itself — a plain `pip install ai-parrot-server`
deployment has this route without needing repo-root `app.py` to register
it separately (as it did before FEAT-475). The registration is
idempotent: a host app that still registers the route itself does not
crash on startup.

## Adopter view: running it

```bash
pip install ai-parrot-server
# ... start your aiohttp app that calls BotManager.setup(), which wires
# setup_admin_ui() automatically ...
```

Visit `/admin` — you get the login page, then Home/Dashboard/Agents, with
**no Node.js required on the host**. The UI ships pre-built inside the
wheel (`parrot/server/ui/dist/`); the server only serves static files.

### The git-install caveat

If you install `ai-parrot-server` **from a git checkout** (editable
install, `pip install -e .`, or building your own wheel locally) **without
running the UI build first**, `parrot/server/ui/dist/` will not exist.
`setup_admin_ui()` degrades gracefully in that case:

- the server starts normally,
- a single `WARNING` is logged,
- zero `/admin` routes are registered,
- the rest of the API is completely unaffected.

This is expected, not a bug — `dist/` is intentionally gitignored (it is
build output, not source). If you need the Admin UI from a git checkout,
build it yourself first:

```bash
cd packages/ai-parrot-server/ui
pnpm install --frozen-lockfile
pnpm generate   # regenerate TS types from the backend's JSON Schema
pnpm build      # writes packages/ai-parrot-server/src/parrot/server/ui/dist/
```

Then start the server as usual. Note: `parrot-formdesigner`'s own `/admin`
redirect will 404 if you skip this step — that is an accepted consequence
of the git-install caveat, not a separate failure mode.

The official release pipeline (`.github/workflows/release.yml`'s
`build-server` job, and the `make build-server-ui` / `make release` path)
always runs this build before publishing a wheel — see
[Wheel-content guarantee](#wheel-content-guarantee-and-release-pipeline)
below.

## Developer view: working on the Admin UI

The UI is a standalone Vite + Svelte 5 SPA (not SvelteKit) that lives at
`packages/ai-parrot-server/ui/`. It is **not** part of the `uv` Python
workspace — manage it with `pnpm`.

```bash
cd packages/ai-parrot-server/ui
pnpm install

# Point the dev server at a running backend (defaults to
# http://localhost:5000 — override via a .env's PUBLIC_API_URL, read
# through `lib/config.ts`):
pnpm dev
```

`pnpm dev` starts Vite's dev server with `/api` proxied to the backend
(see `vite.config.ts`'s `server.proxy`), so you can iterate on the UI
against a real running server without rebuilding anything Python-side.

### Codegen (`pnpm generate`)

TypeScript types under `ui/src/lib/types/generated/` are generated from
backend Pydantic models' JSON Schema — never hand-edit files carrying the
`// GENERATED … DO NOT EDIT` banner. Regenerate them with:

```bash
pnpm generate
```

This runs `json2ts` (`json-schema-to-typescript`) against `ui/schemas/`
and writes `.d.ts` files. `pnpm build` always runs `pnpm generate` first
(see `package.json`'s `build` script), so a production build never ships
stale types.

### Where the build output lands

```bash
pnpm build
```

writes the production bundle to
`packages/ai-parrot-server/src/parrot/server/ui/dist/` (see
`vite.config.ts`'s `build.outDir`) — directly into the Python package's
source tree, one level below the aiohttp handlers that serve it
(`parrot/server/ui/serving.py`). That directory is gitignored; it exists
only as local build output or as release-pipeline output.

### Tests

```bash
pnpm test    # vitest — component + unit tests, jsdom environment
pnpm build   # also type-checks/generates and verifies the production build
```

## Wheel-content guarantee and release pipeline

A wheel built **without** the Node/pnpm stage silently ships no Admin UI —
`setuptools`'s package-data glob
(`"parrot.server.ui" = ["dist/*", "dist/assets/*"]` in
`packages/ai-parrot-server/pyproject.toml`) only picks up files that
already exist in `dist/` at build time, and there is no build hook that
runs the frontend build automatically. This is caught by a **dual check**:

1. **`@pytest.mark.wheel_build` test** —
   `packages/ai-parrot-server/tests/test_wheel_layout.py::TestWheelContainsAdminUI`
   builds the wheel (via the existing `satellite_wheel_path` fixture, which
   shells out to `uv build`) and asserts it contains
   `parrot/server/ui/dist/index.html` and at least one file under
   `parrot/server/ui/dist/assets/`. Run it locally:

   ```bash
   pytest packages/ai-parrot-server/tests/test_wheel_layout.py -v -m wheel_build
   ```

   It fails if `pnpm build` was never run (no `dist/`, or a stale
   `packages/ai-parrot-server/build/` cache from a previous build — clean
   that directory locally if you see stale results) and passes once the UI
   has actually been built.

2. **Release-workflow step** — both real release paths build the UI
   *before* invoking `uv build`, and fail loudly (`test -f
   .../dist/index.html`, non-zero exit) rather than silently publishing a
   UI-less wheel:
   - `.github/workflows/release.yml`'s `build-server` job (the path that
     feeds the `deploy` job publishing to PyPI): sets up Node 24 LTS +
     pnpm 9 via corepack, `pnpm install --frozen-lockfile`, `pnpm
     generate`, `pnpm build`, then asserts `dist/index.html` exists.
   - `Makefile`'s `release` target now depends on a new `build-server-ui`
     target (`make build-server-ui`) that does the same, before any
     `uv build --package ai-parrot-server` / `uv publish` step.
