---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
# projects: parts of the codebase this doc concerns. Use `packages/*` dir names
#   (ai-parrot, ai-parrot-server, parrot-formdesigner, …) or an area
#   (sdd-tooling, dev-loop, admin-ui, docs, ci). Unknown values warn, not fail.
projects: [ai-parrot, ai-parrot-tools, ai-parrot-server, docs]
# tags: free-form kebab-case keywords for organizing specs (e.g. memory, mcp).
tags: [metrics, kpicard, a2ui, output-mode, querysource, tenancy]
---

# Feature Specification: Metric Definition Registry (tenant-scoped KPIs with a declared default shape)

**Feature ID**: FEAT-756
**Date**: 2026-10-27
**Author**: Jesus Lara
**Status**: approved
**Target version**: TBD
**Source**: Jira NAV-10382 review (2026-10-27). No accepted exploration document — see §9. Sibling specs written the same day: FEAT-755 `inline-a2ui-component-routing` (hint channel this feature plugs into), FEAT-752 `followup-suggestion-chips` (provider protocol this feature implements).

---

## 1. Motivation & Business Requirements

> Why does this feature exist? What problem does it solve?

### Problem Statement

NAV-10382 proposed a **client-side metric catalog** so the Navigator chat could turn
"show me worked hours this month" into a KPI card. The review found the real gap is
server-side: **nothing in ai-parrot decides the default shape of a metric**.

- The FEAT-224 output-mode router (`IntentRouterMixin._resolve_output_mode`,
  `packages/ai-parrot/src/parrot/bots/mixins/intent_router.py:209`) routes only
  *presentation phrasing* — "make a bar chart", "show as a table", "plot on a map" —
  against the phrase bank `DEFAULT_OUTPUT_MODE_ROUTES`
  (`packages/ai-parrot/src/parrot/bots/data.py:297`). A plain metric question carries
  no presentation verb, so the router abstains (`rs.mode is None` → `super()`), and the
  turn falls through to the agent default (`AbstractBot._apply_default_output_mode`,
  `packages/ai-parrot/src/parrot/bots/abstract.py:4191`; call sites
  `bots/base.py:300`, `bots/base.py:1155`, `bots/data.py:1350`). Precedence today is
  **explicit > router > agent default** — there is no slot for "what this *metric*
  looks like by default".
- The only KPI → shape catalog in the system is **prose for the LLM**: the Flex
  `/widget` skill asset `agents/flex_dashboard/skills/widget/kpi-table.md` (local,
  git-ignored agent dir) maps 12 Flex KPIs to a registered transformer, dataset
  aliases, a recipe data-model path, an output mode (`KPICard` hero /
  `STRUCTURED_CHART` / `STRUCTURED_TABLE` / `STRUCTURED_MAP`) and the supported
  filters. It is correct, but it is a Markdown table the model may or may not follow,
  it is per-agent (not per-tenant), nothing can list or validate it, and it is
  unreachable from tools, HTTP or MCP.
- Meanwhile the KPICard catalog component already knows how to render exactly what a
  metric needs — `label`, `value`, `unit`, `delta`, `trend`, `comparisonPeriod`,
  `higherIsBetter` (tri-state), `series`, `periods`
  (`packages/ai-parrot/src/parrot/outputs/a2ui/catalog/parrot/kpicard.py:15`) — and
  the toolkit lane can already emit TOOL-origin, refreshable *linked* surfaces for a
  query slug (`QuerysourceToolkit.build_linked_surface`,
  `packages/ai-parrot-tools/src/parrot_tools/querysource/toolkit.py:351`). What is
  missing is the **declaration** that binds a metric name to its source, its unit, its
  comparison policy and its default component.

The default shape of a metric is a property of the **metric**, not of the phrasing.
It therefore needs a persisted, tenant-scoped **metric definition registry**,
consulted *between* the phrasing router and the agent default, and executable by a
tool so the answer comes from the declared source instead of free pandas.

Who is affected: Navigator chat users (KPI questions answered as the right widget,
deterministically); agent authors (one YAML instead of a prose table per agent);
tenant administrators (per-tenant metric vocabularies, FEAT-707 style); the
ui_surfaces plane (a pinned KPI card that is refreshable because it is linked);
MCP clients (`list_metrics` / `query_metric` as first-class tools).

### Goals

- G1 **One Pydantic v2 `MetricDefinition`** that captures identity, matching vocabulary
  (aliases + example phrases), semantics (unit, format, `higher_is_better` tri-state,
  dimensions, time grain, default period, comparison policy), the **default shape**
  (KPICard | Chart | DataTable | Map with its minimal config) and a **discriminated
  `source`** (`query_slug` | `transformer` | `recipe` | reserved `semantic_metric`).
- G2 **Storage mirrors the ui_surfaces plane**: a Postgres table under the `navigator`
  schema, `AsyncDB("pg")`, idempotent `CREATE … IF NOT EXISTS` DDL, server-set tenant
  column, visibility + `allowed_groups`, PBAC through the same `RequestScope` /
  `scope_grants` seam (`packages/ai-parrot-server/src/parrot/handlers/scope.py:40,181`);
  plus an in-memory store for tests and agents without a database.
- G3 **Seed/import lanes, not hand-typed SQL**: per-agent `metrics.yaml` under the agent
  dir and the FEAT-707 tenant tree (`agents/<agent>/tenants/<tenant>/metrics.yaml`),
  and a one-shot importer that converts the Flex `kpi-table.md` rows into
  recipe-sourced definitions.
- G4 **`MetricRegistry` service**: list / describe / resolve; phrase → metric matching
  with a lexical alias fast path and an embedding lane that reuses
  `EmbeddingIntentRouter` (aliases + example phrases as the route bank); tenant-scoped
  views that shadow global definitions by id/alias exactly like `SkillView`
  (`packages/ai-parrot/src/parrot/skills/tenancy.py:134`), honouring `global_only`.
- G5 **`MetricsToolkit`** (ai-parrot-tools, MCP-exposable through `TOOL_REGISTRY` and
  `parrot mcp-local`): `list_metrics`, `describe_metric`, `query_metric`,
  `explain_metric`. `query_metric` executes the declared source, applies the period and
  the comparison policy, and emits the default-shape **TOOL-origin A2UI envelope**
  (KPICard with `delta` / `trend` / `comparisonPeriod` / `higherIsBetter` / `series`),
  optionally as a **linked** surface with a refresh policy so a pin is refreshable.
- G6 **Resolver hook**: a cooperative `_resolve_output_mode()` override in a new
  `MetricRoutingMixin` that, when the phrasing router abstains and the question matches
  a metric above threshold, answers with the metric's `default_shape` component hint
  (FEAT-755 channel) and stashes the match for the main turn / `query_metric`.
  Precedence becomes **explicit > router (phrasing) > metric default shape > agent
  default**. Zero behaviour change when no registry is configured.
- G7 **Suggestions**: a `MetricSuggestionProvider` (FEAT-752 protocol) that derives
  "vs previous period", "by <dimension>", "as <other shape>" chips from the matched
  definition — no LLM call.
- G8 **Minimal tenant-scoped REST** in ai-parrot-server (`GET` list/get for every
  caller the scope grants; `POST`/`PUT` for authors), following the `UISurfacesHandler`
  conventions (`packages/ai-parrot-server/src/parrot/handlers/ui_surfaces.py:328`).
- G9 **Additive**: no change to `IntentRouterMixin`, `AbstractBot`, `BaseBot`,
  `PandasAgent`, `clients/base.py`, the KPICard schema, the ui_surfaces DDL or the
  querysource toolkit's public tools.

### Non-Goals (explicitly out of scope)

- A query compiler / semantic layer. Metric *math* (measures, joins, RLS) is FEAT-704
  (`sdd/proposals/semantic-layer-rev2.proposal.md`, paused). This feature **reserves**
  `source.kind = "semantic_metric"` as a parse-only variant so a definition authored
  for FEAT-704 round-trips through the registry; it is never executed here.
- Chart-of-accounts rollups and fiscal calendars — FEAT-713
  (`sdd/specs/accounting-metrics-layer.spec.md`, draft) is a future *producer* of
  definitions (it may write `MetricDefinition`s), not a consumer this feature wires.
- The composite route `a2ui:<Component>`, the component-hint channel and the
  catalog-driven inline emitter — FEAT-755 owns them; this spec only *consumes* the
  hook FEAT-755 specifies.
- The chip rendering / transport of suggestions — FEAT-752 owns the protocol and the
  wire; this spec only ships one provider.
- A frontend catalog UI, client-side intent parsing (the NAV-10382 proposal as
  written), navigator-frontend-next work.
- Multi-input (`len(requires_columns) > 1`) transformers in the `transformer` lane —
  the linked `transform.python` lane is single-input in v1
  (`packages/ai-parrot/src/parrot/outputs/a2ui/linked/pytransform.py:49-50`); such
  KPIs use the `recipe` lane (which is exactly how the Flex `payroll_hero` rows work).
- `DELETE` / bulk import over HTTP, versioned definitions with history, approval
  workflows, per-user favourites.
- Changing the 7-keyword QuerySource UDF vocabulary; adding "previous month" style
  keywords upstream.
- Any change to `clients/base.py`.

---

## 2. Architectural Design

### Overview

Nine additive pieces across three distributions:

1. **Definition model (core, M1).** `parrot/metrics/models.py` — `MetricDefinition`
   and its parts (`DimensionSpec`, `TimeSpec`, `ComparisonPolicy`, the `ShapeSpec`
   union, the `MetricSource` discriminated union, `MetricMatch`). Everything a
   registry, a store, a tool, a hook or an HTTP handler needs is this one model; the
   store persists it as one JSONB column plus indexed scalar columns.
2. **Stores + seed lanes (core, M2; server, M4).** A small `MetricStore` protocol with
   `InMemoryMetricStore` (core) and `PgMetricDefinitionStore` (server, table
   `navigator.metric_definitions`, the `PgUISurfaceStore` idiom). `load_metrics_yaml`
   reads `metrics.yaml` from an agent dir and from each FEAT-707 tenant tree;
   `import_kpi_table` converts the Flex `kpi-table.md` rows into recipe-sourced
   definitions.
3. **Registry service (core, M3).** `MetricRegistry` composes `MetricView`s (global ∪
   tenant overlay, `SkillView` rules) and resolves a question to a `MetricMatch`:
   lexical alias fast path first (normalized exact / contains on `aliases ∪ {name}`),
   then an `EmbeddingIntentRouter` whose route labels are metric ids and whose bank is
   `aliases ∪ example_phrases`. Threshold/margin reuse the FEAT-224 calibration.
4. **Executors + shapes (tools, M6/M7).** One executor per source kind — `query_slug`
   through `QuerysourceToolkit.execute_slug` / `build_linked_surface`; `transformer`
   through a `query_slug` fetch plus `apply_python_transform` (the `transform.python`
   lane, by registered name); `recipe` through `RecipeRunner.run(include_envelope=True)`
   plus a JSON-pointer read of the recipe's data model. A period resolver turns
   `TimeSpec.default_period` into concrete ISO dates (and, when expressible, QuerySource
   UDF keywords) and derives the comparison period. A shape emitter builds the
   TOOL-origin envelope with the existing builders.
5. **Toolkit (tools, M5).** `MetricsToolkit(AbstractToolkit)` exposing `list_metrics`,
   `describe_metric`, `query_metric`, `explain_metric`; registered in `TOOL_REGISTRY`
   as `"metrics"` so `parrot mcp-local metrics` serves it like `parrot-querysource`.
6. **Routing hook (core, M8).** `MetricRoutingMixin._resolve_output_mode()` — the
   cooperative slot FEAT-755 leaves open after the phrasing router abstains — plus
   `MetricSuggestionProvider` (FEAT-752).
7. **HTTP (server, M9).** `MetricDefinitionsHandler(BaseView)` mounted at
   `/api/v1/metrics[/{metric_id}]`.
8. **Wiring + docs (M10).** `TOOL_REGISTRY`, `bots/mixins/__init__.py` export, manager
   routes, `docs/outputs/metric-registry.md`.

Design decisions taken here (binding for `/sdd-task`):

- **D1 — separate `MetricRoutingMixin`, not a flag inside `IntentRouterMixin`.** The
  FEAT-224 mixin is the phrasing router and already chains `super()` on abstain
  (`intent_router.py:209-250`); the brainstorm feeding FEAT-755 pins the contract as
  *"FEAT-756 overrides the same method to return `(A2UI, hint)` from a matched metric's
  `default_shape`"* (`sdd/proposals/output-mode-intent-router.brainstorm.md:151-154`).
  A separate mixin keeps FEAT-224's tests byte-identical, needs no edit to
  `intent_router.py`, and makes precedence a plain MRO fact:
  `class X(IntentRouterMixin, MetricRoutingMixin, BasicAgent)`. The mixin warns at
  construction when `IntentRouterMixin` sits *after* it in the MRO (that order would
  let a metric outrank explicit phrasing).
- **D2 — the hook is feature-detected.** FEAT-755 has not landed (no
  `a2ui_component` / `component_hint` anywhere in the tree today). When its hint
  channel is present the mixin returns the FEAT-755 form; when it is absent the mixin
  **stashes the match and abstains** (returns `None`), so the toolkit lane
  (`query_metric`) still benefits and nothing can emit `OutputMode.A2UI` into a turn
  that has no inline emitter yet.
- **D3 — tenant comes from the same places skills take it.** Explicit kwarg →
  `ctx.kwargs["tenant"]` → bound ContextVar → instance default
  (`parrot/skills/mixin.py:135-150`). The registry never trusts a tenant from tool
  arguments on the HTTP lane; the handler sets it from `RequestScope.tenant`.
  *Amended (issue:a262cacba885):* the explicit kwarg is reserved for trusted host
  code. `MetricsToolkit` and `MetricRoutingMixin` call `resolve_metric_tenant` with
  `explicit=None` — a tenant supplied by the model in tool arguments is never
  honoured — so their order is `ctx.kwargs["tenant"]` → ContextVar → default.
- **D4 — `query_slug` is the only source kind that can be *linked*.** Linked surfaces
  carry a `LinkedDataSource(kind="query_slug")` (`linked/models.py:207`); `transformer`
  rides on it as `transform.python`; `recipe` has no linked descriptor (FEAT-598
  brainstorm Option C rejected) and stays a baked envelope with `recipe_name` for the
  FEAT-492 refresh lane.
- **D5 — HTTP writes in v1 are `POST` (create) and `PUT` (replace) gated by
  `scope.may_author`; `DELETE` is deferred.** A definition is small, self-contained
  JSON; the store's upsert already exists for the seed lane, so exposing create/replace
  costs one request model. Deleting a tenant's metric vocabulary from chat has no
  user story yet.

