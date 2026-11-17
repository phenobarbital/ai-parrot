---
title: User stores (Redis by default)
summary: Where ai-parrot keeps per-user credentials, BYOK keys, overrides, MCP configs, OAuth connections and dashboards — and how to switch.
---

# User stores (Redis by default)

## Purpose

User stores hold per-user data that agents need at runtime. FEAT-878 makes Redis the default for all of them, so ai-parrot runs without MongoDB for local or simple installations.

| Collection | What it holds | Switch |
|---|---|---|
| `user_credentials` | Vault: AES-GCM sealed credentials | `VAULT_STORE` |
| `user_llm_keys` | Per-user LLM API keys (BYOK) | `BYOK_STORE` |
| `user_toolkit_configs` | Per-user toolkit overrides | `TOOLKIT_OVERRIDES_STORE` |
| `user_mcp_configs` | Per-user activated MCP servers | `MCP_CONFIGS_STORE` |
| `telegram_user_mcp_configs` | Telegram `/add_mcp` servers | `TELEGRAM_MCP_STORE` |
| `users_integrations` | OAuth2 connection records | `INTEGRATIONS_STORE` |
| `dashboards`, `dashboard_tabs` | Saved dashboards | `DASHBOARDS_STORE` |

## Configuration & Parameters

Resolution order (read at call time):
1. Per-store switch (e.g., `VAULT_STORE`)
2. Global switch `PARROT_USER_STORE`
3. Default: `redis`

| Switch | Allowed values | Collections |
|---|---|---|
| `VAULT_STORE` | `redis`, `documentdb`, `postgres` | `user_credentials` |
| `BYOK_STORE` | `redis`, `documentdb`, `postgres` | `user_llm_keys` |
| `TOOLKIT_OVERRIDES_STORE` | `redis`, `documentdb`, `postgres` | `user_toolkit_configs` |
| `MCP_CONFIGS_STORE` | `redis`, `documentdb` | `user_mcp_configs` |
| `TELEGRAM_MCP_STORE` | `redis`, `documentdb` | `telegram_user_mcp_configs` |
| `INTEGRATIONS_STORE` | `redis`, `documentdb` | `users_integrations` |
| `DASHBOARDS_STORE` | `redis`, `documentdb` | `dashboards`, `dashboard_tabs` |

Redis-specific settings:

| Key | Default | Meaning |
|---|---|---|
| `PARROT_USER_STORE_REDIS_URL` | `redis://{REDIS_HOST}:{REDIS_PORT}/6` | Full Redis URL (overrides host/port/db) |
| `PARROT_USER_STORE_REDIS_DB` | `6` | Logical database number |
| `PARROT_USER_STORE_REDIS_PREFIX` | `parrot:us` | Key prefix (no trailing colon) |

Crew result storage:

| Key | Default | Meaning |
|---|---|---|
| `CREW_RESULT_STORAGE` | follows `PARROT_USER_STORE` | Where crew/flow results are stored |
| `CREW_RESULT_STORAGE_REDIS_URL` | `REDIS_URL` | Separate URL for results (not secrets) |
| `CREW_RESULT_STORAGE_REDIS_TTL` | `7 days` | TTL for results in Redis |

When `CREW_RESULT_STORAGE` is unset, it follows `PARROT_USER_STORE` (or `redis` if that is also unset).

## Upgrading an installation that uses MongoDB

**Startup guard.** When `DOCUMENTDB_HOSTNAME` or `DOCUMENTDB_DBNAME` is set, and any store (or unset `CREW_RESULT_STORAGE`) would default to Redis, startup stops with `UserStoreMisconfigured` and a message listing the affected stores. Setting `PARROT_USER_STORE` clears the guard; setting every per-store switch clears it only if `CREW_RESULT_STORAGE` is also set. The guard also runs when the first user-store Redis client is created, so standalone runners and scripts are covered, not only `BotManager.setup()`. If `USE_DOCUMENTDB` is enabled but neither `DOCUMENTDB_HOSTNAME` nor `DOCUMENTDB_DBNAME` is set (DocumentDB would default to `localhost`), a warning is logged because stores silently default to Redis.

