# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Feature Specification: DataAgent — Dashboard Infographics with Deterministic Refresh

**Feature ID**: FEAT-428
**Date**: 2026-08-17
**Author**: Jesus (with Claude)
**Status**: draft
**Target version**: next minor
**Brainstorm**: `sdd/proposals/agent-infographic-generation.brainstorm.md` (Option A accepted)

---

## 1. Motivation & Business Requirements

### Problem Statement

Users want to hand an agent a set of data origins — QuerySource query-slugs (e.g.
`fm_rep_utilization`, `fm_regions_avg_employees_html`, `flex_msl_brian_bi`) plus an
uploaded Excel workbook (TmpFile via HTTP upload) — and receive a **multi-tab,
filterable dashboard** with widgets like "Worked Hours by Month", "Payroll by
Month", "P&L Revenue by Month", "Pay Code Hours" (reference: hand-built
`documents/test.html`).

Today that dashboard is hand-authored HTML (~3k lines) that fetches data
client-side with a **QuerySource API key embedded in the HTML** — unshareable,
unrefreshable, and a security smell. There is no agent that produces such
dashboards, no A2UI vocabulary for tabs/filters, no replayable provenance for
multi-widget artifacts, and no file-backed DataSource that a frozen recipe can
reference for the Excel half of the data.

Typical user prompt: *"basados en los siguientes query-slugs [...] y este Excel,
genera un dashboard que explore el Payroll Contribution by Rep Utilization,
Regions, Proximity Staffing y Payroll Contribution."*

### Goals

- G1 — `DataAgent(PandasAgent)` example agent (`agents/data.py`) orchestrating the
  verified tool fleet: ExecutionPlanToolkit, WorkingMemoryToolkit,
  ExcelIntelligenceToolkit, InfographicToolkit, InteractiveToolkit,
  PythonPandasTool, QSourceTool, SensitivityAnalysisTool, ThinkTool, WhatIfToolkit.
- G2 — Output is **both** a validated A2UI `CreateSurface` envelope (new
  `Dashboard` + `FilterBar` catalog components; widgets reuse Chart/DataTable/
  KPICard/Map) **and** a persisted self-contained HTML artifact.
- G3 — HTML delivery is **dual-write**: canonical via `ArtifactStore` (signed
  public URL returned to the caller) plus a physical copy under
  `STATIC_DIR/<agent_id>/dashboards/`.
- G4 — **Deterministic refresh**: a `DashboardRecipe` records every widget's
  provenance (sources, transforms, layout); `DataAgent.refresh_dashboard(name,
  params)` replays it via `RecipeRunner` with **no LLM in the loop**.
- G5 — New `PythonCodeStep` recipe step: LLM-authored pandas pre/post-processing
  code stored in the recipe and replayed in the sandboxed REPL — **with a declared
  contract** (inputs/outputs + `requires_columns`, dry-run gateable) and a
  per-step timeout (default 30s). Freeze rejects contract-less code steps.
- G6 — Excel data is frozen as a **parquet snapshot** referenced by the recipe
  (`FileSnapshotSource`); refresh reuses the snapshot unless a new file is passed
  (`replace_file` param).
- G7 — Self-contained HTML: baked JSON dataModel (total ≤ **8 MB**, per-widget row
  cap default 25k with `truncated=true` degradation), vendored Chart.js, inline
  d3-geo `geoAlbersUsa` US map + radius slider (Map component lowering),
  client-side tabs and the extended filter set (multi-select w/ search, range
  slider, date-range, single-select dropdown, boolean toggle). Zero external
  network references, zero embedded credentials.
- G8 — Declarative dashboard **templates** (parametrized A2UI layout JSON) stored
  in `BASE_DIR/templates/infographics/`; when the requested template is missing,
  the agent generates one, validates it against the catalog, and persists it. A
  seed `payroll-contribution` template (4 tabs, derived from `documents/test.html`)
  ships with the feature.
- G9 — LLM config: `DataAgent.llm = "anthropic:claude-opus-5"` (adaptive thinking,
  no client changes); `ExecutionPlanToolkit(planner_llm="anthropic:claude-haiku-4-5-20251001")`
  (or Sonnet) for cheap plan authoring.

### Non-Goals (explicitly out of scope)

- HTTP handler exposing `refresh_dashboard` (explicit follow-up feature).
- Live-fetch dashboards (client-side API calls) — rejected in brainstorm
  (Option D, `proposals/agent-infographic-generation.brainstorm.md`).
- Server-side filter evaluation — filters are 100% client-side over baked data.
- LLM-authored raw HTML templates — rejected in brainstorm (Option B); templates
  are declarative A2UI layout JSON.
- `thinking_budget` support on the direct `AnthropicClient` — adaptive-only for
  v1 (resolved in brainstorm).
- Frontend (consumer-side) implementation of the `Dashboard`/`FilterBar`
  components — this spec delivers the catalog contract + backend renderer only.
- Scheduled refresh wiring (the `run_scheduled_refresh` entry point already
  exists; scheduling policy is out of scope).

---

## 2. Architectural Design

### Overview

Extend the FEAT-324 recipe subsystem from "one infographic = one recipe" to
"one dashboard = one recipe with N widgets", and give A2UI a first-class
dashboard vocabulary. Six coordinated additions:

1. **A2UI catalog**: `Dashboard` composite component (tabs → widget slots) and
   `FilterBar` component (the five resolved control types). Widgets are the
   existing `Chart`, `DataTable`, `KPICard`, `Map` components — no duplication.
   This types the "tabs" concept that today survives only as an unschema'd
   `Chart` property which the infographic adapter flattens away.
2. **Recipes**: `DashboardRecipe` (schema-versioned) = dashboard-level
   `data_sources[]` + per-widget `{data refs, transforms, layout}` + tabs/filters
   + render spec. New `PythonCodeStep` alongside `TransformStep`.
   `RecipeRunner.run_dashboard()` reuses the existing stage machinery
   (fetch → gate → transform → assemble → render → persist) per widget.
3. **Excel snapshots**: `FileSnapshotSource(DataSource)` — extracted workbook
   tables persisted as parquet at generation time; `DataSourceSpec` can reference
   them; replay accepts `replace_file` to re-ingest.
4. **Renderer**: `dashboard-html` A2UI render profile (ai-parrot-visualizations),
   generalizing `InteractiveHTMLRenderer`: baked Chart.js + JSON dataModel, tab
   switching, FilterBar recompute, inline d3-geo US map + radius slider, 8 MB
   budget enforcement. Persistence dual-writes ArtifactStore + STATIC_DIR copy.
