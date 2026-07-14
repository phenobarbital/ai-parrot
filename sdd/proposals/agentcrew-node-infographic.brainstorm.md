---
# SDD flow type and base branch (FEAT-145).
type: feature
base_branch: dev
---

# Brainstorm: AgentCrew ResultAgent — End-of-Flow Multi-Tab Infographic Node

**Date**: 2026-07-14
**Author**: Jesus Lara
**Status**: exploration
**Recommended Option**: A

---

## Problem Statement

When an `AgentCrew` finishes a multi-agent run, its output is a `FlowResult`
containing the final `output`, an optional LLM `summary`, and per-node execution
records — but there is **no presentation-ready artifact** that lets a human
consume the run as a whole. To understand "what did the crew actually do", a
user today has to read the raw `summary`, then dig into `execution_memory` node
by node.

We want a reusable, opt-in capability that, **at the end of any crew run**,
produces a single self-contained **multi-tab HTML infographic**:

- **Tab 1** — Executive Summary & Insights (cross-cutting synthesis).
- **Tab 2** — Final Result of the AgentCrew execution.
- **Tabs 3…N** — One tab per research agent, showing that agent's result.

The generator is a proper internal **`ResultAgent`** (an `Agent` carrying an
`InfographicToolkit`) that is **registered in the `AgentRegistry`** so it is
discoverable/overridable by any crew, and it reads per-agent results from the
crew's **Execution Result memory** (`ExecutionMemory`).

**Who is affected**: developers/operators building crews (they flip one flag and
get a shareable report); end users/stakeholders who receive the infographic.

**Why now**: the `InfographicToolkit` (FEAT-197) already ships a built-in
`multi_tab` template, `AgentCrew` already persists per-agent results in
`ExecutionMemory`, and lifecycle hooks (FEAT-157) already exist — the building
blocks are all present and unassembled.

## Constraints & Requirements

- **Opt-in, non-breaking**: default behavior of every `run_*()` mode is
  unchanged; the feature activates only via an explicit flag.
- **All four execution modes** (`run_flow`, `run_sequential`, `run_parallel`,
  `run_loop`) must be supported — reading from `ExecutionMemory`, which every
  mode populates.
- **Hybrid rendering**: the Executive-Summary/Insights tab is LLM-authored; the
  final-result tab and per-agent tabs are built **deterministically** from
  `ExecutionMemory` into `tab_view` blocks, then rendered via the toolkit's
  `crew_report` template (a bound-relaxed derivative of the built-in `multi_tab`).
- **Insights reuse existing synthesis**: feed the crew's own
  `SynthesisMixin` output into Tab 1 rather than running a second synthesis pass.
- **Registry-resolved**: the ResultAgent is registered once
  (`@register_agent`) and resolved by a **configurable name** (default
  `"result-agent"`), so a crew can supply a custom ResultAgent.
- **Graceful degradation**: any failure in synthesis/render/validation must
  **not** lose the crew's real work — log and return `FlowResult` with
  `infographic=None`.
- **ResultAgent is not a research agent**: it must be excluded from the
  per-agent tabs and from synthesis/`execution_memory` accounting to avoid
  self-referential recursion.
- Async-first, Pydantic models, `self.logger` — per project rules.
- **Dynamic tab count — NOT enforced**: the number of tabs is driven by the run,
  **minimum one** (a single result with no per-agent breakdown) and **maximum =
  number of research agents** (plus the fixed Executive-Summary and Final-Result
  tabs). The built-in `multi_tab` template hard-codes `min_items=3, max_items=7`
  on its `tab_view` block, so this feature **cannot use `multi_tab` as-is** — it
  must register a bound-relaxed template variant (e.g. `crew_report`) that
  removes the 3–7 constraint.
- **Large / non-text per-agent results**: **summarize**, or **link out** when the
  content can be published to the `ArtifactStore` and yields a URL — never dump
  an unbounded payload into a tab.
