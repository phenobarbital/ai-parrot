# TASK-2711: Rich DataTable — typed numerics, formatting, sticky header, totals, truncation, search/pagination

**Feature**: FEAT-493 — Backend HTML Design System
**Spec**: `sdd/specs/html-renderer-design-system.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-2710
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 4. `_render_datatable` ignores `TableColumn.type` and
`TableColumn.format` — whose own docstring says they carry *"the minimum
information a frontend grid library needs to render a column correctly"* —
and renders every cell as `str(v)`. No alignment, no currency or percent
formatting, no `tabular-nums`. `total_rows`/`truncated` are dropped too, so
a capped result set presents as complete.

This task is what replaces grid.js. Spec §1 Non-Goals rejects vendoring it:
~40KB plus a companion stylesheet per artifact, on top of the ~200KB inline
Chart.js bundle, for features this table does not need.

---

## Scope

- Add a shared formatting helper (pure, testable, no renderer state) mapping
  `(value, TableColumn.type, TableColumn.format)` → display string:
  thousands separators for `integer`/`number`, `currency`, `percent`,
  `duration`; pass-through for `string`/`boolean`/`date`/`datetime`/`time`/
  `any`. Formatting happens **in Python**, so `ssr-html` and `pdf` come out
  formatted without any JS.
- `_render_datatable` (`interactive_html.py:653`) emits
  `<td class="num" data-v="<raw>">` for numeric-typed columns and plain
  `<td>` otherwise. `data-v` carries the unformatted value.
- Fix the client sort to prefer `data-v` over the visible text — today it
  parses the rendered string, which mis-sorts as soon as thousands
  separators appear. The hook is `[data-sort-table]` / `[data-sort-key]` in
  `_BEHAVIOR_JS` (`interactive_html.py:142`).
- Sticky `<thead>` (CSS lives in `components.css`; this task only ensures the
  markup/classes the CSS expects).
- Total and group rows: a row carrying `parrot_role: "row"` marked as total
  gets `class="total-row"`; group rows get `class="group-row"`.
- Render the truncation notice when `truncated` is true, using `total_rows`:
  "showing N of M rows".
- Search input + pagination in `_BEHAVIOR_JS`, rendered **only** when the row
  count exceeds 100 — a pager over 8 rows is worse UI than none.
- Apply the same typed/formatted cell emission in `ssr_html`'s table path so
  SSR and PDF benefit.

**NOT in scope**: `FilterBar` (TASK-2715/2716); chart rendering; virtual
scrolling; any external table library.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `.../a2ui_renderers/_table_format.py` | CREATE | Pure value formatter keyed on type/format |
| `.../a2ui_renderers/interactive_html.py` | MODIFY | `_render_datatable`, `_BEHAVIOR_JS` sort/search/pagination |
| `.../a2ui_renderers/ssr_html.py` | MODIFY | Typed/formatted cells on the SSR table path |
| `packages/ai-parrot-visualizations/tests/outputs/a2ui_renderers/test_rich_datatable.py` | CREATE | Formatting, alignment, truncation, threshold tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from parrot.models.outputs import StructuredTableConfig, TableColumn
# verified: packages/ai-parrot/src/parrot/models/outputs.py:530, 493
```

### The column contract being honoured

```python
# packages/ai-parrot/src/parrot/models/outputs.py
class TableColumn(BaseModel):                      # line 493
    name: str                                      # line 513 — matches a key in every row dict
    type: str                                      # line 514
    #   string | integer | number | boolean | date | datetime | time | duration | any
    title: str                                     # line 521
    format: Optional[str] = None                   # line 522
    #   currency | percent | email | uri | enum | id | code
    #   "This is a *hint* for the frontend — it does NOT change the base storage type."

class StructuredTableConfig(BaseModel):            # line 530
    columns: List[TableColumn]                     # line 551
    data: List[dict]                               # line 554 — INPUT-ONLY
    explanation: Optional[str]
    total_rows: ...                                # set when data came from a larger dataset
    truncated: ...                                 # True when capped at row_limit
```

`DATATABLE_SCHEMA` is derived from this model via `derive_schema`
(`catalog/parrot/datatable.py:28-32`), so the baked props carry exactly
these key names (`columns`, `totalRows`, `truncated`, `explanation`).

### The renderer method being replaced

```python
# packages/ai-parrot-visualizations/.../interactive_html.py:653-687
def _render_datatable(self, props: dict[str, Any]) -> str:
    columns = props.get("columns") or []
    rows = props.get("data")
    rows = rows if isinstance(rows, list) else []
    title = props.get("title")
    title_html = f'<p class="a2ui-heading">{html.escape(str(title))}</p>' if title else ""
    header_cells = "".join(
        f'<th data-sort-key="{html.escape(str(col.get("name", "")), quote=True)}">'
        f'{html.escape(str(col.get("title") or col.get("name", "")))}</th>'
        for col in columns if isinstance(col, dict)
    )
    # body: f"<td>{html.escape('' if (v := row.get(col.get('name'))) is None else str(v))}</td>"
    #   -> NOTE: type and format are never consulted
    return (
        f'<div class="a2ui-card a2ui-table-wrap">{title_html}'
        f"<table data-sort-table><thead><tr>{header_cells}</tr></thead>"
        f'<tbody>{"".join(body_rows)}</tbody></table></div>'
    )
```

### The existing behaviour hooks (documented at `interactive_html.py:41-46`)

```
[data-sort-table] on a <table> + [data-sort-key] on its <th> cells —
client-side column sort: reorders the ALREADY-rendered <tr> rows by parsed
numeric or lexicographic comparison; no data re-fetch, no re-render from the
data model.
```

That "parsed numeric" comparison operates on visible text — this is the bug
`data-v` fixes.