### Component Diagram
```
                    question (ask / conversation)
                               │
            ┌──────────────────▼───────────────────┐
            │ IntentRouterMixin._resolve_output_mode│  phrasing bank (FEAT-224)
            │   abstain → super()                   │
            └──────────────────┬───────────────────┘
                               │
            ┌──────────────────▼───────────────────┐
            │ MetricRoutingMixin._resolve_output_mode│  M8 (this spec)
            │   MetricRegistry.resolve(q, tenant)   │──▶ MetricMatch stashed
            │   hint channel present? → (A2UI, hint)│    (ctx.kwargs + ContextVar)
            │   else → None (abstain)               │
            └──────────────────┬───────────────────┘
                               │
            AbstractBot._resolve_output_mode (terminal no-op)
                               │
            _apply_default_output_mode → agent default

 MetricRegistry (M3) ──uses──▶ MetricView ──over──▶ MetricStore (M2 protocol)
        │                                             ├─ InMemoryMetricStore (M2)
        │ EmbeddingIntentRouter (labels = metric ids) └─ PgMetricDefinitionStore (M4)
        │                                                   ▲
        └── load_metrics_yaml / import_kpi_table (M2) ──────┘  seed lanes

 MetricsToolkit (M5): list_metrics · describe_metric · query_metric · explain_metric
        │
        ├─ SourceExecutor (M6): query_slug → QuerysourceToolkit.execute_slug / build_linked_surface
        │                       transformer → fetch + apply_python_transform (registry name)
        │                       recipe → RecipeRunner.run(include_envelope=True) + pointer
        ├─ periods.resolve_period / previous_period (M7)
        └─ ShapeEmitter (M7): build_surface("KPICard", …, origin=TOOL) | build_chart | build_datatable
                               → CreateSurface (baked) | linked envelope (query_slug only)

 MetricDefinitionsHandler (M9): GET/POST/PUT /api/v1/metrics[/{metric_id}] ── RequestScope → PgMetricDefinitionStore
 MetricSuggestionProvider (M8): MetricMatch → chips (FEAT-752)
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `AbstractBot._resolve_output_mode` (`bots/abstract.py:4168`) | overrides (cooperative MRO) | `MetricRoutingMixin` sits between `IntentRouterMixin` and the terminal no-op; call sites `base.py:300`, `base.py:1155`, `data.py:1350` are untouched |
| `IntentRouterMixin` (`bots/mixins/intent_router.py:123`) | precedes in MRO | its `super()._resolve_output_mode` on abstain reaches M8; no edit |
| `EmbeddingIntentRouter` (`registry/routing/embedding_router.py:57`) | uses | metric ids as route labels; `add_route` / `route` / `route_scores` are key-agnostic at runtime (dict keyed by whatever is passed) though annotated `OutputMode` — see §7 risk R1 |
| `IntentRouterConfig` (`registry/capabilities/models.py:149`) | reuses values | `embedding_model`, `output_mode_threshold`, `discrepancy_margin` default the registry matcher's settings |
| `RequestContext` (`utils/helpers.py:7`) | writes | `ctx.kwargs["metric_match"]`; reads `ctx.kwargs["tenant"]` |
| `SkillView` / tenancy helpers (`skills/tenancy.py:30,42,51,82,134`) | pattern + reuse | `validate_tenant_id`, `discover_tenant_dirs`, `current_skill_tenant`; `MetricView.compose()` applies the same C1–C6 shadowing rules |
| `SkillRegistryMixin._resolve_tenant` (`skills/mixin.py:135`) | pattern | the 4-step tenant resolution order is copied verbatim into `MetricRegistryMixin`-free helper `resolve_metric_tenant` |
| `QuerysourceToolkit` (`parrot_tools/querysource/toolkit.py:76`) | uses | `execute_slug` L253 (value/series), `describe_slug` L222 (placeholder validation at import), `build_linked_surface` L351 (linked KPI/Chart/Table) |
| `transformer_registry` / `apply_python_transform` (`a2ui/recipes/transformers.py:192`, `a2ui/linked/pytransform.py:94`) | uses | `transformer` source kind; `validate_python_transform` L36 at import time |
| `RecipeRunner.run` (`tools/infographic_recipes/runner.py:243`) | uses | `recipe` source kind; `include_envelope=True` then pointer read of `data_model` |
| `build_surface` / `build_chart` / `build_datatable` (`a2ui/builders.py:79,130,193`) | uses | shape emitter; KPICard props go through `build_surface("KPICard", props, origin=ProducerOrigin.TOOL)` because `build_kpicard` L151 has no `series` / `comparisonPeriod` / `higherIsBetter` |
| `KPICARD_SCHEMA` (`a2ui/catalog/parrot/kpicard.py:15`) | conforms to | `higher_is_better` tri-state maps 1:1 to `higherIsBetter`; `format` to `format` |
| `PublishSurfaceTool` / `InfographicAuthoringMixin.publish_surface` (`parrot_tools/ui_surfaces.py:65`, `bots/mixins/infographic_authoring.py:442`) | uses (optional) | `query_metric(pin=True)` forwards the envelope; linked envelopes pass `LinkedSurfaceService.validate_for_persistence` as today |
| `PgUISurfaceStore` (`handlers/models/ui_surfaces.py:457`) | mirrors | DDL list, `_exec`, `_get_db`, `_ensure_ready`, jsonb-as-native-object rule (L503-540) |
| `RequestScope` / `scope_grants` / `get_scope_resolver` (`handlers/scope.py:40,181,142`) | uses | PBAC on list/get; `may_author` on writes |
| `UISurfacesHandler` (`handlers/ui_surfaces.py:328`) | pattern | `BaseView`, app-cached store property, `_scope()`, `_error()` (L390) |
| `TOOL_REGISTRY` (`parrot_tools/__init__.py:13`) | extends | `"metrics": "parrot_tools.metrics.toolkit.MetricsToolkit"` |
| `parrot mcp-local` (`parrot/cli/__init__.py:116`) + `.parrot/mcp-toolkits.yaml:123` | operator step | a `metrics:` toolkit entry serves the four tools over MCP; not a code edit |
| `Agent.followup` (`bots/agent.py:1510`) | reuses pattern | `explain_metric` returns a deterministic definition + lineage text; a bot that wants prose calls `followup()` over it — no new LLM lane |
| FEAT-755 hint channel | consumes (assumed) | `_resolve_output_mode` → `(OutputMode.A2UI, component_hint)`; carrier re-pinned at task time (§8 Q1) |
| FEAT-752 `SuggestionProvider` | implements (assumed) | `MetricSuggestionProvider`; protocol import re-pinned at task time (§8 Q2) |

### Data Models
```python
# packages/ai-parrot/src/parrot/metrics/models.py  (new)
from typing import Annotated, Any, Literal
from datetime import datetime
from pydantic import BaseModel, Field, ConfigDict

MetricId = Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,62}$")]   # same grammar as skills_catalog tenant ids
Visibility = Literal["private", "tenant", "public"]
Grain = Literal["day", "week", "month", "quarter", "year"]
PeriodPreset = Literal["today", "yesterday", "this_week", "last_week", "this_month", "last_month", "mtd",
                       "qtd", "ytd", "last_7d", "last_30d", "last_90d", "this_year", "last_year"]

class DimensionSpec(BaseModel):
    """A breakdown axis ("by cost center")."""
    model_config = ConfigDict(extra="forbid")
    name: str                       # what users say
    column: str                     # column / placeholder in the source
    label: str | None = None
    aliases: list[str] = Field(default_factory=list)

class PeriodBinding(BaseModel):
    """How a resolved period reaches the source: two placeholders, or one date column for post-filtering."""
    model_config = ConfigDict(extra="forbid")
    start_placeholder: str | None = None   # e.g. "firstdate"
    end_placeholder: str | None = None     # e.g. "lastdate"
    date_column: str | None = None         # fallback: filter the returned frame
    @model_validator(mode="after")  # exactly one of (placeholders pair) | date_column

class TimeSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    grain: Grain = "month"
    default_period: PeriodPreset = "this_month"
    binding: PeriodBinding
    series_grain: Grain | None = "day"     # None → no sparkline `series`

class ComparisonPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["previous_period", "same_period_last_year", "none"] = "previous_period"
    label: str | None = None               # KPICard.comparisonPeriod; default derived ("vs last month")

class KPICardShape(BaseModel):
    model_config = ConfigDict(extra="forbid")
    component: Literal["KPICard"] = "KPICard"
    value_column: str                      # column holding the scalar (after aggregation)
    aggregate: Literal["sum", "avg", "min", "max", "count", "last", "first", "none"] = "sum"
    icon: str | None = None
    color: str | None = None

class ChartShape(BaseModel):
    model_config = ConfigDict(extra="forbid")
    component: Literal["Chart"] = "Chart"
    chart_type: Literal["line", "bar", "area", "pie"] = "line"
    x: str
    y: list[str]
    title: str | None = None

class DataTableShape(BaseModel):
    model_config = ConfigDict(extra="forbid")
    component: Literal["DataTable"] = "DataTable"
    columns: list[dict[str, Any]]          # TableColumn dicts as build_datatable takes them
    title: str | None = None

class MapShape(BaseModel):
    model_config = ConfigDict(extra="forbid")
    component: Literal["Map"] = "Map"
    lat: str
    lon: str
    label: str | None = None

ShapeSpec = Annotated[KPICardShape | ChartShape | DataTableShape | MapShape, Field(discriminator="component")]

class QuerySlugSource(BaseModel):
    """FEAT-558 request grammar, verbatim (toolkit.py:253-265)."""
    model_config = ConfigDict(extra="forbid")
    kind: Literal["query_slug"] = "query_slug"
    slug: str
    tenant: str | None = None              # QuerySource tenant store (routing, not security)
    placeholders: dict[str, Any] = Field(default_factory=dict)
    filter: dict[str, Any] = Field(default_factory=dict)
    fields: list[str] = Field(default_factory=list)
    ordering: list[str] = Field(default_factory=list)
    grouping: list[str] = Field(default_factory=list)
    limit: int | None = None

class TransformerSource(BaseModel):
    """`transform.python` lane: a query_slug frame fed to ONE registered transformer (single input alias)."""
    model_config = ConfigDict(extra="forbid")
    kind: Literal["transformer"] = "transformer"
    input: QuerySlugSource
    transformer: str                       # registered name — transformer_registry.get(name)
    params: dict[str, Any] = Field(default_factory=dict)
    input_alias: str = "source"
    output: str | None = None              # PythonTransform.output (frame selection)

class RecipeSource(BaseModel):
    """Flex lane: replay a published recipe and read one pointer of its data model."""
    model_config = ConfigDict(extra="forbid")
    kind: Literal["recipe"] = "recipe"
    recipe_name: str
    recipe_owner: str | None = None
    params: dict[str, Any] = Field(default_factory=dict)
    data_model_path: str                   # absolute JSON pointer, e.g. "/payroll_hero/worked_hours_total"
    param_map: dict[str, str] = Field(default_factory=dict)   # metric filter name → recipe param name

class SemanticMetricSource(BaseModel):
    """RESERVED for FEAT-704. Parses, lists and describes; execution raises MetricSourceUnavailable."""
    model_config = ConfigDict(extra="forbid")
    kind: Literal["semantic_metric"] = "semantic_metric"
    model: str
    metric: str

MetricSource = Annotated[QuerySlugSource | TransformerSource | RecipeSource | SemanticMetricSource,
                         Field(discriminator="kind")]

class MetricDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: MetricId
    name: str
    description: str = ""
    tenant: str | None = None              # None = global
    program: str | None = None
    aliases: list[str] = Field(default_factory=list)
    example_phrases: list[str] = Field(default_factory=list)
    unit: str | None = None
    format: Literal["percent", "currency", "number"] | None = None
    higher_is_better: bool | None = True   # True (default) | False | None — KPICard tri-state, kpicard.py:33-49
    dimensions: list[DimensionSpec] = Field(default_factory=list)
    time: TimeSpec
    comparison: ComparisonPolicy = Field(default_factory=ComparisonPolicy)
    default_shape: ShapeSpec
    source: MetricSource
    owner: str | None = None
    visibility: Visibility = "tenant"
    allowed_groups: list[str] = Field(default_factory=list)   # reserved, must be empty (issue:a262cacba885)
    global_only: bool = False              # skills semantics: a tenant tree may not shadow it
    version: int = 1
    created_at: datetime | None = None
    updated_at: datetime | None = None
    # validators: tenant → validate_tenant_id; visibility "public" requires tenant is None;
    #             default_shape.value_column/x/y must appear in source.fields when fields is non-empty.

class MetricMatch(BaseModel):
    """Result of MetricRegistry.resolve()."""
    model_config = ConfigDict(extra="forbid")
    metric: MetricDefinition
    score: float
    lane: Literal["alias", "embedding"]
    ambiguous: bool = False
    tenant: str | None = None
    requested_period: PeriodPreset | None = None     # parsed from the question when unambiguous ("this month")
    requested_dimension: str | None = None           # "by cost center" → dimension name

class ResolvedPeriod(BaseModel):
    """Concrete dates for one period (M7)."""
    model_config = ConfigDict(extra="forbid")
    preset: PeriodPreset
    start: date
    end: date
    label: str                                       # "October 2026", "last 30 days"
    udf_keywords: dict[str, str] | None = None       # {"firstdate": "FDOM", "lastdate": "LDOM"} when expressible
```

Persisted row (`navigator.metric_definitions`, M4): `metric_id VARCHAR(63)`,
`tenant VARCHAR(63) NULL`, `name TEXT`, `owner VARCHAR`, `visibility VARCHAR(16)`,
`allowed_groups JSONB`, `global_only BOOLEAN`, `program VARCHAR`, `definition JSONB`
(the whole `MetricDefinition.model_dump(mode="json")`), `version INTEGER`,
`created_at`, `updated_at`; `UNIQUE (tenant, metric_id)` plus a partial unique index on
`metric_id WHERE tenant IS NULL` (the `ai_skills_catalog` idiom,
`handlers/models/skills_catalog.py:34-50`); `CHECK (tenant IS NOT NULL OR visibility <> 'tenant')`.

### New Public Interfaces
```python
# parrot.metrics (core)
from parrot.metrics import (
    MetricDefinition, MetricMatch, MetricSource, ShapeSpec, ResolvedPeriod,
    MetricStore, InMemoryMetricStore, MetricRegistry, MetricView,
    load_metrics_yaml, import_kpi_table, resolve_metric_tenant,
    current_metric_match, bind_metric_match, reset_metric_match,
    MetricNotFound, MetricSourceUnavailable, MetricRegistryError,
)
from parrot.metrics.suggestions import MetricSuggestionProvider
from parrot.bots.mixins import MetricRoutingMixin

# parrot_tools.metrics (tools)
from parrot_tools.metrics import MetricsToolkit, QueryMetricResult

