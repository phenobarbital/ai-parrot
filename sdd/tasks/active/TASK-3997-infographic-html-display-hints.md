# TASK-3997: Infographic HTML lane honours the display hints

**Feature**: FEAT-623 — Infographic → A2UI display hints
**Spec**: `sdd/specs/infographic-a2ui-display-hints.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3994, TASK-3996
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 4 (G3). Once TASK-3994 adds the model hints and TASK-3996
aligns `format_cell`, the infographic HTML renderer must print the same
strings the A2UI renderers print, and draw a second value axis when a series
asks for one. Today it escapes hero values verbatim (`:747`), prints every
table cell with `escape(str(cell))` (`:1227`), and builds a single `yAxis`
dict (`:958`).

---

## Scope

- **`_render_hero_card`**:
  - A numeric `value` (int/float, not bool) with a `format` renders as
    `format_cell(value, col_type="number", col_format=format)`, followed by
    `" " + unit` unless `format == "percent"`.
  - A numeric value with a `unit` but no `format` renders as
    `str(value) + " " + unit`.
  - A `str` value is escaped verbatim, exactly as today.
- **`_render_table`**: for a `ColumnDef` column with a numeric `type`
  (`is_numeric_column`), format the cell with `format_cell` and right-align
  it, unless `ColumnDef.align` is set. Every other cell renders as today.
- **`_build_echarts_option`, bar/line/area branch**: when any series has
  `axis == "right"`:
  - `option["yAxis"]` becomes a list of two value axes: `[left, right]`.
  - The left axis keeps today's dict (splitLine, name, currency formatter).
  - The axis names come from `y_axis_labels[i]`. The left falls back to
    `y_axis_label`.
  - Right-axis series items get `"yAxisIndex": 1`.

  With no right-axis series, the option is byte-identical to today.
- Write `test_infographic_lanes_agree.py`, the HTML half: one
  `InfographicResponse` fixture (numeric hero with `format`, typed table, a
  titled progress block, a right-axis chart). Assert the visible strings
  and the ECharts axis config in the HTML.

**NOT in scope**:
- The model fields (TASK-3994).
- `format_cell` itself (TASK-3996).
- The adapter-side assertions of `test_infographic_lanes_agree`. Those
  belong to TASK-3995's adapter tests, over the same fixture shape.
- `_render_progress`, which already renders title, % and target.
- The A2UI Python renderers, which already honour `seriesAxes`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-visualizations/src/parrot/outputs/formats/infographic_html.py` | MODIFY | hero / table via `format_cell`; dual `yAxis` |
| `packages/ai-parrot-visualizations/tests/outputs/test_infographic_html_display_hints.py` | CREATE | unit tests for hero / table / chart |
| `packages/ai-parrot-visualizations/tests/outputs/test_infographic_lanes_agree.py` | CREATE | HTML half of the lanes-agree fixture |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# inside infographic_html.py (relative, same package ai-parrot-visualizations):
from ..a2ui_renderers._table_format import format_cell, is_numeric_column  # verified: parrot/outputs/a2ui_renderers/_table_format.py:28,41
# already imported there (verified: infographic_html.py:33-71): ChartBlock, ChartDataSeries, ChartType, ColumnDef, HeroCardBlock, TableBlock, InfographicResponse
# tests:
from parrot.outputs.formats.infographic_html import InfographicHTMLRenderer  # verified: test_infographic_html_layouts.py:5 ; class at infographic_html.py:224
```

### Existing Signatures to Use
```python
# packages/ai-parrot-visualizations/src/parrot/outputs/formats/infographic_html.py
from markupsafe import escape                                    # :19
class InfographicHTMLRenderer(BaseRenderer):                     # :224
    def render_to_html(self, data, ..., layout=...) -> str:      # :303  (tests call InfographicHTMLRenderer().render_to_html(payload_dict))
    def _render_hero_card(self, block: HeroCardBlock) -> str:    # :745 ; `value = escape(block.value)` :747
    def _render_chart(self, block: ChartBlock) -> str:           # :782
    def _is_currency_axis(block: ChartBlock) -> bool:            # :818 (staticmethod; "$" in y_axis_label) — keep on the LEFT axis only
    def _build_echarts_option(self, block: ChartBlock) -> dict:  # :916
        # bar/line/area branch :950 ; option["yAxis"] = {...} :958-961 ; `if block.y_axis_label:` :962-963
        # currency formatter :967-969 ; option["series"] = [] :976 ; `for s in block.series:` :977 ; `if block.stacked:` :1012
    def _render_table(self, block: TableBlock) -> str:           # :1190 ; header cells honour ColumnDef width/align/color :1202-1221
        # body cells: `cells = "\n".join(f"                    <td>{escape(str(cell))}</td>" for cell in row)` :1227
