---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Feature Specification: ScrapingFlow — Composable Long-Horizon Scraping

**Feature ID**: FEAT-221
**Date**: 2026-06-04
**Author**: Jesus Lara
**Status**: draft
**Target version**: next
**Proposal**: `sdd/proposals/scrapingflow-composable-scraping.proposal.md`
**Research audit**: `sdd/state/FEAT-221/`

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
| `test_template_bind_basic` | 1 | bind() renders {{param}} in url, objective, steps |
| `test_template_bind_missing_required` | 1 | bind() raises ValueError for missing required param |
| `test_template_bind_type_validation` | 1 | bind() validates int/date/enum types |
| `test_template_bind_defaults` | 1 | bind() fills defaults for optional params |
| `test_template_bind_fingerprint_unique` | 1 | Two binds with different params produce different fingerprints |
| `test_template_bind_fingerprint_stable` | 1 | Same params always produce same fingerprint |
| `test_template_does_not_expand_single_braces` | 1 | {{param}} renders but {index} passes through unchanged |
| `test_flownode_model` | 2 | FlowNode validates fields and defaults |
| `test_scrapingflow_valid_dag` | 2 | ScrapingFlow accepts valid connected DAG |
| `test_scrapingflow_detects_cycle` | 2 | ScrapingFlow rejects circular inputs |
| `test_scrapingflow_detects_dangling_ref` | 2 | ScrapingFlow rejects ref to non-existent node |
| `test_scrapingflow_topological_order` | 2 | topological_order() returns correct execution order |
| `test_exec_loop_fixed_iterations` | 3 | exec_loop runs N iterations with substitution |
| `test_exec_loop_values_list` | 3 | exec_loop iterates over values with {value} substitution |
| `test_exec_loop_condition` | 3 | exec_loop evaluates JS condition to continue/stop |
| `test_exec_loop_break_on_error` | 3 | exec_loop stops on step failure when break_on_error=True |
| `test_exec_conditional_true_branch` | 3 | exec_conditional runs actions_if_true when condition met |
| `test_exec_conditional_false_branch` | 3 | exec_conditional runs actions_if_false when condition not met |
| `test_substitute_template_vars_arithmetic` | 3 | Handles {i+1}, {i*2}, nested dicts/lists |
| `test_executor_dispatches_loop` | 4 | _dispatch_step calls exec_loop for "loop" action |
| `test_executor_dispatches_conditional` | 4 | _dispatch_step calls exec_conditional for "conditional" action |
| `test_legacy_tool_delegates_loop` | 5 | WebScrapingTool._exec_loop delegates to advanced_actions |
| `test_page_driver_navigate` | 6 | PageDriver.navigate delegates to page.goto |
| `test_page_driver_click` | 6 | PageDriver.click delegates to page.click |
| `test_page_driver_get_source` | 6 | PageDriver.get_page_source delegates to page.content |
| `test_page_driver_start_noop` | 6 | PageDriver.start() is a no-op |
| `test_page_driver_quit_closes_page` | 6 | PageDriver.quit() closes the page |
| `test_page_driver_xpath_prefix` | 6 | XPath selectors get `xpath=` prefix |
| `test_session_manager_lazy_create` | 7 | get_context creates on first call, caches on second |
| `test_session_manager_distinct_sessions` | 7 | Different session labels get different contexts |
| `test_session_manager_close_if_last` | 7 | Context closed after its last node |
| `test_session_manager_close_all` | 7 | close_all cleans up all contexts |
| `test_flow_executor_simple_linear` | 8 | Two-node linear flow executes in order |
| `test_flow_executor_input_resolution` | 8 | Data passes from node A's extracted_data to node B's params |
| `test_flow_executor_fan_out` | 8 | node[*] clones dependent node per list item |
| `test_flow_executor_checkpoint_resume` | 8 | Resume skips completed nodes, re-executes from failure |
| `test_flow_executor_abort_on_error` | 8 | on_error="abort" stops flow |
| `test_flow_executor_skip_on_error` | 8 | on_error="skip" continues, skips dependents |
| `test_flow_executor_retry_on_error` | 8 | on_error="retry" retries N times |