# parrot.handlers (server)
from parrot.handlers.models.metric_definitions import PgMetricDefinitionStore
from parrot.handlers.metric_definitions import MetricDefinitionsHandler
```

---

## 3. Module Breakdown

> Define the discrete modules that will be implemented.
> These directly map to Task Artifacts in Phase 2.

#### Delegation-eligible modules

Mark which modules can be implemented by the targeted writer from an
already-decided TASK packet. Architecture decisions always stay with the
thinking model; eligibility only means "the design is complete enough that
writing the code is mechanical".

| Module | Eligible? | Decided patterns / exact contracts | Why not (if no) |
|---|---|---|---|
| M1: Definition models | yes | Every field, union discriminator and validator is fixed in §2 Data Models; pure Pydantic, no I/O | — |
| M2: Stores + seed lanes | yes | `MetricStore` protocol fixed below; `InMemoryMetricStore` is a dict; YAML layout fixed (§7); `kpi-table.md` column order fixed (§7) | — |
| M3: Registry + matching | partial | `MetricView` shadowing rules = `SkillView` C1–C6 verbatim; alias fast path fixed | Embedding lane depends on how FEAT-755 widens `EmbeddingIntentRouter` labels (R1) — the task packet must pin the call form |
| M4: Postgres store | yes | DDL fixed in §2; method set = the protocol; AsyncDB idiom copied from `PgUISurfaceStore` | — |
| M5: `MetricsToolkit` | yes | Four tool signatures + docstrings fixed below; result models fixed | — |
| M6: Source executors | partial | `query_slug` and `recipe` are mechanical over verified signatures | `transformer` lane must mirror `LinkedSurfaceService.fetch_source` semantics; one design read required |
| M7: Periods + shapes | yes | Preset table and KPICard prop mapping fixed in §7 | — |
| M8: Routing mixin + suggestions | no | Hook carrier (FEAT-755) and chip model (FEAT-752) are external contracts not yet in the tree | §8 Q1, Q2 must be resolved first |
| M9: HTTP handler | yes | Routes, request models, status codes fixed below; handler idiom = `UISurfacesHandler` | — |
| M10: Wiring + docs | yes | Three one-line edits + one doc page | — |

### Module 1: Definition models
- **Path**: `packages/ai-parrot/src/parrot/metrics/__init__.py`, `packages/ai-parrot/src/parrot/metrics/models.py`, `packages/ai-parrot/src/parrot/metrics/errors.py`
- **Responsibility**: the `MetricDefinition` family (§2 Data Models), `MetricMatch`, `ResolvedPeriod`, the three exceptions; JSON-schema export for docs/HTTP.
- **Depends on**: `pydantic`; `parrot.skills.tenancy.validate_tenant_id` (`tenancy.py:30`) for the tenant validator. No other parrot import (keeps `parrot.metrics` importable without the a2ui chain).
- **Interface Skeleton** *(signatures + docstrings only — bodies belong to task blueprints, FEAT-545)*:
  ```python
  # packages/ai-parrot/src/parrot/metrics/errors.py  (new)
  class MetricRegistryError(Exception):
      """Base error of the metric registry."""
  class MetricNotFound(MetricRegistryError):
      """No definition with that id is visible to the caller."""
  class MetricSourceUnavailable(MetricRegistryError):
      """The source kind is declared but cannot run here (e.g. ``semantic_metric``, FEAT-704)."""

  # packages/ai-parrot/src/parrot/metrics/models.py  (new) — classes as in §2 Data Models, plus:
  class MetricDefinition(BaseModel):
      """A tenant-scoped metric: vocabulary, semantics, default shape and executable source."""
      def matching_terms(self) -> list[str]:
          """Return ``[name] + aliases + example_phrases`` de-duplicated, lower-cased, order-preserving."""
      def dimension(self, name_or_alias: str) -> DimensionSpec | None:
          """Return the dimension whose name or alias equals ``name_or_alias`` (case-insensitive), else ``None``."""
      def shadow_key(self) -> str:
          """Return ``self.id`` — the key a tenant definition shadows a global one by (``SkillView`` C1)."""
      @classmethod
      def json_schema_v1(cls) -> dict[str, Any]:
          """Return the JSON Schema served by ``GET /api/v1/metrics/schema`` and written to docs."""
  ```

### Module 2: Stores + seed/import lanes
- **Path**: `packages/ai-parrot/src/parrot/metrics/store.py`, `packages/ai-parrot/src/parrot/metrics/loader.py`, `packages/ai-parrot/src/parrot/metrics/importers.py`
- **Responsibility**: the `MetricStore` protocol every backend implements; `InMemoryMetricStore`; `load_metrics_yaml` (agent dir + FEAT-707 tenant trees); `import_kpi_table` (Flex `kpi-table.md` → recipe-sourced definitions).
- **Depends on**: M1; `yaml` (already a core dependency — `a2ui/recipes/store.py:33`, `recipes/models.py:19`); `parrot.skills.tenancy.discover_tenant_dirs` (`tenancy.py:51`) and `tenant_skills_dir` (`tenancy.py:42`) — the tenant *metrics* path is the sibling `agent_root/tenants/{tenant}/metrics.yaml`, built with the same `secure_path` containment; `parrot.conf.AGENTS_DIR` (`conf.py:181`).
- **Interface Skeleton** *(signatures + docstrings only — bodies belong to task blueprints, FEAT-545)*:
  ```python
  # packages/ai-parrot/src/parrot/metrics/store.py  (new)
  class MetricStore(Protocol):
      """Persistence boundary. Tenancy is explicit on every call; ``tenant=None`` means the global namespace."""
      async def get(self, metric_id: str, *, tenant: str | None) -> MetricDefinition | None:
          """Return one definition in exactly that namespace, or ``None``."""
      async def list(self, *, tenant: str | None, program: str | None = None) -> list[MetricDefinition]:
          """Return every definition of one namespace (no visibility filtering — that is the registry's job)."""
      async def save(self, definition: MetricDefinition, *, overwrite: bool = False) -> str:
          """Insert (or upsert when ``overwrite``) and return ``definition.id``; raises ``ValueError`` on a duplicate."""
      async def delete(self, metric_id: str, *, tenant: str | None) -> bool:
          """Remove one definition; ``True`` when a row was removed."""

  class InMemoryMetricStore:
      """Dict-backed ``MetricStore`` for tests, notebooks and agents without Postgres."""
      def __init__(self, definitions: Iterable[MetricDefinition] = ()) -> None:
          """Pre-load ``definitions`` (duplicates raise ``ValueError``)."""
      # get / list / save / delete as the protocol

  # packages/ai-parrot/src/parrot/metrics/loader.py  (new)
  class MetricsYamlReport(BaseModel):
      """Configure-time audit of one YAML file (loaded ids, dropped entries with reasons) — ``TenantTreeReport`` twin."""
  def load_metrics_yaml(path: Path, *, tenant: str | None = None, logger: logging.Logger | None = None,
                        ) -> tuple[list[MetricDefinition], MetricsYamlReport]:
      """Parse ``metrics.yaml`` (top-level ``metrics: [ … ]``). ``tenant`` is FORCED onto every entry
      (a tenant file cannot declare another tenant, nor ``global_only``); invalid entries are dropped and
      reported, never raised — a bad row must not take the agent down."""
  def load_agent_metrics(agent_root: Path, *, logger: logging.Logger | None = None,
                         ) -> dict[str | None, list[MetricDefinition]]:
      """Return ``{None: global defs, "<tenant>": tenant defs, …}`` from ``agent_root/metrics.yaml`` and every
      ``agent_root/tenants/<t>/metrics.yaml`` found by ``discover_tenant_dirs`` (tenancy.py:51)."""
  async def seed_store(store: MetricStore, definitions: Mapping[str | None, Iterable[MetricDefinition]],
                       *, overwrite: bool = False) -> int:
      """Persist loaded definitions; returns the number written. Idempotent with ``overwrite=True``."""

  # packages/ai-parrot/src/parrot/metrics/importers.py  (new)
  class KpiTableRow(BaseModel):
      """One row of the Flex ``kpi-table.md`` table: kpi, transformer, dataset_aliases, recipe_path, output_mode, filters."""
  def parse_kpi_table(markdown: str) -> list[KpiTableRow]:
      """Parse the 6-column GFM table (header ``| KPI | Transformer | Dataset alias(es) | Recipe path | Output mode | Supported filters |``)."""
  def import_kpi_table(markdown: str, *, recipe_name: str, recipe_owner: str | None, tenant: str | None,
                       program: str | None = None, period_param: str = "month") -> list[MetricDefinition]:
      """Convert rows to ``RecipeSource`` definitions: ``KPICard hero`` → ``KPICardShape``, ``STRUCTURED_CHART`` →
      ``ChartShape(line)``, ``STRUCTURED_TABLE`` → ``DataTableShape``, ``STRUCTURED_MAP`` → ``MapShape``; the
      ``Supported filters`` cell becomes ``dimensions`` (minus the period filter, which becomes ``TimeSpec``)."""
  ```

### Module 3: Registry service + matching + tenant views
- **Path**: `packages/ai-parrot/src/parrot/metrics/registry.py`, `packages/ai-parrot/src/parrot/metrics/matching.py`, `packages/ai-parrot/src/parrot/metrics/context.py`
- **Responsibility**: `MetricView` (global ∪ tenant overlay, `SkillView` rules), `MetricRegistry` (list/describe/resolve over a `MetricStore` + optional seed definitions), `MetricMatcher` (lexical fast path + embedding lane), the match ContextVar.
- **Depends on**: M1, M2; `EmbeddingIntentRouter` (`registry/routing/embedding_router.py:57`, `add_route` L108, `route` L152, `route_scores` L125); `IntentRouterConfig` defaults (`capabilities/models.py:216-238`); `current_skill_tenant` (`tenancy.py:82`) and the `_resolve_tenant` order (`skills/mixin.py:135-150`).
- **Interface Skeleton** *(signatures + docstrings only — bodies belong to task blueprints, FEAT-545)*:
  ```python
  # packages/ai-parrot/src/parrot/metrics/context.py  (new) — tenancy.py:82-95 pattern
  def current_metric_match() -> MetricMatch | None:
      """Return the match bound to the current task, or ``None``."""
  def bind_metric_match(match: MetricMatch | None) -> Token:
      """Bind ``match`` for the current task; returns the reset token."""
  def reset_metric_match(token: Token) -> None:
      """Undo ``bind_metric_match``."""
  def resolve_metric_tenant(explicit: str | None = None, ctx: Any | None = None, default: str | None = None) -> str | None:
      """explicit → ``ctx.kwargs["tenant"]`` → ``current_skill_tenant()`` → ``default``; validates the first
      non-empty candidate with ``validate_tenant_id`` (skills/mixin.py:135-150 order, verbatim)."""

  # packages/ai-parrot/src/parrot/metrics/registry.py  (new)
  class MetricView:
      """Read-only overlay of a tenant namespace over the global one (SkillView twin, tenancy.py:134)."""
      def __init__(self, global_defs: Sequence[MetricDefinition], tenant_defs: Sequence[MetricDefinition] = (),
                   *, tenant: str | None = None, logger: logging.Logger | None = None) -> None: ...
      def compose(self) -> "MetricView":
          """C1 tenant shadows global by id; C2 by alias collision (tenant wins, global alias dropped);
          C3 ``global_only`` global drops the tenant entry with a warning; C5/C6 single-namespace views."""
      def get(self, metric_id: str) -> MetricDefinition | None: ...
      def list(self, *, program: str | None = None) -> list[MetricDefinition]: ...
      def terms(self) -> dict[str, list[str]]:
          """``{metric_id: matching_terms()}`` — the matcher's bank."""

  class MetricRegistry:
      """List / describe / resolve metrics for one agent, tenant-aware."""
      def __init__(self, store: MetricStore, *, matcher: "MetricMatcher | None" = None, default_tenant: str | None = None,
                   visibility_filter: Callable[[MetricDefinition], bool] | None = None, logger: logging.Logger | None = None) -> None:
          """``matcher=None`` builds a default ``MetricMatcher`` lazily on first ``resolve``."""
      async def view(self, tenant: str | None) -> MetricView:
          """Compose (and cache per tenant until ``invalidate``) the view for ``tenant``."""
      async def list(self, *, tenant: str | None = None, program: str | None = None) -> list[MetricDefinition]: ...
      async def describe(self, metric_id: str, *, tenant: str | None = None) -> MetricDefinition:
          """Raises ``MetricNotFound``."""
      async def resolve(self, question: str, *, tenant: str | None = None) -> MetricMatch | None:
          """Alias fast path, then the embedding lane; ``None`` below threshold. Never raises on matcher failure
          (logs and abstains) — a registry must never break a turn."""
      def invalidate(self, tenant: str | None = None) -> None:
          """Drop the cached view (and its route bank) for one tenant, or all."""

  # packages/ai-parrot/src/parrot/metrics/matching.py  (new)
  class MetricMatcher:
      """Phrase → metric id. Lexical first (exact / word-boundary contains on normalized terms), then embeddings."""
      def __init__(self, *, embedding_model: str = "intfloat/multilingual-e5-small", threshold: float = 0.85,
                   margin: float = 0.05, enable_embeddings: bool = True) -> None:
          """Defaults equal ``IntentRouterConfig`` (capabilities/models.py:216-238) so one calibration serves both routers."""
      def configure(self, bank: Mapping[str, Sequence[str]]) -> None:
          """Encode ``{metric_id: terms}`` once (``EmbeddingIntentRouter.add_route`` per id — embedding_router.py:108);
          replaces any previous bank."""
      def match(self, question: str) -> tuple[str, float, str, bool] | None:
          """Return ``(metric_id, score, lane, ambiguous)`` or ``None``. CPU-bound: callers use ``asyncio.to_thread``
          exactly like ``IntentRouterMixin`` (intent_router.py:209-250)."""
      @staticmethod
      def parse_period(question: str) -> PeriodPreset | None:
          """Small EN/ES lexicon: "this month"/"este mes" → this_month, "last month"/"mes pasado" → last_month, "ytd", …"""
      @staticmethod
      def parse_dimension(question: str, dimensions: Sequence[DimensionSpec]) -> str | None:
          """"by <dimension-or-alias>" / "por <…>" → dimension name."""
  ```

### Module 4: Postgres store (server)
- **Path**: `packages/ai-parrot-server/src/parrot/handlers/models/metric_definitions.py`
- **Responsibility**: `PgMetricDefinitionStore` implementing M2's protocol over `navigator.metric_definitions`, plus `list_visible(scope)` for the HTTP lane.
- **Depends on**: M1, M2; `asyncdb.AsyncDB`, `parrot.conf.default_dsn` (as `handlers/models/ui_surfaces.py:29-30`); `RequestScope` + `scope_grants` (`handlers/scope.py:40,181`). Mirrors `PgUISurfaceStore` (`ui_surfaces.py:457-560`): `_DDL_STATEMENTS` list, `_exec` (L438), `_get_db` (L474), `_ensure_ready` (L478), `ensure_schema` race tolerance (L483-501), jsonb passed as native objects (L524-534 note).
- **Interface Skeleton** *(signatures + docstrings only — bodies belong to task blueprints, FEAT-545)*:
  ```python
  # packages/ai-parrot-server/src/parrot/handlers/models/metric_definitions.py  (new)
  _DDL_STATEMENTS: list[str]   # CREATE SCHEMA navigator; CREATE TABLE navigator.metric_definitions (§2); indexes:
                               #   UNIQUE (tenant, metric_id); partial UNIQUE (metric_id) WHERE tenant IS NULL;
                               #   (tenant, visibility); (program)

  class PgMetricDefinitionStore:
      """Postgres ``MetricStore`` (PgUISurfaceStore idiom — handlers/models/ui_surfaces.py:457)."""
      def __init__(self, dsn: str | None = None) -> None:
          """``dsn`` defaults to ``parrot.conf.default_dsn``."""
      def _get_db(self) -> AsyncDB:
          """Fresh ``AsyncDB("pg", dsn=self.dsn)`` per call (ui_surfaces.py:474)."""
      async def ensure_schema(self) -> None:
          """Idempotent DDL; tolerates "already exists" races (ui_surfaces.py:483-501)."""
      async def get(self, metric_id: str, *, tenant: str | None) -> MetricDefinition | None: ...
      async def list(self, *, tenant: str | None, program: str | None = None) -> list[MetricDefinition]: ...
      async def save(self, definition: MetricDefinition, *, overwrite: bool = False) -> str:
          """INSERT … ON CONFLICT DO NOTHING / DO UPDATE; ``definition`` column stored as a native dict (never json.dumps)."""
      async def delete(self, metric_id: str, *, tenant: str | None) -> bool: ...
      async def list_visible(self, scope: RequestScope, *, program: str | None = None) -> list[MetricDefinition]:
          """Global ``public`` rows ∪ rows of ``scope.tenant`` that ``scope_grants`` (handlers/scope.py:181) accepts
          (owner rows always; ``is_superuser`` sees every row of the tenant)."""
  ```

### Module 5: `MetricsToolkit`
- **Path**: `packages/ai-parrot-tools/src/parrot_tools/metrics/__init__.py`, `packages/ai-parrot-tools/src/parrot_tools/metrics/toolkit.py`, `packages/ai-parrot-tools/src/parrot_tools/metrics/models.py`
- **Responsibility**: the four LLM/MCP-facing tools; tenant resolution per D3; result models.
- **Depends on**: M1, M3, M6, M7; `AbstractToolkit` (`parrot/tools/toolkit.py:225`; `exclude_tools` L262, `tool_prefix` L276, `get_tools` L522); `QuerysourceToolkit` (`parrot_tools/querysource/toolkit.py:76`) injected or built from kwargs; `PublishSurfaceTool` (`parrot_tools/ui_surfaces.py:65`) for `pin=True`.
- **Interface Skeleton** *(signatures + docstrings only — bodies belong to task blueprints, FEAT-545)*:
  ```python
  # packages/ai-parrot-tools/src/parrot_tools/metrics/models.py  (new)
  class MetricSummary(BaseModel):
      """id, name, unit, default_component, tenant, program, dimensions (names), source_kind."""
  class MetricExplanation(BaseModel):
      """definition (MetricDefinition), lineage: str (deterministic prose: source, filters, period, comparison, shape),
      source_detail: SlugDetail | TransformerManifest | dict | None."""
  class QueryMetricResult(BaseModel):
      """metric_id, period: ResolvedPeriod, comparison_period: ResolvedPeriod | None, value: Any, previous: Any | None,
      delta: float | None, delta_pct: float | None, trend: Literal["up","down","flat"] | None, rows: list[dict] (≤ max_rows),
      envelope: dict (CreateSurface, TOOL origin), linked: bool, surface_id: str | None (when pinned), duration_ms: int."""

  # packages/ai-parrot-tools/src/parrot_tools/metrics/toolkit.py  (new)
  class MetricsToolkit(AbstractToolkit):   # AbstractToolkit verified: parrot/tools/toolkit.py:225
      """Tenant-scoped metric registry tools: list, describe, query (default-shape A2UI envelope) and explain."""
      exclude_tools: tuple[str, ...] = ("open", "close")
      def __init__(self, registry: MetricRegistry | None = None, *, store: MetricStore | None = None,
                   querysource: QuerysourceToolkit | None = None, recipe_runner: RecipeRunner | None = None,
                   pctx_provider: Callable[[], Any] | None = None, default_tenant: str | None = None,
                   max_rows: int = 200, allow_pin: bool = True, publish_tool: PublishSurfaceTool | None = None,
                   **kwargs: Any) -> None:
          """``registry`` wins over ``store``; when both are ``None`` an empty ``InMemoryMetricStore`` is used (zero
          behaviour: every tool answers "no metrics configured"). ``querysource`` defaults to
          ``QuerysourceToolkit(**kwargs.pop("querysource_kwargs", {}))`` lazily on first use."""
      async def list_metrics(self, search: str | None = None, program: str | None = None, tenant: str | None = None) -> list[MetricSummary]:
          """List the metrics visible in this tenant. `search` filters name/aliases/description (case-insensitive).
          `tenant` is routing only; omit it to use the request's tenant."""
      async def describe_metric(self, metric_id: str, tenant: str | None = None) -> MetricDefinition:
          """Return the full definition of one metric (source, unit, dimensions, default period and shape)."""
      async def query_metric(self, metric_id: str, period: PeriodPreset | None = None, by: str | None = None,
                             filters: dict[str, Any] | None = None, compare: bool | None = None,
                             shape: Literal["KPICard", "Chart", "DataTable", "Map"] | None = None,
                             linked: bool = False, pin: bool = False, title: str | None = None,
                             tenant: str | None = None) -> QueryMetricResult:
          """Execute a metric from its declared source and return its value plus a ready A2UI envelope in the
          metric's default shape (override with `shape`). `period` defaults to the metric's default period;
          `by` breaks the metric down by one declared dimension (switches the shape to Chart/DataTable);
          `compare` applies the comparison policy (delta/trend vs the previous period); `linked=True`
          emits a refreshable linked surface (query_slug/transformer sources only); `pin=True` persists it
          to the ui_surfaces plane and returns `surface_id`."""
      async def explain_metric(self, metric_id: str, tenant: str | None = None) -> MetricExplanation:
          """Explain how a metric is computed: its source (slug / transformer / recipe), filters, period and
          comparison policy, unit and why the default shape was chosen. Deterministic — no LLM call."""
      async def _pre_execute(self, tool_name: str, /, **kwargs: Any) -> None:   # pattern: querysource/toolkit.py:860
          """Resolve the effective tenant (D3) and stash it for the call; reject an explicit tenant that fails validation."""
  ```

### Module 6: Source executors
- **Path**: `packages/ai-parrot-tools/src/parrot_tools/metrics/executors.py`
- **Responsibility**: turn a `MetricDefinition` + `ResolvedPeriod` + optional dimension/filters into a frame (and, for `query_slug`, a linked descriptor); one executor per source kind; `semantic_metric` raises `MetricSourceUnavailable`.
- **Depends on**: M1, M7; `QuerysourceToolkit.execute_slug` (`toolkit.py:253`), `describe_slug` (L222), `build_linked_surface` (L351); `transformer_registry.get` (`recipes/transformers.py:148`), `validate_python_transform` / `apply_python_transform` (`linked/pytransform.py:36,94`), `PythonTransform` (`linked/models.py:178`); `RecipeRunner.run` (`runner.py:243`); `pandas`.
- **Interface Skeleton** *(signatures + docstrings only — bodies belong to task blueprints, FEAT-545)*:
  ```python
  # packages/ai-parrot-tools/src/parrot_tools/metrics/executors.py  (new)
  class SourceFrame(BaseModel):
      """frame rows (list[dict]), columns, applied_conditions, truncated, linked_request: dict | None
      (the `request` dict `build_linked_surface` accepts — toolkit.py:351-372 — when the source can be linked)."""

  class SourceExecutor(Protocol):
      async def fetch(self, definition: MetricDefinition, *, period: ResolvedPeriod, dimension: DimensionSpec | None,
                      filters: Mapping[str, Any], tenant: str | None) -> SourceFrame:
          """Fetch the rows for one period. Raises ``MetricSourceUnavailable`` / ``QuerysourceToolkitError`` as-is."""

  class QuerySlugExecutor:
      """``query_slug``: placeholders ← period binding (ISO dates), filters ← `filter` grammar, grouping ← dimension."""
      def __init__(self, querysource: QuerysourceToolkit) -> None: ...
      async def fetch(...) -> SourceFrame:
          """``execute_slug(slug, placeholders, filter, fields, ordering, grouping, limit, tenant)`` — toolkit.py:253-265."""
      def linked_request(self, definition: MetricDefinition, *, period: ResolvedPeriod) -> dict[str, Any]:
          """Request dict for ``build_linked_surface``: UDF keywords when ``period.udf_keywords`` is set, else ISO
          dates as ``locked`` params (§7 'Linked periods')."""

  class TransformerExecutor:
      """``transformer``: ``QuerySlugExecutor.fetch(input)`` then ``apply_python_transform`` by registered name."""
      def __init__(self, querysource: QuerysourceToolkit, *, max_rows: int = 5000) -> None: ...
      async def fetch(...) -> SourceFrame:
          """Validates with ``validate_python_transform`` first (registry membership, single input alias — pytransform.py:36-52)."""

  class RecipeExecutor:
      """``recipe``: ``RecipeRunner.run(name, params=…, pctx=…, recipe_owner=…, include_envelope=True)`` (runner.py:243-250),
      then read ``source.data_model_path`` from the rendered envelope's ``dataModel``."""
      def __init__(self, runner: RecipeRunner, *, pctx_provider: Callable[[], Any]) -> None:
          """``pctx_provider`` must return a real ``PermissionContext`` — ``RecipeRunner.run`` fails OPEN on a falsy pctx
          (agents/flex_dashboard.py RefreshDashboardTool docstring); the executor refuses to run when it returns ``None``."""
      async def fetch(...) -> SourceFrame:
          """A scalar at the pointer → one-row frame ``{value_column: scalar}``; a list → rows; a dict of lists → frame."""

  def executor_for(source: MetricSource, *, querysource: QuerysourceToolkit | None, runner: RecipeRunner | None,
                   pctx_provider: Callable[[], Any] | None) -> SourceExecutor:
      """Dispatch on ``source.kind``; ``semantic_metric`` → raises ``MetricSourceUnavailable`` (reserved for FEAT-704)."""
  ```

### Module 7: Periods + shape emitter
- **Path**: `packages/ai-parrot-tools/src/parrot_tools/metrics/periods.py`, `packages/ai-parrot-tools/src/parrot_tools/metrics/shapes.py`
- **Responsibility**: resolve `PeriodPreset` → `ResolvedPeriod` (+ previous / same-period-last-year); aggregate the frame to the KPI scalar; compute delta/trend; build the KPICard / Chart / DataTable / Map envelope (TOOL origin) and, for linkable sources, the linked variant.
- **Depends on**: M1, M6; `build_surface` (`builders.py:79`), `build_chart` (L130), `build_datatable` (L193), `ProducerOrigin` (`catalog/base.py:99`), `KPICARD_SCHEMA` (`kpicard.py:15`); `QuerysourceToolkit.build_linked_surface` (`toolkit.py:351`); `RefreshPolicy` (`linked/models.py:43`).
- **Interface Skeleton** *(signatures + docstrings only — bodies belong to task blueprints, FEAT-545)*:
  ```python
  # packages/ai-parrot-tools/src/parrot_tools/metrics/periods.py  (new)
  def resolve_period(preset: PeriodPreset, *, today: date | None = None, grain: Grain = "month") -> ResolvedPeriod:
      """Concrete ``start``/``end`` (inclusive) for the preset; sets ``udf_keywords`` only for presets the closed
      7-keyword QuerySource vocabulary can express: this_month → FDOM/LDOM, today → TODAY, yesterday → YESTERDAY,
      ytd/this_year → CURRENT_YEAR, last_year → LAST_YEAR; every other preset → ``None``."""
  def comparison_period(period: ResolvedPeriod, policy: ComparisonPolicy) -> ResolvedPeriod | None:
      """previous_period → same length immediately before; same_period_last_year → shifted one year; none → ``None``."""
  def series_buckets(period: ResolvedPeriod, grain: Grain) -> list[date]:
      """Zero-fill skeleton for KPICard ``series`` ([{date, value}], sorted)."""

  # packages/ai-parrot-tools/src/parrot_tools/metrics/shapes.py  (new)
  class KPIFigures(BaseModel):
      """value, previous, delta, delta_pct, trend, comparison_label, series: list[dict] | None."""
  def aggregate(frame_rows: Sequence[Mapping[str, Any]], shape: KPICardShape) -> Any:
      """Apply ``shape.aggregate`` to ``shape.value_column``; ``none`` requires exactly one row."""
  def figures(current: Any, previous: Any | None, *, policy: ComparisonPolicy, period: ResolvedPeriod,
              comparison: ResolvedPeriod | None, series: list[dict] | None) -> KPIFigures:
      """delta = current - previous; delta_pct guarded for previous == 0 (``None``); trend from the sign with a
      0.5 % flat band."""
  def kpicard_props(definition: MetricDefinition, fig: KPIFigures) -> dict[str, Any]:
      """label/value/unit/format/delta/trend/comparisonPeriod/higherIsBetter/icon/color/series — ONLY keys present in
      ``KPICARD_SCHEMA`` (kpicard.py:15); ``higherIsBetter`` omitted when ``higher_is_better is True`` (schema: omitted
      means yes), ``null`` when ``None`` (tri-state, kpicard.py:33-49)."""
  def build_metric_envelope(definition: MetricDefinition, *, shape: ShapeSpec, fig: KPIFigures | None,
                            rows: Sequence[Mapping[str, Any]], surface_id: str, title: str | None) -> CreateSurface:
      """Baked TOOL-origin envelope: KPICard via ``build_surface("KPICard", props, origin=ProducerOrigin.TOOL)``
      (builders.py:79); Chart via ``build_chart`` (L130) with ``data_model={"rows": rows}``; DataTable via
      ``build_datatable`` (L193); Map via ``build_surface("Map", …)``."""
  async def build_linked_metric_envelope(querysource: QuerysourceToolkit, definition: MetricDefinition, *,
                                         shape: ShapeSpec, request: dict[str, Any], comparison_request: dict[str, Any] | None,
                                         refresh: RefreshPolicy, snapshot: bool, surface_id: str | None) -> dict[str, Any]:
      """``query_slug``/``transformer`` only: ``build_linked_surface(slug, component, request=…, tenant=…, snapshot=…,
      refresh=…, transform=…)`` (toolkit.py:351-372); KPICard ``value`` binds to the live source, the comparison value
      (when any) to a second source keyed ``previous`` with ``locked`` ISO dates (§7)."""
  ```

### Module 8: `MetricRoutingMixin` + `MetricSuggestionProvider`
- **Path**: `packages/ai-parrot/src/parrot/bots/mixins/metric_routing.py`, `packages/ai-parrot/src/parrot/metrics/suggestions.py`
- **Responsibility**: the cooperative `_resolve_output_mode()` slot (D1, D2); stash the `MetricMatch`; the FEAT-752 provider.
- **Depends on**: M1, M3; `AbstractBot._resolve_output_mode` terminal (`abstract.py:4168`); `RequestContext` (`helpers.py:7`, `kwargs` L36, `output_mode` L41, `intent_score` L42); `OutputMode` (`models/outputs.py:23`, `A2UI` L55); **FEAT-755** hint channel (assumed); **FEAT-752** `SuggestionProvider` protocol (assumed).
- **Interface Skeleton** *(signatures + docstrings only — bodies belong to task blueprints, FEAT-545)*:
  ```python
  # packages/ai-parrot/src/parrot/bots/mixins/metric_routing.py  (new)
  class MetricRoutingMixin:
      """Metric default-shape slot of the output-mode chain: explicit > router (phrasing) > METRIC > agent default.

      MRO contract: ``class X(IntentRouterMixin, MetricRoutingMixin, BasicAgent)`` — ``IntentRouterMixin`` chains
      ``super()`` only when it abstains (intent_router.py:209-250), so this hook never outranks phrasing.
      """
      metric_registry: MetricRegistry | None = None
      metric_route_threshold: float | None = None       # None → registry matcher's own threshold
      def __init__(self, **kwargs: Any) -> None:
          """Pops ``metric_registry`` / ``metric_route_threshold``; warns when ``IntentRouterMixin`` follows this
          class in ``type(self).__mro__`` (precedence would invert)."""
      def configure_metric_router(self, registry: MetricRegistry, *, threshold: float | None = None) -> None:
          """Attach (or replace) the registry after construction."""
      async def _resolve_output_mode(self, query: str, ctx: Any) -> Any:   # Optional[OutputMode] | FEAT-755 form
          """No registry → ``super()``. Otherwise ``registry.resolve(query, tenant=resolve_metric_tenant(None, ctx, …))``
          off the event loop; no match → ``super()``. On a match: stash ``MetricMatch`` in ``ctx.kwargs["metric_match"]``
          and the ContextVar, mirror ``ctx.intent_score``; if the FEAT-755 hint channel is available return the
          FEAT-755 form for ``(OutputMode.A2UI, match.metric.default_shape.component)``; else return ``super()``
          (D2 — the toolkit lane still sees the match). Never raises."""
      def _hint_channel_available(self) -> bool:
          """Feature detection of the FEAT-755 channel (exact probe pinned at task time, §8 Q1)."""

  # packages/ai-parrot/src/parrot/metrics/suggestions.py  (new)
  class MetricSuggestionProvider:   # implements FEAT-752 SuggestionProvider (assumed protocol — §8 Q2)
      """Chips derived from the stashed ``MetricMatch``: "vs previous period" (when policy ≠ none and the turn did not
      compare), "by <dimension>" per declared dimension (max 3), "as <other shape>" (Chart ↔ KPICard ↔ DataTable)."""
      def __init__(self, *, max_chips: int = 5) -> None: ...
      async def suggest(self, *, question: str, response: Any, ctx: Any) -> list[Any]:
          """Return chips (FEAT-752 chip model) or ``[]`` when no match is stashed. Each chip's prompt is a complete
          follow-up sentence ("Show worked hours by cost center") so it re-enters the same resolver."""
  ```

### Module 9: HTTP handler (server)
- **Path**: `packages/ai-parrot-server/src/parrot/handlers/metric_definitions.py`
- **Responsibility**: `GET /api/v1/metrics` (list visible, `?program=`), `GET /api/v1/metrics/schema`, `GET /api/v1/metrics/{metric_id}`, `POST /api/v1/metrics` (create), `PUT /api/v1/metrics/{metric_id}` (replace); tenant set from scope, never from the body.
- **Depends on**: M1, M4; `BaseView` (`navigator.views`), `get_scope_resolver` (`handlers/scope.py:142`), `RequestScope` (L40), `_get_user_id` idiom (`handlers/ui_surfaces.py:134`), `_error` idiom (L390), app-cached store (L344).
- **Interface Skeleton** *(signatures + docstrings only — bodies belong to task blueprints, FEAT-545)*:
  ```python
  # packages/ai-parrot-server/src/parrot/handlers/metric_definitions.py  (new)
  class UpsertMetricRequest(BaseModel):
      """``definition: dict`` — a ``MetricDefinition`` WITHOUT ``tenant`` / ``owner`` (server-set; 422 when present)."""

  class MetricDefinitionsHandler(BaseView):   # BaseView verified: handlers/ui_surfaces.py:26,328
      """REST lane of the metric registry (UISurfacesHandler idiom: one view, dispatch on match_info/path)."""
      _logger_name: str = "Parrot.MetricDefinitions"
      def post_init(self, *args: Any, **kwargs: Any) -> None: ...
      @property
      def store(self) -> PgMetricDefinitionStore:
          """``app["metric_definitions_store"]`` or a lazily created ``PgMetricDefinitionStore()``."""
      async def _scope(self) -> RequestScope:
          """``get_scope_resolver(self.request.app).resolve(self.request)`` — once per request (ui_surfaces.py:381-388)."""
      def _error(self, message: str, *, status: int = 400) -> web.Response:
          """Direct ``json_response`` (ui_surfaces.py:390-404 rationale)."""
      async def get(self) -> web.Response:
          """``/schema`` → JSON Schema; ``{metric_id}`` → 200 | 404 (never 403 — existence is not disclosed);
          list → ``store.list_visible(scope, program=)``."""
      async def post(self) -> web.Response:
          """Create: 403 unless ``scope.may_author``; 401 without user; tenant := ``scope.tenant`` (a global definition
          needs ``scope.is_superuser``); 409 on duplicate; 201 with the stored definition."""
      async def put(self) -> web.Response:
          """Replace: same gates; owner or ``may_administer`` only; 404 when absent; 200 with the stored definition."""
  ```

### Module 10: Wiring + docs
- **Path**: `packages/ai-parrot-tools/src/parrot_tools/__init__.py` (one `TOOL_REGISTRY` line), `packages/ai-parrot/src/parrot/bots/mixins/__init__.py` (export), `packages/ai-parrot-server/src/parrot/manager/manager.py` (three `router.add_view` lines + one import), `docs/outputs/metric-registry.md` (new)
- **Responsibility**: make the toolkit discoverable (`parrot mcp-local metrics`), the mixin importable from `parrot.bots.mixins`, the handler mounted; document the YAML format, the kpi-table import, the precedence chain and the MCP recipe.
- **Depends on**: M5, M8, M9.
- **Interface Skeleton** *(signatures + docstrings only — bodies belong to task blueprints, FEAT-545)*:
  ```python
  # packages/ai-parrot-tools/src/parrot_tools/__init__.py  (modifies parrot_tools/__init__.py:96 — insert after the "querysource" entry)
  "metrics": "parrot_tools.metrics.toolkit.MetricsToolkit",   # verified: TOOL_REGISTRY dict at parrot_tools/__init__.py:13

  # packages/ai-parrot/src/parrot/bots/mixins/__init__.py  (modifies bots/mixins/__init__.py:15 and the __all__ at L19)
  from .metric_routing import MetricRoutingMixin   # verified: eager import block, L15-17; __all__ L19-26

  # packages/ai-parrot-server/src/parrot/manager/manager.py  (modifies manager.py:48 import block and L2427 route block)
  from ..handlers.metric_definitions import MetricDefinitionsHandler   # verified: sibling import at manager.py:48
  router.add_view("/api/v1/metrics", MetricDefinitionsHandler)                 # verified: add_view idiom manager.py:2422-2427
  router.add_view("/api/v1/metrics/schema", MetricDefinitionsHandler)
  router.add_view("/api/v1/metrics/{metric_id}", MetricDefinitionsHandler)
  ```

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_metric_definition_roundtrip` | M1 | YAML/JSON → model → `model_dump(mode="json")` → model; discriminators on `source.kind` and `default_shape.component` |
| `test_metric_definition_rejects_public_tenant` | M1 | `visibility="public"` with a tenant → `ValidationError` |
| `test_higher_is_better_tristate` | M1 | `True`/`False`/`None` preserved; default `True` |
| `test_semantic_metric_parses_but_is_unavailable` | M1/M6 | `SemanticMetricSource` round-trips; `executor_for` raises `MetricSourceUnavailable` |
| `test_period_binding_exactly_one_mode` | M1 | placeholders pair XOR `date_column` |
| `test_inmemory_store_crud` | M2 | get/list/save/delete, duplicate → `ValueError`, overwrite upsert |
| `test_load_metrics_yaml_forces_tenant_and_drops_invalid` | M2 | tenant forced, `global_only` stripped, bad entry reported not raised |
| `test_load_agent_metrics_discovers_tenant_trees` | M2 | `tmp_path/agents/x/{metrics.yaml,tenants/acme/metrics.yaml}` → `{None: …, "acme": …}` |
| `test_import_kpi_table_twelve_rows` | M2 | fixture copy of the Flex table → 12 definitions; `KPICard hero` → `KPICardShape`; `STRUCTURED_MAP` → `MapShape`; filters → dimensions minus `month` |
| `test_metric_view_c1_shadow_by_id` … `test_metric_view_c3_global_only_drops_tenant` | M3 | `SkillView` C1/C2/C3/C5/C6 twins |
| `test_matcher_alias_fast_path_no_encoder` | M3 | exact alias hits without loading the embedding model (encoder stub asserts not called) |
| `test_matcher_embedding_lane_threshold` | M3 | stubbed encoder: score ≥ threshold → match; below → `None`; margin → `ambiguous` |
| `test_matcher_parse_period_and_dimension` | M3 | EN/ES lexicon for presets; "by cost center" → dimension |
| `test_registry_resolve_never_raises` | M3 | matcher raising → logged, `None` |
| `test_resolve_metric_tenant_order` | M3 | explicit > `ctx.kwargs["tenant"]` > ContextVar > default; invalid → `ValueError` |
| `test_pg_store_sql_shapes` | M4 | `AsyncDB` mocked (`test_ui_surfaces_store.py` idiom): DDL list, native-dict jsonb params, upsert vs insert-or-skip, `list_visible` predicate per scope |
| `test_resolve_period_presets` | M7 | every preset at a fixed `today`; `udf_keywords` only for the five expressible presets |
| `test_comparison_period_modes` | M7 | previous / same-period-last-year / none |
| `test_figures_delta_and_trend` | M7 | zero-previous guard, flat band, trend sign |
| `test_kpicard_props_schema_keys_only` | M7 | every key ∈ `KPICARD_SCHEMA["properties"]`; `higherIsBetter` omitted/`False`/`null` |
| `test_build_metric_envelope_validates_tool_origin` | M7 | `validate_envelope(..., origin=TOOL)` passes for each shape |
| `test_query_slug_executor_request` | M6 | placeholders ← period, `filter` grammar, grouping ← dimension; `fake_core_qs` fixture |
| `test_transformer_executor_single_input` | M6 | registered single-input transformer accepted, multi-input rejected (`py_registry` fixture idiom) |
| `test_recipe_executor_pointer_read` | M6 | stubbed `RecipeRunner.run(include_envelope=True)`; scalar / list / dict pointers; refuses `pctx=None` |
| `test_query_metric_kpicard_end_to_end_stubbed` | M5 | in-memory registry + stubbed executor → `QueryMetricResult.envelope` KPICard with delta/trend/series |
| `test_query_metric_by_dimension_switches_shape` | M5 | `by=` → Chart/DataTable; unknown dimension → error |
| `test_query_metric_linked_only_for_query_slug` | M5 | `linked=True` on a recipe source → clear error |
| `test_list_metrics_uses_request_tenant` | M5 | `_pre_execute` tenant resolution; explicit invalid tenant rejected |
| `test_metric_routing_mixin_abstains_without_registry` | M8 | identical to `test_resolve_output_mode_noop` behaviour |
| `test_metric_routing_mixin_after_router_abstain` | M8 | `_SuperSentinel` idiom (`test_intent_router_output_mode.py:17-40`): router abstains → metric hook stashes match; hint channel absent → `None`; present (monkeypatched probe) → FEAT-755 form |
| `test_metric_routing_mixin_mro_warning` | M8 | wrong MRO order → warning logged |
| `test_metric_suggestion_provider_chips` | M8 | vs-previous / by-dimension / as-shape chips; `[]` without a match |
| `test_metric_handler_get_list_scope_filter` | M9 | mocked store + `RequestScope` variants (`test_ui_surfaces_handler.py` idiom) |
| `test_metric_handler_post_put_gates` | M9 | 401 / 403 (`may_author`) / 409 / 422 (tenant in body) / 201 / 200 |
| `test_tool_registry_has_metrics` | M10 | `TOOL_REGISTRY["metrics"]` importable (`test_leadiq.py:398` idiom) |