- **ResultAgent location & default LLM**: the `ResultAgent` lives under
  `parrot/bots/flows/`, and its default LLM is **Gemini 3.5 Flash** (via the
  `google` client) when the crew supplies no `_llm`. *(Confirm the exact model
  identifier string at spec time.)*

---

## Options Explored

### Option A: Opt-in flag → internal finalization step invoking a registry-resolved ResultAgent  *(RECOMMENDED)*

`AgentCrew.__init__` gains `generate_infographic: bool = False` (plus
`result_agent_name: str = "result-agent"` and optional render config). Each
`run_*()` method, after it builds its `FlowResult` and runs synthesis but
**before** `_fire_hooks()`/`return`, calls a new private coroutine
`_finalize_infographic(result)`. That step:

1. Resolves the ResultAgent from `AgentRegistry` by name (default
   `"result-agent"`), instantiating it with the crew's `_llm`.
2. Builds a deterministic `tab_view` structure from
   `self.execution_memory` snapshot (Tab 2 = final result, Tabs 3…N =
   per-agent results), **excluding** the ResultAgent itself.
3. Passes the crew's `summary` (SynthesisMixin output) + the assembled tab
   structure to the ResultAgent, which LLM-authors Tab 1 and calls
   `infographic_render(template_name="crew_report", …)`.
4. Attaches the rendered artifact to a **new `FlowResult.infographic` field**;
   on any exception, logs and leaves it `None`.

Because the finalization hangs off `run_*()` uniformly, it is mode-agnostic —
`run_flow`'s DAG, `run_parallel`'s gather, `run_sequential`'s pipeline, and
`run_loop`'s iterations all converge on the same `ExecutionMemory`.

✅ **Pros:**
- One flag, works identically in all four modes (matches the "all modes" +
  "internal post-run step" decisions).
- ResultAgent stays a real, registered, reusable agent — satisfies "available
  for any crew" and remains overridable by name.
- Hybrid render keeps per-agent tabs faithful/deterministic while still getting
  LLM-quality insights, at minimal extra token cost (reuses existing synthesis).
- Clean consumer surface (`result.infographic`); no self-referential tab.

❌ **Cons:**
- Touches every `run_*()` method (one call-site each) and adds a field to
  `FlowResult` — a shared type.
- The ResultAgent is not represented as a node in `run_flow`'s
  `workflow_graph`, so it won't appear in graph visualizations (acceptable —
  it's explicitly excluded by design).

📊 **Effort:** Medium

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| (internal) `parrot.tools.infographic_toolkit.InfographicToolkit` | Render multi-tab HTML | FEAT-197, `return_direct=True`, `multi_tab` template built-in |
| (internal) `parrot.registry.register_agent` | Register ResultAgent for discovery | decorator on `agent_registry` |
| `pydantic` | `FlowResult.infographic` model / render envelope | already a core dep |
| `jinja2` (via `TemplateEngine`) | Optional custom template rendering | only if a custom template is supplied |

🔗 **Existing Code to Reuse:**
- `parrot/bots/flows/crew/crew.py` — `AgentCrew` (`__init__` L134, `execution_memory` L194, `on_complete` L252, `_fire_hooks` L282, `final_agents` L699, `run_sequential` L1172, `run_flow` L2289).
- `parrot/bots/flows/core/storage/memory.py` — `ExecutionMemory.get_results_by_agent`/`get_snapshot`.
- `parrot/tools/infographic_toolkit.py` — `InfographicToolkit` (L110), `render` (L240), `get_tools` (L184).
- `parrot/models/infographic_templates.py` — `TEMPLATE_MULTI_TAB` (`multi_tab`, `tab_view`, 3–7 tabs).
- `parrot/bots/agent.py` — `Agent`/`BasicAgent` with `agent_tools()` override (L305/L1207).
- `parrot/agents/demo.py` — `@register_agent` example (L148).

---

### Option B: Real terminal DAG node in `run_flow` + post-step fallback elsewhere

In `run_flow`, inject an actual terminal `CrewAgentNode` that fans-in from
`final_agents` and produces the infographic as a genuine graph node; for
`run_sequential/parallel/loop`, fall back to the Option-A post-run step.

