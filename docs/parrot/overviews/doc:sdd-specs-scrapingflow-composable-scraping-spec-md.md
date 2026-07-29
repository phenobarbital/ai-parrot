---
type: Wiki Overview
title: 'Feature Specification: ScrapingFlow — Composable Long-Horizon Scraping'
id: doc:sdd-specs-scrapingflow-composable-scraping-spec-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'The `WebScrapingToolkit` resolves a single unit of work: a `ScrapingPlan`
  (JSON declarative)'
relates_to:
- concept: mod:parrot_tools.scraping
  rel: mentions
- concept: mod:parrot_tools.scraping.advanced_actions
  rel: mentions
- concept: mod:parrot_tools.scraping.base_registry
  rel: mentions
- concept: mod:parrot_tools.scraping.executor
  rel: mentions
- concept: mod:parrot_tools.scraping.models
  rel: mentions
- concept: mod:parrot_tools.scraping.plan
  rel: mentions
- concept: mod:parrot_tools.scraping.toolkit_models
  rel: mentions
---

---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Feature Specification: ScrapingFlow — Composable Long-Horizon Scraping

**Feature ID**: FEAT-222
**Date**: 2026-06-04
**Author**: Jesus Lara
**Status**: approved
**Target version**: next
**Proposal**: `sdd/proposals/scrapingflow-composable-scraping.proposal.md`
**Research audit**: `sdd/state/FEAT-222/`

---

## 1. Motivation & Business Requirements

### Problem Statement

The `WebScrapingToolkit` resolves a single unit of work: a `ScrapingPlan` (JSON declarative)
executed on one page and cached by URL in the `PlanRegistry`. This covers repeatable
structured extraction, but three needs remain unmet:

1. **Parameterized reuse.** A plan is bound to a concrete URL via its `fingerprint`. "Same
   flow, different arguments" (dates, origin/destination, search filters) requires
   regenerating or duplicating plans. No template concept exists.
2. **Long-horizon composition.** Tasks like login → listing → detail-per-item → checkout
   cannot be modeled as a sequence of plans passing data between stages. `CrawlEngine`
   covers "follow homogeneous links" but not a heterogeneous DAG of distinct stages.
3. **Multi-window session operation.** No explicit session/`BrowserContext` model exists for
   sharing authentication state across stages — which is what distinguishes an authenticated
   long-horizon flow from N independent scrapes.

Additionally, a fourth gap was discovered during research:

4. **Advanced action support in the modern toolkit.** Loop and Conditional actions are fully
   implemented only in the legacy `WebScrapingTool` (tool.py). The modern `WebScrapingToolkit`
   delegates to `execute_plan_steps`, which **stubs these actions** with a warning and returns
   `True`. This means plans containing Loop/Conditional steps silently produce incomplete
   results when executed through the modern toolkit path.

### Goals

- G1: Parameterized plan templates with typed parameters and `bind()` producing concrete `ScrapingPlan`s.
- G2: DAG-based flow composition with data-dependency wiring between stages and session affinity.
- G3: In-engine flow execution with BrowserContext lifecycle management, fan-out, and per-node checkpoints.
- G4: Extract Loop/Conditional dispatch from the legacy tool into a shared module, fixing the existing gap in `WebScrapingToolkit` and enabling FlowExecutor support.
- G5: Resumability — failure at stage N does not force restart from stage 0.

### Non-Goals (explicitly out of scope)

- Playwright code generation / portable script export — deferred to future spec.
- MCP server exposure of the flow DSL — deferred to future spec.
- Code-as-action (Webwright-style) agent loop — rejected in brainstorm Option B.
- Fan-out concurrency on a shared authenticated session — known deferred debt (safe in sequential mode).
- Modification of `ScrapingPlan` as a value object — parametrization is built ABOVE it.

---

## 2. Architectural Design

### Overview

Three layered capabilities built on the existing scraping engine, plus an extraction of
advanced action dispatch from the legacy tool:

