---
id: F007
query_id: Q006
type: read
intent: Locate the JSON filtering dialect — how conditions/filter/fields/ordering/limit are parsed.
executed_at: 2026-09-15T02:47:00Z
duration_ms: 9000
parent_id: null
depth: 1
---
# F007 — The QuerySource conditions dialect (parsers are compiled; source fetched from GitHub `dev`)
## Summary
The installed wheel ships `querysource/parsers/*.cpython-312-*.so` + `.pxd` only (no `.py`/`.pyx`), so the dialect was read from `abstract.pyx`/`sql.pyx` on GitHub branch `dev` (`main` also 200; `master` 404) — **version drift vs 4.5.11 is possible**; the `.pxd` confirms the same attribute/method set. The request `conditions` dict is a *mixed bag*: reserved option keys are popped first, remaining keys become either placeholder substitutions (when present in `cond_definition`) or WHERE filters. Merge order for placeholders: `{**definition.conditions, **conditions, **conditions['conditions']}` — a nested `"conditions": {...}` key is accepted (matches the user's example). Values starting with `@fn` call app-registered variable functions (`QS_VARIABLES`, populated from the *deploying app's* `settings.settings.QUERYSOURCE_VARIABLES` — not part of the library).
Option keys: `fields` (list), `_limit`/`querylimit` (int), `_offset`, `paged`, `page`, `group_by`/`grouping` (list or CSV str), `order_by`/`ordering`, `filter_options`, `qry_options`, `where_cond`/`filter` (dict), `refresh` (bool), `hierarchy`, `distinct`, `add_fields`, `tablename`/`schema`/`database`, `slug`.
WHERE value grammar (SQLParser): scalar → `key = 'v'`; `"!v"` or key suffix `!` → `!=`; list → `IN (...)` (`key!` → `NOT IN`); `[op, v]` with op ∈ `('<','>','>=','<=','<>','!=','IS NOT','IS')`; `{op: v}` with op ∈ `('>=','<=','<>','!=','<','>')`; string containing `BETWEEN` → `(key BETWEEN a AND b)`; `"null"`/`"!null"` → `IS NULL`/`IS NOT NULL`; bool literal. Keys must be identifier-safe (`[A-Za-z0-9_.]` after stripping suffix chars `|!~#@:`); unsafe keys/operators are silently dropped.
## Citations
- path: `.venv/lib/python3.12/site-packages/querysource/parsers/abstract.pxd`
  lines: 9-76
  symbol: `AbstractParser`
  excerpt: |
    cdef public dict filter; cdef public dict filter_options; cdef public list fields
    cdef public list ordering; cdef public list grouping; cdef public str program_slug
    cdef public int querylimit; cdef public dict cond_definition; cdef public dict _conditions
    cdef void _query_limit_sync(self); _offset_pagination_sync; _grouping_sync; _ordering_sync; _query_filter_sync
- path: `https://raw.githubusercontent.com/phenobarbital/querysource/dev/querysource/parsers/abstract.pyx`
  lines: 156-290
  symbol: `AbstractParser._extract_options` helpers
  excerpt: |
    self._hierarchy = self.conditions.pop('hierarchy', [])
    refresh = self.conditions.pop('refresh', False)
    self.fields = self.conditions.pop('fields', [])
    self.querylimit = int(self.conditions.pop('_limit', 0)) or int(self.conditions.pop('querylimit', 0))
    self._offset = self.conditions.pop('_offset', 0); paged = self.conditions.pop('paged', False); self._page_ = self.conditions.pop('page', 0)
    group_by / grouping ; order_by / ordering  (str → split(','))
    self.filter = self.conditions.pop('where_cond', {}) or self.conditions.pop('filter', {}) or self.definition.filtering
- path: `https://raw.githubusercontent.com/phenobarbital/querysource/dev/querysource/parsers/abstract.pyx`
  lines: 380-410
  symbol: `AbstractParser.set_options`
  excerpt: |
    self._distinct = bool(self.conditions.pop('distinct', False)); self._add_fields = self.conditions.pop('add_fields', False)
    params = conditions.pop('conditions', {})
    conditions = {**def_conditions, **conditions, **params}
- path: `https://raw.githubusercontent.com/phenobarbital/querysource/dev/querysource/parsers/abstract.pyx`
  lines: 474-527
  symbol: `AbstractParser._process_element`, `set_conditions`
  excerpt: |
    if key in self.cond_definition: ... self._conditions[key] = is_valid(key, value, _type)   # placeholder
    else: _filter[key] = value                                                                 # becomes WHERE
    # '@fn' string values → QS_VARIABLES[fn](key, val)
- path: `https://raw.githubusercontent.com/phenobarbital/querysource/dev/querysource/parsers/sql.pyx`
  lines: 25, 96, 113-235
  symbol: `COMPARISON_TOKENS`, `SQLParser.valid_operators`, `SQLParser.filter_conditions`
  excerpt: |
    COMPARISON_TOKENS = ('>=', '<=', '<>', '!=', '<', '>',)
    self.valid_operators = ('<', '>', '>=', '<=', '<>', '!=', 'IS NOT', 'IS')
    dict value → {op: v}; list → [op, v] or IN(...); "BETWEEN" str; 'null'/'!null'; key end '!' → NOT IN / !=
- path: `.venv/lib/python3.12/site-packages/querysource/services.py`
  lines: 29-33, 94-96
  excerpt: |
    try: from settings.settings import QUERYSOURCE_FILTERS, QUERYSOURCE_VARIABLES
    except ImportError: QUERYSOURCE_FILTERS = {}; QUERYSOURCE_VARIABLES = {}
    for name, fn in QUERYSOURCE_VARIABLES.items(): QS_VARIABLES[name] = func
- path: `.venv/lib/python3.12/site-packages/querysource/parsers/__init__.py`
  lines: 6
  excerpt: QS_VARIABLES = {}
## Notes
A Rust fast path (`qs_parsers/_qs_parsers.so`, `HAS_RUST`) implements the same WHERE builder; grammar parity is asserted by the library, not verified here. The dialect reference the toolkit ships to the LLM should be generated from this finding and re-verified at spec time against the pinned querysource version.

## Addendum (2026-09-15, /sdd-spec)
GitHub tag `4.5.11` exists (`git ls-remote --tags`) and its `querysource/parsers/abstract.pyx` and `parsers/sql.pyx`
are byte-identical to the `dev` copies cited above (`diff -q`). The dialect is therefore verified against the
installed wheel version, not just `dev`; confidence for claim C4 rises to high.