# Model fields consumed (ADDED BY TASK-3994 — verify they exist before starting):
#   HeroCardBlock.value: Union[str, float]; HeroCardBlock.format: Optional[Literal["percent","currency","number"]]; HeroCardBlock.unit: Optional[str]
#   ColumnDef.type: Optional[str]; ColumnDef.format: Optional[str]
#   ChartDataSeries.axis: Optional[Literal["left","right"]]; ChartBlock.y_axis_labels: Optional[List[Optional[str]]]
# packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/_table_format.py
def is_numeric_column(col_type: str | None) -> bool:                                      # :28
def format_cell(value: Any, *, col_type: str | None, col_format: str | None = None) -> str: # :41 (aligned by TASK-3996)
```

### Does NOT Exist
- ~~`HeroCardBlock.format` / `.unit`, `ColumnDef.type` / `.format`,
  `ChartDataSeries.axis`, `ChartBlock.y_axis_labels`~~ on `dev` today.
  TASK-3994 adds them; this task depends on it.
- ~~A `format_cell` `unit` parameter~~: append the unit in the renderer.
- ~~A `.num` CSS class in the infographic HTML theme~~: that class belongs to
  the A2UI renderers' DataTable. Use an inline `text-align:right` here.
- ~~A shared `test_infographic_lanes_agree` fixture module~~: none exists;
  the payload is defined in this task's test file.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-visualizations/src/parrot/outputs/formats/infographic_html.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-visualizations/tests/outputs/test_infographic_html_display_hints.py", "action": "CREATE"},
    {"path": "packages/ai-parrot-visualizations/tests/outputs/test_infographic_lanes_agree.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-visualizations/src/parrot/outputs/formats/infographic_html.py#InfographicHTMLRenderer._render_hero_card",
    "sym:packages/ai-parrot-visualizations/src/parrot/outputs/formats/infographic_html.py#InfographicHTMLRenderer._render_table",
    "sym:packages/ai-parrot-visualizations/src/parrot/outputs/formats/infographic_html.py#InfographicHTMLRenderer._build_echarts_option",
    "sym:packages/ai-parrot-visualizations/src/parrot/outputs/formats/infographic_html.py#InfographicHTMLRenderer.render_to_html",
    "sym:packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/_table_format.py#format_cell",
    "sym:packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/_table_format.py#is_numeric_column"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Without hints, output must be **byte-identical** to today: string hero
  values, `List[str]` columns, and series without `axis`. Existing
  `test_infographic_html_layouts.py` and
  `packages/ai-parrot/tests/unit/outputs/test_formats_infographic_html_renderer.py`
  must stay green untouched.
- Never infer: format a cell only when its `ColumnDef.type` is numeric, and
  a hero value only when it is a number.
- Escape every formatted string with `escape(...)`, as the rest of the file does.

---

## Implementation Blueprint

### Steps (in order)
1. Add the `format_cell` / `is_numeric_column` import. *Why*: this is the
   one shared formatter (spec non-goal: no new formatter module).
2. Change `_render_hero_card`. *Why*: numeric hero values (G1/G3).
3. Change the `_render_table` body cells. *Why*: typed columns must print
   like the A2UI DataTable.
4. Add the dual axis in `_build_echarts_option`. *Why*: spec M4. The A2UI
   lanes already draw it.
5. Write both test files and run the Validation Commands plus the existing
   infographic HTML tests.

### `packages/ai-parrot-visualizations/src/parrot/outputs/formats/infographic_html.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'from .assets.design_system import DesignSystem' infographic_html.py) — :73
# AFTER — insert below `from .assets.design_system import DesignSystem`
from ..a2ui_renderers._table_format import format_cell, is_numeric_column


