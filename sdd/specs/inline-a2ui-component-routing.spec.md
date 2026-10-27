---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
# projects: parts of the codebase this doc concerns. Use `packages/*` dir names
#   (ai-parrot, ai-parrot-server, parrot-formdesigner, …) or an area
#   (sdd-tooling, dev-loop, admin-ui, docs, ci). Unknown values warn, not fail.
projects: [ai-parrot, ai-parrot-server, ai-parrot-visualizations]
# tags: free-form kebab-case keywords for organizing specs (e.g. memory, mcp).
tags: [a2ui, output-mode, intent-router, inline-widgets, kpicard, phrase-bank]
# e2e: optional deterministic-E2E-gate policy metadata (FEAT-581). Absent
#   entirely (the default for every spec written before this feature) means
#   the generated e2e-plan.md's policy defaults to `optional` when loaded.
#   `policy` MUST be exactly `required`, `optional` or `none` — an
#   unrecognized value fails plan loading closed, it is never coerced to a
#   default. `scenario_ids` are the plan's stable `ScenarioSpec.id` values,
#   kept in sync with the "### E2E Scenarios" subsection below (§4). Omit
#   this whole key for a feature with no E2E surface.
# e2e:
#   policy: optional
#   scenario_ids: []
---

# Feature Specification: Inline A2UI Component Routing

**Feature ID**: FEAT-755
**Date**: 2026-10-27
**Author**: Jesus Lara
**Status**: draft
**Target version**: TBD (next minor)

> **Source**: accepted brainstorm
> [`sdd/proposals/output-mode-intent-router.brainstorm.md`](../proposals/output-mode-intent-router.brainstorm.md)
> (rev 2, 2026-10-27 — re-scoped to A2UI component routing; rev 1 was realized by
> FEAT-224). Recommended Option A is carried forward unchanged in spirit.

---

## 1. Motivation & Business Requirements

> Why does this feature exist? What problem does it solve?

### Problem Statement

Inline chat answers can be routed, from the user's phrasing alone, to exactly
three structured shapes — `structured_chart`, `structured_table`,
`structured_map` — because the FEAT-224 phrase bank
`DEFAULT_OUTPUT_MODE_ROUTES` (`parrot/bots/data.py:297-337`) only knows those
three `OutputMode` values. Meanwhile the server-side A2UI v1.0 catalog already
defines richer display-only components — `KPICard` (`catalog/parrot/kpicard.py:15`),
`InfoCard` (`infocard.py:18`), `Timeline` (`timeline.py:16`) and the viz-core
`Graph` (`catalog/viz_core/graph.py:63`, FEAT-529) — and the formats registry
already declares the per-kind legacy modes superseded: *"OutputMode.CARD →
A2UI with the InfoCard/KPICard catalog components"*
(`parrot/outputs/formats/__init__.py:15-27`). Nothing bridges the two:

1. **No router target.** `output_mode_routes` keys are `OutputMode` *values*
   (`registry/capabilities/models.py:216-222`), `EmbeddingIntentRouter.add_route()`
   takes an `OutputMode` (`embedding_router.py:108`), `RouteScore.mode` is a bare
   `Optional[OutputMode]` (`:37-54`) and `_resolve_output_mode()` returns one
   (`bots/mixins/intent_router.py:209`). There is no way to say "route to
   `OutputMode.A2UI` *with component KPICard*".
2. **No catalog-driven emitter for a chat turn.** `STRUCTURED_CHART` works because
   a registered system prompt (`structured_chart.py:40`, injected at
   `data.py:1418`) makes the LLM author a validated config in the single main
   turn, and `StructuredOutputBase._route_envelope()` dual-emits the A2UI
   envelope (`structured_base.py:87-199`). For `OutputMode.A2UI` the agent has
   **no renderer at all**: `PandasAgent.ask()` degrades A2UI to `DEFAULT` when no
   tool produced a surface (`data.py:1955-1966`), and the only LLM producer
   (`outputs/a2ui/producer.py:191`, `generate_envelope`) is a *separate* free-form
   call, not the data-producing main turn.
3. **Phrase bank is a code constant.** `DEFAULT_OUTPUT_MODE_ROUTES` is only
   overridable by passing an `IntentRouterConfig` in Python
   (`data.py:898-903`); there is no per-agent / per-tenant data configuration
   the way skills have one (FEAT-707, `skills/tenancy.py`).
4. **No inline-eligibility signal.** The reference renderer infers widget vs
   dashboard from the root component (`ui/.../a2ui/a2ui-kind.ts:31-39`,
   `docs/frontend/agentdashboard-a2ui-reference.md` §6.2); the envelope never
   says "this was produced as an inline answer", so `ChatBubble.svelte` has no
   `a2ui` branch at all (its structured branches are `structured_chart` /
   `structured_table` / `structured_map` only, `ChatBubble.svelte:1149-1290`).

The trigger was the NAV-10382 review (2026-10-27): its first "How to test" step,
*"show me worked hours this month → KPI card"*, has **no server-side decider
today**.

**Affected**: every agent with `output_routing=True`, the ai-parrot-server
reference renderer (`packages/ai-parrot-server/ui/src/lib/components/agents/`),
navigator-frontend-next's AgentChat (consumer, out of scope), and the sibling
features FEAT-752 / FEAT-753 / FEAT-754 / FEAT-756, which all need the same
component-hint channel.

### Goals

Carried from rev 1 (still binding, realized by FEAT-224 and preserved here):

- **G1 — Decide before/at the turn.** The component is chosen *before* the main
  LLM turn so the LLM shapes the data for it in that single turn; no post-hoc
  forcing of a shape onto mismatched data.
- **G2 — Non-override.** An explicit caller `output_mode` (or an explicit
  `a2ui_component=` kwarg, or a `/trigger` skill) always wins; the router never
  overrides it. Precedence stays explicit > router > agent default
  (`abstract.py:4191-4210`).
- **G3 — Conservative.** Ambiguous → abstain → `DEFAULT`. Any router or emitter
  error → `DEFAULT`, never raise, never an empty bubble.
- **G4 — Reuse FEAT-224.** `EmbeddingIntentRouter` + `IntentRouterMixin` are
  extended additively; no parallel classifier.

New in rev 2:

- **G5 — No new `OutputMode` members per component.** The target is
  `OutputMode.A2UI` plus a *component hint* carried on the request context.
- **G6 — Catalog is the single source of truth.** The emitter derives its
  prompt and validation from the component's registered `ComponentDefinition`
  (`schema_` + `instructions`), never from a hand-written per-component prompt
  copy; a per-component *authoring-notes* constant may only add guidance on top.
- **G7 — Every emitted surface validates** against the Parrot/viz-core catalog
  allowlist with LLM-origin semantics and, lowered, against the Basic wire
  schema — exactly like every other emitter in the conformance suite.
- **G8 — Phrase bank configurable per agent and per tenant** as data
  (`routes.yaml`) merged over the code constant; invalid entries are skipped
  with a warning, never fatal.
- **G9 — Precedence chain stays open** for a metric-declared default shape
  (FEAT-756): the cooperative `_resolve_output_mode()` chain plus a public,
  documented hint channel are the hook; this spec defines the hook, not the
  registry.
- **G10 — Degradation.** A component the data cannot fill degrades to prose
  with a logged, machine-readable reason; text-only transports keep receiving
  `lower()`-based fallback text via `finalize_a2ui_response()`.
- **G11 — Reference renderer renders inline.** The ai-parrot-server UI renders
  `KPICard` / `InfoCard` / `Timeline` / `Graph` inside the chat bubble when the
  envelope carries the inline marker; frontend work in navigator-frontend-next is
  out of scope.

### Non-Goals (explicitly out of scope)

- **Rejected options B/C** (one new `OutputMode` + renderer per component;
  LLM self-declares the component under `DEFAULT`) — see brainstorm §Options.
- **FEAT-752 followup-suggestion-chips** — the `suggestions` field and any chip
  that carries an `a2ui_component` hint are designed there; this spec only
  guarantees the hint name (`a2ui_component`) and label grammar they consume.
- **FEAT-753 a2ui-mermaid-diagram** — the `MermaidDiagram` catalog component is
  designed there; it registers a route through the contract in §2 "Route
  registration contract", nothing else here changes for it.
- **FEAT-754 a2ui-c4-diagrams** — the C4 `kind` for `Graph` is designed there;
  `a2ui:Graph` routes and authoring notes here are kind-agnostic.
- **FEAT-756 metric-definition-registry** — the metric → default-shape resolver
  is designed there; this spec specifies only the hook it plugs into (§2 "Hook
  contract for FEAT-756"). No metric logic lives here.
- Rev 1's registry-level feasibility layer (`CapabilityRegistry.not_for`
  consulted by the router) — superseded by the emitter-local check (M6).
- Emitter wiring in `BaseBot.ask()` / `conversation()` (`bots/base.py:300`,
  `:1155`): those call sites receive the hint through the shared mixin, but the
  v1 catalog-driven emitter is wired into `PandasAgent.ask()` only, where the
  computed DataFrame lives. Extending emission to `BaseBot` is a follow-up.
- Interactive / action-bearing components (`requires_actions=True`), surface
  persistence, and the navigator-frontend-next AgentChat.
- Any new `OutputMode` member, any change to `parrot/clients/base.py`.

---

## 2. Architectural Design

### Overview

Option A from the brainstorm: **composite component routes on the existing
embedding router + one catalog-driven A2UI emitter**.