5. **Templates**: declarative A2UI layout JSON under
   `BASE_DIR/templates/infographics/` + `dashboard_generate_template` tool +
   seed `payroll-contribution` template.
6. **Agent**: `agents/data.py` `DataAgent(PandasAgent)` example (porygon.py
   pattern) + `refresh_dashboard()` method.

Deterministic refresh, dry-run gating, PBAC-on-replay, stores, artifact
persistence and the Chart.js-baked HTML runtime are **inherited from FEAT-324/326
infrastructure**, not reinvented.

### Component Diagram

```
User prompt (slugs + Excel TmpFile)
        │
        ▼
DataAgent (agents/data.py, llm=anthropic:claude-opus-5)
  ├─ QSourceTool / DatasetManager(QuerySlugSource) ──── slug DataFrames
  ├─ ExcelIntelligenceToolkit ─→ excel_analyzer ─→ FileSnapshotSource (parquet)
  ├─ ExecutionPlanToolkit(planner_llm=haiku) ── tool-only DAG processing
  ├─ PythonPandasTool / WorkingMemoryToolkit ── intermediates
  ▼
InfographicToolkit (dashboard tools)
  ├─ dashboard template store (BASE_DIR/templates/infographics/)
  ├─ dashboard_render ─→ CreateSurface(Dashboard+FilterBar+widgets, dataModel)
  │        │                    │ validate_envelope (catalog)
  │        │                    ▼
  │        │            dashboard-html renderer (a2ui_renderers/dashboard_html.py)
  │        │                    │ self-contained HTML (Chart.js, d3-geo, filters JS)
  │        │                    ▼
  │        └── persist: ArtifactStore (canonical, signed URL)
  │                     + STATIC_DIR/<agent_id>/dashboards/ copy
  └─ dashboard_save_recipe ─→ DashboardRecipe ─→ FileRecipeStore (YAML)
                                                       ▲
DataAgent.refresh_dashboard(name, params) ─→ RecipeRunner.run_dashboard ──┘
  (no LLM: fetch → gate → transforms/PythonCodeStep → assemble → render → persist)
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `parrot/outputs/a2ui/recipes/models.py` | extends | `DashboardRecipe`, `WidgetSpec`, `PythonCodeStep`, `TabSpec`, `FilterSpec` |
| `parrot/tools/infographic_recipes/runner.py` | extends | `run_dashboard()` path; python-code execution stage reusing existing stage/error model |
| `parrot/tools/infographic_toolkit.py` | extends | new dashboard tools, conditionally exposed like `_RECIPE_TOOL_NAMES`; dual-write persist |
| `parrot/outputs/a2ui/catalog/components/` | extends | new `dashboard.py`, `filterbar.py` via `register_component` |
| `parrot/outputs/a2ui/builders.py` | extends | `build_dashboard`, `build_filterbar` deterministic builders |
| `ai-parrot-visualizations a2ui_renderers/` | extends | new `dashboard_html.py` profile (base: `interactive_html.py`) |
| `parrot/tools/dataset_manager/sources/` | extends | new `file_snapshot.py` (`FileSnapshotSource`) |
| `parrot/tools/infographic_recipes/freeze.py` | extends | dashboard freeze path (relax single-component rule: `Dashboard` is the single root) |
| `parrot/conf.py` | extends | dashboard template dir + snapshot dir settings |
| `parrot/bots/data.py` (`PandasAgent`) | depends on | reuses `return_direct` post-loop branch (`_extract_last_infographic_result`); no changes required to PandasAgent itself beyond what `DataAgent` subclasses |
| `agents/` (repo root) | adds | `agents/data.py` example (not shipped in packages) |
| `parrot/storage/artifacts.py` + `artifact_signing.py` | uses | `save_artifact` + `build_public_html_url` |
| ai-parrot-server handlers | none (v1) | refresh HTTP handler is a follow-up |

### Data Models

```python
# parrot/outputs/a2ui/recipes/models.py — NEW models (design sketch, not code)

class PythonCodeStep(BaseModel):
    """LLM-authored pandas step, replayed in the PythonPandasTool sandbox."""
    kind: Literal["python_code"] = "python_code"
    code: str                          # literal pandas code
    inputs: list[str]                  # frame keys consumed (declared contract)
    output_key: str                    # frame key produced (declared contract)
    requires_columns: dict[str, list[str]] = {}   # per-input column gate (dry-run)
    timeout_seconds: float = 30.0
    description: str = ""

DashboardStep = Annotated[Union[TransformStep, PythonCodeStep],
                          Field(discriminator="kind")]
# NOTE: TransformStep gains kind: Literal["transform"] = "transform" (defaulted →
# existing YAML recipes without `kind` still parse; schema_version handles drift).

class FilterSpec(BaseModel):
    id: str
    label: str
    control: Literal["multi_select", "range_slider", "date_range",
                     "single_select", "toggle"]           # resolved extended set
    field: str                          # column in the bound dataset(s)
    targets: list[str]                  # widget ids this filter affects
    searchable: bool = False            # multi_select search box
    params: dict = {}                   # min/max/step for slider, etc.

class WidgetSpec(BaseModel):
    id: str
    tab: str                            # TabSpec.id
    component: Literal["Chart", "DataTable", "KPICard", "Map"]
    properties: dict                    # catalog-schema properties ($bind allowed)
    data_key: str                       # dataModel pointer this widget binds
    steps: list[DashboardStep] = []     # widget-local transforms
    max_rows: int = 25_000              # per-widget row cap (resolved)

class TabSpec(BaseModel):
    id: str
    title: str
    filters: list[str] = []             # FilterSpec ids shown on this tab

class DashboardRecipe(BaseModel):
    schema_version: int = 1
    name: str
    title: str
    description: str = ""
    owner: Optional[str] = None
    params: list[RecipeParam] = []      # includes replace_file for snapshots
    data_sources: list[DataSourceSpec] = []   # slugs AND file snapshots
    shared_steps: list[DashboardStep] = []    # pre-processing shared by widgets
    tabs: list[TabSpec]
    filters: list[FilterSpec] = []
    widgets: list[WidgetSpec]
    render: RenderSpec                  # profile="dashboard-html"
    data_budget_bytes: int = 8_388_608  # ≤8 MB baked JSON (resolved)
    template_name: Optional[str] = None # provenance: which template produced this
    updated_at: Optional[datetime] = None

class DashboardTemplate(BaseModel):
    """Declarative, parametrized dashboard layout stored as JSON in
    BASE_DIR/templates/infographics/<name>.json (G8)."""
    schema_version: int = 1
    name: str
    title: str
    description: str = ""
    tabs: list[TabSpec]
    filters: list[FilterSpec] = []
    widget_slots: list[dict]            # WidgetSpec skeletons with param holes
    params: list[RecipeParam] = []
