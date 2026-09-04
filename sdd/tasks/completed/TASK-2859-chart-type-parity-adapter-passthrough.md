# TASK-2859: Chart parity — extend `ChartType`, stop collapsing donut/radar, forward presentation props in the adapter

**Feature**: FEAT-527 — Infographic → A2UI migration (dual-emit)
**Spec**: `sdd/specs/infographic-a2ui-migration.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §1 G3, §2 Overview step 4, §3 Module 2 items 1-2. The A2UI `Chart` schema is derived from
`StructuredChartConfig` (camelCased by `derive_schema`) and **already** accepts `donut`,
`radar`, `horizontalBar`, `colorBySign`, `positiveColor`, `negativeColor`, `palette`,
`trendline`, `xAxisMode`, `xAxisLabel`, `yAxisLabel`, `splitSeries`. Yet
`adapters/infographic.py` collapses `donut→pie`, `radar→line` and forwards only `stacked` and
`showLegend`. Resolved U3: extend presentation parity first. (This task resolves spec §8's
open question on key casing: the derived keys are **camelCase**.)

---

## Scope

- `parrot/models/outputs.py:309-312` — extend the `ChartType` Literal with `"gauge"`, `"funnel"`,
  `"waterfall"`, `"heatmap"`, `"treemap"`. Add `layout: Optional[Literal["full", "half"]]` to
  `StructuredChartConfig` (`:319+`, with a `Field(description=...)`) so `CHART_SCHEMA` gains
  `layout` by construction. Update the docstring `"""Supported chart types ..."""`.
- `catalog/parrot/chart.py:33-44` — update `CHART_INSTRUCTIONS` to list the new types and
  `layout`.
- `adapters/infographic.py`:
  - `CHART_TYPE_MAP` (`:83-96`): identity for `donut`, `radar`, `gauge`, `funnel`, `waterfall`,
    `heatmap`, `treemap`; keep `bar/line/area/scatter/pie`. Update the module docstring
    "Known lossy degradations" bullet (`:53-56`) — chart-type collapse no longer happens.
  - `_chart()` (`:235-265`): forward from the block — `color_by_sign → "colorBySign"`,
    `positive_color → "positiveColor"`, `negative_color → "negativeColor"`, per-series colours
    → `"palette"` (ordered list of `series[i].color`, only when any is set),
    `trendline → "trendline"`, `x_axis_label/y_axis_label → "xAxisLabel"/"yAxisLabel"`,
    `layout → "layout"`, `description → "description"`. Omit keys whose block value is `None`
    (never invent). A `ChartBlock` with `layout` implying horizontal orientation, if such a
    field exists on `ChartBlock` (verify `models/infographic.py:511-709`), maps to
    `"horizontalBar"`; otherwise do not add orientation logic.
  - Update the module docstring "Presentation-only fields ... are dropped" bullet (`:57-59`)
    to list only what is still dropped after this task (table `style`, bullet `columns`,
    hero-card fields — handled by TASK-2860).
- Tests: `tests/outputs/a2ui/adapters/test_infographic_adapter.py` (extend),
  `tests/outputs/a2ui/test_components_chart_datatable_map.py` (schema enum assertion),
  `tests/unit/...` for `StructuredChartConfig(type="gauge")`.
- Regenerate `tests/outputs/a2ui/golden/chart_lowered.json` **only if** `ChartComponent.lower()`
  output changes (it should not in this task — the lowering ignores the new props); record the
  outcome in the completion note.

**NOT in scope**: KPICard/DataTable/Infographic props and goldens (TASK-2860); renderer support for
the new chart types (TASK-2861); frontend.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/models/outputs.py` | MODIFY | `ChartType` Literal + `layout` field |
| `packages/ai-parrot/src/parrot/outputs/a2ui/catalog/parrot/chart.py` | MODIFY | `CHART_INSTRUCTIONS` text |
| `packages/ai-parrot/src/parrot/outputs/a2ui/adapters/infographic.py` | MODIFY | `CHART_TYPE_MAP`, `_chart()`, docstring |
| `packages/ai-parrot/tests/outputs/a2ui/adapters/test_infographic_adapter.py` | MODIFY | pass-through + no-collapse tests |
| `packages/ai-parrot/tests/outputs/a2ui/test_components_chart_datatable_map.py` | MODIFY | enum/`layout` in `CHART_SCHEMA` |
| `packages/ai-parrot/tests/unit/models/test_structured_chart_config_types.py` | CREATE | new chart types validate |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.models.outputs import StructuredChartConfig, ChartType, XAxisMode    # models/outputs.py:319, :309, :315
from parrot.models.infographic import ChartBlock, ChartDataSeries, InfographicResponse  # models/infographic.py:511, :497, :1027
from parrot.outputs.a2ui.adapters import infographic_response_to_envelope, CHART_TYPE_MAP  # adapters/__init__.py:12-15
from parrot.outputs.a2ui.catalog.parrot.chart import CHART_SCHEMA, ChartComponent  # catalog/parrot/chart.py:26, :48
from parrot.outputs.a2ui.catalog.parrot._derive import derive_schema             # _derive.py:88
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/models/outputs.py
ChartType = Literal["bar", "horizontalBar", "line", "area", "scatter", "pie", "donut", "radar", "map"]  # :309-312 ← EXTEND
XAxisMode = Literal["category", "time"]                                                              # :315
class StructuredChartConfig(BaseModel):                                                              # :319
    type: ChartType; x: str; y: List[str]                                                            # :344-346
    stacked: Optional[bool]; trendline: Optional[bool]; split_series: Optional[bool]; show_legend: Optional[bool]  # :347-357
    x_axis_mode: Optional[XAxisMode]; palette: Optional[List[str]]; color_by_sign: Optional[bool]   # :358-368
    negative_color: Optional[str]; positive_color: Optional[str]                                     # :369-376
    # pydantic aliases produce camelCase in model_json_schema(by_alias=True) — derived keys verified:
    # ['colorBySign','data','dataVariable','description','mapName','negativeColor','palette','positiveColor',
    #  'showLegend','splitSeries','stacked','title','trendline','type','x','xAxisLabel','xAxisMode','y','yAxisLabel']

