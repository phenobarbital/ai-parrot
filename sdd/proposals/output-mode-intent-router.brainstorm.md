---
# SDD flow type and base branch (FEAT-145).
type: feature
base_branch: dev
projects: [ai-parrot, ai-parrot-server, ai-parrot-visualizations]
tags: [a2ui, output-mode, intent-router, inline-widgets, kpicard, phrase-bank]
---

# Brainstorm: Output-Mode Intent Router → A2UI component routing (rev 2)

**Date**: 2026-06-04 (rev 1) · 2026-10-27 (rev 2)
**Author**: Juan Ruffato (rev 1), Jesus Lara (rev 2)
**Status**: accepted (rev 2 — re-scoped to A2UI component routing; rev 1 was realized by FEAT-224)
**Recommended Option**: A (composite component routes on the existing embedding router + one catalog-driven A2UI emitter)
**Feeds**: `sdd/specs/inline-a2ui-component-routing.spec.md` (FEAT-755)

> **Revision note (rev 2).** Rev 1 asked for an LLM-driven chart / map / table
> selector in `PandasAgent.ask()`. That problem was solved by **FEAT-224**
> (`intent-router-mixin-embedding-routing`, merged 2026-06-05): a deterministic,
> local, multilingual *embedding* router (`EmbeddingIntentRouter`) hooked into
> `ask()` through `AbstractBot._resolve_output_mode()`, with a bounded LLM
> tie-breaker only on genuine ambiguity. Rev 2 keeps rev 1's constraints (decide
> *before* the main turn so the LLM shapes the data; never override an explicit
> caller mode; conservative abstain to `DEFAULT`; never raise) and **re-scopes
> the target**: the router must be able to land on the A2UI Parrot-catalog
> components an inline chat bubble can render — `KPICard`, `InfoCard`,
> `Timeline`, `Graph` (and, through their own specs, `MermaidDiagram` FEAT-753 /
> C4 FEAT-754) — not only on the three legacy `STRUCTURED_*` modes. The
> trigger was the NAV-10382 review (2026-10-27): the first "How to test" step,
> *"show me worked hours this month → KPI card"*, has **no server-side decider
> today**. Rev 1's text is preserved below where still accurate; superseded
> parts are marked.

---

## Problem Statement

Inline chat answers in ai-parrot can be routed, from the user's phrasing, to
exactly three structured shapes: `structured_chart`, `structured_table`,
`structured_map` (FEAT-224 phrase bank `DEFAULT_OUTPUT_MODE_ROUTES`,
`parrot/bots/data.py:297`). Meanwhile the server-side A2UI v1.0 catalog
already defines richer display-only components — `KPICard` (value, unit,
delta, trend, comparisonPeriod, higherIsBetter, sparkline `series`),
`InfoCard`, `Timeline`, `Graph` (flowchart / DAG / state machine with a
Mermaid codec, FEAT-529) — and the formats registry already declares the
per-kind modes superseded: *"OutputMode.CARD → A2UI with the InfoCard/KPICard
catalog components"* (`parrot/outputs/formats/__init__.py:15-24`). Nothing
bridges the two:

1. **No router target.** `output_mode_routes` keys are `OutputMode` *values*
   (`registry/capabilities/models.py:216-222`); `_resolve_output_mode()` returns
   a bare `Optional[OutputMode]` (`bots/mixins/intent_router.py:209`). There is
   no way to say "route to `OutputMode.A2UI` *with component KPICard*".
2. **No catalog-driven emitter.** `STRUCTURED_CHART` works because a system
   prompt + schema (`structured_chart.py:40`) makes the LLM produce a validated
   config in the single main turn, and `StructuredOutputBase._route_envelope()`
   dual-emits the A2UI envelope (`structured_base.py:87`). `KPICard`,
   `InfoCard`, `Timeline`, `Graph` have catalog JSON schemas
   (`outputs/a2ui/catalog/parrot/*.py`) but no equivalent "LLM authors this
   component from the data it just computed" path for an inline answer.
3. **Phrase bank is a code constant.** `DEFAULT_OUTPUT_MODE_ROUTES` is only
   overridable by passing an `IntentRouterConfig` in Python; there is no
   per-agent / per-tenant configuration the way skills are (FEAT-707).
