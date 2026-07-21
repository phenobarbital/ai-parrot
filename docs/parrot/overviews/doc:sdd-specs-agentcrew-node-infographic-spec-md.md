---
type: Wiki Overview
title: 'Feature Specification: AgentCrew ResultAgent — End-of-Flow Multi-Tab Infographic
  Node'
id: doc:sdd-specs-agentcrew-node-infographic-spec-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: When an `AgentCrew` finishes a multi-agent run, its output is a `FlowResult`
relates_to:
- concept: mod:parrot.bots.agent
  rel: mentions
- concept: mod:parrot.bots.flows.core.result
  rel: mentions
- concept: mod:parrot.bots.flows.core.storage.memory
  rel: mentions
- concept: mod:parrot.bots.flows.crew.crew
  rel: mentions
- concept: mod:parrot.models.infographic
  rel: mentions
- concept: mod:parrot.models.infographic_templates
  rel: mentions
- concept: mod:parrot.registry
  rel: mentions
- concept: mod:parrot.tools.infographic_toolkit
  rel: mentions
---

---
type: feature
base_branch: dev
---

# Feature Specification: AgentCrew ResultAgent — End-of-Flow Multi-Tab Infographic Node

**Feature ID**: FEAT-308
**Date**: 2026-07-14
**Author**: Jesus Lara
**Status**: approved
**Target version**: (next minor)

> Source brainstorm: `sdd/proposals/agentcrew-node-infographic.brainstorm.md`
> (Recommended Option A). All 10 brainstorm open questions were resolved before
> this spec; see §8 for the audit trail.

---

## 1. Motivation & Business Requirements

### Problem Statement

When an `AgentCrew` finishes a multi-agent run, its output is a `FlowResult`
containing the final `output`, an optional LLM `summary`, and per-node execution
records — but there is **no presentation-ready artifact** that lets a human
consume the run as a whole. To understand "what did the crew actually do", a
user today must read the raw `summary`, then dig into `execution_memory` node by
node.

We want a reusable, opt-in capability that, **at the end of any crew run**,
produces a single self-contained **multi-tab HTML infographic**:

- **Tab 1** — Executive Summary & Insights (cross-cutting synthesis).
- **Tab 2** — Final Result of the AgentCrew execution.
- **Tabs 3…N** — One tab per research agent, showing that agent's result.

The generator is a proper internal **`ResultAgent`** (an `Agent` carrying an
`InfographicToolkit`) registered in the `AgentRegistry` so it is discoverable and
overridable by any crew, reading per-agent results from the crew's Execution
Result memory (`ExecutionMemory`).

### Goals

- **G1** — Add an opt-in `generate_infographic` flag to `AgentCrew` that, when
  `True`, produces the multi-tab infographic at the end of **every** execution
  mode (`run_flow`, `run_sequential`, `run_parallel`, `run_loop`).
- **G2** — Default behaviour is unchanged and non-breaking when the flag is off.
- **G3** — Register a `ResultAgent` under `@register_agent("result-agent")`,
  resolvable from `AgentRegistry` by a configurable name (default
  `"result-agent"`) and overridable per crew.