✅ **Pros:**
- The infographic step is a first-class node in `run_flow` — visible in graph
  telemetry and `on_node_event` listeners.
- Conceptually closest to the literal "add a new node" phrasing.

❌ **Cons:**
- Two divergent code paths (graph node vs post-run step) doubling test surface.
- The injected node would land in `FlowResult.agents`/`execution_memory` and
  could be swept into synthesis and the per-agent tabs — exactly the
  self-referential recursion we chose to avoid; requires special-case filtering
  at every `.agents`/memory read.
- `final_agents` is computed at L699 from `workflow_graph` successors; injecting
  a node mutates that graph and reshuffles terminal detection.

📊 **Effort:** High

📦 **Libraries / Tools:** same as Option A, plus deeper `CrewAgentNode`/FSM wiring.

🔗 **Existing Code to Reuse:**
- `parrot/bots/flows/crew/nodes.py` — `CrewAgentNode`.
- `parrot/bots/flows/crew/crew.py` — `_update_workflow_metadata` (final_agents, L699), `run_flow` (L2289).

---

### Option C: Deterministic-only infographic via an `on_complete` lifecycle hook (no LLM, no agent)  *(unconventional)*

Skip the ResultAgent entirely. Ship a builder function
`build_crew_infographic(result, memory)` and register it through the existing
`crew.on_complete(...)` hook (FEAT-157). It maps `ExecutionMemory` straight into
`multi_tab` `tab_view` blocks and calls `InfographicToolkit.render` directly —
Tab 1 reuses the crew `summary` verbatim (no fresh insights).

✅ **Pros:**
- Zero LLM cost, fully reproducible, trivially unit-testable.
- **Least invasive** — no changes to `run_*()`; purely additive via the existing
  hook API (`on_complete` L252, `_fire_hooks` L282).
- A useful fallback/building-block that Option A can reuse for its deterministic
  tabs.

❌ **Cons:**
- No true "insights" synthesis — contradicts the "Executive Summary & Insights"
  requirement (Tab 1 is just the raw summary).
- Not an `Agent` and not in `AgentRegistry` — fails "ResultAgent registered and
  available for any crew".
- Hooks receive only `(crew_name, result)`; wiring `ExecutionMemory` in needs a
  closure/partial, and hook exceptions are swallowed (good for degradation, but
  no `infographic` field surfaced to the caller).

📊 **Effort:** Low

📦 **Libraries / Tools:** `InfographicToolkit`, `pydantic`.

🔗 **Existing Code to Reuse:**
- `parrot/bots/flows/crew/crew.py` — `on_complete` (L252), `_fire_hooks` (L282).
- `parrot/models/infographic_templates.py` — `TEMPLATE_MULTI_TAB`.

---

### Option D: Fully LLM-composed ResultAgent (agent authors every tab)

Same registration/flag as Option A, but the ResultAgent's LLM reads the whole
`ExecutionMemory` and composes **all** tabs (including per-agent tabs) itself.

✅ **Pros:**
- Maximum narrative flexibility; the agent can reshape/summarize each agent's
  output for presentation.

❌ **Cons:**
- Highest token cost and lowest determinism; per-agent tab fidelity depends on
  the LLM not dropping/garbling content.
- Harder to test (non-deterministic block output vs the `multi_tab` contract).
- Rejected by the Round-1 decision in favor of Hybrid.

📊 **Effort:** Medium

📦 **Libraries / Tools:** same as Option A.

🔗 **Existing Code to Reuse:** same as Option A.

---

## Recommendation

**Option A** is recommended. It is the only option that satisfies **all** the
decisions taken during discovery simultaneously:

- *Opt-in flag on `AgentCrew`* → `generate_infographic=True`.
- *Uniform internal post-run step* → one `_finalize_infographic()` call-site per
  `run_*()`, all converging on `ExecutionMemory`, avoiding Option B's dual code
  path and the graph-mutation fallout at `final_agents` (L699).
