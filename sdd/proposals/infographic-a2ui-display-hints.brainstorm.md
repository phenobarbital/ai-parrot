---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
# projects: parts of the codebase this doc concerns. Use `packages/*` dir names
#   (ai-parrot, ai-parrot-server, parrot-formdesigner, …) or an area
#   (sdd-tooling, dev-loop, admin-ui, docs, ci). Unknown values warn, not fail.
projects: [ai-parrot, ai-parrot-visualizations]
# tags: free-form kebab-case keywords for organizing specs (e.g. memory, mcp).
tags: [a2ui, infographic, display-hints, formatting]
---

# Brainstorm: Infographic → A2UI display hints (lossless lowering)

**Date**: 2026-09-30
**Author**: Juan Rodriguez + Claude
**Status**: accepted
**Recommended Option**: B

---

## Problem Statement

`InfographicToolkit` dual-emits every render: an HTML artifact and an A2UI
v1.0 envelope, both built from the same `InfographicResponse`. The
walkthrough (`examples/agents/a2ui/a2ui_dashboard_walkthrough.py`) presents
them as "identical content by construction". **They are not.** The A2UI lane
loses meaning that the HTML lane keeps, and the infographic model can't carry
the display hints that the A2UI wire already supports.

This came up while reviewing navigator-svelte's A2UI renderer polish
brainstorm (`navigator-svelte: sdd/proposals/a2ui-renderer-visual-polish.brainstorm.md`,
branch `chore/a2ui-parrot-envelope-compare`). That review rendered the
walkthrough's `02_envelope_v1.json` and found that several "renderer defects"
are really defects in the envelope:

1. **`progress` is lowered lossily.** `ProgressItem.value` is, by contract,
   a 0–100 completion percentage with an optional `target`
   (`models/infographic.py:905-907`). The adapter's `_progress`
   (`adapters/infographic.py:355`) emits a bare `KPICard{label, value}`
   for each item. The block `title` ("Goal completion"), the percent meaning
   and the target are all dropped. A consumer receives `ARR target: 90.4`
   with no way to know it means 90.4 %. The HTML lane (`_render_progress`,
   `infographic_html.py:1329`) renders the title, `90%`, a bar and the
   target marker.
2. **Progress items land in whatever section is open.** The adapter opens
   sections only on `title`/`divider` blocks. In the walkthrough, the hero
   card, both charts, the table and the three goal KPIs all end up in **one**
   section. Renderers therefore cannot group the goals.
3. **Tables carry no column semantics.** `ColumnDef` has `header`, `width`,
   `align` and `color`, but no `type` or `format`
   (`models/infographic.py:204`). `_table` (`adapters/infographic.py:295`)
   also drops `align`. The wire's `TableColumn` already has `type` and
   `format` (`models/outputs.py:557`), and both renderers honour them, but
   nothing can reach them. So the walkthrough pre-formats cells
   (`as_money(...)` → `"$794.1K"`, `f"{churn:.2f}"` → `"2.80"`), and a
   renderer can't sort, align or reformat those strings.
4. **There is no dual axis.** `ChartDataSeries` has `name`, `values` and
   `color` only (`models/infographic.py:497`). The A2UI `Chart` schema
   accepts `seriesAxes` and `yAxisLabels` (`models/outputs.py:397-410`,
   `catalog/parrot/chart.py:38-44`), but an infographic chart can't ask for
   them. "New MRR" (~50K) shares an axis with "MRR" (~1.2M) and sits flat
   on the floor.
