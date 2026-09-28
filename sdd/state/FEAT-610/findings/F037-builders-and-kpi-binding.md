---
id: F037
query_id: Q031
type: read
intent: Python builders for dashboard surfaces and how KPICard binds to a linked source
executed_at: 2026-09-28T18:24:17Z
parent_id: null
depth: 0
---
# F037 — builders.py: build_surface/build_chart/build_kpicard/build_datatable + build_linked_surface binding rules
## Summary
`builders.py` offers single-component builders (`build_chart`, `build_kpicard`, `build_datatable`, all via `build_surface`, LLM-origin validation by default, rejecting inlined rows) and the FEAT-598 `build_linked_surface(components, sources, frames, *, surface_id, snapshot=True, max_snapshot_rows=500)` which takes free-form component dicts, validates their axes against pandas frames, and writes each source's snapshot to `dataModel[<key>] = {"rows": [...]}` (capped at 500 rows, `snapshot_truncated` flag). Recognised bindings: Chart/DataTable `data: {"path": "/<key>/rows"}`; KPICard `value: {"path": "/<key>/rows/0/<column>"}` (single-row KPI source, first row's column). Chart y columns must be numeric dtypes.
## Citations
- path: `packages/ai-parrot/src/parrot/outputs/a2ui/builders.py`
  lines: 129-167
  symbol: `build_chart`, `build_kpicard`
  excerpt: |
    def build_chart(*, chart_type: str, x: str, y: Sequence[str], title=None, data_binding=None, ...)
    def build_kpicard(*, label: str, value: Any, unit=None, delta=None, trend=None, surface_id="kpi")
- path: `packages/ai-parrot/src/parrot/outputs/a2ui/builders.py`
  lines: 460-476
  symbol: `_rows_key`
  excerpt: |
    tokens = path[1:].split("/")
    if len(tokens) < 2 or tokens[1] != "rows" or tokens[0] not in sources:
        return None
    if len(tokens) == 2:
        return tokens[0], None
    if len(tokens) == 4 and tokens[2] == "0":
        return tokens[0], tokens[3]
- path: `packages/ai-parrot/src/parrot/outputs/a2ui/builders.py`
  lines: 514-523, 543-545
  symbol: `build_linked_surface`
  excerpt: |
    def build_linked_surface(components, sources, frames, *, surface_id: str,
        snapshot: bool = True, max_snapshot_rows: int = 500, catalog_id: str = DEFAULT_CATALOG_ID) -> CreateSurface:
    rows = json.loads(frame.head(max_snapshot_rows).to_json(orient="records", date_format="iso"))
    snapshot_truncated = len(frame) > max_snapshot_rows
## Implications
- KPI hero cards should each bind to a tiny aggregate source (e.g. `total_count` with one row) via `/<key>/rows/0/<col>`; the renderer resolves the pointer after each refresh.
- The 17k-row grid source will be snapshot-truncated to 500 rows in `dataModel` by default; the renderer must fetch the full set live (on_mount) — or the example must raise `max_snapshot_rows`/use `snapshot=False`.
- Charts by country/licensee/course are best served by QuerySource-side `group_by` count sources (small rows), not by client aggregation of the 17k rows; alternatively a `transform` DSL op (Lane A) could aggregate client-side.
