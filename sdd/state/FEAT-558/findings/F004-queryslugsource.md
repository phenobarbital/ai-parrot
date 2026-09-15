---
id: F004
query_id: Q004
type: read
intent: Read QuerySlugSource / MultiQuerySlugSource — the other in-repo QS() consumer.
executed_at: 2026-09-15T02:43:00Z
duration_ms: 1200
parent_id: null
depth: 0
---
# F004 — QuerySlugSource: permanent_filter precedence and a patchable QS import
## Summary
`QuerySlugSource(DataSource)` wraps `QS(slug=..., conditions=params)` and always requests `output_format='pandas'`. It supports a `permanent_filter` that **overrides** runtime params (`{**params, **self._permanent_filter}`), maps `force_refresh`→`conditions['refresh']=True`, and prefetches schema with `{"querylimit": 1}`. `MultiQuerySlugSource` is *not* MultiQuery — it just concatenates several slugs. The module-level `QS = None` + `_get_qs()` pattern makes the import patchable in tests.
## Citations
- path: `packages/ai-parrot/src/parrot/tools/dataset_manager/sources/query_slug.py`
  lines: 19-33
  symbol: `_get_qs`
  excerpt: |
    QS = None  # Module-level variable so names are patchable in tests.
    def _get_qs(): ... _qs_mod = lazy_import("querysource.queries.qs", package_name="querysource", extra="db")
- path: `packages/ai-parrot/src/parrot/tools/dataset_manager/sources/query_slug.py`
  lines: 122-162
  symbol: `QuerySlugSource.fetch`
  excerpt: |
    force_refresh = params.pop('force_refresh', False)
    if force_refresh: params['refresh'] = True
    merged = {**params, **self._permanent_filter}   # permanent filter wins
    qy = qs_cls(slug=self.slug, conditions=merged)
    df, error = await qy.query(output_format='pandas')
- path: `packages/ai-parrot/src/parrot/tools/dataset_manager/sources/query_slug.py`
  lines: 165-198
  symbol: `MultiQuerySlugSource`
  excerpt: "Fetches each slug independently and concatenates the resulting DataFrames." (cache_key multiqs:{slugs})