New test files (created by the M-tasks; `/sdd-task` appends them to the cached `test_contract` once they exist):
`packages/ai-parrot/tests/unit/metrics/test_models.py`, `test_store_and_loader.py`, `test_importers.py`,
`test_registry_view.py`, `test_matching.py`; `packages/ai-parrot/tests/bots/test_metric_routing_mixin.py`;
`packages/ai-parrot/tests/unit/metrics/test_suggestions.py`; `packages/ai-parrot-tools/tests/metrics/test_periods.py`,
`test_shapes.py`, `test_executors.py`, `test_metrics_toolkit.py`; `packages/ai-parrot-server/tests/handlers/test_metric_definitions_store.py`,
`test_metric_definitions_handler.py`.

### Integration Tests
| Test | Description |
|---|---|
| `test_metric_turn_precedence` (`packages/ai-parrot/tests/bots/test_metric_routing_mixin.py`) | `IntentRouterMixin` + `MetricRoutingMixin` + `_SuperSentinel`: "make a bar chart of hours" → router wins (`STRUCTURED_CHART`), "worked hours this month" → metric match stashed, explicit `output_mode=TEXT` → neither consulted |
| `test_query_metric_against_fake_qs` (`packages/ai-parrot-tools/tests/metrics/test_metrics_toolkit.py`) | `fake_core_qs` + `py_registry` fixtures: query_slug KPI value + previous period + linked envelope passes `LinkedSurfaces` validation |
| `test_metric_store_live` (`packages/ai-parrot-server/tests/handlers/test_metric_definitions_store.py::test_live_roundtrip`) | skip-if-unreachable Postgres (`test_ui_surfaces_store_live.py` idiom): DDL, save, get, list_visible |

