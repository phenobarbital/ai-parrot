---
type: feature
base_branch: dev
---

# Feature Specification: Flex A2UI Dashboard Agent (`agents/flex_dashboard.py`)

**Feature ID**: FEAT-491
**Date**: 2026-09-01
**Author**: Jesus Lara (jlara@trocglobal.com) + Claude
**Status**: draft
**Target version**: next minor
**Proposal**: `sdd/proposals/flex-agent-infographic-a2ui.proposal.md` (research artifact FEAT-517; audit at `sdd/state/FEAT-517/`)

---

## 1. Motivation & Business Requirements

### Problem Statement

The Flex program needs an analytics agent that (a) answers KPI questions over
six QuerySource datasets (Payroll Contribution, Proximity Staffing, Rep
Utilization) and (b) publishes an interactive A2UI dashboard with a KPI hero
row, monthly charts, pay-code breakdowns, embedded-data client-side filters,
and a **refresh button backed by deterministic replay** — the same lane the
standalone Flex Program report (`documents/flex_program_report.html`)
pioneered by hand, now productized on the FEAT-324/326/420/469 recipe
infrastructure. Today that report is a one-off HTML file: no agent can answer
questions about its numbers, refresh it, or export a single KPI as a
structured A2UI widget.

### Goals

- A registered `flex_dashboard` agent based on `PandasAgent` consuming the six
  QuerySource slugs through its `DatasetManager`.
- Deterministic, replayable Flex dashboard recipe(s): hero cards (Worked
  Hours, Payroll, P&L Revenue, Payroll % to Revenue) + Worked Hours / Payroll /
  Revenue / Payroll% by month + Pay Code Hours + Worked Hours by Pay Code
  Allocation, refreshable via the A2UIRuntime `refresh_dashboard` lane.
- Per-section filters: Month, Flex Type, Pay Code, Cost Center (each filter
  applies only to sections whose dataset carries the column).
- `/widget` skill: export any single KPI as an A2UI structured chart / map /
  hero-card envelope for frontend rendering.
- `/infographic` skill + `InfographicToolkit`: user-requested descriptive
  infographics.
- `WorkingMemoryToolkit` for intermediate data operations.
- File-based kb documents pinning down each KPI's exact computation.
- Both deployment lanes: standalone example runner (FileRecipeStore) for
  dev/tests AND server-lane compatibility (recipes usable through the existing
  `infographic_recipes` handlers).

### Non-Goals (explicitly out of scope)

- No changes to core packages (`PandasAgent`, `DatasetManager`,
  `InfographicToolkit`, `WorkingMemoryToolkit`, A2UI runtime/renderers,
  skills middleware) — this feature is pure composition.
- No tier-1 data-splice/jinja template path (FEAT-420 removed it from
  FinanceReporter; we follow tier 2 `publish_recipe` exclusively).
- No new server handlers — the existing `infographic_recipes` /
  `infographic_render` handlers are consumed as-is.
- The `wip: info agent` work on `bots/data.py` (commit `69422348d`) is
  unrelated (confirmed in proposal U5) — do not build on or block on it.
- Ad-hoc LLM-driven SQL via `QSourceTool` — the six slugs are registered
  DatasetManager datasets; the agent does not need raw-SQL tooling.

---

## 2. Architectural Design

### Overview

`FlexDashboard(NarrativeMixin, InfographicAuthoringMixin, PandasAgent)` in
`agents/flex_dashboard.py`, mirroring `FinanceReporter` (FEAT-420) with a
sibling package `agents/flex_dashboard/` for transformers, skills and kb docs
(same file+directory coexistence pattern as `agents/porygon.py` +
`agents/porygon/`).

Data plane: `configure()` registers the six slugs on `self._dataset_manager`
via `add_dataset(query_slug=…)` (lazy `QuerySlugSource`) with stable aliases
that the transformers hard-code as input keys:

| Alias | Slug | Content |
|---|---|---|
| `msl` | `flex_msl_brian_bi` | Master Store List (district/region/market/account/store, lat/lon) |
| `finance` | `Finance_results_bi` | Monthly P&L per project (currency **strings**, `month` month-end) |
| `hours` | `flex_hours_query_pbi` | Hours/wages by month, program, pay_code, cost_center |
| `employees` | `flex_empolyees_brian_bi` | Employee roster with lat/lon, Flex Type, tenure |
| `region_utilization` | `fm_regions_avg_employees_html` | Regional monthly employee utilization (BOP/EOP dates) |
| `rep_utilization` | `fm_rep_utilization` | Rep utilization by region/state/category (has `catagory` typo column) |

Compute plane: pure `@infographic_transformer` functions in
`agents/flex_dashboard/transformers.py` (registered at import time), each
`(inputs, params) -> dict`, with a shared normalization module
(`agents/flex_dashboard/normalize.py`) for currency-string parsing, month-grain
alignment (three date conventions), and column canonicalization
(`catagory` → `category`). **Resolved KPI formulas** (spec Q&A):

- **Payroll % to Revenue** = `sum(Payroll) / sum(Revenue)` from `finance`
  (denominator is `Revenue` alone, NOT `Revenue + PC Revenue`).
- **Worked Hours** = `sum(hours)` from `hours` (pay-code/cost-center
  filterable). `finance.Total Hours` is used only as an FTE cross-check.
- **Rep Utilization** = `employees_worked / average_active` per
  region/category/month recomputed from `rep_utilization`;
  `region_utilization.Employee Utilization` (precomputed) serves as a
  validation cross-check, not the source of truth.
- **Proximity Staffing** = per-store nearest-N employees by haversine
  distance with a configurable radius threshold (default 50 miles): two map
  layers (stores / employees) + a coverage table (proposal U4).

Dashboard plane: `SectionDescriptor` + `LayoutSpec` v2 (`{"path"}` bindings,
`metadata.extensions.parrot_optional`) published via
`InfographicAuthoringMixin.publish_recipe()`; deterministic replay via
`RecipeRunner.run(name, params=…, pctx=…)`; the refresh button is a
`refresh_dashboard` `AbstractTool` (agent function) invoked through
`A2UIRuntime` `callAgentFunction`, reading per-surface filter state
(`current_a2ui_surface_state()`) exactly as in
`examples/agents/a2ui/deterministic_refresh_dashboard.py`. Filters are
**per-section** (proposal U1): each transformer declares only the filter
params its dataset supports; the recipe's `RecipeParam` declarations carry
them.

Narrative plane: `NarrativeMixin` with a `flex-narrative` skill (declared via
`NarrativeSpec(skill="flex-narrative", facts_key="narrative_facts")`), like
FinanceReporter's `budget-narrative` — the recipe replays deterministically
when no narrator is configured (optional step).

Skills plane: `skill_paths = [AGENT_SKILLS_DIR]` pointing at
`agents/flex_dashboard/skills/`, containing composite skills
`widget/SKILL.md` (triggers: `/widget`) and `infographic/SKILL.md`
(triggers: `/infographic`) plus `flex-narrative/SKILL.md`. `/widget` guides
the agent to run the named KPI's transformer via the pandas/toolkit lane and
emit the corresponding A2UI structured envelope (chart / map / hero card) —
leveraging `output_routing=True` (FEAT-224) and the structured output
adapters. `/infographic` guides use of `InfographicToolkit.render*`.

KB plane (proposal U2): one markdown doc per KPI under
`agents/flex_dashboard/kb/*.md` (versioned with code). The agent sets
`use_kb=True` and at `configure()` loads each doc as a fact dict
(`{"content": <doc text>, "metadata": {"category": "kpi", "kpi": <name>}}`)
into `self.kb_store` via `add_facts()` (`stores/kb/store.py:99`).

### Component Diagram