```
Layer 0 (extraction):  advanced_actions module
                       ├── exec_loop, exec_conditional, substitute_template_vars
                       └── consumed by: executor.py, tool.py, FlowExecutor

Layer 1 (models):      TemplatePlan + ParamSpec     ScrapingFlow + FlowNode
                       │                            │
                       │  bind(**params)             │  topological sort
                       ▼                            ▼
                       ScrapingPlan (existing)       execution order

Layer 2 (execution):   FlowExecutor
                       ├── SessionManager (BrowserContext lifecycle)
                       ├── PageDriver (AbstractDriver adapter per Page)
                       ├── execute_plan_steps (per-node, existing)
                       └── Checkpoint persistence (per-node FlowResult)
```

**TemplatePlan** is a Pydantic model with `ParamSpec` typed parameters. `bind(**kwargs)`
validates parameters, renders `{{param}}` placeholders in `url_template`, `objective_template`,
and `steps_template`, and produces a concrete `ScrapingPlan`. The fingerprint of the
produced plan incorporates `template_name + param_hash` to avoid collisions.

**Placeholder convention**: TemplatePlan uses **double braces** `{{param}}` — distinct from
Loop's single-brace `{index}` convention (confirmed by research: tool.py:3271 uses regex
`r'\{([^}]*(?:i|index|iteration)[^}]*)\}'`). Double braces avoid collision with CSS selectors,
JSON syntax, and Loop variables. Rendering uses `re.sub(r'\{\{(\w+)\}\}', ...)` — not
`str.format()` — to prevent KeyError on unrelated braces.

**ScrapingFlow** is a DAG of `FlowNode`s where edges are data dependencies (`inputs:
{param: "node_id.field"}`). Each node also declares a `session` label for BrowserContext
affinity. Data-flow and session are orthogonal axes: a node can consume data from a
different session without sharing cookies.

**FlowExecutor** computes topological order from the `inputs` graph, creates/caches
BrowserContexts via `SessionManager`, wraps each Page in a `PageDriver` adapter,
and executes each node through `execute_plan_steps`. Per-node results are persisted
as checkpoints for resumability.

**advanced_actions** extracts `_exec_loop`, `_exec_conditional`, and
`_substitute_template_vars` from the legacy `WebScrapingTool` into standalone async
functions. These accept `AbstractDriver` + a `dispatch_step_fn` callback for recursive
step execution. The executor's `_dispatch_step` calls them instead of stubbing, fixing
the gap in `WebScrapingToolkit`. The legacy tool delegates to them, eliminating duplication.

### Component Diagram

```
                        ┌─────────────────┐
                        │  TemplatePlan    │
                        │  + ParamSpec     │
                        │  bind() ─────────┼──→ ScrapingPlan (existing, unmodified)
                        └─────────────────┘

┌─────────────────┐     ┌──────────────────────────────────────────┐
│  ScrapingFlow    │     │              FlowExecutor                │
│  + FlowNode[]   │────→│  topo_sort() → for node in order:        │
│  (DAG model)    │     │    resolve inputs from prior results     │
└─────────────────┘     │    bind template → ScrapingPlan          │
                        │    SessionManager.new_page(session)      │
                        │    PageDriver(page)                      │
                        │    execute_plan_steps(driver, plan)      │
                        │    checkpoint result                     │
                        │    SessionManager.close_if_last(session) │
                        └──────────────┬───────────────────────────┘
                                       │
                        ┌──────────────▼───────────────────────────┐
                        │          SessionManager                   │
                        │  Browser ──→ BrowserContext per session   │
                        │  lazy open, deterministic close by last-use│
                        └──────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│                    advanced_actions module                        │
│  exec_loop(driver, action, dispatch_step_fn)                     │
│  exec_conditional(driver, action, dispatch_step_fn)              │
│  substitute_template_vars(value, index, ...)                     │
│                                                                  │
│  Called by: executor._dispatch_step, FlowExecutor, tool.py       │
└─────────────────────────────────────────────────────────────────┘
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `execute_plan_steps` (executor.py:41) | depends on | FlowExecutor invokes per-node; no signature changes |
| `ScrapingPlan` (plan.py:59) | depends on | Output of `TemplatePlan.bind()`; unmodified |
| `_compute_fingerprint` (plan.py:31) | reuses | Called with `template_name + param_hash` for templates |
| `BasePlanRegistry[T]` (base_registry.py) | extends | Optional TemplatePlanRegistry follows ExtractionPlanRegistry pattern |
| `ACTION_MAP` (models.py:726) | depends on | Unchanged; advanced_actions reads Loop/Conditional from it |
| `ScrapingResult` (models.py:834) | depends on | Per-node output from execute_plan_steps |
| `AbstractDriver` (drivers/abstract.py:11) | implements | PageDriver implements all 19 abstract methods |
| `PlaywrightDriver` (drivers/playwright_driver.py) | bypasses | FlowExecutor works at Browser level, not through PlaywrightDriver |
| `DriverConfig` (toolkit_models.py:15) | depends on | FlowExecutor accepts for browser configuration |
| `WebScrapingTool._exec_loop` (tool.py:2582) | refactors | Extracted to advanced_actions; legacy tool becomes thin wrapper |
| `WebScrapingTool._exec_conditional` (tool.py:2456) | refactors | Extracted to advanced_actions; legacy tool becomes thin wrapper |
| `WebScrapingTool._substitute_template_vars` (tool.py:3271) | refactors | Extracted to advanced_actions |
| `executor._dispatch_step` (executor.py:280) | modifies | Stub replaced with calls to advanced_actions |
| `__init__.py` (scraping/) | extends | New public exports added |

### Data Models

```python
from pydantic import BaseModel, Field, computed_field, model_validator
from typing import Any, Dict, List, Literal, Optional
from datetime import datetime, timezone