```

### New Public Interfaces

```python
# parrot/outputs/a2ui/builders.py
def build_dashboard(*, title, tabs, filters, widgets, data_model,
                    surface_id="dashboard") -> CreateSurface: ...
def build_filterbar(*, filters, surface_id="filterbar") -> CreateSurface: ...

# parrot/tools/infographic_recipes/runner.py
class RecipeRunner:
    async def run_dashboard(self, name, *, params=None, pctx=None,
                            recipe_owner=None) -> RenderedArtifact: ...
    async def dry_run_dashboard(self, recipe) -> list[RecipeRunError]: ...

# parrot/tools/infographic_toolkit.py — new LLM tools (conditional on recipe_store)
async def dashboard_render(...) -> InfographicRenderResult          # terminal
async def dashboard_save_recipe(...) -> dict
async def dashboard_run_recipe(name, params=None) -> InfographicRenderResult
async def dashboard_list_templates() -> list[dict]
async def dashboard_generate_template(brief, name, tabs, ...) -> dict  # persists JSON
async def dashboard_get_recipe_contract(name) -> dict

# parrot/tools/dataset_manager/sources/file_snapshot.py
class FileSnapshotSource(DataSource):
    def __init__(self, snapshot_path: str | Path, *,
                 origin_filename: str = "", sheet: str | None = None): ...

# agents/data.py (example, repo root — not shipped in packages)
@register_agent(name="data-dashboard")
class DataAgent(PandasAgent):
    llm = "anthropic:claude-opus-5"
    async def refresh_dashboard(self, name: str,
                                params: dict | None = None,
                                replace_file: str | Path | None = None
                                ) -> InfographicRenderResult: ...
```

---

## 3. Module Breakdown

### Module 1: Dashboard recipe models + PythonCodeStep
- **Path**: `packages/ai-parrot/src/parrot/outputs/a2ui/recipes/models.py` (+ new `dashboard.py` sibling if size warrants)
- **Responsibility**: `DashboardRecipe`, `WidgetSpec`, `TabSpec`, `FilterSpec`,
  `PythonCodeStep`, discriminated `DashboardStep` union; YAML round-trip;
  back-compat for existing `InfographicRecipe` YAML (defaulted `kind`).
- **Depends on**: existing recipe models (verified §6).

### Module 2: Code-step executor + RecipeRunner.run_dashboard
- **Path**: `packages/ai-parrot/src/parrot/tools/infographic_recipes/` (`runner.py` + new `code_step.py`)
- **Responsibility**: execute `PythonCodeStep` in the PythonPandasTool sandbox
  (fresh namespace per step, declared inputs injected, output extracted, timeout
  via `asyncio.wait_for`); extend dry-run to gate code-step contracts
  (`requires_columns`, inputs/outputs declared); `run_dashboard()` orchestrating
  per-widget stages with per-widget error isolation (partial dashboards).
- **Depends on**: Module 1.

### Module 3: A2UI catalog — Dashboard + FilterBar components + builders
- **Path**: `packages/ai-parrot/src/parrot/outputs/a2ui/catalog/components/dashboard.py`, `filterbar.py`; `builders.py`
- **Responsibility**: schemas + INSTRUCTIONS + `lower()` fallbacks (text summary
  of tabs/widgets, like Chart's degrade); `build_dashboard`/`build_filterbar`;
  registration in `catalog/components/__init__.py`; envelope validation covers
  nested widget components.
- **Depends on**: existing catalog registry (verified §6). Independent of Modules 1–2.

### Module 4: FileSnapshotSource
- **Path**: `packages/ai-parrot/src/parrot/tools/dataset_manager/sources/file_snapshot.py` (+ export in `sources/__init__.py`)
- **Responsibility**: parquet-backed `DataSource` (snapshot dir under
  `BASE_DIR/dashboards/snapshots/`, config-overridable); snapshot writer helper
  (DataFrame → parquet + checksum); `replace_file` re-ingest path (Excel →
  excel_analyzer tables → new snapshot, same source name); wire into
  `DatasetManager.add_dataset` (new `file_snapshot=` kwarg or registration
  helper — keep `add_dataset`'s one-of contract intact).
- **Depends on**: nothing in this spec (parallel-safe).

### Module 5: dashboard-html renderer
- **Path**: `packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/dashboard_html.py` (+ assets)
- **Responsibility**: registered profile `"dashboard-html"`; renders
  `Dashboard` envelope → single self-contained HTML doc: tab bar, FilterBar
  controls (5 types), Chart.js (existing vendored UMD), inline d3-geo
  `geoAlbersUsa` + radius-slider Map lowering (ported from `documents/test.html`,
  bundled as an asset file, no CDN), client-side filter→recompute pipeline over
  the baked dataModel; enforce `data_budget_bytes` (≤8 MB) + per-widget
  `max_rows` with `truncated=true` + visible note; zero external refs.
- **Depends on**: Module 3 (component schemas). Rendering only — persistence
  stays in Module 6.

### Module 6: InfographicToolkit dashboard tools + dual-write persist + freeze
- **Path**: `packages/ai-parrot/src/parrot/tools/infographic_toolkit.py`, `infographic_recipes/freeze.py`
- **Responsibility**: the six new tools (§2 New Public Interfaces), conditional
  exposure when `recipe_store is None` (extend `_RECIPE_TOOL_NAMES` pattern);
  dashboard freeze path (single root = `Dashboard` component satisfies the
  existing one-component rule); persist step: `ArtifactStore.save_artifact` +
  `build_public_html_url` (canonical) **and** file copy to
  `STATIC_DIR/<agent_id>/dashboards/<artifact_id>.html`; embed a manifest
  summary (recipe name, widget provenance digest) in the artifact `definition`;
  PBAC via the existing `_infographic_pctx_var` pattern.
- **Depends on**: Modules 1, 2, 3, 5.

### Module 7: Template store + generation + seed template
- **Path**: `packages/ai-parrot/src/parrot/outputs/a2ui/recipes/templates.py` (store/loader) + `templates/infographics/payroll-contribution.json` (repo seed, installed to `BASE_DIR/templates/infographics/`)
- **Responsibility**: `DashboardTemplate` load/save/list from
  `BASE_DIR/templates/infographics/` (dir created lazily; config override);
  `dashboard_generate_template` flow: LLM proposes a `DashboardTemplate` JSON →
  catalog validation → persist; seed `payroll-contribution` template: 4 tabs
  (Rep Utilization, Regions, Proximity Staffing, Payroll Contribution) with the
  filter/widget structure extracted from `documents/test.html` — **without** the
  API-key fetch pattern.
- **Depends on**: Modules 1, 3.

### Module 8: DataAgent example + refresh method + docs
- **Path**: `agents/data.py` (repo root), docs in `docs/`
- **Responsibility**: `DataAgent(PandasAgent)` following the `agents/porygon.py`
  pattern (class-attr `llm = "anthropic:claude-opus-5"`; toolkits registered in
  `configure()` via `self.tool_manager.register_toolkit(...)` before
  `await super().configure(...)`); wires all ten tools with correct constructor
  kwargs (§6); `refresh_dashboard()` delegating to `RecipeRunner.run_dashboard`
  (accepts `replace_file`); system-prompt addendum making the LLM aware of the
  python_code pre/post-processing capability and the template workflow; usage doc.
- **Depends on**: Modules 1–7.

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_dashboard_recipe_yaml_roundtrip` | 1 | DashboardRecipe → YAML → model, stable |
| `test_transformstep_backcompat_no_kind` | 1 | Existing recipe YAML without `kind` still parses |
| `test_python_code_step_requires_contract` | 1 | Missing inputs/output_key/requires_columns → validation error |
| `test_code_step_executes_in_sandbox` | 2 | Declared inputs in, output frame out |
| `test_code_step_timeout_enforced` | 2 | Sleeping code step fails at timeout with stage error |
| `test_code_step_forbidden_import_rejected` | 2 | Sandbox policy inherited from PythonPandasTool |
| `test_dry_run_gates_code_step_columns` | 2 | Missing required column → RecipeRunError(stage="gate") |
| `test_run_dashboard_partial_isolation` | 2 | One widget fails → others render, dashboard marked partial |
| `test_dashboard_component_registration` | 3 | Dashboard/FilterBar in catalog; schemas validate |
| `test_dashboard_lower_degrades_to_text` | 3 | `lower()` produces readable fallback |
| `test_build_dashboard_builder` | 3 | Deterministic builder emits valid envelope |
| `test_filterbar_five_control_types` | 3 | multi_select/range_slider/date_range/single_select/toggle validate |
| `test_file_snapshot_roundtrip` | 4 | DataFrame → parquet snapshot → fetch identical |
| `test_replace_file_reingests` | 4 | New Excel replaces snapshot, same source name |
| `test_renderer_self_contained` | 5 | No `http(s)://` refs, no `apikey` substrings in output HTML |
| `test_renderer_budget_enforced` | 5 | >8 MB dataModel → truncation + `truncated=true` + note |
| `test_renderer_map_inline_geo` | 5 | Map widget lowers to inline d3-geo block (no CDN) |
| `test_dashboard_tools_absent_without_store` | 6 | Tool exposure mirrors `_RECIPE_TOOL_NAMES` gating |
| `test_dual_write_persist` | 6 | Artifact saved + STATIC_DIR copy exists; URL returned |
| `test_freeze_dashboard_single_root` | 6 | Dashboard envelope freezes; contract-less code step rejected |
| `test_template_generate_validates_and_persists` | 7 | Invalid template rejected pre-persist; valid one lands in dir |
| `test_seed_template_loads` | 7 | payroll-contribution.json parses and validates |
| `test_data_agent_tool_wiring` | 8 | All ten tools registered with verified constructor kwargs |
| `test_refresh_dashboard_no_llm` | 8 | refresh path never touches the LLM client (mock asserts zero calls) |