```
QuerySource slugs (6)
      │  add_dataset(query_slug=…)  [lazy QuerySlugSource]
      ▼
DatasetManager ──sync──▶ PandasAgent REPL (PythonPandasTool)
      │                        ▲
      │ inputs[alias]          │ /widget, Q&A, WorkingMemoryToolkit
      ▼                        │
agents/flex_dashboard/transformers.py (@infographic_transformer, pure)
      │ sections (name = transformer)          agents/flex_dashboard.py
      ▼                                        FlexDashboard(NarrativeMixin,
SectionDescriptor + LayoutSpec v2 ◀────────────  InfographicAuthoringMixin,
      │ publish_recipe()                          PandasAgent)
      ▼
InfographicRecipe (FileRecipeStore | server store)
      │ RecipeRunner.run(params)  ← byte-identical replay
      ▼
interactive-html render ──▶ dashboard HTML (hero row, charts, map, filters)
      ▲                                   │
      └── refresh_dashboard (AbstractTool) ◀─ A2UIRuntime callAgentFunction
            + current_a2ui_surface_state()     (per-surface filter dataModel)
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `PandasAgent` (`parrot/bots/data.py:379`) | extends | base class; `output_routing=True` |
| `InfographicAuthoringMixin` (`bots/mixins/infographic_authoring.py:54`) | mixes in | `publish_recipe` at :279 |
| `NarrativeMixin` (`bots/mixins/narrative.py:29`) | mixes in | subclasses `SkillRegistryMixin`; `narrate(facts, skill)` at :54 |
| `DatasetManager` (`tools/dataset_manager/tool.py:501`) | uses | `add_dataset(query_slug=…)` at :966 |
| `infographic_transformer` (`outputs/a2ui/recipes/transformers.py:164`) | uses | registers pure `(inputs, params) -> dict` at import |
| `RecipeRunner` (`tools/infographic_recipes/runner.py:204`) | uses | `run(name, params=…, pctx=…)` at :242 |
| `A2UIRuntime` (`outputs/a2ui/runtime/dispatch.py:76`) | uses | refresh RPC + surface state |
| `InfographicToolkit` (`tools/infographic_toolkit.py:180`) | attaches | `/infographic` skill backend |
| `WorkingMemoryToolkit` (`tools/working_memory/tool.py:44`) | attaches | intermediate data ops |
| Skills middleware (`skills/mixin.py:142-188`) | uses | deterministic `/trigger` activation |
| KB store (`bots/abstract.py:554-562`, `stores/kb/store.py:99`) | uses | `use_kb=True` + `add_facts` |
| `infographic_recipes` handlers (`ai-parrot-server/src/parrot/handlers/infographic_recipes.py`) | compatible with | server lane; no new handlers |

### Data Models

No new persisted Pydantic models. New code consists of:
- transformer functions returning plain dicts (recipe contract),
- `SectionDescriptor`/`SectionSpec`/`LayoutSpec`/`RecipeParam`/`NarrativeSpec`
  instances built with the EXISTING models (verified in §6),
- normalization helpers (pure functions over DataFrames).

### New Public Interfaces

```python
# agents/flex_dashboard.py  (shape only — not implementation)
@register_agent(name="flex_dashboard")
class FlexDashboard(NarrativeMixin, InfographicAuthoringMixin, PandasAgent):
    agent_id: str = "flex_dashboard"
    narrative_skill = "flex-narrative"
    skill_paths: List[Path]                     # → agents/flex_dashboard/skills/
    DASHBOARD_RECIPE_NAME = "flex-program-dashboard"

    async def register_datasets(self) -> None: ...      # six add_dataset calls
    async def configure(self, app=None, queries=None) -> None: ...
    @classmethod
    def dashboard_descriptor(cls) -> SectionDescriptor: ...
