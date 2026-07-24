---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Feature Specification: DataAgent Infographic — Infographic Authoring for Data Agents

**Feature ID**: FEAT-326
**Date**: 2026-07-24
**Author**: jesuslara
**Status**: approved
**Target version**: 0.26.x
**Brainstorm**: `sdd/proposals/dataagent-infographic.brainstorm.md` (Recommended Option A)

---

## 1. Motivation & Business Requirements

### Problem Statement

The "Budget Variance" infographic (`sdd/artifacts/budget_variance_dashboard_Template.html`) is
produced OUTSIDE ai-parrot by two standalone Windows scripts (`sdd/artifacts/daily_report.py` +
`sdd/artifacts/executive_summary.py`): they read CSVs from a OneDrive-synced folder, splice a
JSON payload into the template's `<script type="application/json" id="report-data">` tag, write
the HTML to disk, and email it via Outlook COM. Every new infographic of this style requires
another hand-written script.

This feature moves that workflow into ai-parrot as an **agent capability**: an agent extending
`PandasAgent` (which already carries a `DatasetManager` and a pandas REPL) that (1) takes an
infographic template, (2) follows a machine-enforced **descriptor** declaring which data fills
each section (hero cards ← revenue projection + revenue variance + EBITDA, …), (3) executes
pandas transformation code against `DatasetManager` datasets to build the per-section datasets,
(4) hands them to `InfographicToolkit` to emit the HTML, and (5) persists the artifact through
`ArtifactStore` together with a deterministic descriptor allowing re-generation with fresh data.

FEAT-324 already implements the *deterministic replay* half (recipe → DatasetManager fetch →
registered transform chain → render → deliver). This feature is the *authoring* half plus one
new render mode (**data-splice**) — it does NOT build a parallel replay path.

### Goals

- G-1: A reusable **`InfographicAuthoringMixin`** (cooperative pattern, like
  `ModelSwitchingMixin`) composable onto `PandasAgent` and any future `DatasetManager`-bearing
  agent — NOT a dedicated agent subclass.
- G-2: **Two-tier model** — tier 1: one-shot infographics built with ad-hoc REPL pandas code
  (not replayable); tier 2: published FEAT-324 recipes composed ONLY of registered transformers
  (deterministic replay via the existing `RecipeRunner`).
- G-3: **Machine-enforced `SectionDescriptor`** (Pydantic, fail-fast): required
  datasets/columns per section validated BEFORE rendering, for both render modes.
- G-4: **Data-splice render mode** in `InfographicToolkit`: inject a validated JSON payload into
  a `<script type="application/json" id="...">` marker of a self-contained HTML template
  (generalizing `splice_into_template()` from `daily_report.py`). Jinja `render_template` path
  drivable by the same descriptor.
- G-5: **Persistence milestone 1 = local disk** using existing infrastructure only:
  `ArtifactStore` + `ConversationSQLiteBackend` + `OverflowStore` over the local
  `FileManagerInterface` (`PARROT_OVERFLOW_STORE` / `PARROT_OVERFLOW_LOCAL_PATH`). S3 later is a
  configuration change, not an interface change.
- G-6: All three invocation modes: conversational (chat), programmatic API
  (`generate_infographic` / `publish_recipe`), and scheduled refresh (FEAT-324 scheduler trigger
  running the published recipe under a **system account** principal).
- G-7: Report **delivery uses FEAT-324 `RenderSpec.delivery`** (resolved in brainstorm) —
  replacing the original script's Outlook COM email step.

### Non-Goals (explicitly out of scope)

- **Transformer promotion tooling**: v1 only emits a *gap report* with suggested transformer
  source when publication finds unregistered transforms; no human-approval write path
  (resolved in brainstorm — see §8).
- **Persisting executable code in recipes or descriptors**: FEAT-324 spec G1 stays inviolable;
  tier-1 descriptors do NOT store the ad-hoc python code at all (resolved in brainstorm).
- **Porting the budget_variance template to A2UI catalog components** (brainstorm Option D
  rejected — see `sdd/proposals/dataagent-infographic.brainstorm.md`).
- **A new `FileStore`/storage abstraction or a `DataInfographicAgent` subclass** (brainstorm
  Options B/C rejected).
- **S3/GCS rollout**: deferred to configuration (`PARROT_OVERFLOW_STORE=s3`); no code changes
  planned for it in this feature.

---

## 2. Architectural Design

### Overview