### Integration Tests
| Test | Description |
|---|---|
| `test_end_to_end_generate_then_refresh` | Mock slug sources + sample xlsx → dashboard artifact + recipe; mutate source data → `refresh_dashboard` → new artifact reflects new data, same layout, no LLM |
| `test_existing_infographic_tools_regression` | Pre-existing infographic/recipe tool suites still pass (toolkit tool list without store unchanged) |
| `test_a2ui_envelope_frontend_contract` | Generated envelope validates via `validate_envelope` with nested widgets + dataModel bindings resolvable |

### Test Data / Fixtures
```python
@pytest.fixture
def sample_slug_frames():
    """Small DataFrames mimicking fm_rep_utilization / fm_regions_avg_employees_html
    / flex_msl_brian_bi shapes (month, region, hours, payroll columns)."""

@pytest.fixture
def sample_workbook(tmp_path):
    """openpyxl-written .xlsx with two sheets/tables for ExcelIntelligence +
    snapshot tests."""

@pytest.fixture
def dashboard_recipe_yaml():
    """Frozen DashboardRecipe with: 1 slug source, 1 file snapshot, 1 TransformStep,
    1 PythonCodeStep, 2 tabs, 3 filters, 4 widgets (incl. 1 Map)."""
```

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] All unit tests pass (`pytest packages/ai-parrot/tests/ packages/ai-parrot-visualizations/tests/ -v` for the new suites)
- [ ] Integration tests pass, including `test_existing_infographic_tools_regression` (no breaking changes to FEAT-324/326 surfaces)
- [ ] `dashboard_render` returns an `InfographicRenderResult` with a validated A2UI envelope (Dashboard root) AND an artifact URL (G2)
- [ ] Persist dual-writes: ArtifactStore canonical + `STATIC_DIR/<agent_id>/dashboards/` copy; signed public URL returned (G3)
- [ ] `DataAgent.refresh_dashboard` replays a saved `DashboardRecipe` with zero LLM calls and reflects fresh source data (G4)
- [ ] `PythonCodeStep` without declared inputs/output/requires_columns is rejected at freeze AND at model validation; per-step timeout (default 30s) enforced (G5)
- [ ] Excel data replays from parquet snapshot; `replace_file` param re-ingests a new workbook (G6)
- [ ] Rendered HTML is self-contained: zero external URLs, zero credentials (grep-guard test), tabs + all 5 filter controls functional client-side, inline d3-geo map with radius slider (G7)
- [ ] Data budget enforced: ≤8 MB baked JSON, per-widget 25k row cap default, `truncated=true` + visible note on excess (G7)
- [ ] Missing template → generated, catalog-validated, persisted to `BASE_DIR/templates/infographics/`; seed `payroll-contribution` template ships and loads (G8)
- [ ] `agents/data.py` exists, registers all ten tools with verified kwargs, `llm = "anthropic:claude-opus-5"`, planner on Haiku/Sonnet (G1, G9)
- [ ] Dashboard tools absent from `get_tools()` when no `recipe_store` configured (FEAT-324 gating pattern preserved)
- [ ] `ruff check` clean on all touched files; documentation added under `docs/`

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> Carried forward from the brainstorm's Code Context and re-verified 2026-08-17
> (spot-checked line numbers post-brainstorm; all matched).

