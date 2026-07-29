---
type: Wiki Overview
title: 'Brainstorm: Output-Mode Intent Router (LLM-driven chart / map / table selection)'
id: doc:sdd-proposals-output-mode-intent-router-brainstorm-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Today the caller must **manually** choose the output format from a frontend
relates_to:
- concept: mod:parrot.bots.mixins
  rel: mentions
- concept: mod:parrot.models.outputs
  rel: mentions
- concept: mod:parrot.registry.capabilities
  rel: mentions
- concept: mod:parrot.registry.capabilities.models
  rel: mentions
---

---
# SDD flow type and base branch (FEAT-145).
type: feature
base_branch: dev
---

# Brainstorm: Output-Mode Intent Router (LLM-driven chart / map / table selection)

**Date**: 2026-06-04
**Author**: Juan Ruffato
**Status**: exploration
**Recommended Option**: A (with layered feasibility from B)

> Realizes the deferred **Option C / Q4** ("output-side artifact/kind selector —
> agent proposes `kind` / router validates") explicitly left out of
> `structured-artifact-contract` (FEAT-223) and `structured-config-homologation`
> (FEAT-224). Distinct from the **input-side** FEAT-070 Intent Router, but reuses
> its machinery.

---

## Problem Statement

Today the caller must **manually** choose the output format from a frontend
dropdown (Table, Plotly, ECharts, Structured Chart, Map Visualization, …). The
`Default (Auto)` option only auto-detects **map** (post-hoc, data-aware —
`data.py:_detect_map_intent`); chart and table are never auto-selected. We want
the agent to **detect from the natural-language request** whether the user wants
a chart, a map, or a table, and set the output mode accordingly — so the user
stops hunting through the dropdown.

**Why the naïve approach is wrong (Jesus's feedback, 2026-06-04):**
- The decision must be made by the **LLM in the backend**, not by regex/keyword
  matching nor by the frontend. Regex misreads intent — e.g. *"map to XYZ"* may
  mean *make a map* or *associate/map elements*.
- The decision must be **coupled to data production**: a pie needs exactly two
  columns (categories + values). If the `AIMessage` already came back with the
  wrong shape, nothing can render it. So the mode must be known **when the LLM
  receives the question**, so the LLM shapes the result correctly.
- It must respect **feasibility**: *"map by region of expenses"* over finance
  data (which has no regions) is impossible — the system must not force a map it
  cannot fill.

**Affected:** PandasAgent users (e.g. `troc_finance`); frontend visualization
consumers; anyone relying on `Default (Auto)`.

## Constraints & Requirements

- Intent decided by the **LLM**, not regex (regex only acceptable as an optional
  fast-path with an LLM fallback — the same pattern FEAT-070 already uses).
- The mode must be set **before/at the turn** so the LLM produces output-shaped
  data (pie → 2 columns). No post-hoc forcing of a mode onto mismatched data.
- **Layered feasibility**: (1) capability-aware *upfront* (don't route to a kind
  no resource can satisfy — e.g. map over non-geo data), and (2) *post-production*
  validation (downgrade the kind if the produced columns don't fit).
- **Conservative**: ambiguous wording → `OutputMode.DEFAULT` (today's behavior);
  never surprise the user.
- **Non-override**: when the caller explicitly picks a mode (dropdown ≠ Auto),
  the router must NOT override it.
- Scope: **chart + table + map**.
- Reuse FEAT-070 (`_llm_route` + `CapabilityRegistry`) rather than build parallel
  machinery.
- Graceful degradation: any router/LLM error → `DEFAULT` (never raise).

---

## Options Explored

### Option A: Pre-turn LLM output-mode router in `ask()` (capability-aware)

A lightweight LLM classification step runs **inside `PandasAgent.ask()` before
the main turn** (before the system prompt is built at `data.py:1411`). It uses
`client.invoke()` (FEAT-069) — the same call FEAT-070's `_llm_route` uses — with
the user prompt **plus the agent's capabilities** (datasets and their `not_for`
exclusions, pulled from a `CapabilityRegistry`) to decide one of
`STRUCTURED_CHART | STRUCTURED_MAP | STRUCTURED_TABLE | DEFAULT`. The chosen mode
then flows through the **existing** structured pipeline unchanged: the structured
system prompt is appended (`data.py:1411-1418`) and the LLM produces
output-shaped data in the **single** main turn (validated in production for
`STRUCTURED_CHART`). A post-production validator can still downgrade the kind if
the produced columns don't fit (layer 2).

✅ **Pros:**
- Matches Jesus's mental model exactly: *"el LLM al recibir la pregunta … cambia
  el output_mode para que se retorne lo necesario"*.
- Coupling is preserved — the main turn runs with the structured prompt, so the
  LLM shapes the data (pie → 2 cols).
- **Upfront feasibility** via `CapabilityRegistry.not_for` (Jesus's finance-map
  case is decided *before* wasting the main turn).
- Reuses `_llm_route` + `CapabilityRegistry` + `RoutingTrace` (FEAT-070).
- Existing post-hoc `_detect_map_intent` stays as a data-aware safety net.

❌ **Cons:**
- Adds **one extra LLM call** per `Default (Auto)` turn (cheap model, ~20 tokens,
  but ~0.3–1s latency).
- Needs a **new touch-point in `ask()`** — FEAT-070 only hooks `conversation()`.
- Classifier call needs a client resolved before the system prompt is built
  (`self._llm` opens at `data.py:1442`, after `1411`) → small reorder or a
  short-lived client context.

📊 **Effort:** Medium

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| (none new) | — | Reuses `client.invoke()`, `CapabilityRegistry`, Pydantic |

🔗 **Existing Code to Reuse:**
- `parrot/bots/mixins/intent_router.py:373` — `_llm_route` invoke() pattern.
- `parrot/registry/capabilities/registry.py` — `CapabilityRegistry` (search + `not_for`).
- `parrot/clients/base.py:1586` — `invoke()` (FEAT-069).
- `parrot/bots/data.py:1354` — output-mode decision point in `ask()`.

---

### Option B: "Agent proposes the kind" (single-call, self-declared)

The **main** LLM turn declares the output kind as a structured field of its own
response (it already knows the data it produced and whether a map is feasible).
A thin validator confirms or **downgrades** the kind against the real produced
columns (pie needs ≥2 usable cols; map needs geo cols → else `table`/`DEFAULT`),
reusing the deterministic `_safe_x`/`_safe_y` logic already in the chart renderer.

✅ **Pros:**
- **Single LLM call** — zero extra latency.
- Intent + data-shaping are coupled *by construction* (same turn that makes the
  data names the kind).
- Feasibility is natural: the LLM won't claim "map" if it produced no geo data.

❌ **Cons:**
- Requires the LLM, under `DEFAULT`, to emit a **polymorphic** output (pick kind
  *and* emit the matching config) — heavier prompt engineering than reusing the
  per-mode structured prompts.
- Self-reported kind is less controllable than a dedicated classifier; needs the
  validator as a guard.
- Feasibility is **post-production only** (no upfront `not_for` short-circuit) —
  a doomed map still consumes the turn before being downgraded.

📊 **Effort:** Medium–High (polymorphic structured output)

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| (none new) | — | Pydantic discriminated union for the kind + config |

🔗 **Existing Code to Reuse:**
- `parrot/outputs/.../structured_chart.py` — `_safe_x`/`_safe_y` deterministic fallback (FEAT-223).
- `parrot/bots/data.py:1588` — existing STRUCTURED_CHART data-injection plumbing.

---

### Option C: Extend FEAT-070 natively — output-mode as a second routing dimension

Make output-mode a first-class part of Jesus's router: add `output_mode:
Optional[OutputMode]` to `RoutingDecision`, teach `_llm_route` to emit it, and
add an **`ask()` hook** to `IntentRouterMixin` (today it only intercepts
`conversation()`). One unified router then decides both *who answers* (input
strategy) and *how to present* (output kind), capability-aware end-to-end.

✅ **Pros:**
- Architecturally unified — one router, one decision object, one trace.
- Strongest long-term story; both routing dimensions share the registry + invoke.

❌ **Cons:**
- Highest effort and blast radius — touches FEAT-070 core (`RoutingDecision`,
  `_llm_route`, mixin), which is in active use by `conversation()` agents.
- Conflates two orthogonal dimensions (strategy vs format) in one decision.
- Overkill for PandasAgent's immediate need (it doesn't use the input strategies).

📊 **Effort:** High

🔗 **Existing Code to Reuse:**
- `parrot/registry/capabilities/models.py:91` — `RoutingDecision`.
- `parrot/bots/mixins/intent_router.py` — whole mixin.

---

## Recommendation

**Option A**, with the **post-production validation from Option B** layered on
top (the "both" feasibility the team asked for).

Reasoning:
- A is the closest fit to Jesus's stated model (LLM decides at question-reception
  and changes `output_mode` so the right data is produced) while **reusing** his
  FEAT-070 machinery (`_llm_route` + `CapabilityRegistry`) rather than inventing a
  parallel one.
- A gets **upfront feasibility** for free via `CapabilityRegistry.not_for`
  (directly solves the finance-map case) — B cannot short-circuit before the turn.
- A reuses the **existing, production-validated** structured pipeline (set
  `output_mode` → structured prompt → single main turn), so the only genuinely new
  code is the classifier + an `ask()` touch-point. B needs a polymorphic output
  contract; C rebuilds Jesus's core.
- We accept A's **one extra cheap LLM call** as the price of robustness over
  regex — Jesus explicitly preferred LLM correctness over a zero-latency heuristic.
- Layer B's **column-fit validation** at the end as a cheap safety net (downgrade
  an unfillable kind to `table`/`DEFAULT`), giving defense-in-depth feasibility.

C is recorded as the **long-term unification** to revisit once output-mode routing
proves out on PandasAgent.

---

## Feature Description

### User-Facing Behavior
With the dropdown on **`Default (Auto)`**, the user simply asks in natural
language — *"dame un gráfico de torta de los gastos 2025"*, *"muéstrame los
empleados activos en una tabla"*, *"sales by region on a map"* — and the agent
returns the right structured artifact (chart / table / map) without the user
selecting a format. Plain questions (*"what's our net income?"*) return normal
text. If the user explicitly picks a mode, that choice is always respected.

### Internal Behavior
1. In `ask()`, when `output_mode == DEFAULT`, an **output-mode router** runs a
   lightweight `invoke()` classification: input = user prompt + the agent's
   capability summary (datasets and their `not_for`). Output = a structured
   `OutputModeDecision { kind: chart|map|table|none, confidence, reasoning }`.
2. **Upfront feasibility**: candidates whose `not_for` excludes the requested kind
   are filtered (finance has no geo → map is dropped, falls back to `none`).
3. If a confident kind is chosen, set `output_mode` to the matching
   `STRUCTURED_*` value **before** the system prompt is built → the existing
   pipeline produces output-shaped data in the single main turn.
4. **Post-production validation** (layer 2): after the turn, if the produced
   columns can't satisfy the kind (e.g. <2 usable cols for a pie, no geo cols for
   a map), **downgrade** to `table`/`DEFAULT` rather than emit a broken artifact.
5. A `RoutingTrace` records the decision for observability.

### Edge Cases & Error Handling
- **Ambiguous prompt** → `none` → `DEFAULT` (unchanged behavior).
- **Explicit caller mode** → router skipped entirely.
- **Infeasible kind** (map over non-geo) → upfront `not_for` drop, else layer-2
  downgrade; never a broken/empty artifact.
- **invoke() error / timeout** → `DEFAULT` (never raise), mirroring `_llm_route`.
- **No `CapabilityRegistry` configured** → router still classifies on the prompt
  alone (no feasibility layer 1), layer 2 still applies.

---

## Capabilities

### New Capabilities
- `output-mode-intent-router`: LLM-driven, capability-aware selection of the
  structured output kind (chart/map/table) for data agents, with layered
  feasibility and conservative fallback to DEFAULT.

### Modified Capabilities
- `structured-artifact-contract` (FEAT-223) — fulfils its deferred Option C/Q4.
- `intent-router` (FEAT-070) — reused (and optionally extended in Option C).

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `parrot/bots/data.py` (`PandasAgent.ask`) | extends | new pre-turn output-mode decision at the `output_mode == DEFAULT` point (~:1354), before the system prompt build (~:1411) |
| `parrot/registry/capabilities/` | reuses | `CapabilityRegistry`, `invoke()` routing pattern, `not_for` |
| `parrot/clients/*` (`invoke`) | depends on | FEAT-069 lightweight call |
| `navigator-plugins/docs/troc.py` | modifies | add `routing_meta.not_for` to datasets (today they use `usage_guidance` do/dont, which the registry does NOT read as `not_for`) |
| `parrot/bots/mixins/intent_router.py` | extends (Option C only) | add `ask()` hook + `output_mode` on `RoutingDecision` |
| frontend `Default (Auto)` | none (backend-only) | dropdown semantics unchanged |

---

## Code Context

### User-Provided Code
```text
# Source: WhatsApp thread with Jesus Lara (2026-06-04), verbatim intent:
# - "el intent router lo tiene que hacer el LLM"
# - "usar regex o word expressions para extraer intent no es óptimo … puedes
#    terminar infiriendo incorrectamente lo que el usuario quiere"
# - Pie needs 2 columns; if the AIMessage didn't come shaped that way you can't
#   render it → mode must be decided when the LLM receives the question.
# - "map by region over finance data" is infeasible (no regions) → must not force.
```

### Verified Codebase References

#### Classes & Signatures
```python
# parrot/bots/mixins/intent_router.py
class IntentRouterMixin:                                  # :118  (overrides conversation(), NOT ask())
    def configure_router(self, config, registry) -> None: # :149  (inactive until called)
    async def conversation(self, prompt, **kwargs):       # :166
    async def _llm_route(self, prompt, strategies, candidates) -> Optional[RoutingDecision]:  # :373
    # _KEYWORD_STRATEGY_MAP (:54) — FEAT-070's own keyword fast-path before the LLM

# parrot/registry/capabilities/registry.py
class CapabilityRegistry:
    def register_from_datasource(self, source) -> None:   # :58  reads source.routing_meta["not_for"]
    def register_from_tool(self, tool) -> None:           # :90
    def register_from_yaml(self, path) -> None:           # :114
    async def build_index(self, embedding_fn) -> None:    # :148  (needs an async embed fn)
    async def search(self, query, top_k) -> list[RouterCandidate]:  # :183

# parrot/registry/capabilities/models.py
class ResourceType(str, Enum):    # :25  DATASET, TOOL, GRAPH_NODE, PAGEINDEX, VECTOR_COLLECTION
class RoutingType(str, Enum):     # :35  GRAPH_PAGEINDEX, DATASET, VECTOR_SEARCH, TOOL_CALL, FREE_LLM, MULTI_HOP, FALLBACK, HITL  (NO output formats)
class CapabilityEntry(BaseModel): # :48  name, description, resource_type, metadata, not_for(:69)
class RoutingDecision(BaseModel): # :91  routing_type, candidates, cascades, confidence, reasoning
class IntentRouterConfig(BaseModel): # :149  confidence_threshold, hitl_threshold, custom_keywords, ...

# parrot/clients/base.py
async def invoke(self, prompt, *, output_type=None, structured_output=None,
                 model=None, system_prompt=None, max_tokens=4096,
                 temperature=0.0, ...) -> InvokeResult:   # :1586  (stateless, no history)

# parrot/bots/data.py
class PandasAgent(BasicAgent):
    async def ask(self, ...):                             # :1294
        # output_mode default                              :1354  ← router decision point
        # structured system-prompt addon (uses output_mode):1411-1418
        # async with self._llm as client                  :1442  ← client available here
        # STRUCTURED_CHART structured_output config        :~1508
        # first client.ask(**llm_kwargs)                   :1535
def _detect_map_intent(question, df) -> bool:             # :410  (post-hoc, data-aware — safety net)
        # post-hoc DEFAULT→MAP auto-switch                 :1784

# parrot/models/outputs.py
class OutputMode(str, Enum):  # :37  STRUCTURED_CHART(:70), STRUCTURED_TABLE(:71), STRUCTURED_MAP(:72), DEFAULT, MAP, ...
```

#### Verified Imports
```python
from parrot.registry.capabilities import CapabilityRegistry            # registry/capabilities/__init__.py:16
from parrot.registry.capabilities.models import (                      # models.py
    CapabilityEntry, RoutingDecision, IntentRouterConfig, ResourceType,
)
from parrot.bots.mixins import IntentRouterMixin                       # bots/mixins/__init__.py:6
from parrot.models.outputs import OutputMode                           # models/outputs.py:37
```

#### Key Attributes & Constants
- `CapabilityEntry.not_for` → `list[str]` (registry/capabilities/models.py:69) — the feasibility lever.
- `IntentRouterMixin._router_active` → `bool` (default False; no-op until `configure_router`).
- A working POC of the **regex** classifier (rejected as the primary mechanism)
  lives at `artifacts/poc/output_mode_autodetect_poc.py` — useful only as an
  optional fast-path or as a test oracle.

### Does NOT Exist (Anti-Hallucination)
- ~~An output-format member of `RoutingType`~~ — it only has INPUT strategies.
- ~~`IntentRouterMixin.ask()`~~ — the mixin overrides `conversation()` only; PandasAgent's data path is NOT intercepted.
- ~~An `OutputModeRouter` / output-mode classifier in the codebase~~ — does not exist (the regex version was reverted; lives only under `artifacts/poc/`).
- ~~`routing_meta` / `not_for` on the `troc_finance` datasets~~ — they define `usage_guidance` (do/dont), which `register_from_datasource` does NOT read as `not_for`.
- ~~A global `enable_intent_router` / `enable_output_router` flag~~ — FEAT-070 activates only via explicit `configure_router()`.

---

## Parallelism Assessment

- **Internal parallelism**: low. The core is a single decision point in
  `PandasAgent.ask()` plus a small router module; tightly coupled. Dataset
  `not_for` annotations (in navigator-plugins) and the router itself could be two
  small parallel tasks, but the integration is one sequential thread.
- **Cross-feature independence**: touches `data.py` (shared with FEAT-224
  artifact-envelope code — already merged) and reuses FEAT-070 (read-only unless
  Option C). Low conflict risk if Option A/B; **high** if Option C (edits FEAT-070
  core).
- **Recommended isolation**: `per-spec` (one worktree, sequential tasks).
- **Rationale**: small, coupled change centered on one method; parallel worktrees
  add ceremony without benefit.

---

## Open Questions
- [ ] A vs B vs C — final architecture call (recommendation: A + B's layer-2 validation). — *Owner: Jesus Lara*
- [ ] Classifier model + budget: which lightweight model for the `invoke()` call, and is the ~0.3–1s extra latency acceptable on every Auto turn? — *Owner: Jesus Lara*
- [ ] Optional keyword fast-path (FEAT-070-style) before the LLM call to cut latency on obvious prompts, or pure-LLM only? — *Owner: Jesus Lara / Juan*
- [ ] Where do dataset `not_for` annotations live — in each agent's `configure()` (navigator-plugins) or a shared YAML via `register_from_yaml`? — *Owner: Juan*
- [ ] Should this extend FEAT-070's `IntentRouterMixin` (add `ask()` hook) or be a standalone `OutputModeRouter` that merely reuses `CapabilityRegistry`/`invoke()`? — *Owner: Jesus Lara*
- [ ] Confidence threshold for committing to a kind vs falling back to DEFAULT. — *Owner: Juan*
