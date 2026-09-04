# TASK-2861: Renderer support for the 5 new chart types — ECharts native, Chart.js/SSR recorded degradation

**Feature**: FEAT-527 — Infographic → A2UI migration (dual-emit)
**Spec**: `sdd/specs/infographic-a2ui-migration.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-2859
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 2 item 4, §7 "Chart.js has no native gauge/funnel/…". TASK-2859 lets envelopes
carry `type ∈ {gauge, funnel, waterfall, heatmap, treemap}` (plus un-collapsed `donut`/`radar`).
The satellite renderers must handle them: ECharts supports all natively; the Chart.js-based
`interactive-html` and the static `ssr-html` must degrade **visibly and recorded**, never
silently.

---

## Scope

- `a2ui_renderers/echarts.py` — `_SERIES_TYPE` (`:38-58`) += `gauge`, `funnel`, `treemap`,
  `heatmap`; `_build_option()` (`:128+`) builds correct series for: `gauge` (single value per
  series, `series.type="gauge"`, `data=[{value,name}]`), `funnel` (`type="funnel"`, `data=[{value,name}]`
  from first y), `treemap` (`type="treemap"`, `data=[{name,value}]`), `heatmap` (`type="heatmap"`,
  `data=[[xIdx,yIdx,value]]` over `x` × `y` columns, `visualMap` added), `waterfall` (stacked-bar
  technique: transparent "placeholder" series + delta series, `series.stack`), `donut`
  (`type="pie"` with `radius=["40%","70%"]`), `radar` (`type="radar"` + `radar.indicator` from x
  labels). Honour `colorBySign`/`palette` where meaningful (already at `:147-184`).
- `a2ui_renderers/interactive_html.py` — `_CHART_TYPE` (`:161-167`) maps `donut→doughnut`,
  `radar→radar` (Chart.js natives), `horizontalBar→bar` with `indexAxis:'y'` if the option
  builder supports it (verify `buildDatasets`/config JS at `:200-230`), and the 5 new types →
  `"bar"` **plus** a `degraded` record via `degrade()`/the renderer's degradation list in
  `_render_chart()` (`:1005+`), with a visible caption "rendered as bar (no <type> support in this
  surface)".
- `a2ui_renderers/ssr_html.py` — chart lowering already degrades to a text summary; ensure the type
  caption prints the original type and add a `degraded` record for the 5 new types (find where
  `Chart` lowering output is rendered; the caption Text carries `parrot_role: "series"`-style
  extensions — verify).
- Tests: `tests/outputs/a2ui_renderers/test_echarts.py`, `test_echarts_props.py`,
  `test_interactive_html.py`, `test_ssr_html.py` (visualizations package).

**NOT in scope**: `HtmlDocument` rendering (TASK-2865); KPICard icon/color visuals (follow-up);
`adaptive_cards.py` / `pdf.py` beyond what `SSRHTMLRenderer` inheritance gives (`pdf.py:99`).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/echarts.py` | MODIFY | native series builders |
| `packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/interactive_html.py` | MODIFY | type map + recorded degradation |
| `packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/ssr_html.py` | MODIFY | recorded degradation for unsupported chart types |
| `packages/ai-parrot-visualizations/tests/outputs/a2ui_renderers/test_echarts.py` | MODIFY | new-type option tests |
| `packages/ai-parrot-visualizations/tests/outputs/a2ui_renderers/test_interactive_html.py` | MODIFY | degradation tests |
| `packages/ai-parrot-visualizations/tests/outputs/a2ui_renderers/test_ssr_html.py` | MODIFY | degradation tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.outputs.a2ui.models import Component, CreateSurface                 # test_ssr_html.py:9 pattern
from parrot.outputs.a2ui.renderers import get_a2ui_renderer, AbstractA2UIRenderer, RendererCapabilities, register_a2ui_renderer  # renderers/__init__.py:141,78,51,108
from parrot.outputs.a2ui.renderers.degrade import degrade                       # renderers/degrade.py:24  def degrade(node: BasicNode, reason: str) -> BasicNode
from parrot.outputs.a2ui.artifacts import RenderedArtifact                     # artifacts.py:54 (metadata["degraded"] list)
from parrot.outputs.a2ui.baking import bake_envelope                            # echarts.py:23
from parrot.outputs.a2ui_renderers.echarts import EChartsRenderer               # echarts.py:60
from parrot.outputs.a2ui_renderers.ssr_html import SSRHTMLRenderer              # ssr_html.py:142
from parrot.outputs.a2ui_renderers.interactive_html import InteractiveHTMLRenderer  # interactive_html.py:574 (verify class name at :574)
from parrot.outputs.a2ui.builders import build_chart                            # builders.py:97
```

### Existing Signatures to Use
```python
# echarts.py
_SERIES_TYPE = {"bar": "bar", ..., "pie": "pie"}                                  # :38-58 ← EXTEND
class EChartsRenderer(AbstractA2UIRenderer):                                    # :60
    async def render(self, envelope, *, bake=True)                              # :63
    def _build_option(self, props: dict[str, Any]) -> dict[str, Any]            # :128 ; chart_type = props.get("type","bar") :140 ; series_type = _SERIES_TYPE.get(chart_type,"bar") :141
        series_entry = {"name": col, "type": series_type, "data": values}       # :154 ; stacked :147-157 ; palette → option["color"] :182-184 ; pie special-case :202
    @staticmethod def _linear_trend(values) -> list[float]                      # :228
    def _wrap_html(self, option, title) -> str                                  # :249