### Verified Imports
```python
from parrot.bots.data import PandasAgent                       # packages/ai-parrot/src/parrot/bots/data.py
from parrot.tools.execution_plan import ExecutionPlanToolkit   # execution_plan/__init__.py:24 (NOT top-level parrot.tools)
from parrot.tools.working_memory import WorkingMemoryToolkit   # working_memory/__init__.py:2 (pattern: agents/porygon.py:9)
from parrot.tools.excel_intelligence import ExcelIntelligenceToolkit  # NOT top-level; zero non-test call sites today
from parrot.tools.interactive_toolkit import InteractiveToolkit  # also lazy top-level (tools/__init__.py:267)
from parrot.tools.pythonpandas import PythonPandasTool         # also lazy top-level (tools/__init__.py:260)
from parrot_tools.qsource import QSourceTool
from parrot_tools.sensitivity_analysis import SensitivityAnalysisTool
from parrot_tools.think import ThinkTool
from parrot_tools.whatif_toolkit import WhatIfToolkit          # PREFER over legacy WhatIfTool
from parrot.tools.infographic_toolkit import InfographicToolkit, InfographicRenderResult
from parrot.outputs.a2ui.recipes.models import (
    InfographicRecipe, TransformStep, LayoutSpec, RecipeParam,
    DataSourceSpec, RenderSpec, RecipeRunError,
)
from parrot.outputs.a2ui.recipes.store import AbstractRecipeStore, FileRecipeStore, DBRecipeStore
from parrot.outputs.a2ui.recipes.transformers import transformer_registry, infographic_transformer
from parrot.tools.infographic_recipes.runner import RecipeRunner, RecipeRunException
from parrot.tools.infographic_recipes.freeze import freeze_session_envelope, FreezeProvenanceError, FreezeValidationError
from parrot.outputs.a2ui.models import CreateSurface, Component
from parrot.outputs.a2ui.catalog import register_component, validate_envelope
from parrot.outputs.a2ui.renderers import register_a2ui_renderer, get_a2ui_renderer, AbstractA2UIRenderer, RendererCapabilities
from parrot.outputs.a2ui.artifacts import RenderedArtifact
from parrot.storage.artifacts import ArtifactStore
from parrot.storage.artifact_signing import build_public_html_url
from parrot.storage.models import Artifact, ArtifactType, ArtifactCreator
from parrot.tools.dataset_manager import DatasetManager
from parrot.tools.dataset_manager.sources import DataSource, InMemorySource, QuerySlugSource, MultiQuerySlugSource
from parrot.conf import BASE_DIR, STATIC_DIR                   # conf.py:5, :43
from parrot.registry import register_agent                     # pattern: agents/porygon.py:12
from parrot.models.outputs import OutputMode                   # A2UI="a2ui" at models/outputs.py:64
```

