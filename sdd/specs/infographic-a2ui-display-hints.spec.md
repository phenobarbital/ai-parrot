---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
projects: [ai-parrot, ai-parrot-visualizations, admin-ui]
tags: [a2ui, infographic, display-hints, formatting]
---

# Feature Specification: Infographic → A2UI display hints (lossless lowering)

**Feature ID**: FEAT-623
**Date**: 2026-09-30
**Author**: Juan Rodriguez + Claude
**Status**: draft
**Target version**: next minor of `ai-parrot` / `ai-parrot-visualizations`
**Brainstorm**: `sdd/proposals/infographic-a2ui-display-hints.brainstorm.md` (accepted, Option B)

---

## 1. Motivation & Business Requirements

### Problem Statement

`InfographicToolkit` dual-emits every render: an HTML artifact and an A2UI
v1.0 envelope, both built from one `InfographicResponse`. The walkthrough
presents them as "identical content by construction". **They are not.** The
A2UI lane loses meaning that the HTML lane keeps, and the infographic model
can't carry display hints the A2UI wire already supports:

1. **`progress` is lowered lossily.** `ProgressItem.value` is a 0–100
   completion percentage with an optional `target`. `_progress` emits a bare
   `KPICard{label, value}`, dropping the block title, the percent meaning
   and the target. The HTML lane (`_render_progress`) renders all three.
2. **Progress items land in whatever section is open.** In the walkthrough,
   every block ends up in one section.
3. **Tables carry no column semantics.** `ColumnDef` has no `type`/`format`,
   and `_table` drops `align`. So the walkthrough pre-formats cells
   (`"$794.1K"`, `"2.80"`).
4. **There is no dual axis.** `ChartDataSeries` has no axis, so an
   infographic chart can't ask for `seriesAxes`/`yAxisLabels`.
5. **Hero values must be pre-formatted strings**, which contradicts
   FEAT-611's KPICard rule: send a ratio with `format`, never a string.
6. **The adapter docstring is false.** It claims "nothing
   presentation-relevant is dropped any more".

It was found while reviewing navigator-svelte's `a2ui-renderer-visual-polish`
brainstorm, which renders the walkthrough's `02_envelope_v1.json`.

### Goals
- G1: Every infographic display hint reaches the A2UI envelope through
  vocabulary that already exists on the wire: `KPICard.format/unit/
  comparisonPeriod/color`, `DataTable.columns[].type/format`,
  `Chart.seriesAxes/yAxisLabels`.
- G2: `progress` lowers losslessly, as a titled group *inside* the current
  section, never as a new section (more than one section renders as tabs).
- G3: Both Python lanes (infographic HTML and the A2UI `ssr_html` /
  `interactive_html` / PDF renderers) print the same string as the admin
  UI's `formatA2UIValue` for the same `(value, format, unit)`. This is
  pinned by a shared-fixture parity test.
- G4: `infographic_build_block` emits typed table columns from DataFrame
  dtypes.
- G5: The walkthrough sends raw numbers with hints, and its README stops
  claiming parity that doesn't exist.
- G6: The admin UI renders `seriesAxes`/`yAxisLabels` (stop rule in §7).

### Non-Goals (explicitly out of scope)
- No new A2UI wire vocabulary and no catalog version bump. In particular,
  no `compact` value in `format`. Compact is notation, not meaning
  (brainstorm, resolved Q1).
- No new formatter module. `format_cell` is reused and aligned (resolved Q2).
- No change to how renderers *infer*: nothing is guessed from labels or
  magnitudes.
- Embedding `StructuredTableConfig`/`StructuredChartConfig` in blocks was
  rejected; see the brainstorm, Option C.
- Carrying `ColumnDef.align`/`width`/`color` over the wire. They stay
  HTML-lane only and are documented as lossy in the A2UI lane (§8 Q3).
  Extending `TableColumn` is a **follow-up**, see §8.
- navigator-svelte changes. It already honours every hint, and its polish
  work is a separate feature in that repo.

---

## 2. Architectural Design

### Overview

Display semantics become data that flows from the block author to every
renderer:

```
block author (LLM / infographic_build_block / walkthrough)
   │  ColumnDef.type/format · ChartDataSeries.axis · ChartBlock.y_axis_labels
   │  HeroCardBlock.value: str|float + format/unit · ProgressItem (0–100, target)
   ▼
InfographicResponse ──► infographic_html.py ──► format_cell ◄── a2ui_renderers (ssr/interactive/pdf)
   │                    (HTML lane)              (aligned to TS)
   ▼
adapters/infographic.py (lossless lowering)
   │  KPICard{value, format, unit, comparisonPeriod, color}
   │  DataTable.columns[]{name, title, type, format}   (+ align → see §7)
   │  Chart{seriesAxes, yAxisLabels}
   │  progress → Column{Text(title), Row{KPICard{value/100, format:'percent'}}} in the current section
   ▼
A2UI envelope ──► admin UI (formatA2UIValue, AppChart dual axis) · navigator-svelte · A2A peers
```

User-facing behaviour:
- **Goal blocks read as goals.** A "Goal completion" heading is followed by
  KPI cards showing `90.4%`. When a target is set, it shows as neutral
  `vs 80% target` text, never as a coloured delta.
- **Tables are typed.** Numeric cells arrive as numbers with `type`/`format`.
- **Charts with two scales use two axes.**
- **Hero KPIs can be numbers.** `value: 1203456, format: 'currency'` is
  formatted by the renderer. A string value still renders verbatim, for
  hand-written headlines like `$1.20M`.
- **HTML artifacts print the same strings** as the A2UI renderers.