4. **No inline-eligibility signal.** The frontend infers widget vs dashboard
   from the root component (`docs/frontend/agentdashboard-a2ui-reference.md`
   §6.2 heuristic); the envelope never says "this was produced as an inline
   answer".

**Affected:** every agent with `output_routing=True` (e.g. `flex_dashboard`,
`agents/flex_dashboard.py:185`), the ai-parrot-server reference renderer
(`packages/ai-parrot-server/ui/.../canvas/a2ui/`), navigator-frontend-next's
AgentChat (consumer, out of scope here), and FEAT-756 (metric default shape),
which needs the same component-hint channel.

### Rev 1 problem (historical, realized by FEAT-224)

> Today the caller must manually choose the output format from a frontend
> dropdown … We want the agent to detect from the natural-language request
> whether the user wants a chart, a map, or a table, and set the output mode
> accordingly. Decision by the backend, before the turn, coupled to data
> production, feasibility-aware, conservative, never overriding an explicit
> mode. — *Delivered by FEAT-224 except the feasibility layer (see Open
> Questions).*

## Constraints & Requirements

Carried from rev 1 (still binding):
- Decide **before/at the turn** so the LLM produces component-shaped data in
  the single main turn; no post-hoc forcing of a shape onto mismatched data.
- **Non-override**: an explicit caller `output_mode` (or `/trigger` skill) wins;
  the router never overrides it. Precedence today: explicit > router > agent
  default (`bots/abstract.py:4191-4210`).
- **Conservative**: ambiguous → abstain → `DEFAULT`. Any router error →
  `DEFAULT`, never raise.
- Reuse the existing router machinery (`EmbeddingIntentRouter`,
  `IntentRouterMixin`) — no parallel classifier.

New in rev 2:
- **No new `OutputMode` members per component.** The target is
  `OutputMode.A2UI` plus a *component hint*; the formats registry already
  points every per-kind legacy mode at A2UI.
- **Catalog is the single source of truth** for what an inline bubble can
  carry: the emitter derives its prompt/schema from the component's registered
  catalog schema, never from a hand-written per-component prompt copy.
- **Every emitted surface validates** against both the Parrot catalog allowlist
  and the lowered Basic wire schema, like every other emitter (conformance
  tests `tests/outputs/a2ui/conformance/`).