class ParamSpec(BaseModel):
    """Typed parameter definition for TemplatePlan."""
    name: str
    type: Literal["string", "int", "date", "enum", "url"] = "string"
    required: bool = True
    default: Optional[Any] = None
    choices: Optional[List[Any]] = None
    description: str = ""


class TemplatePlan(BaseModel):
    """Parameterized plan template that produces ScrapingPlans via bind()."""
    name: str
    objective_template: str
    url_template: str
    params: List[ParamSpec]
    steps_template: List[Dict[str, Any]]
    selectors: Optional[List[Dict[str, Any]]] = None
    tags: List[str] = Field(default_factory=list)
    browser_config: Optional[Dict[str, Any]] = None
    version: str = "1.0"
    source: str = "llm"
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def bind(self, **kwargs) -> "ScrapingPlan":
        """Validate kwargs against ParamSpec, render {{param}} placeholders,
        return a concrete ScrapingPlan with fingerprint = hash(name + sorted(params))."""
        ...

    @computed_field
    @property
    def fingerprint(self) -> str:
        """Template-level fingerprint derived from name (not URL)."""
        ...


class FlowNode(BaseModel):
    """A single stage in a ScrapingFlow DAG."""
    id: str
    plan_ref: str                                   # template name or plan fingerprint
    inputs: Dict[str, str] = Field(default_factory=dict)  # param <- "node_id.field"
    session: str = "default"                        # same session = same BrowserContext
    on_error: Literal["abort", "skip", "retry"] = "abort"
    max_retries: int = Field(default=3, ge=1)       # used only when on_error="retry"


class ScrapingFlow(BaseModel):
    """DAG of FlowNodes with data-dependency edges and session affinity."""
    name: str
    description: str = ""
    nodes: List[FlowNode]
    global_params: Dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_dag(self) -> "ScrapingFlow":
        """Validate: no dangling refs, no cycles, all input sources exist."""
        ...


class FlowResult(BaseModel):
    """Aggregated result of a ScrapingFlow execution."""
    flow_name: str
    node_results: Dict[str, Any] = Field(default_factory=dict)  # node_id -> ScrapingResult
    success: bool = True
    error_message: Optional[str] = None
    elapsed_seconds: float = 0.0
    nodes_completed: int = 0
    nodes_total: int = 0
    checkpoint_path: Optional[str] = None
    resumed_from: Optional[str] = None
```

### New Public Interfaces

```python
# --- advanced_actions.py ---