### Component Diagram
See the flow above. There is one shared formatter (`format_cell`), one
adapter and one model module. The admin UI chart path is
`A2UINode → a2ui-chart-adapter.toChartBlockData → InfographicChartBlock →
AppChart` (layerchart).

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `parrot.models.infographic` (`ColumnDef`, `ChartDataSeries`, `ChartBlock`, `HeroCardBlock`) | extends | optional fields only |
| `parrot.outputs.a2ui.adapters.infographic._Converter` | modifies | `_progress`, `_table`, `_chart`, `_hero_card`, `walk` progress branch, module docstring |
| `parrot.outputs.a2ui_renderers._table_format.format_cell` | modifies | add `$` to currency (sign first), add an explicit `number` branch (max 1 decimal), percent max 1 decimal |
| `parrot.outputs.formats.infographic_html` | modifies | hero/table via `format_cell`; second `yAxis` |
| `parrot.tools.infographic_toolkit._build_table_block` | modifies | typed `ColumnDef`s from dtypes |
| `parrot.bots.prompts` / `parrot.models.infographic_templates` | modifies | teach the optional fields |
| admin UI `a2ui-chart-adapter.ts`, `infographic-types.ts`, `InfographicChartBlock.svelte`, `charts/chart-contract.ts` + `AppChart.svelte` | modifies | dual axis (stop rule §7) |
| admin UI `a2ui-format.ts` | modifies | the reference semantics; pins `'en-US'` on both `Intl.NumberFormat`s (§8 Q2) |
| `tests/ui/_vitest.run_vitest` (ai-parrot-server) | uses | runs the TS parity suite from pytest (FEAT-598 pattern) |
| `examples/agents/a2ui/*` | modifies | raw numbers + hints |
| `KPICardComponent` lowering (`catalog/parrot/kpicard.py`) | uses | already carries `format`/`unit`/`comparisonPeriod` to extensions; unchanged |

### Data Models
```python
# packages/ai-parrot/src/parrot/models/infographic.py — additive
class ColumnDef(BaseModel):
    header: str
    width: Optional[str] = None
    align: Optional[Literal["left", "center", "right"]] = None
    color: Optional[str] = None
    type: Optional[str] = None     # NEW — TableColumn.type vocabulary
    format: Optional[str] = None   # NEW — TableColumn.format vocabulary

class ChartDataSeries(BaseModel):
    name: str
    values: List[Union[int, float, None]]
    color: Optional[str] = None
    axis: Optional[SeriesAxis] = None   # NEW — 'left' | 'right'

class ChartBlock(BaseModel):
    ...
    y_axis_label: Optional[str] = None
    y_axis_labels: Optional[List[Optional[str]]] = None   # NEW — [left, right]

class HeroCardBlock(BaseModel):
    ...
    value: Union[str, float] = ""   # WIDENED — a str still renders verbatim
    format: Optional[Literal["percent", "currency", "number"]] = None   # NEW — KPICard.format
    unit: Optional[str] = None      # NEW
```

### New Public Interfaces
None. Only optional fields on existing models change. The `format_cell`
signature is unchanged.

---

## 3. Module Breakdown

#### Delegation-eligible modules

| Module | Eligible? | Decided patterns / exact contracts | Why not (if no) |
|---|---|---|---|
| M1: Model hints | yes | field names/types fixed in §2 Data Models | — |
| M2: Lossless adapter | yes | mapping table in M2; section rule fixed | — |
| M3: `format_cell` alignment + parity | yes | exact strings fixed by the fixture table in M3 | — |
| M4: Infographic HTML lane | yes | call sites fixed; second `yAxis` shape fixed in M4 | — |
| M5: Admin UI dual axis | no | — | layerchart dual-axis approach is not decided; stop rule §7 |
| M6: Typed table columns | yes | dtype → type map fixed in M6 | — |
| M7: LLM contract text | yes | wording guidance in M7 | — |
| M8: Walkthrough + README | yes | values fixed in M8 | — |

### Module 1: Model hints
- **Path**: `packages/ai-parrot/src/parrot/models/infographic.py`
- **Responsibility**: Add the optional fields from §2 Data Models. Keep
  every existing payload valid. Make the record-shape normalizers pass the
  new keys through.
- **Depends on**: none
- **Interface Skeleton**:
  ```python
  # modifies packages/ai-parrot/src/parrot/models/infographic.py
  from parrot.models.outputs import SeriesAxis  # verified: models/outputs.py:329 (pure-model module; check for an import cycle, else redeclare Literal["left","right"])

  class ColumnDef(BaseModel):  # verified: :204
      type: Optional[str] = Field(None, description="Storage type (TableColumn.type vocabulary): string|integer|number|boolean|date|datetime|time|duration|any")
      format: Optional[str] = Field(None, description="Display hint (TableColumn.format vocabulary): currency|percent|... — percent means a RATIO (0.683)")

  class ChartDataSeries(BaseModel):  # verified: :497
      axis: Optional[SeriesAxis] = Field(None, description="'right' puts this series on a second value axis; default left")

  class ChartBlock(BaseModel):  # verified: :511
      y_axis_labels: Optional[List[Optional[str]]] = Field(None, description="[left, right] axis names when any series is on the right")

  class HeroCardBlock(BaseModel):  # verified: :327
      value: Union[str, float] = Field("", description="A formatted string renders verbatim; a number is formatted per `format`")  # :335
      format: Optional[Literal["percent", "currency", "number"]] = Field(None, description="Only applies to a numeric value; percent = ratio")
      unit: Optional[str] = Field(None, description="Appended after a space unless format='percent'")
  ```

### Module 2: Lossless adapter
- **Path**: `packages/ai-parrot/src/parrot/outputs/a2ui/adapters/infographic.py`
  (+ `tests/outputs/a2ui/adapters/test_infographic_adapter.py`,
  `tests/outputs/a2ui/golden/infographic_lowered.json`)
- **Responsibility**:
  - **Titled `progress`**: stays in the **current section** and is added
    as **one** descriptor:
    `Column{children: [Text{text: title}, Row{children: [KPICard…]}]}`.
    It never opens a section. Both A2UI renderers turn more than one
    section into tabs (admin UI `A2UIInfographic.svelte:75`,
    navigator-svelte `parrot/Infographic.svelte:115`), so a new section
    would hide the goals behind a tab. This revises the brainstorm's
    "own section" answer after codex S8; Juan decided it on 2026-09-30.
  - **Untitled `progress`**: `Row{children: [KPICard…]}` in the current
    section.
  - Sectioning policy and section count are unchanged for every payload.
  - **Per item**: `{"label", "value": item.value / 100, "format": "percent"}`,
    plus `"comparisonPeriod": f"vs {fmt(target)}% target"` when `target` is
    not None, plus `"color"` when set. `fmt` writes at most 1 decimal and no
    trailing `.0`. The target never goes in `delta`.
  - `_table`: columns become `{"name", "title"}` plus `type`/`format` when
    the `ColumnDef` sets them. `align`: see §8 Q3.
  - `_chart`: `seriesAxes` is a list parallel to `y`, with `"left"` for
    unset entries. It is emitted only when ≥1 series sets `axis`.
    `yAxisLabels` is emitted when `y_axis_labels` is set.
  - `_hero_card`: forwards `format`/`unit` when set. The value passes
    through unchanged (a str or a number). It uses an explicit `None` check
    instead of `or ""`, so `0` survives (codex S7).
  - Correct the module docstring: the sectioning policy, the mapping table
    row for `progress`, and the "Known lossy degradations" list. The lossy
    list now names `ColumnDef.align`/`width`/`color` (HTML-lane only, §8 Q3).
