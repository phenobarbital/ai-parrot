---
id: F008
query_id: Q007
type: read
intent: Read the MultiQuery entrypoint (MultiQS) — pipeline JSON contract and execution API.
executed_at: 2026-09-15T02:48:00Z
duration_ms: 2500
parent_id: null
depth: 0
---
# F008 — MultiQS: pipeline = {queries|files|sources} + operator steps + Output; a saved slug is a queries row whose query_raw is the JSON
## Summary
`MultiQS(BaseQuery)` accepts `slug`, `queries`, `files`, `query=<pipeline dict>`, `conditions`, `user_session`, `return_all`. With `query=` it pops `queries`/`files`/`sources` out of the dict and keeps the remaining keys as `_options` (the steps). `query()`: if `slug` is given it loads the row via `get_slug()`; when `query_raw` parses as JSON containing `queries|files|sources` it runs it as a pipeline (this is how a multi-query is *registered*: a `public.queries` row with JSON in `query_raw`); otherwise it wraps the single slug. Steps run in fixed order: `Info` → `Join` → `Concat` → `Melt` → `Merge` → `Output` list (transformations by name via `get_transform_module`, `GroupBy`, `Filter`) → destinations via `outputs.destinations.get_destination`. Returns `(result, options)`; `execute()` aliases `query()`. Raises `DriverError` when slug/queries/files/sources are all empty.
## Citations
- path: `.venv/lib/python3.12/site-packages/querysource/queries/multi/__init__.py`
  lines: 56-113
  symbol: `MultiQS.__init__`
  excerpt: |
    def __init__(self, slug=None, queries=None, files=None, query: Optional[dict]=None, conditions=None,
                 request=None, loop=None, user_session=None, **kwargs):
        self._options: dict = query or {}
        if query: self._queries = query.pop('queries', {}); self._files = query.pop('files', {}); raw_sources = query.pop('sources', [])
        if not (self.slug or self._queries or self._files or self._sources): raise DriverError('Invalid Options passed to MultiQuery...')
- path: `.venv/lib/python3.12/site-packages/querysource/queries/multi/__init__.py`
  lines: 166-200
  symbol: `MultiQS.query`
  excerpt: |
    if self.slug:
        query = await self.get_slug(slug=self.slug)
        slug_data = self._encoder.load(query.query_raw)          # JSON pipeline stored in query_raw
        if isinstance(slug_data, dict) and ('queries' in slug_data or 'files' in slug_data or 'sources' in slug_data):
            self._options = slug_data; self._queries = slug_data.pop('queries', {}) ...
        else:  # Single-query slug: wrap it
            self._queries = {self.slug: {"slug": self.slug, **slug_conditions}}
- path: `.venv/lib/python3.12/site-packages/querysource/queries/multi/__init__.py`
  lines: 356-540
  excerpt: |
    ### Step 2: Info / Join / Concat / Melt / Merge  (get_operator_module(name); self._options.pop(name))
    # Step 3: _output = self._options.pop('Output', None)  → transformations (get_transform_module), GroupBy, Filter
    ### Step 5: saving result to destination (registry-based dispatch): get_destination(step_name)
- path: `.venv/lib/python3.12/site-packages/querysource/queries/multi/__init__.py`
  lines: 553-557
  symbol: `MultiQS.execute`