- **G4** — Hybrid rendering: LLM-authored Executive-Summary/Insights tab
  (seeded by the crew's existing `SynthesisMixin` output); Final-Result and
  per-agent tabs built **deterministically** from `ExecutionMemory`.
- **G5** — Dynamic tab count (minimum 1, maximum = number of research agents +
  the two fixed tabs), via a bound-relaxed `crew_report` template variant.
- **G6** — Expose the artifact on a new optional `FlowResult.infographic` field;
  the ResultAgent is excluded from the per-agent tabs and from
  synthesis/`execution_memory` accounting.
- **G7** — Graceful degradation: any synthesis/render/validation failure logs
  and leaves `infographic=None`; the crew's real work is never lost.
- **G8** — Large / non-text per-agent results are summarized or linked out to a
  published `ArtifactStore` URL — never dumped raw into a tab.

### Non-Goals (explicitly out of scope)

- Representing the ResultAgent as a first-class node inside `run_flow`'s
  `workflow_graph` / graph telemetry. *(Brainstorm Option B — real DAG terminal
  node — was rejected; see `sdd/proposals/agentcrew-node-infographic.brainstorm.md`.)*
- Fully LLM-composed per-agent tabs. *(Brainstorm Option D rejected — per-agent
  tabs are deterministic.)*
- A second synthesis pass — Tab 1 reuses the crew's existing synthesis output.
- A `crew.render_infographic()` post-run method (the post-run-method trigger was
  rejected in favour of an internal finalize step).
- Changing the `InfographicToolkit.render` API or the built-in `multi_tab`
  template.

---

## 2. Architectural Design

### Overview

`AgentCrew.__init__` gains `generate_infographic: bool = False`,
`result_agent_name: str = "result-agent"`, and optional render configuration.
Each `run_*()` method, after it builds its `FlowResult` and runs synthesis but
**before** `_fire_hooks()`/`return`, calls a new coroutine
`await self._finalize_infographic(result)`. That step:

1. Resolves the ResultAgent from `AgentRegistry` by `result_agent_name`,
   instantiating it with the crew's `_llm` (falling back to Gemini 3.5 Flash via
   the `google` client when the crew has no `_llm`).
2. Builds a **deterministic** `tab_view` block structure from
   `self.execution_memory` (Tab 2 = final result from `result.output`, Tabs 3…N =
   per-agent results), **excluding** the ResultAgent's own `node_id`. Large /
   non-text results are summarized or linked out to an `ArtifactStore` URL.
3. Passes the crew's `summary` (SynthesisMixin output) + the deterministic tabs
   to the ResultAgent, which LLM-authors the Tab-1 blocks (Executive Summary &
   Insights).
4. Renders the merged block list through the bound-relaxed `crew_report`
   template (derived from `multi_tab`, no 3–7 clamp) and attaches the
   `InfographicRenderResult` to the new `FlowResult.infographic` field.
5. On **any** exception: logs and leaves `infographic=None`; the crew result is
   returned intact.

Because the finalize step hangs off `run_*()` uniformly, it is mode-agnostic —
`run_flow`'s DAG, `run_parallel`'s gather, `run_sequential`'s pipeline, and
`run_loop`'s iterations all converge on the same `ExecutionMemory`.

**Render path note.** `InfographicToolkit._resolve_blocks` accepts an inline
`blocks` list (no pandas REPL required — infographic_toolkit.py:~280) and
`data_variables=[]` is valid when no block references a DataFrame. The finalize
step therefore assembles the full `[title, tab_view]` block list in Python and
renders it directly, using the LLM only to author the Tab-1 blocks. This keeps
per-agent/final tabs deterministic while still getting LLM-quality insights.

### Component Diagram

```
AgentCrew.run_flow / run_sequential / run_parallel / run_loop
        │ (builds FlowResult + synthesis)
        ▼
AgentCrew._finalize_infographic(result)         [gated by generate_infographic]
        │
        ├─→ AgentRegistry.resolve("result-agent") ──→ ResultAgent(InfographicToolkit)
        │                                                     │
        ├─→ ExecutionMemory.get_snapshot() ──→ deterministic tab_view blocks
        │        (exclude ResultAgent; summarize / link-out large results)
        │                                                     │
        ├─→ crew.summary (SynthesisMixin) ──→ ResultAgent LLM authors Tab 1 blocks
        │                                                     ▼
        └─→ InfographicToolkit.render(template_name="crew_report", blocks=[...])
                     │
                     ▼
             FlowResult.infographic = InfographicRenderResult   (or None on failure)
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `AgentCrew` (`parrot/bots/flows/crew/crew.py`) | modifies | New `__init__` params; `_finalize_infographic()`; one call-site in each `run_*()` before `_fire_hooks`. |
| `FlowResult` (`parrot/bots/flows/core/result.py`) | extends | New optional `infographic` field (default `None`). |
| `ExecutionMemory` (`.../core/storage/memory.py`) | uses | Read via `get_snapshot()` / `get_results_by_agent()`; no changes. |
| `InfographicToolkit` (`parrot/tools/infographic_toolkit.py`) | uses | `render(template_name="crew_report", blocks=[...], data_variables=[])`; no changes. |
| `infographic_registry` (`parrot/models/infographic_templates.py`) | modifies | Register a new `crew_report` template (bound-relaxed `multi_tab`). |
| `AgentRegistry` / `register_agent` (`parrot/registry/`) | uses | Resolve ResultAgent by name; no API change. |
| `Agent` / `BasicAgent` (`parrot/bots/agent.py`) | extends | `ResultAgent(Agent)` overrides `agent_tools()` to return `InfographicToolkit`. |
| `SynthesisMixin` (`.../core/storage/synthesis.py`) | uses | Reuse the already-computed `result.summary` as the Tab-1 seed. |
| `ArtifactStore` (`parrot/storage/`) | uses | Publish large/non-text per-agent results and link out to their URL. |

### Data Models

```python
# parrot/bots/flows/core/result.py — new optional field on FlowResult
@dataclass
class FlowResult:
    output: Any
    ...
    # NEW — populated by AgentCrew._finalize_infographic when generate_infographic=True
    infographic: Optional["InfographicRenderResult"] = None
    # NOTE: keep as the LAST field to preserve existing positional/keyword construction.