### Integration Tests

| Test | Description |
|---|---|
| `test_template_to_flow_end_to_end` | Create TemplatePlan, bind, execute via FlowExecutor with mocked Playwright |
| `test_multi_session_flow` | Flow with two sessions; verify distinct BrowserContexts |
| `test_flow_with_loop_steps` | Flow node containing Loop action executes correctly via advanced_actions |
| `test_checkpoint_persistence_and_resume` | Interrupt a flow mid-execution, resume from checkpoint |

### Test Data / Fixtures

```python
@pytest.fixture
def sample_template_plan():
    return TemplatePlan(
        name="search-flights",
        objective_template="Search flights from {{origin}} to {{destination}} on {{date}}",
        url_template="https://example.com/flights?from={{origin}}&to={{destination}}&date={{date}}",
        params=[
            ParamSpec(name="origin", type="string", required=True),
            ParamSpec(name="destination", type="string", required=True),
            ParamSpec(name="date", type="date", required=True),
        ],
        steps_template=[
            {"action": "navigate", "url": "{{url}}"},
            {"action": "wait", "condition": ".results", "condition_type": "selector"},
            {"action": "extract", "selector": ".flight-card", "output_key": "flights"},
        ],
    )

@pytest.fixture
def sample_flow():
    return ScrapingFlow(
        name="search-and-detail",
        nodes=[
            FlowNode(id="search", plan_ref="search-flights"),
            FlowNode(
                id="detail",
                plan_ref="flight-detail",
                inputs={"url": "search.flights[*]"},
                session="default",
            ),
        ],
    )

@pytest.fixture
def mock_playwright_browser():
    """Mock Playwright Browser with context/page creation."""
    ...
```

---

## 5. Acceptance Criteria

- [ ] `TemplatePlan.bind()` produces valid `ScrapingPlan`s with unique fingerprints per param set
- [ ] `TemplatePlan` uses `{{param}}` double-brace rendering; single-brace `{index}` passes through unchanged
- [ ] `ScrapingFlow` validates DAG on construction: rejects cycles, dangling refs
- [ ] `ScrapingFlow.topological_order()` returns correct execution order
- [ ] `advanced_actions.exec_loop` handles fixed iterations, value lists, JS conditions, break_on_error
- [ ] `advanced_actions.exec_conditional` handles true/false branch dispatch
- [ ] `executor._dispatch_step` calls `advanced_actions` for `loop`/`conditional` instead of stubbing
- [ ] `WebScrapingTool._exec_loop`/`_exec_conditional` delegate to `advanced_actions` (no duplication)
- [ ] `PageDriver` implements all 19 `AbstractDriver` abstract methods, delegating to Playwright Page
- [ ] `SessionManager` creates/caches/closes `BrowserContext`s by session label with deterministic lifecycle
- [ ] `FlowExecutor.run()` executes a flow end-to-end: topo sort → input resolution → bind → execute → checkpoint
- [ ] `FlowExecutor` supports resumption from checkpoint (skips completed nodes)
- [ ] `FlowExecutor` respects `on_error` per node: abort, skip, retry
- [ ] Fan-out (`[*]` syntax) clones dependent node per list item with bounded concurrency
- [ ] All unit tests pass: `pytest packages/ai-parrot-tools/tests/scraping/ -v`
- [ ] No breaking changes to existing `WebScrapingToolkit.scrape()` behavior
- [ ] No breaking changes to existing `execute_plan_steps()` behavior (non-loop plans)
- [ ] All new models use Pydantic BaseModel with strict type hints

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**

### Verified Imports

```python
# Confirmed: packages/ai-parrot-tools/src/parrot_tools/scraping/__init__.py
from parrot_tools.scraping import (
    WebScrapingToolkit, ScrapingPlan, PlanRegistry,
    CrawlEngine, BFSStrategy, DFSStrategy, CrawlStrategy,
    ExtractionPlan, ExtractedEntity, ExtractionResult,
    DriverFactory, AbstractDriver, PlaywrightDriver, SeleniumDriver,
    BasePlanRegistry, ExtractionPlanRegistry, PlaywrightConfig,
    ScrapingResult,
)

# Not re-exported in __init__; import directly:
from parrot_tools.scraping.executor import execute_plan_steps  # executor.py:41
from parrot_tools.scraping.plan import _compute_fingerprint, _normalize_url  # plan.py:31, 18
from parrot_tools.scraping.models import ACTION_MAP, ScrapingStep, Loop, Conditional  # models.py:726, 758, 679, 651
from parrot_tools.scraping.base_registry import BasePlanRegistry  # also in __init__
from parrot_tools.scraping.toolkit_models import DriverConfig  # toolkit_models.py:15
```