### Existing Class Signatures
```python
# packages/ai-parrot/src/parrot/outputs/a2ui/recipes/models.py
class RecipeParam(BaseModel):          # :41  — name/default/description
class DataSourceSpec(BaseModel):       # :59  — dataset/alias/sql/conditions/force_refresh=True
class TransformStep(BaseModel):        # :80  — transformer/inputs[]/params{}/output_key (ONLY step type today)
class LayoutSpec(BaseModel):           # :99  — single root {component, properties}
class RenderSpec(BaseModel):           # :114 — profile="interactive-html"/theme/delivery
class InfographicRecipe(BaseModel):    # :175 — schema_version=1, name, params[], data_sources[], transforms[], layout, render, schedule
    def to_yaml(self) -> str           # :226
    @classmethod def from_yaml(...)    # :237
class RecipeRunError(BaseModel):       # :268 — stage: params|data|gate|transform|layout|render (:283)

# packages/ai-parrot/src/parrot/outputs/a2ui/recipes/store.py
class AbstractRecipeStore(ABC):        # :125 — async save/get/list/delete(name, owner=None)
class FileRecipeStore(AbstractRecipeStore):  # :165 — <dir>/<name>.yaml, owner-scoped subdir, atomic write (:188)
class DBRecipeStore(AbstractRecipeStore):    # :231 — Redis w/ in-memory fallback; keys a2ui_recipe:{ns}:{owner}:{name}

# packages/ai-parrot/src/parrot/tools/infographic_recipes/runner.py
class RecipeRunner:
    def __init__(self, store, dataset_manager, *, artifact_store=None,
                 owner=None, narrator=None)                    # :208
    async def run(self, name, *, params=None, pctx=None,
                  recipe_owner=None) -> RenderedArtifact       # :224 (stages :263-272)
    async def dry_run(self, recipe) -> list[RecipeRunError]    # :273
    def _render_or_raise(...)                                  # :635 — get_a2ui_renderer(recipe.render.profile)

# packages/ai-parrot/src/parrot/tools/infographic_recipes/freeze.py
async def freeze_session_envelope(envelope: CreateSurface, *, dataset_names,
    transform_steps, name, title, runner, description=None, owner=None,
    params=None, render_profile="interactive-html", theme=None) -> InfographicRecipe  # :64
# raises FreezeProvenanceError (:39) when len(envelope.components) != 1
#   → Dashboard-as-single-root satisfies this; the dashboard freeze path extends here
# raises FreezeValidationError (:48) when dry_run is dirty

# packages/ai-parrot/src/parrot/outputs/a2ui/recipes/transformers.py
transformer_registry: TransformerRegistry   # :161 (module singleton)
@infographic_transformer(name, *, requires_columns=None, description="", params_schema=None)  # :164
def validate_inputs(step, frames, *, recipe_name="")           # :198 — fail-fast column check
# 8 built-ins (recipes/library.py): day_totals, division_breakdown, variance_analysis,
#   top_movers, narrative_facts, groupby_aggregate, pivot, latest_vs_baseline

# packages/ai-parrot/src/parrot/outputs/a2ui/
class Component(BaseModel)             # models.py:123 — id/component/properties($bind)/children[str ids]; extra="allow"
class CreateSurface(A2UIMessageBase)   # models.py:167 — surfaceId, catalogId, components[], dataModel
def register_component(name, *, requires_actions=False, catalog_id=DEFAULT_CATALOG_ID)  # catalog/__init__.py:57
def validate_envelope(envelope, origin=...)  # catalog/__init__.py:165
def build_surface(component, properties, *, surface_id, component_id="blk-000", data_model=None)  # builders.py:44
# Registered components (exactly 9): Card, Chart, DataTable, Form, Infographic,
#   KPICard, Map, Report, Timeline (catalog/components/__init__.py)
# CHART_SCHEMA (components/chart.py:22): type enum [bar,line,area,scatter,pie,map], x, y[], data ($bind)
# MAP_SCHEMA (components/map.py:20): title, baseLayer, viewport{center,zoom}, layers[{name,type}], data ($bind)
def register_a2ui_renderer(name, capabilities)  # renderers/__init__.py:97
def get_a2ui_renderer(name)                     # renderers/__init__.py:130 — registry → importlib parrot.outputs.a2ui_renderers.<name>
def bake_envelope(envelope) -> list[dict]       # baking.py:122
def persist_envelope(envelope, store, *, user_id, agent_id, session_id, artifact_id=None, title=...)  # baking.py:156

# packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/interactive_html.py
class InteractiveHTMLRenderer(AbstractA2UIRenderer):  # :217, registered "interactive-html" (:211)
    async def render(self, envelope: CreateSurface, *, bake: bool = True) -> RenderedArtifact  # :220
_CHART_JS_PATH = .../formats/assets/chart.umd.min.js  # :77 (vendored Chart.js UMD 4.5.1, read at import :83)
# Behavior JS hooks: [data-chart-config], [data-tabs-for] (:344-366, unschema'd Chart prop),
#   [data-metric-toggle-for], [data-sort-table]
# Renderer profiles registered today: ssr_html, interactive-html, echarts, pdf, folium_map, adaptive_cards

# packages/ai-parrot/src/parrot/storage/
class ArtifactStore:                   # artifacts.py:27 — __init__(dynamodb, s3_overflow) :37
    async def save_artifact(self, user_id, agent_id, session_id, artifact: Artifact) -> None  # :46 (>200KB → overflow)
    async def get_public_url(...) -> str  # :177 (S3 presigned; inline artifacts raise)
def build_public_html_url(artifact_id, *, user_id=None, agent_id=None,
    session_id=None, expiry_seconds=None, key=None) -> str  # artifact_signing.py:99
#   → "/api/v1/artifacts/public/{expiry}.{sig}/{artifact_id}.html?..." (ArtifactPublicHTMLView)
class ArtifactType                     # models.py:244 — CHART, MAP, TABLE, CANVAS, INFOGRAPHIC, INTERACTIVE, DATAFRAME, EXPORT
class Artifact                         # models.py:275 — artifact_id, artifact_type, title, definition, definition_ref, ...

# packages/ai-parrot/src/parrot/tools/infographic_toolkit.py
class InfographicToolkit(AbstractToolkit):
    def __init__(self, *, artifact_store, template_dirs=None, templates=None,
                 emit_a2ui=False, recipe_store=None, recipe_runner=None,
                 dataset_manager=None, **kwargs)               # :213
    _RECIPE_TOOL_NAMES: tuple                                  # module-level — exclude_tools gating pattern to extend
    _infographic_pctx_var: ContextVar                          # module-level — PBAC context for recipe replay (spec G8 of FEAT-324)
    async def render_data_template(self, template_name, payload, descriptor=None,
                                   marker_id="report-data", title=None)  # :640 (FEAT-326)
    async def infographic_save_recipe(...)                     # :1241
    async def infographic_run_recipe(name, params=None)        # :1356

# packages/ai-parrot/src/parrot/bots/data.py
class PandasAgent(IntentRouterMixin, BasicAgent):
    async def refresh_data(self, cache_expiration=None, **kwargs) -> Dict[str, pd.DataFrame]  # :2294
    @classmethod async def load_from_files(cls, files, **kwargs) -> Dict[str, pd.DataFrame]  # :2969-2970 (stateless)
    def _extract_last_infographic_result(self, tool_calls)     # return_direct post-loop branch (FEAT-197)

# Tool fleet constructors (ALL verified; see brainstorm for full method lists)
class ExecutionPlanToolkit(AbstractToolkit):  # execution_plan/toolkit.py:61
    def __init__(self, *, tool_manager, working_memory: "WorkingMemoryToolkit",
                 planner_llm=None, plans_dir=None, allowed_tools=None, soft_timeout=60.0,
                 permission_context=None, on_node_event=None, max_completed_runs=50, **kwargs)  # :93
    # planner_llm accepts "provider:model" | client | model_config dict
    #   via resolve_planner_client (execution_plan/planner.py:60)
    # tools: plan_execute :432, plan_validate :462, plan_status :385, plan_artifacts :408
class WorkingMemoryToolkit:            # working_memory/tool.py:44, name="working_memory"
    def __init__(self, session_id=None, max_rows=10, max_cols=30,
                 tool_locals_registry=None, answer_memory=None, thread_offload_cells=None, **kwargs)  # :103
    # BasicAgent.configure() auto-wires tool_locals_registry + answer_memory
class ExcelIntelligenceToolkit:        # excel_intelligence.py:18, tool_prefix="excel"
    def __init__(self, **kwargs)       # :33 — tools: inspect_workbook :59, extract_table :96, query_cells :170
class InteractiveToolkit(AbstractToolkit):  # interactive_toolkit.py:74
    def __init__(self, *, artifact_store: ArtifactStore, catalog=None, emit_a2ui=False, **kwargs)  # :90
class PythonPandasTool(PythonREPLTool):     # pythonpandas.py:25, name="python_repl_pandas"
    # sandbox plotting: plotly + altair ONLY (matplotlib/seaborn blocked, FEAT-423)
class QSourceTool(AbstractTool):       # parrot_tools/qsource.py:62, name="QSourceTool"
    def __init__(self, default_driver="db", available_structured_outputs=None, **kwargs)  # :81
class SensitivityAnalysisTool(AbstractTool):  # parrot_tools/sensitivity_analysis.py:42
    # resolves data ONLY via self._parent_agent.dataframes — DataAgent must call set-parent wiring
class ThinkTool(AbstractTool):         # parrot_tools/think.py:76 — do NOT pair with native extended thinking
class WhatIfToolkit(AbstractToolkit):  # parrot_tools/whatif_toolkit.py:169
    def __init__(self, dataset_manager=None, pandas_tool=None, **kwargs)  # :176

# packages/ai-parrot/src/parrot/clients/claude.py
class AnthropicClient(AbstractClient): # :67 — model/max_tokens via **kwargs → AbstractClient (base.py:286-317)
# NO thinking= kwarg on the direct client; adaptive-thinking models normalize/strip thinking payloads (:269-306)
# Agents never construct clients directly — class-attr llm = "provider:model" (agents/porygon.py:16)

# packages/ai-parrot/src/parrot/tools/dataset_manager/
class QuerySlugSource(DataSource):     # sources/query_slug.py:36 — __init__(slug, prefetch_schema_enabled=True, permanent_filter=None) :51
class MultiQuerySlugSource(DataSource):  # sources/query_slug.py:165 — __init__(slugs: List[str]) :175
# DatasetManager.add_dataframe_from_file(name, path, ...)  # tool.py:1171 (csv/xls/xlsx/xlsm/xlsb/ods → InMemorySource)
# DatasetManager.load_file(name, path, ...)                # tool.py:1222 (LLM-context structural load)
# DatasetManager.add_dataset(...)                          # tool.py:966 — one-of query_slug|query|table|dataframe; NO file kwarg today

# Config (packages/ai-parrot/src/parrot/conf.py)
BASE_DIR                                # :5 (from navconfig); PROJECT_ROOT = BASE_DIR :34
STATIC_DIR                              # :43-45 (fallback BASE_DIR/'static'); per-agent STATIC_DIR/<agent_id>/... pattern (bots/agent.py:349+)
INFOGRAPHIC_RENDER_TEMPLATE_DIRS: list[str]  # :864-865, fallback []
```

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `PythonCodeStep` executor | `PythonPandasTool` sandbox | REPL namespace exec w/ timeout | `tools/pythonpandas.py:25` |
| `RecipeRunner.run_dashboard` | `RecipeRunner.run` stage machinery | shared private stages | `infographic_recipes/runner.py:224,263-272` |
| Dashboard freeze | `freeze_session_envelope` | Dashboard = single root component | `infographic_recipes/freeze.py:64` (rule at :39) |
| `Dashboard`/`FilterBar` | catalog registry | `register_component` + `lower()` | `a2ui/catalog/__init__.py:57` |
| `dashboard-html` renderer | renderer registry | `register_a2ui_renderer("dashboard-html", ...)` | `a2ui/renderers/__init__.py:97,130` |
| Renderer Chart widgets | vendored Chart.js | existing asset | `a2ui_renderers/interactive_html.py:77-83` |
| Dual-write persist | `ArtifactStore.save_artifact` + `build_public_html_url` + STATIC_DIR copy | toolkit persist step | `storage/artifacts.py:46`, `artifact_signing.py:99` |
| `FileSnapshotSource` | `DataSource` ABC + `DataSourceSpec.dataset` | new source type | `dataset_manager/sources/__init__.py:60-73`, `recipes/models.py:59` |
| Dashboard tools gating | `exclude_tools` conditional exposure | `_RECIPE_TOOL_NAMES` pattern | `infographic_toolkit.py` (module head) |
| `DataAgent` result routing | `PandasAgent._extract_last_infographic_result` | `return_direct=True` envelope | `bots/data.py` (FEAT-197 branch) |
| Recipe replay PBAC | `_infographic_pctx_var` ContextVar | `_pre_execute` capture | `infographic_toolkit.py` (module head) |