```

```python
# parrot/models/infographic_templates.py — new bound-relaxed template variant
TEMPLATE_CREW_REPORT = InfographicTemplate(
    name="crew_report",
    description="Crew execution report: exec summary + final result + per-agent tabs.",
    default_theme="light",
    block_specs=[
        BlockSpec(block_type=BlockType.TITLE, description="Report title", required=True),
        BlockSpec(
            block_type=BlockType.TAB_VIEW,
            description="1..N tabs: Exec Summary, Final Result, then one per research agent.",
            required=True,
            # NO min_items / max_items — dynamic count (min 1, max = #agents + 2)
        ),
    ],
)
# Registered at import: infographic_registry.register(TEMPLATE_CREW_REPORT)
```

### New Public Interfaces

```python
# parrot/bots/flows/crew/crew.py
class AgentCrew(PersistenceMixin, SynthesisMixin):
    def __init__(
        self,
        ...,
        generate_infographic: bool = False,        # NEW — opt-in
        result_agent_name: str = "result-agent",   # NEW — registry resolution key
        **kwargs,
    ): ...

    async def _finalize_infographic(self, result: "FlowResult") -> None:
        """Populate result.infographic; swallow+log on failure (result.infographic=None)."""

# parrot/bots/flows/result_agent.py
@register_agent("result-agent")
class ResultAgent(Agent):
    """Internal agent that renders a crew's ExecutionMemory into a crew_report infographic."""
    def agent_tools(self) -> List[AbstractTool]: ...  # returns [InfographicToolkit(...)]
