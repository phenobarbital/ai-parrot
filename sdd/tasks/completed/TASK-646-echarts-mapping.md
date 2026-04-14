# TASK-646: ECharts Chart Rendering

**Feature**: infographic-html-output
**Spec**: `sdd/specs/infographic-html-output.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-645
**Assigned-to**: unassigned

---

## Context

> Implements Module 3 from the spec. Adds interactive ECharts chart rendering
> to the `InfographicHTMLRenderer`. TASK-645 created the renderer with chart
> block placeholders; this task replaces those placeholders with actual ECharts
> initialization code and bundles the ECharts JS library inline.

---

## Scope

- Add inline ECharts JS bundle (minified, echarts@5.5.x) to the HTML document `<head>`.
  Store the minified JS as a file in `parrot/outputs/formats/assets/echarts.min.js`
  and load it at import time (or lazy-load on first render).
- Replace the chart placeholder `_render_chart()` method in `InfographicHTMLRenderer`
  with a full implementation that:
  - Creates a `<div id="chart-{uuid}" style="width:100%;height:400px;">` container
  - Generates a `<script>` tag that calls `echarts.init(dom).setOption({...})`
  - Maps `ChartType` enum to ECharts option configurations
- Implement `_build_echarts_option(block: ChartBlock) -> dict` method that maps:
  - `BAR` → `{xAxis: {data: labels}, series: [{type: 'bar', data: values}]}`
  - `LINE` → `{xAxis: {data: labels}, series: [{type: 'line', data: values}]}`
  - `PIE` → `{series: [{type: 'pie', data: [{name, value}]}]}`
  - `DONUT` → pie with `radius: ['40%', '70%']`
  - `AREA` → line with `areaStyle: {}`
  - `SCATTER` → `{series: [{type: 'scatter', data: values}]}`
  - `RADAR` → radar chart with `indicator` from labels
  - `GAUGE` → `{series: [{type: 'gauge', data: [{value}]}]}`
  - `FUNNEL` → `{series: [{type: 'funnel', data: [{name, value}]}]}`
  - `TREEMAP` → `{series: [{type: 'treemap', data: [{name, value}]}]}`
  - `HEATMAP` → heatmap config
  - `WATERFALL` → custom bar implementation with positive/negative coloring
- Handle series colors: propagate `ChartDataSeries.color` to ECharts series items
- Handle chart options: `stacked`, `show_legend`, `x_axis_label`, `y_axis_label`
- Use `orjson.dumps()` to serialize ECharts options to JSON for the `<script>` tag
- Escape any user text in chart titles/labels with `markupsafe.escape()`

**NOT in scope**:
- Non-chart block renderers (TASK-645, already done)
- Content negotiation (TASK-647)
- Static SVG chart rendering (deferred to future feature)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/outputs/formats/infographic_html.py` | MODIFY | Replace chart placeholder, add ECharts mapping methods, add JS bundle loading |
| `packages/ai-parrot/src/parrot/outputs/formats/assets/echarts.min.js` | CREATE | Bundled ECharts 5.5.x minified JS |
| `packages/ai-parrot/src/parrot/outputs/formats/assets/__init__.py` | CREATE | Empty init for package |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# From TASK-645 (will exist after that task):
from parrot.outputs.formats.infographic_html import InfographicHTMLRenderer

# Models
from parrot.models.infographic import (
    ChartBlock,          # verified: infographic.py:148
    ChartType,           # verified: infographic.py:54
    ChartDataSeries,     # verified: infographic.py:138
)

# Utilities
import orjson           # verified: installed, used in infographic.py
from markupsafe import escape  # verified: installed
import uuid             # stdlib
from pathlib import Path  # stdlib
```

### Existing Signatures to Use
```python
# parrot/models/infographic.py:148-165
class ChartBlock(BaseModel):
    type: Literal["chart"]
    chart_type: ChartType        # line 150
    title: Optional[str]          # line 151
    description: Optional[str]    # line 152
    labels: List[str]             # line 154 — x-axis labels
    series: List[ChartDataSeries] # line 155
    x_axis_label: Optional[str]   # line 157
    y_axis_label: Optional[str]   # line 158
    stacked: Optional[bool]       # line 160
    show_legend: Optional[bool]   # line 162

