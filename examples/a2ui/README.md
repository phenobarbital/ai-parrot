# A2UI Linked E2E Example

FEAT-610 — Polestar graduates linked dashboard with example client and seed script.

## Prerequisites

- **ENV=prod** — All data scripts run against production (dev DB times out).
- **querysource ≥ 5.1.2** — Required for the LATERAL expansion in the by-course slug.
- **QS_PBAC_ENABLED=false** — Disable PBAC for local development.

## Run Order

1. **Seed the by-course slug** (one-time, idempotent):
   ```bash
   ENV=prod python examples/a2ui/seed_by_course.py --yes
   ```

2. **Start the example server**:
   ```bash
   ENV=prod QS_PBAC_ENABLED=false python examples/a2ui/server.py --port 5000
   ```

3. **Open in browser** or **run smoke check**:
   ```bash
   # Open dashboard in browser
   python examples/a2ui/client.py --open

   # Run the headless check: logs in, replays the lane's requests, ASSERTS the spec values (17572 / 9191 / 6245 /
   # 2884, 95 country groups, 23 licensee groups, the four pie slices) and exercises the grid's server paging.
   # Exit 0 only if everything passes; a 404, a wrong value or a missing source exits 1.
   ENV=prod python examples/a2ui/client.py --check

   # Print the values without asserting them (for data that has legitimately drifted)
   ENV=prod python examples/a2ui/client.py --check --no-expect
   ```

**Notes.** The server binds to loopback by default (`--host 0.0.0.0` exposes production data behind BasicAuth only). The
dashboard envelope is built once by the LLM agent and cached for all users; `GET /api/a2ui/dashboard?rebuild=1` lets any
authenticated user re-run the agent (a demo simplification).

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `ENV` | Yes | Set to `prod` for production data |
| `QS_PBAC_ENABLED` | Yes | Set to `false` for local dev |
| `A2UI_USER_USERNAME` | No | Login user for `--check` (read from `env/<ENV>/.env`; `--user` overrides; default `admin`) |
| `A2UI_USER_PASSWORD` | For `--check` | Login password for `--check` (read from `env/<ENV>/.env`) |
| `A2UI_DEMO_PASSWORD` | No | Password override (takes precedence over `A2UI_USER_PASSWORD`) |

## Files

- `server.py` — Example aiohttp server serving the dashboard
- `client.py` — CLI client with `--open` and `--check` modes
- `seed_by_course.py` — Idempotent seed script for the by-course slug
- `dashboard.py` — Dashboard-owned data sources (`SOURCES`), widget definitions (`WIDGETS`) and agent configuration.
  The dashboard fetches each source once and shares it: four KPICards read one `kpis` query, two bar charts are
  *derived views* (`kind: "derived"`, DSL `group_by`) of one `geo` matrix — 4 QuerySource calls instead of 8.
- `static/linked.js` — Vanilla JS port of the linked lane (fetch, conditions, `refreshSource`/`refreshAll`, derived
  views computed from their parent's frame with a cascade on refresh, and the example-only `fetchPage` used for the
  server-paged grid). `transform.ops` run through `static/dsl.js`; `transform.ref` modules are not supported here.
- `static/dsl.js` — Vanilla port of the transform DSL (ten ops), checked against the shared golden fixtures.
- `static/renderer.js` — renders the envelope (KPICard / Chart / DataTable). The grid is a small native table paged on
  the server (`querylimit` + `_offset`, stable `ordering`, exact-match column filters, total via `count(*)`); all
  envelope text is inserted with `textContent`. The browser logs in with `POST /api/v1/login` (JSON) and keeps the JWT
  in `localStorage` under `ai_parrot_token`.

## Testing

```bash
PYTHONPATH=packages/ai-parrot-tools/src:packages/ai-parrot/src:packages/ai-parrot-server/src:packages/ai-parrot-visualizations/src:. \
  pytest tests/examples -q
```

`test_a2ui_renderer.py` runs the renderer under jsdom against a real envelope built by the production builders; it needs
`node` and the admin UI's `node_modules` (skipped otherwise).