5. **Hero values must be pre-formatted strings.** `HeroCardBlock.value: str`
   (`models/infographic.py:335`). `KPICard` accepts `format` and `unit`
   (`catalog/parrot/kpicard.py:43-63`, FEAT-611: "send a ratio as 0.683 with
   format='percent', never as the string '68.3%'"). The infographic path
   cannot follow that rule.
6. **The adapter docstring is false.** It states that "nothing
   presentation-relevant is dropped any more" (`adapters/infographic.py:52-55`).
   Items 1 and 3 show otherwise.

**Who is affected**: every consumer of `InfographicToolkit`'s A2UI lane:
navigator-svelte (`[programs]/reporting`, shared surfaces), the parrot admin
UI, and A2A peers. The renderers are currently asked to *guess* meaning
(e.g. navigator-svelte's `isRatioLike()` label heuristic), which is exactly
what FEAT-611 says renderers must never do.

## Constraints & Requirements

- **No change to the A2UI wire vocabulary.** Every hint in this brainstorm
  already exists on the catalog components (`KPICard.format/unit/delta/
  comparisonPeriod`, `DataTable.columns[].type/format`, `Chart.seriesAxes/
  yAxisLabels`). This feature only makes the infographic path *produce*
  them. No catalog version bump.
- **Additive model changes only.** Every new field on the infographic models
  is optional, and today's payloads validate unchanged: a `str` hero value,
  `List[str]` table columns and series without an axis.
- **The two lanes stay in lockstep.** Whatever the A2UI lane forwards, the
  HTML lane must render with the same meaning. A raw number with
  `format='currency'` must not show up as `794058.66` in HTML.
- **Never guess.** A hint is forwarded only when the block declares it, or
  when it is derived from a typed source (a DataFrame dtype in
  `infographic_build_block`). Nothing is inferred from labels.
- **The adapter stays pure and deterministic.** Same input → byte-identical
  envelope (adapter docstring, spec G2/D1a). The golden file is updated on
  purpose, not loosened.
- **The one-way import rule (G8) holds.** The adapter imports only the a2ui
  core and `parrot.models.infographic`.

---

## Options Explored

### Option A: Lossless adapter only

Fix the lowering without touching the models:

- `progress` opens its own section (`heading` = block title). Each item
  becomes `KPICard{value: value/100, format: 'percent'}`, with the target as
  `comparisonPeriod`/`delta` text and `color` forwarded.
- `_table` forwards `ColumnDef.align`.
- Correct the docstring.

✅ **Pros:**
- Small: one module plus the golden file.
- Fixes problems 1, 2 and 6 at once.

❌ **Cons:**
- Tables, dual axis and hero values (3, 4, 5) stay impossible to express.
  The walkthrough keeps pre-formatting, and renderers keep guessing.

📊 **Effort:** Low

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| — | — | no new dependency |

🔗 **Existing Code to Reuse:**
- `packages/ai-parrot/src/parrot/outputs/a2ui/adapters/infographic.py` — `_Converter._progress`, `_table`, `_SectionAccumulator.open/close`
- `packages/ai-parrot/tests/outputs/a2ui/golden/infographic_lowered.json` — golden envelope

---

### Option B: End-to-end display hints (model → adapter → both lanes → example)

Treat display semantics as data that flows from the block author to every
renderer:

1. **Model (additive)**:
   - `ColumnDef` gains optional `type` and `format`, reusing the
     `TableColumn` vocabulary from `models/outputs.py:557`.
   - `ChartDataSeries` gains optional `axis: SeriesAxis` (`'left' | 'right'`,
     `models/outputs.py:329`), and `ChartBlock` gains optional
     `y_axis_labels`.
   - `HeroCardBlock.value` widens to `str | float`, with optional `format`
     and `unit`. A string is still rendered verbatim.
2. **Adapter**:
   - Everything Option A does.
   - Forwards `ColumnDef.type/format` → `DataTable.columns[]`, series axes →
     `seriesAxes` (plus `yAxisLabels`), and hero `format/unit` → `KPICard`.
3. **HTML lane — reuse, don't write, a formatter**:
   - The infographic HTML renderer reuses `format_cell`
     (`ai-parrot-visualizations/.../a2ui_renderers/_table_format.py:41`,
     FEAT-493). The A2UI `ssr_html` / `interactive_html` / PDF renderers
     already use it for `DataTable` cells, and `kpi_value_display`
     (`_semantics.py:135`) uses it for `KPICard.format`.
   - `_render_hero_card` and `_render_table` call it, so every Python lane
     prints the same string for the same value.
   - **Align `format_cell` with `a2ui-format.ts`, which is the reference**
     (it is what users see live). Today they disagree:

     | Format | `format_cell` | `formatA2UIValue` |
     |---|---|---|
     | currency | `1,234.56`, no symbol | `$1,234.56` |
     | number | 2 decimals | max 1 decimal |

     After alignment, `format_cell` writes `$` for currency and at most 1
     decimal for number.
   - A parity test runs shared JSON fixtures through pytest
     (`format_cell`) and vitest (`formatA2UIValue`), and fails on any drift.
   - The infographic HTML chart honours `axis: 'right'`. The A2UI Python
     renderers already do (`interactive_html.py`, `echarts.py`).
4. **Admin UI**: its Svelte renderer gains `seriesAxes` / `yAxisLabels`
   support. It is the only parrot renderer that lacks it. Without it, the
   walkthrough's new hint would be ignored by parrot's own UI ("implemented
   but never wired").
5. **Toolkit**: `_build_table_block` derives `ColumnDef.type` from the
   DataFrame dtype (`integer`/`number`), a typed source rather than a guess.
6. **Example**:
   - The walkthrough sends raw numbers with hints: MRR `currency`, churn
     `percent` as a ratio, and New MRR on the right axis with
     `y_axis_labels=['USD', 'USD (new)']`.
   - The README stops claiming parity that doesn't exist.

✅ **Pros:**
- Closes all six problems at the source. Renderers stop guessing.
- The wire is unchanged, so navigator-svelte and the admin UI pick it up
  with no protocol work. Both already honour `format`, and navigator-svelte
  also honours `seriesAxes` and column `type`.
- The HTML lane and the A2UI lane really are identical by construction.

❌ **Cons:**
- It touches the models and adapter in `ai-parrot`, the HTML renderers in
  `ai-parrot-visualizations`, the admin UI, and the walkthrough.
- Aligning `format_cell` with TS changes today's `ssr_html` / PDF output
  for currency and `number` cells: currency gains `$`, and `number` drops
  to 1 decimal. Their golden or snapshot tests move on purpose.
- LLM-facing prompts (`bots/prompts/__init__.py:80-83`, which shows
  `"value": "$3.7M"`) and the template contract need updating, so the model
  learns the new optional fields.

📊 **Effort:** Medium

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `pydantic` | optional fields on the block models | already the model layer |
| `format_cell` (in-repo) | the one Python display formatter | already shared by `ssr_html` / `interactive_html` / PDF; no new module |
| `vitest` | TS side of the parity test | already the admin UI test runner |

🔗 **Existing Code to Reuse:**
- `packages/ai-parrot/src/parrot/models/outputs.py` — `TableColumn` (type/format vocabulary), `SeriesAxis`
- `packages/ai-parrot/src/parrot/outputs/a2ui/catalog/parrot/kpicard.py` — `format`/`unit` contract and instructions
- `packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/a2ui-format.ts` — `formatA2UIValue`, the reference semantics
- `packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/_table_format.py` — `format_cell` (:41), `is_numeric_column`, `NUMERIC_TYPES`
- `packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/_semantics.py` — `kpi_value_display` (:135), `kpi_comparison_html` (:164)
- `packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/a2ui-chart-adapter.ts` — where the admin UI's `seriesAxes` support lands
- `packages/ai-parrot-visualizations/src/parrot/outputs/formats/infographic_html.py` — `_render_hero_card` (:745), `_render_table` (:1190), `_render_progress` (:1329), `_CURRENCY_FORMATTER_JS` (:141)
- `packages/ai-parrot/src/parrot/tools/infographic_toolkit.py` — `_build_table_block` (:1608), `_build_chart_block` (:1571)

---

### Option C: Let infographic blocks embed the structured output models

Instead of growing `ColumnDef`/`ChartDataSeries`, let a `table`/`chart`
block carry a `StructuredTableConfig`/`StructuredChartConfig`
(`models/outputs.py`), which already has `columns[].type/format`,
`series_axes` and `y_axis_labels`. The adapter would pass those through.

✅ **Pros:**
- No parallel vocabulary. One model per concept.

❌ **Cons:**
- There would be two ways to write a table block. The LLM contract and the
  `TableBlock`/`ChartBlock` record normalizers would have to understand both.
- The HTML lane would need to render `Structured*Config`, which it doesn't
  today. The change is larger than B for the same result.
- Positional template contracts (`infographic_templates.py`) are written
  around the block models.

📊 **Effort:** High

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| — | — | no new dependency |

🔗 **Existing Code to Reuse:**
- `packages/ai-parrot/src/parrot/models/outputs.py` — `StructuredTableConfig`, `StructuredChartConfig`

---

### Option D (unconventional): Leave the envelope alone and let renderers infer

Document the current envelope as-is and have each renderer infer meaning:
`%` in a label means percent, `USD`/`$` in an axis label means currency,
magnitude picks compact notation. navigator-svelte already does part of this
(`isRatioLike`), and the HTML lane has `_is_currency_axis` (`"$" in label`).

✅ **Pros:**
- Zero parrot work.

❌ **Cons:**
- It contradicts FEAT-611's rule ("renderers never guess a number's meaning
  from its label") and duplicates heuristics in every renderer.
- It cannot recover what the adapter threw away: the progress title, the
  target, the percent meaning.
- The heuristics already disagree today: the walkthrough's `USD` label does
  not trigger `_is_currency_axis`, which only looks for `$`.

📊 **Effort:** Low (here), recurring (every renderer)

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| — | — | — |

🔗 **Existing Code to Reuse:**
- `infographic_html.py:818` — `_is_currency_axis`

---

## Recommendation

**Option B** is recommended because:

- Of the six problems, A fixes only 1, 2 and 6. Tables, dual axis and hero
  values are where the walkthrough pre-formats, and where navigator-svelte's
  polish work would otherwise have to guess.
- The wire already speaks every hint. The gap is purely in the infographic
  model and its lowering, so B is additive and needs no catalog bump.
- Keeping the HTML lane on the same formatter is the only way the dual-emit
  promise ("identical content by construction") becomes true rather than
  aspirational.
- C reaches the same end through a second vocabulary. D institutionalises
  guessing and still can't recover dropped data.

**What we trade off**:
- B touches three packages, not one.
- The Python and TS formatters become a pair that must stay in sync. A
  shared-fixture parity test makes drift fail loudly.
- Golden-file and prompt churn is expected.

---

## Feature Description

### User-Facing Behavior

For someone viewing an infographic as an A2UI surface (navigator-svelte, the
admin UI, an A2A peer):

- **Goal blocks read as goals.** A "Goal completion" heading is followed by
  `ARR target 90.4%`, `Churn under 2.0% 100%` and `NPS 50 target 92%`. When
  a target is declared, it shows as neutral comparison text (`vs 80% target`),
  never as a coloured delta.
- **Tables are typed.** Numeric columns arrive as numbers with
  `type`/`format`, so renderers right-align, sort numerically, and format
  currency and percent consistently. Declared alignment survives.
- **Charts with two scales use two axes.** A small series declared
  `axis: 'right'` gets its own scale and axis name, so it is no longer flat
  on the floor.
- **Hero KPIs can be numbers.** `value: 1203456, format: 'currency'` renders
  with the renderer's own currency rule. A string value still renders
  verbatim, for authors who want a hand-written headline like `$1.20M`.
- **HTML artifacts show the same strings** as the A2UI renderers for the same
  values.

### Internal Behavior

- **Model**: optional fields only. These are `ColumnDef.type/format`,
  `ChartDataSeries.axis`, `ChartBlock.y_axis_labels`, and
  `HeroCardBlock.value: str | float` with `format/unit`. The record-shape
  normalizers (`TableBlock._normalize_table_data`,
  `ChartBlock._normalize_chart_data`) keep accepting today's shapes and pass
  the new keys through.
- **Adapter** (`_Converter`):
  - A titled `progress` block closes the current section, opens one with
    `heading = title`, adds one `KPICard` per item, then closes it. Each
    card is `value = item.value / 100`, `format = 'percent'`,
    `comparisonPeriod = "vs N% target"` when `target` is set (omitted
    otherwise), and `color` forwarded. The target never goes in `delta`:
    `delta` carries trend colouring and the `higherIsBetter` judgement, and
    a target is neither a change nor good or bad news. All four renderers
    already render `comparisonPeriod` neutrally: `_semantics.kpi_comparison_html`,
    the admin UI `A2UINode.svelte:221`, and navigator-svelte's `MetricCard`.
  - An untitled `progress` keeps today's placement, in the current section,
    but with the same per-item fix.
  - `_table` forwards `align`, `type` and `format`. `_chart` builds
    `seriesAxes` (parallel to `y`) only when at least one series declares an
    axis, plus `yAxisLabels`. `_hero_card` forwards `format` and `unit`.
  - The docstring's "Known lossy degradations" list is corrected.
- **HTML lanes**:
  - There is no new formatter. `format_cell`
    (`a2ui_renderers/_table_format.py`) is aligned with `formatA2UIValue`:
    `$` for currency, at most 1 decimal for number, and percent unchanged.
  - The infographic renderer's `_render_hero_card` / `_render_table` call
    it. A `unit` is appended after a space, except for percent, matching
    TS. The infographic ECharts option honours `axis: 'right'` with a
    second `yAxis`.
  - Shared fixtures (`value`, `type`, `format`, `unit` → expected string)
    are a JSON file read by both a pytest and a vitest test.
- **Admin UI**: `a2ui-chart-adapter.ts` / `A2UINode.svelte` map
  `seriesAxes` / `yAxisLabels` to a second value axis, mirroring
  navigator-svelte's `chart-option.ts:371,399`.
- **Toolkit**: `_build_table_block` emits `ColumnDef` objects with `type`
  derived from pandas dtypes (int → `integer`, float → `number`). It never
  emits `format`, because a dtype carries no currency or percent meaning.
- **Walkthrough + README**:
  - The walkthrough sends raw numbers with hints.
  - `as_money` is used only for the hero card's hand-written headline.
  - Step 5's assertions cover the new props. The README's parity claim is
    corrected.

### Edge Cases & Error Handling

- **A `format` on a non-numeric value**: both formatters pass the value
  through unchanged. This matches `formatA2UIValue` today.
- **`percent` with a value > 1 in a table or hero card**: the contract
  says ratio, so `90.4` renders as `9040%`. The prompt and the KPICard
  instructions already say "send a ratio". Progress items are the only place
  the adapter divides, because their 0–100 range is a model guarantee
  (`ge=0, le=100`).
- **`seriesAxes` declared on a type with no axes** (pie/donut/gauge…): the
  adapter forwards it; the renderers already ignore it there. No adapter-side
  filtering, which keeps the adapter dumb.
- **A titled `progress` block between other content**: the content after it
  goes to a fresh anonymous section and does not rejoin the previous one.
  This is documented in the sectioning policy.
- **Old payloads** (string hero values, `List[str]` columns): byte-identical
  envelope except for the progress/sectioning fix. The golden test proves it.
- **The formatter pair drifts**: the shared-fixture parity test (pytest +
  vitest over one JSON file) fails on any difference.
- **Compact notation** (`$1.20M`) is not part of `format`. `format` says what
  the number *is*, and compact vs. full is how to *write* it. A hand-written
  hero headline stays a string. Axes keep the renderer's own compact
  formatter (`_CURRENCY_FORMATTER_JS`).

---

## Capabilities

### New Capabilities
- `a2ui-format-parity`: shared JSON fixtures plus a pytest and a vitest
  test that pin `format_cell` and `formatA2UIValue` to the same strings.

### Modified Capabilities
- `infographic-a2ui-adapter` (FEAT-470/527): lossless `progress` lowering
  and its own section; forwards column, series-axis and hero hints.
- `infographic-models`: optional display hints on `ColumnDef`,
  `ChartDataSeries`, `ChartBlock`, `HeroCardBlock`.
- `infographic-html-renderer`: hero, table and chart honour the hints via
  `format_cell`.
- `a2ui-cell-formatter` (FEAT-493): `format_cell` aligned with
  `formatA2UIValue` (`$` on currency, max 1 decimal on number).
- `admin-ui-a2ui-chart`: `seriesAxes` / `yAxisLabels` in the admin UI renderer.
- `infographic-toolkit-build-block`: typed `ColumnDef`s from DataFrame dtypes.
- `a2ui-dashboard-walkthrough` (example): raw numbers + hints; README parity
  claim corrected.

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `packages/ai-parrot/src/parrot/models/infographic.py` | extends | optional fields; normalizers pass them through |
| `packages/ai-parrot/src/parrot/outputs/a2ui/adapters/infographic.py` | modifies | `_progress`, `_table`, `_chart`, `_hero_card`, sectioning policy, docstring |
| `packages/ai-parrot/tests/outputs/a2ui/golden/infographic_lowered.json` | modifies | regenerated on purpose |
| `packages/ai-parrot/tests/outputs/a2ui/adapters/test_infographic_adapter.py` | extends | progress, hints, untouched-old-payload cases |
| `packages/ai-parrot-visualizations/src/parrot/outputs/formats/infographic_html.py` | modifies | hero, table, chart right axis |
| `packages/ai-parrot/src/parrot/tools/infographic_toolkit.py` | modifies | `_build_table_block` typed columns |
| `packages/ai-parrot/src/parrot/bots/prompts/__init__.py`, `models/infographic_templates.py` | modifies | teach the optional fields |
| `examples/agents/a2ui/` (walkthrough, `synthetic_data.py`, README) | modifies | raw numbers + hints |
| admin UI `a2ui-format.ts` | depends on | reference semantics; parity test |
| `packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/_table_format.py` | modifies | currency `$`, number max 1 decimal; `ssr_html`/PDF outputs move on purpose |
| admin UI `a2ui-chart-adapter.ts` / `A2UINode.svelte` | modifies | `seriesAxes` / `yAxisLabels` |
| navigator-svelte A2UI renderer | consumer | already honours `format`, column `type`, `seriesAxes`; its `a2ui-renderer-visual-polish` brainstorm depends on this |
| A2UI catalog / wire | unchanged | no version bump |

---

## Code Context

### User-Provided Code
None. The discovery came from rendering the walkthrough's
`artifacts/a2ui_dashboard/02_envelope_v1.json` (copied to navigator-svelte as
`src/routes/(app)/dev/a2ui/parrot-walkthrough.envelope.json`).

### Verified Codebase References

#### Classes & Signatures
```python
# packages/ai-parrot/src/parrot/models/infographic.py
class ColumnDef(BaseModel):                      # :204
    header: str; width: Optional[str]
    align: Optional[Literal["left", "center", "right"]]; color: Optional[str]
class HeroCardBlock(BaseModel):                  # :327
    type: Literal["hero_card"]; label: str
    value: str                                   # :335  "Formatted metric value (e.g., '$1.2M', '98%')"
    icon; trend: Optional[TrendDirection]; trend_value: Optional[str]
    comparison_period: Optional[str]; color: Optional[str]
class ChartDataSeries(BaseModel):                # :497
    name: str; values: List[Union[int, float, None]]; color: Optional[str]
class ChartBlock(BaseModel):                     # :511
    chart_type; title; description; labels: List[str]; series: List[ChartDataSeries]
    x_axis_label; y_axis_label; stacked; show_legend; layout: Optional[Literal["full","half"]]
    # @model_validator(mode="before") _normalize_chart_data  :583
class TableBlock(BaseModel):                     # :749
    columns: Union[List[str], List[ColumnDef]]; rows: List[List[Any]]; sortable; style
    # @model_validator(mode="before") _normalize_table_data  :767
class ProgressItem(BaseModel):                   # :901
    label: str
    value: float   # :905  ge=0.0, le=100.0, "Completion percentage (0-100)"
    color: Optional[str]
    target: Optional[float]  # :907  ge=0.0, le=100.0
class ProgressBlock(BaseModel):                  # :916
    type: Literal["progress"]; title: Optional[str]; items: List[ProgressItem]

# packages/ai-parrot/src/parrot/models/outputs.py
SeriesAxis = Literal["left", "right"]            # :329
#   StructuredChartConfig.y_axis_labels (alias yAxisLabels)  :397
#   StructuredChartConfig.series_axes   (alias seriesAxes)   :407
class TableColumn(BaseModel):                    # :557
    name: str; type: str; title: str
    format: Optional[str]   # currency | percent | email | uri | enum | id | code

# packages/ai-parrot/src/parrot/outputs/a2ui/adapters/infographic.py
# :52-55  docstring: "nothing presentation-relevant is dropped any more"  (false)
class _SectionAccumulator:                       # :172  open(heading=, text=) / close() / add() / set_text()
class _Converter:                                # :220
    def _chart(self, block) -> dict              # :236  forwards yAxisLabel, layout, palette; no seriesAxes
    def _table(self, block) -> dict              # :295  columns -> [{"name", "title"}] only (align/type/format dropped)
    def _hero_card(self, block) -> dict          # :323  label/value/delta/trend/icon/color/comparisonPeriod
    def _progress(self, block) -> list[dict]     # :355  KPICard{"label", "value"} per item; title/target/color dropped
    def walk(self, blocks, sections, *, depth, seen_title)  # :532 ; progress branch :587
def infographic_response_to_envelope(...)        # :642

# packages/ai-parrot/src/parrot/outputs/a2ui/catalog/parrot/kpicard.py
# KPICARD_SCHEMA :15 — label, value, unit, delta, trend, icon, color, comparisonPeriod,
#                      higherIsBetter, format (:43, enum percent|currency|number)

# packages/ai-parrot-visualizations/src/parrot/outputs/formats/infographic_html.py
_CURRENCY_FORMATTER_JS                           # :141  compact $K/$M axis formatter (JS sentinel)
def _render_hero_card(self, block) -> str        # :745  escape(block.value) — assumes str
def _is_currency_axis(block) -> bool             # :818  "$" in y_axis_label
def _render_table(self, block) -> str            # :1190 honours ColumnDef width/align/color
def _render_progress(self, block) -> str         # :1329 title + f"{value:.0f}%" + bar + target marker

# packages/ai-parrot/src/parrot/tools/infographic_toolkit.py
def _build_chart_block(...)                      # :1571 series values = df[col].tolist()
def _build_table_block(...)                      # :1608 columns = [str(c) ...], rows = df[columns].values.tolist()
```

```ts
// packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/a2ui-format.ts
export type A2UINumberFormat = 'percent' | 'currency' | 'number'
export function formatA2UIValue(value: unknown, format?: unknown, unit?: unknown): unknown
//   percent: ratio ×100, max 1 decimal, "%"; number: max 1 decimal; currency: USD;
//   unit appended after a space unless percent; non-numeric passes through.
```

#### Verified Imports
```python
from parrot.models.infographic import ColumnDef, HeroCardBlock, ChartBlock, ChartDataSeries, TableBlock, ProgressBlock, ProgressItem
from parrot.models.outputs import TableColumn, SeriesAxis
from parrot.outputs.a2ui.adapters.infographic import infographic_response_to_envelope   # __all__
```

#### Key Attributes & Constants
- Walkthrough blocks: `examples/agents/a2ui/a2ui_dashboard_walkthrough.py:304-352` (hero `as_money`, table cells pre-formatted, `progress` "Goal completion")
- `build_goals` → `examples/agents/a2ui/synthetic_data.py:116` (`{"label","value"}`, value 0–100, no `target`)
- `as_money` → `examples/agents/a2ui/synthetic_data.py:144`
- Adapter golden → `packages/ai-parrot/tests/outputs/a2ui/golden/infographic_lowered.json`
- LLM prompt example `"value": "$3.7M"` → `packages/ai-parrot/src/parrot/bots/prompts/__init__.py:80-83`

### Does NOT Exist (Anti-Hallucination)
- ~~`ColumnDef.type` / `ColumnDef.format`~~: only header/width/align/color.
- ~~A per-series axis on `ChartDataSeries`~~: only name/values/color.
- ~~`ChartBlock.y_axis_labels`~~: only the singular `y_axis_label`.
- ~~Infographic HTML lane formatting of hero/table values~~: `infographic_html.py` prints them with `escape(...)` verbatim. Its only formatter is the JS `_CURRENCY_FORMATTER_JS` axis sentinel. **A Python formatter DOES exist**, `format_cell` (`a2ui_renderers/_table_format.py:41`), used by the A2UI Python renderers. An earlier revision of this doc wrongly said none existed.
- ~~A `compact` value in the `format` enum~~: deliberately not added (see Edge Cases).
- ~~`seriesAxes`/`yAxisLabels` support in the admin UI renderer~~: no match under `packages/ai-parrot-server/ui/src/lib` (navigator-svelte does support it, `chart-option.ts:60,371,399`).
- ~~`target` on any KPICard prop~~: the catalog has no target field (hence the `comparisonPeriod` text decision).

---

## Parallelism Assessment

- **Internal parallelism**: the model change comes first, because everything
  reads the new fields. After that, these are independent files: the
  adapter, the infographic HTML lane, the `format_cell` alignment plus the
  parity test, the admin UI `seriesAxes`, and the toolkit's typed columns.
  The walkthrough/README goes last.
- **Cross-feature independence**:
  - No in-flight branch touches `adapters/infographic.py` or
    `models/infographic.py`. Checked against every `origin/*` ref on
    2026-09-30, and there are no open Jira tickets.
  - navigator-svelte's `a2ui-renderer-visual-polish` consumes the result.
    Its fixture should be regenerated after this lands.
- **Recommended isolation**: `mixed`. Model first. Then adapter / HTML lane
  / formatter+parity / admin UI / toolkit as parallel tasks; the HTML lane
  task depends on the formatter alignment. The example comes last.
- **Rationale**: the shared surface is the model module only, and every
  later task touches a different package or file.

---

## Open Questions

- [x] Scope? — *Owner: Juan*: Adapter + model + example (Option B).
- [x] How does a progress item lower? — *Owner: Juan*: `KPICard` with ratio + `format='percent'`, and the target as text. No catalog change.
- [x] Does a titled progress block get its own section? — *Owner: Juan*: Yes. **Revised in the spec (FEAT-623, 2026-09-30, after codex S8)**: no. Both renderers turn more than one section into tabs, so it becomes a `Column{Text(title), Row{KPICard…}}` group inside the current section.
- [x] How does the HTML lane handle raw numbers + format? — *Owner: Juan*: A shared Python formatter mirroring `a2ui-format.ts`.
- [x] Hero value shape? — *Owner: Juan*: `value: str | float` plus optional `format`/`unit`.
- [x] Should `currency` gain a compact notation (`$1.20M`)? — *Owner: Juan*: No, not now. `format` states meaning and compact is notation. A hand-written headline stays a string (`value: str | float` already allows it). If it is ever needed, it becomes a separate optional `notation: 'compact'` prop, never a new `format` value.
- [x] Where does the Python formatter live? — *Owner: Juan*: Nowhere new. Reuse `format_cell` (`ai-parrot-visualizations/.../a2ui_renderers/_table_format.py`), which sits in the same package as the infographic HTML renderer. Align it with `a2ui-format.ts`, which is the reference (`$` on currency, max 1 decimal on number), and pin both with a shared-fixture parity test.
- [x] Does the admin UI renderer gain `seriesAxes` support in this feature? — *Owner: Juan*: Yes, as its own small task. It is the only parrot renderer without it, and the walkthrough starts emitting the hint.
- [x] Does the target go in `comparisonPeriod` or `delta`? — *Owner: Juan*: `comparisonPeriod`, worded `vs N% target`, and omitted when there is no target. Never `delta`, which carries trend colour and the `higherIsBetter` judgement.
- [ ] Is changing `format_cell`'s currency/number output acceptable for existing `ssr_html` / PDF consumers? Nothing is known to depend on the bare `1,234.56` form. — *Owner: Jesús*
