# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Brainstorm: DataAgent — Dashboard-Style Infographic Generation with Deterministic Refresh

**Date**: 2026-08-17
**Author**: Jesus (with Claude)
**Status**: exploration
**Recommended Option**: A

---

## Problem Statement

Users want to hand an agent a set of data origins — QuerySource query-slugs (e.g.
`flex_msl_brian_bi`, `fm_regions_avg_employees_html`, `fm_rep_utilization`) plus an
uploaded Excel workbook — and receive a **multi-tab, filterable dashboard** with
widgets like "Worked Hours by Month", "Payroll by Month", "P&L Revenue by Month",
"Pay Code Hours" (see the hand-built reference `documents/test.html`).

Today this dashboard is hand-authored HTML. Building it with an agent requires:

1. An example agent (`agents/data.py`, `DataAgent(PandasAgent)`) that orchestrates
   the existing tool fleet (QSourceTool, ExecutionPlanToolkit, WorkingMemoryToolkit,
   ExcelIntelligenceToolkit, InfographicToolkit, InteractiveToolkit, PythonPandasTool,
   SensitivityAnalysisTool, ThinkTool, WhatIfToolkit).
2. Output as **structured A2UI JSON** (frontend-renderable) **plus** a backend-rendered
   self-contained HTML artifact with a URL.
3. **Deterministic refresh**: the provenance of every widget (which slug, which
   transformation, which chart shape) must be recorded so the dashboard can be
   re-generated with fresh data *without* re-running the LLM loop — later exposed via
   an HTTP handler (follow-up feature).
4. LLM-generated **templates**: when no template exists for the requested exploration
   (e.g. "Payroll Contribution"), the agent must generate one and persist it under
   `BASE_DIR/templates/infographics/` for reuse.
5. Infra for InfographicToolkit to run Python **pre/post-processing** of the data as
   part of the (replayable) pipeline, with the LLM aware of that capability.

The reference `documents/test.html` also exposes a problem to fix: it fetches data
client-side with a **QuerySource API key embedded in the HTML**. The new pipeline must
bake data into the artifact (FEAT-326 data-splice pattern) instead of leaking keys.

**Who is affected**: end users (self-service BI dashboards from chat), developers
(reusable dashboard infra), ops (scheduled/deterministic refresh without LLM cost).

## Constraints & Requirements

- Output = A2UI `CreateSurface` envelope (frontend) **and** persisted self-contained
  HTML artifact + URL (backend renderer). Single source of truth: the envelope.
- Refresh must be deterministic-first: replay recorded provenance, no LLM in the loop
  (LLM only as fallback for schema-drift repair — out of v1 scope).
- Build ON TOP of FEAT-324 recipes (RecipeRunner, stores, transformer_registry,
  dry-run gate, PBAC-aware replay) — decided in discovery, do not fork a parallel
  manifest subsystem.
- New recipe step type `python_code` is accepted (discovery decision): recipes may
  store literal LLM-authored pandas code, replayed inside the same sandbox
  `PythonPandasTool` uses. Registry transformers remain the preferred path.
- Excel/TmpFile datasets: freeze a **parquet snapshot** at generation time,
  referenced by the manifest; refresh reuses the snapshot unless a new file is
  provided as a parameter (discovery decision).
- HTML is fully self-contained: datasets baked as JSON, tabs/filters implemented in
  vanilla client-side JS (discovery decision). No CDN, no live API calls, no API keys.
- Main agent LLM: `anthropic` Opus 5 (`llm = "anthropic:claude-opus-5"` class-attr
  string — agents never construct clients directly). ExecutionPlan planning on a
  cheaper model via the toolkit's existing `planner_llm` kwarg (Haiku/Sonnet).
  NOTE (verified): `AnthropicClient` has **no** `thinking=` kwarg; Fable/Opus-class
  models use adaptive thinking, and only the Bedrock client exposes `thinking_budget`.
- Templates live at `BASE_DIR.joinpath("templates", "infographics")` (new convention;
  `INFOGRAPHIC_RENDER_TEMPLATE_DIRS` config already exists, fallback `[]`).
- Async-first, Pydantic models, Google docstrings, `self.logger` (project standards).

---

## Options Explored

### Option A: Dashboard Recipes + A2UI Dashboard Component (extend FEAT-324 end-to-end)

Extend the existing recipe subsystem from "one infographic = one recipe" to
"one dashboard = one recipe with N widgets", and give A2UI a first-class
dashboard vocabulary:

1. **A2UI catalog**: new `Dashboard` composite component (tabs → widget slots) plus a
   `FilterBar` component (multi-select w/ search, range slider, date-range — the
   controls observed in `documents/test.html`). Widgets are the existing `Chart`,
   `DataTable`, `KPICard`, `Map` components — no widget duplication. This finally
   types the "tabs" concept that today survives only as an unschema'd `Chart`
   property that the infographic adapter flattens away.
