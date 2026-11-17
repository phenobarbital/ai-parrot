---
id: F007
query_id: Q013
type: grep
intent: "Find crew storage configuration keys / env vars (Redis db, DSN, feature flags)."
executed_at: 2026-11-09T17:27:00Z
duration_ms: 600
parent_id: null
depth: 0
merged_from: [FC-008]
---

# F007 — Crew config: only ENABLE_CREWS gates definition persistence; Redis db 2 is hard-coded in CrewRedis; result storage has its own CREW_RESULT_STORAGE* keys; default_dsn may be None

## Summary

All crew settings live in core `packages/ai-parrot/src/parrot/conf.py`. Crew-DEFINITION persistence has a
single flag, `ENABLE_CREWS` (bool, fallback `False`); there is no key selecting its backend, its Redis URL
or db (CrewRedis hard-codes `db=2` and builds the URL from `REDIS_HOST`/`REDIS_PORT`). Crew-RESULT
storage (FEAT-147) has a backend selector `CREW_RESULT_STORAGE` (fallback `"documentdb"`) and per-backend
keys `CREW_RESULT_STORAGE_PG_DSN` (fallback `default_dsn`), `CREW_RESULT_STORAGE_REDIS_URL`,
`CREW_RESULT_STORAGE_REDIS_TTL` — the naming precedent for e.g. `CREW_DEFINITION_STORAGE*`.
`default_dsn` is built from `DBUSER/DBHOST/DBPORT/DBNAME` and is `None` when those are not configured
(lines 72-77), so a Postgres store must handle a missing DSN. No `CREW_*` migration flag exists.

## Citations

- path: `packages/ai-parrot/src/parrot/conf.py`
  lines: 96
  symbol: `ENABLE_CREWS`
  excerpt: |
    ENABLE_CREWS = config.getboolean("ENABLE_CREWS", fallback=False)

- path: `packages/ai-parrot/src/parrot/conf.py`
  lines: 72-77
  symbol: `default_dsn`
  excerpt: |
        default_dsn = f"postgres://{DBUSER}{_pwd}@{DBHOST}:{DBPORT}/{DBNAME}"
        async_default_dsn = f"postgresql+asyncpg://{DBUSER}{_pwd}@{DBHOST}:{DBPORT}/{DBNAME}"
    ...
        default_dsn = None
        async_default_dsn = None

- path: `packages/ai-parrot/src/parrot/conf.py`
  lines: 86-89
  symbol: `REDIS_HOST / REDIS_PORT / REDIS_DB / REDIS_URL`
  excerpt: |
    REDIS_HOST = config.get("REDIS_HOST", fallback="localhost")
    REDIS_PORT = config.get("REDIS_PORT", fallback=6379)
    REDIS_DB = config.get("REDIS_DB", fallback=1)
    REDIS_URL = f"redis://{REDIS_HOST}:{REDIS_PORT}/{REDIS_DB}"

- path: `packages/ai-parrot/src/parrot/conf.py`
  lines: 312-316
  symbol: `CREW_RESULT_STORAGE*`
  excerpt: |
    # Crew/flow execution result storage (FEAT-147)
    CREW_RESULT_STORAGE = config.get("CREW_RESULT_STORAGE", fallback="documentdb")
    CREW_RESULT_STORAGE_PG_DSN = config.get("CREW_RESULT_STORAGE_PG_DSN", fallback=default_dsn)
    CREW_RESULT_STORAGE_REDIS_URL = config.get("CREW_RESULT_STORAGE_REDIS_URL", fallback=REDIS_URL)
    CREW_RESULT_STORAGE_REDIS_TTL = int(config.get("CREW_RESULT_STORAGE_REDIS_TTL", fallback=604800))

- path: `packages/ai-parrot/src/parrot/conf.py`
  lines: 121-122
  symbol: `PARROT_SCHEMA`
  excerpt: |
    PARROT_SCHEMA = config.get("PARROT_SCHEMA", fallback="navigator")

- path: `packages/ai-parrot-server/src/parrot/handlers/crew/redis_persistence.py`
  lines: 24, 38-40
  symbol: `CrewRedis db=2`
  excerpt: |
    db: int = 2  # Use DB 2 for crew persistence
    from ...conf import REDIS_HOST, REDIS_PORT
    redis_url = f"redis://{REDIS_HOST}:{REDIS_PORT}/{db}"

## Notes

- `REDIS_DB`/`REDIS_URL` are defined twice in conf.py (lines ~88-89 and ~309-310); harmless but noisy.
- The ai-parrot-server package has no own `conf.py`; `from ...conf import ...` inside
  `handlers/crew/` resolves to core `parrot.conf`.
- There is no `parrot.conf` key today for selecting the crew-definition backend; the proposal must add one
  (or a constructor/kwarg `migration=True`) — and decide whether the migration flag is config- or code-level.
