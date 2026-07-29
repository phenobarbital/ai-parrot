---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Feature Specification: Infographic Builder — Recipe-Driven, Replayable A2UI Infographics

**Feature ID**: FEAT-324
**Date**: 2026-07-22
**Author**: Jesus Lara (decisions) + Claude (research/synthesis)
**Status**: approved
**Target version**: 0.27.0
**Brainstorm**: `sdd/proposals/infographic-builder.brainstorm.md` (authoritative input; all 7 open questions resolved there and carried forward)

---

## 1. Motivation & Business Requirements

### Problem Statement

Reference artifacts (`sdd/artifacts/daily_report.py`, `sdd/artifacts/executive_summary.py`,
`sdd/artifacts/budget_variance_dashboard_Template.html`) demonstrate a real-world pattern
ai-parrot cannot express today: a **daily financial infographic** where (1) raw datasets pass
through **domain transformation routines** (`day_totals`, `division_breakdown`, variance
analysis, worst/best drivers), (2) the computed results feed a **fixed visual layout** (KPI
row, day ribbon, actual-vs-budget chart, grouped ledger table), and (3) the whole thing
regenerates **every day with fresh data** — same construction instructions, new numbers.

Today that lives in a standalone Windows script (hardcoded paths, string-splicing into an HTML
template, Outlook COM). Inside ai-parrot, FEAT-273 (done) provides the safe declarative output
pipeline (A2UI envelopes → catalog validation → deterministic renderers) and `DatasetManager`
provides refreshable datasets. **The missing middle layer** is a persisted, re-executable
"recipe" binding *datasets → registered transforms → an A2UI envelope layout*, so a user can
say "repeat the budget-variance infographic with today's data" and get a deterministic,
LLM-free regeneration.

### Goals

- **G1 — Recipes are pure data**: every internal object of the infographic is a FEAT-273
  catalog component (JSON schema + data via `$bind` pointers into `dataModel`) inside a
  `CreateSurface` envelope. Transformations are **registered Python transformers referenced by
  name + params** — never stored/executed code. FEAT-273's no-`exec()` invariant holds
  end-to-end.
- **G2 — Dual authorship, one model**: the LLM composes an infographic interactively and
  "freezes" it into a recipe; a developer/power-user writes the same recipe by hand
  (YAML/JSON). Both replay identically.
- **G3 — Deterministic replay with fresh data**: replay re-fetches datasets through
  `DatasetManager` (templated `{param}` substitution + built-in relative-date resolvers:
  `current_month`, `previous_month`, `today`, `yesterday`, `first_of_month`), runs the
  transform chain, assembles + catalog-validates the envelope, renders, persists, and
  optionally delivers. No LLM in the loop.
- **G4 — Fail-fast on schema drift**: transformers declare required input columns; the runner
  validates before executing and aborts with a structured diagnostic (recipe id, transform
  name, dataset, missing columns / empty dataset). No silently-wrong infographics.
- **G5 — Dual stores**: `AbstractRecipeStore` with `FileRecipeStore` (YAML/JSON directory) and
  `DBRecipeStore` (SkillRegistry pattern) — both in **core ai-parrot**. Versioning is simple
  overwrite + `updated_at` + `schema_version` (history is a follow-up).
- **G6 — Three triggers, one runner**: agent chat tools (on `InfographicToolkit`), REST
  handler (ai-parrot-server), and scheduled jobs via the **existing** APScheduler-based
  `AgentSchedulerManager` — all funnel into one `RecipeRunner`.
- **G7 — Client-side baked interactivity**: new `interactive-html` render profile in
  ai-parrot-visualizations emits a single self-contained HTML document (vendored **Chart.js
  v4** + vanilla JS: day tabs, metric toggle, column sort) driven only by the embedded
  dataModel JSON — mirroring the reference template's `<script id="report-data">` pattern.
  Existing static profiles (SSR-HTML → PDF/email) remain available per delivery channel.
- **G8 — Permission safety**: chat/REST replays run under the **invoker's** permission context
  (`pctx`); scheduled jobs run under an explicit principal stored in the schedule config.
  Permissions are never elevated. DatasetManager's PBAC/data-plane guards apply unchanged.

### Non-Goals (explicitly out of scope)

- **LLM-assisted repair on schema drift** (re-mapping columns, proposing a corrected recipe) —
  declared fast-follow; v1's structured diagnostic is designed to feed it later.
- **Recipe version history / diffs** — v1 is overwrite + `updated_at`; SkillRegistry-style
  history is a follow-up.
- **A transform DSL or stored transform code** — rejected in brainstorm (Options C/D); see
  `sdd/proposals/infographic-builder.brainstorm.md`.
- **A new scheduler** — ai-parrot-server already ships `AgentSchedulerManager`; this feature
  only registers a callback and documents job creation.
- **Server-push interactivity / actions** — `requires_actions` components and live updates
  stay with FEAT-B (post-FEAT-273). v1 interactivity is client-local JS only.
- **Extending the legacy FEAT-197 template system** — rejected in brainstorm (Option B); the
  legacy `OutputMode` path already carries deprecation warnings (TASK-1740).

---

## 2. Architectural Design

### Overview

A **recipe subsystem** in three cleanly separated parts:

1. **Recipe model (core, pure data)** — `InfographicRecipe` (Pydantic): metadata (name,
   title, description, owner scope, `schema_version`, `updated_at`), `params` (declared
   parameters with defaults; values resolve at run time via plain `{param}` substitution plus
   the five built-in relative-date resolvers), `data_sources[]` (DatasetManager dataset name +
   optional SQL/conditions template), `transforms[]` (registered transformer name + params +
   `output_key` into the dataModel), `layout` (catalog component tree whose `data` properties
   are `{"$bind": "/pointer"}` bindings), and `render` (profile name, theme, delivery config).
   Serializes to JSON/YAML for hand authoring. Lives under `parrot/outputs/a2ui/recipes/` and
   respects the package's one-way import rule (never imports DatasetManager/agents/LLM
   clients).
2. **Transformer registry** — `@infographic_transformer("name", requires_columns=...)`
   registers pure functions `(inputs, params) -> dict`. Ships a built-in library ported from
   `sdd/artifacts/executive_summary.py`: `day_totals`, `division_breakdown`,
   `variance_analysis`, `top_movers`, plus generic `groupby_aggregate`, `pivot`,
   `latest_vs_baseline`. The registry exposes each transformer's manifest (params schema +
   required columns) for the fail-fast gate and for LLM discovery.
3. **Runner + stores + triggers** — `RecipeRunner` (in `parrot/tools/infographic_recipes/`,
   *outside* the a2ui core package so it may import DatasetManager) resolves datasets
   (`fetch_dataset(force_refresh=True)` with substituted params / `get_dataset_entry(name).df`),
   runs the validation gate, executes transforms into the `dataModel`, assembles the envelope
   via `build_infographic`/`build_surface` (catalog-validated), renders via
   `get_a2ui_renderer(profile)`, persists the `RenderedArtifact`, and optionally delivers via
   `deliver_artifact`. Stores: `AbstractRecipeStore` + `FileRecipeStore` + `DBRecipeStore`
   (core). Triggers: new `InfographicToolkit` tools (`infographic_save_recipe`,
   `infographic_list_recipes`, `infographic_run_recipe`, `infographic_get_recipe_contract`),
   a `RecipeHandler` REST view (ai-parrot-server), and a scheduler callback registered on the
   existing `AgentSchedulerManager`.

The **freeze path** (G2, LLM side): when saving from a live agent session, the toolkit
captures the envelope the LLM produced plus the dataset names and transform invocations in
play, normalizes them into an `InfographicRecipe`, dry-run validates it, then persists.

### Component Diagram

```
                 (authoring)                                (replay)
LLM producer ──→ freeze path ──┐                 chat tool / REST / scheduler job
hand-written YAML/JSON ────────┤                              │
                               ▼                              ▼
                        AbstractRecipeStore  ◄────────  RecipeRunner
                        (File | DB, core)                     │
                                                              ├─ 1. resolve params ({param} + date resolvers)
                                                              ├─ 2. DatasetManager.fetch_dataset(force_refresh)
                                                              ├─ 3. validation gate (requires_columns, non-empty)
                                                              ├─ 4. TransformerRegistry.run(chain) → dataModel
                                                              ├─ 5. build_infographic/build_surface → validate_envelope
                                                              ├─ 6. get_a2ui_renderer(profile).render(envelope)
                                                              │       ├─ "interactive-html" (NEW, Chart.js baked)
                                                              │       └─ "ssr-html" / "pdf" (existing, static)
                                                              └─ 7. RenderedArtifact → ArtifactStore / deliver_artifact
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `parrot/outputs/a2ui/` (core) | extends | new `recipes/` subpackage: models, params, transformer registry, stores — keeps G8 one-way import rule (no DatasetManager imports inside `parrot.outputs.a2ui`) |
| `parrot/outputs/a2ui/builders.py` | uses | `build_surface` / `build_infographic` assemble + catalog-validate envelopes |
| `parrot/outputs/a2ui/catalog/` | uses | component allowlist; `validate_envelope` on every assembled recipe layout |
| `parrot/outputs/a2ui/renderers/__init__.py` | uses | `get_a2ui_renderer(name)` resolution; new renderer self-registers from the satellite |
| `parrot/outputs/a2ui/artifacts.py` + `delivery.py` | uses | `RenderedArtifact` output; `deliver_artifact` for scheduled/notified runs |
| `parrot/tools/dataset_manager/tool.py` | depends on | `fetch_dataset`, `get_dataset_entry(name).df`, `get_metadata`; PBAC/data-plane guards unchanged |
| `parrot/tools/infographic_toolkit.py` | extends | four new recipe tools + freeze path; existing template tools untouched |
| `packages/ai-parrot-visualizations` | extends | new `interactive_html.py` renderer (vendored Chart.js v4 + vanilla JS behaviors; ECharts already vendored) |
| `packages/ai-parrot-server` handlers | extends | new `RecipeHandler` (BaseView pattern from `DatasetManagerHandler`) + routes |
| `packages/ai-parrot-server` scheduler | extends | recipe-replay job callback on existing `AgentSchedulerManager`; jobs managed via existing `SchedulerJobsHandler` REST CRUD |
| `parrot/skills/store.py` | reference only | `SkillRegistry` is the blueprint for `DBRecipeStore` (no changes to skills) |

No breaking changes; everything is additive.

### Data Models

```python
# parrot/outputs/a2ui/recipes/models.py (NEW — shapes, not implementation)

