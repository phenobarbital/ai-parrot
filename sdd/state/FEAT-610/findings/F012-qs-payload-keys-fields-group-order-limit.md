---
id: F012
query_id: Q012
type: read
intent: Semantics of slug payload keys (fields, group_by, ordering, _limit/_offset, paged)
executed_at: 2026-09-28T20:30:00Z
parent_id: null
depth: 0
---
# F012 — Payload keys: `fields` (raw SQL fragments), `group_by`/`grouping`, `ordering`/`order_by`, `_limit`/`querylimit`, `_offset`; `paged`/`page` are parsed but unused
## Summary
The parser pops reserved keys out of the merged conditions (source read from the sibling checkout `../querysource` v5.1.1, since the installed wheel ships only compiled `.so`): `fields` (list), `_limit` then `querylimit`, `_offset`, `paged`/`page`, `group_by` + `grouping` (list or comma string, concatenated), `order_by` + `ordering`, `where_cond` then `filter`, plus `distinct`, `add_fields`, `filter_options`, `qry_options`. `fields` is joined verbatim into the SELECT list — it replaces ` * FROM` / `{fields}` in the slug's `query_raw`, with **no identifier validation** — so aggregates and aliases like `count(*) as graduates` (and arbitrary SQL expressions) work, but only if the slug SQL is `SELECT * FROM ...` or uses `{fields}`. `group_by` appends `GROUP BY <cols>` (or extends an existing outer GROUP BY); ordering appends `ORDER BY`; limit/offset append `LIMIT n OFFSET m`. `paged`/`page` are stored (`is_paged()`) but nothing consumes them — there is no server-side page envelope/total count for slug data; pagination = `_limit`/`_offset` + a separate `count(*)` call.
## Citations
- path: `../querysource/querysource/parsers/abstract.pyx`
  lines: 199-234
  symbol: `AbstractParser._query_fields_sync / _query_limit_sync / _offset_pagination_sync`
  excerpt: |
    self.fields = self.conditions.pop('fields', [])
    ...
    self.querylimit = int(self.conditions.pop('_limit', 0))
    if not self.querylimit:
        self.querylimit = int(self.conditions.pop('querylimit', 0))
    ...
    self._offset = self.conditions.pop('_offset', 0)
    ...
    paged = self.conditions.pop('paged', False)
- path: `../querysource/querysource/parsers/abstract.pyx`
  lines: 237-258
  symbol: `AbstractParser._grouping_sync`
  excerpt: |
    group1 = self.conditions.pop('group_by', [])
    ...
    group2 = self.conditions.pop('grouping', [])
    ...
    self.grouping = (group1 or []) + (group2 or [])
- path: `../querysource/querysource/parsers/sql.pyx`
  lines: 328-351
  symbol: `SQLParser.process_fields`
  excerpt: |
    if isinstance(self.fields, list) and len(self.fields) > 0:
        ...
        sql = sql.replace(' * FROM', ' {fields} FROM')
        fields = ', '.join(self.fields)
        sql = sql.format_map(SafeDict(fields=fields))
- path: `../querysource/querysource/parsers/sql.pyx`
  lines: 356-395
  symbol: `SQLParser.build_query`
  excerpt: |
    sql = await self.process_fields(sql)
    ...
    sql = await self.filter_conditions(sql)
    # processing conditions
    sql = await self.group_by(sql)
    if self.ordering:
        sql = await self.order_by(sql)
    if querylimit: ...
        sql = sql.format_map(SafeDict(**self._conditions))
- path: `../querysource/querysource/parsers/abstract.pyx`
  lines: 124-130
  symbol: `AbstractParser.is_paged`
  excerpt: |
    cpdef bint is_paged(self):
        """Return whether pagination was requested (parsed ``paged`` condition).
## Implications
- `{ "fields": ["count(*)"] }`, `{ "fields": ["country","count(*) as graduates"], "group_by": ["country"] }` and the licensee variant are directly expressible (assuming the slug's `query_raw` is `SELECT * FROM ...`/`{fields}` — must be verified against the live `polestar_graduates_directory` definition, not done here).
- Grid: server-side pages via `{"_limit": 50, "_offset": N, "ordering": ["last_name"], "filter": {...}}` + a parallel `{"fields":["count(*)"], "filter": {...}}` for the total; grid.js `server` mode fits this.
- Leftover (non-reserved) keys become `{placeholder}` substitutions into `query_raw` (`format_map(SafeDict(**self._conditions))`), i.e. a slug SQL may define its own named placeholders.