### Does NOT Exist (Anti-Hallucination)
- ~~A2UI `Tabs`/`TabView`/`Filter`/`Dashboard`/`Grid`/`Layout` catalog component~~ — catalog has exactly 9 components; "tabs" exist only as an unschema'd `Chart` property read by `InteractiveHTMLRenderer` (:344-366) and as legacy `BlockType.TAB_VIEW` blocks that the A2UI adapter **flattens away** (`a2ui/adapters/infographic.py:415-443`). This spec ADDS Dashboard + FilterBar.
- ~~A recipe step type other than `TransformStep`~~ — no python-code/filter/conditional step exists. This spec ADDS `PythonCodeStep`. `TransformStep` has NO `kind` field today (Module 1 adds a defaulted discriminator).
- ~~`ExcelSource`/`FileSource`/`TmpFileSource`/`ParquetSource` DataSource~~ — file ingestion exists only ABOVE the source layer (`add_dataframe_from_file` → `InMemorySource`); `add_dataset()` has NO `file=` kwarg. This spec ADDS `FileSnapshotSource`.
- ~~Per-plan / per-node LLM override in ExecutionPlan~~ — `PlanNode` is tool-only (`extra="forbid"`, no `agent_ref`/`model` field). Only knob: toolkit-level `planner_llm`.
- ~~`AnthropicClient(thinking=...)` / `ask(thinking_budget=...)` on the direct client~~ — only `clients/bedrock.py:594` has `thinking_budget`.
- ~~`from parrot.tools import ExecutionPlanToolkit / ExcelIntelligenceToolkit / WorkingMemoryToolkit`~~ — not in top-level lazy exports nor `parrot_tools.TOOL_REGISTRY`; use subpackage paths.
- ~~`WhatIfTool(name=...)`~~ — legacy `WhatIfTool.__init__(self)` accepts no kwargs (parrot_tools/whatif.py:982); use `WhatIfToolkit`.
- ~~`templates/infographics/` directory~~ — does not exist yet anywhere; Module 7 creates the convention.
- ~~`agents/data.py`~~ — does not exist yet (confirmed); Module 8 creates it.
- ~~`MemoryRecipeStore` / SQL recipe store~~ — only `FileRecipeStore` and Redis `DBRecipeStore` (in-memory fallback inside the latter).
- ~~matplotlib/seaborn inside `PythonPandasTool`~~ — sandbox allows plotly + altair only (FEAT-423). `PythonCodeStep` inherits this policy.
- ~~Artifacts persisted to `STATIC_DIR` by the existing A2UI/infographic path~~ — they persist via `ArtifactStore` (DB + S3 overflow). The STATIC_DIR copy is NEW behavior added by Module 6 (dual-write, resolved decision).
- ~~Multi-component freeze~~ — `freeze_session_envelope` raises when `len(envelope.components) != 1` (freeze.py:39). Dashboard envelopes MUST use `Dashboard` as the single root.
- ~~`RecipeRunner.run_dashboard` / `dry_run_dashboard`~~ — do not exist yet; Module 2 adds them.
- ~~`build_dashboard` / `build_filterbar` builders~~ — `builders.py` `__all__` (:29) has exactly 6 builders today; Module 3 adds these two.

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- Conditional tool exposure: extend the `_RECIPE_TOOL_NAMES` → `exclude_tools`
  pattern for the new dashboard tools (absent when `recipe_store is None`).
- PBAC on replay: capture `PermissionContext` via the existing
  `_infographic_pctx_var` `_pre_execute` pattern — never fail open.