### Validation Contract

> FEAT-699. Explicit pytest operands (repo-relative file or `file::node`) that gate this feature in ALL
> tiers — task, merge, feature (`/sdd-done`) and QA. When present it REPLACES the heuristic breadth
> (import impact, suite escalation); the nightly workflow covers everything else. Write
> `none — fallback` to opt out explicitly (bounded fallback: tasks' own tests + direct importers).
> Never list `real_llm` tests. `integration`/`e2e`-marked operands listed here DO run.
> `/sdd-task` caches this list into the per-spec index header (`test_contract`).

tests:
- packages/ai-parrot-tools/tests/querysource/test_execute_slug.py
- packages/ai-parrot-tools/tests/querysource/test_build_linked_surface_tool.py
- packages/ai-parrot-tools/tests/querysource/test_build_linked_python_transform.py
- packages/ai-parrot-tools/tests/querysource/test_models.py
- packages/ai-parrot-server/tests/handlers/test_ui_surfaces_handler.py
- packages/ai-parrot-server/tests/handlers/test_ui_surfaces_store.py
- packages/ai-parrot-server/tests/handlers/test_ui_surfaces_scope.py
- packages/ai-parrot/tests/bots/test_intent_router_output_mode.py
- packages/ai-parrot/tests/bots/test_intent_router_no_regression.py
- packages/ai-parrot/tests/bots/test_resolve_output_mode_noop.py
- packages/ai-parrot/tests/unit/test_skill_tenancy.py
- packages/ai-parrot/tests/unit/test_skill_tenant_mixin.py
markers: none

### Test Data / Fixtures
```python
# packages/ai-parrot/tests/unit/metrics/conftest.py
@pytest.fixture
def worked_hours_def() -> MetricDefinition:
    """query_slug KPI: slug 'flex_hours', placeholders firstdate/lastdate, dimensions cost_center/pay_code,
    higher_is_better=None, default_shape KPICardShape(value_column='hours', aggregate='sum')."""

@pytest.fixture
def kpi_table_markdown() -> str:
    """Verbatim copy of agents/flex_dashboard/skills/widget/kpi-table.md (12 rows) — committed as a test fixture
    because the agent dir is git-ignored."""

@pytest.fixture
def stub_encoder(monkeypatch):
    """Replace EmbeddingIntentRouter._ensure_encoder with a deterministic bag-of-words encoder (no model download),
    as tests/bots/test_intent_router_output_mode.py does for the FEAT-224 router."""

@pytest.fixture
def frozen_today() -> date:
    return date(2026, 10, 27)

# packages/ai-parrot-tools/tests/metrics/conftest.py — re-uses, by import, `fake_core_qs`
# (tests/querysource/test_build_linked_surface_tool.py) and `py_registry` (test_build_linked_python_transform.py:18).

# packages/ai-parrot-server/tests/handlers/test_metric_definitions_handler.py — SimpleNamespace request/app,
# AsyncMock store, RequestScope(user_id="u1", tenant="acme", groups=frozenset(), may_author=True) variants
# (test_ui_surfaces_handler.py:16-40 idiom).
```

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] `MetricDefinition` round-trips YAML/JSON with discriminated `source` (`query_slug` | `transformer` | `recipe` | `semantic_metric`) and `default_shape` (`KPICard` | `Chart` | `DataTable` | `Map`); `semantic_metric` parses and lists but `query_metric` answers `MetricSourceUnavailable`.
- [ ] `load_agent_metrics(agent_root)` loads `metrics.yaml` and every `tenants/<t>/metrics.yaml`, forcing the tenant and dropping (not raising on) invalid rows; `import_kpi_table` converts the 12 Flex rows into recipe-sourced definitions with the shapes mapped as in §3 M2.
- [ ] `MetricView` applies the `SkillView` shadowing rules (id, alias, `global_only`) and `MetricRegistry.resolve` matches by alias without loading an encoder, by embedding above threshold, and never raises.
- [ ] `PgMetricDefinitionStore` creates `navigator.metric_definitions` idempotently, stores the definition as a native JSONB object, and `list_visible(scope)` returns global public rows plus tenant rows the scope grants.
- [ ] `MetricsToolkit` exposes exactly `list_metrics`, `describe_metric`, `query_metric`, `explain_metric` (no `open`/`close`), `TOOL_REGISTRY["metrics"]` resolves, and `parrot mcp-local metrics --config .parrot/mcp-toolkits.yaml` serves them when a `metrics:` entry is configured (manual check, documented).
- [ ] `query_metric` on a `query_slug` KPI returns value, previous, delta, trend and a TOOL-origin KPICard envelope whose props are all `KPICARD_SCHEMA` keys and which passes `validate_envelope(origin=TOOL)`; with `linked=True` the envelope passes `LinkedSources` validation and carries a `RefreshPolicy`; with `pin=True` it is persisted through `PublishSurfaceTool`/`publish_surface` and `surface_id` is returned.
- [ ] `query_metric(by=<dimension>)` switches to Chart/DataTable; `linked=True` on a `recipe` source fails with a clear message; `recipe` execution refuses a `None` pctx.
- [ ] With `class X(IntentRouterMixin, MetricRoutingMixin, BasicAgent)`: explicit `output_mode` → neither router consulted; phrasing match → FEAT-224 result unchanged; phrasing abstain + metric match → `MetricMatch` stashed in `ctx.kwargs["metric_match"]` and `current_metric_match()`; no registry configured → behaviour byte-identical to today (`test_resolve_output_mode_noop` semantics). With the FEAT-755 channel present, the hook yields `(OutputMode.A2UI, <default component>)` in FEAT-755's form.
- [ ] `MetricSuggestionProvider.suggest` returns deterministic chips from the stashed match and `[]` otherwise.
- [ ] `GET /api/v1/metrics`, `/schema`, `/{metric_id}`, `POST`, `PUT` behave as §3 M9 (401/403/404/409/422/201/200), tenant always server-set.
- [ ] No diff in `intent_router.py`, `abstract.py`, `base.py`, `data.py`, `clients/base.py`, `kpicard.py`, `handlers/models/ui_surfaces.py`, `parrot_tools/querysource/*`; all Validation Contract files still pass.
- [ ] `docs/outputs/metric-registry.md` documents the YAML format, the import CLI usage, the precedence chain, the MCP recipe and the linked-period limitation (§7).

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> This section is the single source of truth for what exists in the codebase.
> Implementation agents MUST NOT reference imports, attributes, or methods
> not listed here without first verifying they exist via `grep` or `read`.
> Verified against `b9417f4a0` (dev, 2026-10-27).