- *Hybrid render* → deterministic per-agent/final tabs (faithful, testable) +
  LLM-authored insights tab, rendered through the bound-relaxed `crew_report`
  template (derived from `multi_tab`, no 3–7 tab clamp).
- *Reuse `SynthesisMixin`* → Tab 1 is seeded by the crew's existing `summary`,
  no second synthesis pass.
- *Registry by configurable name* → `@register_agent("result-agent")`, resolved
  via `result_agent_name`, overridable per crew.
- *Excluded + new field* → ResultAgent is filtered out of tabs/synthesis and the
  artifact is exposed on a new `FlowResult.infographic` field.
- *Graceful degrade* → the finalize step is wrapped so failures log and leave
  `infographic=None`.

**What we trade off:** the ResultAgent won't show up as a node in `run_flow`
graph telemetry (Option B's only real advantage). That is acceptable — it is a
presentation finalizer, explicitly excluded from the research graph by design.
Option C's deterministic builder is not discarded — it becomes the reusable
helper that produces Option A's deterministic tabs.

---

## Feature Description

### User-Facing Behavior

A developer enables the feature with one flag:

```python
crew = AgentCrew(name="ResearchCrew", agents=[...], generate_infographic=True)
result = await crew.run_flow(prompt)
# New surface:
result.infographic.html_url     # persisted artifact URL (ArtifactStore)
result.infographic.html_inline  # inline HTML when < 50 KB
```

The produced HTML is a single self-contained multi-tab document whose tab count
is **dynamic** (minimum one, maximum = number of research agents plus the two
fixed tabs — no 3–7 enforcement):
- **Tab 1 — Executive Summary & Insights**: LLM-authored narrative seeded from
  the crew's synthesis.
- **Tab 2 — Final Result**: the crew's `FlowResult.output`.
- **Tabs 3…N — Per-Agent Results**: one tab per research agent (label = agent
  name), body = that agent's `NodeResult` (summarized, or linked out to a
  published `ArtifactStore` URL when the result is large/non-text).

When the flag is off (default), `run_*()` behaves exactly as today and
`result.infographic` is `None`.

### Internal Behavior

1. **Registration** — a new `ResultAgent(Agent)` under `parrot/bots/flows/`
   decorated `@register_agent("result-agent")`, whose `agent_tools()` returns an
   `InfographicToolkit`, defaulting to the **Gemini 3.5 Flash** (`google`) client
   when the crew has no `_llm`. Registered at import so any crew can resolve it.
2. **Trigger** — each `run_*()` calls `await self._finalize_infographic(result)`
   after synthesis, before `_fire_hooks`. Guarded by `self.generate_infographic`.
3. **Deterministic assembly** — a helper reads `self.execution_memory`
   (`get_snapshot()` / `get_results_by_agent()`), builds the `tab_view` block:
   Tab 2 from `result.output`, Tabs 3…N from each research agent's result,
   **excluding** the ResultAgent's own `node_id`.
4. **LLM insights** — the ResultAgent receives the crew `summary` + assembled
   tabs and authors the Tab-1 blocks, then calls
   `infographic_render(template_name="crew_report", …)` (the bound-relaxed
   variant — see Edge Cases).
5. **Surface** — the returned `InfographicRenderResult`/`InfographicResponse` is
   attached to `result.infographic`. `_fire_hooks` and `return` proceed as normal.

### Edge Cases & Error Handling

- **Dynamic tab count (NOT enforced)**: tabs scale with the run — **minimum one**
  (a single result with no per-agent breakdown), **maximum = number of research
  agents** (plus the fixed Executive-Summary and Final-Result tabs). The built-in
  `multi_tab` template hard-codes `min_items=3, max_items=7` on `tab_view`, so
  the feature registers a **bound-relaxed template variant `crew_report`**
  (same `tab_view` block, no min/max) via `infographic_registry.register(...)`.
  This is the mechanism that makes 1-tab and 10-tab reports both valid.