async def exec_loop(
    driver: AbstractDriver,
    loop_action: Loop,
    dispatch_step_fn: Callable[[AbstractDriver, ScrapingStep, str, int, Dict], Awaitable[bool]],
    base_url: str = "",
    timeout: int = 10,
) -> bool:
    """Execute a Loop action with full iteration, substitution, and break support."""

async def exec_conditional(
    driver: AbstractDriver,
    cond_action: Conditional,
    dispatch_step_fn: Callable[[AbstractDriver, ScrapingStep, str, int, Dict], Awaitable[bool]],
    base_url: str = "",
    timeout: int = 10,
) -> bool:
    """Execute a Conditional action with condition evaluation and branch dispatch."""

def substitute_template_vars(
    value: Any,
    index: int,
    start_index: int = 0,
    values: Optional[List[Any]] = None,
    value_name: str = "value",
) -> Any:
    """Recursively substitute {i}, {index}, {value}, arithmetic in strings/dicts/lists."""


# --- drivers/page_driver.py ---

class PageDriver(AbstractDriver):
    """Lightweight AbstractDriver wrapping a Playwright Page object."""
    def __init__(self, page: Any) -> None: ...
    async def start(self) -> None: ...   # no-op (page already exists)
    async def quit(self) -> None: ...    # await self._page.close()
    # All 19 abstract methods delegate to self._page


# --- session_manager.py ---

class SessionManager:
    """Owns a Playwright Browser; creates/caches/closes BrowserContexts by session label."""
    def __init__(self, browser: Any, default_context_kwargs: Optional[Dict] = None) -> None: ...
    async def get_context(self, session: str) -> Any: ...
    async def new_page(self, session: str) -> Any: ...
    def precompute_last_use(self, topo_order: List[FlowNode]) -> Dict[str, str]: ...
    async def close_if_last(self, session: str, node_id: str) -> None: ...
    async def close_all(self) -> None: ...


# --- flow_executor.py ---

class FlowExecutor:
    """Orchestrates ScrapingFlow execution with session management and checkpoints."""
    def __init__(
        self,
        browser: Any,
        registry: Optional[BasePlanRegistry] = None,
        config: Optional[DriverConfig] = None,
        concurrency: int = 1,
        checkpoint_dir: Optional[Path] = None,
        logger: Optional[logging.Logger] = None,
    ) -> None: ...

    async def run(
        self,
        flow: ScrapingFlow,
        params: Optional[Dict[str, Any]] = None,
        resume_from: Optional[str] = None,
    ) -> FlowResult: ...