A new cooperative mixin `InfographicAuthoringMixin` (in `parrot/bots/mixins/`) wires a
pre-configured `InfographicToolkit` — whose constructor ALREADY accepts `artifact_store`,
`recipe_store`, `recipe_runner`, `dataset_manager` (verified §6) — into any composed agent, and
adds the authoring API on top:

- **Tier 1 — `generate_infographic(...)`**: the agent inspects the template's
  `SectionDescriptor`, builds each declared section dataset with ad-hoc REPL pandas code
  (`PythonPandasTool` / `build_block` flow), passes the fail-fast validation gate, renders via
  the toolkit (data-splice or Jinja mode per the descriptor), persists through `ArtifactStore`,
  and returns the render result plus a **provenance descriptor** (template ref, mode, section →
  data mapping, dataset sources, params, snapshot timestamps — **no python code**).
- **Tier 2 — `publish_recipe(...)`**: maps each section build onto **registered
  `@infographic_transformer` functions** as `TransformStep`s. Full coverage → save an
  `InfographicRecipe` (additive versioned `section_descriptor` field carries the descriptor;
  resolved in brainstorm) with `RenderSpec.delivery` configured for report delivery. Partial
  coverage → return a structured **gap report** (missing transformer names + suggested source
  for a developer to register); the recipe is NOT saved partially.
- **Refresh/replay is NOT new code**: published recipes run through the existing
  `RecipeRunner.run()` (chat tool / REST / scheduler triggers per FEAT-324 G6). Scheduled
  refreshes run under a new **system account** principal resolved via
  `build_principal_context` (resolved in brainstorm) — never with a falsy `pctx` (fail-open
  hazard, §7).

The **data-splice mode** is a new `InfographicToolkit` tool
(`infographic_render_data_template`): registered self-contained HTML template + validated
payload dict → `json.dumps(payload)` injected into the `<script type="application/json"
id="...">` element (default marker id `report-data`, configurable per descriptor) → standard
`InfographicRenderResult`, persisted exactly like the existing render paths. Templates for this
mode are registered via **`template_dirs`** (on-disk registry); the template directory stays
**gitignored** for now — deployed as data, not versioned (resolved in brainstorm; note
`.gitignore` already has a global `templates/` rule at line 245).

Conversational flow example: *"Genera la infografía de budget variance con los datos de hoy"* →
tier 1 render + artifact reference. *"Publícala como reporte diario"* → tier 2 publication (or
gap report). From then on the daily refresh is a FEAT-324 scheduled recipe run.

### Component Diagram

```
                       PandasAgent (DatasetManager + PythonPandasTool REPL)
                            ▲
                            │ composes (cooperative MRO)
              InfographicAuthoringMixin  ── generate_infographic() / publish_recipe()
                   │                │
                   │ validates via  │ publishes via
                   ▼                ▼
           SectionDescriptor   TransformStep mapping ──(gap?)──► GapReport (v1 stops here)
           (fail-fast gate)         │ full coverage
                   │                ▼
                   │        InfographicRecipe (+ section_descriptor field,
                   │                │            RenderSpec.delivery)
                   ▼                ▼
             InfographicToolkit   RecipeRunner.run(pctx=system-account)   ← scheduler/REST/chat
              ├─ render_template (Jinja, existing)
              ├─ infographic_render_data_template (NEW: data-splice)
              └─ ArtifactStore.save_artifact()
                       │
                       ▼
        ConversationSQLiteBackend + OverflowStore(local FileManager)  → HTML on disk
        (PARROT_OVERFLOW_STORE=s3 later — config only)
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `parrot/bots/mixins/` | extends (new module) | `InfographicAuthoringMixin`; mirrors `model_switching.py` cooperative pattern |
| `InfographicToolkit` (`parrot/tools/infographic_toolkit.py`) | modifies | new data-splice tool + descriptor-aware validation; constructor untouched |
| `PandasAgent` (`parrot/bots/data.py`) | uses | composition target; no changes anticipated (existing hooks + `attach_dm`) |
| `DatasetManager` (`parrot/tools/dataset_manager/tool.py`) | uses (read-only) | `get_dataset_entry` / `fetch_dataset` feed the validation gate |
| `RecipeRunner` (`parrot/tools/infographic_recipes/runner.py`) | uses | ALL replay; no changes |
| FEAT-324 recipes (`parrot/outputs/a2ui/recipes/`) | modifies (additive) | versioned `section_descriptor` field on `InfographicRecipe`; new domain transformers registered via `@infographic_transformer` |
| `ArtifactStore` / `OverflowStore` (`parrot/storage/`) | uses | no changes; local-disk milestone is configuration |
| `parrot/auth/` | extends | new **system account** principal for scheduled refreshes (`build_principal_context`) |
| `RenderSpec.delivery` (FEAT-324) | uses | v1 delivery channel for generated reports |
| `sdd/artifacts/budget_variance_dashboard_Template.html` | reference asset | first data-splice template; test fixture (deployed template dir stays gitignored) |

### Data Models

```python
# NEW — parrot/tools/infographic_sections.py (Module 1); names indicative, no impl here.