### Existing Class Signatures

```python
# packages/ai-parrot-tools/src/parrot_tools/scraping/plan.py
class ScrapingPlan(BaseModel):  # line 59
    name: Optional[str] = None
    version: str = "1.0"
    tags: List[str]
    url: str
    domain: str = ""
    objective: str
    steps: List[Dict[str, Any]]
    selectors: Optional[List[Dict[str, Any]]] = None
    browser_config: Optional[Dict[str, Any]] = None
    follow_selector: Optional[str] = None
    follow_pattern: Optional[str] = None
    max_depth: Optional[int] = None
    created_at: datetime  # auto: datetime.now(timezone.utc)
    updated_at: Optional[datetime] = None
    source: str = "llm"
    fingerprint: str = ""  # auto: _compute_fingerprint(normalized_url)

    @computed_field
    @property
    def normalized_url(self) -> str: ...  # line 92
    def model_post_init(self, __context: Any) -> None: ...  # line 98

def _normalize_url(url: str) -> str: ...  # line 18 — strips query/fragment
def _compute_fingerprint(normalized_url: str) -> str: ...  # line 31 — 16-char SHA-256

# packages/ai-parrot-tools/src/parrot_tools/scraping/executor.py
async def execute_plan_steps(  # line 41
    driver: AbstractDriver,
    plan: Optional[ScrapingPlan] = None,
    steps: Optional[List[Dict[str, Any]]] = None,
    selectors: Optional[List[Dict[str, Any]]] = None,
    config: Optional[DriverConfig] = None,
    base_url: Optional[str] = None,
) -> ScrapingResult: ...

# packages/ai-parrot-tools/src/parrot_tools/scraping/models.py
@dataclass
class ScrapingResult:  # line 834
    url: str
    content: str
    bs_soup: BeautifulSoup
    extracted_data: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)
    timestamp: str = ""
    success: bool = True
    error_message: Optional[str] = None

class Loop(BrowserAction):  # line 679
    actions: List["ActionList"]
    iterations: Optional[int] = None
    condition: Optional[str] = None
    values: Optional[List[Any]] = None
    value_name: Optional[str] = "value"
    break_on_error: bool = True
    max_iterations: int = 100
    start_index: int = 0
    do_replace: bool = True

class Conditional(BrowserAction):  # line 651
    target: Optional[str] = None
    target_type: Literal["css", "xpath"] = "css"
    condition_type: Literal["text_contains", "exists", "not_exists", "text_equals", "attribute_equals"]
    expected_value: str
    timeout: int = 5
    actions_if_true: Optional[List["ActionList"]] = None
    actions_if_false: Optional[List["ActionList"]] = None

ACTION_MAP: Dict[str, type]  # line 726 — 29 entries

class ScrapingStep:  # line 758, dataclass
    action: BrowserAction
    description: str = ""
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ScrapingStep": ...  # line 789
    def to_dict(self) -> Dict[str, Any]: ...  # line 774

# packages/ai-parrot-tools/src/parrot_tools/scraping/drivers/abstract.py
class AbstractDriver(ABC):  # line 11
    # 19 abstract methods:
    async def start(self) -> None: ...          # line 36
    async def quit(self) -> None: ...           # line 39
    async def navigate(self, url: str, timeout: int = 30) -> None: ...  # line 46
    async def go_back(self) -> None: ...        # line 55
    async def go_forward(self) -> None: ...     # line 58
    async def reload(self) -> None: ...         # line 62
    async def click(self, selector: str, timeout: int = 10) -> None: ...  # line 69
    async def fill(self, selector: str, value: str, timeout: int = 10) -> None: ...  # line 78
    async def select_option(self, selector: str, value: str, *, by: str = "value", timeout: int = 10) -> None: ...  # line 89
    async def hover(self, selector: str, timeout: int = 10) -> None: ...  # line 104
    async def press_key(self, key: str) -> None: ...  # line 115
    async def get_page_source(self) -> str: ...  # line 129
    async def get_text(self, selector: str, timeout: int = 10) -> str: ...  # line 140
    async def get_attribute(self, selector: str, attribute: str, timeout: int = 10) -> Optional[str]: ...  # line 151
    async def get_all_texts(self, selector: str, timeout: int = 10) -> List[str]: ...  # line 165
    async def screenshot(self, path: str, full_page: bool = False) -> None: ...  # line 176
    async def wait_for_selector(self, selector: str, timeout: int = 10, state: str = "visible") -> None: ...  # line 184
    async def wait_for_navigation(self, timeout: int = 30) -> None: ...  # line 198
    async def wait_for_load_state(self, state: str = "load", timeout: int = 30) -> None: ...  # line 207
    async def execute_script(self, script: str, *args) -> Any: ...  # line 219
    async def evaluate(self, expression: str) -> Any: ...  # line 233
    @property
    def current_url(self) -> str: ...  # line 244

# packages/ai-parrot-tools/src/parrot_tools/scraping/drivers/playwright_driver.py
class PlaywrightDriver(AbstractDriver):  # line 15
    async def start(self) -> None: ...  # line 41 — creates browser, ONE context, ONE page
    async def new_page(self) -> Any: ...  # line 330 — new page in SAME context

# packages/ai-parrot-tools/src/parrot_tools/scraping/extraction_models.py
class ExtractionPlan(BaseModel):  # line 69
    def to_scraping_plan(self) -> ScrapingPlan: ...  # line 127 — translation pattern

class ExtractedEntity(BaseModel):  # line 171
    entity_type: str
    fields: Dict[str, Any]  # key=field_name, value=extracted_data
    source_url: str
    confidence: float
    raw_text: Optional[str] = None
    rag_text: str = ""

class ExtractionResult(BaseModel):  # line 193
    url: str
    objective: str
    entities: List[ExtractedEntity]
    plan_used: ExtractionPlan
    success: bool = True
    error_message: Optional[str] = None
    elapsed_seconds: float = 0.0

# packages/ai-parrot-tools/src/parrot_tools/scraping/base_registry.py
class BasePlanRegistry(Generic[T]):  # generic over plan type
    def __init__(self, plans_dir=None, index_filename="registry.json"): ...
    def lookup(self, url: str, *, allow_domain_fallback=True) -> Optional[PlanRegistryEntry]: ...  # line 93
    def get_by_name(self, name: str) -> Optional[PlanRegistryEntry]: ...  # line 151
    async def register(self, plan, relative_path: str) -> None: ...

# packages/ai-parrot-tools/src/parrot_tools/scraping/tool.py (legacy — extraction targets)
class WebScrapingTool:  # line 119
    async def _exec_conditional(self, action: Conditional, base_url: str = "", args=None) -> bool: ...  # line 2456
    async def _exec_loop(self, action: Loop, base_url: str) -> bool: ...  # line 2582
    def _substitute_template_vars(self, value, index, start_index=0, values=None, value_name="value"): ...  # line 3271
    def _substitute_action_vars(self, action, index, start_index=0, values=None, value_name="value"): ...  # line 3340
```

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `TemplatePlan.bind()` | `ScrapingPlan()` | constructor call | `plan.py:59` |
| `TemplatePlan.bind()` | `_compute_fingerprint()` | function call | `plan.py:31` |
| `FlowExecutor.run()` | `execute_plan_steps()` | function call per node | `executor.py:41` |
| `FlowExecutor.run()` | `SessionManager` | context lifecycle | new module |
| `FlowExecutor.run()` | `PageDriver()` | driver adapter per node | new module |
| `PageDriver` | `AbstractDriver` | implements ABC | `drivers/abstract.py:11` |
| `advanced_actions.exec_loop` | `Loop` model | reads action fields | `models.py:679` |
| `advanced_actions.exec_conditional` | `Conditional` model | reads action fields | `models.py:651` |
| `executor._dispatch_step` | `advanced_actions` | function call | `executor.py:280` (stub to replace) |
| `tool._exec_loop` | `advanced_actions.exec_loop` | delegation | `tool.py:2582` |