### Verified Imports
```python
from parrot.models.outputs import OutputMode                                   # models/outputs.py:23 (A2UI L55, CARD L44, STRUCTURED_* L52-54)
from parrot.utils.helpers import RequestContext, current_context               # utils/helpers.py:7, :58
from parrot.bots.mixins.intent_router import IntentRouterMixin                 # bots/mixins/intent_router.py:123
from parrot.bots.mixins import IntentRouterMixin                               # bots/mixins/__init__.py:15
from parrot.bots.data import DEFAULT_OUTPUT_MODE_ROUTES, PandasAgent           # bots/data.py:297, :338
from parrot.registry.routing.embedding_router import EmbeddingIntentRouter, RouteScore   # embedding_router.py:57, :37
from parrot.registry.capabilities.models import IntentRouterConfig             # capabilities/models.py:149
from parrot.skills.tenancy import validate_tenant_id, tenant_skills_dir, discover_tenant_dirs, current_skill_tenant, bind_skill_tenant, reset_skill_tenant, SkillView, TenantTreeReport   # tenancy.py:30,42,51,82,87,92,134,123
from parrot.conf import AGENTS_DIR, default_dsn                                # conf.py:181; default_dsn as imported at handlers/models/ui_surfaces.py:30
from parrot.outputs.a2ui.builders import build_surface, build_chart, build_kpicard, build_datatable, build_linked_surface   # builders.py:79,130,151,193,528
from parrot.outputs.a2ui.catalog import validate_envelope, register_component  # catalog/__init__.py (validate_envelope per FEAT-598 contract)
from parrot.outputs.a2ui.catalog.base import ProducerOrigin                    # catalog/base.py:99
from parrot.outputs.a2ui.catalog.parrot.kpicard import KPICARD_SCHEMA, KPICardComponent   # kpicard.py:15, :166
from parrot.outputs.a2ui.models import CreateSurface                           # a2ui/models.py (used at handlers/ui_surfaces.py:44)
from parrot.outputs.a2ui.linked import has_data_sources, PythonTransform       # linked/__init__.py:23 (PythonTransform), has_data_sources (handlers/ui_surfaces.py:46)
from parrot.outputs.a2ui.linked.models import LinkedDataSource, LinkedSources, TransformSpec, PythonTransform, RefreshPolicy, TransformRef   # linked/models.py:207,284,192,178,43,59
from parrot.outputs.a2ui.linked.pytransform import validate_python_transform, apply_python_transform, TransformStageError   # pytransform.py:36,94,26
from parrot.outputs.a2ui.linked.service import LinkedSurfaceService, LinkedGuardRequired, SnapshotError   # service.py:79,31,35
from parrot.outputs.a2ui.recipes.transformers import transformer_registry, TransformerRegistry, RegisteredTransformer   # transformers.py:192,63,46
from parrot.outputs.a2ui.recipes.models import TransformerManifest, RecipeParam, InfographicRecipe   # recipes/models.py:313,51,235
from parrot.outputs.a2ui.recipes.store import AbstractRecipeStore, FileRecipeStore, DBRecipeStore   # recipes/store.py:175,230,304
from parrot.tools.infographic_recipes.runner import RecipeRunner, RecipeRunException   # runner.py:205,91
from parrot.tools.infographic_recipes import load_transformer_module           # infographic_recipes/__init__.py:23,44 → loader.py:70
from parrot.tools.infographic_recipes.narrator import Narrator                 # narrator.py:21 (Protocol)
from parrot.tools.toolkit import AbstractToolkit                               # tools/toolkit.py:225
from parrot.tools.abstract import AbstractTool, AbstractToolArgsSchema         # tools/abstract.py:282, :238
from parrot.tools.dataset_manager.tool import DatasetManager                   # dataset_manager/tool.py:499
from parrot.auth.permission import PermissionContext, build_principal_context  # auth/permission.py:81, :166
from parrot.bots.mixins.infographic_authoring import InfographicAuthoringMixin # publish_surface at infographic_authoring.py:442
from parrot_tools import TOOL_REGISTRY                                         # parrot_tools/__init__.py:13
from parrot_tools.querysource import QuerysourceToolkit, SlugDetail, SlugSummary, ExecutionResult, QuerysourceToolkitError, SlugNotFoundError, TenantDeniedError, InvalidConditionsError   # parrot_tools/querysource/__init__.py:3-20
from parrot_tools.querysource.models import PlaceholderInfo                    # models.py:24
from parrot_tools.ui_surfaces import PublishSurfaceTool, PublishSurfaceArgs    # parrot_tools/ui_surfaces.py:65, :35
# ai-parrot-server
from parrot.handlers.models.ui_surfaces import UISurfaceRecord, UISurfaceKind, SurfaceVisibility, PgUISurfaceStore   # handlers/models/ui_surfaces.py:64,42,50,457
from parrot.handlers.scope import RequestScope, EMPTY_SCOPE, ScopeResolver, SessionScopeResolver, get_scope_resolver, resolve_request_tenant, normalize_visibility, scope_grants   # handlers/scope.py:40,62,67,75,142,147,173,181
from parrot.handlers.ui_surfaces_scope import SurfaceScope, scope_grants       # ui_surfaces_scope.py:44 (alias of RequestScope), :48
from parrot.handlers.ui_surfaces import UISurfacesHandler, resolve_surface_access   # handlers/ui_surfaces.py:328, :180
from parrot.handlers.infographic_recipes import get_recipe_runner, register_recipe_routes   # infographic_recipes.py:75, :80
from asyncdb import AsyncDB                                                    # handlers/models/ui_surfaces.py:29
from navigator.views import BaseView                                           # handlers/ui_surfaces.py:26
```

