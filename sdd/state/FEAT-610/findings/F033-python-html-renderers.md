---
id: F033
query_id: Q030
type: read
intent: Existing Python-side A2UI→HTML renderers and their chart libraries
executed_at: 2026-09-28T18:24:17Z
parent_id: null
depth: 0
---
# F033 — Python renderers: interactive-html (Chart.js, static snapshot), echarts (option JSON / single-chart HTML), ssr_html
## Summary
`ai-parrot-visualizations` registers A2UI renderers under `parrot.outputs.a2ui_renderers` via `register_a2ui_renderer`; resolve with `get_a2ui_renderer(name)` and `await Renderer().render(create_surface)` → `RenderedArtifact` (bytes). **interactive-html** emits ONE self-contained HTML page with **vendored Chart.js v4** (not ECharts) + vanilla JS: embeds `dataModel` as `<script type="application/json" id="report-data">`, intercepts Chart/DataTable/Infographic/Map/HtmlDocument, renders KPI cards, sortable tables (search+pagination only above 100 rows, but ALL rows rendered as `<tr data-row>`), and FilterBar client-side multiselect. It declares `supports_updates=False` and has no `parrot_data_sources`/QuerySource refetch (grep for parrot_data_sources/parrot_param in a2ui_renderers → none). **echarts** renderer maps a single `Chart` to an ECharts option dict (`application/json`) or `wrap_html=True` single-chart page inlining vendored `formats/assets/echarts.min.js` (~1 MB); other components are recorded as degraded. **ssr_html** is fully static.
## Citations
- path: `packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/interactive_html.py`
  lines: 1-10
  symbol: `-`
  excerpt: |
    Emits a SINGLE self-contained HTML document — vendored Chart.js v4 (MIT,
    ``formats/assets/chart.umd.min.js``, ...) + a small vanilla-JS runtime — driven entirely by
    the envelope's ``dataModel``, embedded verbatim as
    ``<script type="application/json" id="report-data">``.
- path: `packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/interactive_html.py`
  lines: 129-136, 240-243, 1546
  symbol: `_SURFACE_NAME`, `_INTERCEPTED`, `_PAGINATION_ROW_THRESHOLD`
  excerpt: |
    _SURFACE_NAME = "interactive-html"
    _INTERCEPTED = {"Chart", "DataTable", "Infographic", "Map", "HtmlDocument"}
    _PAGINATION_ROW_THRESHOLD = 100
    body_rows.append(f'<tr{row_cls} data-row="{row_attr}">{cells}</tr>')
- path: `packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/interactive_html.py`
  lines: 867-873, 902
  symbol: `InteractiveHTMLRenderer`
  excerpt: |
    RendererCapabilities(
        interactive=True,
        supports_actions=False,
        supports_updates=False,
        output="text/html",
    class InteractiveHTMLRenderer(AbstractA2UIRenderer):
- path: `packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/echarts.py`
  lines: 96-107, 652-667
  symbol: `EChartsRenderer`, `EChartsRenderer._wrap_html`
  excerpt: |
    output="application/json", supported_components={"Chart", "Graph"},
    ...
    js = _ECHARTS_JS_PATH.read_text(encoding="utf-8")
    '<body><div id="chart" style="width:100%;height:480px"></div>'
    'var chart=echarts.init(document.getElementById("chart"));'
    f"chart.setOption({option_json});"
- path: `packages/ai-parrot/src/parrot/outputs/a2ui/renderers/__init__.py`
  lines: 51, 78, 108, 141
  symbol: `RendererCapabilities`, `AbstractA2UIRenderer`, `register_a2ui_renderer`, `get_a2ui_renderer`
  excerpt: |
    class RendererCapabilities(BaseModel):
    class AbstractA2UIRenderer(ABC):
    def register_a2ui_renderer(
    def get_a2ui_renderer(name: str) -> type[AbstractA2UIRenderer]:
## Implications
- No existing renderer combines echarts + grid.js + linked refresh; interactive-html is the closest reusable base (page shell, KPI rendering, FilterBar JS) but uses Chart.js and is snapshot-only.
- Embedding 17k rows as server-rendered `<tr>` is the interactive-html pattern — too heavy; a grid.js renderer should render from JSON data client-side.
- An example could either (a) add a new registered renderer (e.g. `echarts-gridjs-html`) in ai-parrot-visualizations reusing `EChartsRenderer._build_option` for option building, or (b) ship a standalone static JS renderer consuming the envelope JSON; (a) gives a Python "render surface to HTML" path for free.
