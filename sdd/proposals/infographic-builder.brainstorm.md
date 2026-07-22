---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Brainstorm: Infographic Builder — Recipe-Driven, Replayable A2UI Infographics

**Date**: 2026-07-22
**Author**: Jesus Lara (decisions) + Claude (research/synthesis)
**Status**: exploration
**Recommended Option**: A

---

## Problem Statement

Reference artifacts (`sdd/artifacts/daily_report.py`, `sdd/artifacts/executive_summary.py`,
`sdd/artifacts/budget_variance_dashboard_Template.html`) demonstrate a real-world pattern
that ai-parrot cannot express today: a **daily financial infographic** where

1. raw datasets (3 CSV snapshots) pass through **domain transformation routines**
   (`day_totals()`, `division_breakdown()`, `analyze()` — variance analysis, trends,
   worst/best drivers),
2. the computed results feed a **fixed visual layout** (KPI row, day ribbon, actual-vs-budget
   chart, grouped ledger table with division rollups),
3. and the whole thing regenerates **every day with fresh data** — same construction
   instructions, new numbers.

Today those artifacts are a standalone Windows script with hardcoded paths, string-splicing
into an HTML template, and Outlook COM automation. Inside ai-parrot, FEAT-273 (done) gives us
the safe declarative output pipeline (A2UI envelopes → catalog validation → deterministic
renderers), and `DatasetManager` gives us refreshable datasets (`fetch_dataset(force_refresh=True)`).
**What is missing is the middle layer**: a persisted, re-executable "recipe" that binds
*datasets → registered transforms → an A2UI envelope layout*, so that a user can say
"repeat the budget-variance infographic with today's data" and get a byte-for-byte-comparable
regeneration without re-involving the LLM.

Affected users: end users consuming recurring reports (finance, ops), agent builders who
want deterministic recurring infographics, and platform ops who need the regeneration to be
safe (no `exec()`, FEAT-273 G1) and schedulable.

## Constraints & Requirements

- **Flow**: `type: feature`, `base_branch: dev` (Round 0 decision).
- **Build on FEAT-273, not beside it**: every internal object of the infographic is expressed
  as a catalog component (JSON schema + data via `dataModel` bindings) inside a `CreateSurface`
  envelope; rendering goes through the renderer registry (SSR-HTML et al.). No new wire format.
- **G1 security invariant holds**: recipes are *data*. Transformation routines are **registered
  Python transformers referenced by name + params** — never stored/executed code (user decision).
- **Dual authorship**: the LLM can compose an infographic interactively and "freeze" it into a
  recipe, AND a developer/power-user can write a recipe by hand (YAML/JSON). Both produce the
  same recipe model (user decision: "ambos caminos").
- **Persistence in both backends**: an abstract recipe store with file-based and DB-backed
  implementations (user decision: "ambos backends").
- **Three regeneration triggers**: agent chat tool, REST endpoint, and scheduled job — all
  three funnel into one runner (user decision: all three selected).