# occurrences: 1 (verified: grep -c 'value = escape(block.value)' infographic_html.py) — :747
# REPLACE that line with:
        value = escape(self._hero_display(block))


# ADD a helper method next to _render_hero_card (inside InfographicHTMLRenderer):
    @staticmethod
    def _hero_display(block: HeroCardBlock) -> str:
        """Hero value text: a str verbatim; a number via format_cell when `format` is set, plus `unit` unless percent."""
        # FILL IN: str -> as is; bool -> str(); int/float + format -> format_cell(v, col_type="number", col_format=block.format); append f" {block.unit}" when unit and format != "percent" — bounded by spec M4 and TASK-3996's unit rule


# occurrences: 1 (verified: grep -c 'cells = "\n".join(f"                    <td>{escape(str(cell))}</td>" for cell in row)' infographic_html.py) — :1227
# REPLACE that line with:
            cells = "\n".join(self._table_cell(block.columns, idx, cell) for idx, cell in enumerate(row))


# ADD a helper method next to _render_table:
    @staticmethod
    def _table_cell(columns: List[Any], idx: int, cell: Any) -> str:
        """One <td>: numeric-typed ColumnDef -> format_cell + right-aligned (unless align is set); else escape(str(cell))."""
        # FILL IN: col = columns[idx] if idx < len(columns) else None; only ColumnDef with is_numeric_column(col.type) is formatted — bounded by "never infer"; keep the exact 20-space indent of :1227 for untyped cells (byte-identical output)
```
**Why**: two small helpers keep `_render_table` and `_render_hero_card`
within the complexity budget, and leave their unhinted paths visibly
unchanged.

### `infographic_html.py` — dual value axis (MODIFY, inside `_build_echarts_option`)
```python
# occurrences of `option["series"] = []`: 2 (verified: grep -c) — :976 and :1039. Use the bar/line/area one:
#     fill_line = ct == ChartType.LINE and len(block.series) == 1
#     option["series"] = []
#     for s in block.series:
# occurrences of `if block.stacked:`: 1 (verified: grep -c) — :1012
# AFTER — insert below the line `if block.stacked:` block's `item["stack"] = "total"` (i.e. just before `option["series"].append(item)`):
                if getattr(s, "axis", None) == "right":
                    item["yAxisIndex"] = 1

# AFTER the series loop of this branch (still inside `if ct in (ChartType.BAR, ChartType.LINE, ChartType.AREA):`):
            if any(getattr(s, "axis", None) == "right" for s in block.series):
                option["yAxis"] = self._dual_value_axes(block, option["yAxis"])


# ADD a helper method:
    @staticmethod
    def _dual_value_axes(block: ChartBlock, left: Dict[str, Any]) -> List[Dict[str, Any]]:
        """[left, right] value axes; names from y_axis_labels, left falling back to y_axis_label."""
        # FILL IN: copy `left` (keeps splitLine + currency formatter); left name = labels[0] or y_axis_label; right = {"type": "value", "splitLine": {"show": False}} + name labels[1] when present — bounded by spec M4
```
**Why**: the right axis is purely additive. A chart with no right-axis
series never reaches the helper, so its option JSON is unchanged.

### `packages/ai-parrot-visualizations/tests/outputs/test_infographic_html_display_hints.py` (CREATE)
```python
"""FEAT-623 (TASK-3997): the infographic HTML lane honours the display hints."""

from parrot.outputs.formats.infographic_html import InfographicHTMLRenderer


