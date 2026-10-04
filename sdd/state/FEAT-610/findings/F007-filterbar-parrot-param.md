---
id: F007
query_id: Q007
type: read
intent: Understand FilterBar parrot_param and its role in re-querying (filterable grid)
executed_at: 2026-09-28T18:21:51Z
parent_id: null
depth: 0
---
# F007 — FilterBar `parrot_param`: filter ⇒ re-fetch ("Reload") vs local filter
## Summary
A FilterBar filter may carry `param: {"source", "name"}`; lowering puts `parrot_param` on the generated
`ChoicePicker`'s `metadata.extensions` (next to `parrot_filter_column`). In the renderer, a filter with
`parrot_param` re-fetches that source with the placeholder overridden (`setParam`); filters without it filter the
embedded rows locally. Docs distinguish Filter (local), Reload (`parrot_param` re-fetch) and Refresh (server lane
`POST …/ui/surfaces/{id}/refresh`). `locked` params are ignored (UX hint only, not security).
## Citations
- path: `packages/ai-parrot/src/parrot/outputs/a2ui/catalog/parrot/filterbar.py`
  lines: 102, 115
  symbol: `FilterBarComponent.lower`
  excerpt: |
    param: Optional {"source", "name"} (FEAT-598) — lowered to parrot_param.
    extensions["parrot_param"] = {"source": param["source"], "name": param["name"]}
- path: `docs/outputs/a2ui-v1.md`
  lines: 157-158
  symbol: `-`
  excerpt: |
    | `parrot_data_sources` | **Surface-level** (`createSurface.metadata.extensions`, FEAT-598): linked data-source descriptors ...
    | `parrot_param` | On a `FilterBar` filter / its lowered `ChoicePicker` (FEAT-598): `{"source": "<key>", "name": "<param>"}` — changing the filter re-fetches that source instead of filtering locally |
- path: `docs/frontend/agentdashboard-a2ui-reference.md`
  lines: 751-753, 825
  symbol: `-`
  excerpt: |
    ### 6.5 Linked surfaces (FEAT-598)
    9. **Filter vs Refresh vs Reload (FEAT-598)**: *Filter* is local over embedded rows (items 1-8); a filter carrying
    `parrot_param` is a **Reload** — it re-fetches its linked source from QuerySource with the new param (§6.5); ...
## Implications
- `parrot_param` only overrides **placeholders** (setParam merges into `request.placeholders`), not arbitrary `filter` columns — a "filterable grid" over 17k rows is either client-side filtering (grid.js search) or requires the slug to expose placeholders for the filter columns.
- The FEAT-610 renderer can treat FilterBar as optional; the grid.js built-in search/pagination covers local filtering.