- **Depends on**: M1
- **Interface Skeleton**:
  ```python
  # modifies packages/ai-parrot/src/parrot/outputs/a2ui/adapters/infographic.py
  class _Converter:  # verified: :220
      def _progress(self, block: dict[str, Any]) -> list[dict[str, Any]]:  # verified: :355
          """One KPICard per item: value/100 with format='percent', target as comparisonPeriod 'vs N% target', color forwarded."""
      def walk(self, blocks, sections, *, depth, seen_title) -> None:  # verified: :532
          """progress branch (:587): adds ONE descriptor to the current section — Column{Text(title), Row{KPICard…}} when titled, Row{KPICard…} when not. Never opens a section."""
  ```

### Module 3: `format_cell` alignment + parity fixtures
- **Path**:
  `packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/_table_format.py`.
  New fixtures go in `packages/ai-parrot/src/parrot/outputs/a2ui/format_contract/fixtures/display_format.json`.
  New tests:
  `packages/ai-parrot-visualizations/tests/outputs/test_format_cell_parity.py`,
  `packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/a2ui-format.parity.test.ts`,
  `packages/ai-parrot-server/tests/ui/test_vitest_a2ui_format_parity.py`.
- **Responsibility**: Align `format_cell` with `formatA2UIValue` for
  `format ∈ {percent, currency, number}`, using `formatA2UIValue` as the
  reference. `formatA2UIValue` pins `'en-US'` on `ONE_DECIMAL_FMT` and
  `CURRENCY_FMT` instead of the browser locale (`undefined`), so every lane
  writes the same string in every browser (§8 Q2). One JSON fixture file is
  read by both suites; the FEAT-598 linked-contract pattern is the
  precedent.
- **Depends on**: none
- **Exact strings (fixture seed, en-US)**:

  | value | format | Python today | TS / target |
  |---|---|---|---|
  | `0.683` | percent | `68.3%` | `68.3%` |
  | `1.0` | percent | `100.0%` | `100%` |
  | `1234.5` | currency | `1,234.50` | `$1,234.50` |
  | `-1234.5` | currency | `-1,234.50` | `-$1,234.50` |
  | `1234.56` | number | `1,234.56` | `1,234.6` |
  | `1903` | number | `1,903` | `1,903` |
  | `"n/a"` | currency | `n/a` | `n/a` (pass-through) |

  The untyped/no-format numeric fallback (`format_cell` :79-81:
  integer → grouped, float → 2 decimals) is **unchanged** and out of parity
  scope. TS passes an unformatted value through raw.
- **Interface Skeleton**:
  ```python
  # modifies packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/_table_format.py
  def format_cell(value: Any, *, col_type: str | None, col_format: str | None = None) -> str:  # verified: :41 — signature unchanged
      """percent: ratio ×100, max 1 decimal, no trailing '.0'; currency: sign, '$', grouped, 2 decimals;
      number: grouped, max 1 decimal; everything else unchanged."""
  ```

### Module 4: Infographic HTML lane
- **Path**: `packages/ai-parrot-visualizations/src/parrot/outputs/formats/infographic_html.py`
- **Responsibility**:
  - `_render_hero_card`: a numeric `value` with `format` goes through
    `format_cell(value, col_type="number", col_format=format)`, plus
    `" " + unit` unless percent. A str value is escaped verbatim, as today.
  - `_render_table`: a `ColumnDef` with numeric `type` formats its cells
    with `format_cell` and right-aligns them, unless `align` is set.
  - `_render_chart`, for bar/line/area: when any series has
    `axis == "right"`, `option["yAxis"]` becomes a list of two value axes
    (names from `y_axis_labels`, falling back to `y_axis_label` on the
    left). Right-axis series get `yAxisIndex: 1`.
- **Depends on**: M1, M3
- **Interface Skeleton**:
  ```python
  # modifies packages/ai-parrot-visualizations/src/parrot/outputs/formats/infographic_html.py
  from parrot.outputs.a2ui_renderers._table_format import format_cell  # verified: a2ui_renderers/_table_format.py:41
  def _render_hero_card(self, block: HeroCardBlock) -> str:  # verified: :745 — `value = escape(block.value)` at :747
  def _render_table(self, block: TableBlock) -> str:  # verified: :1190
  # _render_chart value-axis block: `if block.y_axis_label:` at :962; series loop `for s in block.series:` at :977
  ```

### Module 5: Admin UI dual axis
- **Path**: `packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/a2ui-chart-adapter.ts`,
  `.../canvas/infographic/infographic-types.ts`,
  `.../canvas/infographic/blocks/InfographicChartBlock.svelte`,
  `packages/ai-parrot-server/ui/src/lib/components/charts/chart-contract.ts` + `AppChart.svelte`.
- **Responsibility**:
  - `toChartBlockData` maps `seriesAxes` → `ChartSeriesItem.axis` and
    `yAxisLabels` → `ChartBlockData.y_axis_labels`.
  - `InfographicChartBlock` stops discarding `y_axis_label` (`_y_axis_label`
    :15) and passes the axes into `AppChartConfig`.
  - `AppChart` renders a second value scale for right-axis series.
- **Depends on**: none (the wire already carries `seriesAxes`)
- **Stop rule**: §7. If layerchart (`2.0.0-next.64`) cannot draw a second
  scale within `AppChart` without a redesign, this module ships only the
  adapter/type mapping plus a visible `console.warn`-free degradation
  (single axis, unchanged), and the dual-axis render is split into a
  follow-up spec. The decision is recorded in the task's completion note.
