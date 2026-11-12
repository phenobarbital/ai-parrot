---
id: F014
query_id: Q014
type: grep
intent: "Find the DB connection config used by bot storage (default_dsn, DSN env vars) for the migration runner."
executed_at: 2026-11-12T20:42:51Z
duration_ms: 200
parent_id: null
depth: 0
merged_from: [FC-015]
---

# F014 — parrot conf: runtime DSN from DBHOST/DBUSER/DBPWD/DBNAME/DBPORT; no admin-DSN setting

## Summary

`parrot/conf.py` builds `default_dsn = postgres://DBUSER[:DBPWD]@DBHOST:DBPORT/DBNAME` (None when DBUSER is unset), plus
asyncpg/sqlalchemy variants, and `PG_*` aliases defaulting to the DB* values. The bots table name and schema are
configurable (`PARROT_BOTS_TABLE`, default `ai_bots`; `PARROT_SCHEMA`, default `navigator`). A grep of conf.py for
`ADMIN_DSN|DB_ADMIN` returned nothing — there is no separate DDL/admin credential like navauth's `AUTH_ADMIN_DSN` /
`AUTH_ADMIN_USER` / `AUTH_ADMIN_PWD`.

## Citations

- path: `packages/ai-parrot/src/parrot/conf.py`
  lines: 65-77
  symbol: `default_dsn`
  excerpt: |
    DBHOST = config.get("DBHOST", fallback="localhost")
    DBUSER = config.get("DBUSER")
    DBPWD = config.get("DBPWD")
    DBNAME = config.get("DBNAME", fallback="navigator")
    DBPORT = config.get("DBPORT", fallback=5432)
    if DBUSER:
        default_dsn = f"postgres://{DBUSER}{_pwd}@{DBHOST}:{DBPORT}/{DBNAME}"
    else:
        default_dsn = None

- path: `packages/ai-parrot/src/parrot/conf.py`
  lines: 121-122
  symbol: `PARROT_SCHEMA`
  excerpt: |
    PARROT_BOTS_TABLE = config.get("PARROT_BOTS_TABLE", fallback="ai_bots")
    PARROT_SCHEMA = config.get("PARROT_SCHEMA", fallback="navigator")

- path: `packages/ai-parrot/src/parrot/conf.py`
  lines: 269-283
  excerpt: |
    DBHOST/DBUSER/DBPWD/DBNAME/DBPORT re-read (second block)
    PG_USER = config.get("PG_USER", fallback=DBUSER) ... PG_PORT = config.get("PG_PORT", fallback=DBPORT)

## Notes

Absence claim is scoped to conf.py only (single-file grep). Configurable table/schema names mean migration SQL must be
templated (`{schema}`/`{bots_table}`, as navauth's `render_sql` does — F008) rather than hard-code
`navigator.ai_bots` like every existing sdd/migrations script does (F005).