```

---

## 3. Module Breakdown

### Module 1: ParamSpec & TemplatePlan (`template_plan.py`)
- **Path**: `packages/ai-parrot-tools/src/parrot_tools/scraping/template_plan.py`
- **Responsibility**: `ParamSpec` and `TemplatePlan` models; `bind()` validates params,
  renders `{{param}}` via regex in url_template/objective_template/steps_template strings,
  produces `ScrapingPlan` with `fingerprint = _compute_fingerprint(name + sorted_param_hash)`.
- **Depends on**: `ScrapingPlan` (plan.py), `_compute_fingerprint` (plan.py)
- **Key design decisions**:
  - Placeholder rendering uses `re.sub(r'\{\{(\w+)\}\}', replacer, text)` — NOT `str.format()`.
  - Rendering walks only string values in `steps_template` dicts recursively (like Loop's
    `_substitute_template_vars`). Non-string values pass through unchanged.
  - `bind()` raises `ValueError` for missing required params and type mismatches.
  - The produced `ScrapingPlan`'s fingerprint is overridden post-construction (set via
    `object.__setattr__` or by passing it to the constructor) to `hash(template_name + param_hash)`.

### Module 2: ScrapingFlow & FlowNode models (`flow_models.py`)
- **Path**: `packages/ai-parrot-tools/src/parrot_tools/scraping/flow_models.py`
- **Responsibility**: `FlowNode`, `ScrapingFlow` (DAG model), `FlowResult`. DAG validation
  (cycle detection, dangling ref checks) in `model_validator`.
- **Depends on**: None (pure data models; references `ScrapingResult` type only for annotation)
- **Key design decisions**:
  - `validate_dag()` builds an adjacency list from `inputs` refs, runs Kahn's algorithm for
    cycle detection, and verifies all `"node_id.field"` refs point to existing node IDs.
  - `ScrapingFlow.topological_order()` → `List[FlowNode]` is a public method (not just
    validation) used by `FlowExecutor`.

### Module 3: Advanced Actions extraction (`advanced_actions.py`)
- **Path**: `packages/ai-parrot-tools/src/parrot_tools/scraping/advanced_actions.py`
- **Responsibility**: Stateless async functions for Loop, Conditional, and template variable
  substitution. Extracted from `WebScrapingTool` (tool.py:2456-2664, 3271-3340).
- **Depends on**: `AbstractDriver` (drivers/abstract.py), `Loop` (models.py:679), `Conditional` (models.py:651), `ScrapingStep` (models.py:758), `ACTION_MAP` (models.py:726)
- **Key design decisions**:
  - Functions accept a `dispatch_step_fn` callback: `Callable[[AbstractDriver, ScrapingStep, str, int, Dict], Awaitable[bool]]`.
    This decouples them from any specific execution context (executor, tool, FlowExecutor).
  - `exec_loop` handles: fixed iterations, value-list iteration, JS condition loops,
    `break_on_error`, `max_iterations` safety limit, and `start_index` offset.
  - `substitute_template_vars` handles: `{i}`, `{index}`, `{iteration}`, arithmetic
    `{i+1}`, `{i*2}`, value substitution `{value}`. Uses safe eval with no builtins.
  - Legacy `WebScrapingTool` references to `self._driver`, `self._page`, etc. are replaced
    with explicit `driver` parameter. Access to `self._current_context` for condition
    evaluation is replaced with `driver.evaluate()`.

### Module 4: Executor integration (modify `executor.py`)
- **Path**: `packages/ai-parrot-tools/src/parrot_tools/scraping/executor.py`
- **Responsibility**: Replace the stub at lines 280-292 that skips `loop` and `conditional`
  with calls to `advanced_actions.exec_loop` / `exec_conditional`.
- **Depends on**: Module 3 (advanced_actions)
- **Key design decisions**:
  - Only `loop` and `conditional` are promoted from stub to real execution. The other
    stubbed actions (`get_cookies`, `set_cookies`, `authenticate`, `await_human`,
    `await_keypress`, `await_browser_event`, `upload_file`, `wait_for_download`) remain
    stubbed — they require browser-level context not available in the standalone executor.
  - The `dispatch_step_fn` callback passed to advanced_actions is a closure over `_dispatch_step`
    itself (enabling recursive loop-within-loop execution).

### Module 5: Legacy tool delegation (modify `tool.py`)
- **Path**: `packages/ai-parrot-tools/src/parrot_tools/scraping/tool.py`
- **Responsibility**: Delegate `_exec_loop` (line 2582), `_exec_conditional` (line 2456),
  and `_substitute_template_vars` (line 3271) to the `advanced_actions` module. The legacy
  methods become thin wrappers that adapt `self._driver` and `self._execute_step` to the
  stateless function signatures.
- **Depends on**: Module 3 (advanced_actions)
- **Key design decisions**:
  - `_exec_loop` wrapper: calls `advanced_actions.exec_loop(self._driver, action, self._execute_step_callback, base_url)`.
  - `_substitute_template_vars` becomes a module-level re-export or a one-line delegation.
  - `_substitute_action_vars` (line 3340) may remain on the tool class since it does
    model_dump/reconstruction specific to the tool's action handling; or it can be extracted
    if the pattern is reusable. Decide during implementation.

### Module 6: PageDriver adapter (`drivers/page_driver.py`)
- **Path**: `packages/ai-parrot-tools/src/parrot_tools/scraping/drivers/page_driver.py`
- **Responsibility**: Lightweight `AbstractDriver` implementation that wraps a Playwright
  `Page` object and delegates all 19 abstract methods.
- **Depends on**: `AbstractDriver` (drivers/abstract.py)
- **Key design decisions**:
  - `start()` → no-op (page is already alive when passed in).
  - `quit()` → `await self._page.close()` (closes this page only, not the context/browser).
  - `navigate(url)` → `await self._page.goto(url)`.
  - `click(selector)` → `await self._page.click(selector)`.
  - `get_page_source()` → `await self._page.content()`.
  - `current_url` property → `self._page.url`.
  - `execute_script(script, *args)` → `await self._page.evaluate(script, *args)`.
  - `wait_for_selector(selector, timeout, state)` → `await self._page.wait_for_selector(...)`.
  - XPath selectors (starting with `/` or `./`) are prefixed with `xpath=` (same logic as
    PlaywrightDriver lines 351-365).

### Module 7: SessionManager (`session_manager.py`)
- **Path**: `packages/ai-parrot-tools/src/parrot_tools/scraping/session_manager.py`
- **Responsibility**: Owns a Playwright `Browser` instance. Creates/caches/closes
  `BrowserContext`s by session label. Deterministic lifecycle.
- **Depends on**: Module 6 (PageDriver, for type reference)
- **Key design decisions**:
  - `get_context(session)` → lazy: creates on first call, returns cached thereafter.
  - `new_page(session)` → `context.new_page()`, returns the raw Playwright `Page`.
  - `precompute_last_use(topo_order)` → scans ordered nodes; `last_use[session] = node.id`
    (last node in topo order using that session).
  - `close_if_last(session, node_id)` → if `last_use[session] == node_id`, close the context.
  - `close_all()` → cleanup: close all remaining contexts (safety net).
  - Context kwargs (viewport, locale, storage_state, proxy) passed via `default_context_kwargs`
    at construction or overridden per session via a `session_configs: Dict[str, Dict]` parameter.

### Module 8: FlowExecutor (`flow_executor.py`)
- **Path**: `packages/ai-parrot-tools/src/parrot_tools/scraping/flow_executor.py`
- **Responsibility**: Orchestrates `ScrapingFlow` execution end-to-end.
- **Depends on**: Modules 1, 2, 3, 6, 7; `execute_plan_steps` (executor.py), `BasePlanRegistry` (base_registry.py)
- **Key design decisions**:
  - **Input resolution**: resolves `inputs["param"] = "node_id.field"` by looking up
    `node_results[node_id]` → accessing `ScrapingResult.extracted_data[field]` or
    `ExtractionResult.entities[idx].fields[field]`. Grammar: `"node_id.field_name"` for
    flat access; `"node_id.field_name[N]"` for list index; `"node_id.field_name[*]"` for
    fan-out (maps to N parallel executions of the dependent node).
  - **Fan-out**: when an input resolves to a list and uses `[*]`, the dependent node is
    cloned N times. Uses `asyncio.Semaphore(self._concurrency)` for bounded concurrency
    (pattern from CrawlEngine:173). Fan-out within a session is sequential (deferred debt).
  - **Checkpoint persistence**: after each node completes, writes `{node_id: ScrapingResult.model_dump()}`
    to `checkpoint_dir / f"{flow.name}_{run_id}.json"`. On `resume_from`, loads checkpoint
    and skips already-completed nodes.
  - **Error handling per node**:
    - `on_error="abort"` → stop flow, return partial FlowResult with `success=False`.
    - `on_error="skip"` → record failure in FlowResult, continue to next node (dependents
      of skipped node that require its output are also skipped).
    - `on_error="retry"` → retry up to `max_retries` times with fresh Page.

### Module 9: Exports & integration (modify `__init__.py`)
- **Path**: `packages/ai-parrot-tools/src/parrot_tools/scraping/__init__.py`
- **Responsibility**: Add new public exports.
- **Depends on**: All new modules
- **New exports**: `TemplatePlan`, `ParamSpec`, `ScrapingFlow`, `FlowNode`, `FlowExecutor`,
  `FlowResult`, `PageDriver`, `SessionManager`.

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_paramspec_validation` | 1 | ParamSpec rejects invalid type/choices combinations |

…(truncated)…