def _html(*blocks):
    return InfographicHTMLRenderer().render_to_html({"blocks": [{"type": "title", "title": "T"}, *blocks]})


def test_hero_numeric_formatted() -> None:
    html = _html({"type": "hero_card", "label": "MRR", "value": 1234.5, "format": "currency"})
    assert "$1,234.50" in html


def test_hero_string_verbatim() -> None:
    assert "$1.20M" in _html({"type": "hero_card", "label": "MRR", "value": "$1.20M"})


def test_table_numeric_column_formatted() -> None:
    # FILL IN: ColumnDef(type="number", format="percent") cell 0.028 -> "2.8%" right-aligned; a List[str]-column table renders exactly as before
    ...


def test_chart_right_axis_two_yaxes() -> None:
    # FILL IN: series [{"name":"MRR",...},{"name":"New MRR","axis":"right",...}], y_axis_labels -> two yAxis entries in the option JSON + "yAxisIndex": 1 on New MRR; a chart without axis keeps a single yAxis
    ...
```

### `packages/ai-parrot-visualizations/tests/outputs/test_infographic_lanes_agree.py` (CREATE)
```python
"""FEAT-623 (TASK-3997): HTML half of the lanes-agree check (adapter half lives in TASK-3995's adapter tests)."""

from parrot.outputs.formats.infographic_html import InfographicHTMLRenderer

PAYLOAD = {
    "blocks": [
        {"type": "title", "title": "Lanes"},
        {"type": "hero_card", "label": "Closing MRR", "value": 1203456.78, "format": "currency"},
        # FILL IN: typed table (number+currency, number+percent ratio, integer), titled progress block, line chart with one right-axis series + y_axis_labels — the same shape TASK-3995 asserts on the envelope side
    ]
}


def test_html_lane_prints_the_hinted_strings() -> None:
    html = InfographicHTMLRenderer().render_to_html(PAYLOAD)
    assert "$1,203,456.78" in html
    # FILL IN: assert table strings, progress title + %, and the dual yAxis / yAxisIndex — bounded by spec §4 test_infographic_lanes_agree
```

### FILL IN checklist
- [ ] `_hero_display`: str / number / unit rules; bounded by spec M4.
- [ ] `_table_cell`: typed-only formatting; byte-identical untyped cells.
- [ ] `_dual_value_axes`: names and right-axis style; bounded by spec M4.
- [ ] Both test files: complete the stubs.

---

## Acceptance Criteria

- [ ] A numeric hero with `format` prints via `format_cell`, plus the unit
      unless percent. A string hero is unchanged.
- [ ] Numeric-typed `ColumnDef` cells print via `format_cell`, right-aligned
      unless `align` is set. Untyped cells are byte-identical.
- [ ] A chart with any `axis: "right"` series has two `yAxis` entries, and
      those series have `yAxisIndex: 1`. Without one, the option is unchanged.
- [ ] Existing infographic HTML tests are green and untouched.

## Validation Commands
- `pytest packages/ai-parrot-visualizations/tests/outputs/test_infographic_html_display_hints.py -q`
- `pytest packages/ai-parrot-visualizations/tests/outputs/test_infographic_lanes_agree.py -q`
- `pytest packages/ai-parrot-visualizations/tests/outputs/test_infographic_html_layouts.py -q`
- `pytest packages/ai-parrot/tests/unit/outputs/test_formats_infographic_html_renderer.py -q`

---

## Agent Instructions

1. Work in the FEAT-623 feature worktree. TASK-3994 and TASK-3996 must be
   `done` in `sdd/tasks/index/infographic-a2ui-display-hints.json`.
2. Re-run every `grep -c` above. Line numbers are as of `344549403`.
3. Implement from the blueprint, complete the `FILL IN`s, and run the
   Validation Commands.
4. Commit only the listed files, then run
   `scripts/sdd/close_task.sh TASK-3997 infographic-a2ui-display-hints verified`.

---

## Completion Note

*(Agent fills this in when done)*