# packages/ai-parrot/src/parrot/outputs/a2ui/catalog/parrot/_derive.py
def derive_schema(model: type[BaseModel], *, binding_fields: Sequence[str], required: Sequence[str] = ()) -> dict  # :88 ; uses model.model_json_schema(by_alias=True)

# packages/ai-parrot/src/parrot/outputs/a2ui/catalog/parrot/chart.py
CHART_SCHEMA = derive_schema(StructuredChartConfig, binding_fields=("data",), required=("type","x","y"))  # :26-30
CHART_INSTRUCTIONS = ("Use Chart to visualize ... Set `type` (bar/line/area/scatter/pie/donut/radar/horizontalBar) ...")  # :32-44 ← UPDATE
@register_component("Chart") class ChartComponent: def lower(self, component, data_model) -> BasicTree  # :48-56

# packages/ai-parrot/src/parrot/outputs/a2ui/adapters/infographic.py
CHART_TYPE_MAP: dict[str, str] = {"bar":"bar","line":"line","area":"area","scatter":"scatter","pie":"pie",
    "donut":"pie","radar":"line","funnel":"bar","waterfall":"bar","heatmap":"bar","treemap":"bar","gauge":"bar"}  # :83-96
_CHART_FALLBACK = "bar"                                                                             # :98
def _chart(self, block: dict[str, Any]) -> dict[str, Any]                                          # :235
    properties = {"title", "type": CHART_TYPE_MAP.get(raw_type, _CHART_FALLBACK), "x": _X_COLUMN, "y": y_names,
                  "stacked": bool(block.get("stacked")), "showLegend": block.get("show_legend") is not False,
                  "data": self._bind_rows("charts", key, rows)}                                     # :256-264
    return _descriptor("Chart", properties)                                                         # :265

# packages/ai-parrot/src/parrot/models/infographic.py
class ChartType(str, Enum)   # :103 (12 legacy members incl. donut/radar/heatmap/treemap/funnel/gauge/waterfall)
class ChartDataSeries(BaseModel)  # :497 (has name, values, optional color — verify field names before use)
class ChartBlock(BaseModel)       # :511-709 (chart_type, title, description, labels, series, x_axis_label, y_axis_label,
                                  #  stacked, show_legend, layout, color_by_sign, positive_color, negative_color — verify each at :511+)