# interactive_html.py
_CHART_TYPE = {"bar":"bar","line":"line","area":"line","scatter":"scatter","pie":"pie"}   # :161-167 ← EXTEND
_INTERCEPTED = {"Chart", "DataTable", "Infographic", "Map"}                     # :120
def _render_descriptor(self, descriptor) -> str                                 # :705
def _render_chart(self, props: dict[str, Any]) -> str                           # :1005
def _render_datatable(self, props) -> str                                       # :1058
def _render_infographic(self, props) -> str                                     # :1136
# degradation list: `degradations.append(...)` idiom + `degrade(node, "no renderer available")` :772

# ssr_html.py
@register_a2ui_renderer(... RendererCapabilities(...))                          # :113-141
class SSRHTMLRenderer(AbstractA2UIRenderer): __init__(*, theme="light", layout="analytics")  # :142-164
def _render_basic(self, node, degradations) -> str                              # :383-394 (uses degradation_record(node, msg) + degrade(node, reason))
def _render_Text(self, node, degradations) -> str                               # :402
# pdf.py: class PDFRenderer(SSRHTMLRenderer) :99 — inherits everything above

# ChartComponent.lower() degrades to a data summary (title, type caption, axis line, series list) — catalog/parrot/chart.py:52-56
```

### Does NOT Exist
- ~~Chart.js native `gauge`/`funnel`/`waterfall`/`heatmap`/`treemap`~~ — degrade to `bar` with a record.
- ~~a CDN `<script src>`~~ — FEAT-493 invariant: the interactive document must stay self-contained (vendored Chart.js at `formats/assets/chart.umd.min.js`; vendored ECharts at `formats/assets/echarts.min.js`).
- ~~`get_a2ui_renderer("interactive_html")`~~ — registered name is `"interactive-html"`; import the module explicitly in tests (cold-registry caveat).
- ~~`RenderedArtifact.degradations`~~ — the list lives at `metadata["degraded"]`.

---

## Implementation Notes

### Pattern to Follow
`echarts.py:140-160` — branch on `chart_type`, build `series_entry` per y column; keep the
option a plain dict (G1: no code strings, no `exec`).

### Key Constraints
- Never silently drop a series; unsupported → nearest type + `degraded` record + visible caption.
- Keep `test_interactive_html.py`'s self-contained assertions (no `<script src=`, `<link `, `@import`) green.
- ECharts `heatmap` needs `visualMap`; `gauge` ignores `x`; document each mapping in the method docstring.

### References in Codebase
- `packages/ai-parrot-visualizations/tests/outputs/a2ui_renderers/test_echarts_props.py` — asserts prop handling (stacked/palette/colorBySign).
- `packages/ai-parrot-visualizations/tests/outputs/a2ui_renderers/test_filterbar_degradation.py` — degradation-record test style.

---

## Acceptance Criteria

- [ ] ECharts option JSON for each of gauge/funnel/waterfall/heatmap/treemap/donut/radar is built from bound rows with the correct `series[].type`; `palette`/`colorBySign` still honoured
- [ ] `interactive-html`: donut→doughnut, radar→radar; the 5 new types render as bar **and** append a `degraded` entry with the original type; visible caption present
- [ ] `ssr-html`/`pdf`: type caption shows the original type; `degraded` entry recorded for the 5 new types
- [ ] Self-contained HTML invariants unchanged (`test_interactive_html.py` external-reference assertions)
- [ ] `timeout -s KILL 600 pytest packages/ai-parrot-visualizations/tests/outputs/a2ui_renderers -q` green; `ruff check` on the three renderer modules

---

## Test Specification

```python
# tests/outputs/a2ui_renderers/test_echarts.py (add)
@pytest.mark.parametrize("ctype,series_type", [("gauge","gauge"),("funnel","funnel"),("treemap","treemap"),("heatmap","heatmap"),("donut","pie"),("radar","radar")])
def test_new_chart_types_series(ctype, series_type):
    props = {"type": ctype, "x": "m", "y": ["v"], "data": [{"m": "a", "v": 1}, {"m": "b", "v": 2}]}
    option = EChartsRenderer()._build_option(props)
    assert option["series"][0]["type"] == series_type