- **Phrase bank configurable per agent and per tenant**, with the code
  constant as the fallback default; configuration must be data (YAML/JSON next
  to the agent's skills), not Python.
- **Precedence chain stays open for a metric-declared default shape** (FEAT-756
  plugs between router and agent default); this brainstorm defines the hook,
  not the registry.
- **Degradation**: a component the active renderer cannot show lowers to Basic
  primitives (`lower()`, FEAT-470) — text-only transports (Telegram/A2A text)
  must still get a sensible answer.
- Frontend work in navigator-frontend-next is **out of scope**; the
  ai-parrot-server UI is the reference renderer and must render the new inline
  components.

---

## Options Explored

### Option A: Composite component routes on the existing router + one catalog-driven A2UI emitter (recommended)

1. **Route keys gain a component dimension.** `output_mode_routes` accepts keys
   of the form `"a2ui:<ComponentName>"` next to plain `OutputMode` values
   (e.g. `"a2ui:KPICard": ["show me the total …", "dame el KPI de …"]`).
   `EmbeddingIntentRouter.add_route()` keeps one label per route;
   `RouteScore` carries the label, and `_resolve_output_mode()` resolves it to
   `(OutputMode.A2UI, component_hint)` — the hint rides on the request
   (`ctx`/kwarg `a2ui_component`), the mode stays an `OutputMode`, so every
   existing caller is unchanged.
2. **Generic catalog-driven emitter for `OutputMode.A2UI` + hint.** One
   renderer builds the system prompt from the component's catalog JSON schema
   (same contract style as `STRUCTURED_CHART_SYSTEM_PROMPT`: data rows come
   from the computed DataFrame / tool output via `dataVariable`, the LLM emits
   only the component config), parses + validates the JSON against the catalog,
   builds the envelope with the existing builders, and sets
   `response.a2ui_envelope` + `response.output` exactly like
   `StructuredOutputBase._emit_a2ui_envelope`. Display-only components only
   (`requires_actions=False`): KPICard, InfoCard, Timeline, Graph in v1.
3. **Phrase bank as data.** A loader reads `<agent dir>/routes.yaml` (and the
   FEAT-707 tenant tree) into `IntentRouterConfig.output_mode_routes`, merged
   over `DEFAULT_OUTPUT_MODE_ROUTES`; default bank gains EN/ES utterances for
   the four new routes.
4. **Inline-eligibility marker.** The emitter stamps
   `metadata.extensions.parrot_presentation = {"kind": "widget", "inline": true,
   "origin": "chat_turn"}` so renderers stop guessing from the root component.
5. **Hook for FEAT-756.** After the router abstains, `_resolve_output_mode()`
   chains `super()`; FEAT-756 overrides the same method to return
   `(A2UI, hint)` from a matched metric's `default_shape`. Nothing to add here
   beyond keeping the chain cooperative and the hint channel public.

✅ **Pros:** zero enum growth; one emitter for N components; catalog remains
the single source of truth; reuses FEAT-224 end to end; per-tenant config
mirrors skills; gives FEAT-753/754/756 a ready channel.
❌ **Cons:** `RouteScore`/`_resolve_output_mode` signatures grow a label/hint
(additive, but touches the FEAT-224 core); the generic prompt must be good
enough for four very different components (Graph is the hard one — may need a
per-component "authoring notes" asset in the catalog module).
📊 **Effort:** Medium.
🔗 **Reuse:** `EmbeddingIntentRouter` (`registry/routing/embedding_router.py:57`),
`IntentRouterMixin._resolve_output_mode` (`intent_router.py:209`),
`StructuredOutputBase` (`structured_base.py:87-139`), catalog schemas
(`catalog/parrot/kpicard.py`, `infocard.py`, `timeline.py`, `graph/models.py`),
`validate_envelope` / `validate_message`, `lower()`.

### Option B: One new `OutputMode` + renderer per component (STRUCTURED_KPI, STRUCTURED_TIMELINE, …)

Mirror `structured_chart.py` for each component in ai-parrot-visualizations;
phrase bank keys stay plain `OutputMode` values.

✅ **Pros:** zero change to router signatures; each renderer can have a
hand-tuned prompt.
❌ **Cons:** contradicts the registry's own direction (per-kind modes are
"superseded by A2UI"); enum grows with every component; four near-identical
renderers to maintain; ai-parrot-server/UI selectors and generated TS enums
churn on every addition.
📊 **Effort:** Medium (×N over time).

### Option C: LLM self-declares the component in the main turn (rev 1's Option B)

Under `DEFAULT`, the main turn emits a polymorphic `{kind, config}`; a
validator downgrades infeasible kinds.

✅ **Pros:** single call; feasibility by construction.
❌ **Cons:** unchanged from rev 1 — heavy polymorphic prompt, less
controllable, no pre-turn decision, and it bypasses the router the team
already standardized on.
📊 **Effort:** Medium–High.

---

## Recommendation

**Option A.** It is the only option that treats the A2UI catalog as the
source of truth, keeps `OutputMode` closed, reuses FEAT-224 unchanged in
spirit (additive hint), and hands FEAT-753 (Mermaid), FEAT-754 (C4) and
FEAT-756 (metric default shape) the same channel instead of three ad-hoc
ones. Option B is the fallback only if the generic emitter proves unable to
author `Graph` well — in which case `Graph` alone gets a dedicated prompt
asset, not a dedicated mode.

---

## Feature Description

### User-Facing Behavior
With the selector on `Default (Auto)`, *"show me total worked hours this
month"* returns an inline **KPI card** (value, delta vs previous period,
trend); *"timeline of the releases this quarter"* an inline **Timeline**;
*"diagram the approval flow"* an inline **Graph**; chart / table / map phrasing
keeps working exactly as today. Explicitly picking a mode, or typing a
`/trigger`, still wins. Plain questions still answer in prose.

### Internal Behavior
1. `configure_output_router()` loads the merged phrase bank (code default ←
   agent `routes.yaml` ← tenant overrides) and registers composite labels.
2. `_resolve_output_mode()` → `RouteScore(label, score, …)`; a composite label
   resolves to `OutputMode.A2UI` + `component_hint` on the request context;
   ambiguity → existing bounded LLM tie-breaker over labels.