# tests
GOLDEN_DIR = Path(__file__).parent / "golden"   # tests/outputs/a2ui/test_components_chart_datatable_map.py:12 ; test_chart_lowering_golden :89
```

### Does NOT Exist
- ~~snake_case keys (`color_by_sign`, `show_legend`) in `CHART_SCHEMA`~~ — the derived schema is camelCase; the adapter must emit `colorBySign`, `showLegend`, etc.
- ~~`"layout"` in today's `CHART_SCHEMA`~~ — added by this task via `StructuredChartConfig`.
- ~~a hand-written Chart JSON schema~~ — `CHART_SCHEMA` is derived; never edit property dicts by hand.
- ~~`ChartBlock.orientation`~~ — verify before assuming; if absent, do not map to `horizontalBar`.

---

## Implementation Notes

### Pattern to Follow
Adapter purity (spec G2): pass values through; omit `None`; no defaults invented. Existing
`"showLegend": block.get("show_legend") is not False` shows the camelCase target naming.

### Key Constraints
- Adding fields to `StructuredChartConfig` changes `CHART_SCHEMA` and possibly
  `tests/outputs/a2ui/test_catalog_parity.py` expectations — run it and update assertions
  deliberately (record in completion note).
- `ChartComponent.lower()` must remain deterministic; the golden `chart_lowered.json` should be unchanged.
- Run: `timeout -s KILL 600 pytest packages/ai-parrot/tests/outputs/a2ui -q` (adapters, catalog, parity, goldens).

### References in Codebase
- `packages/ai-parrot/tests/outputs/a2ui/adapters/test_infographic_adapter.py` — adapter test style.
- `packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/echarts.py:131-184` — consumer of `colorBySign`/`palette` (proves key names).

---

## Acceptance Criteria

- [ ] `StructuredChartConfig(type=t, x="m", y=["v"])` validates for the 5 new types; `CHART_SCHEMA["properties"]["type"]["enum"]` contains them; `"layout"` in `CHART_SCHEMA["properties"]`
- [ ] `CHART_TYPE_MAP["donut"] == "donut"`, `["radar"] == "radar"`, and the 5 new types map to themselves
- [ ] Adapter `Chart` descriptor carries `colorBySign`, `positiveColor`, `negativeColor`, `palette`, `trendline`, `xAxisLabel`, `yAxisLabel`, `layout`, `description` when set on the block; keys absent when the block has `None`
- [ ] `infographic_response_to_envelope()` still validates against the catalog (`validate_envelope` inside `build_infographic`)
- [ ] `timeout -s KILL 600 pytest packages/ai-parrot/tests/outputs/a2ui packages/ai-parrot/tests/unit/models -q` green; `ruff check` on the three modified modules

---

## Test Specification

```python
# packages/ai-parrot/tests/outputs/a2ui/adapters/test_infographic_adapter.py (add)
def _chart_descriptor(envelope, idx=0): ...  # find the Chart descriptor inside the Infographic root's sections

def test_donut_and_radar_are_not_collapsed():
    for t in ("donut", "radar", "gauge", "funnel", "waterfall", "heatmap", "treemap"):
        assert CHART_TYPE_MAP[t] == t

def test_chart_presentation_fields_forwarded():
    resp = InfographicResponse(blocks=[{"type": "title", "title": "T"},
        {"type": "chart", "chart_type": "bar", "layout": "half", "color_by_sign": True,
         "positive_color": "#0a0", "negative_color": "#a00", "labels": ["a"], "series": [{"name": "d", "values": [1]}]}])
    props = _chart_descriptor(infographic_response_to_envelope(resp))["properties"]
    assert props["colorBySign"] is True and props["layout"] == "half"
    assert props["positiveColor"] == "#0a0" and props["negativeColor"] == "#a00"
    assert "palette" not in props  # no per-series colours given
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — none
3. **Verify the Codebase Contract** — read `models/infographic.py:511-709` to confirm the exact `ChartBlock` field names before mapping them
4. **Update status** in `sdd/tasks/index/infographic-a2ui-migration.json` → `"in-progress"`
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-2859-chart-type-parity-adapter-passthrough.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below (state whether `chart_lowered.json` changed)

---

## Completion Note

**Completed by**: sdd-worker (Claude)
**Date**: 2026-09-05
**Notes**: Extended `ChartType` Literal with `gauge`/`funnel`/`waterfall`/
`heatmap`/`treemap` and added `StructuredChartConfig.layout: Optional[Literal["full","half"]]`
(no alias — matches the derived schema's flat `layout` key). Updated
`CHART_INSTRUCTIONS`. `CHART_TYPE_MAP` is now the identity map for all 12
legacy `ChartBlock.chart_type` members (removed the `donut→pie`/`radar→line`/
5-new-types→bar collapses); kept as an explicit dict (not passthrough) so
an unrecognised future type still degrades to `_CHART_FALLBACK` instead of
failing catalog validation. `_chart()` now forwards `description`,
`colorBySign`, `positiveColor`, `negativeColor`, `trendline`, `xAxisLabel`,
`yAxisLabel`, `layout` when the block value is not `None`, plus a `palette`
list of per-series colours when any series has one. Verified key casing
live against the derived `CHART_SCHEMA` before writing adapter keys
(resolves spec §8's open question): flat `enum` for `type`, `anyOf` wrapper
for `Optional[Literal]` fields like `layout`. `chart_lowered.json` golden
UNCHANGED (verified: `ChartComponent.lower()` ignores the new/forwarded
props; `test_chart_lowering_golden` passes byte-for-byte) — no regeneration
needed. `donut`/`radar`/gauge etc. Chart.js/SSR renderer support is
TASK-2861 (out of scope here); this task only stops the catalog/adapter
from collapsing them. 744/746 targeted tests pass
(`tests/outputs/a2ui` + `tests/unit/models`); the 2 failures in
`test_chart_config_convergence.py` are a pre-existing, unrelated
module-identity collision (verified via `git stash`: they fail on the base
commit too, only when `tests/unit/models/test_output_mode_infographic.py`'s
`sys.modules.pop("parrot.models.outputs")` trick runs earlier in the same
pytest session as `test_chart_config_convergence.py` — an `isinstance`
check then compares against a stale module object). `ruff check` on all 6
touched files: all checks passed.

**Deviations from spec**: none.