def test_waterfall_uses_stacked_placeholder():
    option = EChartsRenderer()._build_option({"type": "waterfall", "x": "m", "y": ["v"], "data": [{"m": "a", "v": 5}, {"m": "b", "v": -2}]})
    assert len(option["series"]) == 2 and all(s.get("stack") for s in option["series"])

# tests/outputs/a2ui_renderers/test_interactive_html.py (add)
async def test_gauge_degrades_to_bar_with_record():
    env = build_chart(type="gauge", x="m", y=["v"], rows=[{"m": "a", "v": 1}])   # verify build_chart kwargs at builders.py:97
    art = await InteractiveHTMLRenderer().render(env)
    assert any("gauge" in d.get("reason", "") for d in art.metadata["degraded"])
    assert "<script src=" not in art.content.decode()
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — TASK-2859 in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — read `echarts.py:128-230` and `interactive_html.py:1005-1060` fully before editing
4. **Update status** in `sdd/tasks/index/infographic-a2ui-migration.json` → `"in-progress"`
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-2861-renderers-new-chart-types-degradation.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (Claude)
**Date**: 2026-09-05
**Notes**:
- **ECharts** (`echarts.py`): `_SERIES_TYPE` += donut→pie/radar/gauge/funnel/
  treemap/heatmap; row-native types (gauge/funnel/treemap/heatmap/waterfall/
  radar) built via a new `_build_row_native_series()` dispatcher (early
  return from `_build_option`) rather than the standard per-y-column loop:
  gauge (one data point per y column, x ignored), funnel/treemap (data from
  the FIRST y column only), heatmap ([xIdx,yIdx,value] triples + a new
  `_heatmap_visual_map()` + categorical x/y axes), waterfall (2-series
  stacked-bar technique: transparent placeholder + delta series), radar (one
  trace per y column, `radar.indicator` from x categories). `donut` reuses
  the standard `pie` loop with `radius:["40%","70%"]` added per series.
  `palette`/`colorBySign` remain honoured for bar/line/area/scatter/pie/donut
  (unchanged code path) — not meaningful for the row-native types, so not
  applied there.
- **interactive-html** (`interactive_html.py`): `_CHART_TYPE` (Python,
  previously DEAD CODE — verified unused anywhere) and the mirrored inline
  JS `chartTypeMap` both gained `donut→doughnut`/`radar→radar`. The 5
  unsupported types render as `"bar"` in the embedded Chart.js config AND
  append a `degradation_record` (a visible `<p class="a2ui-notice">rendered
  as bar (no <type> support in this surface)</p>` caption too) — implemented
  in `_render_chart()`, which now takes a `degradations` list threaded
  through `_render_top` → `_render_chart`/`_render_descriptor` →
  `_render_infographic` (nested Chart-in-Infographic degradations now reach
  the top-level `metadata["degraded"]`, previously impossible since neither
  method accepted the list).
- **ssr-html** (`ssr_html.py`): ALL chart types already lower to the same
  generic text summary (`ChartComponent.lower()`'s caption already prints
  `f"Chart ({type})"` — verified, no change needed there, out of this
  task's file scope anyway). `_lower_composites()` now takes a
  `degradations` list and records the 5 new types (before FEAT-527 the
  adapter collapsed them to a supported type, so this renderer never saw
  the literal type before); `pdf.py`'s `PDFRenderer(SSRHTMLRenderer)`
  inherits the fix with zero code changes (confirmed no override exists).
- **Deviation (documented, not scope creep)**: `test_semantic_classes.py`'s
  `TestGoldensUntouched::test_no_catalog_file_modified` (a pre-existing
  FEAT-522/TASK-2715 guard, git-diffing `catalog/` against `origin/dev`)
  started failing purely as a side effect of TASK-2859/2860's ALREADY-LANDED,
  spec-sanctioned catalog edits — not anything in this task's own diff.
  Left unfixed it would permanently redden
  `pytest packages/ai-parrot-visualizations/tests/outputs/a2ui_renderers`,
  this task's own acceptance criterion. Updated its allowlist with the 4
  FEAT-527 catalog files and a comment citing spec §7's explicit golden-
  freeze exception. Not listed in this task's Files table; added as the
  minimal necessary companion fix, called out here rather than silently
  bundled.
- 204/204 tests pass in
  `pytest packages/ai-parrot-visualizations/tests/outputs/a2ui_renderers`.
  `ruff check` on all 7 touched files: all checks passed.

**Deviations from spec**: none in the renderer behaviour itself; see the
`test_semantic_classes.py` note above for the one out-of-list file touched
(a stale guard-test fix, not a code-behavior deviation).