- **Large / non-text agent results** (DataFrame, dict, HTML): **summarize**, or
  **link out** when the content can be published to the `ArtifactStore` and
  yields a URL — never dump an unbounded payload into a tab. `NodeResult.to_text()`
  provides the base rendering for small text results.
- **Synthesis unavailable** (no `_llm` / synthesis returned `None`): Tab 1 falls
  back to a deterministic overview built from the per-agent list.
- **Render/validation/LLM failure**: caught in `_finalize_infographic`; logged;
  `result.infographic = None`; crew result otherwise intact (graceful degrade).
- **`result_agent_name` not found in registry**: log a warning, skip
  infographic generation (degrade), do not raise.
- **Memory reset ordering**: `run_sequential`/`run_flow` re-instantiate
  `execution_memory` (e.g. L1238) at the *start* of a run — the finalize step
  must read memory of the *current* run before any reset for a subsequent run.

---

## Capabilities

### New Capabilities
- `agentcrew-node-infographic`: opt-in end-of-flow ResultAgent that renders a
  multi-tab HTML infographic from an `AgentCrew` run's `ExecutionMemory`, with a
  dynamic (1..N) tab count.
- `result-agent`: a registry-discoverable `Agent` (under `parrot/bots/flows/`)
  bundling `InfographicToolkit`, defaulting to Gemini 3.5 Flash, resolvable by
  name and overridable per crew.
- `crew-report-template`: a bound-relaxed `crew_report` infographic template
  variant (no 3–7 tab clamp) registered on `infographic_registry`.

### Modified Capabilities
- `AgentCrew` execution (`crew.py`): new `generate_infographic` /
  `result_agent_name` params and `_finalize_infographic` step across all
  `run_*()` modes.
- `FlowResult` (`core/result.py`): new optional `infographic` field.

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `parrot/bots/flows/crew/crew.py` | modifies | New `__init__` params; `_finalize_infographic()`; call-site in each `run_*()` before `_fire_hooks`. |
| `parrot/bots/flows/core/result.py` | extends | Add optional `infographic` field to `FlowResult` (shared type — verify no positional-arg construction breaks). |
| `parrot/bots/flows/` (new file) | creates | `ResultAgent` + `@register_agent("result-agent")`, default LLM Gemini 3.5 Flash. |
| `parrot/tools/infographic_toolkit.py` | depends on | Reuse `render`; no changes expected. |
| `parrot/bots/flows/core/storage/memory.py` | depends on | Read via `get_snapshot()`/`get_results_by_agent()`; no changes. |
| `parrot/models/infographic_templates.py` | modifies | Register a **new bound-relaxed `crew_report` template variant** (like `multi_tab` but no `min_items=3/max_items=7` on `tab_view`) to allow 1..N dynamic tabs. |
| `parrot/registry/` | depends on | Resolve ResultAgent by name; no API change. |
| Tests | creates | Unit tests for deterministic assembly, **dynamic tab count (1 / N agents, no 3–7 clamp)**, large-result summarize/link-out, graceful degrade, and the opt-in default-off contract. |

---

## Code Context

### User-Provided Code

_None — the request was described in prose (see Problem Statement)._

### Verified Codebase References

> Package root: `packages/ai-parrot/src/parrot/` (import namespace `parrot`).