class SectionSpec(BaseModel):
    """One template section and the data that must fill it."""
    name: str                      # e.g. "hero-cards"
    target: str                    # payload JSON-pointer (data-splice) or context key (jinja)
    datasets: list[str]            # required DatasetManager aliases
    columns: dict[str, list[str]]  # required columns per dataset alias
    shape: Literal["records", "scalar", "mapping", "table"]
    hint: Optional[str]            # semantic guidance for the LLM (non-enforced)

class SectionDescriptor(BaseModel):
    """Machine-enforced contract: template + mode + sections. extra='forbid'."""
    template: str
    mode: Literal["jinja", "data-splice"]
    splice_marker_id: str = "report-data"     # data-splice only
    sections: list[SectionSpec]
    params: dict[str, Any] = {}

class ProvenanceDescriptor(BaseModel):
    """Returned with every tier-1 artifact. Records datasets/params/mapping and
    snapshot timestamps. NEVER stores python code (resolved in brainstorm)."""
    descriptor: SectionDescriptor
    dataset_snapshots: dict[str, str]          # alias -> ISO-8601 snapshot ts
    artifact_id: str
    tier: Literal["one-shot", "recipe"]
    recipe_ref: Optional[tuple[str, Optional[str]]]  # (name, owner) when tier == "recipe"

class TransformerGap(BaseModel):
    """One unmapped section build found during publish_recipe()."""
    section: str
    proposed_name: str
    suggested_source: str          # transformer source for HUMAN registration — never executed

class GapReport(BaseModel):
    gaps: list[TransformerGap]
    covered: list[str]             # sections already mappable to registered transformers

# MODIFIED (additive, versioned) — parrot/outputs/a2ui/recipes/models.py
class InfographicRecipe(BaseModel):
    ...existing fields...
    section_descriptor: Optional[SectionDescriptor] = None   # NEW; schema version bumped
```

### New Public Interfaces

```python
# parrot/bots/mixins/infographic_authoring.py
class InfographicAuthoringMixin:
    async def generate_infographic(
        self, template: str, descriptor: SectionDescriptor | str,
        params: dict | None = None,
    ) -> tuple[InfographicRenderResult, ProvenanceDescriptor]: ...

    async def publish_recipe(
        self, name: str, descriptor: SectionDescriptor | str,
        owner: str | None = None, delivery: dict | None = None,   # -> RenderSpec.delivery
        overwrite: bool = False,
    ) -> InfographicRecipe | GapReport: ...

