---
id: F005
query_id: Q005
type: read
intent: Extract the QS() constructor/execution contract from installed querysource 4.5.11.
executed_at: 2026-09-15T02:44:00Z
duration_ms: 3000
parent_id: null
depth: 0
---
# F005 — QS() contract: slug | query+driver | raw_query; conditions merge; `program` is accepted but ignored
## Summary
`QS(BaseQuery)` in `querysource/queries/qs.py` (536 lines, installed 4.5.11) takes `slug=''`, `conditions=None`, `request=None`, `loop=None`, `**kwargs` where kwargs may carry `query`+`driver`, `raw_query`, `driver` alone, `lazy`, `dwh`. `build_provider()` for a slug calls `connection.get_slug(slug, program=self._program)`, then merges `{**objquery.conditions, **self._conditions}` (caller conditions override the stored defaults) and instantiates the provider. `query(output_format)` lazily builds the provider and returns `(result, error)`; `dry_run()` returns `[result, error]` without executing; `close()` disposes the connection. **`get_slug()` ignores `program`** — it resolves by `query_slug` primary key only, so tenancy is not enforced inside QS.
## Citations
- path: `.venv/lib/python3.12/site-packages/querysource/queries/qs.py`
  lines: 42-99
  symbol: `QS.__init__`
  excerpt: |
    def __init__(self, slug: str = '', conditions: dict = None, request: web.Request = None,
                 loop: asyncio.AbstractEventLoop = None, **kwargs):
        if 'dwh' in conditions: self._dwh = conditions.pop('dwh')
        if slug: self._query = slug; self._type = 'slug'
        elif 'query' in self.kwargs: self._query = kwargs.pop('query'); self._driver = kwargs.pop('driver', 'db'); self._type = 'query'
        elif 'raw_query' in self.kwargs: ... self._type = 'raw'
        lazy = kwargs.pop('lazy', True)
- path: `.venv/lib/python3.12/site-packages/querysource/queries/qs.py`
  lines: 163-233
  symbol: `QS.build_provider`
  excerpt: |
    objquery = await self.connection.get_slug(self._query, program=self._program)
    self._conn, self._provider = await self.connection.get_provider(objquery, session=_pbac_session, app=_pbac_app)
    self.is_cached = objquery.is_cached; self.timeout = objquery.cache_timeout
    conditions = {**objquery.conditions, **self._conditions}   # caller overrides stored defaults
    self._qs = self._provider(slug=..., definition=objquery, conditions=conditions, request=..., loop=...)
- path: `.venv/lib/python3.12/site-packages/querysource/queries/qs.py`
  lines: 363-376
  symbol: `QS.query`
  excerpt: |
    async def query(self, output_format: Optional[str] = None):
        if not self._qs: await self.build_provider()
        ... return await self._output_format(self._result, error)   # -> (result, error)
- path: `.venv/lib/python3.12/site-packages/querysource/queries/qs.py`
  lines: 519-536
  symbol: `QS.close`, `QS.dry_run`
  excerpt: |
    async def dry_run(self):
        if not self._qs: await self.build_provider()
        result, error = await self._qs.dry_run(); return [result, error]
- path: `.venv/lib/python3.12/site-packages/querysource/interfaces/connections.py`
  lines: 494-506
  symbol: `QueryConnection.get_slug`
  excerpt: |
    async def get_slug(self, slug: str, program: str = None, evt=None):
        obj = await self.get_query_slug(slug, evt=evt)      # `program` never used
        if obj is None: raise SlugNotFound(f'Slug \'{slug}\' not found')
- path: `.venv/lib/python3.12/site-packages/querysource/interfaces/connections.py`
  lines: 444-480
  symbol: `QueryConnection.get_query_slug`
  excerpt: |
    async with await db.connection() as conn:
        return await QueryModel.get(query_slug=slug, _connection=conn)
    except ValidationError as ex: raise SlugNotFound(...)
## Notes
Exceptions worth mapping in the toolkit: `SlugNotFound`, `QueryException`, `EmptySentence`, `DataNotFound` (all in `querysource.exceptions`). `QS.dry_run()` is the cheapest "what would this slug run" probe.