### Existing Class Signatures
```python
# packages/ai-parrot/src/parrot/bots/abstract.py
class AbstractBot:
    async def _resolve_output_mode(self, query: str, ctx: "Optional[RequestContext]") -> "Optional[OutputMode]":  # L4168 — terminal no-op, returns None
    def _apply_default_output_mode(self, output_mode: OutputMode) -> OutputMode:   # L4191 — DEFAULT → default_output_mode
    async def ask(...)   # L4738

# packages/ai-parrot/src/parrot/bots/base.py
class BaseBot(AbstractBot):   # L91
    async def _conversation_body(...)   # L270 — `_resolved_mode = await self._resolve_output_mode(question, ctx)` at L300, only when output_mode == DEFAULT
    async def ask(...)                  # L1063 — same call at L1155
# packages/ai-parrot/src/parrot/bots/data.py
class PandasAgent(IntentRouterMixin, BasicAgent):   # L338 — call at L1350; `ctx.output_mode = _resolved_mode` L1354; `_apply_default_output_mode` L1358

# packages/ai-parrot/src/parrot/bots/mixins/intent_router.py
class IntentRouterMixin:   # L123
    _router_active: bool = False; _router_config: Optional[IntentRouterConfig] = None   # L137-138
    def __init__(self, **kwargs: Any) -> None   # L141
    def configure_output_router(self, config: IntentRouterConfig) -> None   # L175 — EmbeddingIntentRouter(config.embedding_model, output_mode_threshold, discrepancy_margin); add_route(OutputMode(mode_value), utterances)
    async def _resolve_output_mode(self, query: str, ctx: Any) -> "Optional[OutputMode]"   # L209 — no router → super(); rs.mode None → super(); ambiguous → _llm_disambiguate_output_mode; ctx.intent_score = rs.score
    async def _llm_disambiguate_output_mode(self, query: str, candidates: "list[OutputMode]") -> "Optional[OutputMode]"   # L252

# packages/ai-parrot/src/parrot/utils/helpers.py
class RequestContext:   # L7
    def __init__(self, request=None, app=None, llm=None, user_id=None, session_id=None, **kwargs)   # L21; self.kwargs = kwargs L36
    output_mode = None; intent_score = None   # L41-42 (FEAT-224)
def current_context() -> Optional[RequestContext]   # L58 (ContextVar L53)

# packages/ai-parrot/src/parrot/registry/routing/embedding_router.py
class RouteScore(NamedTuple): mode: Optional[OutputMode]; score: float; runner_up: float; ambiguous: bool   # L37-54
class EmbeddingIntentRouter:   # L57
    def __init__(self, model: str = "intfloat/multilingual-e5-small", threshold: float = 0.85, margin: float = 0.05) -> None   # L65; self._routes: dict[OutputMode, np.ndarray] L88
    def add_route(self, mode: OutputMode, utterances: list[str]) -> None   # L108 — stores self._routes[mode] (no type check on the key)
    def route_scores(self, query: str) -> list[tuple[OutputMode, float]]   # L125
    def route(self, query: str) -> RouteScore   # L152 — sync, CPU-bound; callers use asyncio.to_thread

# packages/ai-parrot/src/parrot/registry/capabilities/models.py
class IntentRouterConfig(BaseModel):   # L149
    enable_output_mode_routing: bool = False; embedding_model: str = "intfloat/multilingual-e5-small"   # L209-215
    output_mode_routes: dict[str, list[str]]; output_mode_threshold: float = 0.85; discrepancy_margin: float = 0.05   # L216-238

# packages/ai-parrot/src/parrot/skills/tenancy.py
def validate_tenant_id(value: str) -> str   # L30 — validate_path_segment + RESERVED_TENANT_NAMES
def tenant_skills_dir(agent_root: Path, tenant: str) -> Path   # L42 — secure_path(agent_root, "tenants", tenant, "skills")
def discover_tenant_dirs(agent_root: Path, logger=None) -> Dict[str, Path]   # L51
def current_skill_tenant() -> Optional[str]; bind_skill_tenant(tenant) -> Token; reset_skill_tenant(token) -> None   # L82, L87, L92
class SkillView:   # L134
    def __init__(self, global_registry, tenant_registry=None, *, tenant=None, logger=None)   # L137
    def compose(self) -> "SkillView"   # L160 — C1 name shadow, C2 trigger shadow, C3/C4 global_only drops, C5/C6 single-side
    def get(self, trigger) / get_by_name(name) / list_skills() / has_trigger(trigger)   # L246-258
# packages/ai-parrot/src/parrot/skills/mixin.py
class SkillRegistryMixin: tenant_based: bool = False   # L110
    def _resolve_tenant(self, explicit=None, ctx=None) -> Optional[str]   # L135 — explicit, ctx.kwargs["tenant"], current_skill_tenant(), instance default

# packages/ai-parrot/src/parrot/outputs/a2ui/builders.py
def build_surface(component: str, properties: dict, *, surface_id: str, component_id: str = "root", data_model=None,
                  origin: ProducerOrigin = ProducerOrigin.LLM, metadata=None, surface_metadata=None) -> CreateSurface   # L79-89
def build_chart(*, chart_type, x, y: Sequence[str], title=None, data_binding=None, show_legend=True, surface_id="chart", data_model=None) -> CreateSurface   # L130
def build_kpicard(*, label, value, unit=None, delta=None, trend=None, surface_id="kpi") -> CreateSurface   # L151 — NO series/comparisonPeriod/higherIsBetter/format
def build_datatable(*, columns: Sequence[dict], data_binding=None, title=None, total_rows=None, truncated=False, surface_id="table", data_model=None) -> CreateSurface   # L193
def build_linked_surface(components: Sequence[dict], sources: Mapping[str, "LinkedSource"], frames: Mapping[str, "pd.DataFrame"], ...)   # L528

# packages/ai-parrot/src/parrot/outputs/a2ui/catalog/parrot/kpicard.py
KPICARD_SCHEMA: dict   # L15 — label, value, unit, delta, trend{up,down,flat}, icon, color, comparisonPeriod, higherIsBetter {bool,null} (L33-49), format{percent,currency,number}, periods, series, defaultPeriod
class KPICardComponent: SCHEMA, INSTRUCTIONS; def lower(self, component, data_model) -> BasicTree   # L166

# packages/ai-parrot/src/parrot/outputs/a2ui/linked/models.py
class RefreshPolicy(BaseModel): policy: Literal["on_mount","manual","interval"] = "on_mount"; interval_seconds: int | None   # L43
class PythonTransform(BaseModel): transformer: str; params: dict; input_alias: str = "source"; output: str | None   # L178
class TransformSpec(BaseModel): ops | ref | python — exactly one   # L192-203
class LinkedDataSource(BaseModel): kind: Literal["query_slug"]; slug; tenant; is_multiquery; multi_output; conditions; request: SourceRequest; params; locked; transform; target; snapshot_at; snapshot_truncated; refresh: RefreshPolicy   # L207-240
class LinkedSources(RootModel[dict[str, LinkedSource]])   # L284 — python-transformed sources are terminal (L315-332)
# linked/pytransform.py
def validate_python_transform(spec: PythonTransform) -> list[str]   # L36 — registry membership; multi-input (>1 alias) rejected L49-50; alias mismatch L51-52
async def apply_python_transform(frame: pd.DataFrame, spec: PythonTransform, *, max_rows: int) -> pd.DataFrame   # L94
# linked/service.py
class LinkedSurfaceService: def __init__(self, *, guard, max_fetch_rows=5000, max_snapshot_rows=500)   # L79, L88; validate_for_persistence L127; ensure_snapshot L154; refresh L187; fetch_source L250

# packages/ai-parrot/src/parrot/outputs/a2ui/recipes/transformers.py
@dataclass(frozen=True) class RegisteredTransformer: func: TransformerFunc; manifest: TransformerManifest   # L46
class TransformerRegistry: register L104; get(name) -> RegisteredTransformer L148 (KeyError when unknown); manifest(name) L167; list() L181   # L63
transformer_registry = TransformerRegistry(builtins_module="parrot.outputs.a2ui.recipes.library")   # L192
# recipes/models.py
class TransformerManifest(BaseModel): name; description; requires_columns: dict[str, list[str]]; params_schema: dict   # L313-330

# packages/ai-parrot/src/parrot/tools/infographic_recipes/runner.py
class RecipeRunner:   # L205
    def __init__(self, store: AbstractRecipeStore, dataset_manager: DatasetManager, *, artifact_store=None, owner=None, narrator: Optional[Narrator] = None)   # L227
    async def run(self, name: str, *, params: dict | None = None, pctx: Any | None = None, recipe_owner: Optional[str] = None, include_envelope: bool = False) -> RenderedArtifact   # L243 — fails OPEN on falsy pctx (docstring)

# packages/ai-parrot/src/parrot/tools/toolkit.py
class AbstractToolkit(ServerManagedToolkit, ABC):   # L225
    exclude_tools: tuple[str, ...] = ()   # L262
    tool_prefix: str | None = None        # L276
    def get_tools(...)                    # L522 — prefix rule L557-570
# parrot/tools/abstract.py: class AbstractToolArgsSchema(BaseModel) L238; class AbstractTool(EventEmitterMixin, ABC) L282

# packages/ai-parrot-tools/src/parrot_tools/querysource/toolkit.py
class QuerysourceToolkit(AbstractToolkit):   # L76
    def __init__(self, programs=None, allow_write=False, allow_raw_sql=False, allow_external_sources=True, include_sql=True, max_rows=200, forced_conditions=None, dsn=None, multiquery_timeout=600.0, **kwargs)   # L89-101
    async def list_slugs(self, search=None, program=None, limit=50)   # L170
    async def describe_slug(self, slug: str, dry_run: bool = False, tenant: str | None = None) -> SlugDetail   # L222
    async def execute_slug(self, slug, placeholders=None, filter=None, fields=None, ordering=None, grouping=None, limit=None, offset=None, refresh=False, tenant=None) -> ExecutionResult   # L253-265
    async def build_linked_surface(self, slug, component: dict, request=None, tenant=None, snapshot=False, surface_id=None, target_key=None, refresh=None, transform=None) -> dict   # L351-362
    async def build_linked_dashboard(...)   # L417
    async def _pre_execute(self, tool_name: str, /, **kwargs) -> None   # L860
# parrot_tools/querysource/models.py: SlugSummary L13; PlaceholderInfo(name, type, default, required, accepts_keywords) L24; SlugDetail L38; ExecutionResult(status, slug, rows, returned_rows, total_rows, truncated, columns, applied_conditions, rejected_inputs, duration_ms) L54-66

# packages/ai-parrot-tools/src/parrot_tools/ui_surfaces.py
class PublishSurfaceTool(AbstractTool):   # L65; name = "publish_surface"
    def __init__(self, bot=None, surface_store=None, agent_id=None, user_id=None, session_id=None, linked_service=None, guard=None, **kwargs)   # L86
    async def _execute(self, *, kind: str, title: str, envelope: dict, recipe_name=None, recipe_owner=None, recipe_params=None, ...)   # L127
# bots/mixins/infographic_authoring.py: async def publish_surface(self, *, kind, title, envelope, recipe_name=None, recipe_owner=None, recipe_params=None, overwrite=False, surface_store=None, user_id=None, session_id=None) -> str   # L442
# parrot_tools/__init__.py: TOOL_REGISTRY: dict[str, str] L13; "querysource" L96; "publish_surface" L127

# packages/ai-parrot-server/src/parrot/handlers/models/ui_surfaces.py
class UISurfaceKind(str, Enum) L42; class SurfaceVisibility(str, Enum) L50
class UISurfaceRecord(BaseModel): surface_id, kind, title, envelope, catalog_id, agent_id, user_id, session_id, recipe_name, recipe_owner, recipe_params, tenant, visibility, allowed_groups, created_at, updated_at   # L64-82
_DDL_STATEMENTS: list[str]   # L107 — CREATE SCHEMA navigator; CREATE TABLE navigator.ui_surfaces L110-128; ADD COLUMN IF NOT EXISTS live-migration idiom L148-157
async def _exec(conn: Any, sql: str, *args: Any) -> None   # L438
class PgUISurfaceStore:   # L457
    def __init__(self, dsn: str | None = None)   # L469 — default_dsn
    def _get_db(self) -> AsyncDB               # L474 — AsyncDB("pg", dsn=self.dsn)
    async def _ensure_ready(self) -> None      # L478
    async def ensure_schema(self) -> None      # L483 — "already exists" race tolerated L495-500
    async def save(self, record, *, overwrite=False) -> str   # L503 — jsonb params passed as native objects (note L524-534); None from DO NOTHING → ValueError L545-548
    async def get(surface_id) L553; list(user_id, *, kind) L564; list_visible(scope, *, kind) L583; update_visibility L624; update_envelope L656; delete L686

# packages/ai-parrot-server/src/parrot/handlers/scope.py
@dataclass class RequestScope: user_id; tenant; groups: frozenset[str]; is_superuser=False; may_author=True; may_administer=False; studio_enabled=True   # L40-59
EMPTY_SCOPE L62; class ScopeResolver(Protocol): async def resolve(self, request) -> RequestScope L67-70; class SessionScopeResolver L75; get_scope_resolver(app) L142
def scope_grants(*, tenant, visibility, allowed_groups, scope) -> bool   # L181 — pure; ownership handled by callers
# handlers/ui_surfaces_scope.py: SurfaceScope = RequestScope L44; scope_grants(record, scope) adapter L48

# packages/ai-parrot-server/src/parrot/handlers/ui_surfaces.py
class PublishSurfaceRequest(BaseModel) L72; async def _get_user_id(request) -> str | None L134; async def resolve_surface_access(...) L180
class UISurfacesHandler(BaseView):   # L328
    _logger_name L336; def post_init L338; @property store L344 (app["ui_surfaces_store"] lazy); _linked_service L359; _recipe_runner L371
    async def _scope(self) -> SurfaceScope L381; def _error(self, message, *, status=400) L390; async def get L406; async def post L415 (dispatch on path suffix); _get_list L481; _pin_save L523; _refresh L632
# handlers/models/skills_catalog.py: class SkillCatalogEntry(Model) — DDL in docstring L34-50: UNIQUE (tenant, name) + partial unique index WHERE tenant IS NULL + CHECK constraints (idiom reused by M4)
# manager/manager.py: `from ..handlers.ui_surfaces import UISurfacesHandler` L48; router.add_view("/api/v1/ui/surfaces…", UISurfacesHandler) × 6 at L2422-2427
# parrot/cli/__init__.py: "mcp-local": "parrot.mcp.local_cli" L116; .parrot/mcp-toolkits.yaml:123 `querysource:` entry (class + kwargs) — the per-toolkit MCP recipe
```

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `MetricRoutingMixin._resolve_output_mode` (M8) | `IntentRouterMixin._resolve_output_mode` `super()` chain / `AbstractBot._resolve_output_mode` | cooperative MRO | `intent_router.py:209-250`, `abstract.py:4168` |
| `MetricRoutingMixin` (M8) | call sites that honour the result | no edit; `output_mode == DEFAULT` guard | `base.py:300`, `base.py:1155`, `data.py:1350` |
| `MetricMatcher` (M3) | `EmbeddingIntentRouter.add_route / route / route_scores` | metric id as key | `embedding_router.py:108,152,125` |
| `resolve_metric_tenant` (M3) | `ctx.kwargs["tenant"]`, `current_skill_tenant()` | read | `skills/mixin.py:143-146`, `tenancy.py:82` |
| `load_agent_metrics` (M2) | `discover_tenant_dirs`, `secure_path` containment | call | `tenancy.py:51`, `tenancy.py:42-49` |
| `QuerySlugExecutor.fetch` (M6) | `QuerysourceToolkit.execute_slug` | await | `toolkit.py:253-265` |
| `build_linked_metric_envelope` (M7) | `QuerysourceToolkit.build_linked_surface` | await | `toolkit.py:351-362` |
| `TransformerExecutor.fetch` (M6) | `validate_python_transform`, `apply_python_transform`, `transformer_registry.get` | call / await | `pytransform.py:36,94`, `transformers.py:148` |
| `RecipeExecutor.fetch` (M6) | `RecipeRunner.run(include_envelope=True)` | await | `runner.py:243-250` |
| `build_metric_envelope` (M7) | `build_surface(..., origin=ProducerOrigin.TOOL)`, `build_chart`, `build_datatable` | call | `builders.py:79,130,193` |
| `kpicard_props` (M7) | `KPICARD_SCHEMA["properties"]` | key allowlist | `kpicard.py:15-98` |
| `MetricsToolkit.query_metric(pin=True)` (M5) | `PublishSurfaceTool._execute` / `InfographicAuthoringMixin.publish_surface` | await | `parrot_tools/ui_surfaces.py:127`, `infographic_authoring.py:442` |
| `MetricsToolkit` (M5) | `TOOL_REGISTRY["metrics"]` → `parrot mcp-local metrics` | registry string | `parrot_tools/__init__.py:13,96`; `cli/__init__.py:116` |
| `PgMetricDefinitionStore` (M4) | `AsyncDB("pg")`, `default_dsn`, `_exec` idiom | copy of | `handlers/models/ui_surfaces.py:29-30,438,474-501` |
| `PgMetricDefinitionStore.list_visible` (M4) | `scope_grants(tenant=, visibility=, allowed_groups=, scope=)` | call | `handlers/scope.py:181` |
| `MetricDefinitionsHandler` (M9) | `BaseView`, `get_scope_resolver(app).resolve(request)` | inherit / await | `handlers/ui_surfaces.py:26,381-388` |
| `MetricDefinitionsHandler` (M9) | `router.add_view` in `BotManager` | three lines after the ui_surfaces block | `manager.py:2422-2427` |
| `MetricSuggestionProvider` (M8) | `current_metric_match()` / `ctx.kwargs["metric_match"]` | read | M3 `context.py` (new) |

### Does NOT Exist (Anti-Hallucination)
- ~~`parrot.metrics` package, `MetricDefinition`, `MetricRegistry`, `MetricView`, `MetricMatcher`, `MetricMatch`, `MetricStore`, `InMemoryMetricStore`, `load_metrics_yaml`, `import_kpi_table`, `resolve_metric_tenant`, `current_metric_match`~~ — net-new (M1–M3). (`parrot/observability/` is telemetry; unrelated.)
- ~~`parrot_tools.metrics`, `MetricsToolkit`, `QueryMetricResult`, `SourceExecutor`, `resolve_period`, `kpicard_props`~~ — net-new (M5–M7). A test-local `class MetricsToolkit(AbstractToolkit)` exists ONLY in `packages/ai-parrot/tests/tools/test_nested_model_args.py:29` (fixture class, not importable from any package).
- ~~`MetricRoutingMixin`, `MetricSuggestionProvider`~~ — net-new (M8).
- ~~`PgMetricDefinitionStore`, `navigator.metric_definitions`, `MetricDefinitionsHandler`, `/api/v1/metrics`~~ — net-new (M4/M9).
- ~~`a2ui_component`, `component_hint`, composite `"a2ui:<Component>"` route keys, a `RouteScore.label`~~ — FEAT-755, **not in the tree** (grep: zero hits in `packages/ai-parrot/src/parrot`); `add_route()` is annotated `OutputMode` and `configure_output_router` does `OutputMode(mode_value)` (`intent_router.py:195-201`).
- ~~`SuggestionProvider`, a chip model, a suggestions transport~~ — FEAT-752, not in the tree.
- ~~A `_resolve_output_mode` return form other than `Optional[OutputMode]`~~ — today every override returns a bare mode or `None` (`abstract.py:4168-4189`, `intent_router.py:209-250`).
- ~~`_resolve_output_mode` called from `Agent.ask` / `Chatbot`~~ — only `base.py:300`, `base.py:1155`, `data.py:1350` call it.
- ~~`RequestContext.tenant` attribute~~ — tenant travels in `ctx.kwargs["tenant"]` (`skills/mixin.py:143-146`); `RequestContext` has `output_mode` / `intent_score` only (`helpers.py:41-42`).
- ~~`EmbeddingIntentRouter(labels=…)`, `add_route(label: str, …)`~~ — keys are typed `OutputMode`; runtime is key-agnostic (§7 R1).
- ~~`build_kpicard(series=…, comparison_period=…, higher_is_better=…, format=…)`~~ — `build_kpicard` takes label/value/unit/delta/trend only (`builders.py:151-158`); richer KPICards go through `build_surface("KPICard", props)`.
- ~~`QuerysourceToolkit.execute_slug(period=…)`, `previous_period=`, any date arithmetic in `parrot_tools/querysource/dialect.py`~~ — the toolkit knows the closed 7-keyword UDF vocabulary only (`toolkit.py:369-370` docstring).
- ~~A QuerySource UDF keyword for "previous month" / "last 30 days"~~ — vocabulary is TODAY, YESTERDAY, FDOM, LDOM, CURRENT_YEAR, CURRENT_MONTH, LAST_YEAR (FEAT-598 contract; `toolkit.py:369-370`).
- ~~Multi-input transformers in the linked `transform.python` lane~~ — rejected at `pytransform.py:49-50`.
- ~~`RecipeRunner.run(data_model_path=…)`, a recipe "single value" mode~~ — `run()` returns a `RenderedArtifact`; the envelope is available only with `include_envelope=True` (`runner.py:243-250`).
- ~~`LinkedDataSource(kind="recipe")`~~ — only `query_slug` and `derived` kinds exist (`linked/models.py:211,251`).
- ~~A shared base class for Postgres stores (`AbstractPgStore`), a generic `list_visible` helper~~ — `PgUISurfaceStore` is standalone; M4 copies the idiom.
- ~~`UISurfaceKind.metric`, a `metric_id` column on `navigator.ui_surfaces`~~ — not added; a pinned metric is an ordinary `widget` surface.
- ~~`SkillView` accepting arbitrary objects~~ — it is typed over `SkillFileRegistry` (`tenancy.py:137-141`); M3 re-implements the rules, it does not subclass.
- ~~`agents/flex_dashboard/skills/widget/kpi-table.md` in git~~ — the agent dir is git-ignored; tests use a committed fixture copy.
- ~~`sdd/specs/inline-a2ui-component-routing.spec.md`, `sdd/specs/followup-suggestion-chips.spec.md`~~ — not committed at spec time (being written concurrently); only `sdd/proposals/output-mode-intent-router.brainstorm.md` (rev 2, accepted) exists.

### Edit Sites (Blueprint Anchors)

Verified against: `b9417f4a0` (2026-10-27). `/sdd-task` MUST re-run the `grep -c` for every row it uses.

| File | Action | Verbatim anchor line | Verified at | Occurrences |
|---|---|---|---|---|
| `packages/ai-parrot/src/parrot/metrics/__init__.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/metrics/models.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/metrics/errors.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/metrics/store.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/metrics/loader.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/metrics/importers.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/metrics/registry.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/metrics/matching.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/metrics/context.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/metrics/suggestions.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/bots/mixins/metric_routing.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/bots/mixins/__init__.py` | MODIFY | `from .intent_router import IntentRouterMixin` | `bots/mixins/__init__.py:15` | 1 |
| `packages/ai-parrot-tools/src/parrot_tools/metrics/__init__.py` | CREATE | — | — | — |
| `packages/ai-parrot-tools/src/parrot_tools/metrics/models.py` | CREATE | — | — | — |
| `packages/ai-parrot-tools/src/parrot_tools/metrics/toolkit.py` | CREATE | — | — | — |
| `packages/ai-parrot-tools/src/parrot_tools/metrics/executors.py` | CREATE | — | — | — |
| `packages/ai-parrot-tools/src/parrot_tools/metrics/periods.py` | CREATE | — | — | — |
| `packages/ai-parrot-tools/src/parrot_tools/metrics/shapes.py` | CREATE | — | — | — |
| `packages/ai-parrot-tools/src/parrot_tools/__init__.py` | MODIFY | `    "querysource": "parrot_tools.querysource.toolkit.QuerysourceToolkit",` | `parrot_tools/__init__.py:96` | 1 |
| `packages/ai-parrot-server/src/parrot/handlers/models/metric_definitions.py` | CREATE | — | — | — |
| `packages/ai-parrot-server/src/parrot/handlers/metric_definitions.py` | CREATE | — | — | — |
| `packages/ai-parrot-server/src/parrot/manager/manager.py` | MODIFY | `from ..handlers.ui_surfaces import UISurfacesHandler` | `manager.py:48` | 1 |
| `packages/ai-parrot-server/src/parrot/manager/manager.py` | MODIFY | `        router.add_view("/api/v1/ui/surfaces/{surface_id}/share/{token}", UISurfacesHandler)` | `manager.py:2427` | 1 |
| `docs/outputs/metric-registry.md` | CREATE | — | — | — |
| `packages/ai-parrot/tests/unit/metrics/{conftest,test_models,test_store_and_loader,test_importers,test_registry_view,test_matching,test_suggestions}.py` | CREATE | — | — | — |
| `packages/ai-parrot/tests/unit/metrics/fixtures/kpi-table.md` | CREATE | — | — | — |
| `packages/ai-parrot/tests/bots/test_metric_routing_mixin.py` | CREATE | — | — | — |
| `packages/ai-parrot-tools/tests/metrics/{conftest,test_periods,test_shapes,test_executors,test_metrics_toolkit}.py` | CREATE | — | — | — |
| `packages/ai-parrot-server/tests/handlers/{test_metric_definitions_store,test_metric_definitions_handler}.py` | CREATE | — | — | — |

