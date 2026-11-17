# Passkey (WebAuthn) end-to-end example

A self-contained demo of FEAT-772: an aiohttp server with the embedded Admin UI, one chat agent
(`hello-agent`), password sign-in **and** passkey sign-in/enrolment, backed by a throw-away Postgres and
Redis. Everything lives in `examples/passkey/`.

| File | Purpose |
|---|---|
| `docker-compose.yml` | Postgres 16 (`:55432`) and Redis 7 (`:56379`) — ports offset to avoid your dev stack |
| `env_defaults.py` | Forces the demo settings (DB, Redis, auth, relying party) ahead of any `parrot`/`navigator_auth` import |
| `setup_demo_db.py` | Creates the `auth.users` table and the demo user (idempotent) |
| `server.py` | The server: `BotManager` + embedded UI + `AuthHandler(BasicAuth, PasskeyAuth)` + `HelloAgent` |
| `smoke_test.py` | Browser-less checks against the running server |

> `examples/**/*.py` is git-ignored in this repository; the files are tracked with `git add -f`.

## Requirements

| Need | Why |
|---|---|
| Python 3.11+ and the repo's virtualenv (`source .venv/bin/activate`) | runs the server |
| `ai-parrot-server[passkey]` | pulls `navigator-auth[passkey]>=0.28.9` → `webauthn` 2.x. Without it startup fails with `PasskeyAuth requires the optional extra` |
| Docker + Docker Compose | Postgres (user store, passkey tables) and Redis ≥ 6.2 (challenges use `GETDEL`) |
| Node 24 LTS (with corepack → `pnpm` 9) | builds the Admin UI once (`packages/ai-parrot-server/ui`) |
| An LLM API key (default `GOOGLE_API_KEY`) | only for actually chatting; sign-in works without it |
| A browser with WebAuthn and a platform or security-key authenticator | the real ceremony. `http://localhost` counts as a secure context; any other host needs HTTPS |

## Install

From the repository root:

```bash
source .venv/bin/activate

# 1. The passkey extra (webauthn + cbor2)
uv pip install "ai-parrot-server[passkey]"

# 2. Build the Admin UI into the server package (writes parrot/server/ui/dist)
make build-server-ui          # or: cd packages/ai-parrot-server/ui && pnpm install && pnpm build

# 3. Postgres + Redis
docker compose -f examples/passkey/docker-compose.yml up -d

# 4. Schema + demo user  (demo / demo-password)
python examples/passkey/setup_demo_db.py
```

Working from a git worktree? The shared virtualenv is editable-installed against the main checkout, so
prefix commands with `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-server/src`.

## Run

```bash
export GOOGLE_API_KEY=...            # or: export DEMO_LLM="openai:gpt-4o-mini" and OPENAI_API_KEY=...
python examples/passkey/server.py    # http://localhost:5000
```

Settings can be overridden with `DEMO_<NAME>` variables, e.g. `DEMO_PORT=5001` (the relying-party origin
follows the port), `DEMO_DBPORT`, `DEMO_REDIS_URL`, `DEMO_LLM`.

### Verify without a browser

In a second terminal:

```bash
python examples/passkey/smoke_test.py
```

Expected: eight `PASS` lines (SPA shell, both auth methods advertised, password login, `hello-agent` listed,
passkey login/register options, empty passkey list).

### Verify in a browser (the real ceremony)

1. Open `http://localhost:5000/login` and sign in with **demo / demo-password**.
2. Go to **Account → Security** (`/account/security`) → **Add a passkey**, name it, and approve the
   browser/OS prompt.
3. Sign out. On `/login` choose **Sign in with a passkey** (or focus the username field and pick the passkey
   from the autofill list). The top bar shows a passkey badge for passkey sessions.
4. Back on **Account → Security**: rename the passkey, then delete it (a confirmation dialog appears; the server
   answers 409 and the UI explains it if it would remove your last login method).
5. Open `/agents/hello-agent/chat` and talk to the agent (needs the API key from the Run step).
6. The legacy page `http://localhost:5000/autonomous/admin` also offers a passkey button when the backend is on.

## How it fits together

- `server.py` calls `AuthHandler(backends=[BasicAuth, PasskeyAuth])`. The backends are explicit on purpose:
  a developer's `settings/settings.py` can override `AUTHENTICATION_BACKENDS` at import time.
- `PASSKEY_RELYING_PARTIES` has one entry per **exact** browser origin (`http://localhost:5000`, rp_id
  `localhost`). Enrolling on `:5173` (Vite dev server) does not make the passkey usable on `:5000`; add an
  entry per origin if you develop the UI with `pnpm dev`.
- `PasskeyAuth` creates its tables (`auth.passkey_credentials`, …) at startup. Challenges live in Redis
  (`REDIS_AUTH_URL`, 300 s TTL).
- The agent is registered with `BotManager.registry.register_instance(...)`, which is what
  `GET /api/v1/bots` lists and the chat page resolves.

## Isolation notes

`navconfig` prefers values from `env/.env` over `os.environ`, so a developer machine's real database and Redis
would otherwise win. `env_defaults.py` therefore writes the demo values with `config.set(...)` before anything
else is imported, and points `AGENTS_DIR` at an empty temp directory so your repository's own `agents/` are
**not** loaded. If you bypass `env_defaults.py`, check what `DBHOST`/`REDIS_URL` resolve to first.

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `PasskeyAuth requires the optional extra` | `uv pip install "ai-parrot-server[passkey]"` |
| `ConfigError` mentioning `PASSKEY_RELYING_PARTIES` | empty/invalid JSON, or the origin does not match the URL in the address bar |
| Login page loads but there is no passkey button | the browser lacks WebAuthn, the page is not a secure context, or `/api/v1/auth/methods` does not list `PasskeyAuth` |
| `/login` returns 404 | UI not built — run `make build-server-ui` |
| Passkey prompt never appears on `127.0.0.1` | use `localhost`; the relying-party id must match the host name |
| `ERROR … relation "navigator.ai_bots" does not exist` at startup | harmless: the agent looks for a database definition, finds none and configures itself manually |
| Chat answers with an authentication error | missing/invalid LLM API key (sign-in itself is unaffected) |

## Clean up

```bash
docker compose -f examples/passkey/docker-compose.yml down -v   # drops the demo database and Redis data
```