#### Classes & Signatures
```python
# From parrot/bots/flows/crew/crew.py
class AgentCrew(PersistenceMixin, SynthesisMixin):          # L93
    def __init__(self, name="AgentCrew", agents=None, ...,  # L134
                 persist_results: bool = True,              # L147
                 result_storage=None, **kwargs): ...
        self.execution_memory = ExecutionMemory(...)        # L194
        self.last_crew_result: Optional[FlowResult] = None  # L211
        self._on_complete_hooks: List[CrewHookCallback] = []# L226 (approx)
        self.final_agents: Set[str] = set()                 # L187
    def on_complete(self, callback: CrewHookCallback) -> None: ...  # L252
    async def _fire_hooks(self, result: Any) -> None: ...   # L282
    async def run_sequential(self, ...) -> FlowResult: ...  # L1172
    async def run_flow(self, ...) -> FlowResult: ...        # L2289
    # final_agents recomputed from workflow_graph successors # L699

# From parrot/bots/flows/core/storage/memory.py
class ExecutionMemory(VectorStoreMixin):                    # L19
    def add_result(self, result: NodeResult, vectorize=True) -> None: ...  # L55
    def get_results_by_agent(self, agent_id: str) -> Optional[NodeResult]: ...  # L79
    def get_snapshot(self) -> Dict[str, Any]: ...           # L134

# From parrot/bots/flows/core/result.py
class NodeResult:                                           # L39
    node_id: str; node_name: str; task: str; result: Any
    ai_message: Optional[Any]; metadata: Dict[str, Any]
    def to_text(self) -> str: ...                           # L88
    @property
    def agent_id(self) -> str: ...                          # L77 (alias of node_id)
class FlowResult:                                           # L273
    output: Any; responses: Dict[str, Any]; summary: str = ""
    nodes: List[NodeExecutionInfo]; status: FlowStatus
    # NOTE: no `infographic` field yet — this feature adds it.

# From parrot/tools/infographic_toolkit.py
class InfographicToolkit(AbstractToolkit):                  # L110
    return_direct: bool = True                              # L129
    def __init__(self, template_dirs=None, templates=None, ...): ...  # L134
    def get_tools(self, **kwargs): ...                      # L184
    async def render(self, template_name: str, ...): ...    # L240
class InfographicRenderResult(BaseModel):                  # L91
    template_name: str                                      # L100

# From parrot/models/infographic_templates.py
TEMPLATE_MULTI_TAB = InfographicTemplate(name="multi_tab",  # L453
    block_specs=[TITLE(required), TAB_VIEW(min_items=3, max_items=7)])
class InfographicTemplateRegistry:                          # L485
    def register(self, template) -> None; def get(self, name); def list_templates()

# From parrot/bots/agent.py
class BasicAgent(Chatbot, NotificationMixin):               # L29
    def agent_tools(self) -> List[AbstractTool]: ...        # L305 (override hook)
class Agent(BasicAgent):                                    # L1204
    def agent_tools(self) -> List[AbstractTool]: ...        # L1207
```

#### Verified Imports
```python
from parrot.registry import register_agent, agent_registry         # parrot/registry/__init__.py
from parrot.tools.infographic_toolkit import InfographicToolkit     # L110
from parrot.models.infographic_templates import (                   # multi_tab lives here
    infographic_registry, InfographicTemplate,
)
from parrot.bots.agent import Agent, BasicAgent                     # L29 / L1204
from parrot.bots.flows.crew.crew import AgentCrew                   # L93
from parrot.bots.flows.core.result import FlowResult, NodeResult    # L273 / L39
from parrot.bots.flows.core.storage.memory import ExecutionMemory   # L19
```

#### Key Attributes & Constants
- `AgentCrew.execution_memory` → `ExecutionMemory` (crew.py:194)
- `AgentCrew.final_agents` → `Set[str]` (crew.py:699)
- `AgentCrew.last_crew_result` → `Optional[FlowResult]` (crew.py:211)
- `AgentCrew._on_complete_hooks` (crew.py, FEAT-157) + `on_complete()` (L252)
- `InfographicToolkit.return_direct` → `True` (infographic_toolkit.py:129)
- `_INLINE_THRESHOLD` → `50_000` bytes, inline-HTML cutoff (infographic_toolkit.py)
- `TEMPLATE_MULTI_TAB` tab bounds → `min_items=3, max_items=7` **(the hard clamp this feature must relax via a `crew_report` variant)**
- `register_agent` → `agent_registry.register_bot_decorator` (registry/__init__.py)