# parrot/models/infographic.py:138-145
class ChartDataSeries(BaseModel):
    name: str                    # line 140
    values: List[Any]            # line 141 — can be int, float, etc.
    color: Optional[str]         # line 143

# parrot/models/infographic.py:54-67
class ChartType(str, Enum):
    BAR = "bar"
    LINE = "line"
    PIE = "pie"
    DONUT = "donut"
    AREA = "area"
    SCATTER = "scatter"
    RADAR = "radar"
    HEATMAP = "heatmap"
    TREEMAP = "treemap"
    FUNNEL = "funnel"
    GAUGE = "gauge"
    WATERFALL = "waterfall"
```

### Does NOT Exist
- ~~`InfographicHTMLRenderer._build_echarts_option()`~~ — does not exist yet; this task creates it
- ~~`parrot.outputs.formats.echarts.EChartsRenderer._build_option()`~~ — no such reusable method
- ~~`parrot.outputs.formats.assets`~~ — does not exist yet; this task creates the directory

---

## Implementation Notes

### ECharts JS Bundle
- Download `echarts@5.5.1` minified from the official release
- Store at `parrot/outputs/formats/assets/echarts.min.js`
- Load at module level: `ECHARTS_JS = Path(__file__).parent / "assets" / "echarts.min.js"`
- Read on first use (lazy): `_echarts_js_cache = None`
- Include in `<head>` as `<script>{echarts_js_content}</script>`

### ECharts Option Generation Pattern
```python
def _build_echarts_option(self, block: ChartBlock) -> dict:
    """Map ChartBlock to ECharts option dict."""
    option = {"tooltip": {"trigger": "axis"}, "grid": {"containLabel": True}}

    if block.title:
        option["title"] = {"text": str(escape(block.title))}

    if block.show_legend is not False:
        option["legend"] = {"data": [s.name for s in block.series]}

    # Dispatch by chart type
    if block.chart_type in (ChartType.BAR, ChartType.LINE, ChartType.AREA):
        option["xAxis"] = {"type": "category", "data": block.labels}
        if block.x_axis_label:
            option["xAxis"]["name"] = str(escape(block.x_axis_label))
        option["yAxis"] = {"type": "value"}
        if block.y_axis_label:
            option["yAxis"]["name"] = str(escape(block.y_axis_label))
        option["series"] = []
        for s in block.series:
            item = {"name": s.name, "data": s.values, "type": block.chart_type.value}
            if block.chart_type == ChartType.AREA:
                item["type"] = "line"
                item["areaStyle"] = {}
            if s.color:
                item["itemStyle"] = {"color": s.color}
            if block.stacked:
                item["stack"] = "total"
            option["series"].append(item)
    elif block.chart_type in (ChartType.PIE, ChartType.DONUT):
        # ... pie/donut handling
    # ... etc for each ChartType
    return option
