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
- **Agents** (`/admin/agents`) — read-only table over `GET /api/v1/bots`
  (merged database + registry agents). No create/edit/delete — that is a
  future spec.

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
