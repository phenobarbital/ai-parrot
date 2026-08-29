# TASK-2564: Satellite renderer fidelity — echarts + folium honour the new props

**Feature**: FEAT-473 — A2UI v1.0 for STRUCTURED_CHART / STRUCTURED_TABLE / STRUCTURED_MAP
**Spec**: `sdd/specs/a2ui-v1-structured-outputs.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-2560
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 5 (G7). With TASK-2560 the wire exposes every config field, but
the satellite A2UI renderers ignore the new props. `EChartsRenderer` must
honour the chart styling props; `FoliumMapRenderer` must render multi-layer
maps with the per-layer `MapLayer` fields.

---

## Scope

- `a2ui_renderers/echarts.py` — `_build_option` honours:
  `stacked`, `splitSeries`, `trendline` (extra series), `colorBySign` +
  `negativeColor`/`positiveColor`, `xAxisLabel`/`yAxisLabel` (axis `name`),
  `palette` (option `color`).
- `a2ui_renderers/folium_map.py` — iterate `dataModel.layers[<i>].features`
  per layer (one `FeatureGroup` each), honouring per-layer `markerColor`,
  `tooltipTemplate`, `labelField`, `geodesic` (polylines), `dataShape`.
- Unit tests (spec §4 Module-5 rows).

**NOT in scope**: catalog schemas (TASK-2560), the `_route_envelope` hook
(TASK-2563), pdf/ssr/adaptive_cards renderers (no prop work specced for them).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/echarts.py` | MODIFY | `_build_option` new props |
| `packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/folium_map.py` | MODIFY | multi-layer + MapLayer props |
| `packages/ai-parrot-visualizations/tests/a2ui_renderers/test_echarts_props.py` | CREATE | option assertions |
| `packages/ai-parrot-visualizations/tests/a2ui_renderers/test_folium_layers.py` | CREATE | layer/marker/tooltip/geodesic assertions |

---

## Codebase Contract (Anti-Hallucination)

> **[470-wt]** lines verified on `feat-470-a2ui-v1-dialect` @ `0da976674`
> (these renderer files land with the FEAT-470 merge). Re-verify on `dev` first.

### Verified Imports
```python
# [470-wt] satellite a2ui renderers
from parrot.outputs.a2ui_renderers.echarts import EChartsRenderer      # echarts.py:58
from parrot.outputs.a2ui_renderers.folium_map import FoliumMapRenderer # folium_map.py:62
```

### Existing Signatures to Use
```python
# [470-wt] echarts.py
class EChartsRenderer:            # :58  supported_components = {"Chart"}
    def render(...)               # :61
    def _build_option(...)        # ~:113 — extend here
# [470-wt] folium_map.py
class FoliumMapRenderer:          # :62  supported_components = {"Map"}
    def render(...)               # :65-118
# Renderers consume BAKED v1.0 components: props are top-level camelCase on the
# root component node; rows come from the envelope dataModel
# (Chart: /rows · Map: /layers/<i>/features — after TASK-2560/2561).
# Legacy chart type "map" → fall back to "bar" (existing CHART_TYPE_MAP/_CHART_FALLBACK convention).
```

### Does NOT Exist
- ~~echarts handling of `stacked/splitSeries/trendline/colorBySign/axis labels/palette`~~ — this task adds it.
- ~~folium multi-layer iteration / `markerColor` / `tooltipTemplate` / `labelField` / `geodesic` / `dataShape`~~ — this task adds it.
- ~~new hard dependencies~~ — folium 0.20.0 is already the satellite `a2ui` extra; nothing new (AC-12).

---

## Implementation Notes

### Key Constraints
- Props may be ABSENT (older envelopes) — every new prop read needs a default
  preserving current output; do not break existing echarts/folium tests.
- `tooltipTemplate` is a string template over feature fields; `labelField`
  names the feature key used for marker labels/popups.