# parrot/tools/infographic_toolkit.py — new tool on InfographicToolkit
async def render_data_template(
    self, template_name: str, payload: dict,
    descriptor: SectionDescriptor | None = None,
    marker_id: str = "report-data", title: str | None = None,
) -> InfographicRenderResult: ...
```

---

## 3. Module Breakdown

### Module 1: Section descriptor contract + validation gate
- **Path**: `parrot/tools/infographic_sections.py` (+ exports)
- **Responsibility**: `SectionSpec`, `SectionDescriptor`, `ProvenanceDescriptor`,
  `TransformerGap`, `GapReport`; fail-fast validation: required datasets/columns checked against
  `DatasetManager.get_dataset_entry()`, assembled payload checked against per-section `shape`.
  Structured errors listing every unmet section (philosophy of FEAT-324 `$bind` cross-check /
  `InfographicValidationError`).
- **Depends on**: existing `DatasetManager`, `InfographicValidationError`.

### Module 2: Data-splice render mode in `InfographicToolkit`
- **Path**: `parrot/tools/infographic_toolkit.py`
- **Responsibility**: `render_data_template()` + tool exposure
  (`infographic_render_data_template`); JSON payload injection into the script-tag marker
  (generalized `splice_into_template`, structured error when marker missing); numpy/pandas-safe
  JSON serialization; persistence via existing `ArtifactStore` path; descriptor-aware validation
  when a descriptor is supplied. Template registration for this mode via existing
  `template_dirs`.
- **Depends on**: Module 1.

### Module 3: `InfographicAuthoringMixin`
- **Path**: `parrot/bots/mixins/infographic_authoring.py`
- **Responsibility**: cooperative mixin (MRO-safe next to `IntentRouterMixin`); wires the
  pre-configured `InfographicToolkit` into the agent's tools + system prompt;
  `generate_infographic()` tier-1 flow (validate → build via REPL → render → persist → return
  `ProvenanceDescriptor` with NO code); conversational affordances.
- **Depends on**: Modules 1–2; existing `PandasAgent` hooks / `attach_dm`.

### Module 4: Tier-2 publication — recipe mapping + gap report + delivery
- **Path**: `parrot/bots/mixins/infographic_authoring.py` (publish path) +
  `parrot/outputs/a2ui/recipes/models.py` (additive `section_descriptor` field, schema version
  bump + store round-trip)
- **Responsibility**: map section builds to registered transformers as `TransformStep`s;
  full coverage → save `InfographicRecipe` with `section_descriptor` and
  `RenderSpec.delivery` populated from the `delivery` argument; partial coverage → `GapReport`
  (recipe NOT saved); `(name, owner)` collision requires explicit `overwrite=True`.
- **Depends on**: Modules 1, 3; existing recipe store/`RecipeRunner` (unchanged).

### Module 5: System account principal for scheduled refresh
- **Path**: `parrot/auth/` (exact module per existing auth layout)
- **Responsibility**: a provisionable **system account** entity whose `PermissionContext` is
  built via `build_principal_context` and passed as `pctx` to scheduled
  `RecipeRunner.run()` calls. Fail-closed: scheduling a refresh without a resolvable system
  account principal is an error.
- **Depends on**: existing `parrot.auth.permission.build_principal_context`; FEAT-324 scheduler
  trigger.

### Module 6: Domain transformers + budget_variance fixture + docs
- **Path**: transformer registration module (e.g.
  `parrot/outputs/a2ui/recipes/library.py` or a domain module per existing layout);
  `packages/ai-parrot/tests/fixtures/`; `docs/`
- **Responsibility**: port `day_totals` / `division_breakdown` from
  `sdd/artifacts/executive_summary.py` into registered `@infographic_transformer` functions;
  end-to-end fixture using the budget_variance template (sample CSVs → payload
  `{"days": {...}}` → data-splice render → recipe publish → `RecipeRunner` replay);
  documentation in `docs/`.
- **Depends on**: Modules 1–4.

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_section_descriptor_forbids_extra` | 1 | `extra="forbid"` and required fields enforced |
| `test_validation_gate_missing_dataset` | 1 | Unmet section aborts pre-render, lists every deficit |
| `test_validation_gate_missing_columns` | 1 | Column-level deficit reported per dataset alias |
| `test_payload_shape_mismatch` | 1 | `shape` declaration violated → structured error |
| `test_render_data_template_splices_json` | 2 | Payload lands inside the marker script tag; template otherwise byte-identical |
| `test_render_data_template_marker_missing` | 2 | Structured error naming the expected marker id |
| `test_render_data_template_numpy_serialization` | 2 | numpy/pandas scalars coerced; non-serializable → clear error |
| `test_render_data_template_persists_artifact` | 2 | `ArtifactStore.save_artifact` called; >200 KB payload offloads to overflow |
| `test_mixin_mro_cooperative` | 3 | Composes with `PandasAgent` (`IntentRouterMixin` intact) |
| `test_generate_infographic_provenance_has_no_code` | 3 | `ProvenanceDescriptor` contains datasets/params/mapping, snapshot ts — and NO python source |
| `test_publish_recipe_full_coverage` | 4 | All sections mapped → recipe saved with `section_descriptor` + `RenderSpec.delivery` |
| `test_publish_recipe_gap_report` | 4 | Unmapped section → `GapReport`, recipe NOT saved |
| `test_publish_recipe_name_collision` | 4 | Existing `(name, owner)` without `overwrite=True` → error |
| `test_recipe_schema_version_roundtrip` | 4 | `section_descriptor` survives store save/get; old recipes still load |
| `test_scheduled_refresh_requires_system_account` | 5 | Falsy/missing pctx → fail closed, run refused |
| `test_transformers_registered` | 6 | `day_totals` / `division_breakdown` resolvable by name in the registry |

