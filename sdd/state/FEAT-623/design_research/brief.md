<!--
  sdd/templates/design_research.prompt.md — neutral design-research brief (FEAT-545).
  Rendered by /sdd-spec section 3b and piped to `codex exec ... --output-schema
  design_research.schema.json`.
  FORBIDDEN INPUTS: never paste the spec draft, the spec author's reasoning, a preferred
  conclusion, or any text written by the model that will author the spec. The brief carries
  ONLY the accepted exploration document (brainstorm/proposal) and verified code anchors.
  Placeholders (double-curly-brace tokens, deliberately NOT written with literal braces in
  this comment — a renderer that does a naive whole-document string replace must not also
  rewrite this sentence): problem_statement, constraints_and_goals,
  recommended_option_or_scope, code_context_paths, open_questions, question.
-->
# Independent design review — read-only

You are an independent design reviewer for **ai-parrot**, an async-first Python
framework for AI agents (aiohttp, Pydantic v2, `uv` workspace under `packages/`).
You have read-only access to the repository in your working directory.

## Rules
1. Read the code you cite. Every `affected_paths` entry must be a repo-relative
   path you actually opened; suggestions with unverifiable paths are discarded.
2. Judge the design intent below against what exists in the repository: what is
   missing, what is risky, what would be simpler, what the codebase already
   provides that the intent re-invents.
3. Do not restate the intent, do not praise it, do not write code. Propose at
   most 12 concrete, falsifiable suggestions, each tagged with a kind
   (`architecture` | `api` | `testing` | `risk` | `alternative`), a risk level and
   your confidence.
4. Output exactly ONE JSON object conforming to the schema you were given — no
   markdown fences, no prose before or after.

## Accepted design intent (verbatim from the exploration document)

### Problem statement
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

### Constraints and goals
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

### Recommended option / probable scope
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

### Verified code anchors (paths only — open them yourself)
examples/agents/a2ui/a2ui_dashboard_walkthrough.py
examples/agents/a2ui/synthetic_data.py
packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/a2ui-chart-adapter.ts
packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/a2ui-format.ts
packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/_semantics.py
packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/_table_format.py
packages/ai-parrot-visualizations/src/parrot/outputs/formats/infographic_html.py
packages/ai-parrot/src/parrot/bots/prompts/__init__.py
packages/ai-parrot/src/parrot/models/infographic.py
packages/ai-parrot/src/parrot/models/outputs.py
packages/ai-parrot/src/parrot/outputs/a2ui/adapters/infographic.py
packages/ai-parrot/src/parrot/outputs/a2ui/catalog/parrot/kpicard.py
packages/ai-parrot/src/parrot/tools/infographic_toolkit.py
packages/ai-parrot/tests/outputs/a2ui/adapters/test_infographic_adapter.py
packages/ai-parrot/tests/outputs/a2ui/golden/infographic_lowered.json

### Questions still open in the exploration document
- [ ] Is changing `format_cell`'s currency/number output acceptable for existing `ssr_html` / PDF consumers? Nothing is known to depend on the bare `1,234.56` form. — *Owner: Jesús*

## Question
Given this accepted design intent and these verified code anchors, how would you build it? What is missing, risky, or better done another way?
