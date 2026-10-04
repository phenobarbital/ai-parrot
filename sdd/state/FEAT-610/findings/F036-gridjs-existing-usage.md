---
id: F036
query_id: Q030
type: grep
intent: Existing grid.js usage (not A2UI) that the renderer can borrow
executed_at: 2026-09-28T18:24:17Z
parent_id: null
depth: 0
---
# F036 — grid.js exists only in legacy TABLE output mode and the interactive-toolkit library catalog (SRI placeholder)
## Summary
grid.js is not used by any A2UI renderer (Python or Svelte). It appears in (1) the legacy `OutputMode.TABLE` formatter `TableRenderer`, which builds `new gridjs.Grid({columns, data})` from a DataFrame as list-of-lists and loads gridjs from **unpkg** (unpinned) in its HTML document; and (2) the interactive-artifact toolkit's library catalog `gridjs.md` pinning gridjs@6.2.0 on jsDelivr, but whose `sri_hash`/`css_sri_hash` are **placeholders** (`sha384-REGENERATEME...`). No gridjs npm dependency exists in the admin UI package.json.
## Citations
- path: `packages/ai-parrot/src/parrot/outputs/formats/table.py`
  lines: 51-52, 127-140
  symbol: `TableRenderer._generate_gridjs_code`
  excerpt: |
    @register_renderer(OutputMode.TABLE, system_prompt=GRIDJS_SYSTEM_PROMPT)
    class TableRenderer(BaseRenderer):
    def _generate_gridjs_code(self, df: pd.DataFrame, element_id: str = "wrapper") -> str:
        columns = df.columns.tolist()
        data = df.values.tolist()
            new gridjs.Grid({{ columns: {json_columns}, data: {json_data},
- path: `packages/ai-parrot/src/parrot/outputs/formats/table.py`
  lines: 181-182
  symbol: `-`
  excerpt: |
    <link href="https://unpkg.com/gridjs/dist/theme/mermaid.min.css" rel="stylesheet" />
    <script src="https://unpkg.com/gridjs/dist/gridjs.umd.js" defer></script>
- path: `packages/ai-parrot/src/parrot/tools/interactive/catalog/libraries/gridjs.md`
  lines: 1-10
  symbol: `-`
  excerpt: |
    name: gridjs
    url: https://cdn.jsdelivr.net/npm/gridjs@6.2.0/dist/gridjs.umd.js
    sri_hash: sha384-REGENERATEMEREGENERATEMEREGENERATEMEREGENERATEMEREGENERATEME
    css_url: https://cdn.jsdelivr.net/npm/gridjs@6.2.0/dist/theme/mermaid.min.css
    global_var: gridjs
## Implications
- The example should pin gridjs@6.2.0 (consistent with the catalog) and compute real SRI hashes; do not copy the placeholder.
- Map DataTable `columns[{name,title,type,format}]` → grid.js `columns[{id:name, name:title||name, formatter}]` and feed row objects (grid.js accepts objects when columns carry `id`), with `pagination`, `search`, `sort` enabled; 17k rows client-side is within grid.js's comfort zone, and `grid.updateConfig({data}).forceRender()` is the refresh path.
- FilterBar filters (local, non-`param`) must pre-filter the row array before `updateConfig`, since grid.js search is free-text only.