- **Data binding**: recipe references a `DatasetManager` dataset (dataset_id/name) as the
  primary source of truth, **plus override parameters at regeneration time** (e.g. "same
  report but for June") (user decision: "Ambos + parámetros de refresh").
- **Interactivity**: client-side baked — tabs/metric toggles/sortable tables work offline in a
  self-contained HTML file, like the reference template (user decision). Note: the current
  `SSRHTMLRenderer` is deliberately static (`interactive=False`, zero `<script>` output), so
  this requires a new interactive render profile in `ai-parrot-visualizations`.
- **Schema drift → fail fast**: transformers declare required input columns; regeneration
  validates before executing and fails with a precise diagnostic (missing column, empty
  dataset). No silently-wrong infographics (user decision).
- **Location**: new `parrot/outputs/a2ui/recipes/` subsystem + new tools hung off the existing
  `InfographicToolkit`; renderers stay in `ai-parrot-visualizations` (user decision).
  Caveat: `parrot.outputs.a2ui` has a one-way import rule (never imports DatasetManager/agents/
  LLM clients — spec G8), so the recipe *runner* that touches DatasetManager must live outside
  the core envelope package (see Feature Description).

---

## Options Explored

### Option A: Recipe Layer over A2UI (transformer registry + recipe store + runner)

A new **recipe subsystem** with three cleanly separated parts:

1. **Recipe model (core, `parrot/outputs/a2ui/recipes/models.py`)** — a Pydantic
   `InfographicRecipe` that is pure data: metadata (id, name, version, owner scope),
   `data_sources[]` (dataset name + refresh spec: optional SQL/conditions template with
   named parameters like `{month}`), `transforms[]` (registered transformer name + params +
   output key), and `layout` — the component tree expressed exactly as FEAT-273 catalog
   component instances whose `data` properties are `{"$bind": "/pointer"}` bindings into the
   `dataModel` that transforms populate. The recipe *is* the "precise construction
   instructions". Serializes to JSON/YAML for hand authoring.
2. **Transformer registry (`parrot/outputs/a2ui/recipes/transformers.py`)** — an
   `@infographic_transformer("name")` decorator registering pure functions
   `(df | dict[str, df], params) -> dict` that declare `requires_columns` (per input) for
   fail-fast validation. Ship a built-in library ported from `executive_summary.py`:
   `day_totals`, `division_breakdown`, `variance_analysis`, `top_movers` — plus generic
   tabular ones (`groupby_aggregate`, `pivot`, `latest_vs_baseline`).
3. **Runner + store + triggers (outside the core package, G8-compliant)** —
   `RecipeRunner` (e.g. `parrot/tools/infographic_recipes/runner.py`) resolves datasets via
   `DatasetManager.fetch_dataset(..., force_refresh=True)` / `get_dataframe()`, applies
   override params, validates schemas, executes transforms, assembles the envelope via
   `parrot.outputs.a2ui.builders`, validates against the catalog, renders through the
   renderer registry, persists the `RenderedArtifact` and delivers via the FEAT-273 delivery
   bridge. `AbstractRecipeStore` with `FileRecipeStore` (YAML/JSON dir, SkillsDirectoryLoader
   pattern) and `DBRecipeStore` (SkillRegistry pattern, versioned). Triggers: new
   `InfographicToolkit` tools (`infographic_save_recipe`, `infographic_list_recipes`,
   `infographic_run_recipe`), a `RecipeHandler` REST view (DatasetManagerHandler pattern),
   and a scheduled-job entry point that calls the same runner.

✅ **Pros:**
- Recipes are pure data → G1 preserved end-to-end; regeneration is deterministic and LLM-free.
- Every internal object is a JSON-schema'd catalog component + data, exactly as requested —
  any FEAT-273 renderer (SSR-HTML, PDF, Adaptive Cards) can materialize it.
- Both authorship paths converge on one model; the LLM "freeze" path reuses the existing
  catalog-validate-retry producer.
- Transformer registry gives testable, typed domain logic (the `executive_summary.py` port
  becomes golden-file-testable library code).
- One runner behind all three triggers → no drift between chat, REST and scheduler behavior.

❌ **Cons:**
- New transformers require a code deploy (accepted trade-off of the registry decision).
- Interactive baked-JS profile is net-new renderer work in `ai-parrot-visualizations`.
- Two store backends + versioning is real surface area (mitigated by copying SkillRegistry).

📊 **Effort:** High (but decomposes well — see Parallelism)

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `pydantic` v2 | Recipe/transformer-manifest models | already core dependency |
| `pandas` | transform execution substrate | already used by DatasetManager |
| `PyYAML` | hand-authored file recipes | already in deps (skills frontmatter) |
| vendored `echarts.min.js` | interactive baked charts | already shipped in ai-parrot-visualizations assets |
| `asyncdb`/existing DB layer | DBRecipeStore persistence | same stack SkillRegistry uses |

🔗 **Existing Code to Reuse:**
- `parrot/outputs/a2ui/builders.py` — `build_surface/build_chart/build_kpicard/build_infographic` assemble + validate envelopes.
- `parrot/outputs/a2ui/catalog/` — component registry, schemas, `lower()` trees (Infographic, Chart, KPICard, DataTable).
- `parrot/tools/dataset_manager/tool.py` — `fetch_dataset`, `get_dataframe`, `get_dataset_entry` (data refresh + PBAC already handled).
- `parrot/skills/store.py` — `SkillRegistry` as the DB-store/versioning blueprint.
- `parrot/tools/infographic_toolkit.py` — toolkit host for the new tools; artifact persistence flow.
- `packages/ai-parrot-server/src/parrot/handlers/datasets.py` — `DatasetManagerHandler` as REST handler pattern.
- `packages/ai-parrot-visualizations/.../a2ui_renderers/ssr_html.py` + `echarts.py` — base for the interactive profile.
- `sdd/artifacts/executive_summary.py` — `day_totals`, `division_breakdown`, `analyze` as the seed transformer library.

---

### Option B: Extend the FEAT-197 InfographicTemplate system

Grow the existing `InfographicTemplate` / `infographic_registry` (positional block contracts)
into recipes: add dataset bindings and transform references to templates, keep the existing
`infographic_render` flow, and persist enriched templates.

✅ **Pros:**
- Smallest conceptual delta — `InfographicToolkit` already has templates, block validation,
  artifact persistence and an `_build_a2ui_envelope` bridge.
- No new storage concept (extends the template registry).

❌ **Cons:**
- Templates are *layout contracts* (positional BlockSpecs), not data pipelines — bolting
  dataset refresh + transforms onto them conflates two concerns permanently.
- The template path is the pre-A2UI legacy flow (FEAT-197/`OutputMode` formats now carrying
  deprecation warnings per TASK-1740); building the future on it inverts FEAT-273's direction.
- Code-defined registry ≠ user-persisted recipes; retrofitting per-user DB storage into
  `InfographicTemplateRegistry` is awkward.

📊 **Effort:** Medium

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `pydantic` v2 | extended template models | existing |

🔗 **Existing Code to Reuse:**
- `parrot/models/infographic_templates.py` — `InfographicTemplate` (line 47), `InfographicTemplateRegistry` (line 512).
- `parrot/tools/infographic_toolkit.py` — full render/validate/persist flow.

---

### Option C: Declarative transform DSL engine

Recipes embed a JSON transform DSL (`groupby`, `aggregate`, `pivot`, `variance`, `rank` ops)
executed by a generic engine over pandas; no registered Python functions needed for new logic.

✅ **Pros:**
- New analyses composable at runtime without code deploys; the LLM can author transforms as data.
- Maximum recipe portability (a recipe fully describes its own math).

❌ **Cons:**
- User explicitly chose registered transformers over a DSL (Round 1).
- A safe, complete DSL engine is a large attack/test surface — effectively a query language to
  spec, validate, and maintain.
- Domain logic like "first-of-month file is displayed-date minus one day" (see
  `daily_report.py:find_first_of_month_file`) is painful to express declaratively.

📊 **Effort:** High

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `pandas` | DSL execution substrate | existing |

🔗 **Existing Code to Reuse:**
- Same A2UI surface as Option A; the DSL replaces only the transformer registry.

---

### Option D (unconventional): Recipes as learned Skills

Persist the construction instructions as a composite Skill (`save_learned_skill` /
`SkillRegistry.upload_skill`): natural-language + structured steps the *agent* re-executes
with the LLM each time regeneration is requested.

✅ **Pros:**
- Zero new storage or models — reuses the entire skills subsystem today.
- Instructions stay human-readable and LLM-editable ("make the June version but highlight X").

❌ **Cons:**
- Regeneration is LLM-mediated → non-deterministic, token-costly, and slower; contradicts the
  core requirement ("repetir la construcción de la misma infografía" precisely).
- No schema-drift fail-fast guarantee; correctness depends on the model run.
- Scheduling an LLM loop per report is operationally heavier than replaying data.

📊 **Effort:** Low

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| — | none new | reuses skills subsystem |

🔗 **Existing Code to Reuse:**
- `parrot/skills/store.py`, `parrot/skills/tools.py` — full persistence + retrieval path.

---

## Recommendation

**Option A** is recommended because it is the only option that satisfies all seven user
decisions simultaneously: deterministic LLM-free replay (kills D), recipes as pure data with
registered transformers (kills C), a persistence model designed for per-user/DB + file storage
(kills B's registry retrofit), and native alignment with FEAT-273 — the envelope *is* the
"json-schema + data per internal object" contract the user asked for, and rendering rides the
existing renderer registry. What we trade off: more upfront surface (registry + stores + runner
+ interactive render profile) and code deploys for new transformers. Both are acceptable — the
surface decomposes into independent tasks, and the transformer library grows exactly like the
tool ecosystem already does (decorator + registry, reviewed and tested).

Option D remains interesting as a *complement* (an LLM skill that helps users author/edit
recipes conversationally), not as the persistence mechanism.

---

## Feature Description

### User-Facing Behavior

- **Compose & freeze (chat)**: a user works with an agent ("build me a budget-variance
  infographic from dataset `in_month_projections`"). The agent (LLM producer + builders)
  assembles the envelope, shows the rendered infographic, and the user says "save this as
  `budget-variance-daily`". The toolkit freezes the exact construction — dataset refs,
  transform chain, layout, theme, render profile — as a named, versioned recipe.
- **Author by hand**: a developer writes the same recipe as a YAML/JSON file in a recipes
  directory (file store) or POSTs it to the REST handler (DB store). Hand-written and frozen
  recipes are the same model and replay identically.
- **Replay**: "regenerate `budget-variance-daily`" (chat tool), `POST /api/v1/infographic_recipes/{id}/run`
  (REST), or a scheduled job. Optional override params (`month=2026-06`) map onto the recipe's
  declared parameters. Output: a self-contained interactive HTML artifact (client-side tabs,
  metric toggles, sortable ledger — works offline like the reference template), persisted via
  the artifact store and optionally delivered through notifications (email/Telegram/Teams),
  replacing the Outlook COM path of `daily_report.py`.
- **Manage**: list recipes (name, description, params, last run), inspect a recipe's contract
  (which dataset + columns it needs), delete/deprecate.

### Internal Behavior

1. **Recipe resolution**: runner loads `InfographicRecipe` from the store (file or DB) and
   merges override params with declared defaults (relative-date params like `current_month`
   resolve at run time).
2. **Data acquisition**: for each `data_source`, resolve the named dataset through the bound
   `DatasetManager` — re-fetching from source (`fetch_dataset` with templated SQL/conditions,
   `force_refresh=True`) so data is current. PBAC/data-plane guards apply as they do today.
3. **Validation gate (fail-fast)**: before any transform runs, check each transformer's
   declared `requires_columns` against the actual dataframes and reject empty datasets; on
   failure, abort with a structured diagnostic (recipe id, transform name, missing columns).
4. **Transform execution**: run the transform chain (pure registered functions), accumulating
   outputs into the envelope `dataModel` under each transform's output key.
5. **Envelope assembly**: instantiate the recipe's layout — catalog components whose `data`
   props are `$bind` pointers into the dataModel — via `build_surface`/`build_infographic`;
   `validate_envelope` enforces the catalog allowlist.
6. **Render & persist**: pass the envelope to the selected render profile. New
   `interactive-html` profile (ai-parrot-visualizations) emits a single self-contained HTML
   document with vendored JS (ECharts) and small vanilla-JS behaviors (day tabs, metric
   toggle, table sort) driven only by the embedded dataModel JSON — mirroring the reference
   template's `<script id="report-data">` pattern. Static profiles (existing SSR-HTML → PDF/
   email) remain available for delivery channels that need them. Result is a
   `RenderedArtifact` persisted and optionally delivered via `send_notification`.
7. **Freeze path**: when saving from a live agent session, the toolkit captures the envelope
   the LLM produced, the dataset names in play, and the transform invocations, normalizes them
   into the recipe model, validates a dry-run, then persists (new version if the name exists).

### Edge Cases & Error Handling

- **Missing column / empty dataset** → fail fast with structured error naming the recipe,
  transform, dataset and columns (user decision). REST returns 422 with the diagnostic; chat
  tool returns the diagnostic as tool output so the agent can explain it.
- **Dataset no longer registered** → error suggests available datasets; recipe is not mutated.
- **Unknown transformer name** (recipe authored against a newer/older library) → fail at
  validation gate, listing registered transformers.
- **Override param not declared by the recipe** → reject (typo protection) rather than ignore.
- **Renderer profile unavailable** (visualizations extra not installed) → same degradation
  contract FEAT-273 renderers already use; suggest the static profile.
- **Concurrent replays of one recipe** → runs are independent (recipe is read-only at run
  time); artifact names carry run timestamps.
- **Recipe schema evolution** → recipes carry a `schema_version`; store migrates or rejects
  with guidance.

---

## Capabilities

### New Capabilities
- `infographic-recipes`: persisted, replayable dataset→transform→A2UI-envelope recipes with
  transformer registry, dual stores (file/DB), runner, toolkit tools, REST handler and
  scheduled-run entry point.
- `a2ui-interactive-html-renderer`: self-contained interactive HTML render profile (baked
  vendored JS, client-side-only interactivity) in ai-parrot-visualizations.

### Modified Capabilities
- `a2ui-implementation` (FEAT-273): consumed, not changed — except registering the new render
  profile in the renderer registry.

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `parrot/outputs/a2ui/` (core) | extends | new `recipes/` subpackage: models + transformer registry (pure, keeps G8 one-way import rule — no DatasetManager imports here) |
| `parrot/tools/infographic_toolkit.py` | extends | new tools: save/list/run/inspect recipes; freeze path from live session |
| `parrot/tools/dataset_manager/tool.py` | depends on | `fetch_dataset` / `get_dataframe` / `get_dataset_entry`; no changes expected |
| `packages/ai-parrot-visualizations` | extends | new `interactive_html.py` renderer profile (vendored ECharts + vanilla JS behaviors) |
| `packages/ai-parrot-server` handlers | extends | new `RecipeHandler` (BaseView) + routes; scheduled-job entry point |
| `parrot/outputs/a2ui/delivery.py` | depends on | reuse RenderedArtifact delivery bridge for scheduled runs |
| `parrot/skills/store.py` | reference | SkillRegistry pattern copied for DBRecipeStore (no changes) |
| DB migrations | adds | recipe table(s) for DBRecipeStore |

No breaking changes; everything is additive.

---

## Code Context

### User-Provided Code

Reference artifacts supplied by the user (full files in repo):

```python
# Source: sdd/artifacts/daily_report.py (structure to replace/absorb)
def parse_csv(path: Path) -> list: ...          # CSV → compact rows [division, project, revA, revB, ebA, ebB]
def build_report_data() -> dict: ...            # {"days": {"YYYYMMDD": rows, ...}} — 3 snapshots
def splice_into_template(template_html, report_data) -> str  # writes JSON into <script id="report-data">
```

```python
# Source: sdd/artifacts/executive_summary.py (seed transformer library)
def day_totals(rows: list) -> dict: ...          # rev/ebitda actual, budget, variance, variance_pct
def division_breakdown(rows: list) -> dict: ...  # per-division rollup + per-project variances
def analyze(report_data: dict) -> dict: ...      # first/last totals, trends, worst/best drivers
```

```html
<!-- Source: sdd/artifacts/budget_variance_dashboard_Template.html -->
<!-- Self-contained HTML: inline Chart.js v4.4.4 + datalabels plugin, data injected via -->
<script type="application/json" id="report-data">{...}</script>
<!-- Layout: KPI row (4 cards) · day ribbon tabs · actual-vs-budget chart w/ metric toggle
     (Revenue/EBITDA buttons) · grouped ledger table (division subtotal rollup, sortable) -->
```

### Verified Codebase References

#### Classes & Signatures
```python
# From packages/ai-parrot/src/parrot/tools/dataset_manager/tool.py
class DatasetManager(AbstractToolkit):                                  # line 501
    def get_dataset_entry(self, name: str) -> Optional[DatasetEntry]:   # line 2250
    async def list_datasets(self) -> List[Dict[str, Any]]:              # line 2762
    async def get_metadata(self, ...):                                  # line 2895
    async def get_dataframe(self, name: str) -> Dict[str, Any]:         # line 3131
    async def fetch_dataset(self, name: str, sql: Optional[str] = None,
                            conditions: Optional[Dict[str, Any]] = None,
                            force_refresh: bool = False) -> Dict[str, Any]:  # line 3266

# From packages/ai-parrot/src/parrot/outputs/a2ui/builders.py
def build_surface(component: str, properties: dict[str, Any], *, surface_id: str,
                  component_id: str = ..., data_model: Optional[dict] = None) -> CreateSurface:  # line 44
def build_chart(*, chart_type: str, x: str, y: Sequence[str], title=None,
                data_binding: Optional[str] = None, show_legend: bool = True,
                surface_id: str = "chart") -> CreateSurface:             # line 71
def build_kpicard(*, label: str, value: Any, unit=None, delta=None, trend=None,
                  surface_id: str = "kpi") -> CreateSurface:             # line 91
def build_datatable(...) -> CreateSurface:                               # line 128
def build_infographic(*, title: str, sections: Sequence[dict[str, Any]], subtitle=None,
                      theme=None, surface_id: str = "infographic",
                      data_model: Optional[dict] = None) -> CreateSurface:  # line 151

# From packages/ai-parrot/src/parrot/outputs/a2ui/models.py
class Component(BaseModel): ...        # line 123 — id, component, properties (w/ $bind validation)
class CreateSurface(A2UIMessageBase):  # line 167 — surfaceId, catalogId, components, dataModel

# From packages/ai-parrot/src/parrot/outputs/a2ui/catalog/components/chart.py
@register_component("Chart")           # line 56
class ChartComponent:                  # line 57 — display-only; data prop is {'$bind': '/pointer'}
    def lower(self, component: Component, data_model: dict) -> BasicTree  # line 64

# From packages/ai-parrot/src/parrot/outputs/a2ui/catalog/components/infographic.py
class InfographicComponent:            # line 83
    def lower(self, component: Component, data_model: dict[str, Any]) -> BasicTree  # line 89

# From packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/ssr_html.py
class SSRHTMLRenderer(AbstractA2UIRenderer):   # line 59 — self-contained, NO scripts,
    async def render(self, ...):               # line 62 — registered with interactive=False (line 53)

# From packages/ai-parrot/src/parrot/tools/infographic_toolkit.py (FEAT-197 + TASK-1739)
class InfographicToolkit(AbstractToolkit):     # line 111
    async def render(self, ...):               # line 245
    def _build_a2ui_envelope(self, ...):       # line 494
    async def list_templates(self) -> List[Dict[str, str]]:  # line 611
    async def get_template_contract(self, template_name: str) -> Dict[str, Any]:  # line 625

# From packages/ai-parrot/src/parrot/skills/store.py (DB-store blueprint)
class SkillRegistry:                           # line 120 — upload_skill:263, read_skill:475,
                                               # search_skills:518, list_skills:774, versioning:399

# From packages/ai-parrot-server/src/parrot/handlers/datasets.py (REST pattern)
class DatasetManagerHandler(BaseView):         # line 141

# From packages/ai-parrot/src/parrot/models/infographic_templates.py (legacy template system)
class InfographicTemplate(BaseModel):          # line 47
class InfographicTemplateRegistry:             # line 512
```

#### Verified Imports
```python
# Confirmed working (module paths verified on disk):
from parrot.outputs.a2ui.models import CreateSurface, Component      # a2ui/__init__.py re-exports models (line 12)
from parrot.outputs.a2ui.builders import build_infographic, build_chart, build_kpicard, build_surface
from parrot.tools.dataset_manager.tool import DatasetManager
from parrot.skills.store import SkillRegistry
from parrot.tools.toolkit import AbstractToolkit                     # used by infographic_toolkit.py:26
```

#### Key Attributes & Constants
- FEAT-273 catalog v1 components: `Infographic, Report, Map, Chart, DataTable, KPICard, Card, Timeline, Form` (spec OQ-B, all implemented under `parrot/outputs/a2ui/catalog/components/`)
- `SSRHTMLRenderer` registration: `interactive=False` (ssr_html.py:53) — static profile only
- Vendored `echarts.min.js` exists in ai-parrot-visualizations assets (FEAT-273 spec, echarts renderer)
- `DatasetManager.tool_prefix = "dataset"` (tool.py: near 522)
- One-way import rule for `parrot.outputs.a2ui` (its `__init__.py` docstring, spec G8): never imports agents/DatasetManager/LLM clients

### Does NOT Exist (Anti-Hallucination)
- ~~`parrot/outputs/a2ui/recipes/`~~ — does not exist; entirely new subpackage
- ~~`TransformerRegistry` / `@infographic_transformer` / any transform registry~~ — no transform registry anywhere in `parrot/` (grep-verified)
- ~~`RecipeStore` / `AbstractRecipeStore` / `InfographicRecipe`~~ — do not exist
- ~~An interactive/JS-emitting A2UI HTML renderer~~ — `SSRHTMLRenderer` is explicitly script-free; `echarts.py` emits a payload, not a standalone interactive document
- ~~A scheduler subsystem in core parrot~~ — no job scheduler exists; scheduled runs must be an entry point invoked by external schedulers (cron/systemd/k8s) or a server-side hook, to be decided in spec
- ~~`DatasetManager.get_dataframe()` returning a raw `pd.DataFrame`~~ — it returns a `Dict[str, Any]` (info + sample); raw frames come from `get_dataset_entry(name).df`

---

## Parallelism Assessment

- **Internal parallelism**: Moderate. Natural seams: (1) core recipe models + transformer
  registry + built-in transformer library, (2) stores (file + DB), (3) runner + toolkit tools,
  (4) interactive-html renderer (different package), (5) REST handler + scheduled entry
  (different package). (4) and (5) touch disjoint packages and could run in parallel worktrees
  after (1) lands; (1)→(2)→(3) are sequential (shared models).
- **Cross-feature independence**: No conflict with in-flight FEAT-322 (agent-host-protocol)
  or FEAT-323 (dev-loop). Touches `infographic_toolkit.py`, which FEAT-273 finished modifying
  (merged). FEAT-306 worktree contains a stale copy of `dataset_manager/tool.py` but we do not
  modify that file.
- **Recommended isolation**: per-spec (single worktree, sequential tasks).
- **Rationale**: the dependency spine (models → stores → runner → tools) dominates the task
  graph; only 2 of ~8 tasks are truly independent, so worktree-per-task overhead outweighs the
  gain. Order renderer/handler tasks after the models task within the same worktree.

---

## Open Questions

- [ ] Interactive-html renderer scope: reuse vendored ECharts only, or also vendor a
  Chart.js-equivalent to match the reference template's visuals? What is the minimum JS
  behavior set (day tabs, metric toggle, column sort) for v1? — *Owner: spec author*
- [ ] Recipe versioning semantics: SkillRegistry-style new-version-per-edit with history, or
  simple overwrite + `updated_at` for v1? — *Owner: Jesus*
- [ ] Refresh-parameter templating: plain `{param}` substitution into SQL/conditions plus a
  small set of built-in relative-date resolvers (`current_month`, `yesterday`), or a richer
  expression syntax? — *Owner: spec author*
- [ ] PBAC context on replay: scheduled/REST runs execute under the recipe owner's permission
  context or the invoker's? (DatasetManager guards need a `pctx`.) — *Owner: Jesus*
- [ ] DBRecipeStore placement: table + migrations in ai-parrot-server (like datasets handler
  storage) or core? — *Owner: spec author*
- [ ] Scheduled trigger mechanism: document external-cron invocation only (CLI/REST), or ship
  a server-side periodic task hook? — *Owner: Jesus*
- [ ] Should the LLM-assisted "repair" path (schema drift → propose remapped recipe) be a
  fast-follow feature? (Explicitly out of v1 per fail-fast decision.) — *Owner: Jesus*
