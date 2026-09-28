---
id: F017
query_id: Q017
type: read
intent: What infrastructure/env QuerySource needs at runtime; what "no external deps" can mean
executed_at: 2026-09-28T20:30:00Z
parent_id: null
depth: 0
---
# F017 — QS runtime needs Postgres (`DBUSER/DBPWD/DBHOST/DBPORT/DBNAME`, import fails without `DBUSER`) and Redis (condition parsing), all via navconfig `env/.env`
## Summary
`querysource.conf` builds `default_dsn = postgres://{DBUSER}:{DBPWD}@{DBHOST}:{DBPORT}/{DBNAME}` from navconfig and raises `RuntimeError('Missing PostgreSQL Default Settings.')` at import time when `DBUSER` is absent — so merely importing QS requires the env. Datasource-specific vars exist (`PG_HOST/PG_USER/PG_PWD/PG_DATABASE/PG_PORT`, pool sizes, `POSTGRES_SSL*`). Every slug execution also opens a Redis connection (`AsyncDB('redis', dsn=REDIS_URL)`) during condition parsing, and slug caching uses `CACHE_HOST/CACHE_PORT` / `REDIS_HOST/REDIS_PORT`. The slug catalogue itself lives in that Postgres (F016), and the demo data (`polestar_graduates_directory`, 17,572 rows) is a real table in it.
## Citations
- path: `venv:querysource/conf.py`
  lines: 24-34
  symbol: `default_dsn`
  excerpt: |
    DBHOST = config.get('DBHOST', fallback='localhost')
    DBUSER = config.get('DBUSER')
    DBPWD = config.get('DBPWD')
    DBNAME = config.get('DBNAME', fallback='navigator')
    DBPORT = config.get('DBPORT', fallback=5432)
    if not DBUSER:
        raise RuntimeError('Missing PostgreSQL Default Settings.')
    ...
    default_dsn = f'postgres://{DBUSER}:{DBPWD}@{DBHOST}:{DBPORT}/{DBNAME}'
- path: `venv:querysource/conf.py`
  lines: 37-42, 78-90
  symbol: `PG_HOST / CACHE_HOST / REDIS_HOST`
  excerpt: |
    PG_DRIVER = config.get('PG_DRIVER', fallback='pg')
    PG_HOST = config.get('PG_HOST', fallback='localhost')
    ...
    CACHE_HOST = config.get('CACHE_HOST', fallback='localhost')
    ...
    REDIS_HOST = config.get('REDIS_HOST', fallback='localhost')
- path: `../querysource/querysource/parsers/abstract.pyx`
  lines: 63-67, 450-453
  symbol: `AbstractParser._get_redis / _parser_conditions`
  excerpt: |
    cdef object _get_redis(self):
        ...
        self._redis = AsyncDB('redis', dsn=REDIS_URL)
    ...
    async def _parser_conditions(self, conditions: dict):
        redis = self._get_redis()
        async with await redis.connection() as conn:
- path: `packages/ai-parrot/pyproject.toml`
  lines: 223-225
  symbol: `-`
  excerpt: |
    # Database / query tools (querysource, psycopg, advanced asyncdb extras)
    ...
        "querysource>=4.1.11",
## Implications
- "No external dependencies to ai-parrot" can realistically mean: no code/packages outside the ai-parrot workspace + its declared extras (querysource, navigator-auth, navigator-session are already deps). It cannot mean no services — Postgres (data + `queries` table + navigator-auth users) and Redis are mandatory and come from the developer's `env/.env`.
- The example should fail fast with a clear message if `DBUSER`/Redis are missing, and document the required env vars; a fully offline variant would need a seeded Postgres container (out of scope unless the spec asks).