```

---

## 3. Module Breakdown

### Module 1: `crew_report` Infographic Template Variant
- **Path**: `parrot/models/infographic_templates.py` (extend)
- **Responsibility**: Define `TEMPLATE_CREW_REPORT` (same blocks as `multi_tab`
  but **no** `min_items`/`max_items` on `TAB_VIEW`) and register it on
  `infographic_registry` at import so `render(template_name="crew_report")`
  resolves.
- **Depends on**: existing `InfographicTemplate`, `BlockSpec`, `BlockType`,
  `infographic_registry`.

### Module 2: Deterministic Tab-Assembly Helper
- **Path**: `parrot/bots/flows/crew/result_infographic.py` (new)
- **Responsibility**: Pure(ish) helper that reads `ExecutionMemory` and builds
  the deterministic block list — Title + `tab_view` with the Final-Result tab
  (Tab 2) and one tab per research agent (Tabs 3…N), **excluding** the
  ResultAgent's own `node_id`. Summarize or link-out large/non-text results via
  `ArtifactStore`. Merges LLM-authored Tab-1 blocks in front.
- **Depends on**: Module 1; `ExecutionMemory`, `NodeResult.to_text()`,
  `ArtifactStore`.

### Module 3: `ResultAgent`
- **Path**: `parrot/bots/flows/result_agent.py` (new)
- **Responsibility**: `@register_agent("result-agent")` subclass of `Agent`
  whose `agent_tools()` returns an `InfographicToolkit`; default LLM Gemini 3.5
  Flash (`google` client) when none supplied. Authors the Tab-1 (Executive
  Summary & Insights) blocks from the crew `summary`, then renders the merged
  block list through `crew_report`.
- **Depends on**: Module 1, Module 2; `Agent`/`BasicAgent`, `InfographicToolkit`,
  `register_agent`.

### Module 4: `AgentCrew` Integration
- **Path**: `parrot/bots/flows/crew/crew.py` (extend)
- **Responsibility**: Add `generate_infographic` / `result_agent_name`
  `__init__` params; implement `_finalize_infographic(result)`; call it in each
  of `run_flow`, `run_sequential`, `run_parallel`, `run_loop` after synthesis and
  before `_fire_hooks()`. Resolve the ResultAgent from `AgentRegistry` by name
  (log-and-skip if not found). Exclude the ResultAgent from tabs / memory
  accounting.
- **Depends on**: Modules 2 & 3; existing `execution_memory`, `_fire_hooks`,
  `SynthesisMixin`.

### Module 5: `FlowResult.infographic` Field
- **Path**: `parrot/bots/flows/core/result.py` (extend)
- **Responsibility**: Add the optional `infographic` field (default `None`) as
  the **last** dataclass field; expose it in `to_dict()` if present.
- **Depends on**: `InfographicRenderResult` type (import-safe / forward ref).

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_crew_report_template_registered` | M1 | `infographic_registry.get("crew_report")` returns a template with a `TAB_VIEW` block and **no** min/max. |
| `test_assemble_single_result_one_tab` | M2 | 0 research agents → dynamic tab count works (min 1); no 3-tab padding, no clamp error. |
| `test_assemble_many_agents_no_clamp` | M2 | 8 research agents → 10 tabs assembled without hitting the old 7-tab cap. |
| `test_assemble_excludes_result_agent` | M2 | The ResultAgent's own `node_id` is absent from the per-agent tabs. |
| `test_assemble_large_result_linked_out` | M2 | Oversized / non-text result is summarized or replaced by an `ArtifactStore` URL, not dumped raw. |
| `test_result_agent_registered` | M3 | `agent_registry` resolves `"result-agent"`; `agent_tools()` yields an `InfographicToolkit`. |
| `test_result_agent_default_llm` | M3 | With no crew `_llm`, ResultAgent defaults to the Gemini Flash (`google`) client. |
| `test_flag_off_is_noop` | M4 | `generate_infographic=False` (default) → `result.infographic is None`, no ResultAgent resolved. |
| `test_finalize_graceful_degrade` | M4 | Render/LLM raises → logged, `result.infographic is None`, crew result status unchanged. |
| `test_unknown_result_agent_name_skips` | M4 | `result_agent_name` not in registry → warn + skip, no raise. |
| `test_flowresult_infographic_field` | M5 | `FlowResult(...)` default `infographic is None`; positional construction unaffected. |

### Integration Tests
| Test | Description |
|---|---|
| `test_run_flow_generates_infographic` | 3-agent DAG with `generate_infographic=True` → `result.infographic.html_url` set; tab_view has Exec Summary + Final Result + 3 agent tabs. |
| `test_all_modes_generate_infographic` | Parametrized over `run_sequential`/`run_parallel`/`run_loop` → each yields a populated `result.infographic`. |
| `test_insights_tab_uses_synthesis` | Tab 1 content is seeded from the crew's `summary` (SynthesisMixin), not a second synthesis pass. |

### Test Data / Fixtures
```python
@pytest.fixture
def crew_with_infographic():
    # Two stub agents returning short text; crew(generate_infographic=True, llm=<fake>)
    ...

@pytest.fixture
def fake_llm():
    # Deterministic AbstractClient stub whose .ask() returns canned Tab-1 blocks
    ...
```

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] **[G1/G2]** `AgentCrew(generate_infographic=False)` (the default) leaves
  every `run_*()` behaviour byte-for-byte unchanged and `result.infographic is None`.
- [ ] **[G1]** `generate_infographic=True` produces a populated
  `result.infographic` in **all four** modes (flow, sequential, parallel, loop).