class RecipeParam(BaseModel):
    name: str                      # e.g. "month"
    default: Optional[str] = None  # literal or resolver name (e.g. "current_month")
    description: Optional[str] = None

class DataSourceSpec(BaseModel):
    dataset: str                            # DatasetManager dataset name
    alias: str                              # key transforms use to reference this frame
    sql: Optional[str] = None               # optional SQL template with {param} placeholders
    conditions: Optional[dict[str, Any]] = None  # optional conditions template
    force_refresh: bool = True

class TransformStep(BaseModel):
    transformer: str               # registered name, e.g. "division_breakdown"
    inputs: list[str]              # data-source aliases and/or prior output_keys
    params: dict[str, Any] = {}    # {param} placeholders allowed in values
    output_key: str                # dataModel key receiving the result

class LayoutSpec(BaseModel):
    component: str                 # catalog component name (e.g. "Infographic")
    properties: dict[str, Any]     # catalog properties; data props use {"$bind": "/pointer"}

class RenderSpec(BaseModel):
    profile: str = "interactive-html"      # renderer name for get_a2ui_renderer()
    theme: Optional[str] = None
    delivery: Optional[dict[str, Any]] = None  # provider/recipients for deliver_artifact

class ScheduleSpec(BaseModel):
    principal: str                 # explicit run-as principal (G8); REQUIRED when scheduled
    # cron/interval config lives in the AgentSchedulerManager job, not here

class InfographicRecipe(BaseModel):
    schema_version: int = 1
    name: str                      # unique per store scope
    title: str
    description: Optional[str] = None
    owner: Optional[str] = None    # user/agent scope
    params: list[RecipeParam] = []
    data_sources: list[DataSourceSpec]
    transforms: list[TransformStep]
    layout: LayoutSpec
    render: RenderSpec = RenderSpec()
    schedule: Optional[ScheduleSpec] = None
    updated_at: datetime           # overwrite semantics (G5)

class TransformerManifest(BaseModel):
    name: str
    description: str
    requires_columns: dict[str, list[str]]  # input alias → required columns
    params_schema: dict[str, Any]           # JSON schema of accepted params

class RecipeRunError(BaseModel):            # structured fail-fast diagnostic (G4)
    recipe: str
    stage: Literal["params", "data", "gate", "transform", "layout", "render"]
    transformer: Optional[str] = None
    dataset: Optional[str] = None
    missing_columns: list[str] = []
    detail: str
```

### New Public Interfaces

```python
# parrot/outputs/a2ui/recipes/transformers.py (NEW)
def infographic_transformer(
    name: str, *, requires_columns: dict[str, list[str]] | None = None,
    description: str = "",
) -> Callable: ...                          # registration decorator (pure functions only)

class TransformerRegistry:
    def get(self, name: str) -> RegisteredTransformer: ...
    def manifest(self, name: str) -> TransformerManifest: ...
    def list(self) -> list[TransformerManifest]: ...

# parrot/outputs/a2ui/recipes/store.py (NEW)
class AbstractRecipeStore(ABC):
    async def save(self, recipe: InfographicRecipe) -> None: ...      # overwrite + updated_at
    async def get(self, name: str, owner: str | None = None) -> InfographicRecipe: ...
    async def list(self, owner: str | None = None) -> list[dict]: ...
    async def delete(self, name: str, owner: str | None = None) -> None: ...

class FileRecipeStore(AbstractRecipeStore): ...   # YAML/JSON directory
class DBRecipeStore(AbstractRecipeStore): ...     # SkillRegistry pattern, core table

# parrot/tools/infographic_recipes/runner.py (NEW — outside a2ui core, may import DatasetManager)
class RecipeRunner:
    def __init__(self, store: AbstractRecipeStore, dataset_manager: DatasetManager, ...): ...
    async def run(
        self, name: str, *, params: dict[str, Any] | None = None,
        pctx: Any | None = None,           # invoker context; scheduled jobs pass principal's
    ) -> RenderedArtifact: ...             # raises RecipeRunException(RecipeRunError) on failure
    async def dry_run(self, recipe: InfographicRecipe) -> list[RecipeRunError]: ...  # freeze-path validation

# parrot/tools/infographic_toolkit.py (EXTENDED — four new tools)
async def infographic_save_recipe(...) -> dict: ...        # freeze current session envelope
async def infographic_list_recipes(...) -> list[dict]: ...
async def infographic_run_recipe(name: str, params: dict | None = None) -> dict: ...
async def infographic_get_recipe_contract(name: str) -> dict: ...  # datasets+columns+params needed

# packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/interactive_html.py (NEW)
class InteractiveHTMLRenderer(AbstractA2UIRenderer):
    capabilities = RendererCapabilities(
        interactive=True, supports_actions=False, supports_updates=False, output="text/html",
    )
    async def render(self, envelope: CreateSurface, *, bake: bool = True) -> RenderedArtifact: ...