1. **Route keys gain a component dimension.** `output_mode_routes` accepts keys
   of the form `"a2ui:<ComponentName>"` next to plain `OutputMode` values. A new
   pure module `route_labels.py` owns the grammar (`make_route_label` /
   `parse_route_label` / `OutputShape`). `EmbeddingIntentRouter` keeps one label
   per route but the label becomes a `str`; `RouteScore` gains `label` and
   `component` (additive, defaulted). `configure_output_router()` validates
   every key — an `OutputMode` value **or** a composite label whose component is
   a registered, display-only catalog component — and warns+skips anything else
   (today's `ValueError` handling, `intent_router.py:195-201`).
2. **The hint rides on the request context.** `_resolve_output_mode()` still
   returns `Optional[OutputMode]` (every caller unchanged, `data.py:1350`,
   `base.py:300/1155`); a composite win returns `OutputMode.A2UI` and writes the
   component to `ctx.a2ui_component` (new `RequestContext` attribute next to
   `output_mode` / `intent_score`, `utils/helpers.py:41-42`). An explicit
   `ask(..., a2ui_component="KPICard")` kwarg wins over the router (G2).
3. **One catalog-driven emitter for `OutputMode.A2UI` + hint** (new
   `parrot/outputs/a2ui/inline/` package, core). At the prompt seam
   (`data.py:1418`) it injects a system-prompt addon built from the component's
   catalog schema + instructions + authoring notes (same contract style as
   `STRUCTURED_CHART_SYSTEM_PROMPT`: the LLM emits only the component config as
   a single JSON object, computing every figure itself). After the turn, right
   before the existing "A2UI requested but nothing rendered" fallback
   (`data.py:1960`), the emitter parses the JSON, runs the per-component
   feasibility check, builds the envelope with `build_surface(origin=LLM)`
   (which validates against the catalog), stamps the inline marker, serializes
   it onto `response.a2ui_envelope` and calls `finalize_a2ui_response()`. On any
   failure it degrades to prose (`DEFAULT`) with a reason in
   `response.metadata["a2ui_inline"]`.
4. **Phrase bank as data.** `route_bank.py` loads `<AGENTS_DIR>/<agent>/routes.yaml`
   and `<AGENTS_DIR>/<agent>/tenants/<tenant>/routes.yaml` (FEAT-707 tree,
   sibling of `skills/`), merges them over `DEFAULT_OUTPUT_MODE_ROUTES`
   (default ← agent ← tenant), and `configure_output_router()` builds one router
   per tenant bank sharing the single warm encoder. `_resolve_output_mode()`
   picks the tenant router from the FEAT-707 ContextVar / `ctx.kwargs["tenant"]`
   and falls back to the global one. The default bank gains EN/ES utterances for
   `a2ui:KPICard`, `a2ui:InfoCard`, `a2ui:Timeline`, `a2ui:Graph`.
5. **Inline-eligibility marker.** The emitter stamps the **surface-level**
   `createSurface.metadata.extensions.parrot_presentation =
   {"kind": "widget", "inline": true, "origin": "chat_turn", "component": "<Name>"}`
   (the `parrot_*` namespace mandated by `docs/outputs/a2ui-v1.md:140-162` and
   `outputs/a2ui/models.py:341-360`; surface-level like `parrot_data_sources`).
   The reference renderer's `inferSurfaceKind()` gives the marker precedence over
   the root-component heuristic, and `ChatBubble.svelte` renders an inline
   `A2UISurface` for `output_mode === "a2ui"` envelopes whose marker says
   `inline: true`.
6. **Hook for FEAT-756.** After the router abstains, `_resolve_output_mode()`
   chains `super()`; FEAT-756 overrides the same method, chains `super()` first
   and, when that abstains, returns `set_output_shape(ctx, OutputShape(OutputMode.A2UI, "<Component>"))`.
   Nothing else is needed: the channel is public, typed and documented on the
   base method.

### Component Diagram

```
                         CONFIGURE (once)                         REQUEST (per ask)
┌──────────────────────┐  ┌───────────────────────┐   ┌──────────────────────────────────┐
│ DEFAULT_OUTPUT_MODE_ │  │ route_bank.py          │   │ PandasAgent.ask(question, ctx,    │
│ ROUTES (data.py:297) │─►│ load/merge routes.yaml │   │   output_mode=DEFAULT,            │
│ + a2ui:* utterances  │  │ (agent ← tenants)      │   │   a2ui_component=None)            │
└──────────────────────┘  └──────────┬────────────┘   └──────────────┬───────────────────┘
                                     │ IntentRouterConfig            │ explicit? ─► skip router (G2)
                                     ▼                               ▼
                       ┌──────────────────────────────┐   ┌──────────────────────────────┐
                       │ IntentRouterMixin            │   │ _resolve_output_mode(q, ctx) │
                       │ .configure_output_router()   │   │  router(tenant|global).route │
                       │  validate labels             │──►│  RouteScore(label, component)│
                       │  (route_labels.py + catalog) │   │  ambiguous → LLM over labels │
                       │  global + per-tenant routers │   │  → OutputMode.A2UI +         │
                       │  (shared encoder)            │   │    ctx.a2ui_component        │
                       └──────────────────────────────┘   │  abstain → super() ──► FEAT-756
                                                          └──────────────┬───────────────┘
                                                                         ▼
                                                   _apply_default_output_mode (unchanged)
                                                                         ▼
                        ┌───────────────────────────────────────────────────────────────┐
                        │ inline/prompt.py  build_component_prompt(hint)                 │
                        │   catalog ComponentDefinition.schema_ + .instructions          │
                        │   + INLINE_AUTHORING_NOTES[hint]  ──► system prompt addon      │
                        └───────────────────────────────┬───────────────────────────────┘
                                                        ▼  main LLM turn (tools, DataFrame)
                        ┌───────────────────────────────────────────────────────────────┐
                        │ inline/emitter.py  emit_inline_component(response, hint)       │
                        │   extract JSON ─► feasibility.py ─► build_surface(origin=LLM) │
                        │   ─► stamp parrot_presentation ─► serialize ─►                 │
                        │   response.a2ui_envelope + finalize_a2ui_response()            │
                        │   failure ─► DEFAULT prose + metadata["a2ui_inline"].reason    │
                        └───────────────────────────────┬───────────────────────────────┘
                                                        ▼ handlers/agent.py passthrough (unchanged)
                        ┌───────────────────────────────────────────────────────────────┐
                        │ UI: a2ui-presentation.ts (marker) ─► a2ui-kind.ts precedence   │
                        │     ChatBubble.svelte `a2ui` inline branch ─► A2UISurface       │
                        └───────────────────────────────────────────────────────────────┘
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `EmbeddingIntentRouter` / `RouteScore` (`registry/routing/embedding_router.py:37,57`) | extends | labels become `str`; `RouteScore` gains defaulted `label`/`component`; new `route_label_scores()`; optional shared `encoder` |
| `IntentRouterConfig` (`registry/capabilities/models.py:208-238`) | extends | composite keys accepted in `output_mode_routes`; new `tenant_output_mode_routes` |
| `IntentRouterMixin` (`bots/mixins/intent_router.py:175,209,252`) | extends | label validation, per-tenant routers, hint on ctx, tie-breaker over labels |
| `RequestContext` (`utils/helpers.py:7,41-42`) | extends | new `a2ui_component` attribute (default `None`) |
| `AbstractBot._resolve_output_mode` / `_apply_default_output_mode` (`bots/abstract.py:4168,4191`) | documents | docstrings describe the hint channel and the FEAT-756 slot; behavior unchanged |
| `DEFAULT_OUTPUT_MODE_ROUTES`, `PandasAgent.configure/ask` (`bots/data.py:297,898-903,1350,1418,1513,1960`) | extends | new default utterances; route-bank loading; explicit kwarg; prompt addon; no forced `PandasAgentResponse` for A2UI+hint; emitter call |
| Catalog (`outputs/a2ui/catalog/__init__.py:209` `get_component`, `:743` `validate_envelope`) | reuses | `ComponentDefinition.schema_`/`instructions`/`requires_actions` drive prompt + allowlist |
| `build_surface` (`outputs/a2ui/builders.py:79`) | reuses | `origin=ProducerOrigin.LLM`, `surface_metadata=` carries the marker |
| `finalize_a2ui_response` (`outputs/a2ui/emission.py:18`) | reuses | sets `output_mode=A2UI` + text fallback for text-only transports |
| `serialize` (`outputs/a2ui/serialization.py:104`) | reuses | envelope → dict on `response.a2ui_envelope` |
| FEAT-707 tenancy (`skills/tenancy.py:26-48,82-84`) | reuses | `TENANTS_DIRNAME`, `validate_tenant_id`, `current_skill_tenant` locate the tenant `routes.yaml` and pick the tenant router |
| `AGENTS_DIR` (`conf.py:181`) + `_resolve_agents_dir` (`skills/mixin.py:290`) | reuses | agent root = `AGENTS_DIR / agent_id` (same convention as skills) |
| Reference renderer (`ui/.../canvas/a2ui/a2ui-kind.ts:31`, `ChatBubble.svelte:41,1149`, `features.ts:31`) | extends | marker precedence; inline `A2UISurface` branch behind `features.a2ui` |
| `handlers/agent.py` (`:2727-2729`, `:2874`) | none | `a2ui_envelope` passthrough already exists |
| Conformance suite (`tests/outputs/a2ui/conformance/test_all_emitters.py`) | extends | the inline emitter joins the swept emission points |

### Route registration contract (FEAT-753 / FEAT-754 and any future component)

A sibling feature makes a catalog component routable by doing **only** this:

1. Register the component with `@register_component("<Name>", requires_actions=False)`
   (any catalog id — `get_component(name)` resolves across catalogs,
   `catalog/__init__.py:209-250`; a name registered in more than one catalog
   must be disambiguated by that feature, not here).
2. Add utterances under the key `make_route_label("<Name>")` — i.e.
   `"a2ui:<Name>"` — to `DEFAULT_OUTPUT_MODE_ROUTES` (or to a `routes.yaml`).
3. Optionally add an entry to `INLINE_AUTHORING_NOTES["<Name>"]` (M6) when the
   catalog `instructions` are not enough for single-turn authoring.
4. Optionally extend `check_feasibility()` with a component-specific rule;
   unknown components default to "feasible when the config validates".

FEAT-754 (C4 kind for `Graph`) needs no route change: `a2ui:Graph` is
kind-agnostic and the authoring notes defer kind selection to the catalog
instructions.

### Hook contract for FEAT-756 (metric default shape)

- **Where**: override `_resolve_output_mode(self, query, ctx)` in a mixin placed
  *after* `IntentRouterMixin` in the MRO (so the router runs first) and *before*
  `AbstractBot` (the no-op terminal, `abstract.py:4168`).
- **How**: `resolved = await super()._resolve_output_mode(query, ctx)`; if
  `resolved is not None` return it unchanged (router wins); otherwise, on a
  metric match, `return set_output_shape(ctx, OutputShape(OutputMode.A2UI, "KPICard"))`
  (M1 helper: writes `ctx.a2ui_component`, returns the mode); otherwise
  `return None`.
- **Effective precedence** (G2/G9): explicit caller `output_mode` / explicit
  `a2ui_component` kwarg > router (mode + hint) > **metric default shape
  (FEAT-756)** > agent default (`_apply_default_output_mode`, unchanged).
- **Read side**: `get_component_hint(ctx)` is the only sanctioned reader; the
  emitter never inspects FEAT-756 state.

### Data Models

```python
# parrot/registry/routing/route_labels.py (new)
A2UI_LABEL_PREFIX: Final[str] = "a2ui:"

class OutputShape(NamedTuple):
    """A resolved output shape: an OutputMode plus an optional A2UI component hint."""
    mode: OutputMode
    component: Optional[str] = None

# parrot/registry/routing/embedding_router.py (modified)
class RouteScore(NamedTuple):
    mode: Optional[OutputMode]
    score: float
    runner_up: float
    ambiguous: bool
    label: Optional[str] = None       # NEW: raw route label ("structured_chart" | "a2ui:KPICard")
    component: Optional[str] = None   # NEW: component for composite labels, else None

# parrot/registry/routing/route_bank.py (new)
class RouteBankFile(BaseModel):
    """One `routes.yaml`: routes + merge policy + optional threshold overrides."""
    model_config = ConfigDict(extra="forbid")
    version: int = 1
    routes: dict[str, list[str]] = Field(default_factory=dict)
    replace: bool = False              # False: extend base utterances per key; True: replace the key
    threshold: Optional[float] = None  # overrides IntentRouterConfig.output_mode_threshold
    margin: Optional[float] = None     # overrides IntentRouterConfig.discrepancy_margin

class ResolvedRouteBanks(BaseModel):
    global_routes: dict[str, list[str]]
    tenant_routes: dict[str, dict[str, list[str]]] = Field(default_factory=dict)
    threshold: Optional[float] = None
    margin: Optional[float] = None
    sources: list[str] = Field(default_factory=list)   # files actually read, for logging

# parrot/registry/capabilities/models.py (modified, additive)
class IntentRouterConfig(BaseModel):
    output_mode_routes: dict[str, list[str]]  # keys: OutputMode value OR "a2ui:<Component>"
    tenant_output_mode_routes: dict[str, dict[str, list[str]]] = Field(default_factory=dict)  # NEW

# parrot/outputs/a2ui/inline/feasibility.py (new)
class FeasibilityResult(NamedTuple):
    feasible: bool
    reason: Optional[str] = None       # machine-readable, e.g. "kpicard_value_missing"

# parrot/outputs/a2ui/inline/emitter.py (new)
PRESENTATION_EXTENSION: Final[str] = "parrot_presentation"

class InlineEmitOutcome(NamedTuple):
    status: Literal["emitted", "degraded"]
    component: str
    reason: Optional[str] = None       # None when emitted; otherwise the degradation reason
    surface_id: Optional[str] = None

# Surface-level marker (createSurface.metadata.extensions)
# {"parrot_presentation": {"kind": "widget", "inline": true, "origin": "chat_turn", "component": "KPICard"}}

# AIMessage.metadata side-channel written by the emitter (both outcomes)
# response.metadata["a2ui_inline"] = {"component": "KPICard", "status": "degraded", "reason": "kpicard_value_missing"}
```

`routes.yaml` example (agent or tenant level):

```yaml
version: 1
replace: false
routes:
  "a2ui:KPICard":
    - "how many hours did we work this month"
    - "cuántas horas trabajamos este mes"
  structured_chart:
    - "plot weekly revenue"
```

### New Public Interfaces

```python
# parrot/registry/routing/route_labels.py
def make_route_label(component: str) -> str: ...
def parse_route_label(label: str) -> OutputShape: ...          # ValueError on unknown grammar
def is_inline_component(component: str) -> bool: ...           # registered + display-only
def set_output_shape(ctx: Any, shape: OutputShape) -> OutputMode: ...   # FEAT-756 entry point
def get_component_hint(ctx: Any) -> Optional[str]: ...

# parrot/registry/routing/route_bank.py
def load_route_bank(path: Path) -> Optional[RouteBankFile]: ...
def merge_route_banks(base: Mapping[str, Sequence[str]], *overlays: RouteBankFile) -> dict[str, list[str]]: ...
def resolve_route_banks(agent_root: Optional[Path], *, defaults, tenant_based: bool) -> ResolvedRouteBanks: ...

# parrot/registry/routing/embedding_router.py
class EmbeddingIntentRouter:
    def __init__(self, model=..., threshold=..., margin=..., *, encoder: Any | None = None) -> None: ...
    def add_route(self, label: OutputMode | str, utterances: list[str]) -> None: ...
    def route_label_scores(self, query: str) -> list[tuple[str, float]]: ...

# parrot/outputs/a2ui/inline
def build_component_prompt(component: str) -> str: ...
def check_feasibility(component: str, config: Mapping[str, Any], frame: Any | None) -> FeasibilityResult: ...
def extract_component_config(response: Any) -> Optional[dict[str, Any]]: ...
def emit_inline_component(response: Any, component: str, *, frame: Any | None = None,
                          surface_id: Optional[str] = None) -> InlineEmitOutcome: ...
def presentation_extension(component: str) -> dict[str, Any]: ...

# PandasAgent.ask() (data.py) — new keyword accepted through **kwargs
#   a2ui_component: Optional[str]  — explicit component hint; implies OutputMode.A2UI when
#                                    output_mode is DEFAULT/None; never overridden by the router.

# Reference UI (TypeScript)
export function getPresentation(surface: CreateSurface): PresentationExtension | null;
export function isInlinePresentation(envelope: A2UIEnvelope | null | undefined): boolean;
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
| M1: Route labels + hint channel | yes | grammar `a2ui:<Name>` fixed; `OutputShape`; `set_output_shape` writes `ctx.a2ui_component`; lazy catalog import; `ValueError` on bad grammar | — |
| M2: Router label support | yes | `_routes: dict[str, ndarray]`; `RouteScore` defaulted fields; `route_scores()` compat mapping (composite → `A2UI`); `route_label_scores()`; kw-only `encoder` | — |
| M3: Route bank loader + config field | yes | `RouteBankFile` (`extra="forbid"`); file names fixed; merge semantics in §7; `secure_path` containment; PyYAML `safe_load` | — |
| M4: Mixin wiring | yes | validation order fixed; per-tenant routers share encoder; tenant pick order fixed; tie-breaker keeps JSON key `output_mode` but accepts labels | — |
| M5: RequestContext + base docstrings | yes | one attribute; docstring text supplied by the task | — |
| M6: Inline emitter package | **partial** | prompt/feasibility/emitter contracts and failure codes fixed below | authoring-notes wording for `Graph` needs a human pass over a few real transcripts before freezing |
| M7: PandasAgent wiring | yes | six edit sites fixed (§6); degrade path mirrors `data.py:1960-1966` | — |
| M8: Reference renderer | yes | marker precedence rule; branch placement; gate `features.a2ui`; Svelte 5 runes | — |
| M9: Docs + conformance | yes | row in `a2ui-v1.md` table; new doc; fixture added to `test_all_emitters.py` | — |

### Module 1: Route labels & hint channel
- **Path**: `packages/ai-parrot/src/parrot/registry/routing/route_labels.py` (new)
- **Responsibility**: the one place that knows the composite-label grammar and
  how a component hint travels on a `RequestContext`. Pure; the only import of
  the catalog is lazy (inside `is_inline_component`) so `registry.routing`
  stays light.
- **Depends on**: `parrot.models.outputs.OutputMode`; lazily
  `parrot.outputs.a2ui.catalog.get_component`.
- **Interface Skeleton** *(signatures + docstrings only — bodies belong to task blueprints, FEAT-545)*:
  ```python
  # parrot/registry/routing/route_labels.py  (new)
  from parrot.models.outputs import OutputMode  # verified: parrot/models/outputs.py:23

  A2UI_LABEL_PREFIX: Final[str] = "a2ui:"

  class OutputShape(NamedTuple):
      """Resolved output shape: ``mode`` plus an optional A2UI ``component`` hint."""
      mode: OutputMode
      component: Optional[str] = None

  def make_route_label(component: str) -> str:
      """Return ``"a2ui:<component>"``; raises ``ValueError`` on an empty/whitespace name."""

  def parse_route_label(label: str) -> OutputShape:
      """Parse a phrase-bank key.

      ``"structured_chart"`` -> ``OutputShape(OutputMode.STRUCTURED_CHART)``;
      ``"a2ui:KPICard"`` -> ``OutputShape(OutputMode.A2UI, "KPICard")``.
      Raises ``ValueError`` for an unknown OutputMode value or a malformed composite.
      Does NOT consult the catalog (see :func:`is_inline_component`).
      """

  def is_inline_component(component: str) -> bool:
      """True when ``component`` is registered in any catalog with ``requires_actions=False``.

      Lazily imports ``parrot.outputs.a2ui.catalog.get_component``  # verified: catalog/__init__.py:209
      and reads ``RegisteredComponent.definition.requires_actions``  # verified: catalog/base.py:234-248,293-297
      Returns False (never raises) on ``KeyError``/``CatalogError``.
      """

  def set_output_shape(ctx: Any, shape: OutputShape) -> OutputMode:
      """Write ``shape.component`` to ``ctx.a2ui_component`` (when ``ctx`` is not None) and return ``shape.mode``.

      Public entry point for cooperative ``_resolve_output_mode`` overrides (FEAT-756).
      """

  def get_component_hint(ctx: Any) -> Optional[str]:
      """Return ``ctx.a2ui_component`` or ``None``; tolerant of ``ctx is None`` and duck-typed contexts."""
  ```

### Module 2: Router label support
- **Path**: `packages/ai-parrot/src/parrot/registry/routing/embedding_router.py` (modify)
- **Responsibility**: keep the engine pure and additive while allowing string
  labels. Plain `OutputMode` routes behave byte-for-byte as today; the existing
  positional construction `RouteScore(None, -1.0, -1.0, False)`
  (`embedding_router.py:168`, pinned by `tests/routing/test_embedding_router.py:83`)
  keeps working thanks to defaulted trailing fields.
- **Depends on**: Module 1.
- **Interface Skeleton** *(signatures + docstrings only — bodies belong to task blueprints, FEAT-545)*:
  ```python
  # modifies parrot/registry/routing/embedding_router.py:37-54 (RouteScore), :65-88 (__init__), :108-173
  class RouteScore(NamedTuple):  # verified: embedding_router.py:37
      mode: Optional[OutputMode]
      score: float
      runner_up: float
      ambiguous: bool
      label: Optional[str] = None      # NEW — raw winning label
      component: Optional[str] = None  # NEW — component for "a2ui:<Name>" labels

  class EmbeddingIntentRouter:  # verified: embedding_router.py:57
      def __init__(self, model: str = "intfloat/multilingual-e5-small", threshold: float = 0.85,
                   margin: float = 0.05, *, encoder: Any | None = None) -> None:  # verified: :65-69 (+ kw-only encoder)
          """``encoder``: an already-loaded SentenceTransformer shared across per-tenant routers; ``None`` keeps lazy loading."""

      def add_route(self, label: OutputMode | str, utterances: list[str]) -> None:  # verified: :108
          """Encode utterances under ``label`` (an OutputMode is stored as its ``.value``). Empty lists are ignored (unchanged)."""

      def route_label_scores(self, query: str) -> list[tuple[str, float]]:
          """Every label's max-cosine score, sorted desc; ``[]`` when no routes. CPU-bound (to_thread)."""

      def route_scores(self, query: str) -> list[tuple[OutputMode, float]]:  # verified: :125
          """Compat view of :meth:`route_label_scores`: labels parsed to OutputMode (composite -> OutputMode.A2UI, may repeat)."""

      def route(self, query: str) -> RouteScore:  # verified: :152
          """As today, plus ``label``/``component`` filled from the winning label (``mode`` is ``OutputMode.A2UI`` for composites)."""
  ```

### Module 3: Route bank loader & config field
- **Path**: `packages/ai-parrot/src/parrot/registry/routing/route_bank.py` (new);
  `packages/ai-parrot/src/parrot/registry/capabilities/models.py` (modify)
- **Responsibility**: turn `routes.yaml` files into merged phrase banks; never
  raises for a bad file (warning + skip). Tenant discovery mirrors FEAT-707:
  `agent_root/tenants/<tenant>/routes.yaml`, tenant ids validated with
  `validate_tenant_id`, paths contained with `secure_path`.
- **Depends on**: Module 1; `parrot.skills.tenancy`, `parrot.utils.paths`, PyYAML
  (already a core dependency, `packages/ai-parrot/pyproject.toml:58`).
- **Interface Skeleton** *(signatures + docstrings only — bodies belong to task blueprints, FEAT-545)*:
  ```python
  # parrot/registry/routing/route_bank.py  (new)
  from parrot.skills.tenancy import TENANTS_DIRNAME, validate_tenant_id  # verified: skills/tenancy.py:26,30
  from parrot.utils.paths import secure_path  # verified: utils/paths.py:52

  ROUTES_FILENAME: Final[str] = "routes.yaml"

  class RouteBankFile(BaseModel):
      """Schema of one ``routes.yaml`` (``extra="forbid"``)."""

  class ResolvedRouteBanks(BaseModel):
      """Merged global bank + per-tenant banks + optional threshold/margin overrides."""

  def agent_routes_path(agent_root: Path) -> Path:
      """``agent_root/routes.yaml``."""

  def tenant_routes_path(agent_root: Path, tenant: str) -> Path:
      """``secure_path(agent_root, TENANTS_DIRNAME, validate_tenant_id(tenant), ROUTES_FILENAME)``; raises ValueError like tenant_skills_dir."""

  def load_route_bank(path: Path) -> Optional[RouteBankFile]:
      """``yaml.safe_load`` + model validation. Missing file -> None; invalid file -> warning + None (never raises)."""

  def merge_route_banks(base: Mapping[str, Sequence[str]], *overlays: RouteBankFile) -> dict[str, list[str]]:
      """Left-to-right merge: per key, ``replace=False`` extends (dedup, order kept), ``replace=True`` substitutes. Keys are NOT validated here."""

  def resolve_route_banks(agent_root: Optional[Path], *, defaults: Mapping[str, Sequence[str]],
                          tenant_based: bool) -> ResolvedRouteBanks:
      """defaults <- agent file <- (per discovered tenant) tenant file. ``agent_root=None`` returns defaults only."""

  # modifies parrot/registry/capabilities/models.py:216-222
  class IntentRouterConfig(BaseModel):  # verified: models.py:149
      output_mode_routes: dict[str, list[str]]  # description now: "OutputMode value or 'a2ui:<Component>' -> utterances"
      tenant_output_mode_routes: dict[str, dict[str, list[str]]] = Field(default_factory=dict)  # NEW
  ```

### Module 4: Mixin wiring (labels, tenants, hint)
- **Path**: `packages/ai-parrot/src/parrot/bots/mixins/intent_router.py` (modify)
- **Responsibility**: validate labels at CONFIGURE, build the global and
  per-tenant routers sharing one encoder, resolve to `(mode, hint)` at REQUEST,
  tie-break over labels.
- **Depends on**: Modules 1–3.
- **Interface Skeleton** *(signatures + docstrings only — bodies belong to task blueprints, FEAT-545)*:
  ```python
  # modifies parrot/bots/mixins/intent_router.py:151 (state), :175-207, :209-250, :252-305
  class IntentRouterMixin:  # verified: intent_router.py:123
      _output_router: Optional[EmbeddingIntentRouter]                 # verified: :151
      _tenant_output_routers: dict[str, EmbeddingIntentRouter]        # NEW, set in __init__ (:141-152)

      def configure_output_router(self, config: IntentRouterConfig) -> None:  # verified: :175
          """CONFIGURE: validate each key with ``parse_route_label`` + ``is_inline_component`` (composite only);
          invalid -> ``logger.warning`` + skip (today's ValueError branch, :195-201). Build the global router,
          then one router per ``config.tenant_output_mode_routes`` entry passing the global router's encoder.
          Still a no-op unless ``enable_output_mode_routing``."""

      def _select_output_router(self, ctx: Any) -> Optional[EmbeddingIntentRouter]:
          """Tenant pick order: ``current_skill_tenant()`` (skills/tenancy.py:82) -> ``ctx.kwargs.get("tenant")`` -> global."""

      async def _resolve_output_mode(self, query: str, ctx: Any) -> "Optional[OutputMode]":  # verified: :209
          """As today, over labels. A composite win returns ``set_output_shape(ctx, OutputShape(A2UI, component))``;
          a plain win returns the OutputMode; abstain chains ``super()`` (unchanged)."""

      async def _llm_disambiguate_output_mode(self, query: str, candidates: "list[str]") -> "Optional[str]":  # verified: :252
          """Candidates/return are route LABELS now; prompt JSON key stays ``output_mode`` (plain labels equal
          OutputMode values, so existing stubs returning ``{"output_mode": "structured_table"}`` still work).
          Accepts only a value that is one of the candidates; abstains otherwise (unchanged policy)."""
  ```

### Module 5: RequestContext attribute & base docstrings
- **Path**: `packages/ai-parrot/src/parrot/utils/helpers.py` (modify);
  `packages/ai-parrot/src/parrot/bots/abstract.py` (modify, docstrings only)
- **Responsibility**: make the hint channel a first-class, documented context
  attribute; document the FEAT-756 slot on the base method.
- **Depends on**: Module 1 (for the docstring cross-reference only; no import).
- **Interface Skeleton** *(signatures + docstrings only — bodies belong to task blueprints, FEAT-545)*:
  ```python
  # modifies parrot/utils/helpers.py:41-42
  class RequestContext:  # verified: utils/helpers.py:7
      output_mode: Any = None      # verified: :41
      intent_score: Any = None     # verified: :42
      a2ui_component: Optional[str] = None  # NEW — FEAT-755 component hint ("KPICard"), set by the router / explicit kwarg

  # modifies parrot/bots/abstract.py:4168-4189 and :4191-4210 (docstrings only; bodies untouched)
  async def _resolve_output_mode(self, query: str, ctx: "Optional[RequestContext]") -> "Optional[OutputMode]":  # verified: abstract.py:4168
      """...adds: a composite route resolves to ``OutputMode.A2UI`` with the component on ``ctx.a2ui_component``
      (``parrot.registry.routing.route_labels.set_output_shape``); overrides that chain ``super()`` first may
      fill the slot between router and agent default (FEAT-756)."""

  def _apply_default_output_mode(self, output_mode: OutputMode) -> OutputMode:  # verified: abstract.py:4191
      """...precedence text extended: explicit > router (mode + hint) > metric default shape (FEAT-756) > agent default."""
  ```

### Module 6: Inline emitter package (prompt · feasibility · emitter)
- **Path**: `packages/ai-parrot/src/parrot/outputs/a2ui/inline/__init__.py`,
  `prompt.py`, `feasibility.py`, `emitter.py` (new)
- **Responsibility**: the single catalog-driven authoring path for a display-only
  component in an inline answer. Obeys the a2ui one-way import rule
  (`builders.py:14`): no agents, no clients.
- **Depends on**: catalog (`get_component`, `ProducerOrigin`), `build_surface`,
  `serialize`, `finalize_a2ui_response`, `models.SurfaceMetadata/Extensions`;
  `StructuredOutputBase._extract_json_code`-equivalent logic (re-implemented
  locally — that helper lives in the visualizations satellite,
  `structured_base.py:202`, and core must not import it).
- **Interface Skeleton** *(signatures + docstrings only — bodies belong to task blueprints, FEAT-545)*:
  ```python
  # parrot/outputs/a2ui/inline/prompt.py  (new)
  from parrot.outputs.a2ui.catalog import get_component  # verified: catalog/__init__.py:209

  INLINE_COMPONENTS: Final[frozenset[str]] = frozenset({"KPICard", "InfoCard", "Timeline", "Graph"})  # v1 allowlist
  INLINE_AUTHORING_NOTES: Final[dict[str, str]] = {"Graph": "..."}  # Graph-only in v1; others rely on catalog instructions

  def build_component_prompt(component: str) -> str:
      """System-prompt addon for ``component``: header ("INLINE A2UI <Name> OUTPUT MODE"), the catalog
      ``definition.schema_`` as JSON, ``definition.instructions``, ``INLINE_AUTHORING_NOTES.get(component, "")``,
      and the fixed rules (single JSON object, no prose/fences, compute every figure yourself, never emit
      rows/positions/actions). Raises ``KeyError`` when the component is not registered."""

  # parrot/outputs/a2ui/inline/feasibility.py  (new)
  class FeasibilityResult(NamedTuple):
      feasible: bool
      reason: Optional[str] = None

  def check_feasibility(component: str, config: Mapping[str, Any], frame: Any | None) -> FeasibilityResult:
      """Emitter-local data-feasibility rules (rev 1 layer-2, per component, no CapabilityRegistry coupling):
      KPICard -> ``value`` present and scalar (number or non-empty str) -> else ``kpicard_value_missing``;
      Timeline -> >=1 event with ``title`` -> else ``timeline_events_missing``;
      InfoCard -> non-empty ``title`` -> else ``infocard_title_missing``;
      Graph -> >=1 node and >=0 edges whose endpoints exist -> else ``graph_nodes_missing`` / ``graph_edge_dangling``;
      unknown component -> feasible (schema validation decides)."""

  # parrot/outputs/a2ui/inline/emitter.py  (new)
  from parrot.outputs.a2ui.builders import build_surface  # verified: builders.py:79
  from parrot.outputs.a2ui.catalog import ProducerOrigin  # verified: catalog/__init__.py:59, catalog/base.py:99
  from parrot.outputs.a2ui.models import SurfaceMetadata, Extensions  # verified: models.py:341,378
  from parrot.outputs.a2ui.serialization import serialize  # verified: serialization.py:104
  from parrot.outputs.a2ui.emission import finalize_a2ui_response  # verified: emission.py:18

  PRESENTATION_EXTENSION: Final[str] = "parrot_presentation"

  class InlineEmitOutcome(NamedTuple):
      status: Literal["emitted", "degraded"]
      component: str
      reason: Optional[str] = None
      surface_id: Optional[str] = None

  def presentation_extension(component: str) -> dict[str, Any]:
      """``{"kind": "widget", "inline": True, "origin": "chat_turn", "component": component}``."""

  def extract_component_config(response: Any) -> Optional[dict[str, Any]]:
      """Config dict from ``response.structured_output`` (dict/BaseModel) else the first JSON object in
      ``response.output`` / ``response.content`` (fenced or bare). ``None`` when nothing parses."""

  def emit_inline_component(response: Any, component: str, *, frame: Any | None = None,
                            surface_id: Optional[str] = None) -> InlineEmitOutcome:
      """Never raises. Steps: component in allowlist? -> extract config -> feasibility -> ``build_surface(component,
      config, surface_id=surface_id or f"{component.lower()}-{uuid4().hex[:8]}", origin=ProducerOrigin.LLM,
      surface_metadata=SurfaceMetadata(extensions=Extensions(root={PRESENTATION_EXTENSION: ...})))`` (validates) ->
      ``response.a2ui_envelope = serialize(surface)`` -> ``finalize_a2ui_response(response)`` ->
      ``response.metadata["a2ui_inline"]`` written on BOTH outcomes. Degrade reasons: ``component_not_inline``,
      ``config_unparseable``, the feasibility reasons, ``catalog_validation_failed``, ``unexpected_error``."""
  ```

### Module 7: PandasAgent wiring
- **Path**: `packages/ai-parrot/src/parrot/bots/data.py` (modify)
- **Responsibility**: default bank utterances for the four routes; load route
  banks at configure; honor the explicit kwarg; inject the component prompt; skip
  the forced `PandasAgentResponse`; call the emitter before the existing A2UI
  fallback; degrade like the structured modes do.
- **Depends on**: Modules 1, 3, 4, 6.
- **Interface Skeleton** *(signatures + docstrings only — bodies belong to task blueprints, FEAT-545)*:
  ```python
  # modifies parrot/bots/data.py
  DEFAULT_OUTPUT_MODE_ROUTES: Dict[str, List[str]]  # verified: data.py:297 — adds "a2ui:KPICard" / "a2ui:InfoCard" /
                                                    # "a2ui:Timeline" / "a2ui:Graph" with >=8 EN + >=8 ES utterances each

  class PandasAgent(IntentRouterMixin, BasicAgent):  # verified: data.py:338
      async def configure(self, app=None) -> None:
          """At :898-903: when routing is on and no explicit config was given, call
          ``resolve_route_banks(self._resolve_agents_dir() / agent_id, defaults=DEFAULT_OUTPUT_MODE_ROUTES,
          tenant_based=getattr(self, "tenant_based", False))`` (route_bank.py) and build the IntentRouterConfig from it
          (threshold/margin overrides applied); an explicit ``output_routing_config`` still takes precedence."""

      async def ask(self, question, ..., output_mode=None, ..., **kwargs) -> AIMessage:  # verified: data.py:1265-1278
          """New kwarg ``a2ui_component`` (popped from kwargs): explicit hint -> ``set_output_shape(ctx, OutputShape(A2UI, hint))``
          and the router is skipped (G2). After resolution (:1350-1358): ``component_hint = get_component_hint(ctx)``.
          Prompt seam (:1418): for ``output_mode == A2UI and component_hint`` append ``build_component_prompt(hint)``.
          Structured forcing (:1513): for A2UI+hint do NOT force ``PandasAgentResponse`` (free JSON, structured_chart style).
          Before the fallback at :1960: ``if output_mode == A2UI and component_hint and response.a2ui_envelope is None:
          outcome = emit_inline_component(response, hint, frame=<response.data if DataFrame>)``; ``degraded`` -> the
          existing fallback runs (logs the outcome.reason)."""
  ```

### Module 8: Reference renderer (ai-parrot-server UI)
- **Path**: `packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/a2ui-presentation.ts` (new),
  `.../a2ui/a2ui-kind.ts` (modify), `.../agents/ChatBubble.svelte` (modify)
- **Responsibility**: read the marker, let it override the kind heuristic, and
  render inline. Svelte 5 runes, gated by `features.a2ui`
  (`ui/src/lib/features.ts:31`), lazy-imported like the other heavy renderers
  (`ChatBubble.svelte:39-62`). No change to generated types: the marker lives
  inside the envelope JSON, which is already typed loosely as
  `metadata.extensions` (`a2ui-types.ts:79`).
- **Depends on**: Module 6 (marker shape).
- **Interface Skeleton** *(signatures + docstrings only — bodies belong to task blueprints, FEAT-545)*:
  ```ts
  // canvas/a2ui/a2ui-presentation.ts  (new)
  export const PRESENTATION_EXTENSION = 'parrot_presentation';
  export interface PresentationExtension { kind: SurfaceKind; inline: boolean; origin: 'chat_turn' | string; component: string; }
  /** The surface-level `metadata.extensions.parrot_presentation`, or null when absent/malformed. */
  export function getPresentation(surface: CreateSurface): PresentationExtension | null;
  /** True when the envelope was produced as an inline chat answer (`inline === true`). */
  export function isInlinePresentation(envelope: A2UIEnvelope | null | undefined): boolean;

  // modifies canvas/a2ui/a2ui-kind.ts:31
  export function inferSurfaceKind(surface: CreateSurface): SurfaceKind;  // verified: a2ui-kind.ts:31 — marker `kind` wins; heuristic otherwise

  // modifies agents/ChatBubble.svelte:41 (lazy import of A2UISurface) and :1149 (new `{:else if}` branch before structured_chart)
  // {:else if features.a2ui && message.output_mode === "a2ui" && isInlinePresentation(message.a2ui_envelope)} -> <A2UISurface envelope=... />
  ```

### Module 9: Docs & conformance
- **Path**: `docs/outputs/inline-a2ui-component-routing.md` (new);
  `docs/outputs/a2ui-v1.md` (modify: `parrot_presentation` row);
  `packages/ai-parrot/tests/outputs/a2ui/conformance/test_all_emitters.py` (modify: inline fixture)
- **Responsibility**: document the route grammar, `routes.yaml`, the marker and
  the FEAT-756 hook; make the inline emitter a swept emission point.
- **Depends on**: Modules 1–8.
- **Interface Skeleton** *(signatures + docstrings only — bodies belong to task blueprints, FEAT-545)*:
  ```python
  # modifies tests/outputs/a2ui/conformance/test_all_emitters.py (near `def _assert_conformant(`)
  def test_inline_emitter_envelopes_conform() -> None:
      """For each of KPICard/InfoCard/Timeline/Graph: ``emit_inline_component`` on a SimpleNamespace response with a
      valid config -> ``_assert_conformant(response.a2ui_envelope["createSurface"])`` (catalog + lowered wire)."""
  ```

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_parse_route_label_plain_and_composite` | M1 | `"structured_chart"` → `(STRUCTURED_CHART, None)`; `"a2ui:KPICard"` → `(A2UI, "KPICard")`; bad grammar → `ValueError` |
| `test_is_inline_component_rejects_action_bearing_and_unknown` | M1 | registered display-only → True; unknown → False; a component registered with `requires_actions=True` (test fixture via `register_component`/`unregister_component`) → False |
| `test_set_get_output_shape_roundtrip` | M1 | writes `ctx.a2ui_component`, returns mode; `ctx=None` tolerated |
| `test_add_route_accepts_str_label_and_route_fills_component` | M2 | composite label wins → `mode is OutputMode.A2UI`, `component == "KPICard"` (skips offline, like `test_embedding_router.py`) |
| `test_route_score_positional_compat` | M2 | `RouteScore(None, -1.0, -1.0, False)` still equal to the abstain value |
| `test_route_scores_compat_maps_composites_to_a2ui` | M2 | `route_scores()` yields `OutputMode.A2UI` for composite labels |
| `test_shared_encoder_not_reloaded` | M2 | two routers built with `encoder=` share the object; `_ensure_encoder` not called |
| `test_load_route_bank_missing_invalid_valid` | M3 | missing → `None`; `extra` key → warning + `None`; valid → model |
| `test_merge_extend_vs_replace_dedup_order` | M3 | extend keeps base order and dedups; `replace=True` substitutes per key |
| `test_resolve_route_banks_tenant_tree` | M3 | `tmp_path` agent root with `routes.yaml` + `tenants/acme/routes.yaml`; reserved tenant dir ignored |
| `test_configure_skips_invalid_labels_with_warning` | M4 | unknown mode / unknown component / action-bearing component skipped, caplog warning, router still built |
| `test_resolve_composite_sets_ctx_hint` | M4 | stubbed router returning a composite `RouteScore` → `OutputMode.A2UI` + `ctx.a2ui_component` |
| `test_tenant_router_selection_order` | M4 | ContextVar tenant → ctx kwarg tenant → global |
| `test_tie_breaker_over_labels_accepts_only_candidates` | M4 | labels in prompt; off-list answer → abstain to embedding winner |
| `test_super_chain_still_reached_on_abstain` | M4 | `_SuperSentinel` pattern from `test_intent_router_output_mode.py` |
| `test_request_context_has_a2ui_component_default_none` | M5 | attribute present, default `None` |
| `test_build_component_prompt_uses_catalog_schema_and_instructions` | M6 | prompt contains the schema JSON, the catalog instructions, Graph notes only for Graph; unknown → `KeyError` |
| `test_check_feasibility_rules` | M6 | each reason code reachable; unknown component feasible |
| `test_emit_inline_component_emits_and_stamps_marker` | M6 | envelope on `response.a2ui_envelope`, `createSurface.metadata.extensions.parrot_presentation` present, `output_mode == A2UI`, `response.response` non-empty, metadata status `emitted` |
| `test_emit_inline_component_degrades_never_raises` | M6 | unparseable / infeasible / invalid-schema configs → `degraded` with the right reason; `a2ui_envelope` stays `None` |
| `test_extract_component_config_sources` | M6 | `structured_output` dict, BaseModel, fenced JSON in `output`, bare JSON in `content`, nothing → `None` |
| `test_default_routes_contain_four_composite_keys` | M7 | keys present, every utterance non-empty, EN+ES counts ≥ 8 |
| `test_ask_explicit_a2ui_component_skips_router` | M7 | harness replicating the call site (pattern of `test_intent_router_output_mode_integration.py`): explicit kwarg → router not consulted |
| `test_ask_wires_prompt_addon_and_emitter` | M7 | source-fidelity assertions that `data.py` contains `build_component_prompt(` and `emit_inline_component(` at the guarded sites |
| `getPresentation / isInlinePresentation` (vitest) | M8 | marker parsed; malformed → `null`/`false` |
| `inferSurfaceKind prefers marker` (vitest) | M8 | marker `kind` wins over root heuristic; no marker → today's result |
| `ChatBubble renders inline A2UISurface` (vitest) | M8 | `output_mode: "a2ui"` + inline marker + `features.a2ui` → `A2UISurface` mounted; without marker → no bubble widget |

### Integration Tests
| Test | Description |
|---|---|
| `test_inline_emitter_envelopes_conform` | Every v1 component's inline envelope passes catalog validation and lowered wire validation (conformance suite) |
| `test_routing_to_kpicard_end_to_end_offline` | Real `IntentRouterMixin` + real router (skips offline) with the default bank: "show me total worked hours this month" → `A2UI` + `KPICard`; "haz una gráfica" → `STRUCTURED_CHART` unchanged |

### Validation Contract

> FEAT-699. Explicit pytest operands (repo-relative file or `file::node`) that gate this feature in ALL
> tiers — task, merge, feature (`/sdd-done`) and QA. When present it REPLACES the heuristic breadth
> (import impact, suite escalation); the nightly workflow covers everything else. Write
> `none — fallback` to opt out explicitly (bounded fallback: tasks' own tests + direct importers).
> Never list `real_llm` tests. `integration`/`e2e`-marked operands listed here DO run.
> `/sdd-task` caches this list into the per-spec index header (`test_contract`).

runners:
- kind: pytest
  tests:
  - packages/ai-parrot/tests/routing/test_embedding_router.py
  - packages/ai-parrot/tests/routing/test_route_labels.py
  - packages/ai-parrot/tests/routing/test_route_bank.py
  - packages/ai-parrot/tests/bots/test_intent_router_output_mode.py
  - packages/ai-parrot/tests/bots/test_intent_router_output_mode_integration.py
  - packages/ai-parrot/tests/bots/test_intent_router_component_routes.py
  - packages/ai-parrot/tests/bots/test_resolve_output_mode_noop.py
  - packages/ai-parrot/tests/outputs/a2ui/inline/test_prompt.py
  - packages/ai-parrot/tests/outputs/a2ui/inline/test_feasibility.py
  - packages/ai-parrot/tests/outputs/a2ui/inline/test_emitter.py
  - packages/ai-parrot/tests/outputs/a2ui/test_emission_wiring.py
  - packages/ai-parrot/tests/outputs/a2ui/test_builders.py
  - packages/ai-parrot/tests/outputs/a2ui/test_components_card_kpicard_timeline_form.py
  - packages/ai-parrot/tests/outputs/a2ui/test_components_graph.py
  - packages/ai-parrot/tests/outputs/a2ui/conformance/test_all_emitters.py
  - packages/ai-parrot/tests/outputs/formats/test_renderer_registry.py
  - packages/ai-parrot/tests/outputs/test_legacy_deprecation.py
  - packages/ai-parrot/tests/outputs/formats/test_structured_chart.py
  - packages/ai-parrot/tests/unit/test_skill_tenancy.py
  - packages/ai-parrot-visualizations/tests/formats/test_structured_envelope.py
  markers: none
- kind: vitest
  cwd: packages/ai-parrot-server/ui
  tests:
  - src/lib/components/agents/canvas/a2ui/a2ui-kind.test.ts
  - src/lib/components/agents/canvas/a2ui/a2ui-presentation.test.ts
  - src/lib/components/agents/canvas/a2ui/A2UISurface.test.ts
  - src/lib/components/agents/canvas/a2ui/A2UINode.test.ts
  - src/lib/components/agents/ChatBubble.test.ts

(`test_route_labels.py`, `test_route_bank.py`, `test_intent_router_component_routes.py`,
`outputs/a2ui/inline/test_*.py` and `a2ui-presentation.test.ts` are created by this
feature; every other operand exists today and exercises touched code.)

### Test Data / Fixtures
```python
# Key fixtures needed
@pytest.fixture
def routed_ctx():
    """Minimal RequestContext stand-in with output_mode / intent_score / a2ui_component / kwargs."""
    return SimpleNamespace(output_mode=None, intent_score=None, a2ui_component=None, kwargs={})

@pytest.fixture
def kpi_response():
    """AIMessage-like response whose `output` carries a KPICard config JSON (fenced) and a DataFrame in `data`."""
    return SimpleNamespace(
        output='```json\n{"label": "Worked hours", "value": 1234.5, "unit": "h", "delta": 0.12, "trend": "up"}\n```',
        content=None, structured_output=None, response="", data=None, metadata={}, a2ui_envelope=None, output_mode=None,
    )

@pytest.fixture
def agent_root_with_banks(tmp_path):
    """<root>/routes.yaml + <root>/tenants/acme/routes.yaml + a reserved `tenants/skills/` dir to be ignored."""
    ...

@pytest.fixture
def composite_route_score():
    """RouteScore(OutputMode.A2UI, 0.93, 0.80, False, label="a2ui:KPICard", component="KPICard")."""
    ...
```

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] All Validation Contract operands pass (pytest runner + vitest runner).
- [ ] No breaking change to the public API: `_resolve_output_mode()` still returns `Optional[OutputMode]`; `RouteScore(None, -1.0, -1.0, False)` still constructs; `route_scores()` keeps its signature; `add_route(OutputMode, ...)` still works; `OutputMode` has no new member (G5).
- [ ] **G1**: for `output_mode=DEFAULT` the component prompt addon is injected *before* the main LLM turn (`data.py:1418` seam) and no second LLM call is made to author the component.
- [ ] **G2**: an explicit `output_mode` or `a2ui_component=` kwarg is never overridden by the router; an explicit hint skips routing entirely.
- [ ] **G3**: router or emitter failure of any kind yields `OutputMode.DEFAULT` prose with `response.metadata["a2ui_inline"]["reason"]` set; no exception escapes `ask()`; no empty bubble (`response.response` non-empty).
- [ ] **G4/G6**: no new classifier; the prompt is built from `ComponentDefinition.schema_` + `instructions`; the only hand-written per-component text is `INLINE_AUTHORING_NOTES`.
- [ ] **G7**: every inline envelope passes `validate_envelope(origin=LLM)` and, lowered, `validate_message` (conformance test); `requires_actions` components are rejected at CONFIGURE (`is_inline_component`) and at emit time.
- [ ] **G8**: `routes.yaml` at agent level and tenant level are loaded and merged (default ← agent ← tenant) with `replace` semantics; an invalid file or key logs a warning and is skipped; the code constant remains the fallback.
- [ ] Per-tenant routers share one encoder instance (no per-tenant model load).
- [ ] **G9**: a mixin overriding `_resolve_output_mode()` that chains `super()` and then returns `set_output_shape(ctx, OutputShape(OutputMode.A2UI, "KPICard"))` is honored by `PandasAgent.ask()` without any other change (unit test with a stub mixin).
- [ ] **G10**: `finalize_a2ui_response()` populates `response.response` for the inline envelope; the four feasibility reasons and the schema-failure reason are each reachable in tests.
- [ ] The surface-level marker `metadata.extensions.parrot_presentation` is present on every inline envelope with `kind="widget"`, `inline=true`, `origin="chat_turn"`, `component=<Name>`, and `Extensions` validation accepts it (no `a2ui_` prefix).
- [ ] **G11**: reference renderer — `inferSurfaceKind()` returns the marker kind when present; `ChatBubble` renders `A2UISurface` inline for `output_mode === "a2ui"` + inline marker under `features.a2ui`, and is byte-identical in behavior when the flag is off or the marker is absent.
- [ ] Default bank contains `a2ui:KPICard`, `a2ui:InfoCard`, `a2ui:Timeline`, `a2ui:Graph` with ≥ 8 EN and ≥ 8 ES utterances each; legacy chart/table/map routing results on the existing test phrases are unchanged.
- [ ] Documentation: `docs/outputs/inline-a2ui-component-routing.md` written (grammar, `routes.yaml`, marker, FEAT-756 hook, FEAT-753/754 registration contract); `docs/outputs/a2ui-v1.md` extension table gains the `parrot_presentation` row.
- [ ] `ruff check` clean on every touched Python file; no banned imports (TID251).

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> This section is the single source of truth for what exists in the codebase.
> Implementation agents MUST NOT reference imports, attributes, or methods
> not listed here without first verifying they exist via `grep` or `read`.

### Verified Imports
<!-- Exact import statements confirmed to work. Agents MUST use these verbatim. -->
```python
from parrot.bots.mixins.intent_router import IntentRouterMixin  # verified: parrot/bots/mixins/intent_router.py:123
from parrot.registry.routing.embedding_router import EmbeddingIntentRouter, RouteScore  # verified: embedding_router.py:57,37
from parrot.registry.capabilities.models import IntentRouterConfig  # verified: registry/capabilities/models.py:149
from parrot.models.outputs import OutputMode  # verified: parrot/models/outputs.py:23
from parrot.models.outputs import StructuredOutputConfig  # verified: parrot/models/outputs.py:59
from parrot.bots.data import DEFAULT_OUTPUT_MODE_ROUTES  # verified: parrot/bots/data.py:297
from parrot.bots.prompts import OUTPUT_SYSTEM_PROMPT  # verified: imported at parrot/bots/data.py:42
from parrot.utils.helpers import RequestContext  # verified: parrot/utils/helpers.py:7
from parrot.outputs.a2ui.catalog import (  # verified: catalog/__init__.py:62-90 (__all__)
    DEFAULT_CATALOG_ID, ProducerOrigin, RegisteredComponent, ComponentDefinition,
    get_component, validate_envelope, validate_message, register_component, unregister_component,
)
from parrot.outputs.a2ui.catalog.viz_core import VIZ_CORE_CATALOG_ID  # verified: catalog/viz_core/__init__.py:28
from parrot.outputs.a2ui.builders import build_surface, build_kpicard, build_card, build_graph  # verified: builders.py:57-68,79,151,171,330
from parrot.outputs.a2ui.models import CreateSurface, ComponentMetadata, SurfaceMetadata, Extensions  # verified: models.py:341,364,378
from parrot.outputs.a2ui.serialization import serialize  # verified: serialization.py:104
from parrot.outputs.a2ui.emission import finalize_a2ui_response  # verified: emission.py:18 (callers: bots/base.py:21,546)
from parrot.outputs.a2ui.catalog.parrot.kpicard import KPICARD_SCHEMA, KPICARD_INSTRUCTIONS  # verified: kpicard.py:15,99
from parrot.outputs.a2ui.catalog.parrot.infocard import INFOCARD_SCHEMA, INFOCARD_INSTRUCTIONS  # verified: infocard.py:18,31
from parrot.outputs.a2ui.catalog.parrot.timeline import TIMELINE_SCHEMA, TIMELINE_INSTRUCTIONS  # verified: timeline.py:16,36
from parrot.outputs.a2ui.catalog.viz_core.graph import GRAPH_INSTRUCTIONS  # verified: catalog/viz_core/graph.py:42
from parrot.outputs.a2ui.graph.models import GraphSpec, GraphNode, GraphEdge  # verified: graph/models.py:179,57,87
from parrot.outputs.a2ui.graph.mermaid import to_mermaid  # verified: graph/mermaid.py:206
from parrot.skills.tenancy import (  # verified: skills/tenancy.py:26-27,30,42,51,82
    TENANTS_DIRNAME, SKILLS_DIRNAME, validate_tenant_id, tenant_skills_dir, discover_tenant_dirs, current_skill_tenant,
)
from parrot.utils.paths import secure_path, validate_path_segment  # verified: utils/paths.py:52,33
from parrot.conf import AGENTS_DIR  # verified: parrot/conf.py:181
from parrot.registry.routing.llm_helper import extract_json_from_response  # verified: llm_helper.py:24
from parrot.outputs.formats import register_renderer, get_output_prompt, has_system_prompt, _A2UI_REPLACEMENTS  # verified: formats/__init__.py:76,108,117,15
import yaml  # PyYAML>=6.0.2 — verified: packages/ai-parrot/pyproject.toml:58
```

### Existing Class Signatures
<!-- Exact signatures of classes/methods that tasks will extend or call.
     Include attribute types and method signatures with line numbers. -->
```python
# parrot/registry/routing/embedding_router.py
class RouteScore(NamedTuple):                                   # line 37
    mode: Optional[OutputMode]; score: float; runner_up: float; ambiguous: bool   # lines 51-54
class EmbeddingIntentRouter:                                    # line 57
    def __init__(self, model: str = "intfloat/multilingual-e5-small", threshold: float = 0.85, margin: float = 0.05) -> None  # 65-69
    self.threshold / self.margin                                # lines 85-86
    def _ensure_encoder(self)                                   # line 90 (lazy SentenceTransformer; returns self._encoder, :106)
    def add_route(self, mode: OutputMode, utterances: list[str]) -> None   # line 108 (self._routes[mode] = ndarray, :123)
    def route_scores(self, query: str) -> list[tuple[OutputMode, float]]   # line 125
    def route(self, query: str) -> RouteScore                   # line 152 (abstain value RouteScore(None, -1.0, -1.0, False), :168)

# parrot/bots/mixins/intent_router.py
class IntentRouterMixin:                                        # line 123
    def __init__(self, **kwargs) -> None                        # line 141 (sets self._output_router = None, :151)
    def configure_output_router(self, config: IntentRouterConfig) -> None   # line 175
        #   for mode_value, utterances in config.output_mode_routes.items(): router.add_route(OutputMode(mode_value), utterances)  # :195-197
        #   except ValueError: logger.warning("Unknown OutputMode in output_mode_routes: %s", mode_value)                       # :198-201
    async def _resolve_output_mode(self, query: str, ctx: Any) -> "Optional[OutputMode]"   # line 209
        #   router None / rs.mode None -> return await super()._resolve_output_mode(query, ctx)   # :227-234
        #   rs.ambiguous -> candidates within router.margin -> _llm_disambiguate_output_mode     # :237-246
        #   ctx.intent_score = rs.score                                                           # :248-249
    async def _llm_disambiguate_output_mode(self, query: str, candidates: "list[OutputMode]") -> "Optional[OutputMode]"  # line 252
        #   prompt JSON contract: {"output_mode": "<one of the candidates>"}; timeout from self._router_config.strategy_timeout_s  # :276-288
        #   extract_json_from_response(raw); OutputMode(parsed.get("output_mode")); accept only if in candidates                 # :297-305

# parrot/registry/capabilities/models.py
class IntentRouterConfig(BaseModel):                            # line 149 (model_config at :74 is a different class)
    enable_output_mode_routing: bool = Field(False, ...)        # line 208
    embedding_model: str = Field("intfloat/multilingual-e5-small", ...)   # line 212
    output_mode_routes: dict[str, list[str]] = Field(default_factory=dict, ...)   # line 216
    output_mode_threshold: float = Field(0.85, ge=0.0, le=1.0, ...)       # line 223
    discrepancy_margin: float = Field(0.05, ge=0.0, le=1.0, ...)          # line 233

# parrot/bots/abstract.py
class AbstractBot:
    self.formatter = OutputFormatter()                          # line 555
    async def _resolve_output_mode(self, query: str, ctx: "Optional[RequestContext]") -> "Optional[OutputMode]"   # line 4168 (no-op terminal)
    def _apply_default_output_mode(self, output_mode: OutputMode) -> OutputMode   # line 4191 (reads self.default_output_mode, :4207)
    # ctx = RequestContext(request=..., app=..., llm=..., user_id=..., session_id=..., **ctx_kwargs)   # line 4381

# parrot/bots/data.py
DEFAULT_OUTPUT_MODE_ROUTES: Dict[str, List[str]]                # line 297 (keys OutputMode.STRUCTURED_CHART/TABLE/MAP.value, :298,311,323)
class PandasAgent(IntentRouterMixin, BasicAgent):               # line 338
    output_routing: bool = False, output_routing_config: Optional[IntentRouterConfig] = None   # ctor, lines 380-381 -> :420-421
    async def configure(...)  # :898-903 builds IntentRouterConfig(enable_output_mode_routing=True, output_mode_routes=DEFAULT_OUTPUT_MODE_ROUTES)
    async def ask(self, question: str, session_id=None, user_id=None, use_conversation_history=True, memory=None,
                  ctx: Optional[Any] = None, structured_output=None, output_mode: Any = None, format_kwargs: dict = None,
                  return_structured: bool = True, use_tools: bool = True, **kwargs) -> AIMessage   # lines 1265-1278
        # if output_mode == OutputMode.DEFAULT: _resolved_mode = await self._resolve_output_mode(question, ctx) ... ctx.output_mode = _resolved_mode   # :1349-1354
        # output_mode = self._apply_default_output_mode(output_mode)                                                                                 # :1358
        # if output_mode != OutputMode.DEFAULT: system_prompt += OUTPUT_SYSTEM_PROMPT.format(...); if system_prompt_addon := self.formatter.get_system_prompt(output_mode)  # :1412-1419
        # _forced_output_type = StructuredChartConfig if output_mode == OutputMode.STRUCTURED_CHART else PandasAgentResponse                        # :1512-1514
        # response: AIMessage = await client.ask(**llm_kwargs)                                                                                       # :1533
        # if output_mode == OutputMode.A2UI: (infographic dual-emit branch)                                                                           # :1880
        # if output_mode == OutputMode.A2UI: warning "output_mode=a2ui requested but no A2UI surface was produced" -> DEFAULT                          # :1960-1966
        # content, wrapped = await self.formatter.format(output_mode, response, **format_kwargs)                                                     # :1988
        # _structured_modes fallback -> DEFAULT on renderer failure                                                                                   # :2005-2017

# parrot/utils/helpers.py
class RequestContext:                                           # line 7
    def __init__(self, request=None, app=None, llm=None, user_id=None, session_id=None, **kwargs)   # lines 21-29
    self.kwargs = kwargs                                        # line 36
    self.output_mode = None; self.intent_score = None           # lines 41-42

# parrot/models/responses.py
class AIMessage:
    structured_output: Optional[Any]                            # line 190
    metadata: Dict[str, Any]                                    # line 194
    a2ui_envelope: Optional[Dict[str, Any]] = Field(default=None, ...)   # line 212

# parrot/models/outputs.py
class OutputMode(str, Enum):                                    # line 23  (CARD :44, STRUCTURED_CHART :52, STRUCTURED_TABLE :53, STRUCTURED_MAP :54, A2UI :55)
class StructuredOutputConfig                                    # line 59

# parrot/outputs/formats/__init__.py
_A2UI_REPLACEMENTS: dict[OutputMode, str]                       # lines 15-27 (CARD -> "OutputMode.A2UI with the InfoCard/KPICard catalog components", :22)
RENDERERS: dict[OutputMode, type[Renderer]]; _PROMPTS: dict[OutputMode, str]   # lines 48-49
_MODULE_MAP: dict                                               # lines 52-73 (no entry for OutputMode.A2UI)
def register_renderer(mode: OutputMode, system_prompt: str | None = None)   # line 76
def get_output_prompt(mode: OutputMode) -> str | None           # line 108
def has_system_prompt(mode: OutputMode) -> bool                 # line 117

# parrot/outputs/formatter.py
class OutputFormatter:                                          # line 117
    def get_system_prompt(self, mode: OutputMode) -> Optional[str]   # line 242 (-> get_output_prompt)
    async def format(self, mode: OutputMode, data: Any, **kwargs) -> Tuple[str, Optional[str]]   # line 267

# parrot/outputs/a2ui/catalog/__init__.py
def register_component(name: str, *, requires_actions: bool = False, catalog_id: str = DEFAULT_CATALOG_ID, is_primitive: bool = False,
                       allowed_parents=None, allowed_children=None, tool_only=...)   # line 114
def unregister_component(name: str, catalog_id: str = DEFAULT_CATALOG_ID) -> None   # line 196
def get_component(name: str, catalog_id: str | None = None) -> RegisteredComponent   # line 209 (KeyError unknown; CatalogError ambiguous)
def catalog_instructions(catalog_ids: Sequence[str] | None = None) -> str             # line 314
def validate_message(message: A2UIAgentMessage | A2UIRendererMessage) -> None          # line 458
def validate_envelope(envelope: CreateSurface | UpdateComponents, *, origin: ProducerOrigin = ProducerOrigin.TOOL,
                      surface_catalog_id: str | None = None) -> None                   # line 743

# parrot/outputs/a2ui/catalog/base.py
DEFAULT_CATALOG_ID = "https://parrot.dev/catalogs/v1"           # line 53
class ProducerOrigin(str, Enum)                                 # line 99 (LLM display-only; TOOL may carry actions)
class ComponentDefinition(BaseModel)                            # line 234 (name, catalog_id, schema_ [alias "schema"], instructions, requires_actions, is_primitive, allowed_parents, ...)
class RegisteredComponent: definition: ComponentDefinition; component_cls: type   # lines 293-297

# parrot/outputs/a2ui/catalog/parrot/kpicard.py
KPICARD_SCHEMA: dict[str, Any]                                  # line 15 (required: ["label", "value"], :96)
KPICARD_INSTRUCTIONS                                            # line 99
@register_component("KPICard") class KPICardComponent: SCHEMA; INSTRUCTIONS; def lower(self, component: Component, data_model) -> BasicTree   # lines 165-172
# infocard.py: INFOCARD_SCHEMA :18 (required ["title"]), INFOCARD_INSTRUCTIONS :31, @register_component("InfoCard") :37
# timeline.py: TIMELINE_SCHEMA :16 (required ["events"]; events[].title required), TIMELINE_INSTRUCTIONS :36, @register_component("Timeline") :43
# catalog/viz_core/graph.py: GRAPH_SCHEMA (derived from GraphSpec) :40, GRAPH_INSTRUCTIONS :42, @register_component("Graph", catalog_id=VIZ_CORE_CATALOG_ID) :63, lower :76

# parrot/outputs/a2ui/builders.py
def build_surface(component: str, properties: dict[str, Any], *, surface_id: str, component_id: str = "root",
                  data_model: dict[str, Any] | None = None, origin: ProducerOrigin = ProducerOrigin.LLM,
                  metadata: ComponentMetadata | None = None, surface_metadata: SurfaceMetadata | None = None) -> CreateSurface   # lines 79-89 ("Build and validate")
def build_kpicard(*, label, value, unit=None, delta=None, trend=None, surface_id="kpi") -> CreateSurface   # line 151
def build_card(*, title, subtitle=None, body=None, image=None, footer=None, surface_id="card") -> CreateSurface   # line 171 (emits InfoCard)
def build_graph(*, nodes, edges, kind="flowchart", direction="TB", title=None, ..., surface_id="graph", origin=ProducerOrigin.TOOL) -> CreateSurface   # line 330

# parrot/outputs/a2ui/models.py
class Extensions(RootModel[dict[str, Any]])                     # line 341 (UAX#31 keys; "a2ui_" prefix rejected, :355-360)
class ComponentMetadata(BaseModel): extensions: Extensions | None   # lines 364-373
SurfaceMetadata = ComponentMetadata                             # line 378

# parrot/outputs/a2ui/emission.py
def finalize_a2ui_response(response: Any) -> None               # line 18 (wraps envelope, sets output_mode=A2UI, fills response.response fallback, :30-46)

# parrot/outputs/a2ui/producer.py  (NOT used by this feature; listed to prevent confusion)
async def generate_envelope(client, prompt, *, catalog=None, max_attempts=3, model="", system_prompt=None) -> ProducerResult   # line 191 — separate free-form LLM call

# parrot/skills/tenancy.py
RESERVED_TENANT_NAMES; TENANTS_DIRNAME = "tenants"; SKILLS_DIRNAME = "skills"   # lines 23-27
def validate_tenant_id(value: str) -> str                       # line 30
def tenant_skills_dir(agent_root: Path, tenant: str) -> Path    # line 42
def discover_tenant_dirs(agent_root: Path, logger=None) -> Dict[str, Path]   # line 51
def current_skill_tenant() -> Optional[str]                     # line 82

# parrot/skills/mixin.py
tenant_based: bool = False                                      # line 110
def _resolve_agents_dir(self) -> Optional[Path]                 # line 290 (agent_root = agents_dir / agent_id, :252)

# parrot/utils/paths.py
def validate_path_segment(value: str, name: str = "path segment") -> str   # line 33
def secure_path(base: Union[str, Path], *segments: str, name: str = "path segment") -> Path   # line 52

# packages/ai-parrot-visualizations/src/parrot/outputs/formats/
STRUCTURED_CHART_SYSTEM_PROMPT                                  # structured_chart.py:40 ; @register_renderer(OutputMode.STRUCTURED_CHART, system_prompt=...) :79
class StructuredOutputBase: _route_envelope :87 ; _emit_a2ui_envelope :139 ; _extract_json_code (staticmethod) :202   # structured_base.py

# Reference UI (packages/ai-parrot-server/ui/src/lib)
export function inferSurfaceKind(surface: CreateSurface): SurfaceKind        # components/agents/canvas/a2ui/a2ui-kind.ts:31
export function hasInfographicRoot(envelope) / isLinkedSurface(envelope)     # a2ui-kind.ts:44,53
features.a2ui                                                                 # features.ts:31
ChatBubble.svelte: lazy renderer imports in $effect (:39-62); structured branches :1149 (structured_chart), :1234, :1290
AgentMessage.a2ui_envelope?: A2UIEnvelope                                     # types/agent.ts:51
A2UISurface.svelte props { envelope, persistedSurfaceId?, transformsBase?, shareToken? }   # canvas/a2ui/A2UISurface.svelte:34-39
```

### Integration Points
<!-- How new code connects to existing code. Specify exact method calls. -->
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `route_labels.is_inline_component` | `catalog.get_component()` → `definition.requires_actions` | lazy import + attribute read | `catalog/__init__.py:209`, `catalog/base.py:234-248` |
| `EmbeddingIntentRouter.add_route(label)` | `self._routes[...]` ndarray bank | key becomes `str` | `embedding_router.py:123` |
| `IntentRouterMixin.configure_output_router` | `parse_route_label` / `is_inline_component` | replaces `OutputMode(mode_value)` | `intent_router.py:197` |
| `IntentRouterMixin._resolve_output_mode` | `set_output_shape(ctx, ...)` | return path for composite wins | `intent_router.py:236-250` |
| `IntentRouterMixin._select_output_router` | `current_skill_tenant()` / `ctx.kwargs` | tenant pick | `skills/tenancy.py:82`, `utils/helpers.py:36` |
| `route_bank.resolve_route_banks` | `PandasAgent.configure` | before `configure_output_router` | `data.py:898-903` |
| `route_bank.tenant_routes_path` | `secure_path`, `validate_tenant_id`, `TENANTS_DIRNAME` | path containment | `utils/paths.py:52`, `skills/tenancy.py:30,26` |
| `inline.prompt.build_component_prompt` | `PandasAgent.ask` system prompt | appended at the `get_system_prompt` seam | `data.py:1418` |
| `inline.emitter.emit_inline_component` | `build_surface(origin=LLM, surface_metadata=...)` | validated envelope | `builders.py:79-89` |
| `inline.emitter.emit_inline_component` | `serialize()` → `response.a2ui_envelope`; `finalize_a2ui_response()` | same seam as structured dual-emit / FEAT-273 | `serialization.py:104`, `emission.py:18`, `structured_base.py:139-199` |
| `inline.emitter.emit_inline_component` | `PandasAgent.ask` | called before the "no A2UI surface" fallback | `data.py:1960` |
| `PandasAgent.ask(a2ui_component=...)` | `set_output_shape` | explicit hint | `data.py:1278` (`**kwargs`) |
| `RequestContext.a2ui_component` | `get_component_hint` | read side | `utils/helpers.py:41-42` |
| `a2ui-presentation.ts` | `inferSurfaceKind` / `ChatBubble` | marker precedence + inline branch | `a2ui-kind.ts:31`, `ChatBubble.svelte:41,1149` |
| conformance fixture | `_assert_conformant` | inline envelopes swept | `tests/outputs/a2ui/conformance/test_all_emitters.py` |

### Does NOT Exist (Anti-Hallucination)
<!-- Things that look plausible but DO NOT exist in the codebase.
     Prevents agents from inventing imports or attributes. -->
- ~~`"a2ui:<Component>"` composite keys~~ — `configure_output_router` does `OutputMode(mode_value)` and warns on anything else (`intent_router.py:195-201`); `add_route()` takes an `OutputMode` (`embedding_router.py:108`). *(grep `a2ui_component|component_hint` over `packages/*/src`: 0 hits.)*
- ~~`RouteScore.label` / `RouteScore.component`~~ — `RouteScore` has exactly `mode, score, runner_up, ambiguous` (`embedding_router.py:51-54`).
- ~~`EmbeddingIntentRouter.route_label_scores()` / `encoder=` kwarg~~ — not present (`:65-69`, `:125`).
- ~~`RequestContext.a2ui_component`~~ — only `output_mode` and `intent_score` exist (`utils/helpers.py:41-42`).
- ~~`IntentRouterConfig.tenant_output_mode_routes` / `route_bank_path`~~ — FEAT-224 fields end at `discrepancy_margin` (`models.py:233-238`).
- ~~A renderer registered for `OutputMode.A2UI`~~ — `_MODULE_MAP` has no A2UI entry (`formats/__init__.py:52-73`); the only `register_renderer(OutputMode.…)` calls are for TEXT/JSON/HTML/YAML/TABLE (core) and APPLICATION/SLACK/JINJA2/MARKDOWN/WHATSAPP/MAP/CARD/TEMPLATE_REPORT/ECHARTS/STRUCTURED_*/INFOGRAPHIC (visualizations). `PandasAgent.ask()` degrades A2UI to DEFAULT when no tool produced a surface (`data.py:1955-1966`).
- ~~A catalog-driven LLM authoring prompt for KPICard / InfoCard / Timeline / Graph in a chat turn~~ — only `structured_chart/_table/_map` register system prompts; `generate_envelope()` (`producer.py:191`) is a separate free-form call with its own `client.ask`, not the main turn.
- ~~`parrot/outputs/a2ui/inline/` package, `parrot/registry/routing/route_labels.py`, `route_bank.py`~~ — do not exist yet.
- ~~`routes.yaml` loader / `AGENTS_DIR/<agent>/routes.yaml` convention~~ — grep `routes\.yaml|load_output_mode_routes` over `packages/*/src`: 0 hits; the tenant tree today holds only `skills/` (`tenancy.py:42-48`).
- ~~`metadata.extensions.parrot_presentation`~~ — grep over `packages/*/src` and the UI: 0 hits; existing `parrot_*` keys are `parrot_role`, `parrot_variant`, `parrot_component_id`, `parrot_optional`, `parrot_unit`/`parrot_trend`/…, `parrot_data_sources`, `parrot_param` (`docs/outputs/a2ui-v1.md:151-158`).
- ~~An `a2ui` branch in `ChatBubble.svelte`~~ — grep `a2ui` in that file: 0 hits; `A2UISurface` is mounted only from `InfographicCanvas.svelte:21` (and recursively `A2UINode.svelte`).
- ~~A `kind` field on the wire~~ — `a2ui-kind.ts:4-9` and `agentdashboard-a2ui-reference.md:53` state there is none.
- ~~`StructuredOutputBase._extract_json_code` importable from core~~ — it lives in the visualizations satellite (`structured_base.py:202`); core must re-implement.
- ~~The rev 1 feasibility layer (`CapabilityRegistry.not_for` consulted by the output router)~~ — never built.
- ~~`IntentRouterConfig.model_config`~~ — the `model_config` at `models.py:74` belongs to a different class; `IntentRouterConfig` (`:149`) declares none.
- ~~`_llm_disambiguate_output_mode` returning labels~~ — today it returns `Optional[OutputMode]` and does `OutputMode(parsed.get("output_mode"))` (`:300-305`).

### Edit Sites (Blueprint Anchors)
<!-- One row per file the §3 modules will touch. `/sdd-task` turns each row into an
     Implementation Blueprint block, so the anchor is verified ONCE per feature here
     instead of once per task. Keep it to files the modules actually change — this
     table is re-read on every downstream turn, so rows must earn their place.

     Verified against: c2b7531c6 (dev @ 2026-10-27; every anchored file is byte-identical to b9417f4a0,
     the commit this spec's research started on — `git diff --stat b9417f4a0..c2b7531c6 -- packages/ docs/outputs`
     touches only knowledge/wiki/ledger/sdd_meta.py)

     Anchors go stale between spec time and task time. `/sdd-task` MUST re-run the
     `grep -c` for every row it uses; this table saves the search, not the check. -->

| File | Action | Verbatim anchor line | Verified at | Occurrences |
|---|---|---|---|---|
| `packages/ai-parrot/src/parrot/registry/routing/route_labels.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/registry/routing/route_bank.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/registry/routing/embedding_router.py` | MODIFY | `class RouteScore(NamedTuple):` | `embedding_router.py:37` | 1 |
| `packages/ai-parrot/src/parrot/registry/routing/embedding_router.py` | MODIFY | `    def add_route(self, mode: OutputMode, utterances: list[str]) -> None:` | `embedding_router.py:108` | 1 |
| `packages/ai-parrot/src/parrot/registry/routing/embedding_router.py` | MODIFY | `    def route_scores(self, query: str) -> list[tuple[OutputMode, float]]:` | `embedding_router.py:125` | 1 |
| `packages/ai-parrot/src/parrot/registry/routing/embedding_router.py` | MODIFY | `    def route(self, query: str) -> RouteScore:` | `embedding_router.py:152` | 1 |
| `packages/ai-parrot/src/parrot/registry/capabilities/models.py` | MODIFY | `    output_mode_routes: dict[str, list[str]] = Field(` | `models.py:216` | 1 |
| `packages/ai-parrot/src/parrot/bots/mixins/intent_router.py` | MODIFY | `        self._output_router: Optional[EmbeddingIntentRouter] = None` | `intent_router.py:151` | 1 |
| `packages/ai-parrot/src/parrot/bots/mixins/intent_router.py` | MODIFY | `                router.add_route(OutputMode(mode_value), utterances)` | `intent_router.py:197` | 1 |
| `packages/ai-parrot/src/parrot/bots/mixins/intent_router.py` | MODIFY | `    async def _resolve_output_mode(` | `intent_router.py:209` | 1 |
| `packages/ai-parrot/src/parrot/bots/mixins/intent_router.py` | MODIFY | `    async def _llm_disambiguate_output_mode(` | `intent_router.py:252` | 1 |
| `packages/ai-parrot/src/parrot/utils/helpers.py` | MODIFY | `        self.intent_score = None` | `helpers.py:42` | 1 |
| `packages/ai-parrot/src/parrot/bots/abstract.py` | MODIFY (docstring) | `    async def _resolve_output_mode(` | `abstract.py:4168` | 1 |
| `packages/ai-parrot/src/parrot/bots/abstract.py` | MODIFY (docstring) | `    def _apply_default_output_mode(self, output_mode: OutputMode) -> OutputMode:` | `abstract.py:4191` | 1 |
| `packages/ai-parrot/src/parrot/outputs/a2ui/inline/__init__.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/outputs/a2ui/inline/prompt.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/outputs/a2ui/inline/feasibility.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/outputs/a2ui/inline/emitter.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/bots/data.py` | MODIFY | `DEFAULT_OUTPUT_MODE_ROUTES: Dict[str, List[str]] = {` | `data.py:297` | 1 |
| `packages/ai-parrot/src/parrot/bots/data.py` | MODIFY | `            await asyncio.to_thread(self.configure_output_router, router_cfg)` | `data.py:903` | 1 |
| `packages/ai-parrot/src/parrot/bots/data.py` | MODIFY | `                _resolved_mode = await self._resolve_output_mode(question, ctx)` | `data.py:1350` | 1 |
| `packages/ai-parrot/src/parrot/bots/data.py` | MODIFY | `                    if system_prompt_addon := self.formatter.get_system_prompt(output_mode):` | `data.py:1418` | 1 |
| `packages/ai-parrot/src/parrot/bots/data.py` | MODIFY | `                        StructuredChartConfig if output_mode == OutputMode.STRUCTURED_CHART else PandasAgentResponse` | `data.py:1513` | 1 |
| `packages/ai-parrot/src/parrot/bots/data.py` | MODIFY | `                # There is no A2UI renderer to dispatch to — the mode is a request-side` / `                # signal handled by the render tools — so degrade to DEFAULT` / `                # rather than let the formatter raise "No renderer registered".` / `                if output_mode == OutputMode.A2UI:` | `data.py:1957-1960` | 2 (bare line also at `:1880`; use the 3 comment lines above as context) |
| `packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/a2ui-presentation.ts` | CREATE | — | — | — |
| `packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/a2ui-kind.ts` | MODIFY | `export function inferSurfaceKind(surface: CreateSurface): SurfaceKind {` | `a2ui-kind.ts:31` | 1 |
| `packages/ai-parrot-server/ui/src/lib/components/agents/ChatBubble.svelte` | MODIFY | `    const mode = message.output_mode;` | `ChatBubble.svelte:41` | 1 |
| `packages/ai-parrot-server/ui/src/lib/components/agents/ChatBubble.svelte` | MODIFY | `        {:else if message.output_mode === "structured_chart" && message.output}` | `ChatBubble.svelte:1149` | 1 |
| `docs/outputs/a2ui-v1.md` | MODIFY | `` | `parrot_param` | `` (table row prefix) | `a2ui-v1.md:158` | 1 |
| `docs/outputs/inline-a2ui-component-routing.md` | CREATE | — | — | — |
| `packages/ai-parrot/tests/outputs/a2ui/conformance/test_all_emitters.py` | MODIFY | `def _assert_conformant(` | `test_all_emitters.py` | 1 |

- A **CREATE** row declares only the path the module adds; it needs no anchor.
- **Occurrences > 1** means the one-line anchor is ambiguous. Quote 2–3 lines of
  surrounding context in the anchor cell so the blueprint block can attach uniquely.
- An anchor that cannot be verified is written `(unverified — check before use)`,
  never guessed.

---

## 7. Implementation Notes & Constraints

> Architecture decisions stay with the thinking model. A delegated
> implementation may only express a decision already recorded here and in
> the TASK's implementation blocks — it must never invent an API, choose a
> file, or resolve an open design question.

### Patterns to Follow
- **Additive on the FEAT-224 core.** `RouteScore` only grows defaulted trailing
  fields; `route_scores()` keeps its signature as a compat view; every
  `_resolve_output_mode()` caller stays untouched (`data.py:1350`,
  `base.py:300,1155`). The hint travels on `ctx`, never in the return value.
- **Label grammar lives in one module** (`route_labels.py`). Nobody else
  string-splits on `"a2ui:"`.
- **Validation order at CONFIGURE**: `parse_route_label` (grammar + OutputMode
  value) → for composites `is_inline_component` (registered + display-only) →
  `add_route`. Each failure is one `logger.warning("Skipping output_mode_routes key %r: %s", key, reason)`;
  the router is still built with the surviving routes.
- **Merge semantics for banks**: left-to-right (`defaults` ← agent ← tenant);
  per key, `replace=False` appends unseen utterances preserving order,
  `replace=True` substitutes the key's list; a key present only in an overlay is
  added; `threshold`/`margin` overrides apply last-writer-wins; tenant banks
  inherit the already-merged agent bank. Loader uses `yaml.safe_load` only.
- **Per-tenant routers share the encoder**: build the global router first, call
  `_ensure_encoder()` once, pass `encoder=` to every tenant router. Tenant pick
  order at REQUEST: `current_skill_tenant()` → `ctx.kwargs.get("tenant")` →
  global. Unknown tenant → global (no warning spam: warn once per tenant like
  `skills/mixin.py:176`).
- **Prompt addon contract** (mirrors `STRUCTURED_CHART_SYSTEM_PROMPT`,
  `structured_chart.py:40-100`): single JSON object, no prose/markdown/fences;
  the LLM computes every figure itself in the tool loop (KPICard `value`/`delta`
  are literals, never bindings); never emit rows, positions or `action`; include
  the catalog schema verbatim as JSON; append `INLINE_AUTHORING_NOTES` last.
- **Emitter placement**: after structured post-processing and before the
  existing A2UI-fallback at `data.py:1960`, so a degraded outcome flows into the
  very same `DEFAULT` degradation already in place. The emitter never touches
  `response.output_mode` on failure (same rule as `_emit_a2ui_envelope`,
  `structured_base.py:156-159`).
- **`surface_id`** pattern `f"{component.lower()}-{uuid4().hex[:8]}"` — the
  FEAT-224 id pattern used by `_emit_a2ui_envelope` (`structured_base.py:149`).
- **Marker is surface-level** (`createSurface.metadata.extensions`), exactly
  like `parrot_data_sources`; the component itself carries no marker.
- **UI**: Svelte 5 runes only; lazy-import `A2UISurface` in the existing
  `$effect` block; the new branch sits *before* the `structured_chart` branch;
  gate with `features.a2ui`; vitest next to the code.
- Async-first; no blocking calls on the loop (`route()` stays under
  `asyncio.to_thread`); `self.logger` everywhere; Pydantic v2 models; Google
  docstrings; 120 columns; `black` + `ruff`.

### Known Risks / Gotchas
- **Hint for a component not in the allowlist** (e.g. a future `routes.yaml`
  naming `DataTable`) → skipped at CONFIGURE; if it still reaches the emitter
  (explicit kwarg) → `degraded` with `component_not_inline`, prose answer.
- **Data cannot fill the component** (KPICard without a scalar, Timeline
  without dated rows) → emitter-local `check_feasibility` degrades to prose and
  records the reason; no `CapabilityRegistry` coupling (rev 1 layer-2, now per
  component).
- **Tenant bank with an invalid `OutputMode`/component label** → warning +
  entry skipped (mirrors the current `ValueError` branch).
- **Text-only transports** (Telegram / A2A text) → `finalize_a2ui_response()`
  fills `response.response`; `lower()` remains the renderer-side fallback.
- **Graph authoring quality** is the hard case (brainstorm con). Mitigation:
  `INLINE_AUTHORING_NOTES["Graph"]` (≤ 25 nodes, stable ids, `direction`,
  `accessibleDescription`, no positions, choose `kind` per catalog
  instructions) plus `GraphSpec` validation via `build_surface`. If it still
  proves unreliable, the brainstorm's fallback is a dedicated prompt asset for
  Graph — never a dedicated mode.
- **`get_component` ambiguity**: today no name is registered twice
  (`catalog/__init__.py:209-222`); if a sibling spec introduces one, the
  emitter must pass `catalog_id` — covered by the registration contract (§2).
- **Threshold drift**: the default `output_mode_threshold=0.85` was calibrated
  for three routes; four more semantically close routes (KPI vs chart) may need
  a re-sweep. The bank files can override `threshold`/`margin` per agent/tenant
  so operators can tune without code.
- **Embedding model offline**: tests touching the real e5 model skip gracefully
  (pattern of `tests/routing/test_embedding_router.py`); pure-logic tests stub
  the router.
- **Tie-breaker compat**: the JSON key stays `output_mode`; plain labels equal
  `OutputMode` values, so FEAT-224 stubs keep working; composite labels are
  returned verbatim.
- **Reference UI vs navigator-frontend-next**: only the former is in scope; the
  marker is the documented contract for the latter.
- **Shared-checkout hazards**: `data.py` and `abstract.py` are high-traffic
  files; keep diffs minimal and rebase early (see `.claude/rules/worktree-management.md`).

### External Dependencies
| Package | Version | Reason |
|---|---|---|
| `PyYAML` | `>=6.0.2` (already in core deps, `packages/ai-parrot/pyproject.toml:58`) | `routes.yaml` loading via `yaml.safe_load` |
| `sentence-transformers` | already vendored (FEAT-224 G6) | encoder for the embedding router — no change |
| `jsonschema` | already used by the catalog | envelope validation — no change |

No new dependency is introduced.

---

## 8. Open Questions

> Questions that must be resolved before or during implementation.

Resolved by FEAT-224 (carried forward from the brainstorm, never re-opened):
- [x] A vs B vs C (rev 1) — *Resolved by FEAT-224*: deterministic local embedding router (`multilingual-e5-small`) hooked into `ask()` via `_resolve_output_mode()`, bounded LLM tie-breaker only on ambiguity.
- [x] Classifier model + budget — *Resolved by FEAT-224*: `intfloat/multilingual-e5-small`, CPU, encoder + phrase bank encoded once at CONFIGURE; no cloud call on the hot path.
- [x] Keyword fast-path vs pure LLM — *Resolved by FEAT-224*: embeddings replace both; no regex fast-path.
- [x] Extend `IntentRouterMixin` vs standalone router — *Resolved by FEAT-224*: extends the mixin; `AbstractBot._resolve_output_mode()` is the cooperative no-op terminal.
- [x] Confidence threshold — *Resolved by FEAT-224*: `output_mode_threshold=0.85`, `discrepancy_margin=0.05`, calibrated for e5-small (per-bank overrides added here, §3 M3).

Rev 2 questions:
- [x] Composite label format: string keys vs a parallel `a2ui_component_routes` field? — *Resolved in spec*: composite string keys `"a2ui:<Component>"` inside `output_mode_routes` (one bank, one grammar in `route_labels.py`); validation extended in `configure_output_router` (§3 M1/M4). A parallel field would split the bank across two merge paths for `routes.yaml`.
- [x] Where the per-agent / per-tenant phrase bank lives? — *Resolved in spec*: `AGENTS_DIR/{agent_id}/routes.yaml` + `AGENTS_DIR/{agent_id}/tenants/{tenant}/routes.yaml` (sibling of the FEAT-707 `skills/` tree, same `validate_tenant_id`/`secure_path` containment), not a key inside the agent config document (§3 M3).
- [x] Emitter contract: pydantic `structured_output` generated off the catalog schema vs free JSON + catalog validation? — *Resolved in spec*: free JSON authored in the main turn under a catalog-schema system prompt, then `build_surface(origin=LLM)` validation (structured_chart style); `Graph` gets `INLINE_AUTHORING_NOTES["Graph"]` (§3 M6). Dynamic pydantic models would re-encode the catalog schema and break G6.
- [x] Name/namespace of the inline marker? — *Resolved in spec*: `metadata.extensions.parrot_presentation`, **surface-level**, following the `parrot_*` convention of `docs/outputs/a2ui-v1.md:140-162` (the `a2ui_` prefix is reserved and rejected by `Extensions`, `models.py:355-360`); no existing key fits (`parrot_variant` is component-level and describes lowered Cards).
- [x] Revive rev 1's data-feasibility layer per component inside the emitter? — *Resolved in spec*: yes, emitter-local `check_feasibility()` with fixed reason codes, no `CapabilityRegistry` coupling (§3 M6). Degradation target in v1 is prose (`DEFAULT`), not `structured_table` — re-running a second renderer after the main turn would violate G1.
- [x] Which inline components ship in v1? — *Resolved in spec*: `KPICard` + `InfoCard` + `Timeline` + `Graph` (`INLINE_COMPONENTS`); `MermaidDiagram` (FEAT-753) joins through the registration contract.
- [ ] Should the inline emitter also be wired into `BaseBot.ask()` / `conversation()` (`bots/base.py:300,1155`) in this feature, or stay PandasAgent-only in v1 (current Non-Goal)? Product call: it decides whether non-data agents can answer with a KPI card computed by tools. — *Owner: Jesus Lara*
- [ ] Default `threshold`/`margin` for the enlarged bank: keep 0.85/0.05 (and rely on per-bank overrides) or re-sweep once the EN/ES utterances are authored? Needs a short offline sweep over the labelled phrase set during M7. — *Owner: Jesus Lara*

---

## 9. Design Research Cross-Check

> Independent design opinion from the `codex` seat over the **accepted exploration
> doc** (never over this spec). Model: `<model>` · Status: completed | skipped (<reason>)
> · Transcript: `sdd/state/<FEAT-ID>/design_research/`
> Every row is a suggestion the reviewer made; the disposition is the spec author's
> call (CONFIRM = folded into the spec, REJECT = reason recorded, ESCALATE = §8 question).

Status: skipped (codex design-research seat not run in this session)

| # | Suggestion (kind) | Disposition | Reason | Landed in |
|---|---|---|---|---|

Summary: **0** confirmed · **0** rejected · **0** escalated.

---

## Worktree Strategy

- **Default isolation unit**: `per-spec` — one feature worktree
  (`feat-FEAT-755-inline-a2ui-component-routing`, created by the implementing
  lane via `python -m scripts.sdd.ensure_worktree --slug inline-a2ui-component-routing --feature-id FEAT-755`).
- **Rationale / internal parallelism (medium)**: three threads meet only at two
  names the spec fixes up front — the `a2ui_component` hint (`ctx.a2ui_component`,
  kwarg name) and the `parrot_presentation` marker:
  (a) **router thread** M1 → M2 → M3 → M4 → M5 (sequential: shared files
  `embedding_router.py`, `intent_router.py`);
  (b) **emitter thread** M6 (independent of (a); depends only on the catalog);
  (c) **renderer thread** M8 (independent; depends only on the marker shape).
  M7 (`data.py` wiring) joins (a)+(b); M9 closes. (a), (b) and (c) can run
  concurrently inside the worktree (sub-worktrees per task are fine); M7 and M9
  wait.
- **Cross-feature dependencies**: FEAT-753 (`MermaidDiagram`), FEAT-754 (C4
  `Graph` kind) and FEAT-756 (metric default shape) consume this feature's
  thread (a) — they depend on M1–M5 landing on `dev` first, not on M6–M8.
  FEAT-752 (suggestion chips) may emit chips carrying `a2ui_component` hints
  (additive; depends on M1 for the name/grammar only). None of them must merge
  before this feature. Coordinate at merge time on `bots/data.py` and
  `bots/abstract.py`, which are edited by several in-flight features.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-10-27 | Jesus Lara | Initial draft from accepted brainstorm `output-mode-intent-router.brainstorm.md` rev 2 (Option A); six rev-2 design questions resolved in spec, two product-level questions left open |