- A **CREATE** row declares only the path the module adds; it needs no anchor.
- **Occurrences > 1** means the one-line anchor is ambiguous. Quote 2–3 lines of
  surrounding context in the anchor cell so the blueprint block can attach uniquely.
- An anchor that cannot be verified is written `(unverified — check before use)`,
  never guessed.
- Deliberately **no** rows for `bots/mixins/intent_router.py`, `bots/abstract.py`, `bots/base.py`,
  `bots/data.py`, `clients/base.py`, `catalog/parrot/kpicard.py`, `handlers/models/ui_surfaces.py`,
  `parrot_tools/querysource/*` — G9. `.parrot/mcp-toolkits.yaml` is operator configuration, not a
  feature edit (documented in `docs/outputs/metric-registry.md`).

---

## 7. Implementation Notes & Constraints

> Architecture decisions stay with the thinking model. A delegated
> implementation may only express a decision already recorded here and in
> the TASK's implementation blocks — it must never invent an API, choose a
> file, or resolve an open design question.

### Patterns to Follow
- Pydantic v2 everywhere, `extra="forbid"` on every definition model (a typo in YAML must fail loud at load time and be *reported*, never silently ignored).
- `parrot.metrics` imports nothing from `parrot.outputs.a2ui` or `parrot.tools` — the a2ui chain is expensive (`bots/mixins/__init__.py:28-31` comment) and the registry must stay importable by the router hook with no side effects. Envelope building lives in `parrot_tools.metrics.shapes`.
- Logging through `self.logger` / module `logger`; the hook and the registry **never raise into a turn** (`IntentRouterMixin` precedent: warn and chain `super()`).
- CPU-bound matching (`MetricMatcher.match`) runs under `asyncio.to_thread`, exactly like `router.route` at `intent_router.py:231`.
- Tool docstrings are the LLM-facing descriptions (M5 skeleton text is binding); `exclude_tools=("open","close")` like `QuerysourceToolkit` (`toolkit.py:85`).
- Postgres store: copy `PgUISurfaceStore` idioms verbatim — fresh `AsyncDB("pg")` per call, `_DDL_STATEMENTS` list with race tolerance, jsonb params as native objects, `ON CONFLICT DO NOTHING` returning `None` as the duplicate signal.
- Handler: one `BaseView` dispatching on `match_info`/path suffix; `_error()` builds responses directly (status whitelist landmine, `handlers/ui_surfaces.py:390-404`); tenant always from `RequestScope`, never from the body (`PublishSurfaceRequest` precedent — deliberately no tenant field).

### `metrics.yaml` format (M2, binding)
```yaml
metrics:
  - id: worked_hours
    name: Worked Hours
    aliases: [hours worked, horas trabajadas, worked hrs]
    example_phrases: ["show me worked hours this month", "cuántas horas trabajamos este mes"]
    unit: h
    format: number
    higher_is_better: null          # tri-state; omit for true
    program: flex
    dimensions:
      - {name: cost center, column: cost_center, aliases: [cc]}
      - {name: pay code, column: pay_code}
    time: {grain: month, default_period: this_month, series_grain: day,
           binding: {start_placeholder: firstdate, end_placeholder: lastdate}}
    comparison: {mode: previous_period}
    default_shape: {component: KPICard, value_column: hours, aggregate: sum}
    source: {kind: query_slug, slug: flex_hours, tenant: null}
```
Agent-level file: `AGENTS_DIR/<agent_id>/metrics.yaml` (global namespace). Tenant files:
`AGENTS_DIR/<agent_id>/tenants/<tenant>/metrics.yaml` — tenant forced, `global_only` stripped, `visibility: public` rejected.

### `kpi-table.md` import mapping (M2, binding)
Columns (verbatim header): `| KPI | Transformer | Dataset alias(es) | Recipe path | Output mode | Supported filters |`.
`id` = slugified KPI (`worked_hours_total`); `source = RecipeSource(recipe_name=<arg>, data_model_path=<Recipe path>, param_map={month: month, …})`;
`Output mode` → shape: `KPICard hero` → `KPICardShape(value_column="value", aggregate="none")`, `STRUCTURED_CHART` → `ChartShape(line, x="month", y=["value"])`,
`STRUCTURED_TABLE` → `DataTableShape(columns=[])` (columns filled from the first run), `STRUCTURED_MAP` → `MapShape(lat="lat", lon="lon")`;
`Supported filters` minus `month` → `dimensions`; `month` present → `TimeSpec(binding=PeriodBinding(start_placeholder="month", end_placeholder="month"))` with the recipe's own month grammar
(the importer records `transformer` and `dataset aliases` in `description` for lineage — they are informational for a recipe source).
Rows whose recipe path contains `{…}` (Proximity Staffing) import with `MapShape` and a `description` note; they are listable but `query_metric` returns the coverage frame only (§8 Q5).

### Period resolution (M7, binding)
| preset | start / end | `udf_keywords` |
|---|---|---|
| `today`, `yesterday` | that day | `TODAY` / `YESTERDAY` |
| `this_month` | first..last day of month | `{start: FDOM, end: LDOM}` |
| `mtd` | first day..today | `{start: FDOM, end: TODAY}` |
| `ytd`, `this_year` | Jan 1..today / Dec 31 | `{start: CURRENT_YEAR}` only when the binding has a single placeholder; else `None` |
| `last_month`, `last_week`, `this_week`, `qtd`, `last_7d`, `last_30d`, `last_90d`, `last_year` | computed ISO dates | `None` |
`comparison_period`: previous_period = same length ending the day before `start`; same_period_last_year = both bounds minus one year. The comparison frame is a **second execution** of the same source (no new grammar).

### Linked periods (M7, binding limitation)
A linked KPICard binds `value` to a live `query_slug` source. The current period uses UDF keywords when `udf_keywords` is set (so a renderer refresh rolls with the calendar); otherwise the ISO dates are sent as `locked` params and the surface refreshes *that* window. The comparison value, when any, is a second linked source keyed `previous` with `locked` ISO dates. Consequence: after a period roll, `value` may be live while `previous` is frozen — `query_metric(linked=True)` therefore defaults `refresh` to `manual`, stamps `comparisonPeriod` with the explicit label ("Sep 2026"), and the doc states it. `recipe` sources are never linked (D4); `pin=True` on them passes `recipe_name`/`recipe_params` so FEAT-492 `_refresh` replays the recipe.

### KPICard prop mapping (M7, binding)
`label=name`, `value=aggregate(...)`, `unit`, `format`, `delta=delta_pct` when `format != percent` and `previous` not in {0, None} (else absolute delta), `trend`, `comparisonPeriod=comparison.label or derived`, `higherIsBetter` omitted when `True` / `false` / `null`, `icon`/`color` from the shape, `series=[{date, value}]` zero-filled at `series_grain` when the source returns a date column (`binding.date_column` or the start placeholder's column). No `periods` in v1.

### Known Risks / Gotchas
- **R1 — `EmbeddingIntentRouter` keys.** Runtime stores whatever key `add_route` receives (`self._routes[mode]`, L123) and `route()` returns that key; only the annotations say `OutputMode`. FEAT-755 widens them to labels. Until it lands, `MetricMatcher.configure` passes metric-id strings with a `# type: ignore[arg-type]` and a comment pointing here; the task packet re-checks the FEAT-755 state. Mitigation if FEAT-755 *renames* the API: `MetricMatcher` is the only caller — one file.
- **R2 — hint channel shape.** D2 feature-detection means a mismatch degrades to "abstain + stash", never to a wrong mode. The probe is pinned at task time (§8 Q1).
- **R3 — encoder cold start.** The first `resolve` on the embedding lane loads `multilingual-e5-small`; the alias fast path answers before that, and `enable_embeddings=False` is an explicit switch for CPU-poor hosts. The hook never blocks the event loop (`to_thread`).
- **R4 — false positives on short questions.** Threshold 0.85 was calibrated for presentation phrasing; metric names are shorter. The matcher applies the alias lane only to questions ≥ 2 tokens and the embedding lane only to questions ≥ 3 tokens; threshold is per-registry configurable. A match is *advisory* for the output mode and *never* overrides an explicit mode.
- **R5 — `RecipeRunner` fails open on falsy pctx** (its own docstring). `RecipeExecutor` refuses `None` from `pctx_provider`; the toolkit documents that the host must inject one (the `RefreshDashboardTool` precedent in `agents/flex_dashboard.py`).
- **R6 — tenant confusion between skills tenant and QuerySource tenant.** `MetricDefinition.tenant` is the *auth/namespace* tenant (FEAT-535/707); `QuerySlugSource.tenant` is the QuerySource *store* (routing). Field docstrings say so; the importer never copies one into the other.
- **R7 — TOOL_REGISTRY key collision.** `"metrics"` is free today (`parrot_tools/__init__.py:13-130`); `test_tool_registry_has_metrics` pins it.
- **R8 — shared checkout.** Sibling specs FEAT-752/755 are being authored concurrently; task decomposition must re-read them (they may land before this feature's worktree is cut) and update §8 Q1/Q2 before writing M8.

### External Dependencies
| Package | Version | Reason |
|---|---|---|
| `pydantic` | `>=2` (existing) | models |
| `pyyaml` | existing core dep (`a2ui/recipes/store.py:33`) | `metrics.yaml` |
| `sentence-transformers` / `numpy` | existing optional dep of `EmbeddingIntentRouter` | embedding lane (lazy; alias lane needs neither) |
| `asyncdb` | existing (ai-parrot-server) | Postgres store |
| `pandas` | existing | frame aggregation in M6/M7 |
No new dependency is added to any `pyproject.toml`.

---

## 8. Open Questions

> Questions that must be resolved before or during implementation.

- [ ] **Q1 — FEAT-755 hint carrier.** The brainstorm says the hint "rides on the request (`ctx`/kwarg `a2ui_component`)" and that the hook "returns `(A2UI, hint)`". Which is it on the wire — a tuple return from `_resolve_output_mode`, or `OutputMode.A2UI` + `ctx.kwargs["a2ui_component"]`? M8's `_hint_channel_available()` probe and return form are pinned to FEAT-755's merged spec at task time. — *Owner: Jesus Lara (FEAT-755 author)*
- [ ] **Q2 — FEAT-752 protocol.** Exact `SuggestionProvider` method name/signature and chip model import path. If FEAT-752 has not merged when M8 is scheduled, M8 ships the mixin only and the provider task is blocked on FEAT-752. — *Owner: Jesus Lara (FEAT-752 author)*
- [ ] **Q3 — HTTP writes in v1 (D5).** Confirm `POST`/`PUT` gated by `may_author` is wanted now, or defer all writes to v2 and ship read-only. — *Owner: Jesus Lara*
- [ ] **Q4 — Global definitions over HTTP.** D5 requires `is_superuser` to create a `tenant=None` definition. Should `may_administer` suffice? — *Owner: Jesus Lara*
- [ ] **Q5 — Proximity Staffing row.** Its recipe path is a brace set (`/proximity_staffing/{store_layer,employee_layer,coverage}`); the importer maps it to `MapShape` over `coverage`. Keep, or exclude from the import and leave it to the `/widget` skill? — *Owner: Jesus Lara*
- [ ] **Q6 — Package name.** `parrot/metrics/` vs `parrot/knowledge/metrics/` (business-knowledge sibling of ontology/okf). `parrot/metrics/` chosen for discoverability; confirm it will not be confused with observability metrics. — *Owner: Jesus Lara*
- [ ] **Q7 — Should `MetricRoutingMixin` be mixed into `PandasAgent` by default** (as `IntentRouterMixin` is, `data.py:338`) with `metric_registry=None`, so hosts only pass a registry? Zero behaviour change either way; default-mixed means one less MRO decision for authors. — *Owner: Jesus Lara*
- [ ] **Q8 — Threshold for the metric lane.** Start at the FEAT-224 0.85 and sweep on the Flex vocabulary (12 KPIs × EN/ES phrases) during M3, record the result in `docs/outputs/metric-registry.md`. — *Owner: implementer of M3*

---

## 9. Design Research Cross-Check

> Independent design opinion from the `codex` seat over the **accepted exploration
> doc** (never over this spec). Model: `<model>` · Status: completed | skipped (<reason>)
> · Transcript: `sdd/state/<FEAT-ID>/design_research/`
> Every row is a suggestion the reviewer made; the disposition is the spec author's
> call (CONFIRM = folded into the spec, REJECT = reason recorded, ESCALATE = §8 question).

Status: skipped (no accepted exploration document — spec authored from the NAV-10382 ticket review)

| # | Suggestion (kind) | Disposition | Reason | Landed in |
|---|---|---|---|---|

Summary: **0** confirmed · **0** rejected · **0** escalated.

---

## Worktree Strategy

- **Isolation**: ONE feature worktree `feat-FEAT-756-metric-definition-registry` (from `origin/dev`); the `sdd-coder` engine gives each task its own sub-worktree inside it.
- **Module dependency graph** (edges = imports/uses, evidence in §3):
  - M2 → M1; M3 → M1, M2; M4 → M1, M2 (protocol); M6 → M1, M7 (`ResolvedPeriod`); M7 → M1; M5 → M1, M3, M6, M7; M8 → M1, M3 (+ FEAT-755 / FEAT-752 contracts); M9 → M1, M4; M10 → M5, M8, M9.
  - No edge between: M4 ‖ M3/M5/M6/M7/M8; M7 ‖ M3/M4/M8; M9 ‖ M5/M8. After M1 lands, {M2, M7} run concurrently; after M2, {M3, M4} concurrently; after M3+M7, {M5+M6, M8}; M9 after M4.
- **Shared files** (tasks serialized): `parrot_tools/__init__.py` (M10 only), `bots/mixins/__init__.py` (M10 only), `manager.py` (M10 only); `parrot/metrics/__init__.py` exports are written by M1 and appended by M2/M3 in dependency order (one task each, sequential).
- **Exclusive resources**: none (`parallel: true` for every task; no `pyproject.toml` / `uv.lock` change; no `pnpm generate`).
- **Cross-feature dependencies**: M8's FEAT-755 form and FEAT-752 provider depend on those specs landing; everything else is independent of them. FEAT-598/611/636 (linked surfaces, python transforms) and FEAT-707 (per-tenant skills) are merged on `dev`.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-10-27 | Jesus Lara | Initial draft from the NAV-10382 review; verified against `b9417f4a0` |
| 0.2 | 2026-10-27 | Jesus Lara | Approved for `/sdd-task`. Q1 resolved: FEAT-755 is on `dev` — hook returns `set_output_shape(ctx, OutputShape(OutputMode.A2UI, component))` (`registry/routing/route_labels.py:97`). Q2 pinned to the FEAT-752 spec's `SuggestionProvider` (provider task blocked until FEAT-752 merges). Q3–Q7 take the spec defaults (POST/PUT now; `is_superuser` for globals; keep Proximity row; `parrot/metrics/`; no default mix into `PandasAgent`). |