3. `_apply_default_output_mode()` precedence becomes: explicit caller mode >
   router (mode + hint) > *metric default shape (FEAT-756 hook)* > agent
   default.
4. The A2UI catalog emitter runs the main turn with the component's schema
   prompt, validates, builds the envelope, stamps `parrot_presentation`, sets
   `a2ui_envelope`/`output`; on validation failure it degrades to prose +
   a `Degraded` note (never an empty bubble).
5. Reference renderer: `ChatBubble` renders `KPICard` / `InfoCard` /
   `Timeline` / `Graph` inline when `parrot_presentation.inline` is true.

### Edge Cases & Error Handling
- Hint for a component not in the catalog allowlist → ignored, `DEFAULT`.
- Hint for a component the data cannot fill (KPICard with no scalar) → emitter
  degrades to `structured_table`/prose with a logged reason (rev 1's layer-2
  validation, now per component).
- Tenant bank with an invalid `OutputMode`/component label → warning, entry
  skipped (mirrors `configure_output_router`'s current `ValueError` handling).
- Text-only transports → `lower()` fallback text.

---

## Capabilities

### New Capabilities
- `a2ui-component-routing`: composite router labels resolving to
  `OutputMode.A2UI` + component hint; per-agent/per-tenant phrase bank.
- `a2ui-catalog-emitter`: one catalog-schema-driven LLM authoring path for
  display-only Parrot components in an inline answer.
- `parrot_presentation` extension: inline-eligibility / provenance marker.

### Modified Capabilities
- `intent-router-mixin-embedding-routing` (FEAT-224) — additive hint channel.
- `structured-artifact-contract` (FEAT-223/473) — the generic emitter joins the
  dual-emission family.
- `per-tenant-skills` (FEAT-707) — same tenant tree now also hosts `routes.yaml`.

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `parrot/registry/routing/embedding_router.py` | extends | labels beyond `OutputMode`; `RouteScore` gains the label |
| `parrot/registry/capabilities/models.py` (`IntentRouterConfig`) | extends | composite keys in `output_mode_routes`; loader hook |
| `parrot/bots/mixins/intent_router.py` | extends | `_resolve_output_mode()` resolves hint; tie-breaker over labels |
| `parrot/bots/abstract.py` (`_apply_default_output_mode`, `ask`) | extends | carries `a2ui_component`; precedence slot for FEAT-756 |
| `parrot/bots/data.py` (`DEFAULT_OUTPUT_MODE_ROUTES`, `PandasAgent.configure`) | extends | new default utterances; load agent/tenant bank |
| `parrot/outputs/a2ui/catalog/parrot/*` | reuses | schemas drive the emitter; optional per-component authoring notes |
| `parrot/outputs/formats/` (+ ai-parrot-visualizations) | adds | the catalog-driven `OutputMode.A2UI` emitter |
| `parrot/skills/tenancy.py` (FEAT-707 tree) | reuses | tenant override location |
| `packages/ai-parrot-server/ui/.../canvas/a2ui/`, `ChatBubble` | extends | inline render of KPICard / InfoCard / Timeline / Graph |
| handlers `agent.py` | none expected | `a2ui_envelope` passthrough already exists (L2727/2874/2975) |
| navigator-frontend-next | none (documented contract) | consumer |

---

## Code Context

### User-Provided Code
```text
# Source: NAV-10382 review (Jesus Lara, 2026-10-27), verbatim intent:
# - "lo que pretenden con el intent-router es que el usuario no tenga que
#    definir a mano con un selector el 'kind' del next bubble sino que se
#    determine a partir del request"
# - "las structured output modes para los inline chat bubbles se limitan a
#    chart/map/table, no hay kpi cards ni otros tipos de artefactos inline
#    renderizables … este catálogo de objetos renderizables inline podría
#    ampliarse a futuro"
# Rev 1 (WhatsApp, 2026-06-04): decision in the backend, before the turn,
#    coupled to data production, feasibility-aware, never force a shape.
```

### Verified Codebase References (rev 2, dev @ 2026-10-27)

#### Classes & Signatures
```python
# parrot/bots/mixins/intent_router.py
class IntentRouterMixin:                                                  # :123
    def configure_output_router(self, config: IntentRouterConfig) -> None # :175  builds EmbeddingIntentRouter, add_route(OutputMode(mode_value), utterances)
    async def _resolve_output_mode(self, query, ctx) -> Optional[OutputMode]  # :209  threshold/margin policy, chains super()
    async def _llm_disambiguate_output_mode(self, query, candidates) -> Optional[OutputMode]  # :252  bounded invoke() tie-breaker

# parrot/registry/routing/embedding_router.py
class RouteScore(NamedTuple): mode: Optional[OutputMode]; score: float; runner_up: float; ambiguous: bool  # :37-56
class EmbeddingIntentRouter:                                              # :57
    def add_route(self, mode: OutputMode, utterances: list[str]) -> None  # :108
    def route_scores(self, query) -> list[tuple[OutputMode, float]]       # :125
    def route(self, query) -> RouteScore                                  # :152

# parrot/registry/capabilities/models.py — IntentRouterConfig (FEAT-224 fields)
enable_output_mode_routing: bool = False                                  # :208
embedding_model: str = "intfloat/multilingual-e5-small"
output_mode_routes: dict[str, list[str]]  # keys are OutputMode VALUES    # :216-222
output_mode_threshold: float = 0.85; discrepancy_margin: float = 0.05     # :223-

# parrot/bots/abstract.py
async def _resolve_output_mode(self, query, ctx) -> Optional[OutputMode]  # :4168  no-op terminal of the MRO chain
def _apply_default_output_mode(self, output_mode) -> OutputMode           # :4191  explicit > router > agent default
# ask(): output_mode: OutputMode = OutputMode.DEFAULT                     # :4140

# parrot/bots/data.py
DEFAULT_OUTPUT_MODE_ROUTES: Dict[str, List[str]]                          # :297  structured_chart / _table / _map, EN+ES
# PandasAgent.configure(): if self._output_routing_enabled or ...: configure_output_router(...)  # :~896-903
# PandasAgent.ask(): _resolved_mode = await self._resolve_output_mode(question, ctx)  # :1350
#                    output_mode = self._apply_default_output_mode(output_mode)       # :1358

# parrot/models/outputs.py
class OutputMode(str, Enum)   # :23-55  … STRUCTURED_CHART/TABLE/MAP, A2UI = "a2ui" (FEAT-273), CARD (legacy)

# parrot/outputs/formats/__init__.py
_A2UI_REPLACEMENTS: dict[OutputMode, str]   # :15-24  CARD -> "A2UI with the InfoCard/KPICard catalog components", …

# packages/ai-parrot-visualizations/src/parrot/outputs/formats/
STRUCTURED_CHART_SYSTEM_PROMPT  # structured_chart.py:40 ; @register_renderer(OutputMode.STRUCTURED_CHART, system_prompt=…)  :79
class StructuredOutputBase: _route_envelope  # structured_base.py:87 ; _emit_a2ui_envelope :139

# parrot/outputs/a2ui/catalog/parrot/
kpicard.py   KPICARD_SCHEMA (label, value, unit, delta, trend, icon, color, comparisonPeriod, higherIsBetter, series…); class KPICardComponent :166
infocard.py, timeline.py, chart.py, datatable.py, map.py, report.py, form.py, filterbar.py, htmldocument.py, infographic.py
# parrot/outputs/a2ui/graph/{models.py (GraphSpec), mermaid.py (to_mermaid/from_mermaid: flowchart, dag, state), layout.py}
# parrot/outputs/a2ui/adapters/structured.py — StructuredXConfig -> CreateSurface (pure, deterministic)

# agents/flex_dashboard.py (local, gitignored): FlexDashboard(..., output_routing=True)  # :185
```

#### Verified Imports
```python
from parrot.bots.mixins.intent_router import IntentRouterMixin
from parrot.registry.routing.embedding_router import EmbeddingIntentRouter, RouteScore
from parrot.registry.capabilities.models import IntentRouterConfig
from parrot.models.outputs import OutputMode
from parrot.bots.data import DEFAULT_OUTPUT_MODE_ROUTES
```

### Does NOT Exist (Anti-Hallucination)
- ~~Composite route keys (`"a2ui:KPICard"`)~~ — `add_route()` takes an
  `OutputMode`; `configure_output_router` does `OutputMode(mode_value)` and
  warns on anything else.
- ~~A component hint on `_resolve_output_mode()` / `RouteScore`~~ — both carry
  a bare `OutputMode`.
- ~~A catalog-driven LLM authoring prompt for KPICard / InfoCard / Timeline /
  Graph in an inline answer~~ — only `structured_chart/_table/_map` have
  registered system prompts (`has_system_prompt`, `formats/__init__.py:117`);
  `OutputMode.A2UI` has no generic emitter for a chat turn.
- ~~A per-agent / per-tenant phrase-bank loader (`routes.yaml`)~~ — the bank is
  the code constant or a Python-constructed `IntentRouterConfig`.
- ~~A `parrot_presentation` / inline-eligibility marker in
  `metadata.extensions`~~ — renderers infer kind from the root component.
- ~~The rev 1 feasibility layer (`CapabilityRegistry.not_for` consulted by the
  output router)~~ — never built; FEAT-224 routes on phrasing only.
- Rev 1's `artifacts/poc/output_mode_autodetect_poc.py` (regex POC) — not in
  the tree anymore (unverified — check before citing).

---

## Parallelism Assessment

- **Internal parallelism**: medium. Three independent threads — (a) router
  label/hint channel + config loader, (b) catalog-driven emitter + conformance
  tests, (c) reference renderer inline components — meet only at the
  `a2ui_component` kwarg name and the `parrot_presentation` key, which the spec
  must fix up front.
- **Cross-feature**: FEAT-753 (MermaidDiagram), FEAT-754 (C4 Graph kind) and
  FEAT-756 (metric default shape) consume the hint channel — they depend on
  this feature's (a) landing first, not on (b)/(c). FEAT-752 chips may emit
  presentation chips carrying `a2ui_component` hints (additive).
- **Recommended isolation**: one feature worktree; tasks for (a)/(b)/(c) can
  run concurrently inside it.

---

## Open Questions

Resolved by FEAT-224 (carried forward from rev 1):
- [x] A vs B vs C (rev 1) — *Resolved by FEAT-224*: deterministic local embedding router (`multilingual-e5-small`) hooked into `ask()` via `_resolve_output_mode()`, bounded LLM tie-breaker only on ambiguity; rev 1's "LLM classifier on every Auto turn" was superseded.
- [x] Classifier model + budget — *Resolved by FEAT-224*: `intfloat/multilingual-e5-small`, CPU, encoder + phrase bank encoded once at CONFIGURE; no cloud call on the hot path.
- [x] Keyword fast-path vs pure LLM — *Resolved by FEAT-224*: embeddings replace both; no regex fast-path.
- [x] Extend `IntentRouterMixin` vs standalone router — *Resolved by FEAT-224*: extends the mixin; `AbstractBot._resolve_output_mode()` is the cooperative no-op terminal.
- [x] Confidence threshold — *Resolved by FEAT-224*: `output_mode_threshold=0.85`, `discrepancy_margin=0.05`, calibrated for e5-small.

Open for rev 2 (owner: Jesus Lara unless noted):
- [ ] Composite label format: `"a2ui:<Component>"` string keys inside `output_mode_routes`, or a parallel `a2ui_component_routes: dict[str, list[str]]` field? (string keys keep one bank; a parallel field keeps `OutputMode(mode_value)` validation untouched)
- [ ] Where the per-agent / per-tenant phrase bank lives: `AGENTS_DIR/{agent}/routes.yaml` + `tenants/{tenant}/routes.yaml` (mirrors FEAT-707 skills), or a key inside the existing agent config document?
- [ ] Emitter contract: LLM `structured_output` from a pydantic model generated off the catalog JSON schema, or free JSON + `validate_envelope` (the structured_chart style)? Graph likely needs authoring notes either way.
- [ ] Name/namespace of the inline marker: `metadata.extensions.parrot_presentation` (new) vs extending an existing extension key — check `docs/outputs/a2ui-v1.md` "metadata.extensions" conventions. — *Owner: spec author*
- [ ] Should rev 1's data-feasibility layer be revived per component (KPICard needs a scalar, Timeline needs dated rows), as a post-production downgrade inside the emitter? (recommendation: yes, emitter-local, no `CapabilityRegistry` coupling)
- [ ] Which inline components ship in v1: KPICard + InfoCard + Timeline + Graph (recommended), or KPICard only first?