### Integration Tests
| Test | Description |
|---|---|
| `test_e2e_budget_variance_one_shot` | Sample CSVs → DatasetManager → tier-1 generate → HTML on local disk with spliced `{"days": ...}` payload |
| `test_e2e_publish_and_replay` | Tier-2 publish → `RecipeRunner.run(name, pctx=system_account_ctx)` reproduces the artifact with fresh data |
| `test_e2e_delivery_config` | Published recipe carries `RenderSpec.delivery`; replay invokes `deliver_artifact` path |

### Test Data / Fixtures
```python
@pytest.fixture
def budget_variance_template_dir(tmp_path):
    """Copies sdd/artifacts/budget_variance_dashboard_Template.html into a
    tmp template_dirs root (the deployed dir is gitignored — tests copy from
    sdd/artifacts/, which IS versioned)."""

@pytest.fixture
def sample_snapshot_csvs(tmp_path):
    """Three financial_projection_extract_YYYYMMDD.csv files (first-of-month,
    yesterday, today) matching daily_report.py's column layout."""

@pytest.fixture
def local_artifact_store(tmp_path):
    """ArtifactStore over ConversationSQLiteBackend + OverflowStore(local FileManager)."""
```

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] All unit tests pass (`pytest packages/ai-parrot/tests/ -v`)
- [ ] All integration tests pass (budget_variance e2e: one-shot, publish+replay, delivery)
- [ ] **G1 preserved**: no recipe, descriptor, or artifact stores executable code; tier-1
  `ProvenanceDescriptor` contains **no python source** (resolved in brainstorm)
- [ ] `SectionDescriptor` validation is fail-fast: rendering never starts with unmet
  datasets/columns, and the error enumerates every deficit
- [ ] Data-splice mode renders the unmodified budget_variance template with a fresh payload
  (marker `report-data`), and errors clearly when the marker is absent
- [ ] Artifacts persist through the existing `ArtifactStore` with SQLite backend + local
  filesystem overflow — HTML retrievable from disk; switching to S3 requires only
  `PARROT_OVERFLOW_STORE` (no code change)
- [ ] `publish_recipe` with full transformer coverage yields a recipe that
  `RecipeRunner.run()` replays deterministically; with partial coverage it yields a
  `GapReport` (suggested source included) and saves nothing (resolved in brainstorm)
- [ ] Recipes carry the descriptor as an **additive versioned `section_descriptor` field** on
  `InfographicRecipe`; pre-existing recipes still load (resolved in brainstorm)
- [ ] Scheduled refreshes run under a provisioned **system account** principal
  (`build_principal_context`); a falsy `pctx` is refused — fail closed (resolved in brainstorm)
- [ ] Report delivery goes through **`RenderSpec.delivery`** (resolved in brainstorm)
- [ ] Data-splice templates are registered via **`template_dirs`**; the deployed template
  directory is gitignored (resolved in brainstorm; `.gitignore` global `templates/` rule)
- [ ] Mixin composes onto `PandasAgent` without breaking `IntentRouterMixin` behavior
- [ ] No breaking changes to existing public API (`InfographicToolkit` constructor untouched)
- [ ] Documentation updated in `docs/` (mixin usage, descriptor contract, data-splice mode)

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> This section is the single source of truth for what exists in the codebase.
> Implementation agents MUST NOT reference imports, attributes, or methods
> not listed here without first verifying they exist via `grep` or `read`.
> All references re-verified 2026-07-24 on `dev`.

### Verified Imports
```python
from parrot.storage import OverflowStore              # parrot/storage/__init__.py:17
from parrot.storage import ConversationSQLiteBackend  # parrot/storage/__init__.py:21 (also Postgres/Mongo)
from parrot.storage.backends import build_overflow_store
# build_overflow_store(override=None) -> OverflowStore — resolves PARROT_OVERFLOW_STORE;
# default for non-dynamodb backends is LOCAL filesystem under PARROT_OVERFLOW_LOCAL_PATH.
from parrot.interfaces.file.abstract import FileManagerInterface  # imported by overflow.py:17
# Local/S3/GCS/Temp implementations: parrot/interfaces/file/{local,s3,gcs,tmp}.py
```