- **Interface Skeleton**:
  ```ts
  // modifies .../canvas/infographic/infographic-types.ts
  export interface ChartSeriesItem {  // verified: :69
    name: string; values: (number | null)[]; color?: string
    axis?: 'left' | 'right'           // NEW
  }
  export interface ChartBlockData { /* ... */ y_axis_label?: string; y_axis_labels?: (string | null)[] /* NEW */ }
  // modifies .../a2ui/a2ui-chart-adapter.ts — after the yAxisLabel line (:79)
  ```

### Module 6: Typed table columns from DataFrames
- **Path**: `packages/ai-parrot/src/parrot/tools/infographic_toolkit.py`
- **Responsibility**: `_build_table_block` emits `ColumnDef{header, type}`
  instead of bare strings. The type comes from the pandas dtype, using
  `pandas.api.types` predicates rather than dtype-name strings:
  - `is_bool_dtype` → `boolean`. This is checked before integer, because
    bool is an integer subtype.
  - `is_integer_dtype`, including nullable `Int64`, → `integer`.
  - `is_float_dtype`, including `Float64`, → `number`.
  - `is_datetime64_any_dtype`, tz-aware included, → `datetime`.
  - `category`, `object`, mixed or anything else → no `type`. The key is
    omitted and the column renders as today.

  It never emits `format`, because a dtype carries no currency or percent
  meaning. Tested in `tests/unit/tools/test_infographic_build_block.py`
  (codex S9).
- **Depends on**: M1
- **Interface Skeleton**:
  ```python
  # modifies packages/ai-parrot/src/parrot/tools/infographic_toolkit.py
  def _build_table_block(...)  # verified: :1608 — `"columns": [str(c) for c in columns],` at :1623
  ```

### Module 7: LLM contract text
- **Path**: `packages/ai-parrot/src/parrot/bots/prompts/__init__.py`,
  `packages/ai-parrot/src/parrot/models/infographic_templates.py`
- **Responsibility**: Teach the optional fields:
  - a hero `value` may be a number with `format`;
  - a ratio goes in as `0.683` with `format: "percent"`;
  - `ColumnDef.type/format`;
  - `series[].axis: "right"` when scales differ.

  Keep the existing `"$3.7M"` example valid, and add one numeric example
  next to it.
- **Depends on**: M1

### Module 8: Walkthrough + README
- **Path**: `examples/agents/a2ui/a2ui_dashboard_walkthrough.py`, `examples/agents/a2ui/synthetic_data.py`, `examples/agents/a2ui/README.md`
- **Responsibility**:
  - Table: `ColumnDef`s with `type`/`format`. MRR is `number` + `currency`
    with raw floats. Churn % is `number` + `percent` as a ratio
    (`churn_rate / 100`). Accounts and NPS are `integer`.
  - Chart: New MRR gets `axis: "right"`, with
    `y_axis_labels: ["MRR (USD)", "New MRR (USD)"]`.
  - The hero card keeps its `as_money` string headline.
  - `build_goals` stays as is (no targets).
  - Step 5's assertions cover the progress section heading, the
    `format: "percent"` KPI cards, `seriesAxes`, and the column hints.
  - README: drop "identical content by construction" as an unqualified
    claim, and document what each lane renders.