```

---

## 3. Module Breakdown

> Modules map to Task Artifacts. Dependency spine: M1 → M2 → (M3, M4) → M5 → M6;
> M7 and M8 depend only on M1 (+M5 for M8's runner wiring) and touch disjoint packages.

### Module 1: Recipe models + param resolution
- **Path**: `packages/ai-parrot/src/parrot/outputs/a2ui/recipes/{__init__,models,params}.py`
- **Responsibility**: `InfographicRecipe` and sub-models (§2 Data Models); JSON/YAML
  round-trip; plain `{param}` substitution engine + the five built-in relative-date resolvers
  (`current_month`, `previous_month`, `today`, `yesterday`, `first_of_month`); undeclared
  override params are rejected. Pure — no DatasetManager/agent imports (G8 rule).
- **Depends on**: existing `parrot.outputs.a2ui.models` only.

### Module 2: Transformer registry + validation gate
- **Path**: `packages/ai-parrot/src/parrot/outputs/a2ui/recipes/transformers.py`
- **Responsibility**: `@infographic_transformer` decorator, `TransformerRegistry`,
  `TransformerManifest`, and the fail-fast gate helper (check `requires_columns` against
  dataframe columns, reject empty frames) producing `RecipeRunError` diagnostics.
- **Depends on**: Module 1.

### Module 3: Built-in transformer library
- **Path**: `packages/ai-parrot/src/parrot/outputs/a2ui/recipes/library.py`
- **Responsibility**: port `sdd/artifacts/executive_summary.py` analysis functions as
  registered transformers — `day_totals`, `division_breakdown`, `variance_analysis`
  (first-vs-latest trends), `top_movers` (worst/best N) — plus generic `groupby_aggregate`,
  `pivot`, `latest_vs_baseline`. Golden-file tested against fixture data derived from the
  reference artifacts.
- **Depends on**: Module 2.

### Module 4: Recipe stores (file + DB)
- **Path**: `packages/ai-parrot/src/parrot/outputs/a2ui/recipes/store.py`
- **Responsibility**: `AbstractRecipeStore`, `FileRecipeStore` (YAML/JSON directory, one file
  per recipe), `DBRecipeStore` (core table, SkillRegistry persistence pattern; overwrite +
  `updated_at`). Owner scoping on all operations.
- **Depends on**: Module 1.

### Module 5: RecipeRunner
- **Path**: `packages/ai-parrot/src/parrot/tools/infographic_recipes/{__init__,runner}.py`
- **Responsibility**: the seven-step replay pipeline (§2 diagram): param resolution → dataset
  acquisition via DatasetManager (invoker `pctx`, G8-permissions) → validation gate →
  transform chain → envelope assembly (`build_infographic` + `validate_envelope`) → render via
  `get_a2ui_renderer(profile)` → persist/deliver. `dry_run()` for the freeze path. Structured
  `RecipeRunException` carrying `RecipeRunError`.
- **Depends on**: Modules 1–4; existing DatasetManager, builders, renderer registry, delivery.

### Module 6: InfographicToolkit recipe tools + freeze path
- **Path**: `packages/ai-parrot/src/parrot/tools/infographic_toolkit.py` (extend) +
  `packages/ai-parrot/src/parrot/tools/infographic_recipes/freeze.py`
- **Responsibility**: `infographic_save_recipe` (capture session envelope + dataset/transform
  provenance → normalize → `dry_run` → persist), `infographic_list_recipes`,
  `infographic_run_recipe`, `infographic_get_recipe_contract`. Tool docstrings written for LLM
  consumption (framework rule).
- **Depends on**: Module 5.

### Module 7: Interactive-HTML renderer (satellite)
- **Path**: `packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/interactive_html.py`
  (+ vendored `chart.umd.min.js` asset)
- **Responsibility**: self-contained interactive HTML document: embedded dataModel JSON
  (`<script type="application/json" id="report-data">` pattern), vendored Chart.js v4,
  vanilla-JS behaviors (day tabs, metric toggle, column sort) generated from the lowered
  component tree. Self-registers as `"interactive-html"` via `register_a2ui_renderer`. Zero
  external network references in output.
- **Depends on**: Module 1 (recipe render profile name); existing renderer contract.

### Module 8: REST handler + scheduler callback (server)
- **Path**: `packages/ai-parrot-server/src/parrot/handlers/infographic_recipes.py` (+ route
  registration; scheduler callback registration alongside existing scheduler wiring)
- **Responsibility**: `RecipeHandler(BaseView)` — CRUD for recipes + `POST .../{name}/run`
  (422 with `RecipeRunError` on failure); register a `run_recipe` job callback on
  `AgentSchedulerManager` so recipe replays are schedulable through the existing
  `SchedulerJobsHandler` CRUD; scheduled runs execute under the recipe's stored
  `schedule.principal`.
- **Depends on**: Modules 4–5.

### Module 9: End-to-end example + docs
- **Path**: `docs/outputs/infographic-recipes.md` + `examples/` recipe reproducing the
  budget-variance dashboard (fixture CSVs → recipe YAML → interactive HTML)
- **Responsibility**: the migration story for the reference artifacts: a hand-written
  `budget-variance-daily.yaml` recipe using Modules 1–8 end-to-end; documented scheduling
  walkthrough replacing `daily_report.py`'s Task Scheduler + Outlook flow.
- **Depends on**: Modules 1–8.

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_recipe_roundtrip_json_yaml` | M1 | Recipe model serializes/deserializes losslessly in both formats |
| `test_param_substitution_and_resolvers` | M1 | `{param}` substitution; all five date resolvers; undeclared override rejected |
| `test_transformer_registration_and_manifest` | M2 | Decorator registers; manifest exposes params schema + required columns |
| `test_gate_missing_columns_fail_fast` | M2 | Gate produces `RecipeRunError` naming recipe/transform/dataset/columns |
| `test_gate_empty_dataset_fail_fast` | M2 | Empty frame rejected before transforms run |
| `test_library_golden_day_totals` | M3 | `day_totals`/`division_breakdown`/`variance_analysis`/`top_movers` match golden outputs derived from `executive_summary.py` semantics |
| `test_file_store_crud_and_owner_scope` | M4 | Save/get/list/delete; overwrite bumps `updated_at`; owner isolation |
| `test_db_store_crud` | M4 | Same contract against the DB backend (mocked/asyncdb test double) |
| `test_runner_pipeline_order_and_binding` | M5 | Transform outputs land at `output_key`; layout `$bind` pointers resolve; envelope passes `validate_envelope` |
| `test_runner_unknown_transformer` | M5 | Fails at gate listing registered transformers |
| `test_runner_dataset_not_registered` | M5 | Error suggests available datasets; recipe unchanged |
| `test_freeze_normalizes_and_dry_runs` | M6 | Freeze path produces a recipe whose `dry_run` is clean |
| `test_interactive_html_self_contained` | M7 | Output has zero external refs; embeds dataModel JSON; includes Chart.js + behavior JS |
| `test_recipe_handler_run_422_on_drift` | M8 | REST run returns 422 with structured `RecipeRunError` |
| `test_scheduler_callback_uses_principal` | M8 | Scheduled replay runs under `schedule.principal`, not server identity |

