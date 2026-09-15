---
id: F003
query_id: Q003
type: read
intent: Read parrot_tools/querytoolkit.py — an existing toolkit over querysource that may shape the refactor.
executed_at: 2026-09-15T02:42:00Z
duration_ms: 1500
parent_id: null
depth: 0
---
# F003 — QueryToolkit: an AbstractToolkit base with a `program` attribute and a QS slug helper
## Summary
`QueryToolkit(AbstractToolkit)` (401 lines) is a base for DB-query toolkits: holds `default_dsn` (from `querysource.conf`), `schema`, `driver`, `program` (exposed as `program_slug` property), `agent_id`, an `AsyncDB` handle, and helpers `_fetch_one`, `_get_dataset`, `_get_queryslug(slug, output_format, conditions, structured_obj)` — the latter builds `QS(slug=slug, conditions=conditions)` and calls `query()` **without** `build_provider()` (QS.query() calls it lazily). It has no LLM-facing tools itself; subclasses `PricesTool` and `EpsonProductToolkit` add them. It uses `print()` (line 306) and does not enforce `program` on QS calls — `program` only selects prompt/query file paths.
## Citations
- path: `packages/ai-parrot-tools/src/parrot_tools/querytoolkit.py`
  lines: 89-137
  symbol: `QueryToolkit.__init__`
  excerpt: |
    def __init__(self, dsn=None, schema=None, credentials=None, driver='pg',
                 program: Optional[str] = '', agent_id=None, **kwargs):
        _qs_conf = lazy_import("querysource.conf", package_name="querysource", extra="db")
        self.default_dsn = dsn or _qs_conf.default_dsn
        self.program = program
- path: `packages/ai-parrot-tools/src/parrot_tools/querytoolkit.py`
  lines: 140-144
  symbol: `QueryToolkit.program_slug`
  excerpt: |
    @property
    def program_slug(self) -> str: return self.program
- path: `packages/ai-parrot-tools/src/parrot_tools/querytoolkit.py`
  lines: 335-401
  symbol: `QueryToolkit._get_queryslug`
  excerpt: |
    _qs_mod = lazy_import("querysource.queries.qs", package_name="querysource", extra="db")
    qs = _qs_mod.QS(slug=slug, conditions=conditions)
    result, error = await qs.query()
    if error: raise ToolError(f"Error executing query '{slug}': {error}")
- path: `packages/ai-parrot-tools/src/parrot_tools/pricestool.py`
  lines: 45
  symbol: `PricesTool(QueryToolkit)`
- path: `packages/ai-parrot-tools/src/parrot_tools/epson/__init__.py`
  lines: 55
  symbol: `EpsonProductToolkit(QueryToolkit)`
## Notes
`QueryToolkit` is a *base class for per-program SQL toolkits*, not a generic QuerySource surface. The new toolkit should not subclass it (it eagerly builds an `AsyncDB` in `__init__`), but its `program` naming is the in-repo precedent for "tenant".