```

---

## 3. Module Breakdown

### Module 1: Normalization layer
- **Path**: `agents/flex_dashboard/normalize.py` (+ `agents/flex_dashboard/__init__.py`)
- **Responsibility**: deterministic input canonicalization — currency-string
  → float (`"$137,456.85"`, negatives `"-$44,621.24"`), month alignment
  (finance `month` month-end / hours `month_start`–`month_end` / fm `BOP
  Date`–`EOP Date` → one `month` period column), column canonicalization
  (`catagory`→`category`, `FM Region`→`region`, etc.). Pure functions.
- **Depends on**: nothing new.

### Module 2: Flex transformers
- **Path**: `agents/flex_dashboard/transformers.py`
- **Responsibility**: registered `@infographic_transformer` functions:
  `payroll_hero` (4 hero totals), `worked_hours_by_month`,
  `payroll_by_month`, `revenue_by_month`, `payroll_pct_by_month`,
  `pay_code_hours`, `pay_code_allocation`, `rep_utilization_by_region`,
  `proximity_staffing` (nearest-N + coverage, haversine, radius param
  default 50 mi), `narrative_facts` (consumes prior step outputs — must be
  the LAST section, FinanceReporter pattern). Each declares only the filter
  params its dataset supports (per-section filters): `month`, `flex_type`,
  `pay_code`, `cost_center` where applicable, via `params_schema`.
- **Depends on**: Module 1.

### Module 3: Agent class
- **Path**: `agents/flex_dashboard.py`
- **Responsibility**: `FlexDashboard` mixin composition; `register_datasets()`
  with the six aliases + `usage_guidance`; `use_kb=True` + kb-doc loading at
  configure; attach `WorkingMemoryToolkit` + `InfographicToolkit`;
  `output_routing=True`; `skill_paths`; `refresh_dashboard` agent-function
  tool (example pattern, `RecipeRunner` + surface state).
- **Depends on**: Modules 1-2.

### Module 4: Dashboard recipe & layout
- **Path**: `agents/flex_dashboard.py` (descriptor classmethods)
- **Responsibility**: `dashboard_descriptor()` — hero-card row (Worked Hours,
  Payroll, P&L Revenue, Payroll % to Revenue) + month-series sections +
  pay-code sections + proximity map/table + utilization section, LayoutSpec
  v2, `RecipeParam` declarations for the filters, `NarrativeSpec` optional
  step; published under `DASHBOARD_RECIPE_NAME` via `publish_recipe`.
- **Depends on**: Module 2 (section names = transformer names, 1:1 aliases).

### Module 5: Skills
- **Path**: `agents/flex_dashboard/skills/{widget,infographic,flex-narrative}/SKILL.md`
- **Responsibility**: `/widget` (KPI → A2UI structured chart/map/hero-card
  envelope; instructs which transformer + output mode per KPI),
  `/infographic` (InfographicToolkit descriptive infographic),
  `flex-narrative` (facts → executive prose; quote-only-figures rule copied
  from `budget-narrative`). Triggers declared in frontmatter.
- **Depends on**: Module 3.

### Module 6: KB documents
- **Path**: `agents/flex_dashboard/kb/*.md` (one per KPI)
- **Responsibility**: authoritative KPI definitions — formulas resolved in
  this spec (§2 Overview), input slug + columns, normalization rules, filter
  applicability, worked example numbers from the sample rows.
- **Depends on**: formulas in §2 (no code dependency).

### Module 7: Example runner + tests wiring
- **Path**: `examples/agents/a2ui/flex_dashboard_demo.py`
- **Responsibility**: standalone lane — synthetic seed frames (NO
  database/network/LLM), publish + replay + refresh RPC demo mirroring
  `deterministic_refresh_dashboard.py` (incl. `--serve`); doubles as the
  integration-test harness. Server-lane note: recipes published to a shared
  store are servable through existing `infographic_recipes` handlers — the
  example documents this; no server code.
- **Depends on**: Modules 1-5.

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_parse_currency` | 1 | `"$137,456.85"`→137456.85, `"-$44,621.24"`→-44621.24, `"$0.00"`→0.0 |
| `test_month_alignment` | 1 | finance month-end, hours month_start, fm BOP/EOP → same period key |
| `test_column_canonicalization` | 1 | `catagory`→`category`; fm header variants normalized |
| `test_payroll_hero_totals` | 2 | hero dict: worked hours from `hours`, payroll/revenue from `finance`, pct = payroll/revenue |
| `test_payroll_pct_denominator` | 2 | pct uses `Revenue` alone (NOT + PC Revenue) — regression pin |
| `test_month_series_transformers` | 2 | worked_hours/payroll/revenue/pct by month over synthetic frames |
| `test_pay_code_sections` | 2 | pay_code_hours + allocation respect `pay_code`/`cost_center` params |
| `test_per_section_filters` | 2 | a `flex_type` param does NOT alter finance-only sections (per-section rule) |
| `test_rep_utilization_formula` | 2 | employees_worked/average_active; cross-check column within tolerance |
| `test_proximity_staffing` | 2 | haversine nearest-N + radius coverage on fixed coordinates |
| `test_transformers_registered` | 2 | every §3-Module-2 name resolves in `transformer_registry` |
| `test_dashboard_descriptor` | 4 | section names map 1:1 to registered transformers; layout paths valid; narrative optional (FinanceReporter descriptor-test pattern) |
| `test_agent_datasets` | 3 | six aliases registered with expected source kind `query_slug` |
| `test_kb_docs_loaded` | 3/6 | configure loads one fact per kb doc |
| `test_skills_discovered` | 5 | `/widget`, `/infographic`, `flex-narrative` found via skill_paths |

Location: `packages/ai-parrot/tests/unit/bots/test_flex_dashboard_*.py`
(FinanceReporter convention).

### Integration Tests

| Test | Description |
|---|---|
| `test_flex_dashboard_publish_replay` | publish recipe → `RecipeRunner.run()` twice → byte-identical HTML (synthetic frames) |
| `test_flex_dashboard_filtered_replay` | params override (month/pay_code) → deterministic filtered variant |
| `test_flex_refresh_rpc` | A2UIRuntime `callAgentFunction`→`refresh_dashboard` honors surface filter state |

Location: `packages/ai-parrot/tests/integration/test_flex_dashboard_e2e.py`.

### Test Data / Fixtures

```python
@pytest.fixture
def flex_frames() -> dict[str, pd.DataFrame]:
    """Synthetic frames for all six aliases, shaped exactly like the
    sample rows in sdd/state/FEAT-517/source.md (currency strings,
    month conventions, 'catagory' typo included)."""
```

---

## 5. Acceptance Criteria

- [ ] `FlexDashboard` is importable from `agents/flex_dashboard.py`,
      registered as `flex_dashboard`, and instantiates without network/DB.
- [ ] The six slugs are registered as lazy `query_slug` datasets with the §2
      aliases; no eager fetch at construction.
- [ ] Payroll % to Revenue = Payroll / Revenue (finance); Worked Hours from
      `hours`; utilization recomputed from `rep_utilization` — all pinned by
      unit tests.
- [ ] Dashboard recipe publishes with FULL transformer coverage (an
      `InfographicRecipe`, not a `GapReport`) and replays byte-identically on
      unchanged inputs.
- [ ] Filters are per-section: each transformer declares only supported
      params; a filter never mutates a section whose dataset lacks the column.
- [ ] `refresh_dashboard` agent function re-runs the recipe via
      `RecipeRunner`, honoring per-surface filter state (args win).
- [ ] Proximity Staffing renders two map layers + a coverage table with a
      configurable radius (default 50 miles).
- [ ] `/widget` exports a named KPI as an A2UI structured envelope;
      `/infographic` produces an InfographicToolkit render; both skills are
      trigger-activated.
- [ ] One kb markdown doc per KPI exists and is loaded into the KB store at
      configure (`use_kb=True`).
- [ ] Recipe replays deterministically with NO narrator configured (narrative
      step optional).
- [ ] `examples/agents/a2ui/flex_dashboard_demo.py` runs offline on synthetic
      data and produces the dashboard artifacts.
- [ ] All unit + integration tests above pass (`pytest packages/ai-parrot/tests/unit/bots/test_flex_dashboard*.py packages/ai-parrot/tests/integration/test_flex_dashboard_e2e.py -v`).
- [ ] No modifications to core packages (git diff confined to `agents/`,
      `examples/`, `packages/ai-parrot/tests/`).

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor** (carried from proposal FEAT-517
> findings F001-F006 and re-verified 2026-09-01 on dev post-merge).

### Verified Imports

```python
from parrot.bots.data import PandasAgent                     # verified: agents/finance_reporter.py:41
from parrot.bots.mixins import InfographicAuthoringMixin, NarrativeMixin  # verified: agents/finance_reporter.py:42
from parrot.registry import register_agent                   # verified: agents/finance_reporter.py:44
from parrot.tools.infographic_sections import SectionDescriptor, SectionSpec, GapReport  # verified: tools/infographic_sections.py:42,80,196
from parrot.outputs.a2ui.recipes.models import LayoutSpec, NarrativeSpec, RecipeParam    # verified: recipes/models.py:109,199,51
from parrot.outputs.a2ui.recipes.transformers import infographic_transformer             # verified: recipes/transformers.py:164
from parrot.outputs.a2ui.recipes.store import FileRecipeStore                            # verified: example:83
from parrot.tools.infographic_recipes.runner import RecipeRunner, RecipeRunException     # verified: example:102-105
from parrot.outputs.a2ui.runtime import A2UICallContext, A2UIRuntime, SurfaceState       # verified: example:87-92; dispatch.py:76
from parrot.outputs.a2ui.runtime.adapters import ToolManagerExecutor                     # verified: example:93; adapters.py:51
from parrot.tools.working_memory import WorkingMemoryToolkit  # verified: working_memory/__init__.py:2; agents/porygon.py:9
from parrot.tools.infographic_toolkit import InfographicToolkit  # verified: examples/simple_infographic_agent.py:102
from parrot.tools.abstract import AbstractTool, AbstractToolArgsSchema, current_a2ui_surface_state  # verified: example:97-101
```

(All paths under `packages/ai-parrot/src/` unless noted; "example" =
`examples/agents/a2ui/deterministic_refresh_dashboard.py`.)

### Existing Class Signatures

```python
# packages/ai-parrot/src/parrot/bots/data.py
class PandasAgent(IntentRouterMixin, BasicAgent):            # line 379
    def __init__(self, name="Pandas Agent", enable_scenarios=False, tools=None,
                 system_prompt=None, df=None, query=None, capabilities=None,
                 generate_eda=True, cache_expiration=24, temperature=0.0,
                 max_iterations=None, output_routing=False,
                 output_routing_config=None, **kwargs)       # line 406
    def attach_dm(self, dm: DatasetManager) -> None          # line 494
    async def configure(self, ...) -> None                   # line 874 (queries kwarg)
    async def add_query(self, query: str) -> Dict[str, pd.DataFrame]   # line 2136
    async def refresh_data(self, cache_expiration=None, **kwargs)      # line 2160

# packages/ai-parrot/src/parrot/tools/dataset_manager/tool.py
class DatasetManager(AbstractToolkit):                       # line 501
    async def add_dataset(self, name, ..., query_slug=None, query=None,
                          table=None, dataframe=None, permanent_filter=None,
                          ...)                               # line 966 — exactly one source kwarg
    async def add_table_source(...)                          # line 1459

# packages/ai-parrot/src/parrot/bots/mixins/infographic_authoring.py
class InfographicAuthoringMixin:                             # line 54
    async def publish_recipe(self, name: str,
        descriptor: "SectionDescriptor | str", owner: Optional[str] = None,
        delivery: Optional[dict] = None, overwrite: bool = False
    ) -> Union[InfographicRecipe, GapReport]                 # line 279

# packages/ai-parrot/src/parrot/bots/mixins/narrative.py
class NarrativeMixin(SkillRegistryMixin):                    # line 29
    async def narrate(self, facts: dict[str, Any], skill: str) -> Optional[str]  # line 54

# packages/ai-parrot/src/parrot/outputs/a2ui/recipes/transformers.py
def infographic_transformer(name=..., ..., params_schema: dict | None = None)  # line 164
# registers a pure  (inputs: dict, params: dict) -> dict  at import time (line 5)

# packages/ai-parrot/src/parrot/tools/infographic_recipes/runner.py
class RecipeRunner:                                          # line 204
    async def run(self, name: str, *, params: dict | None = None,
                  pctx: Any | None = None, recipe_owner: Optional[str] = None
    ) -> RenderedArtifact                                    # line 242
    # pctx SHOULD be a real PermissionContext — falsy pctx makes
    # DatasetManager PBAC guards fail OPEN (runner.py docstring)

# packages/ai-parrot/src/parrot/stores/kb/store.py
class KnowledgeBaseStore:
    async def add_facts(self, facts: List[Dict[str, Any]])   # line 99
    # each fact: {"content": str, "metadata": {...}} — content key REQUIRED
# wired by AbstractBot: use_kb=True → self.kb_store; kwargs kb=[...] → self._kb
# (bots/abstract.py:554-562); configure_kb() calls add_facts(self._kb) (line 1453-1458)

# packages/ai-parrot/src/parrot/tools/working_memory/tool.py
class WorkingMemoryToolkit(AbstractToolkit):                 # line 44
    # store/store_result/get_stored/search_stored/compute_and_store/
    # merge_stored/summarize_stored/import_from_tool (lines 194-650)

# packages/ai-parrot/src/parrot/tools/infographic_toolkit.py
class InfographicToolkit(AbstractToolkit):                   # line 180
    async def render(self, template_name, ...)               # line 402
    async def render_template(self, template_name, ...)      # line 527
    async def render_data_template(self, template_name, ...) # line 643
    # template_dirs entries validated EAGERLY at construction (FEAT-420 lesson)
```

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `FlexDashboard.register_datasets` | `DatasetManager.add_dataset(query_slug=…)` | await on `self._dataset_manager` | `tools/dataset_manager/tool.py:966-1050` |
| flex transformers | `transformer_registry` | `@infographic_transformer` import side effect | `recipes/transformers.py:5,164` |
| `dashboard_descriptor` | `publish_recipe` section→transformer resolution | section name normalized to registry key | `bots/mixins/infographic_authoring.py:297-341` |
| `refresh_dashboard` tool | `RecipeRunner.run` + `current_a2ui_surface_state()` | example pattern lines 356-435, 603 | `examples/agents/a2ui/deterministic_refresh_dashboard.py` |
| skills | `SkillRegistryMixin` discovery | `skill_paths` class attr (directory opt-in) | `agents/finance_reporter.py:62,96` |
| kb docs | `KnowledgeBaseStore.add_facts` | `use_kb=True` + facts at configure | `bots/abstract.py:560-562,1453-1458` |

### Does NOT Exist (Anti-Hallucination)

- ~~`DatasourceManager` / `DataSourceManager` / `DatasSourceManager`~~ — the
  ticket's name does not exist anywhere; the real class is **`DatasetManager`**
  (`tools/dataset_manager/tool.py:501`).
- ~~`artifacts/a2ui_live/flex_program_report%20(39).html`~~ and
  ~~`artifacts/a2ui_live/page.html`~~ — directory does not exist. Real
  references: `docs/flex_program_report (39).html` and
  `documents/flex_program_report.html`.
- ~~`parrot.vectorstores`~~ — long gone; kb store is `parrot/stores/kb/`.
- ~~`InfographicToolkit.generate_infographic` tier-1 data-splice on this
  agent~~ — FEAT-420 removed that path from the FinanceReporter pattern; use
  `publish_recipe` (tier 2).
- ~~`PandasAgent.datasource_manager` attribute~~ — the attribute is
  `self._dataset_manager` (private, set in `__init__` at `data.py:459`).
- No pre-existing flex transformers in
  `parrot/outputs/a2ui/recipes/library.py` — that module holds FEAT-420
  finance (budget-variance) transformers only; flex ones are NEW and live
  with the agent.

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- **`agents/finance_reporter.py` end-to-end** — mixin order, `register_datasets`
  + `configure` override, descriptor classmethods, `skill_paths` anchored to
  the file's own location (not cwd), distinct recipe names, in-file gotcha
  comments.
- **`examples/agents/a2ui/deterministic_refresh_dashboard.py`** — transformer
  filter params, `RefreshDashboardTool`, `A2UIRuntime` wiring,
  `build_principal_context` for pctx, synthetic-data offline runs, `--serve`.
- **`agents/porygon.py` + `agents/porygon/`** — file+package coexistence for
  agent assets; `WorkingMemoryToolkit` attachment.
- **`.agent/skills/budget-narrative/SKILL.md`** — skill frontmatter shape
  (name/description/triggers/category/version) and the quote-only-figures
  narrative rule.
- Google-style docstrings, strict type hints, async-first, `self.logger`.

### Known Risks / Gotchas

- **Alias ↔ transformer-key 1:1** (FEAT-420 lesson): `publish_recipe` forces
  `TransformStep.inputs` to the section's declared dataset alias; transformers
  hard-code `inputs["<alias>"]`. Aliases in §2 are frozen — changing one means
  changing both sides.
- **Dirty inputs**: currency strings, three date-grain conventions, `catagory`
  typo, mixed header casing in fm_* datasets. ALL canonicalization goes
  through Module 1 — never inline in transformers.
- **`narrative_facts` must be the LAST section** — it consumes the other
  steps' output keys, not dataset aliases (FinanceReporter `:196-223`).
- **`RecipeRunner.run` pctx fails OPEN when falsy** — always pass a real
  `PermissionContext` (`build_principal_context`) in the example and any
  server path.
- **interactive-html requires an HTTP origin** — `file://` breaks Chart.js;
  example must ship `--serve`.
- **Eager `template_dirs`** — if any InfographicToolkit template ships, it
  must live in a repo-tracked directory; instantiation must not depend on
  gitignored paths.
- **A2UI v1 dialect is hot** (a2ui-v1-structured-outputs landed days ago) —
  re-verify LayoutSpec v2 details (`{"path"}` bindings,
  `metadata.extensions.parrot_optional`) against `recipes/models.py` when
  tasks start.
- **Slug data is prod-only** (project convention `ENV=prod`); unit/integration
  tests run on synthetic frames exclusively; live slugs stay lazy.
- **`Finance_results_bi` slug casing** — the slug starts with a capital
  letter; keep it verbatim in `add_dataset(query_slug="Finance_results_bi")`.

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| (none new) | — | haversine implemented with numpy (already a dependency); Prophet/Chart.js/Leaflet lanes ship with existing renderer infra |

---

## Worktree Strategy

- **Isolation unit**: per-spec — one worktree
  (`.claude/worktrees/feat-491-flex-agent-infographic-a2ui`, branched from
  `dev`), tasks sequential.
- **Why**: Modules 2-7 form a dependency chain on Module 1-2's aliases and
  formulas; parallel worktrees would fight over `agents/flex_dashboard*`.
- **Cross-feature dependencies**: none to merge first. The a2ui-v1 work is
  already on dev; the `wip: info agent` WIP is unrelated (proposal U5).

---

## 8. Open Questions

### Resolved (carried from proposal FEAT-517 + spec Q&A)

- [x] Filter scope — *Resolved in proposal (U1)*: per-section; each filter
  only affects sections whose dataset carries that column.
- [x] KB mechanism — *Resolved in proposal (U2)*: file-based markdown docs in
  the agent's directory, loaded via the kb plane (no DB dependency).
- [x] Deployment target — *Resolved in proposal (U3)*: both — standalone
  example (FileRecipeStore) + server-lane compatibility in the same feature.
- [x] Proximity Staffing — *Resolved in proposal (U4)*: per-store nearest-N
  employees, haversine, configurable radius, two map layers + coverage table.
- [x] `wip: info agent` overlap — *Resolved in proposal (U5)*: unrelated.
- [x] Payroll % denominator / Worked Hours source — *Resolved in spec Q&A*:
  Payroll / Revenue (Revenue alone); Worked Hours = sum(hours) from
  `flex_hours_query_pbi`; finance `Total Hours` only as FTE cross-check.
- [x] Utilization source — *Resolved in spec Q&A*: recomputed
  `employees_worked / average_active` from `fm_rep_utilization`; precomputed
  regional column is a cross-check.
- [x] Narrative — *Resolved in spec Q&A*: include `NarrativeMixin` with a
  `flex-narrative` skill; the narrative step stays optional so replay works
  with no narrator.

### Unresolved (defer to implementation)

- [ ] Default proximity radius: spec sets 50 miles as the default; confirm
  with Flex stakeholders whether market practice is 25 — *Owner: jlara*
  (does not block: it is a `RecipeParam` with a default).
- [ ] Exact hero-card iconography/labels vs the shipped report's KPI row —
  *Owner: frontend* (cosmetic; LayoutSpec tweak).

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-09-01 | jlara + Claude | Initial draft from proposal FEAT-517 |