### Integration Tests
| Test | Description |
|---|---|
| `test_e2e_budget_variance_recipe` | Fixture CSVs → DatasetManager → `budget-variance-daily` recipe → transforms → envelope → interactive HTML artifact; re-run with changed fixture data yields updated numbers, identical structure |
| `test_e2e_freeze_then_replay` | Envelope from a simulated session → freeze → replay from store produces an equivalent envelope without the LLM |
| `test_e2e_static_profile_delivery` | Same recipe rendered via existing `ssr-html` profile → `RenderedArtifact` → `deliver_artifact` (mock notification) |

### Test Data / Fixtures
```python
@pytest.fixture
def budget_variance_frames():
    """Three snapshot DataFrames (first-of-month, yesterday, today) with columns
    [division, project, rev_actual, rev_budget, ebitda_actual, ebitda_budget],
    derived from the sdd/artifacts/daily_report.py compact-row format."""

@pytest.fixture
def budget_variance_recipe():
    """Hand-written InfographicRecipe (YAML) reproducing the reference dashboard:
    KPI row + day ribbon + actual-vs-budget chart + grouped ledger DataTable."""
```

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] All unit tests pass (`pytest packages/ai-parrot/tests/outputs/a2ui/recipes/ packages/ai-parrot/tests/tools/infographic_recipes/ -v` and satellite/server suites)
- [ ] All integration tests pass, including `test_e2e_budget_variance_recipe`
- [ ] Recipes contain **no executable code** — grep-level check: no `exec`/`eval`/code fields in the recipe schema; transformers resolve only through the registry (G1)
- [ ] A hand-written YAML recipe and a frozen-from-session recipe replay through the identical `RecipeRunner.run()` path (G2)
- [ ] Replay with `force_refresh=True` re-fetches through DatasetManager and honors `{param}` overrides + all five date resolvers (G3)
- [ ] Missing required column and empty dataset each abort BEFORE any transform executes, with a `RecipeRunError` naming recipe, stage, transformer, dataset and columns (G4)
- [ ] `FileRecipeStore` and `DBRecipeStore` pass the same contract test suite; save is overwrite + `updated_at` bump (G5)
- [ ] Chat tool, REST endpoint and scheduler callback all invoke the same `RecipeRunner.run()` (G6)
- [ ] `interactive-html` output is a single self-contained HTML file: works offline (file://), zero external network refs, day tabs + metric toggle + column sort functional (G7)
- [ ] Chat/REST replays receive the invoker's `pctx`; scheduled replays use `schedule.principal`; a permission-denied dataset fails the run rather than silently widening access (G8)
- [ ] Undeclared override parameters are rejected (typo protection)
- [ ] Unknown renderer profile degrades with the existing actionable ImportError naming the pip extra
- [ ] `parrot.outputs.a2ui.recipes` imports NOTHING from agents/DatasetManager/LLM clients (G8 import rule; enforced by a test)
- [ ] No breaking changes to existing public API (template tools of `InfographicToolkit` untouched)
- [ ] Documentation: `docs/outputs/infographic-recipes.md` with the budget-variance migration example

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> This section is the single source of truth for what exists in the codebase.
> Implementation agents MUST NOT reference imports, attributes, or methods
> not listed here without first verifying they exist via `grep` or `read`.
> All references re-verified on 2026-07-22 against `dev`.

### Verified Imports
```python
from parrot.outputs.a2ui.models import CreateSurface, Component      # a2ui/__init__.py:12 re-exports
from parrot.outputs.a2ui.builders import (                            # builders.py
    build_surface, build_chart, build_kpicard, build_datatable, build_infographic,
)
from parrot.outputs.a2ui.catalog import validate_envelope, register_component, DEFAULT_CATALOG_ID
    # catalog/__init__.py: validate_envelope:165, register_component:57, DEFAULT_CATALOG_ID re-export:21
from parrot.outputs.a2ui.catalog.base import ProducerOrigin, CatalogValidationError
    # catalog/base.py: ProducerOrigin:41, CatalogValidationError:124, DEFAULT_CATALOG_ID:38
from parrot.outputs.a2ui.renderers import (
    AbstractA2UIRenderer, RendererCapabilities, get_a2ui_renderer, register_a2ui_renderer,
)   # renderers/__init__.py __all__:26-31
from parrot.outputs.a2ui.artifacts import RenderedArtifact, DeepLink  # artifacts.py:41, :23
from parrot.outputs.a2ui.delivery import deliver_artifact             # delivery.py:86
from parrot.tools.dataset_manager.tool import DatasetManager, DatasetEntry  # tool.py:501, :124
from parrot.tools.toolkit import AbstractToolkit                      # used by infographic_toolkit.py:26
from parrot.skills.store import SkillRegistry                         # skills/store.py:120 (pattern reference)
```

### Existing Class Signatures
```python
# packages/ai-parrot/src/parrot/tools/dataset_manager/tool.py
class DatasetEntry:                                                    # line 124
    # .df property (backward-compatible) → materialized pd.DataFrame  # docstring lines 131-132
    def __init__(self, name: str, description: Optional[str] = None,
                 source: Optional[DataSource] = None,
                 metadata: Optional[Dict[str, Any]] = None, ...):      # line 139

class DatasetManager(AbstractToolkit):                                 # line 501
    tool_prefix: str = "dataset"                                       # near line 522
    def get_dataset_entry(self, name: str) -> Optional[DatasetEntry]:  # line 2250
    async def list_datasets(self) -> List[Dict[str, Any]]:             # line 2762
    async def get_metadata(self, ...):                                 # line 2895
    async def get_dataframe(self, name: str) -> Dict[str, Any]:        # line 3131 — returns info dict, NOT a DataFrame
    async def fetch_dataset(self, name: str, sql: Optional[str] = None,
                            conditions: Optional[Dict[str, Any]] = None,
                            force_refresh: bool = False) -> Dict[str, Any]:  # line 3266

# packages/ai-parrot/src/parrot/outputs/a2ui/builders.py
def build_surface(component: str, properties: dict[str, Any], *, surface_id: str,
                  component_id: str = ..., data_model: Optional[dict] = None) -> CreateSurface:  # line 44
def build_chart(*, chart_type: str, x: str, y: Sequence[str], title=None,
                data_binding: Optional[str] = None, show_legend: bool = True,
                surface_id: str = "chart") -> CreateSurface:            # line 71
def build_kpicard(*, label: str, value: Any, unit=None, delta=None, trend=None,
                  surface_id: str = "kpi") -> CreateSurface:            # line 91
def build_datatable(...) -> CreateSurface:                              # line 128
def build_infographic(*, title: str, sections: Sequence[dict[str, Any]], subtitle=None,
                      theme=None, surface_id: str = "infographic",
                      data_model: Optional[dict] = None) -> CreateSurface:  # line 151

# packages/ai-parrot/src/parrot/outputs/a2ui/models.py
class Component(BaseModel): ...       # line 123 — id, component, properties (w/ $bind validation)
class CreateSurface(A2UIMessageBase): # line 167 — surfaceId, catalogId, components, dataModel

# packages/ai-parrot/src/parrot/outputs/a2ui/renderers/__init__.py
class RendererCapabilities(BaseModel):        # line ~48 — interactive/supports_actions/supports_updates/output
class AbstractA2UIRenderer(ABC):              # line ~65
    capabilities: RendererCapabilities
    @abstractmethod
    async def render(self, envelope: CreateSurface, *, bake: bool = True) -> "Any | str": ...
# get_a2ui_renderer resolves registry-first, then importlib-imports
# "parrot.outputs.a2ui_renderers.<name>" (satellite self-registers on import);
# missing satellite → actionable ImportError naming pip extra
# "ai-parrot-visualizations[a2ui]" (or a2ui-pdf when name contains "pdf").

# packages/ai-parrot/src/parrot/outputs/a2ui/artifacts.py
class RenderedArtifact(BaseModel):            # line 41
    artifact_id: str; mime_type: str
    content: Optional[bytes]; path: Optional[Path]   # XOR-validated (line 73)
    filename: str; title: str; surface: str
    source_envelope_ref: Optional[str]
    deep_links: list[DeepLink]; metadata: dict[str, Any]

# packages/ai-parrot/src/parrot/outputs/a2ui/delivery.py
async def deliver_artifact(owner: Any, artifact: RenderedArtifact, *, recipients: Any,
                           provider: Any = _EMAIL, message: str = "",
                           subject: Optional[str] = None, artifact_store: Any = None,
                           user_id=None, agent_id=None, session_id=None) -> dict[str, Any]:  # line 86

# packages/ai-parrot/src/parrot/tools/infographic_toolkit.py (FEAT-197 + TASK-1739)
class InfographicToolkit(AbstractToolkit):    # line 111
    async def render(self, ...):              # line 245
    def _build_a2ui_envelope(self, ...):      # line 494
    async def list_templates(self) -> List[Dict[str, str]]:              # line 611
    async def get_template_contract(self, template_name: str) -> Dict[str, Any]:  # line 625

# packages/ai-parrot/src/parrot/skills/store.py (DB-store blueprint — reference only)
class SkillRegistry:                          # line 120 — upload_skill:263, read_skill:475,
                                              # list_skills:774, _persist_skill:820

# packages/ai-parrot-server/src/parrot/scheduler/manager.py (EXISTING scheduler)
class ScheduleType(Enum):                     # line 52 — ONCE/DAILY/WEEKLY/MONTHLY/INTERVAL/CRON/CRONTAB
def schedule(schedule_type: ScheduleType = ScheduleType.DAILY, *,
             success_callback=None, send_result=None, callbacks=None,
             **schedule_config):              # line 63 — decorator attaching _schedule_config metadata
class AgentSchedulerManager:                  # line 284 — APScheduler-backed job manager
    def __init__(self, bot_manager: Any = None, **kwargs):               # line 296
    def _prepare_call_arguments(self, ...):   # line 336

# packages/ai-parrot-server/src/parrot/handlers/scheduler.py (EXISTING job CRUD REST)
class SchedulerJobsHandler(BaseView):         # line 52 — get:70 post:90 patch:119 delete:141
class SchedulerCallbacksHandler(BaseView):    # line 33 — lists registered job callbacks

# packages/ai-parrot-server/src/parrot/handlers/datasets.py (REST pattern)
class DatasetManagerHandler(BaseView):        # line 141

# packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/ssr_html.py
class SSRHTMLRenderer(AbstractA2UIRenderer):  # line 59 — self-contained, NO scripts,
    async def render(self, ...):              # line 62 — registered interactive=False (line 53)
```

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `RecipeRunner` | `DatasetManager.fetch_dataset()` | method call with substituted sql/conditions, `force_refresh=True` | `tool.py:3266` |
| `RecipeRunner` | `DatasetManager.get_dataset_entry(name).df` | raw DataFrame access for transforms | `tool.py:2250`, `:124` |
| `RecipeRunner` | `build_infographic()` → `validate_envelope()` | envelope assembly (builders already call validation) | `builders.py:151`, `catalog/__init__.py:165` |
| `RecipeRunner` | `get_a2ui_renderer(profile)` | registry-first, satellite-import fallback | `renderers/__init__.py` |
| `RecipeRunner` | `deliver_artifact(owner, artifact, ...)` | optional post-render delivery | `delivery.py:86` |
| `InteractiveHTMLRenderer` | `register_a2ui_renderer("interactive-html", ...)` | self-registration on satellite import | `renderers/__init__.py:26-31` |
| Recipe tools | `InfographicToolkit` | new methods on existing toolkit (AbstractToolkit auto-exposure) | `infographic_toolkit.py:111` |
| `RecipeHandler` | `BaseView` | same handler pattern as datasets | `handlers/datasets.py:141` |
| Scheduler callback | `AgentSchedulerManager` job config | registered callback invoking `RecipeRunner.run()` under `schedule.principal` | `scheduler/manager.py:284` |

### Does NOT Exist (Anti-Hallucination)
- ~~`parrot/outputs/a2ui/recipes/`~~ — does not exist yet; entirely new subpackage (this feature creates it)
- ~~`TransformerRegistry` / `@infographic_transformer` / any transform registry~~ — no transform registry anywhere in `parrot/` (grep-verified)
- ~~`RecipeStore` / `AbstractRecipeStore` / `InfographicRecipe` / `RecipeRunner`~~ — do not exist yet
- ~~An interactive/JS-emitting A2UI HTML renderer~~ — `SSRHTMLRenderer` is explicitly script-free (`interactive=False`); `echarts.py` emits a payload, not a standalone interactive document
- ~~Vendored Chart.js in ai-parrot-visualizations~~ — only ECharts is vendored today; Chart.js v4 must be ADDED as a vendored asset (Module 7)
- ~~A scheduler subsystem in **core** ai-parrot~~ — core's `apscheduler` extra is commented out (`packages/ai-parrot/pyproject.toml:184`); the scheduler lives in **ai-parrot-server**: `AgentSchedulerManager` (`scheduler/manager.py:284`, apscheduler==3.11.2) + `SchedulerJobsHandler` (`handlers/scheduler.py:52`). Do NOT build a new scheduler
- ~~`DatasetManager.get_dataframe()` returning a raw `pd.DataFrame`~~ — it returns a `Dict[str, Any]` (info + sample rows); raw frames come from `get_dataset_entry(name).df`
- ~~`InfographicToolkit` recipe/replay/dataset-refresh capabilities~~ — the existing toolkit has TEMPLATES (positional block contracts, FEAT-197), not recipes; do not conflate the two systems

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- **One-way import rule (FEAT-273 G8)**: `parrot.outputs.a2ui.recipes` (Modules 1–4) must
  never import agents, DatasetManager, or LLM clients. The runner (Module 5) lives in
  `parrot/tools/infographic_recipes/` precisely so it may import DatasetManager. Enforce with
  an import-linter-style test.
- **Toolkit pattern**: new tools are methods on `InfographicToolkit` (AbstractToolkit
  auto-exposure); every tool has an LLM-grade Google-style docstring.
- **Renderer pattern**: copy `ssr_html.py`'s structure — module-level self-registration,
  `RendererCapabilities` class attribute, self-contained output (all assets inline; the
  reference template's Google-Fonts `@import` must NOT be reproduced — system font fallbacks).
- **Store pattern**: `DBRecipeStore` follows `SkillRegistry` persistence (`skills/store.py`);
  `FileRecipeStore` follows the one-file-per-item discipline of skills file layouts.
- **Handler pattern**: `RecipeHandler` mirrors `DatasetManagerHandler` (BaseView, post_init,
  error responses).
- **Fail-fast diagnostics**: every abort path constructs a `RecipeRunError`; REST maps it to
  422; the chat tool returns it as structured tool output for the agent to explain.
- Async-first throughout; Pydantic v2 models; `self.logger`, never `print`.

### Known Risks / Gotchas
- **`$bind` pointer drift**: layout bindings reference dataModel keys produced by transforms;
  a renamed `output_key` silently breaks bindings. Mitigation: `dry_run` cross-checks every
  `$bind` pointer against declared `output_key`s and fails fast (part of Module 5).
- **Chart.js vendoring size**: chart.umd.min.js (~200KB) inflates every artifact. Acceptable
  (reference template already inlines it); document artifact-size expectations. Do not add
  more chart libs to the profile.
- **Recipe/dataset coupling**: a recipe is only as replayable as its dataset registration.
  `infographic_get_recipe_contract` exposes exactly which datasets/columns/params a recipe
  needs so operators can verify before scheduling.
- **Scheduled principal validity**: a stored `schedule.principal` can be deprovisioned;
  scheduled runs must fail with the standard permission diagnostic, never fall back to a
  server identity (G8 criterion).
- **Freeze-path provenance**: capturing "which transforms were used" from a live session
  requires the session to have used registry transformers (not ad-hoc REPL pandas). The freeze
  tool must reject envelopes whose data provenance can't be expressed as recipe steps, with a
  clear message (this is the boundary of G2, not a bug).
- **Timezone in date resolvers**: `current_month`/`yesterday` etc. must resolve in a
  configurable timezone (default UTC) — the reference `daily_report.py` bug class
  (filename-date off-by-one) is exactly what these resolvers must not reintroduce.

### External Dependencies
| Package | Version | Reason |
|---|---|---|
| `pydantic` | v2 (existing) | recipe/manifest models |
| `pandas` | existing | transform execution substrate |
| `PyYAML` | existing | hand-authored file recipes |
| `apscheduler` | `==3.11.2` (existing, server) | scheduled replays via AgentSchedulerManager |
| Chart.js | v4.x vendored asset (NEW, no pip dep) | interactive-html profile charts |
| `asyncdb` (existing stack) | existing | DBRecipeStore persistence |

---

## 8. Open Questions

> All brainstorm questions were resolved before this spec was written
> (`sdd/proposals/infographic-builder.brainstorm.md`). Echoed here for the audit trail.

- [x] Interactive-html renderer JS scope — *Resolved in brainstorm*: vendor Chart.js v4 as
  well (visual fidelity with the reference template); minimum v1 behaviors: day tabs, metric
  toggle, column sort in vanilla JS, all driven from the embedded dataModel JSON.
- [x] Recipe versioning semantics — *Resolved in brainstorm*: simple overwrite + `updated_at`
  (plus `schema_version`); full version history is a possible follow-up.
- [x] Refresh-parameter templating — *Resolved in brainstorm*: plain `{param}` substitution +
  fixed built-in relative-date resolvers (`current_month`, `previous_month`, `today`,
  `yesterday`, `first_of_month`). No expression language.
- [x] PBAC context on replay — *Resolved in brainstorm*: invoker's context for chat and REST;
  scheduled jobs store an explicit principal in the recipe's schedule config and run under it.
  Permissions never elevated.
- [x] DBRecipeStore placement — *Resolved in brainstorm*: core ai-parrot, SkillRegistry
  precedent — usable without the server package.
- [x] Scheduled trigger mechanism — *Resolved in brainstorm*: use the EXISTING
  APScheduler-based `AgentSchedulerManager` in ai-parrot-server; register recipe replay as a
  job callback; jobs managed via the existing `SchedulerJobsHandler` REST CRUD; the recipe
  REST endpoint also allows direct invocation. Do not build a new scheduler.
- [x] LLM-assisted repair on schema drift — *Resolved in brainstorm*: fast-follow, out of v1;
  v1's structured drift diagnostic is designed to feed it later.
- [ ] Exact Chart.js vendored version + sourcing (npm dist tarball vs jsDelivr pinned file)
  and license-notice placement — decide at Module 7 implementation. — *Owner: implementer*

---

## Worktree Strategy

- **Default isolation unit**: `per-spec` — all tasks sequential in one worktree
  (`feat-324-infographic-builder`).
- **Rationale**: the dependency spine (M1 → M2 → M3/M4 → M5 → M6) dominates the task graph;
  only M7 (visualizations satellite) and M8 (server) touch disjoint packages and could in
  principle run in parallel after M1/M5 land — but with only 2 of 9 modules parallelizable,
  worktree-per-task overhead outweighs the gain. Order M7 after M1, M8 after M5, within the
  same worktree.
- **Cross-feature dependencies**: none. FEAT-273 (a2UI) is fully merged. No file overlap with
  in-flight FEAT-322/FEAT-323. FEAT-306's stale worktree copy of `dataset_manager/tool.py` is
  irrelevant (this feature does not modify that file).

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-07-22 | Jesus Lara + Claude | Initial draft from brainstorm (all questions pre-resolved) |