2. **Recipes**: new `DashboardRecipe` model (schema-versioned, YAML/JSON) =
   dashboard-level `data_sources[]` + per-widget `{data refs, transforms, layout}` +
   tabs/filters layout + render spec. New `PythonCodeStep` step type alongside
   `TransformStep`: stores literal pandas code executed in the sandboxed REPL at
   replay (pre/post-processing infra, principle #3). `RecipeRunner` grows a
   `run_dashboard()` path reusing its fetch → gate → transform → assemble → render →
   persist stages per widget.
3. **Excel snapshots**: new `FileSnapshotSource(DataSource)` — at generation time the
   uploaded workbook's extracted tables are persisted as parquet snapshots; the
   recipe's `DataSourceSpec` can reference them; replay accepts an optional
   `replace_file` param to re-ingest a new workbook.
4. **Renderer**: new `dashboard-html` render profile in ai-parrot-visualizations,
   generalizing `InteractiveHTMLRenderer`: baked Chart.js, baked JSON dataModel,
   tab switching + FilterBar behavior (client-side recompute per filter selection)
   in vanilla JS. Self-contained, no external calls.
5. **Template lane**: dashboard templates are **declarative A2UI layout JSON**
   (parametrized Dashboard/FilterBar/widget-slot trees) stored in
   `BASE_DIR/templates/infographics/`. If the requested template is missing, the
   agent generates one from the brief (tool: `dashboard_generate_template`),
   validates it against the catalog, persists it. A seed `payroll-contribution`
   template derived from `documents/test.html`'s structure ships with the feature.
6. **Agent**: `agents/data.py` `DataAgent(PandasAgent)` example wiring the ten tools
   (porygon.py pattern: class-attr `llm`, toolkits registered in `configure()`),
   plus `DataAgent.refresh_dashboard(name, params=None)` → deterministic
   `RecipeRunner` replay (HTTP handler in a follow-up).

✅ **Pros:**
- Deterministic refresh is *inherited*, not invented: dry-run gate, PBAC context on
  replay (spec G8), stores, scheduled-refresh entry point already exist.
- Frontend gets a real, typed dashboard component (A2UI-first, per discovery).
- Widgets reuse the 9-component catalog and its enforced `lower()` contracts.
- Fixes the API-key-in-HTML security hole of the reference dashboard.
- `python_code` step is contained: one new step type, executed in the same sandbox
  the agent already uses (plotly/altair only, no matplotlib).

❌ **Cons:**
- Highest scope: touches catalog, recipes, runner, renderer, toolkit, agent.
- New catalog components need frontend counterparts eventually (A2UI consumers).
- `python_code` replays LLM-authored code → weaker guarantees than registry
  transformers (mitigated: sandbox + recipe ownership + dry-run).

📊 **Effort:** High

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `pandas` / `pyarrow` | parquet snapshots for Excel data | already dependencies |
| Chart.js 4.5.1 (vendored) | chart rendering in HTML | already baked in `formats/assets/chart.umd.min.js` |
| `openpyxl` | Excel extraction | already used by `excel_analyzer.py` |
| `PyYAML` | recipe serialization | already used by recipe store |

🔗 **Existing Code to Reuse:**
- `parrot/outputs/a2ui/recipes/` — models, stores, transformer registry (extend)
- `parrot/tools/infographic_recipes/runner.py` — `RecipeRunner` stages (extend)
- `parrot/tools/infographic_toolkit.py` — recipe tools + `_persist` + PBAC ContextVar
- `parrot/outputs/a2ui/catalog/` — `register_component`, validation
- `parrot-visualizations .../a2ui_renderers/interactive_html.py` — base for `dashboard-html`
- `parrot/storage/artifacts.py` + `artifact_signing.py` — persistence + public URL
- `parrot/tools/dataset_manager/` — sources, `add_dataframe_from_file`, excel_analyzer
- `agents/porygon.py` — example-agent wiring pattern

---

### Option B: Template-First Data-Splice (LLM-authored HTML, thin A2UI)

Skip new A2UI components. The dashboard IS an HTML template: the LLM generates (or
reuses) a full multi-tab HTML file in the style of `documents/test.html` (minus the
live fetches), stored in `templates/infographics/`. Rendering uses the existing
FEAT-326 **data-splice** lane (`render_data_template`): datasets are JSON-injected
into a `<script type="application/json">` marker. The manifest records, per payload
key, the slug/transforms that produced it; refresh = re-fetch + re-transform +
re-splice into the same template. A2UI output is a thin `Infographic` envelope
carrying the artifact link (what the Jinja lane already emits).

✅ **Pros:**
- Smallest infra delta: `render_data_template`, template engine, artifact persistence
  all exist today; refresh is byte-stable (same template, new payload).
- Pixel-fidelity with the reference dashboard — the LLM can clone `test.html`'s look.
- Template generation is a pure-LLM concern; no catalog schema work.

❌ **Cons:**
- **A2UI story collapses**: the frontend gets an opaque "here's an HTML artifact"
  envelope, not renderable widgets — contradicts the discovery decision for a real
  dashboard component.
- LLM-authored HTML+JS (~3k lines in the reference) is fragile to generate, hard to
  validate, and un-diffable; widget provenance maps to anonymous JS functions.
- Filters/tabs behavior must be regenerated per template — no shared, tested runtime.

📊 **Effort:** Medium

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| Jinja2 / `TemplateEngine` | template storage & splice | exists (`parrot/template/engine.py`) |
| Chart.js (vendored) | charts inside generated HTML | must be inlined by the generator |

🔗 **Existing Code to Reuse:**
- `InfographicToolkit.render_data_template` + `_splice_payload` (FEAT-326)
- `parrot/tools/infographic_sections.py` — `SectionDescriptor` payload gate
- FEAT-324 recipes for the fetch/transform half of refresh

---

### Option C: InteractiveToolkit Canvas Dashboard

Build on `InteractiveToolkit` (`parrot/tools/interactive_toolkit.py`) and its existing
`dashboard.html` scaffold (`parrot/tools/interactive/catalog/templates/dashboard.html`):
the agent computes data, then calls `interactive_render(template_name="dashboard",
brief=..., data_context=...)`; the LLM "enhance" pass writes the widgets/JS into the
scaffold. Persist per-widget provenance separately for refresh.

✅ **Pros:**
- The dashboard scaffold and the render/persist loop already exist.
- Fastest path to a demo.

❌ **Cons:**
- Enhance-mode is **LLM-in-the-loop by design** → refresh is inherently
  non-deterministic (regenerating JS each time defeats principle #2).
- The interactive catalog is a separate registry from A2UI — no typed envelope for
  the frontend, weak validation.
- Provenance capture must be bolted on with no recipe integration.

📊 **Effort:** Medium

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `InteractiveToolkit` | scaffold + enhance render | exists |

🔗 **Existing Code to Reuse:**
- `parrot/tools/interactive_toolkit.py`, `parrot/tools/interactive/catalog/`

---

### Option D (unconventional): Live-Fetch Dashboards with Server Proxy

Embrace what `documents/test.html` actually does: the HTML holds **no data**, only
widget definitions; each widget fetches its slug through a server-side authenticated
proxy endpoint (`/proxy/queries/<slug>` — no API key in the HTML). "Refresh" becomes
trivial: reload the page. The manifest exists only to rebuild widget *definitions*.

✅ **Pros:**
- Always-fresh data with zero replay machinery; tiny HTML artifacts.
- Matches the reference implementation's mental model.

❌ **Cons:**
- Contradicts the discovery decision (self-contained HTML) — artifacts die outside
  the network / after auth expiry; sharing a file no longer works.
- Excel-derived widgets cannot live-fetch (no server-side source for an uploaded
  tmpfile) → two divergent widget lifecycles.
- Requires the HTTP proxy + per-slug authZ *now*, pulling the follow-up handler
  feature into v1.

📊 **Effort:** Medium-High (mostly server/auth work)

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| aiohttp handlers | authenticated query proxy | `parrot/handlers/` (ai-parrot-server) |

🔗 **Existing Code to Reuse:**
- QuerySource API client (`parrot_tools/qsource.py`), PBAC slug policies (`policies/slugs.yaml`)

---

## Recommendation

**Option A** is recommended.

- It is the only option consistent with all three discovery decisions: extend
  FEAT-324 recipes (not a parallel manifest), a **new A2UI dashboard component**
  (not an opaque HTML blob), and **self-contained HTML** (not live fetch).
- The expensive-looking parts are mostly already built: replay determinism, dry-run
  gating, PBAC-on-replay, stores, artifact persistence, a Chart.js-baked HTML
  renderer, and client-side tab/sort behaviors all exist. Option A's real new code
  is: two catalog components, one recipe model + one step type, one renderer profile,
  one DataSource, one template-generation tool, and the example agent.
- What we trade off: delivery speed (Option B/C demo sooner) and the purity of the
  registry-transformers-only replay boundary (the `python_code` step weakens G2's
  guarantee). Both are acceptable: B and C each violate a core discovery decision,
  and the `python_code` step is contained by the existing REPL sandbox, recipe
  ownership scoping, and the dry-run gate.

---

## Feature Description

### User-Facing Behavior

- User (chat or API): *"Based on query-slugs `fm_rep_utilization`,
  `fm_regions_avg_employees_html`, `flex_msl_brian_bi` and this Excel, generate a
  dashboard exploring Payroll Contribution by Rep Utilization, Regions, Proximity
  Staffing and Payroll Contribution."*
- The agent fetches the slugs (QSourceTool / DatasetManager), inspects the Excel
  (ExcelIntelligenceToolkit), plans heavy processing (ExecutionPlanToolkit on a
  cheap `planner_llm`), stages intermediates (WorkingMemoryToolkit / PythonPandasTool),
  picks or generates a dashboard template, builds widgets, and returns:
  1. an **A2UI envelope** (`Dashboard` component: tabs → FilterBar + Chart/DataTable/
     KPICard/Map widgets, dataModel with baked datasets) for the frontend, and
  2. an **HTML artifact URL** (self-contained page rendered by the `dashboard-html`
     profile, persisted via ArtifactStore with a signed public URL).
- A saved `DashboardRecipe` records every widget's provenance. Later,
  `DataAgent.refresh_dashboard("payroll-contribution", params={...})` re-runs the
  pipeline deterministically (fresh slug data; Excel snapshot reused unless
  `replace_file=` given) and yields a new envelope + artifact — no LLM.
- If no template matches the request, the agent generates one (multi-tab + filters,
  seeded from the structure extracted from `documents/test.html`), stores it in
  `BASE_DIR/templates/infographics/`, and reports that a new template was created.

### Internal Behavior

1. **Acquire**: DatasetManager datasets from slugs (`QuerySlugSource`) + Excel tables
   via `excel_analyzer` → DataFrames; Excel tables snapshotted to parquet and
   registered as `FileSnapshotSource` entries.
2. **Process**: registry transformers where possible; otherwise the agent writes
   pandas code in the REPL and freezes it as a `PythonCodeStep` (code text + input/
   output keys + required columns). ExecutionPlanToolkit optionally orchestrates
   multi-step processing as a tool-only DAG (plans cannot host per-node LLMs —
   verified; only the toolkit-level `planner_llm` knob exists).
3. **Compose**: agent (or template) declares the Dashboard layout: tabs, FilterBar
   specs (field, control type, affected widgets), widget slots bound to dataModel
   pointers. Toolkit validates against the catalog (extended `validate_envelope`).
4. **Freeze**: `dashboard_save_recipe` normalizes envelope + provenance into a
   `DashboardRecipe`, dry-runs it, persists to the recipe store (file store dir
   colocated with template/output conventions).
5. **Render & persist**: `dashboard-html` renderer bakes dataModel + Chart.js +
   filter/tab JS into one HTML doc; `ArtifactStore.save_artifact` +
   `build_public_html_url` produce the URL. Envelope + URL returned via the
   `return_direct` path PandasAgent already handles for `InfographicRenderResult`.
6. **Refresh**: `RecipeRunner.run_dashboard(name, params, pctx)` replays stages 1→5
   without the LLM. Filters are client-side; refresh only re-bakes data.

### Edge Cases & Error Handling

- **Schema drift on refresh**: dry-run/`validate_inputs` fails with structured
  `RecipeRunError` (stage=`data`/`transform`) — surfaced, never silently rendered.
- **`python_code` step failure or forbidden imports**: sandbox rejects; error carries
  the widget id; other widgets still render (per-widget isolation, dashboard marked
  partial).
- **Excel snapshot missing/corrupt**: refresh errors with an actionable "provide
  `replace_file`" message; other (slug-fed) widgets unaffected.
- **Oversized dataModel**: renderer enforces a per-dashboard embedded-data budget
  (row caps per widget with `truncated=true` flags, mirroring DataTable semantics).
- **Template generation produces invalid layout**: catalog validation rejects before
  persistence; agent retries or falls back to the seed template.
- **No recipe store configured**: dashboard recipe tools are excluded from
  `get_tools()` (same pattern as FEAT-324's `_RECIPE_TOOL_NAMES`); generation still
  works, refresh is unavailable and says so.

---

## Capabilities

### New Capabilities
- `a2ui-dashboard-catalog`: `Dashboard` + `FilterBar` A2UI catalog components with
  schemas, instructions, and `lower()` fallbacks.
- `dashboard-recipes`: `DashboardRecipe` model, `PythonCodeStep` step type,
  `RecipeRunner.run_dashboard`, store integration, freeze path + toolkit tools.
- `excel-snapshot-source`: `FileSnapshotSource` DataSource (parquet snapshot,
  replaceable on refresh) + DatasetManager registration.
- `dashboard-html-renderer`: `dashboard-html` A2UI render profile
  (ai-parrot-visualizations) — tabs, filters, baked data, no external calls.
- `infographic-template-store`: declarative dashboard templates under
  `BASE_DIR/templates/infographics/` + LLM template-generation tool + seed
  `payroll-contribution` template.
- `data-agent-example`: `agents/data.py` `DataAgent(PandasAgent)` +
  `refresh_dashboard()` method (HTTP handler = follow-up feature).

### Modified Capabilities
- `infographic-builder` (FEAT-324): recipe models/runner/toolkit extended for
  dashboards and the `python_code` step.

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `parrot/outputs/a2ui/recipes/models.py` | extends | `DashboardRecipe`, `PythonCodeStep`, widget spec models |
| `parrot/tools/infographic_recipes/runner.py` | extends | `run_dashboard()` path; python-code execution stage |
| `parrot/tools/infographic_toolkit.py` | extends | dashboard render/freeze/replay tools + template-gen tool |
| `parrot/outputs/a2ui/catalog/components/` | extends | new `dashboard.py`, `filterbar.py` |
| `parrot/outputs/a2ui/builders.py` | extends | `build_dashboard`, `build_filterbar` deterministic builders |
| `ai-parrot-visualizations a2ui_renderers/` | extends | new `dashboard_html.py` profile (base: `interactive_html.py`) |
| `parrot/tools/dataset_manager/sources/` | extends | new `file_snapshot.py` (`FileSnapshotSource`) |
| `parrot/conf.py` | extends | `templates/infographics` default for `INFOGRAPHIC_RENDER_TEMPLATE_DIRS`-style config |
| `agents/` (repo root) | adds | `agents/data.py` example (not shipped in packages) |
| `parrot/bots/data.py` (PandasAgent) | depends on | reuses `return_direct` post-loop branch; no breaking change |
| ai-parrot-server handlers | none (v1) | refresh HTTP handler is an explicit follow-up |

No breaking changes intended; all new toolkit kwargs optional (FEAT-324 precedent).

---

## Code Context

### User-Provided Code
```text
# Source: user-provided (invocation notes)
# Example artifact: documents/test.html (457 KB, hand-built reference dashboard)
# - 4 tabs: data-tab=flex ("Rep Utilization"), regions, proximity, payroll
#   ("Payroll Contribution")
# - Multi-select filters w/ search (msf-btn/msf-search), range slider
#   (id=proximityRadius), reset buttons, KPI rows, Chart.js charts (inlined UMD),
#   inline d3-geo geoAlbersUsa US map, sortable tables.
# - DATA IS NOT EMBEDDED: each tab fetches
#   https://api.trocdigital.io/api/v2/services/queries/<slug>?apikey=<KEY-IN-HTML>
#   with a /proxy/queries/ fallback. The apikey-in-HTML must NOT be reproduced.
# Query slugs used: fm_rep_utilization, fm_regions_avg_employees_html,
#   flex_msl_brian_bi (+ flex_hours_query_pbi observed in tab 4).
# Typical prompt: "basados en los siguientes query-slugs [...] y este Excel
#   (TmpFile via upload http), genera un dashboard que explore el Payroll
#   Contribution by Rep Utilization, Regions, Proximity Staffing y Payroll
#   Contribution".
```

### Verified Codebase References

#### Classes & Signatures
```python
# From packages/ai-parrot/src/parrot/bots/data.py
class PandasAgent(IntentRouterMixin, BasicAgent):            # data.py (class def)
    async def refresh_data(self, cache_expiration: int = None, **kwargs) -> Dict[str, pd.DataFrame]  # :2294
    @classmethod
    async def load_from_files(cls, files, **kwargs) -> Dict[str, pd.DataFrame]  # :2969 (stateless; keys = stem / stem_sheet)
    def _extract_last_infographic_result(self, tool_calls)   # return_direct post-loop branch

# From packages/ai-parrot/src/parrot/tools/infographic_toolkit.py
class InfographicToolkit(AbstractToolkit):                   # :~180
    def __init__(self, *, artifact_store: ArtifactStore, template_dirs=None,
                 templates=None, emit_a2ui: bool = False,
                 recipe_store: Optional[AbstractRecipeStore] = None,
                 recipe_runner: Optional[RecipeRunner] = None,
                 dataset_manager: Optional[Any] = None, **kwargs)  # :213
    async def render_data_template(self, template_name, payload, descriptor=None,
                                   marker_id="report-data", title=None)  # :640 (FEAT-326 data-splice)
    async def infographic_save_recipe(self, name, title, layout_component,
        layout_properties, dataset_names, transform_steps, description=None,
        render_profile="interactive-html", theme=None)       # :1241
    async def infographic_run_recipe(self, name, params=None)  # :1356

# From packages/ai-parrot/src/parrot/outputs/a2ui/recipes/models.py
class TransformStep(BaseModel):   # :80 — transformer/inputs[]/params{}/output_key (ONLY step type today)
class LayoutSpec(BaseModel):      # :99 — single root {component, properties}
class InfographicRecipe(BaseModel):  # :175 — schema_version=1, name, params[], data_sources[], transforms[], layout, render, schedule
class RecipeRunError(BaseModel):  # :268 — stage: params|data|gate|transform|layout|render

# From packages/ai-parrot/src/parrot/outputs/a2ui/recipes/store.py
class AbstractRecipeStore:        # :125 — async save/get/list/delete(name, owner=None)
class FileRecipeStore(AbstractRecipeStore):  # :165 — <dir>/<name>.yaml, atomic write
class DBRecipeStore(AbstractRecipeStore):    # :231 — Redis w/ in-memory fallback

# From packages/ai-parrot/src/parrot/tools/infographic_recipes/runner.py
class RecipeRunner:
    def __init__(self, store, dataset_manager, *, artifact_store=None,
                 owner=None, narrator=None)                  # :208
    async def run(self, name, *, params=None, pctx=None,
                  recipe_owner=None) -> RenderedArtifact     # :224
    async def dry_run(self, recipe) -> list[RecipeRunError]  # :273

# From packages/ai-parrot/src/parrot/tools/infographic_recipes/freeze.py
async def freeze_session_envelope(envelope: CreateSurface, *, dataset_names,
    transform_steps, name, title, runner, description=None, owner=None,
    params=None, render_profile="interactive-html", theme=None) -> InfographicRecipe  # :64
    # raises FreezeProvenanceError (:39) when len(envelope.components) != 1 —
    # dashboards need a new freeze path or a relaxed single-root Dashboard component

# From packages/ai-parrot/src/parrot/outputs/a2ui/recipes/transformers.py
transformer_registry: TransformerRegistry    # :161 (module singleton)
@infographic_transformer(name, *, requires_columns=None, description="", params_schema=None)  # :164
# 8 built-ins (recipes/library.py): day_totals, division_breakdown, variance_analysis,
# top_movers, narrative_facts, groupby_aggregate, pivot, latest_vs_baseline

# From packages/ai-parrot/src/parrot/outputs/a2ui/ (catalog & builders)
def register_component(name, *, requires_actions=False, catalog_id=DEFAULT_CATALOG_ID)  # catalog/__init__.py:57
def validate_envelope(envelope, origin=...)   # catalog/__init__.py:165
class CreateSurface(A2UIMessageBase):         # models.py:167 — surfaceId, catalogId, components[], dataModel
def build_surface(component, properties, *, surface_id, component_id="blk-000", data_model=None)  # builders.py:44
# Registered components (exactly 9): Card, Chart, DataTable, Form, Infographic,
# KPICard, Map, Report, Timeline (catalog/components/__init__.py)

# From packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/interactive_html.py
class InteractiveHTMLRenderer(AbstractA2UIRenderer):  # :217, registered "interactive-html" :211
    async def render(self, envelope: CreateSurface, *, bake: bool = True) -> RenderedArtifact  # :220
# Chart.js UMD 4.5.1 vendored at parrot/outputs/formats/assets/chart.umd.min.js (:78-84)
# Behavior JS hooks: [data-chart-config], [data-tabs-for], [data-metric-toggle-for], [data-sort-table]

# From packages/ai-parrot/src/parrot/outputs/a2ui/renderers/__init__.py
def register_a2ui_renderer(name, capabilities)  # :97
def get_a2ui_renderer(name)                     # :130 — registry → importlib parrot.outputs.a2ui_renderers.<name>

# From packages/ai-parrot/src/parrot/storage/
class ArtifactStore:                                     # artifacts.py:27
    async def save_artifact(self, user_id, agent_id, session_id, artifact: Artifact) -> None  # :46
def build_public_html_url(artifact_id, *, user_id=None, agent_id=None,
    session_id=None, expiry_seconds=None, key=None) -> str  # artifact_signing.py:99
# → "/api/v1/artifacts/public/{expiry}.{sig}/{artifact_id}.html?..." (served by ArtifactPublicHTMLView)
# ArtifactType (models.py:244): CHART, MAP, TABLE, CANVAS, INFOGRAPHIC, INTERACTIVE, DATAFRAME, EXPORT

# From packages/ai-parrot/src/parrot/tools/ — the agent's tool fleet (ALL verified)
class ExecutionPlanToolkit(AbstractToolkit):  # execution_plan/toolkit.py:61
    def __init__(self, *, tool_manager, working_memory: "WorkingMemoryToolkit",
                 planner_llm=None, plans_dir=None, allowed_tools=None,
                 soft_timeout=60.0, permission_context=None,
                 on_node_event=None, max_completed_runs=50, **kwargs)  # :93
    # tools: plan_execute :432, plan_validate :462, plan_status :385, plan_artifacts :408
    # planner_llm accepts "provider:model" string / client / model_config dict
    #   via resolve_planner_client (execution_plan/planner.py:60)
class WorkingMemoryToolkit:                   # working_memory/tool.py:44, name="working_memory"
    def __init__(self, session_id=None, max_rows=10, max_cols=30,
                 tool_locals_registry=None, answer_memory=None,
                 thread_offload_cells=None, **kwargs)  # :103
class ExcelIntelligenceToolkit:               # excel_intelligence.py:18, tool_prefix="excel"
    # tools: inspect_workbook :59, extract_table :96, query_cells :170 (all async -> str)
class InteractiveToolkit(AbstractToolkit):    # interactive_toolkit.py:74
    def __init__(self, *, artifact_store: ArtifactStore, catalog=None,
                 emit_a2ui: bool = False, **kwargs)  # :90
class PythonPandasTool(PythonREPLTool):       # pythonpandas.py:25, name="python_repl_pandas"
    # sandbox plotting: plotly + altair ONLY (matplotlib/seaborn blocked, FEAT-423)

# From packages/ai-parrot-tools/src/parrot_tools/
class QSourceTool(AbstractTool):              # qsource.py:62, name="QSourceTool"
    def __init__(self, default_driver="db", available_structured_outputs=None, **kwargs)  # :81
class SensitivityAnalysisTool(AbstractTool):  # sensitivity_analysis.py:42
    # resolves data ONLY via self._parent_agent.dataframes — agent must set _parent_agent
class ThinkTool(AbstractTool):                # think.py:76 — do NOT pair with native extended thinking
class WhatIfToolkit(AbstractToolkit):         # whatif_toolkit.py:169 (PREFER over legacy WhatIfTool)
    def __init__(self, dataset_manager=None, pandas_tool=None, **kwargs)  # :176
class WhatIfTool(AbstractTool):               # whatif.py:973 — __init__(self) takes NO kwargs

# From packages/ai-parrot/src/parrot/clients/claude.py
class AnthropicClient(AbstractClient):        # :67 — model/max_tokens via **kwargs -> AbstractClient
    # NO thinking= kwarg; adaptive-thinking models normalize/strip thinking payloads (:269-306)
    # Bedrock client has per-call thinking_budget (bedrock.py:594) — NOT the direct client

# From packages/ai-parrot/src/parrot/tools/dataset_manager/
class QuerySlugSource(DataSource):            # sources/query_slug.py:36
    def __init__(self, slug: str, prefetch_schema_enabled=True, permanent_filter=None)  # :51
class MultiQuerySlugSource(DataSource):       # sources/query_slug.py:165 — __init__(slugs: List[str]) :175
# DatasetManager.add_dataframe_from_file(name, path, ...)  # tool.py:1171 (csv/xls/xlsx/xlsm/xlsb/ods → InMemorySource)
# DatasetManager.load_file(name, path, ...)                # tool.py:1222 (LLM-context structural load)
# DatasetManager.add_dataset(...)                          # tool.py:966 — one of query_slug|query|table|dataframe; NO file kwarg
```

#### Verified Imports
```python
from parrot.bots.data import PandasAgent                       # packages/ai-parrot/src/parrot/bots/data.py
from parrot.tools.execution_plan import ExecutionPlanToolkit   # execution_plan/__init__.py:24 (NOT top-level parrot.tools)
from parrot.tools.working_memory import WorkingMemoryToolkit   # working_memory/__init__.py:2 (used by agents/porygon.py:9)
from parrot.tools.excel_intelligence import ExcelIntelligenceToolkit  # NOT top-level; zero non-test call sites today
from parrot.tools.interactive_toolkit import InteractiveToolkit  # also lazy top-level (tools/__init__.py:267)
from parrot.tools.pythonpandas import PythonPandasTool         # also lazy top-level (tools/__init__.py:260)
from parrot_tools.qsource import QSourceTool
from parrot_tools.sensitivity_analysis import SensitivityAnalysisTool
from parrot_tools.think import ThinkTool
from parrot_tools.whatif_toolkit import WhatIfToolkit
from parrot.tools.infographic_toolkit import InfographicToolkit, InfographicRenderResult
from parrot.outputs.a2ui.recipes.models import InfographicRecipe, TransformStep, RecipeRunError
from parrot.outputs.a2ui.recipes.store import AbstractRecipeStore, FileRecipeStore, DBRecipeStore
from parrot.outputs.a2ui.recipes.transformers import transformer_registry, infographic_transformer
from parrot.tools.infographic_recipes.runner import RecipeRunner, RecipeRunException
from parrot.tools.infographic_recipes.freeze import freeze_session_envelope
from parrot.outputs.a2ui.models import CreateSurface, Component
from parrot.outputs.a2ui.catalog import register_component, validate_envelope
from parrot.outputs.a2ui.renderers import register_a2ui_renderer, get_a2ui_renderer
from parrot.storage.artifacts import ArtifactStore
from parrot.storage.artifact_signing import build_public_html_url
from parrot.conf import BASE_DIR, STATIC_DIR                   # conf.py:5,:43
from parrot.registry import register_agent                     # agents/porygon.py:? pattern
```

#### Key Attributes & Constants
- `OutputMode.A2UI = "a2ui"` → `parrot/models/outputs.py:64`; STRUCTURED_CHART/TABLE/MAP at :61-63
- `DEFAULT_CATALOG_ID = "https://parrot.dev/catalogs/v1"` → `a2ui/catalog/base.py:40`
- `INFOGRAPHIC_RENDER_TEMPLATE_DIRS: list[str]` (fallback `[]`) → `conf.py:864`
- Renderer profiles registered today: `ssr_html`, `interactive-html`, `echarts`, `pdf`, `folium_map`, `adaptive_cards`
- Example-agent pattern (`agents/porygon.py`): `@register_agent(name=...)`; class-attr `llm = "provider:model"`; toolkits registered in `configure()` via `self.tool_manager.register_toolkit(tk)` before `await super().configure(...)`
- `InfographicToolkit` recipe tools are conditionally exposed via `exclude_tools` when `recipe_store is None` (`_RECIPE_TOOL_NAMES`, infographic_toolkit.py) — follow the same pattern for dashboard tools

### Does NOT Exist (Anti-Hallucination)
- ~~A2UI `Tabs` / `TabView` / `Filter` / `Dashboard` / `Grid` / `Layout` catalog component~~ — the catalog has exactly 9 components; "tabs" exist only as an unschema'd `Chart` property read by `InteractiveHTMLRenderer` (:344-366) and as legacy `BlockType.TAB_VIEW` blocks that the A2UI adapter **flattens away** (`a2ui/adapters/infographic.py:415-443`)
- ~~A recipe step type other than `TransformStep`~~ — no python-code step, no filter step, no conditional step (this feature adds `PythonCodeStep`)
- ~~`ExcelSource` / `FileSource` / `TmpFileSource` / `ParquetSource` DataSource~~ — file ingestion exists only ABOVE the source layer (`add_dataframe_from_file` → `InMemorySource`); `add_dataset()` has NO `file=` kwarg, so recipes cannot reference files today (this feature adds `FileSnapshotSource`)
- ~~Per-plan / per-node LLM override in ExecutionPlan~~ — `PlanNode` is tool-only (`extra="forbid"`, no `agent_ref`/`model` field); the only model knob is toolkit-level `planner_llm`
- ~~`AnthropicClient(thinking=...)` or `ask(thinking_budget=...)` on the direct client~~ — only `bedrock.py` exposes `thinking_budget` (:594)
- ~~`from parrot.tools import ExecutionPlanToolkit / ExcelIntelligenceToolkit / WorkingMemoryToolkit`~~ — not in top-level lazy exports nor `parrot_tools.TOOL_REGISTRY`; use the subpackage paths
- ~~`WhatIfTool(name=...)`~~ — legacy `WhatIfTool.__init__(self)` accepts no kwargs; use `WhatIfToolkit`
- ~~`templates/infographics/` directory~~ — does not exist anywhere in the repo yet
- ~~`agents/data.py`~~ — does not exist yet (confirmed); repo-root `agents/` is the example-agent home
- ~~`MemoryRecipeStore` / SQL recipe store~~ — only `FileRecipeStore` and Redis-backed `DBRecipeStore` (with in-memory fallback)
- ~~matplotlib/seaborn inside `PythonPandasTool`~~ — sandbox allows plotly + altair only (FEAT-423)
- ~~Artifacts persisted to `STATIC_DIR` by the A2UI/infographic path~~ — they persist via `ArtifactStore` (DB backend + S3 overflow) and are served through `build_public_html_url` signed routes; "URL to HTML on disk" should be interpreted as the artifact public URL (open question below)
- ~~Multi-component freeze~~ — `freeze_session_envelope` raises when `len(envelope.components) != 1`; the dashboard freeze path must either relax this or make `Dashboard` the single root component

---

## Parallelism Assessment

- **Internal parallelism**: Moderate. Cleanly separable lanes exist — (a) A2UI
  catalog components + builders, (b) `dashboard-html` renderer (satellite package),
  (c) `FileSnapshotSource`, (d) recipe models/runner/toolkit, (e) template store +
  generation, (f) `DataAgent` example. However (d) is the hub: (a), (c), (e), (f)
  all converge on `recipes/models.py`, `runner.py`, and especially
  `infographic_toolkit.py` (a hot, heavily-tested shared file).
- **Cross-feature independence**: Extends FEAT-324's files; no other in-flight spec
  is known to touch `infographic_toolkit.py` / `recipes/`. `agents/` root is
  conflict-free.
- **Recommended isolation**: `per-spec` (single worktree, sequential tasks).
- **Rationale**: the dependency spine (models → runner → toolkit → renderer → agent)
  is inherently sequential, and the shared hot files (`infographic_toolkit.py`,
  `recipes/models.py`) would make parallel worktrees merge-conflict magnets for
  little wall-clock gain.

---

## Open Questions

- [ ] "URL al HTML guardado en disco duro": the existing pipeline persists HTML via
  `ArtifactStore` (DB + S3 overflow) and serves it through signed
  `/api/v1/artifacts/public/...` URLs — NOT as a plain file on disk. Is the artifact
  public URL acceptable as "the URL", or must the renderer ALSO write a copy under
  `STATIC_DIR/<agent_id>/dashboards/` for direct file access? — *Owner: jesuslara*
- [ ] Dashboard recipe/manifest storage: `FileRecipeStore` directory (YAML, matches
  "JSON on disk" intent and FEAT-324) vs Redis `DBRecipeStore` — pick the default
  for `DataAgent` and whether the manifest is ALSO embedded in the artifact
  definition for self-description. — *Owner: jesuslara*
- [ ] `python_code` step guardrails: same REPL sandbox as PythonPandasTool — do we
  additionally require declared `requires_columns`/output contract per step (so
  dry-run can gate it), and cap execution time? Proposed: yes to both. — *Owner: jesuslara*
- [ ] Filter semantics v1: proposed control set = multi-select (with search),
  range slider, date-range; filters recompute client-side over baked data only
  (no server round-trip). Confirm this covers the Payroll Contribution use case. — *Owner: jesuslara*
- [ ] Embedded-data budget: `documents/test.html` is 457 KB *without* data. Define
  per-dashboard cap (e.g. total baked JSON ≤ 3–5 MB, per-widget row caps with
  `truncated` flags) and the degrade behavior. — *Owner: jesuslara*
- [ ] Opus 5 extended thinking: adaptive thinking on `anthropic:claude-opus-5` is the
  default; if explicit budgets are wanted, that's a separate small feature on
  `AnthropicClient` (Bedrock already has `thinking_budget`). Accept adaptive-only
  for v1? — *Owner: jesuslara*
- [ ] Seed template scope: derive the `payroll-contribution` seed template's tab/
  filter/widget structure from `documents/test.html` (4 tabs incl. the d3-geo map)
  — is the US map widget in scope for v1, or charts/tables/KPIs only (Map component
  exists but the dashboard renderer would need the geo behavior ported)? — *Owner: jesuslara*