- **Depends on**: M1, M2, M4

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_columndef_accepts_type_format` / `test_hero_value_str_or_number` / `test_series_axis_literal` | M1 | optional fields validate; old payloads unchanged |
| `test_progress_titled_is_group_in_current_section` | M2 | section count unchanged; one `Column{Text(title), Row{KPICard…}}` descriptor; untitled → bare `Row` |
| `test_hero_numeric_zero_preserved` | M2 | `value: 0` (and `0.0`) reaches `KPICard.value` as `0`, not `""` (codex S7) |
| `test_progress_zero_and_full` | M2 | `0` → `0.0`, `100` → `1.0`, target `0` → `vs 0% target` |
| `test_progress_item_ratio_percent_and_target` | M2 | `90.4` → `0.904` + `format:'percent'`; target 80 → `comparisonPeriod:'vs 80% target'`; no target → key absent; never `delta` |
| `test_table_forwards_type_format` / `test_chart_series_axes_parallel_to_y` / `test_hero_forwards_format_unit` | M2 | hints forwarded only when set |
| `test_old_payload_envelope_unchanged_except_progress` | M2 | golden diff limited to progress lowering + sectioning |
| `test_format_cell_parity_fixtures` | M3 | pytest over `display_format.json` |
| `a2ui-format.parity.test.ts` (run by `test_vitest_a2ui_format_parity.py`) | M3 | vitest over the same JSON |
| `test_hero_numeric_formatted` / `test_table_numeric_column_formatted` / `test_chart_right_axis_two_yaxes` | M4 | HTML lane |
| `a2ui-chart-adapter` axis mapping test | M5 | `seriesAxes`/`yAxisLabels` → `ChartBlockData` |
| `test_build_table_block_typed_columns` | M6 | the dtype map in M6, incl. nullable `Int64`/`Float64`, `boolean`, tz-aware datetime, `category`/`object` → no type; no `format` ever |
| `test_infographic_lanes_agree` | M2+M4 | one fixture (numeric hero, typed table, titled progress, right-axis chart) → assert the envelope props AND the HTML visible strings / `yAxisIndex` together (codex S10) |

### Integration Tests
| Test | Description |
|---|---|
| walkthrough step 5 assertions (M8) | the generated `02_envelope_v1.json` carries the progress section, percent KPIs, `seriesAxes`, column hints |
| `test_infographic_toolkit_a2ui_wiring.py` (existing) | still green |

### Test Data / Fixtures
- `packages/ai-parrot/src/parrot/outputs/a2ui/format_contract/fixtures/display_format.json`:
  a list of `{value, format, unit?, expected}`, seeded with the M3 table
  (and `unit` cases: `{"value": 3, "format": "number", "unit": "visits", "expected": "3 visits"}`).
- Regenerated `tests/outputs/a2ui/golden/infographic_lowered.json`.

---

## 5. Acceptance Criteria

- [ ] **Wire unchanged**: no new catalog component, no new `KPICard`/`Chart`/`DataTable` property, no catalog version bump. *(Constraint: no wire vocabulary change.)*
- [ ] **Additive models**: every pre-existing infographic test and payload validates unchanged (string hero values, `List[str]` columns, series without `axis`).
- [ ] **Lockstep lanes**: for every fixture row, `format_cell` and `formatA2UIValue` return the same string. This is enforced by pytest and by vitest run from pytest. `formatA2UIValue` pins `'en-US'`, so parity holds regardless of the browser locale; a vitest case runs under a non-English default locale to prove it (codex S6).
- [ ] **Never guess**: no hint is emitted unless declared by the block or derived from a DataFrame dtype. No label or magnitude inference is added anywhere.
- [ ] **Deterministic adapter**: same input → byte-identical envelope. The golden file is regenerated on purpose, and its diff is limited to the progress group plus forwarded hints. The section count is unchanged.
- [ ] **One-way import rule (G8)**: the adapter still imports only the a2ui core and `parrot.models.infographic`.
- [ ] A titled `progress` block produces one `Column{Text(title), Row{KPICard…}}` in the current section, never a new section. Its KPI cards carry `format: 'percent'`. Targets appear only as `comparisonPeriod: 'vs N% target'`.
- [ ] A numeric hero `value` of `0` survives lowering (`_hero_card` no longer uses `or ""`).
- [ ] The module docstring no longer claims nothing is dropped.
- [ ] The infographic HTML renders a numeric hero value and numeric table cells via `format_cell`, and draws a second `yAxis` for right-axis series.
- [ ] M5: either the admin UI draws a second scale, or the stop rule fired and a follow-up spec is linked in the completion note.
- [ ] The walkthrough runs green end to end (`python examples/agents/a2ui/a2ui_dashboard_walkthrough.py`), and its README parity claim is corrected.
- [ ] Changed `ssr_html`/PDF currency/number/percent outputs are reflected in their tests intentionally (no `xfail`/skip).
- [ ] `pytest packages/ai-parrot/tests/outputs/a2ui packages/ai-parrot-visualizations/tests packages/ai-parrot-server/tests/ui -q` green.

---

## 6. Codebase Contract

> Verified against `bc15cdf9c` (branch `sdd/infographic-a2ui-display-hints`, = `origin/dev` 275a8d2bd + brainstorm commits).

### Verified Imports
```python
from parrot.models.infographic import ColumnDef, HeroCardBlock, ChartBlock, ChartDataSeries, TableBlock, ProgressBlock, ProgressItem  # models/infographic.py :204/:327/:511/:497/:749/:916/:901
from parrot.models.outputs import TableColumn, SeriesAxis  # models/outputs.py :557 / :329
from parrot.outputs.a2ui.adapters.infographic import infographic_response_to_envelope  # __all__, :642
from parrot.outputs.a2ui_renderers._table_format import format_cell  # ai-parrot-visualizations, :41
```
```ts
import { formatA2UIValue } from './a2ui-format'  // ui/.../canvas/a2ui/a2ui-format.ts
import { run_vitest } from '._vitest'            // python: packages/ai-parrot-server/tests/ui/_vitest.py:14 `def run_vitest(*files: str) -> None`
```

### Existing Class Signatures
```python
# packages/ai-parrot/src/parrot/models/infographic.py
class ColumnDef(BaseModel):          # :204 header, width, align: Literal[left|center|right], color (:210)
class HeroCardBlock(BaseModel):      # :327 label, value: str (:335), icon, trend, trend_value, comparison_period, color
class ChartDataSeries(BaseModel):    # :497 name, values (:501), color
class ChartBlock(BaseModel):         # :511 chart_type, title, description, labels, series, x_axis_label, y_axis_label (:521), stacked, show_legend, layout, color_by_sign, ...
    # _normalize_chart_data  @model_validator(mode="before")  :583
class TableBlock(BaseModel):         # :749 columns: Union[List[str], List[ColumnDef]], rows, sortable, style
    # _normalize_table_data  @model_validator(mode="before")  :767-769
class ProgressItem(BaseModel):       # :901 label, value: float ge=0 le=100 (:905), color, target: Optional[float] ge=0 le=100 (:907)
class ProgressBlock(BaseModel):      # :916 title: Optional[str], items: List[ProgressItem]

# packages/ai-parrot/src/parrot/models/outputs.py
SeriesAxis = Literal["left", "right"]   # :329
# StructuredChartConfig.y_axis_labels alias "yAxisLabels" :397 ; series_axes alias "seriesAxes" :407
class TableColumn(BaseModel):           # :557 name, type, title, format

# packages/ai-parrot/src/parrot/outputs/a2ui/adapters/infographic.py
# docstring: mapping row ``progress`` :40 ; "nothing presentation-relevant is dropped any more" :55
class _SectionAccumulator:  # :172 open(*, heading=None, text=None) :183 ; close() :188 ; add() :201 ; set_text() :206 ; result() :214
class _Converter:           # :220
    def _chart(self, block) -> dict        # :236 ; `if block.get("y_axis_label") is not None:` :283
    def _table(self, block) -> dict        # :295 ; `"columns": [{"name": name, "title": name} for name in names],` :315
    def _hero_card(self, block) -> dict    # :323
    def _progress(self, block) -> list     # :355
    def walk(self, blocks, sections, *, depth, seen_title)  # :532 ; `elif block_type == "progress":` :587

# packages/ai-parrot/src/parrot/outputs/a2ui/catalog/parrot/kpicard.py
# KPICARD_SCHEMA :15 (format enum :43); lowering carries parrot_unit (:140) / parrot_value_format (:145) / comparisonPeriod

# packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/_table_format.py
NUMERIC_TYPES = frozenset({"integer", "number", "duration"})
def format_cell(value, *, col_type, col_format=None) -> str   # :41 ; percent :75-76 ; `if col_format == "currency":` :77 ; fallback :79-81
# _semantics.py: kpi_value_display :135 (calls format_cell with col_type="number") ; kpi_comparison_html :164