### Existing tests that must keep passing unmodified

```
packages/ai-parrot-visualizations/tests/outputs/a2ui_renderers/test_interactive_html.py:135-153
    assert "data-sort-table" in doc
    assert 'data-sort-key="division"' in doc
    assert 'data-sort-key="rev"' in doc
    assert "Sales" in doc and "Ops" in doc
    assert "<table" in doc
```

Note `assert "Sales" in doc` — a formatter must not mangle string cells.

### Does NOT Exist

- ~~`TableColumn.align` / `.width` / `.precision`~~ — only `name`, `type`, `title`, `format`
- ~~`format="thousands"` / `"number"` / `"decimal"`~~ — the closed format vocabulary is `currency | percent | email | uri | enum | id | code`; thousands grouping is driven by `type`, not `format`
- ~~a currency-code field~~ — `format="currency"` carries no currency symbol; pick a neutral presentation and do not invent a `currency_code` prop
- ~~grid.js / any table library~~ — explicitly rejected in spec §1 Non-Goals
- ~~`props["rows"]`~~ — the baked key is `data` (`:661`), with `totalRows`/`truncated` alongside
- ~~a server-side pagination endpoint~~ — everything here is client-side over already-baked rows

---

## Implementation Notes

### Keep the formatter pure

```python
def format_cell(value: Any, *, col_type: str, col_format: str | None) -> str:
    """Format one cell for display. Pure: no I/O, no renderer state."""
```

A pure function is testable without constructing an envelope, and it is
shared by three call sites (interactive, SSR, and PDF via SSR).

### Key Constraints

- `data-v` must hold the RAW value, HTML-escaped but unformatted.
- Numeric detection comes from `type`, never from sniffing the value — a
  zip code typed `string` must not be right-aligned or comma-grouped.
- The 100-row threshold is a module constant with a comment explaining it;
  see spec §8, which leaves its final home open.
- Search and pagination are vanilla ES2017 in `_BEHAVIOR_JS`, consistent
  with the existing hooks. No dependency, no build step.
- `None` renders as an empty cell, exactly as today.

### References in Codebase

- `.../interactive_html.py:142-290` — `_BEHAVIOR_JS`, where sort lives and search/pagination go
- `docs/flex_program_report (39).html` lines 118-145 — reference table styling: `table.rep`, `tabular-nums`, `total-row`, `region-row`
- `packages/ai-parrot/src/parrot/outputs/a2ui/catalog/parrot/datatable.py:28-32` — how the schema derives from `StructuredTableConfig`

---

## Acceptance Criteria

- [ ] A `number`/`integer`/`duration` column renders `<td class="num" data-v="…">` with a formatted body; a `string` column does not
- [ ] `format="currency"` and `format="percent"` produce formatted output; `format=None` on a numeric type still gets thousands grouping
- [ ] A `string` cell's text is unchanged (`"Sales"` stays `"Sales"`)
- [ ] Client sort compares `data-v` numerically: a column containing 1000 / 999 / 10000 sorts correctly with separators present
- [ ] `truncated=True` with `total_rows` renders a "showing N of M" notice
- [ ] ≤100 rows renders no search input and no pager; >100 rows renders both
- [ ] Total rows carry `total-row`; group rows carry `group-row`
- [ ] The same formatting appears in `ssr-html` output with no JS present
- [ ] `test_interactive_html.py:135-153` passes **unmodified**
- [ ] Tests pass: `pytest packages/ai-parrot-visualizations/tests/outputs/a2ui_renderers/ -v`
- [ ] `ruff check` and `mypy` clean on changed files

---

## Test Specification

```python
# packages/ai-parrot-visualizations/tests/outputs/a2ui_renderers/test_rich_datatable.py
import pytest
from parrot.outputs.a2ui_renderers._table_format import format_cell


class TestFormatCell:
    @pytest.mark.parametrize("value,col_type,col_format,expected_fragment", [
        (1234567, "integer", None, "1,234,567"),
        (1234.5, "number", "currency", "1,234"),
        (0.427, "number", "percent", "%"),
        ("Sales", "string", None, "Sales"),
        ("90210", "string", None, "90210"),      # a typed string is never grouped
        (None, "number", None, ""),
    ])
    def test_formatting(self, value, col_type, col_format, expected_fragment):
        assert expected_fragment in format_cell(value, col_type=col_type, col_format=col_format)

    def test_pure_no_state(self):
        """Same inputs, same output, no setup required."""
        assert format_cell(1, col_type="integer", col_format=None) == \
               format_cell(1, col_type="integer", col_format=None)


class TestRichTableMarkup:
    async def test_numeric_columns_formatted_and_aligned(self): ...
    async def test_raw_value_in_data_v(self): ...
    async def test_string_column_not_numeric(self): ...
    async def test_truncation_notice_rendered(self): ...
    async def test_no_pager_below_threshold(self): ...
    async def test_pager_above_threshold(self): ...
    async def test_total_and_group_rows(self): ...
    async def test_ssr_output_formatted_without_js(self): ...
```

---

## Agent Instructions

1. **Read the spec** (§3 Module 4) and `docs/flex_program_report (39).html`
   lines 118-145 for the reference table treatment.
2. **Check dependencies** — TASK-2710 must be completed.
3. **Verify the Codebase Contract**, especially the closed `type`/`format`
   vocabularies and the baked prop key `data` (not `rows`).
4. **Update status** in the per-spec index → `"in-progress"`.
5. **Implement** per scope.
6. **Verify** every acceptance criterion; run `test_interactive_html.py`
   first to confirm the pre-existing table assertions still hold.
7. **Move this file** to `sdd/tasks/completed/`, update the index → `"done"`,
   fill in the Completion Note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