### Does NOT Exist (Anti-Hallucination)
- ~~`FlowResult.infographic`~~ — does **not** exist yet; this feature adds it.
- ~~`AgentCrew.generate_infographic` / `AgentCrew.result_agent_name`~~ — new params, not present today.
- ~~`AgentCrew._finalize_infographic()`~~ — new method, does not exist.
- ~~`ResultAgent`~~ — no such class/registered agent named `"result-agent"` exists yet.
- ~~`crew_report` template~~ — does not exist yet; the built-in `multi_tab` clamps to 3–7 tabs, so this feature registers a bound-relaxed `crew_report` variant.
- ~~`InfographicNode` / a crew node subclass for infographics~~ — does not exist (only `CrewAgentNode` in crew/nodes.py).
- ~~`ExecutionMemory.get_all_results()`~~ — not a method; use `get_snapshot()` or iterate `results` / `get_results_by_agent()`.
- ~~`crew.render_infographic()`~~ — the post-run-method approach was rejected; no such method.

---

## Parallelism Assessment

- **Internal parallelism**: Moderate. Natural task seams: (1) the registered
  `ResultAgent` + `InfographicToolkit` wiring; (2) the deterministic
  memory→`tab_view` assembly helper (incl. tab-bounds/padding logic); (3) the
  `AgentCrew` flag + `_finalize_infographic` integration across `run_*()`; (4)
  the `FlowResult.infographic` field + consumer surface. Tasks 1–2 can proceed
  in parallel; task 3 depends on both; task 4 is small and pairs with 3.
- **Cross-feature independence**: `crew.py`, `core/result.py`, and
  `infographic_toolkit.py` are hot files (FEAT-143/147/157/163/197). Confirm no
  in-flight spec is concurrently editing `crew.py`'s `run_*()` signatures or
  `FlowResult`'s dataclass fields before starting.
- **Recommended isolation**: `per-spec` (all tasks sequential in one worktree).
- **Rationale**: The changes are tightly coupled around `crew.py` +
  `FlowResult`; parallel worktrees editing the same two shared files would
  conflict more than they'd save. Sequential tasks in one worktree keep the
  integration coherent.

---

## Open Questions

- [x] How is the ResultAgent attached to run "at end of flow"? — *Owner: Jesus*: Opt-in flag on `AgentCrew` → uniform internal post-run step in every `run_*()` (not a DAG node).
- [x] How is the infographic HTML produced? — *Owner: Jesus*: Hybrid — LLM authors Tab 1 (insights); Tab 2 + per-agent tabs built deterministically from `ExecutionMemory`, rendered via the bound-relaxed `crew_report` template.
- [x] Which execution modes must be supported? — *Owner: Jesus*: All four (flow, sequential, parallel, loop).
- [x] Where do the executive-summary insights come from? — *Owner: Jesus*: Reuse the crew's `SynthesisMixin` output (seed Tab 1); no second synthesis pass.
- [x] Should ResultAgent appear in `FlowResult.agents`/`execution_memory`, and where is the artifact exposed? — *Owner: Jesus*: Excluded from tabs/synthesis; artifact on a new `FlowResult.infographic` field.
- [x] How does the crew obtain the ResultAgent? — *Owner: Jesus*: Resolve from `AgentRegistry` by a configurable name (default `"result-agent"`).
- [x] Failure behavior? — *Owner: Jesus*: Graceful degrade — log, `infographic=None`, crew result intact.
- [x] Tab-count bounds? — *Owner: Jesus*: **No enforcement.** Tab count is dynamic — minimum one (single result, no per-agent breakdown), maximum = number of research agents (plus the two fixed tabs). Since the built-in `multi_tab` clamps to 3–7, register a bound-relaxed `crew_report` template variant.
- [x] Large / non-text per-agent results? — *Owner: Jesus*: **Summarize**, or **link out** when the content can be published to `ArtifactStore` and yields a URL — never dump an unbounded payload into a tab.
- [x] ResultAgent location & default LLM? — *Owner: Jesus*: Lives under `parrot/bots/flows/`; default LLM is **Gemini 3.5 Flash** (`google` client). *(Confirm the exact model id string at spec time.)*
