---
id: F011
query_id: Q011
type: read
intent: HTTP route + handler for executing a query-slug with a JSON payload
executed_at: 2026-09-28T20:30:00Z
parent_id: null
depth: 0
---
# F011 — `POST /api/v2/services/queries/{slug}` → `QueryService.query`; JSON body and query-string are merged into one `conditions` dict
## Summary
`QuerySource.setup()` registers `GET|POST /api/v2/services/queries/{slug}` (plus HEAD for columns, PATCH for columns) bound to `QueryService.query` (`querysource/handlers/service.py`). The handler reads the JSON body (`self.json_data`) AND the URL query parameters and merges them as `conditions = {**options, **params}` (query-string wins). The slug path segment may carry an output format suffix `slug:format` (e.g. `polestar_graduates_directory:json`); `?queryformat=` also selects the writer, JSON is the default. Tenant-scoped variants exist at `/api/v1/{tenant}/queries/{slug}` and the multi-query pipeline endpoint at `/api/v3/queries/{slug}` (`QueryHandler.query`). Empty results come back as HTTP 204 with `x-status: Empty Result`; SQL errors as 400/404 with `x-status`/`x-message` headers.
## Citations
- path: `venv:querysource/services.py`
  lines: 181-189
  symbol: `QuerySource.setup`
  excerpt: |
    r = self.app.router.add_get('/api/v2/services/queries/{slug}', qs.query, allow_head=False)
    r = self.app.router.add_post('/api/v2/services/queries/{slug}', qs.query)
    r = self.app.router.add_patch('/api/v2/services/queries/{slug}', qs.columns)
    r = self.app.router.add_head('/api/v2/services/queries/{slug}', qs.get_columns)
- path: `venv:querysource/handlers/service.py`
  lines: 164-175
  symbol: `QueryService.query`
  excerpt: |
    params = self.query_parameters(request)
    args = self.match_parameters(request)
    ...
        options = await self.json_data(request)
    ...
        slug: str = args['slug']
        try:
            slug, _format = slug.split(':')
- path: `venv:querysource/handlers/service.py`
  lines: 294-295
  symbol: `QueryService.query`
  excerpt: |
    # get conditions
    conditions = {**options, **params}
- path: `venv:querysource/services.py`
  lines: 245-248
  symbol: `QuerySource.setup`
  excerpt: |
    r = self.app.router.add_post(
        r'/api/v3/queries/{slug}{meta:\:?.*}',
        mq.query
    )
- path: `venv:querysource/outputs/output.py`
  lines: 237-240
  symbol: `DataOutput.response`
  excerpt: |
    except (NoDataFound, DataNotFound) as err:
        ...
        headers = {
            'x-status': 'Empty Result',
## Implications
- Browser refresh = `fetch('/api/v2/services/queries/polestar_graduates_directory', {method:'POST', headers:{Authorization:'Bearer '+tok,'Content-Type':'application/json'}, body: JSON.stringify(payload)})`. Use POST: nested `filter` dicts cannot be expressed cleanly in the query-string.
- Renderer must treat 204 as "zero rows", not an error.