```

### Script Tag Generation
```python
chart_id = f"chart-{uuid.uuid4().hex[:8]}"
option_json = orjson.dumps(option).decode("utf-8")
script = f"""
<div id="{chart_id}" class="chart-container" style="width:100%;height:400px;"></div>
<script>
(function() {{
    var dom = document.getElementById('{chart_id}');
    var chart = echarts.init(dom);
    chart.setOption({option_json});
    window.addEventListener('resize', function() {{ chart.resize(); }});
}})();
</script>
"""
```

### Key Constraints
- ECharts options must be valid JSON (use orjson, not manual string building)
- Chart titles/labels must be escaped before insertion
- Each chart gets a unique DOM id (uuid-based)
- Include `window.addEventListener('resize', ...)` for responsive charts
- The `WATERFALL` chart type uses a custom bar implementation (ECharts has no native waterfall)

---

## Acceptance Criteria

- [ ] ECharts JS is bundled inline in the HTML `<head>`
- [ ] BAR, LINE, PIE charts render correctly with proper ECharts options
- [ ] DONUT renders as pie with inner radius
- [ ] AREA renders as line with areaStyle
- [ ] All 12 ChartType values are handled (no crashes on any type)
- [ ] Series colors are propagated to ECharts config
- [ ] `stacked`, `show_legend`, axis labels are respected
- [ ] Charts are responsive (resize listener)
- [ ] Chart titles/labels are XSS-safe

---

## Test Specification

```python
import pytest
import orjson
from parrot.outputs.formats.infographic_html import InfographicHTMLRenderer
from parrot.models.infographic import (
    InfographicResponse, ChartBlock, ChartType, ChartDataSeries,
    TitleBlock,
)


@pytest.fixture
def renderer():
    return InfographicHTMLRenderer()


class TestEChartsMapping:
    def test_bar_chart_option(self, renderer):
        block = ChartBlock(
            type="chart", chart_type=ChartType.BAR, title="Sales",
            labels=["Q1", "Q2"], series=[ChartDataSeries(name="Rev", values=[100, 200])]
        )
        option = renderer._build_echarts_option(block)
        assert option["xAxis"]["data"] == ["Q1", "Q2"]
        assert option["series"][0]["type"] == "bar"

    def test_pie_chart_option(self, renderer):
        block = ChartBlock(
            type="chart", chart_type=ChartType.PIE, title="Share",
            labels=["A", "B"], series=[ChartDataSeries(name="Share", values=[60, 40])]
        )
        option = renderer._build_echarts_option(block)
        assert option["series"][0]["type"] == "pie"

    def test_series_color(self, renderer):
        block = ChartBlock(
            type="chart", chart_type=ChartType.LINE, title="T",
            labels=["a"], series=[ChartDataSeries(name="s", values=[1], color="#ff0000")]
        )
        option = renderer._build_echarts_option(block)
        assert option["series"][0]["itemStyle"]["color"] == "#ff0000"

    def test_stacked_bar(self, renderer):
        block = ChartBlock(
            type="chart", chart_type=ChartType.BAR, title="T",
            labels=["a"], stacked=True,
            series=[ChartDataSeries(name="s1", values=[1]),
                    ChartDataSeries(name="s2", values=[2])]
        )
        option = renderer._build_echarts_option(block)
        assert all(s.get("stack") == "total" for s in option["series"])

    def test_echarts_js_inline(self, renderer):
        resp = InfographicResponse(
            blocks=[
                TitleBlock(type="title", title="T"),
                ChartBlock(type="chart", chart_type=ChartType.BAR,
                          labels=["a"], series=[ChartDataSeries(name="s", values=[1])]),
            ]
        )
        html = renderer.render_to_html(resp)
        assert "echarts.init" in html
        assert "<script>" in html

    def test_chart_resize_listener(self, renderer):
        block = ChartBlock(
            type="chart", chart_type=ChartType.LINE, title="T",
            labels=["a"], series=[ChartDataSeries(name="s", values=[1])]
        )
        html = renderer._render_chart(block)
        assert "resize" in html
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/infographic-html-output.spec.md`
2. **Check dependencies** — verify TASK-644 and TASK-645 are in `tasks/completed/`
3. **Download ECharts** — get the minified JS for echarts 5.5.x and place it in assets/
4. **Verify the Codebase Contract** — confirm ChartBlock fields at infographic.py:148
5. **Update status** in `tasks/.index.json` → `"in-progress"`
6. **Implement** following the scope and notes above
7. **Verify** all acceptance criteria are met
8. **Move this file** to `tasks/completed/TASK-646-echarts-mapping.md`
9. **Update index** → `"done"`

---

## Completion Note

*(Agent fills this in when done)*
