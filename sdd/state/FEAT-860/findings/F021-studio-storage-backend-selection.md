---
id: F021
query_id: Q004
type: wiki_page
intent: "Read the Studio storage backend selection as the nearest dual-backend (Postgres + fallback) pattern."
executed_at: 2026-11-09T17:13:25Z
duration_ms: 300
parent_id: null
depth: 2
merged_from: [FW-012]
---

# F021 — Studio storage selection: setting auto|database|filesystem, app["database"] pool, read-only probe, fail closed on Postgres switches

## Summary

`ensure_studio_storage(app)` reads `PARROT_STUDIO_STORAGE` (`auto` default), takes the shared pool from
`app.get("database")`, runs a read-only schema-ledger probe, and maps (setting, pool, probe) to
`database | filesystem | unavailable` in the pure `_resolve()`; `auto` degrades to filesystem when there is no pool
or the schema is not migrated, while an explicit `database` setting becomes `unavailable`. Per-store switches
(`VAULT_STORE`, `TOOLKIT_OVERRIDES_STORE`, `BYOK_STORE` = `postgres`) fail closed at startup if the backend is not
`database`, "never fall back". Result is memoised on the app under a lock.

## Citations

- path: `packages/ai-parrot-server/src/parrot/handlers/studio/storage/backend.py`
  lines: 50-54
  symbol: `_read_setting`
  excerpt: |
    value = str(config.get("PARROT_STUDIO_STORAGE", fallback="auto") or "auto").strip().lower()

- path: `packages/ai-parrot-server/src/parrot/handlers/studio/storage/backend.py`
  lines: 67-91
  symbol: `_fail_closed`
  excerpt: |
    _STORE_SWITCHES = ("VAULT_STORE", "TOOLKIT_OVERRIDES_STORE", "BYOK_STORE")
    """Raise when a Postgres store switch is on and the backend cannot serve it (never fall back to DocumentDB)."""

- path: `packages/ai-parrot-server/src/parrot/handlers/studio/storage/backend.py`
  lines: 132-150
  symbol: `_resolve`
  excerpt: |
    if pool is None:
        if setting == "auto": return "filesystem", "no database pool"
        return "unavailable", "PARROT_STUDIO_STORAGE=database but no database pool"

- path: `packages/ai-parrot-server/src/parrot/handlers/studio/storage/backend.py`
  symbol: `ensure_studio_storage`
  excerpt: |
    pool = app.get("database")
    state = await _probe(pool) if pool is not None and setting != "filesystem" else None
    backend, reason = _resolve(setting, pool, state)

## Notes

Reusable ideas for crew storage: an explicit backend setting (e.g. redis | postgres | both) instead of an
implicit "initialize both", the shared `app["database"]` pool rather than a new DSN, a read-only probe of the
table, and a fail-closed rule when Postgres is required but unreachable. Contrast FW-010, which opens its own
connection from a dedicated DSN.