### Existing Class Signatures
```python
# packages/ai-parrot/src/parrot/bots/data.py
class PandasAgent(IntentRouterMixin, BasicAgent):                # line 354
    def attach_dm(self, dm: DatasetManager) -> None: ...        # line 475
    def add_dataframe(self, name, df, metadata=None, ...) -> str: ...  # line 2224
    # also: add_query, refresh_data, list_dataframes, ask (forces PythonPandasTool)

# packages/ai-parrot/src/parrot/tools/dataset_manager/tool.py
class DatasetManager(AbstractToolkit):                           # line 501
    async def add_dataset(...): ...                              # line 962
    def get_dataset_entry(self, name: str) -> Optional[DatasetEntry]: ...  # line 2250
    async def fetch_dataset(...): ...                            # line 3266

# packages/ai-parrot/src/parrot/tools/infographic_toolkit.py
class InfographicValidationError(Exception): ...                 # line 93
class InfographicRenderResult(BaseModel): ...                    # line 124
class InfographicToolkit(AbstractToolkit):                       # line 144
    def __init__(self, *, artifact_store: ArtifactStore,         # line 177
                 template_dirs: Optional[Any] = None,
                 templates: Optional[Dict[str, str]] = None,
                 emit_a2ui: bool = False,
                 recipe_store: Optional[AbstractRecipeStore] = None,
                 recipe_runner: Optional[RecipeRunner] = None,
                 dataset_manager: Optional[Any] = None, **kwargs) -> None: ...
    # tools: infographic_render, infographic_render_template, infographic_list_templates,
    #        infographic_get_template_contract, infographic_validate_blocks, build_block;
    #        + 4 recipe tools (save/list/run/get_recipe_contract) when recipe_store is set.

# packages/ai-parrot/src/parrot/storage/artifacts.py
class ArtifactStore:                                             # line 27
    def __init__(self, dynamodb: ConversationBackend, s3_overflow: OverflowStore) -> None: ...
    async def save_artifact(self, user_id: str, agent_id: str, session_id: str,
                            artifact: Artifact) -> None: ...

# packages/ai-parrot/src/parrot/storage/overflow.py
class OverflowStore:                                             # line 20
    INLINE_THRESHOLD: int = 200 * 1024  # 200 KB                 # line 34
    def __init__(self, file_manager: FileManagerInterface) -> None: ...
    async def maybe_offload(self, data, key_prefix) -> Tuple[Optional[dict], Optional[str]]: ...

# packages/ai-parrot/src/parrot/outputs/a2ui/recipes/models.py
class TransformStep(BaseModel): ...    # line 74 — transformer name + inputs + params + output_key
class InfographicRecipe(BaseModel): ...  # ~line 163; .transforms: list[TransformStep] (line 180)

# packages/ai-parrot/src/parrot/outputs/a2ui/recipes/transformers.py
# "Recipes reference transformations by registered name — never stored/executed code (spec G1)"
def infographic_transformer(name, ...): ...  # line 164 — registration decorator
# TransformerRegistry.register raises on re-registering a DIFFERENT function (~line 103)

# packages/ai-parrot/src/parrot/outputs/a2ui/recipes/store.py
class AbstractRecipeStore(ABC): ...          # line 125 — save/get/list/delete keyed by (name, owner)
class FileRecipeStore(AbstractRecipeStore): ...  # line 165 — on-disk recipe store

# packages/ai-parrot/src/parrot/tools/infographic_recipes/runner.py
class RecipeRunner:                          # __init__ line 194
    async def run(self, name: str, *, params: dict | None = None,
                  pctx: Any | None = None,
                  recipe_owner: Optional[str] = None) -> RenderedArtifact: ...  # line 208
# SECURITY: falsy pctx ⇒ DatasetManager PBAC fails OPEN; callers must build a real
# PermissionContext (parrot.auth.permission.build_principal_context).
```