# packages/ai-parrot-visualizations/src/parrot/outputs/formats/infographic_html.py
_CURRENCY_FORMATTER_JS  # :141
def _render_hero_card(self, block) -> str   # :745 ; `value = escape(block.value)` :747
def _is_currency_axis(block) -> bool        # :818
def _render_chart(...)  # value axis `if block.y_axis_label:` :962 ; series loop :977
def _render_table(self, block) -> str       # :1190
def _render_progress(self, block) -> str    # :1329

# packages/ai-parrot/src/parrot/tools/infographic_toolkit.py
def _build_chart_block(...)  # :1571
def _build_table_block(...)  # :1608 ; `"columns": [str(c) for c in columns],` :1623

# packages/ai-parrot/src/parrot/bots/prompts/__init__.py :83 — hero_card example `"value": "$3.7M"`
```
```ts
// packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/a2ui-format.ts
const ONE_DECIMAL_FMT = new Intl.NumberFormat(undefined, { maximumFractionDigits: 1 })   // :16
export function formatA2UIValue(value: unknown, format?: unknown, unit?: unknown): unknown
// .../a2ui/a2ui-chart-adapter.ts : toChartBlockData(properties, dataModel): ChartBlockData ; yAxisLabel line :79
// .../infographic/infographic-types.ts : interface ChartSeriesItem :69 ; ChartBlockData.y_axis_label :83
// .../infographic/blocks/InfographicChartBlock.svelte : `y_axis_label: _y_axis_label,` :15 (received, unused) ; renders AppChart (layerchart)
// .../a2ui/A2UINode.svelte :221 passes comparison_period to the KPI card
```

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| progress section | `_SectionAccumulator.open/close` | method call | `adapters/infographic.py:183,188` |
| hero/table formatting | `format_cell` | import | `a2ui_renderers/_table_format.py:41` |
| parity fixture (TS side) | `resolve(process.cwd(), '../../ai-parrot/src/parrot/outputs/a2ui/...')` | node fs | precedent `ui/.../a2ui/linked/dsl.test.ts:7` |
| parity (pytest → vitest) | `run_vitest(...)` | function call | `ai-parrot-server/tests/ui/_vitest.py:14` |

### Does NOT Exist (Anti-Hallucination)
- ~~`ColumnDef.type` / `ColumnDef.format`~~, ~~`ChartDataSeries.axis`~~, ~~`ChartBlock.y_axis_labels`~~, ~~`HeroCardBlock.format` / `.unit`~~: added by M1.
- ~~A `target` prop on `KPICard`~~: the target travels as `comparisonPeriod` text.
- ~~A `compact` value in any `format` enum~~: deliberately not added.
- ~~An explicit `col_format == "number"` branch in `format_cell`~~: added by M3. Today `number` falls through to the 2-decimal fallback.
- ~~Dual-axis support in the admin UI chart stack~~: no axis concept in `charts/chart-contract.ts`, and `InfographicChartBlock` discards `y_axis_label`.
- ~~`outputs/a2ui/format_contract/`~~: new directory (M3).
- The ai-parrot `.venv` in the main checkout has no `pydantic` (observed 2026-09-30). Run the tests from an env that has the workspace installed (`uv sync`).

### Edit Sites (Blueprint Anchors)

Verified against: `bc15cdf9c`

| File | Action | Verbatim anchor line | Verified at | Occurrences |
|---|---|---|---|---|
| `packages/ai-parrot/src/parrot/models/infographic.py` | MODIFY | `color: Optional[str] = Field(None, description="Accent color for the column header")` | `:210` | 1 |
| `packages/ai-parrot/src/parrot/models/infographic.py` | MODIFY | `values: List[Union[int, float, None]] = Field(..., description="Data values corresponding to labels")` | `:501` | 1 |
| `packages/ai-parrot/src/parrot/models/infographic.py` | MODIFY | `y_axis_label: Optional[str] = Field(None, description="Y-axis label")` | `:521` | 1 |
| `packages/ai-parrot/src/parrot/models/infographic.py` | MODIFY | `    value: str = Field(` (HeroCardBlock) | `:335` | 1 |
| `packages/ai-parrot/src/parrot/models/infographic.py` | MODIFY | `def _normalize_table_data(cls, values: Any) -> Any:` | `:769` | 1 |
| `packages/ai-parrot/src/parrot/outputs/a2ui/adapters/infographic.py` | MODIFY | `def _progress(self, block: dict[str, Any]) -> list[dict[str, Any]]:` | `:355` | 1 |
| `packages/ai-parrot/src/parrot/outputs/a2ui/adapters/infographic.py` | MODIFY | `elif block_type == "progress":` | `:587` | 1 |
| `packages/ai-parrot/src/parrot/outputs/a2ui/adapters/infographic.py` | MODIFY | `"columns": [{"name": name, "title": name} for name in names],` | `:315` | 1 |
| `packages/ai-parrot/src/parrot/outputs/a2ui/adapters/infographic.py` | MODIFY | `if block.get("y_axis_label") is not None:` | `:283` | 1 |
| `packages/ai-parrot/src/parrot/outputs/a2ui/adapters/infographic.py` | MODIFY | `def _hero_card(self, block: dict[str, Any]) -> dict[str, Any]:` | `:323` | 1 |
| `packages/ai-parrot/src/parrot/outputs/a2ui/adapters/infographic.py` | MODIFY | `"value": block.get("value") or "",` | `:326` | 1 |
| `packages/ai-parrot/tests/unit/tools/test_infographic_build_block.py` | MODIFY | (append dtype tests) | — | — |
| `packages/ai-parrot/src/parrot/outputs/a2ui/adapters/infographic.py` | MODIFY | `nothing presentation-relevant is dropped any more):` | `:55` | 1 |
| `packages/ai-parrot/src/parrot/outputs/a2ui/adapters/infographic.py` | MODIFY | ` ``progress``       one ``KPICard`` per item` | `:40` | 1 |
| `packages/ai-parrot/tests/outputs/a2ui/golden/infographic_lowered.json` | MODIFY | (regenerated) | — | — |
| `packages/ai-parrot/tests/outputs/a2ui/adapters/test_infographic_adapter.py` | MODIFY | (append tests) | — | — |
| `packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/_table_format.py` | MODIFY | `if col_format == "currency":` + next line `return f"{number:,.2f}"` (that line occurs 2× — :78 and :81; anchor on the currency pair) | `:77-78` | 1 (pair) |
| `packages/ai-parrot/src/parrot/outputs/a2ui/format_contract/fixtures/display_format.json` | CREATE | — | — | — |
| `packages/ai-parrot-visualizations/tests/outputs/test_format_cell_parity.py` | CREATE | — | — | — |
| `packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/a2ui-format.parity.test.ts` | CREATE | — | — | — |
| `packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/a2ui-format.ts` | MODIFY | `const ONE_DECIMAL_FMT = new Intl.NumberFormat(undefined, { maximumFractionDigits: 1 });` and `const CURRENCY_FMT = new Intl.NumberFormat(undefined, { style: 'currency', currency: 'USD' });` | `:16-17` | 1 each |
| `packages/ai-parrot-server/tests/ui/test_vitest_a2ui_format_parity.py` | CREATE | — | — | — |
| `packages/ai-parrot-visualizations/src/parrot/outputs/formats/infographic_html.py` | MODIFY | `value = escape(block.value)` | `:747` | 1 |
| `packages/ai-parrot-visualizations/src/parrot/outputs/formats/infographic_html.py` | MODIFY | `def _render_table(self, block: TableBlock) -> str:` | `:1190` | 1 |
| `packages/ai-parrot-visualizations/src/parrot/outputs/formats/infographic_html.py` | MODIFY | `if block.y_axis_label:` then `option["yAxis"]["name"] = str(escape(block.y_axis_label))` | `:962-963` | 1 |
| `packages/ai-parrot-visualizations/src/parrot/outputs/formats/infographic_html.py` | MODIFY | `for s in block.series:` — the occurrence directly after `option["series"] = []` at :976 | `:977` | 3 (use :976-977 context) |
| `packages/ai-parrot/src/parrot/tools/infographic_toolkit.py` | MODIFY | `"columns": [str(c) for c in columns],` | `:1623` | 1 |
| `packages/ai-parrot/src/parrot/bots/prompts/__init__.py` | MODIFY | `block={"type": "hero_card", "label": "Revenue", "value": "$3.7M"})` | `:83` | 1 |
| `packages/ai-parrot/src/parrot/models/infographic_templates.py` | MODIFY | (unverified — check before use: dashboard contract text for hero/table/chart) | — | — |
| `packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/a2ui-chart-adapter.ts` | MODIFY | `if (typeof properties.yAxisLabel === 'string') data.y_axis_label = properties.yAxisLabel;` | `:79` | 1 |
| `packages/ai-parrot-server/ui/src/lib/components/agents/canvas/infographic/infographic-types.ts` | MODIFY | `export interface ChartSeriesItem {` | `:69` | 1 |
| `packages/ai-parrot-server/ui/src/lib/components/agents/canvas/infographic/blocks/InfographicChartBlock.svelte` | MODIFY | `y_axis_label: _y_axis_label,` | `:15` | 1 |
| `packages/ai-parrot-server/ui/src/lib/components/charts/chart-contract.ts` / `AppChart.svelte` | MODIFY | (unverified — check before use: no axis concept today) | — | — |
| `examples/agents/a2ui/a2ui_dashboard_walkthrough.py` | MODIFY | `{"name": "New MRR", "values": [float(v) for v in monthly["new_mrr"]]},` | `:320` | 1 |
| `examples/agents/a2ui/a2ui_dashboard_walkthrough.py` | MODIFY | `as_money(float(row["mrr"])),` | `:342` | 1 |
| `examples/agents/a2ui/README.md` | MODIFY | (parity claim + lane table) | — | — |

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- Additive Pydantic fields with `Field(None, description=...)`. The
  descriptions are LLM-facing, so state the ratio rule explicitly.
- The adapter stays pure. Use `_descriptor`/`_clean` and omit keys whose
  value is None. Never invent values (the FEAT-527 convention in `_chart`).
- Shared TS/Python contract fixtures follow FEAT-598: JSON under
  `ai-parrot/src/parrot/outputs/a2ui/.../fixtures/`, read by vitest via
  `resolve(process.cwd(), '../../ai-parrot/...')` and run from pytest via
  `tests/ui/_vitest.run_vitest`.
- Golden files are regenerated on purpose, and the diff is reviewed in the
  PR, never loosened.

### Known Risks / Gotchas
- **`format_cell` blast radius**: currency gains `$`, percent drops a
  trailing `.0`, and `number` gets 1 decimal. This changes `ssr_html`,
  `interactive_html` and PDF output for KPI and DataTable cells that
  declare those formats. Update their tests on purpose (§8 Q1).
- **Locale**: `formatA2UIValue` used `Intl.NumberFormat(undefined, …)`, the
  browser's locale. It is now pinned to `'en-US'` (§8 Q2). This is a
  visible change for admin UI users on non-English browsers, by decision.
- **No sectioning change, on purpose**: more than one section renders as
  tabs in both A2UI renderers, so `progress` becomes a group inside the
  current section. Renderers that lay out top-level KPI cards in a grid
  must also lay out a nested `Row` of KPI cards sensibly. navigator-svelte
  FEAT-654 records this.
- **Hero value `0`**: `_hero_card` builds `"value": block.get("value") or ""`
  (`adapters/infographic.py:326`), which turns a numeric `0` into `""`.
  Widening `HeroCardBlock.value` to `float` makes this a live bug. Use an
  explicit `None` check (codex S7).
- **Percent misuse**: `90.4` with `format: 'percent'` renders `9040%`. The
  adapter divides only for `ProgressItem`, whose 0–100 range the model
  guarantees (`ge=0, le=100`). Elsewhere the contract says ratio, and M7
  says so explicitly.
- **`seriesAxes` on axis-less charts** (pie/donut/gauge): forwarded
  unfiltered; renderers ignore it.
- **M5 stop rule**: AppChart is layerchart `2.0.0-next.64` with no axis
  abstraction. If a second scale needs an AppChart redesign, ship the
  mapping only and split the render into a follow-up spec. Do not build a
  second chart stack.
- **Import cycle**: `models/infographic.py` importing `SeriesAxis` from
  `models/outputs.py`. Verify there is no cycle; otherwise redeclare the
  `Literal` locally with a comment pointing at `outputs.py:329`.
- **Dev environment**: the main checkout's `.venv` lacks `pydantic`. Use a
  synced env (`uv sync`) for tests.

### External Dependencies
| Package | Version | Reason |
|---|---|---|
| — | — | none new (`pydantic`, `vitest`, `layerchart` already present) |

---

## 8. Open Questions

- [x] Scope — *Resolved in brainstorm*: Adapter + model + example (Option B).
- [x] How a progress item lowers — *Resolved in brainstorm*: `KPICard` with ratio + `format='percent'`, and the target as text. No catalog change.
- [x] Titled progress block gets its own section — *Resolved in brainstorm*: Yes. **Revised at spec time (Juan, 2026-09-30, after codex S8)**: no. It is a `Column{Text(title), Row{KPICard…}}` group inside the current section, because more than one section renders as tabs.
- [x] HTML lane formatting — *Resolved in brainstorm*: Reuse `format_cell`, aligned to `a2ui-format.ts` (the reference), pinned by a shared-fixture parity test.
- [x] Hero value shape — *Resolved in brainstorm*: `value: str | float` plus optional `format`/`unit`.
- [x] Compact currency — *Resolved in brainstorm*: No. A hand-written headline stays a string. Any future need is a separate `notation` prop, never a `format` value.
- [x] Admin UI `seriesAxes` — *Resolved in brainstorm*: In this feature, as its own module (M5), with the §7 stop rule added at spec time after AppChart was found to have no axis concept.
- [x] Target in `comparisonPeriod` or `delta` — *Resolved in brainstorm*: `comparisonPeriod`, worded `vs N% target`, and omitted when there is no target.
- [x] Q1: Is changing `format_cell`'s currency/percent/number output acceptable for existing `ssr_html`/PDF consumers? — *Owner: Jesús; answered by Juan, 2026-09-30*: Yes.
- [x] Q2: Should `formatA2UIValue` pin `'en-US'` instead of `undefined` (the browser locale)? — *Owner: Jesús; answered by Juan, 2026-09-30*: Yes. Pinned in M3.
- [x] Q3: `ColumnDef.align`/`width`/`color` on the wire? — *Owner: Jesús; answered by Juan, 2026-09-30*: Leave them as they are for now. They are dropped in the A2UI lane and documented as lossy (M2). Extending `TableColumn` is a follow-up.
- [ ] **Follow-up (not this feature)**: extend `TableColumn` with `align`/`width`/`color`, so `ColumnDef`'s styling survives the A2UI lane. This is a wire change: catalog + both renderers. — *Owner: Jesús*

---

## 9. Design Research Cross-Check

> Model: `gpt-5.6-luna` · Status: completed (rc=0, schema-valid; every `affected_paths` entry contained and `test -e` OK)
> · Transcript: `sdd/state/FEAT-623/design_research/`

| # | Suggestion (kind) | Disposition | Reason | Landed in |
|---|---|---|---|---|
| S1 | Progress targets have no A2UI destination (architecture) | CONFIRM | Accepted explicitly: the target travels as `comparisonPeriod` text, and the title as a `Text` in the group | §2, M2 |
| S2 | Define 0–100 → ratio conversion (api) | CONFIRM | Already `value/100`; zero, full and target-zero cases added | M2, §4 |
| S3 | Dual axes in the template HTML lane too (architecture) | CONFIRM | Already M4: second `yAxis` + `yAxisIndex` | M4 |
| S4 | Admin chart scope includes AppChart (architecture) | CONFIRM | Matches the spec-time finding; M5 lists AppChart/chart-contract, with a stop rule | M5, §7 |
| S5 | Table `align`/`width`/`color` contract unaddressed (api) | ESCALATE | Needs a wire decision; recommended: drop and document | §8 Q3 |
| S6 | Parity needs a locale policy (risk) | ESCALATE | AC now scoped to en-US with vitest pinned; pinning TS to en-US is Jesús's call | §5, §8 Q2 |
| S7 | Hero value `0` discarded by `or ""` (risk) | CONFIRM | Verified at `adapters/infographic.py:326`; explicit None check + test | M2, §4, §5, §7 |
| S8 | Specify progress sectioning; >1 section → tabs (architecture) | CONFIRM (decision revised) | Verified in both renderers (`A2UIInfographic.svelte:75`, navigator `Infographic.svelte:115`). Juan chose a group inside the current section over a new section | M2, §5, §7, §8 |
| S9 | Bounded, tested dtype inference (api) | CONFIRM | Explicit `pandas.api.types` map incl. nullable/tz/category | M6, §4 |
| S10 | End-to-end lane parity test (testing) | CONFIRM | `test_infographic_lanes_agree` added | §4 |

Summary: **8** confirmed · **0** rejected · **2** escalated.

---

## Worktree Strategy

- **Isolation**: one feature worktree; `sdd-coder` gives each task its own
  sub-worktree.
- **Module dependency graph**:
  - M2 → M1: the adapter reads `ColumnDef.type/format`, `axis`,
    `y_axis_labels`, and hero `format`/`unit`.
  - M4 → M1, M3: it renders the new fields with the aligned `format_cell`.
  - M6 → M1: it builds `ColumnDef(type=…)`.
  - M7 → M1: it documents the fields.
  - M8 → M1, M2, M4: the walkthrough asserts the envelope and renders the
    HTML.
  - M3 and M5 have no edges: they run concurrently with M1.
- **Shared files**: `models/infographic.py` (M1 only). No file is modified
  by two modules.
- **Exclusive resources**: the golden regeneration (M2) and the walkthrough
  run (M8) write generated files; mark both `parallel: false`. M5 needs the
  admin UI `node_modules` / vitest.
- **Cross-feature dependencies**: none in ai-parrot. Downstream,
  navigator-svelte's `a2ui-renderer-visual-polish` should regenerate its
  parrot fixture after this lands.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-09-30 | Juan Rodriguez + Claude | Initial draft from the accepted brainstorm; M5 stop rule and §8 Q1–Q3 added after spec-time verification; codex design research folded in (§9), progress-as-group decision; §8 Q1–Q3 answered (en-US pin, align/width/color follow-up) |
