---
id: F016
query_id: Q016
type: read
intent: Where slugs are stored and how an example could register its own slug definition(s)
executed_at: 2026-09-28T20:30:00Z
parent_id: null
depth: 0
---
# F016 — Slugs are rows in a Postgres `<schema>.queries` table (default `public.queries`, any other schema with a `queries` table = tenant); no file-based slug store
## Summary
`QueryModel` (primary key `query_slug`; `query_raw`, `provider` default `'db'`, `source`, `fields`, `filtering`, `grouping`, `ordering`, `conditions`, `cond_definition`, `is_cached`/`cache_timeout`, `program_slug` …) maps to `QS_QUERIES_SCHEMA.QS_QUERIES_TABLE` (defaults `public`.`queries`; not overridden in `env/.env`). `DefinitionRepository` loads a definition with `SELECT * FROM <table> WHERE query_slug = $1`. `TenantRegistry.discover()` scans `information_schema.tables` for every `queries` BASE TABLE: `public.queries` keeps the legacy contract (default store for `/api/v2/services/queries/{slug}`), every other schema (e.g. `troc.queries`) becomes a tenant reachable at `/api/v1/{tenant}/queries/{slug}`. No YAML/file slug loader exists. New slugs are created through `PUT`/`POST /api/v1/management/queries/{slug}` (`QueryManager`) or by inserting a row.
## Citations
- path: `venv:querysource/models.py`
  lines: 48-52, 71-74, 103-104
  symbol: `QueryModel`
  excerpt: |
    class QueryModel(Model):
        query_slug: str = Field(required=True, primary_key=True)
        ...
        query_raw: str = Field(required=False)
        ...
        provider: str = Field(required=False, default='db')
        ...
            name = QS_QUERIES_TABLE
            schema = QS_QUERIES_SCHEMA
- path: `venv:querysource/conf.py`
  lines: 353-354
  symbol: `QS_QUERIES_SCHEMA`
  excerpt: |
    QS_QUERIES_SCHEMA = config.get('QS_QUERIES_SCHEMA', fallback='public')
    QS_QUERIES_TABLE = config.get('QS_QUERIES_TABLE', fallback='queries')
- path: `venv:querysource/repositories/definitions.py`
  lines: 124
  symbol: `DefinitionRepository._fetch_row`
  excerpt: |
    sql = f"SELECT * FROM {table} WHERE query_slug = $1 LIMIT 1"
- path: `venv:querysource/tenants.py`
  lines: 197-205
  symbol: `TenantRegistry.discover`
  excerpt: |
    # Query information_schema for tables named 'queries'
    ...
    FROM information_schema.tables
    WHERE table_name = 'queries'
    AND table_type = 'BASE TABLE'
- path: `venv:querysource/services.py`
  lines: 234-236
  symbol: `QuerySource.setup`
  excerpt: |
    r = self.app.router.add_view(
        r'/api/v1/management/queries/{slug}', QueryManager
    )
- path: `venv:querysource/handlers/manager.py`
  lines: 671-674
  symbol: `QueryManager.put`
  excerpt: |
    async def put(self):
        """"
        put.
           summary: insert (or modify) a query slug
## Implications
- The example can "ship" an extra slug (e.g. `polestar_graduates_by_course` with a lateral `jsonb_array_elements` query_raw, F014) only as data: an idempotent seed step (SQL upsert, or `PUT /api/v1/management/queries/{slug}` at startup/setup script). That writes to a shared DB — it is not dependency-free, and needs write permission on the queries table.
- Whether `polestar_graduates_directory` lives in `public.queries` or a tenant schema (the brief mentions `troc.queries`) decides the URL: `/api/v2/services/queries/{slug}` vs `/api/v1/troc/queries/{slug}`. Not verified — a read-only DB lookup was denied in this lane (open unknown).