### Does NOT Exist (Anti-Hallucination)

- ~~`parrot_tools.scraping.TemplatePlan`~~ — to be created (Module 1)
- ~~`parrot_tools.scraping.ScrapingFlow`~~ — to be created (Module 2)
- ~~`parrot_tools.scraping.FlowExecutor`~~ — to be created (Module 8)
- ~~`parrot_tools.scraping.PageDriver`~~ — to be created (Module 6)
- ~~`parrot_tools.scraping.SessionManager`~~ — to be created (Module 7)
- ~~`parrot_tools.scraping.advanced_actions`~~ — to be created (Module 3)
- ~~`ScrapingPlan.bind()`~~ — does NOT exist on ScrapingPlan; lives on TemplatePlan
- ~~`ScrapingPlan.params`~~ — does NOT exist; params are on TemplatePlan
- ~~`PlaywrightDriver.new_context()`~~ — does NOT exist; only `new_page()` on same context
- ~~`AbstractDriver.new_page()` / `AbstractDriver.get_context()`~~ — not in the interface
- ~~`execute_plan_steps` handling Loop/Conditional~~ — currently STUBBED, returns True
- ~~`WebScrapingToolkit._exec_loop`~~ — does NOT exist on toolkit; only on legacy tool
- ~~`CrawlEngine.checkpoint()` / `CrawlEngine.resume()`~~ — no checkpoint mechanism exists

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- **`ExtractionPlan.to_scraping_plan()`** (extraction_models.py:127) — translation pattern
  for `TemplatePlan.bind()`: validate inputs, build steps/selectors, return `ScrapingPlan`.
