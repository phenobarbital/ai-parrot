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

   # Run headless smoke check
   A2UI_DEMO_PASSWORD=<password> python examples/a2ui/client.py --check --user admin
   ```

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `ENV` | Yes | Set to `prod` for production data |
| `QS_PBAC_ENABLED` | Yes | Set to `false` for local dev |
| `A2UI_DEMO_PASSWORD` | For `--check` | Password for demo user |
| `QS_ASYNCPG_URL` | No | Override DB connection (defaults to querysource config) |

## Files

- `server.py` — Example aiohttp server serving the dashboard
- `client.py` — CLI client with `--open` and `--check` modes
- `seed_by_course.py` — Idempotent seed script for the by-course slug
- `dashboard.py` — Widget definitions and agent configuration
- `static/linked.js` — Vanilla JS port of the linked lane

## Testing

```bash
pytest tests/examples/test_a2ui_client_seed.py -q
```