- `geodesic=True` layers draw polylines; `dataShape` selects point vs shape
  handling (mirror what `StructuredMapRenderer` does natively on dev —
  `structured_map.py:417/505/539` is the reference behaviour).
- Async-first project rules; module logger; Google docstrings.

### References in Codebase
- `packages/ai-parrot-visualizations/src/parrot/outputs/formats/structured_map.py` (dev)
  — native folium behaviour to mirror per prop
- existing echarts option-building tests under the satellite's tests/ tree

---

## Acceptance Criteria

- [ ] echarts option reflects stacked series, trendline series, axis names, palette, sign colors, splitSeries (AC-8)
- [ ] folium output has one FeatureGroup per layer; marker colour + tooltip template + label field applied; geodesic polyline rendered (AC-8)
- [ ] Envelopes WITHOUT the new props render exactly as before (regression)
- [ ] Tests pass: `pytest packages/ai-parrot-visualizations/tests/a2ui_renderers/ -v`; ruff clean

---

## Test Specification

```python
# test_echarts_props.py
def test_echarts_honours_new_props(chart_cfg): ...
def test_echarts_defaults_without_new_props(): ...
# test_folium_layers.py
def test_folium_multi_layer_and_marker_color(map_cfg_two_layers): ...
def test_folium_geodesic_polyline(): ...
```

---

## Agent Instructions

1. Verify FEAT-470 merged (`a2ui_renderers/` exists on `dev`) and TASK-2560 completed.
2. Re-verify **[470-wt]** contract lines; update contract first if drifted.
3. Implement, test, move to completed, update index, fill Completion Note.

---

## Completion Note

**Completed by**: sdd-worker (Claude Sonnet)
**Date**: 2026-08-29
**Notes**: `echarts.py::_build_option` now honours `stacked` (`series.stack`),
`splitSeries` (multi-grid layout, one grid/xAxis/yAxis per y series —
`xAxis`/`yAxis` become lists only when `splitSeries` + >1 series),
`trendline` (an extra linear-regression series over the first y column),
`colorBySign`+`negativeColor`/`positiveColor` (a piecewise `visualMap`,
JSON-serializable — no JS callback needed), `xAxisLabel`/`yAxisLabel` (axis
`name`), `palette` (top-level `color`). Every new prop read is defaulted so
the option shape is byte-identical to before when absent (verified: 12
pre-existing `test_echarts.py` tests unchanged).

`folium_map.py`: added a multi-layer path gated on `any(layer.get("data")
for layer in layers)` — critical because OLD envelopes ALSO carry a
`layers` list (`{"name": "stores", "type": "markers"}`, FEAT-470 shape) but
with NO per-layer `data` binding; without this exact gate the new path
would have silently swallowed every legacy single-binding map's points
(caught before committing, fixed by gating on `"data" in layer` rather than
just `layers` truthiness). New per-layer support: `markerColor` →
`folium.CircleMarker` (chosen over `folium.Icon` — `Icon.color` only accepts
a closed Leaflet colour-name enum and would raise on a hex string;
`CircleMarker` accepts arbitrary CSS/hex, with a defensive try/except
fallback to a plain `Marker` regardless), `tooltipTemplate` (`str.format_map`
over feature properties, malformed template caught+logged), `labelField`
(fallback label when no template), `geodesic` (GeoJSON `LineString` →
`folium.PolyLine` — documented as a straight-line approximation, no
great-circle plugin vendored). Feature coordinates read from the FEAT-473
`_geometry` GeoJSON `Point`/`LineString` shape (structured_map.py's
`_build_rows_payload` output), never `SpatialResult`.

New `test_echarts_props.py` (2 tests) and `test_folium_layers.py` (3 tests,
incl. an explicit legacy-single-layer regression check) all pass. Full
`ai-parrot-visualizations` suite: 92 passed (0 regressions vs. TASK-2563's
87). ruff clean.

**Deviations from spec**: none.