- [ ] **[G3]** `ResultAgent` is registered as `"result-agent"` and resolved via
  `result_agent_name` (overridable); an unknown name logs a warning and skips.
- [ ] **[G4]** Tab 1 is LLM-authored from the crew's existing `summary`; Tabs 2…N
  are deterministic (no second synthesis pass).
- [ ] **[G5]** Tab count is dynamic (1 tab minimum; N-agent runs render N+2 tabs)
  with **no** 3–7 clamp — served by the registered `crew_report` template.
- [ ] **[G6]** The ResultAgent does not appear in the per-agent tabs; the
  artifact is exposed on `FlowResult.infographic`.
- [ ] **[G7]** Any synthesis/render/validation failure logs and yields
  `infographic=None` without changing `result.status` or losing crew output.
- [ ] **[G8]** Large / non-text per-agent results are summarized or linked to an
  `ArtifactStore` URL, never dumped raw into a tab.
- [ ] All unit tests pass (`pytest tests/ -k infographic -v`).
- [ ] All integration tests pass.
- [ ] No breaking changes to `FlowResult` construction or the `InfographicToolkit`
  / `multi_tab` public API.
- [ ] Documentation updated (AgentCrew infographic usage note).

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor.** Verified against
> `packages/ai-parrot/src/parrot/` on 2026-07-14 (import namespace `parrot`).

### Verified Imports
```python
from parrot.registry import register_agent, agent_registry            # registry/__init__.py
from parrot.bots.agent import Agent, BasicAgent                        # agent.py:1204 / :29
from parrot.tools.infographic_toolkit import (                         # infographic_toolkit.py
    InfographicToolkit,                                                # :110
    InfographicRenderResult,                                           # :91
)
from parrot.models.infographic_templates import (                      # infographic_templates.py:33-36
    InfographicTemplate, BlockSpec, infographic_registry,              # :47 / :21 / :559
)
from parrot.models.infographic import InfographicResponse             # used by render()
from parrot.bots.flows.crew.crew import AgentCrew                      # crew.py:93
from parrot.bots.flows.core.result import FlowResult, NodeResult       # result.py:273 / :39
from parrot.bots.flows.core.storage.memory import ExecutionMemory      # memory.py:19
```