- `return_direct=True` terminal tools: `dashboard_render`/`dashboard_run_recipe`
  return `InfographicRenderResult` verbatim (PandasAgent post-loop branch).
- Example-agent wiring: follow `agents/porygon.py` — class-attr `llm`, toolkits
  registered in `configure()` before `await super().configure(...)`.
- Renderer assets vendored inline (Chart.js precedent); the d3-geo bundle ships
  as a new asset file next to `chart.umd.min.js`, read once at import.
- Async-first, Pydantic models everywhere, Google docstrings (tool docstrings
  ARE the LLM interface), `self.logger`, no `requests`/`httpx`.
- Back-compat: all new toolkit kwargs optional (FEAT-324 precedent); existing
  recipe YAML without `kind` must keep parsing.

### Known Risks / Gotchas
- **`PythonCodeStep` weakens the G2 replay boundary of FEAT-324** (registry-only
  transformers). Mitigations (resolved): declared contract (dry-run gateable),
  sandbox inheritance, per-step timeout, freeze rejection of contract-less steps,
  recipe ownership scoping. Registry transformers remain the documented
  preference in tool docstrings.
- **Dual-write drift**: the STATIC_DIR copy can diverge from the canonical
  artifact (e.g. artifact updated, copy stale). Rule: the copy is written in the
  same persist step, treated as a convenience export, and overwritten on every
  re-render/refresh of the same dashboard; ArtifactStore is always authoritative.
- **8 MB budget vs. filter fidelity**: filters recompute client-side over baked
  rows — aggressive truncation silently changes filter results. Renderer must
  surface truncation visibly on affected widgets (`truncated=true` + note), and
  transforms should pre-aggregate to the widget's display grain.
- **d3-geo port**: the inline geoAlbersUsa bundle in `documents/test.html`
  (~200 KB minified) must be extracted into a versioned asset; radius-slider
  logic depends on point data with lat/lon — the Map widget contract must
  require coordinate columns (MAP_SCHEMA layers + data binding).
- **Snapshot lifecycle**: parquet snapshots under `BASE_DIR/dashboards/snapshots/`
  have no GC in v1 — document the manual cleanup expectation; recipes store the
  snapshot checksum to detect missing/corrupt files and error with an
  actionable "provide replace_file" message.
- **Per-widget error isolation**: one failing widget must not sink the dashboard
  — render remaining widgets, mark the dashboard partial in the result envelope
  and the manifest summary.
- **`ThinkTool` vs adaptive thinking**: ThinkTool's own docs warn against pairing
  with native extended thinking; DataAgent registers it but the system prompt
  should scope it to plan-sketching, not chain-of-thought duplication.
- **Legacy `_orphans` in test.html**: the reference embeds a live API key — the
  seed template must be authored from its *structure*, never by copying markup.

### External Dependencies
| Package | Version | Reason |
|---|---|---|
| `pandas` | existing | frames + parquet I/O |
| `pyarrow` | existing (verify extra) | parquet snapshot engine |
| `openpyxl` | existing | Excel extraction (excel_analyzer) |
| `PyYAML` | existing | recipe serialization |
| Chart.js | 4.5.1 vendored | already at `outputs/formats/assets/chart.umd.min.js` |
| d3-geo (geoAlbersUsa subset) | vendored, new asset | inline US map (extracted from reference, pinned + licensed) |

No new PyPI dependencies expected; d3-geo is a vendored JS asset, not a Python package.

---

## 8. Open Questions

> All brainstorm questions were resolved pre-spec; echoed here for the audit trail.

- [x] HTML URL semantics — *Resolved in brainstorm*: **Dual-write.** ArtifactStore
  is canonical (signed public URL returned) AND the persist step writes a physical
  copy under `STATIC_DIR/<agent_id>/dashboards/`.
- [x] Dashboard recipe/manifest storage — *Resolved in brainstorm*:
  **FileRecipeStore + embedded summary.** Default store is a `FileRecipeStore`
  directory (e.g. `BASE_DIR/dashboards/recipes/`); a manifest summary is embedded
  in the artifact `definition` for self-description.
- [x] `python_code` step guardrails — *Resolved in brainstorm*: **Contract +
  timeout.** Declared inputs/outputs + `requires_columns` (dry-run gateable),
  per-step timeout default 30s, freeze rejects contract-less steps. No import
  allowlist beyond the existing REPL sandbox in v1.
- [x] Filter semantics v1 — *Resolved in brainstorm*: **Extended set.**
  Multi-select with search, numeric range slider, date-range, single-select
  dropdown, boolean toggle — all client-side over baked data.
- [x] Embedded-data budget — *Resolved in brainstorm*: **≤8 MB total baked JSON**
  per dashboard; per-widget row cap default 25k (configurable); truncation with
  `truncated=true` and a visible note.
- [x] Opus 5 extended thinking — *Resolved in brainstorm*: **Adaptive-only for
  v1.** No client changes; explicit budgets remain a separate mini-feature.
- [x] Seed template / map scope — *Resolved in brainstorm*: **Map IN scope for
  v1.** `dashboard-html` ports the inline d3-geo geoAlbersUsa map + radius slider
  as the `Map` component lowering; seed template keeps all 4 tabs.
- [ ] Snapshot GC policy (age/size-based cleanup of `BASE_DIR/dashboards/snapshots/`)
  — decide during implementation or defer to the refresh-handler follow-up —
  *Owner: jesuslara*
- [ ] Exact d3-geo licensing/attribution note for the vendored asset (ISC —
  confirm and record in the asset header) — *Owner: implementer*

---

## Worktree Strategy

- **Default isolation unit**: `per-spec` — all tasks sequential in ONE worktree
  (`.claude/worktrees/feat-428-agent-infographic-generation`, branched from `dev`).
- **Rationale**: the dependency spine (models → code-step/runner → catalog →
  renderer → toolkit → templates → agent) is inherently sequential, and the hub
  files (`infographic_toolkit.py`, `recipes/models.py`, `runner.py`) are hot,
  heavily-tested shared modules — parallel worktrees would be merge-conflict
  magnets for little wall-clock gain.
- **Parallelizable in principle (not recommended as separate worktrees)**:
  Module 3 (catalog) and Module 4 (FileSnapshotSource) have no dependency on
  Modules 1–2 and could be built first/concurrently *within* the single worktree.
- **Cross-feature dependencies**: none known in-flight on `infographic_toolkit.py`
  / `recipes/` / `a2ui_renderers/`. FEAT-324 and FEAT-326 are merged
  prerequisites already on `dev`.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-08-17 | Jesus (with Claude) | Initial draft from accepted brainstorm Option A (all 7 open questions resolved) |