### Reference Code (user-provided, verified in `sdd/artifacts/`)
```python
# sdd/artifacts/daily_report.py:185-200 — logic the data-splice mode generalizes
def splice_into_template(template_html: str, report_data: dict) -> str:
    start_marker = '<script type="application/json" id="report-data">'
    end_marker = "</script>"
    start_idx = template_html.find(start_marker)
    if start_idx == -1:
        raise ValueError("Could not find the report-data script tag in the template. ...")
    content_start = start_idx + len(start_marker)
    content_end = template_html.find(end_marker, content_start)
    if content_end == -1:
        raise ValueError("Could not find the closing </script> tag after report-data.")
    new_json = json.dumps(report_data)
    return template_html[:content_start] + "\n" + new_json + "\n" + template_html[content_end:]

# sdd/artifacts/executive_summary.py:40-51 day_totals(rows) and :54-71 division_breakdown(rows)
# are the two transformer candidates for Module 6. Payload row format:
# [division, project, revActual, revBudget, ebitdaActual, ebitdaBudget];
# daily_report.py:155-182 build_report_data() assembles {"days": {"YYYYMMDD": [rows...]}} —
# the exact client-side shape the template consumes.
```

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `InfographicAuthoringMixin` | `PandasAgent.attach_dm()` / tool wiring | composition (MRO) | `parrot/bots/data.py:475` |
| `SectionDescriptor` gate | `DatasetManager.get_dataset_entry()` | method call | `parrot/tools/dataset_manager/tool.py:2250` |
| `render_data_template` | `ArtifactStore.save_artifact()` | existing persist path | `parrot/storage/artifacts.py` (save_artifact) |
| `publish_recipe` | `AbstractRecipeStore.save()` | `(name, owner)` keyed store | `parrot/outputs/a2ui/recipes/store.py:134` |
| Scheduled refresh | `RecipeRunner.run(pctx=...)` | system-account `PermissionContext` | `parrot/tools/infographic_recipes/runner.py:208` |

### Key Attributes & Constants
- `OverflowStore.INLINE_THRESHOLD` → 200 KB (`parrot/storage/overflow.py:34`)
- `_URL_EXPIRY_SECONDS` via env `INFOGRAPHIC_URL_EXPIRY_SECONDS`, default 604800 (`parrot/storage/artifacts.py:24`)
- Template splice anchor `<script type="application/json" id="report-data">` at
  `sdd/artifacts/budget_variance_dashboard_Template.html:106`; file size 259,581 bytes
  (> inline threshold ⇒ rendered artifacts offload to the file manager = disk in milestone 1)
- Mixin pattern references: `parrot/bots/mixins/{identity,intent_router,model_switching}.py`

### Does NOT Exist (Anti-Hallucination)
- ~~`parrot.bots.mixins.InfographicAuthoringMixin`~~ — created by this feature (Module 3)
- ~~`DataInfographicAgent`~~ — no such class anywhere; this feature ships a mixin, NOT a subclass
- ~~data-splice / `report-data` handling in `InfographicToolkit`~~ — zero hits in
  `infographic_toolkit.py`; `render_template` is Jinja-only today (Module 2 adds it)
- ~~a standalone `FileStore` artifact abstraction~~ — disk persistence is SQLite
  `ConversationBackend` + local `FileManagerInterface` overflow, NOT a new store class
- ~~a filesystem `ConversationBackend`~~ — backends are sqlite/postgres/mongodb/dynamodb only
- ~~`SectionDescriptor` / `ProvenanceDescriptor` / `GapReport`~~ — created by Module 1; today's
  closest analogue is the positional block contract from `get_template_contract`
- ~~registered transformers `day_totals` / `division_breakdown`~~ — exist only as plain
  functions in `sdd/artifacts/executive_summary.py`; Module 6 ports + registers them
- ~~`InfographicRecipe.section_descriptor`~~ — field does not exist yet; Module 4 adds it
  (additive, schema version bump)
- ~~a system-account principal entity~~ — does not exist in `parrot/auth/`; Module 5 creates it
  (verify the exact auth-module layout before implementing — marked
  `(unverified — check before use)` at the sub-module level)

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- **Cooperative mixin** exactly like `parrot/bots/mixins/model_switching.py`
  (`class MyAgent(InfographicAuthoringMixin, PandasAgent)`); never fight `IntentRouterMixin`'s
  MRO — use the same `get_client()`/hook cooperation style.
- **Toolkit extension, not replacement**: new tool follows the existing
  `infographic_*` naming and `return_direct=True` handling in `AbstractToolkit._generate_tool`.
- Async-first throughout; Pydantic (`extra="forbid"`) for every new model; `self.logger`;
  Google-style docstrings + strict type hints; `uv` for any dependency (none expected).
- Register domain transformers with `@infographic_transformer`; registry is idempotent for the
  SAME function, raises for a DIFFERENT one under an existing name.

### Known Risks / Gotchas
- **pctx fail-open**: `RecipeRunner.run()` with falsy `pctx` disables `DatasetManager` PBAC
  filtering. Mitigation: Module 5 system account is mandatory for scheduled runs; publish/replay
  code paths refuse falsy `pctx` (fail closed). Acceptance criterion above.