- **`ExtractionPlanRegistry(BasePlanRegistry[T])`** (extraction_registry.py) — extension
  pattern for optional `TemplatePlanRegistry`: separate index file, per-fingerprint storage.
- **`asyncio.Semaphore + gather`** (crawler.py:173) — bounded concurrency for fan-out.
- **Pydantic BaseModel** for all new data models (consistent with ScrapingPlan, ExtractionPlan).
- **Async-first** — all execution methods are async; no blocking I/O.
- **Logger pattern** — `self.logger = logging.getLogger(__name__)` in classes.

### Known Risks / Gotchas

- **Fan-out on shared authenticated session**: multiple Pages in one BrowserContext
  writing cookies simultaneously may race. Mitigation: sequential execution within a
  session; concurrent fan-out only across different sessions. Documented as deferred debt.
- **PageDriver method parity**: 19 abstract methods to implement. Some Playwright Page
  methods have slightly different signatures (e.g., `wait_for_selector` state values).
  Test each method against the Playwright Page API.
- **Template placeholder collision**: `{{param}}` must NOT be rendered inside values that
  are already processed by Loop's `{index}` — the two conventions are orthogonal. bind()
  runs at plan-creation time (before execution); Loop substitution runs at step-execution time.
- **Fingerprint override in bind()**: `ScrapingPlan.model_post_init` auto-computes fingerprint
  from URL. `bind()` must override this after construction. Use `plan.fingerprint = computed_hash`
  (Pydantic v2 models allow direct attribute assignment by default).
- **_exec_loop's self references**: the legacy `_exec_loop` accesses `self._driver`,
  `self._page`, `self._execute_step`. The extracted version must accept these as parameters.
  Careful mapping required for `self._current_context` (used for JS condition evaluation) →
  replaced with `driver.evaluate()`.

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| `playwright` | `>=1.40` | BrowserContext/Page for multi-window; already in use via PlaywrightDriver |
| `pydantic` | `>=2.0` | Models: TemplatePlan, ScrapingFlow, FlowNode, ParamSpec, FlowResult |

No new dependencies — both are already used by the project.

---

## 8. Open Questions

### Resolved (carried from brainstorm and proposal)