### Existing Class Signatures
```python
# parrot/bots/flows/crew/crew.py
class AgentCrew(PersistenceMixin, SynthesisMixin):                     # L93
    def __init__(self, name="AgentCrew", agents=None, ...,
                 llm=None, persist_results=True, result_storage=None, **kwargs): ...  # L134
    #   self.final_agents: Set[str] = set()                             # L187
    #   self.execution_memory = ExecutionMemory(...)                    # L194 (re-inited per run: L1238/1577/2013/2358)
    #   self.last_crew_result: Optional[FlowResult] = None              # L211
    def on_complete(self, callback) -> None: ...                        # L252
    async def _fire_hooks(self, result: Any) -> None: ...               # L282  (finalize BEFORE this)
    async def run_sequential(self, ...) -> FlowResult: ...              # L1172
    async def run_loop(self, ...) -> FlowResult: ...                    # L1500
    async def run_parallel(self, ...) -> FlowResult: ...               # L1966
    async def run_flow(self, ...) -> FlowResult: ...                    # L2289
    #   final_agents recomputed from workflow_graph successors          # L699

# parrot/bots/flows/core/result.py
@dataclass
class FlowResult:                                                       # L273
    output: Any                                                         # L288 (no default — keep new field LAST)
    responses: Dict[str, Any] = field(default_factory=dict)            # L291
    summary: str = ""                                                   # L294
    nodes: List[NodeExecutionInfo] = field(default_factory=list)       # L297
    status: FlowStatus = FlowStatus.COMPLETED                          # L306
    metadata: Dict[str, Any] = field(default_factory=dict)             # L312
    # (no `infographic` field today — this feature adds it)

class NodeResult:                                                       # L39
    node_id: str; node_name: str; task: str; result: Any
    def to_text(self) -> str: ...                                       # L88
    @property
    def agent_id(self) -> str: ...                                      # L77 (alias of node_id)

# parrot/bots/flows/core/storage/memory.py
class ExecutionMemory(VectorStoreMixin):                               # L19
    self.results: dict                                                  # L45
    def add_result(self, result: NodeResult, vectorize=True) -> None: ...  # L55
    def get_results_by_agent(self, agent_id: str) -> Optional[NodeResult]: ...  # L79
    def get_snapshot(self) -> Dict[str, Any]: ...                      # L134

# parrot/tools/infographic_toolkit.py
_INLINE_THRESHOLD: int = 50_000                                        # L49
class InfographicRenderResult(BaseModel):                              # L91
    html_inline: Optional[str] = None                                  # L99 (None when html >= 50 KB)
class InfographicToolkit(AbstractToolkit):                             # L110
    return_direct: bool = True                                         # L129
    def __init__(self, template_dirs=None, templates=None, ...): ...   # L134
    def get_tools(self, **kwargs): ...                                 # L184
    async def render(self, template_name: str, theme, mode,           # L240
                     data_variables: List[str], blocks=None,
                     blocks_variable=None, enhance_brief=None) -> InfographicRenderResult: ...
    def _validate_template(self, name) -> InfographicTemplate:        # L947 → infographic_registry.get(name) (L950)
    def _resolve_blocks(self, blocks, blocks_variable): ...            # accepts inline `blocks` list (no REPL needed)

# parrot/models/infographic_templates.py
TEMPLATE_MULTI_TAB = InfographicTemplate(name="multi_tab", ...         # L452-453
    block_specs=[TITLE(required), TAB_VIEW(required, min_items=3, max_items=7)])  # L476-477 ← clamp to relax
class InfographicTemplateRegistry:                                     # L485
    def register(self, template) -> None: ...                          # L509
    def get(self, name) -> InfographicTemplate: ...                    # L517 (raises KeyError → TEMPLATE_UNKNOWN)
    def list_templates(self) -> List[str]: ...                         # L538
infographic_registry = InfographicTemplateRegistry()                  # L559 (module singleton)

# parrot/bots/agent.py
class BasicAgent(Chatbot, NotificationMixin):                         # L29
    def __init__(self, ..., tools=None, use_tools=True, use_llm=..., **kwargs): ...  # L62
    def agent_tools(self) -> List[AbstractTool]: ...                   # L305 (override hook)
class Agent(BasicAgent):                                              # L1204
    def agent_tools(self) -> List[AbstractTool]: ...                   # L1207

# parrot/registry/__init__.py
register_agent = agent_registry.register_bot_decorator                # decorator factory
```

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `AgentCrew._finalize_infographic` | `AgentRegistry` | resolve `result_agent_name` | `registry/__init__.py` (`agent_registry`) |
| `AgentCrew._finalize_infographic` | `self.execution_memory` | `get_snapshot()` / `get_results_by_agent()` | `memory.py:134` / `:79` |
| Tab-assembly helper | `NodeResult.to_text()` | text rendering of small results | `result.py:88` |
| `ResultAgent` | `InfographicToolkit.render` | `render(template_name="crew_report", blocks=[...], data_variables=[])` | `infographic_toolkit.py:240` |
| `crew_report` template | `infographic_registry` | `register(TEMPLATE_CREW_REPORT)` → resolved by `_validate_template` | `infographic_templates.py:509` / `:950` |
| `_finalize_infographic` call-site | `run_*()` | invoked after synthesis, before `_fire_hooks()` | `crew.py:282` |
| `FlowResult.infographic` | `InfographicRenderResult` | new dataclass field | `result.py:273` / `infographic_toolkit.py:91` |

### Does NOT Exist (Anti-Hallucination)
- ~~`FlowResult.infographic`~~ — does **not** exist yet; this feature adds it (result.py:273 has no such field).
- ~~`AgentCrew.generate_infographic` / `AgentCrew.result_agent_name`~~ — new `__init__` params, absent today.
- ~~`AgentCrew._finalize_infographic()`~~ — new method, does not exist.
- ~~`ResultAgent` / registered agent `"result-agent"`~~ — does not exist yet.
- ~~`crew_report` template~~ — not registered; only `multi_tab` (clamped 3–7) exists. This feature registers the bound-relaxed variant.

…(truncated)…