- **Data-splice validation is weaker than `$bind`**: the payload-schema check cannot see inside
  the template's client-side JS. Mitigation: descriptor `shape` declarations + e2e fixture
  pinning the exact `{"days": ...}` contract; Option D (catalog port) remains the future
  stronger path.
- **JSON serialization of pandas/numpy values** (NaN, numpy scalars, Timestamps): must coerce
  explicitly and fail loudly on lossy values — `json.dumps` alone silently produces invalid
  JSON for NaN.
- **Overflow fallback inline**: if the file-manager write fails, `OverflowStore.maybe_offload`
  falls back inline with a warning — surface that in the render result instead of hiding it.
- **`.gitignore` global `templates/` rule (line 245)**: the deployed template dir must stay
  ignored (resolved decision) — but any NEW tracked template asset elsewhere needs
  `git add -f` awareness; tests therefore copy the template from `sdd/artifacts/` (versioned).
- **Recipe schema version bump** (`section_descriptor`): `store.py` `_check_schema_version`
  gates loading — the bump must keep old recipes loadable (additive/optional field only).
- **259 KB-class artifacts always offload**: local overflow path must exist and be writable at
  startup; misconfigured `PARROT_OVERFLOW_LOCAL_PATH` should fail at configure time, not at
  first render.
- **Stale data on replay**: `DataSourceSpec.force_refresh=True` default (FEAT-324 G3) keeps
  scheduled refreshes fresh; tier-1 one-shots record snapshot timestamps in the provenance
  descriptor instead.

### External Dependencies
| Package | Version | Reason |
|---|---|---|
| (none new) | — | Pure composition: pandas, pydantic, jinja2 already in the dependency tree |

---

## 8. Open Questions

> All brainstorm questions were resolved before this spec was drafted
> (`sdd/proposals/dataagent-infographic.brainstorm.md`). Decision trail:

- [x] Transformer promotion flow (agent code → registered transformer) — *Resolved in
  brainstorm*: v1 emits the gap report (with suggested transformer source) only; no promotion
  tooling. → §1 Non-Goals, §3 Module 4, §5.
- [x] Persist ad-hoc REPL code in tier-1 descriptors? — *Resolved in brainstorm*: do NOT
  persist python code — tier-1 descriptors record datasets/params/section mapping only.
  → §2 Data Models (`ProvenanceDescriptor`), §5.
- [x] Identity for scheduled refreshes — *Resolved in brainstorm*: a **system account** entity
  must be created (new system-principal concept); scheduled refreshes run under it via
  `build_principal_context`. → §3 Module 5, §5, §7 Known Risks.
- [x] Where does the `SectionDescriptor` live for tier-2 recipes? — *Resolved in brainstorm*:
  additive versioned field on `InfographicRecipe`. → §2 Data Models, §3 Module 4, §5.
- [x] Template registration + versioning — *Resolved in brainstorm*: registered via
  `template_dirs`; the template directory stays gitignored for now (deployed as data).
  `.gitignore` already has a global `templates/` rule (line 245). → §2 Overview, §5,
  §7 Known Risks.
- [x] Report delivery — *Resolved in brainstorm*: v1 MUST use `RenderSpec.delivery`.
  → §1 G-7, §3 Module 4, §5.

- [ ] Exact `parrot/auth/` sub-module and provisioning mechanism for the system account
  (config-declared vs DB-backed) — decide during Module 5 implementation. — *Owner: implementer*

---

## Worktree Strategy

- **Default isolation unit**: `per-spec` — all tasks sequential in ONE worktree
  (`.claude/worktrees/feat-326-dataagent-infographic`, branched from `dev`).
- **Rationale**: the `SectionDescriptor` contract (Module 1) is the shared spine consumed by
  Modules 2–4; descriptor-first sequencing (contract → toolkit mode → mixin → publish →
  system account → fixtures/e2e) has hard dependencies at each step. Only Module 6's
  transformer ports and docs are genuinely independent — not worth a second worktree.
- **Cross-feature dependencies**: none blocking. `parrot/tools/infographic_toolkit.py` is also
  a FEAT-324 follow-up surface — check `sdd/tasks/index/` for in-flight infographic tasks
  before cutting the worktree.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-07-24 | jesuslara + Claude | Initial draft from brainstorm (Option A, 6 resolved questions carried forward) |
| 0.2 | 2026-07-24 | jesuslara | Status → approved |