- [x] **Parametrización LLM-inferida vs. nace parametrizado** — *Resolved in brainstorm*: Ambos. Un LLM puede generalizar un ScrapingPlan existente a TemplatePlan, y un PlanGenerator puede producir plantillas directamente.
- [x] **Fingerprint/clave de registry para plantillas** — *Resolved in brainstorm*: `template_name + param_hash`. hash(name + sorted(params.items())).
- [x] **Sintaxis de placeholders** — *Resolved in proposal (corrected)*: TemplatePlan uses `{{param}}` double braces. Loop uses `{index}` single braces. The brainstorm's claim of "double-brace Loop convention" was incorrect (F003).
- [x] **Almacenamiento de checkpoints** — *Resolved in brainstorm*: File-based JSON per execution run. No existing checkpoint mechanism to reuse (F004, F008).
- [x] **Afinidad de sesión** — *Resolved in brainstorm*: Explicit `session` field per FlowNode. Data-flow and BrowserContext are orthogonal axes.
- [x] **Quién ejecuta el flow** — *Resolved in brainstorm*: FlowExecutor inside the engine, over execute_plan_steps. Not delegated to external agents.
- [x] **Driver del flow** — *Resolved in brainstorm*: Playwright-first via PageDriver adapter. Single-plan scrape() stays driver-agnostic.
- [x] **Loop/Conditional in flow nodes** — *Resolved in proposal*: Extract from legacy WebScrapingTool into shared advanced_actions module. Fixes existing gap in WebScrapingToolkit (F011).
- [x] **PlaywrightDriver multi-context** — *Resolved in proposal*: PlaywrightDriver only supports one BrowserContext (F006). FlowExecutor uses SessionManager working directly with Playwright Browser.

### Unresolved (to be resolved during implementation)

- [ ] **Inputs resolver grammar details** — *Owner*: implementer. Basic grammar defined: `"node_id.field"` for flat access, `"node_id.field[N]"` for index, `"node_id.field[*]"` for fan-out. Open: whether to support deeper nesting (`"node_id.entity_type.field.subfield"`) or keep it flat. Start flat, extend if needed.
- [ ] **Fan-out concurrency on shared authenticated session** — *Owner*: deferred. Sequential within session is safe; concurrent fan-out across sessions. Revisit when `concurrency > 1` within a session is needed.
- [ ] **`_substitute_action_vars` extraction** — *Owner*: implementer of Module 5. Decide whether this helper (tool.py:3340) should be extracted alongside the other three functions or remain on the legacy tool class.

---

## Worktree Strategy

**Isolation**: `per-spec` — all tasks run sequentially in one worktree.

**Rationale**: While Modules 1, 2, 3, and 6 have no interdependencies and could theoretically
run in parallel, they all share `__init__.py` (Module 9) and the test infrastructure. The
risk of merge conflicts outweighs the parallelism benefit for 9 modules.

**Dependency graph**:
```
Group A (parallel-safe): 1 (TemplatePlan), 2 (FlowModels), 3 (AdvancedActions), 6 (PageDriver)
Group B:                 4 (Executor mod) ← 3,  5 (Tool mod) ← 3,  7 (SessionMgr) ← 6
Group C:                 8 (FlowExecutor) ← 1, 2, 3, 6, 7
Group D:                 9 (Exports) ← all
```

**Recommended execution order** (sequential within worktree):
1. Module 3 (advanced_actions) — no dependencies, enables 4 and 5
2. Module 4 (executor integration) — immediate payoff: fixes WebScrapingToolkit gap
3. Module 5 (legacy tool delegation) — completes the extraction
4. Module 1 (TemplatePlan) — independent data model
5. Module 2 (FlowModels) — independent data model
6. Module 6 (PageDriver) — independent adapter
7. Module 7 (SessionManager) — depends on 6
8. Module 8 (FlowExecutor) — integrates everything
9. Module 9 (exports) — final wiring

**Cross-feature dependencies**: None. All referenced existing code is stable (20 commits
in 60 days, no conflicting features in progress).

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-06-04 | Jesus Lara / Claude | Initial draft from FEAT-221 proposal |
