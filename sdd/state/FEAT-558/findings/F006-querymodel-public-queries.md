---
id: F006
query_id: Q011
type: grep
intent: Find the public.queries model (QueryModel) and the program_slug tenant attribute.
executed_at: 2026-09-15T02:45:00Z
duration_ms: 1200
parent_id: null
depth: 0
---
# F006 — QueryModel maps `public.queries`; `program_slug` is a plain column with default 'default'
## Summary
`QueryModel(Model)` (datamodel/asyncdb, `Meta.driver='pg'`, name/schema from `QS_QUERIES_TABLE`/`QS_QUERIES_SCHEMA` → `public.queries`) has PK `query_slug` and columns: `description`, `source`, `params`, `attributes`, `conditions` (default values for placeholders), `cond_definition` (per-condition types), `fields`, `filtering`, `ordering`, `grouping`, `qry_options`, `h_filtering`, `query_raw`, `is_raw`, `is_cached`, `provider` (default 'db'), `parser` (default 'SQLParser'), `cache_timeout`, `cache_refresh`, `cache_options`, `program_id`, `program_slug` (required, default 'default'), `dwh*`, audit fields. Nothing in the library filters by `program_slug` when resolving a slug; tenancy must be checked by the caller after loading the row.
## Citations
- path: `.venv/lib/python3.12/site-packages/querysource/models.py`
  lines: 48-110
  symbol: `QueryModel`
  excerpt: |
    class QueryModel(Model):
        query_slug: str = Field(required=True, primary_key=True)
        conditions: Optional[dict] = Field(db_type='jsonb', default_factory=dict)
        cond_definition: Optional[dict] = Field(db_type='jsonb', default_factory=dict)
        fields: List[str]; filtering: Optional[dict]; ordering: List[str]; grouping: List[str]
        query_raw: str; is_raw: bool; is_cached: bool = True; provider: str = 'db'; parser: str = 'SQLParser'
        program_id: int = 1; program_slug: str = Field(required=True, default='default')
        class Meta: driver = 'pg'; name = QS_QUERIES_TABLE; schema = QS_QUERIES_SCHEMA
- path: `.venv/lib/python3.12/site-packages/querysource/models.py`
  lines: 24-45
  symbol: `QueryObject`
  excerpt: option keys: source, driver, conditions, coldef, fields, ordering, group_by, qry_options, filter, where_cond, and_cond, hierarchy, querylimit, _limit, _offset, query_raw
- path: `.venv/lib/python3.12/site-packages/querysource/conf.py`
  lines: 353-354
  excerpt: |
    QS_QUERIES_SCHEMA = config.get('QS_QUERIES_SCHEMA', fallback='public')
    QS_QUERIES_TABLE = config.get('QS_QUERIES_TABLE', fallback='queries')