**Authenticated Redis.** `REDIS_PASSWORD` is not used for user stores; put credentials in `PARROT_USER_STORE_REDIS_URL` (for example `redis://:password@host:6379/6`). Logged URLs have credentials stripped.

**Fix A — keep MongoDB:**
```bash
export PARROT_USER_STORE=documentdb
```

**Fix B — move to Redis:**
```bash
# 1. Dry-run to see what would be copied
python -m parrot.userstore.copy --dry-run

# 2. Copy the data (insert-only by default)
python -m parrot.userstore.copy

# 3. Switch to Redis
export PARROT_USER_STORE=redis
```

The copy CLI:
- Copies documents verbatim (ciphertexts unchanged, no keyring needed)
- Is insert-only by default (existing Redis documents are skipped)
- With `--overwrite`, replaces only when source `updated_at` is strictly newer
- Collapses duplicate DocumentDB documents to the newest by `updated_at`
- Exit code 1 when any document failed

## Redis requirements

**Persistence required.** User stores contain secrets that must survive restarts.

| Setting | Requirement |
|---|---|
| `maxmemory-policy` | Must NOT be `allkeys-*` (eviction would drop secrets) |
| AOF or RDB | At least one persistence mode must be enabled |
| TTL | No TTL on user-store keys (documents live until deleted) |

**Startup diagnostics** run when any store resolves to `redis`:
- `PING` — warns when unreachable
- `CONFIG GET maxmemory-policy` — warns on `allkeys-*` policies
- `CONFIG GET appendonly` / `save` — warns when both persistence modes are off

**Redis Cluster:** Set `PARROT_USER_STORE_REDIS_URL` explicitly (Cluster only supports DB 0).

## Usage Examples

**Local development (no configuration needed):**
```bash
# Redis on localhost:6379, db 6 — no env vars required
python -m parrot.server
```

**Keep MongoDB in production:**
```bash
export PARROT_USER_STORE=documentdb
export DOCUMENTDB_HOSTNAME=docdb.example.com
export DOCUMENTDB_DBNAME=parrot
```

**Mixed: Vault in Postgres, rest in Redis:**
```bash
export PARROT_USER_STORE=redis
export VAULT_STORE=postgres
# Requires Studio backend to be database (schema migrations 0006-0008)
```

**BYOK keys in Postgres, credentials in Redis:**
```bash
export BYOK_STORE=postgres
export VAULT_STORE=redis
export PARROT_USER_STORE=redis
```

## Gotchas

- **Crew results expire:** Results in Redis expire after 7 days (`CREW_RESULT_STORAGE_REDIS_TTL`). This is independent of user-store persistence requirements.
- **Postgres stores fail closed:** `VAULT_STORE=postgres` (or `BYOK_STORE`, `TOOLKIT_OVERRIDES_STORE`) without a registered Postgres store raises `RuntimeError` at call time.
- **Copy CLI is snapshot, not sync:** Changes to DocumentDB after the copy are not propagated; deletions are not synced.
- **Quarantine keeps latest:** Rotation quarantine keeps the latest copy per identity in `{collection}_quarantine`.
- **Duplicate DocumentDB documents:** The old `CredentialsHandler.put` used `save_background` (INSERT), leaving duplicates. The copy CLI collapses these to the newest by `updated_at`.

## Related

- [Agent Studio database storage](../bots/agentstudio/db-storage.md) — Phase-2 switches and Postgres schema
- [DocumentDB interface](documentdb_interface.md) — DocumentDB usage guide
- [Crew definition storage](../bots/orchestration/crew-definition-storage.md) — `CREW_RESULT_STORAGE` behavior
- Spec: `sdd/specs/redis-user-stores.spec.md` (FEAT-878)
