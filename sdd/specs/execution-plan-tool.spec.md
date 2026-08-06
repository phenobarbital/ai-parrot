---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Feature Specification: ExecutionPlanToolkit — deterministic tool-call DAGs for a BasicAgent

**Feature ID**: FEAT-419
**Date**: 2026-08-07
**Author**: Jesus Lara
**Status**: draft
**Target version**: 0.26.0
**Brainstorm**: `sdd/proposals/execution-plan-tool.brainstorm.md` (Option D accepted)

---

## 1. Motivation & Business Requirements

### Problem Statement

Pipelines like the daily Security Advisory flow (list scanner reports in S3 →
parse each one → diff against the previous scan → map to SOC2/NIST controls)
execute dozens to hundreds of tool calls whose payloads (Prowler/Trivy/
CloudSploit reports, hundreds of MB) do not fit in any model's context window
— and which the model **does not need to see**: they only need to be
executed, stored, and analyzed afterwards.

An LLM tool-by-tool loop is worse on every axis: O(N²) input tokens (history
re-sent each iteration), inherently serial (step k+1 cannot be emitted before
step k finishes), and it fails at runtime on unknown tools or invalid args.

The alternative: a *thinking* model writes the complete plan **once** as a
structured `ExecutionPlan`; code validates it statically and executes it on
`AgentsFlow` with **zero LLM tokens in the loop**; payloads go to
`WorkingMemory`; the model later reads back artifacts under keys it chose.

The plan *execution* machinery is already built and tested (60 tests): the
`plan/` module attached at `sdd/artifacts/plan/`, destined for
`packages/ai-parrot/src/parrot/bots/flows/plan/`. **This feature lands that
module and builds the wrapper around it**: `ExecutionPlanToolkit`, the
`AbstractToolkit` that lets a plain `BasicAgent` trigger a plan. The
`ExecutionPlan` schema and `PlanToolNode` executor are frozen contracts —
constraints, not design space.

**Hard requirement**: the invoking agent stays a normal `BasicAgent`. It does
NOT become a Flow or a Crew — it *invokes* a flow through a tool.

### Goals

- A `BasicAgent` can run a deterministic tool-call DAG through one bounded
  tool-call; zero LLM tokens are spent during execution.
- No tool payload ever enters `FlowContext.results`, the tool response, or
  any LLM context — only `ArtifactRef`s (keys + facets + status + bytes).
- Two plan sources in v1: `objective` → internal planner LLM (one structured
  call + at most one validation-repair round), and `plan_name` → versioned
  plan file from a configurable `plans_dir` with load-time
  `{params.<name>}` substitution.
- An invalid plan fails at validation with the complete issue list — never
  at node 47.
- A 300-report run survives the agent's tool-call timeout (soft-timeout →
  `run_id` + `plan_status` polling) and is per-item resumable via
  `ForEach.skip_existing` idempotence.
- Partial failure is data, not an exception: the manifest reports
  `completed | partial | failed`; the agent decides what to do next.
- A shared `ToolManager` cannot be escaped: an explicit `allowed_tools`
  allowlist bounds what a plan may invoke and doubles as the planner's tool
  catalog.

### Non-Goals (explicitly out of scope)

- Redesigning `ExecutionPlan` / `PlanNode` / `ForEach` / `when` or extending
  `PlanToolNode._resolve_args` — the `plan/` module is frozen (60 tests).
- Agent-emitted plans as tool-call arguments — rejected in brainstorm
  (Option A: ~2.9K-token schema permanently in the agent's tool prompt); see
  `proposals/execution-plan-tool.brainstorm.md`.
- Persistent `WorkingMemory` backend (spill to disk/S3 + Postgres index) —
  separate follow-up feature. v1 is pure in-RAM, **no guardrail** (explicit
  user decision; `bytes_stored` gives visibility).
- Cross-restart `plan_resume(run_id)` on FEAT-399 checkpoints — v2. In v1 a
  process restart loses the run registry; re-issuing the same plan redoes
  only missing work thanks to `skip_existing`.
- Per-call `PermissionContext` propagation from the invoking agent — v1
  forwards an optional constructor-level `permission_context`; follow-up.
- DB-backed plan store; execution-wiki / `ReportRef` traceability
  integration — follow-ups.
- The independent cheap fixes noted in the brainstorm (Bedrock unbounded
  tool loop; `_inject_answer_memory_into_toolkits` unwrap bug) — separate
  tasks, not part of this feature.

---

## 2. Architectural Design

### Overview

A single new toolkit, `ExecutionPlanToolkit(AbstractToolkit)`, initialized
once with live dependencies (the FEAT-207 shared-state toolkit pattern):

```
toolkit = ExecutionPlanToolkit(
    tool_manager=...,            # required — dispatch + validation target
    working_memory=...,          # required — SAME instance the analyst uses
    planner_llm=None,            # optional — enables objective mode
    plans_dir=None,              # optional — enables plan_name mode
    allowed_tools=None,          # optional — None ⇒ all manager tools
    soft_timeout=60.0,
    permission_context=None,     # v1: constructor-level default only
    on_node_event=None,          # optional flow-lifecycle listener
)
```

It exposes four small tools to the agent's LLM:

| Tool | Purpose |
|---|---|
| `plan_execute(objective=None, plan_name=None, params=None)` | Acquire → validate → compile → run. Exactly one of `objective`/`plan_name`. Returns the full `ExecutionManifest` if done within `soft_timeout`, else `{run_id, status:"running", nodes_total, nodes_done}` while execution continues in background. |
| `plan_status(run_id)` | Progress counts while running; the final `ExecutionManifest` after completion (kept in the run registry). |
| `plan_artifacts(run_id)` | `ArtifactRef` list so far — the WorkingMemory key map the analyst reads. |
| `plan_validate(objective=None, plan_name=None, params=None)` | Dry-run: acquire + validate, return plan JSON + `ValidationReport`, execute nothing. |

Failure semantics (resolved in brainstorm, Axis 4): the manifest is ALWAYS
the success payload — `status` `completed|partial|failed` with per-node
errors inside (already capped by `MAX_RECORDED_ERRORS=20`). Tool-level
errors are reserved for structural failures: invalid plan after the repair
round, both/neither plan source given, `objective` without `planner_llm`,
unknown `run_id`, unknown `plan_name`.

Replan lives OUTSIDE the tool (Axis 5): the agent reads manifest errors and
may re-invoke `plan_execute`. The only internal LLM loop is one bounded
**pre-execution repair round**: if validation fails, the planner is
re-prompted once with the `ValidationReport` (whose messages are written for
exactly this), then the toolkit gives up and returns the report.

### Component Diagram

```
BasicAgent (unchanged)
    │  tool-call: plan_execute(objective | plan_name+params)
    ▼
ExecutionPlanToolkit ──────────────────────────────┐
    │ acquire                                      │ shared state:
    ├─ objective ─→ PlannerClient (1 LLM call,     │  · run registry
    │               structured_output=ExecutionPlan,│    {run_id → RunRecord}
    │               ≤1 repair round)               │  · plan store cache
    └─ plan_name ─→ PlanStore (plans_dir file,     │  · tool catalog
                    {params.<name>} load-time subst)│    (allowlist ∩ manager)
    │
    ▼ validate_plan(plan, tool_manager) + allowlist issues   [0 tokens]
    ▼ ensure_tool_node_registered(PlanToolNode); to_flow_definition(plan)
    ▼ AgentsFlow.from_definition(defn,
         agent_registry=<empty>,
         node_factories={"tool": make_tool_node_factory(
             tool_manager, working_memory, permission_context)})
    ▼ run_flow(ctx) as asyncio.Task  ──→ on_node_event listeners
    │        │ each node: ToolManager.execute_tool(...)      [0 tokens]
    │        └─→ WorkingMemory.store_result(key=<from plan>)  (payloads)
    ▼ build_manifest() → ExecutionManifest (<2 KB, bounded by construction)
    │
    └──→ agent reads manifest; analyst rehydrates chosen keys via WM tools
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `parrot/bots/flows/plan/` (new, from `sdd/artifacts/plan/`) | adds | Drop-in of the tested module; `_shim.py` is NOT shipped (test-only scaffold) |
| `parrot/tools/execution_plan/` (new) | adds | The toolkit, per `.agent/workflows/create-parrot-tool.md` conventions |
| `AgentsFlow.from_definition` | uses | Requires `agent_registry` unconditionally (flow.py:494-498) even with zero agent nodes — toolkit passes an empty registry; no core change |
| `NODE_REGISTRY` (flow.py) | extends | `"tool"` registered lazily via idempotent `ensure_tool_node_registered(PlanToolNode)`; raises on conflicting registration |
| `ToolManager.execute_tool` | uses | All dispatch via manager (manager.py:1431) — hooks, postprocess, permissions preserved; `status=="error"` ⇒ `ValueError` (:1614) is caught per-node by `PlanToolNode` |
| `WorkingMemoryToolkit.store_result` | uses | Shared instance injected by constructor (Axis 7); catalog stays in-RAM in v1 |
| `AgentCrew.add_tool_node()` | unaffected | Uses crew `ToolNode` directly, not `NODE_REGISTRY` — must keep passing tests |
| Security Advisory pipeline | consumer | First user: daily plan as a versioned file in `plans_dir` |

### Data Models

All plan-side models already exist in the frozen module (see §6). New
toolkit-side models (Pydantic v2, `extra="forbid"`):

```python
# parrot/tools/execution_plan/models.py (new)

class RunRecord(BaseModel):
    """Registry entry for one plan run (toolkit-internal)."""
    run_id: str                          # short unique id, e.g. "run_ab12cd"
    plan_name: str
    source: Literal["objective", "plan_name"]
    status: Literal["running", "completed", "partial", "failed"]
    started_at: datetime
    finished_at: Optional[datetime]
    manifest: Optional[ExecutionManifest]   # set on completion
    nodes_total: int
    nodes_done: int
    # non-serialized runtime handle: the asyncio.Task + AgentsFlow instance

class RunningSummary(BaseModel):
    """What plan_execute returns when soft_timeout elapses first."""
    run_id: str
    status: Literal["running"]
    plan_name: str
    nodes_total: int
    nodes_done: int
    hint: str    # "poll plan_status(run_id)"
```

Tool args schemas follow the repo convention (`AbstractToolArgsSchema`):
`PlanExecuteArgs(objective, plan_name, params)`, `PlanStatusArgs(run_id)`,
`PlanArtifactsArgs(run_id)`, `PlanValidateArgs(objective, plan_name, params)`.

Run-registry bounds (v1 defaults, resolved here): completed/failed records
are evicted oldest-first beyond `max_completed_runs=50`; in-flight runs are
never evicted; no `max_concurrent_runs` cap in v1.

### New Public Interfaces

```python
# parrot/tools/execution_plan/toolkit.py (new) — signatures only
class ExecutionPlanToolkit(AbstractToolkit):
    def __init__(
        self,
        *,
        tool_manager: ToolManager,
        working_memory: WorkingMemoryToolkit,
        planner_llm: Union[str, dict, AbstractClient, None] = None,
        plans_dir: Union[str, Path, None] = None,
        allowed_tools: Optional[Sequence[str]] = None,
        soft_timeout: float = 60.0,
        permission_context: Optional[PermissionContext] = None,
        on_node_event: Optional[Callable[..., Any]] = None,
        max_completed_runs: int = 50,
    ) -> None: ...

    async def plan_execute(self, objective=None, plan_name=None, params=None) -> ToolResult: ...
    async def plan_status(self, run_id: str) -> ToolResult: ...
    async def plan_artifacts(self, run_id: str) -> ToolResult: ...
    async def plan_validate(self, objective=None, plan_name=None, params=None) -> ToolResult: ...

# parrot/tools/execution_plan/store.py (new)
class PlanFileStore:
    def __init__(self, plans_dir: Path) -> None: ...
    def load(self, plan_name: str, params: Optional[dict] = None) -> ExecutionPlan: ...
    # {params.<name>} substitution over string leaves BEFORE model_validate;
    # missing OR unused params raise PlanLoadError. YAML and JSON accepted.

# parrot/tools/execution_plan/planner.py (new)
class PlanPlanner:
    def __init__(self, planner_llm, catalog: list[ToolCatalogEntry]) -> None: ...
    async def author(self, objective: str) -> ExecutionPlan: ...
    async def repair(self, plan_json: dict, report: ValidationReport) -> ExecutionPlan: ...
```

`planner_llm` accepts the same formats as bots' `llm` / `secondary_llm`
(`"provider:model"` | `AbstractClient` class/instance | model_config dict —
pattern: `parrot/bots/mixins/model_switching.py:92`). No implicit default:
unset + `objective` ⇒ structural error naming the missing constructor arg.

The planner prompt embeds `sdd/artifacts/execution_plan.schema.json` —
verified byte-equivalent to `ExecutionPlan.model_json_schema()` — as the
structured-output schema, plus the tool catalog (allowlist ∩ manager:
name, description, `args_schema` summary per tool).

---

## 3. Module Breakdown

### Module 1: Land the `plan/` module
- **Path**: `packages/ai-parrot/src/parrot/bots/flows/plan/` (`models.py`,
  `paths.py`, `guards.py`, `facets.py`, `validator.py`, `compile.py`,
  `node.py`, `__init__.py`) + tests to
  `packages/ai-parrot/tests/bots/flows/plan/`
- **Responsibility**: Drop in the attached module from `sdd/artifacts/plan/`
  verbatim (minus `_shim.py`; the shim import fallbacks in `node.py`/
  `compile.py` collapse to the real `parrot.bots.flows.*` imports). All 60
  tests pass against the real package.
- **Depends on**: nothing new (existing flow core, CEL evaluator).

### Module 2: Toolkit skeleton + run registry
- **Path**: `parrot/tools/execution_plan/{__init__.py,toolkit.py,models.py}`
- **Responsibility**: `ExecutionPlanToolkit` with constructor wiring,
  `RunRecord` registry (bounded, evict oldest completed beyond
  `max_completed_runs`), `plan_status` + `plan_artifacts`, soft-timeout
  execution path (`asyncio.Task` + bounded wait), empty-`AgentRegistry`
  bridge to `from_definition`, `on_node_event` attachment, manifest capture
  via `build_manifest`.
- **Depends on**: Module 1.

### Module 3: Plan file store (`plan_name` mode)
- **Path**: `parrot/tools/execution_plan/store.py`
- **Responsibility**: `PlanFileStore` — resolve `plans_dir/<name>.(yaml|json)`,
  apply `{params.<name>}` load-time substitution over string leaves,
  fail loudly on missing/unused params or unknown plan, then
  `ExecutionPlan.model_validate`. Migrate `sdd/artifacts/example_plan.json`
  → a valid `plans/daily_security_sweep.json` example using `{params.date}`
  (its current `{input}` placeholder is unsupported by the executor).
- **Depends on**: Module 1.

### Module 4: Planner client (`objective` mode)
- **Path**: `parrot/tools/execution_plan/planner.py`
- **Responsibility**: `PlanPlanner` — resolve `planner_llm` formats, build
  the catalog-scoped prompt, one structured-output call →
  `ExecutionPlan`, one bounded repair round fed by `ValidationReport`,
  then give up returning the report.
- **Depends on**: Module 1, Module 5 (catalog).

### Module 5: Allowlist + catalog + validation layering
- **Path**: `parrot/tools/execution_plan/catalog.py` (+ toolkit glue)
- **Responsibility**: Build the tool catalog (allowlist ∩
  `tool_manager.list_tools()`, with description + `args_schema` summary);
  layer `tool_not_allowed` `ValidationIssue`s on top of
  `validate_plan(plan, tool_manager)` output; `plan_validate` dry-run tool.
- **Depends on**: Module 1, Module 2.

### Module 6: End-to-end integration + docs
- **Path**: `packages/ai-parrot/tests/tools/execution_plan/test_integration.py`,
  `docs/`
- **Responsibility**: A real `BasicAgent` + fake tools proving: zero LLM
  calls during execution, payloads only in WM, partial manifest on induced
  failures, soft-timeout → `run_id` → `plan_status` flow, allowlist block,
  `AgentCrew.add_tool_node()` regression green. Usage docs.
- **Depends on**: Modules 1–5.

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_plan_module_lands_with_real_imports` | 1 | The 60 attached tests pass with `parrot.bots.flows.*` imports (no shim) |
| `test_ensure_tool_node_registered_idempotent_and_conflict` | 1 | Second call no-ops; foreign `"tool"` registration raises |
| `test_execute_returns_manifest_within_soft_timeout` | 2 | Fast plan → full `ExecutionManifest` in the tool response |
| `test_execute_soft_timeout_returns_run_id` | 2 | Slow plan → `RunningSummary`; run continues; `plan_status` later yields the final manifest |
| `test_partial_failure_is_success_payload` | 2 | Induced node errors → manifest `status="partial"`, tool call succeeds |
| `test_structural_errors_are_tool_errors` | 2 | both/neither source; unknown `run_id`; `objective` without `planner_llm` |
| `test_run_registry_eviction` | 2 | >`max_completed_runs` completed runs → oldest evicted; in-flight never evicted |
| `test_store_loads_yaml_and_json` | 3 | Both formats validate to `ExecutionPlan` |
| `test_store_params_substitution` | 3 | `{params.date}` replaced before validation; native-value rule for exact-match placeholders |
| `test_store_missing_and_unused_params_raise` | 3 | Nothing silent: both directions fail the load |
| `test_planner_single_call_then_repair` | 4 | Invalid first plan → exactly one repair round with `ValidationReport` text → then give up |
| `test_planner_llm_formats` | 4 | `"provider:model"` string, instance, dict all resolve; unset + objective ⇒ clear error |
| `test_catalog_is_allowlist_intersection` | 5 | Catalog = allowlist ∩ manager; unset allowlist ⇒ all tools |
| `test_tool_not_allowed_validation_issue` | 5 | Plan naming a manager-registered but non-allowlisted tool fails validation pre-execution |
| `test_plan_validate_dry_run` | 5 | Returns plan JSON + report; `ToolManager.execute_tool` never called |

### Integration Tests

| Test | Description |
|---|---|
| `test_basicagent_end_to_end_zero_tokens_in_loop` | `BasicAgent` + fake tool fleet: planner mock called ≤2×, zero LLM calls during execution, payloads only in WM, manifest <2 KB |
| `test_300_item_fanout_resumable` | Fan-out with induced crash mid-run; re-issued plan redoes only missing keys (`skip_existing`) |
| `test_agentcrew_add_tool_node_regression` | Registering `"tool"` in `NODE_REGISTRY` leaves `AgentCrew.add_tool_node()` behavior intact |
| `test_no_payload_in_flowcontext_results` | Assert every `ctx.results` value is an `ArtifactRef`, never a body |

### Test Data / Fixtures

```python
@pytest.fixture
def fake_tool_manager():
    """ToolManagerLike with sync/async fake tools, args_schema, and an
    error-injecting tool; records execute_tool calls for zero-token asserts."""

@pytest.fixture
def wm_toolkit():
    """Real WorkingMemoryToolkit on an in-memory catalog, shared between
    executor and assertions."""

@pytest.fixture
def canned_planner():
    """Planner double returning scripted ExecutionPlans (valid / invalid-
    then-repaired / invalid-twice) without any network."""

@pytest.fixture
def plans_dir(tmp_path):
    """Writes daily_security_sweep.{yaml,json} with {params.date}."""
```

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] The `plan/` module lives at
  `packages/ai-parrot/src/parrot/bots/flows/plan/`, `_shim.py` is not
  shipped, and all 60 attached tests pass against real imports.
- [ ] `ExecutionPlanToolkit` exposes exactly `plan_execute`, `plan_status`,
  `plan_artifacts`, `plan_validate`; response payloads are bounded (an
  `ExecutionManifest` for the 4-node example plan serializes to <2 KB).
- [ ] No payload body ever appears in `FlowContext.results` or in any tool
  response — asserted by integration test.
- [ ] Zero LLM calls occur between validation success and manifest
  construction — asserted by integration test (planner mock call count ≤2:
  one authoring + at most one repair).
- [ ] All plan-node dispatch goes through `ToolManager.execute_tool()` with
  the constructor `permission_context` forwarded — never `tool.execute()`.
- [ ] A plan with failing nodes returns a `partial` manifest as a
  SUCCESSFUL tool call; structural failures (invalid plan, bad args,
  unknown `run_id`/`plan_name`, unconfigured planner) are tool errors.
- [ ] `plan_execute` returns within `soft_timeout` (default 60 s): full
  manifest if done, else `run_id` summary with execution continuing;
  `plan_status(run_id)` returns the final manifest after completion.
- [ ] An invalid plan fails at validation with ALL issues in one report —
  including `tool_not_allowed` for tools outside `allowed_tools` — and no
  tool is ever executed.
- [ ] `plan_name` mode loads YAML/JSON from `plans_dir` with load-time
  `{params.<name>}` substitution; missing or unused params fail the load;
  the executor's runtime placeholders are untouched.
- [ ] `planner_llm` accepts `"provider:model"` | instance | dict; unset +
  `objective` yields a clear structural error; `plan_name` mode works
  without any planner configured.
- [ ] Registering `"tool"` in `NODE_REGISTRY` breaks neither existing node
  types nor `AgentCrew.add_tool_node()` (regression test green).
- [ ] The example plan ships as a valid `plans_dir` file using
  `{params.date}` (no `{input}`).
- [ ] All unit + integration tests pass (`pytest` on the touched packages);
  no changes to `BasicAgent`'s class body.
- [ ] Documentation updated in `docs/` (usage + the v1 RAM caveat for
  WorkingMemory).

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> Verified on `dev` 2026-08-07 (post-merge `019e945`). The user's original
> brief cited `main` line numbers; where they drifted, the `dev` number is
> authoritative below.

### Verified Imports

```python
from parrot.bots.flows.flow.definition import (   # used by plan/compile.py
    EdgeDefinition, FlowDefinition, FlowMetadata, NodeDefinition,
)
from parrot.bots.flows.flow.flow import NODE_REGISTRY, register_node
from parrot.bots.flows.core.node import Node          # PlanToolNode base
from parrot.bots.flows.core.fsm import AgentTaskMachine
from ..abstract import AbstractTool, AbstractToolArgsSchema, ToolResult
#   ^ tool convention per .agent/workflows/create-parrot-tool.md
```

### Existing Class Signatures

#### The attached plan module (source: `sdd/artifacts/plan/`, destination `parrot/bots/flows/plan/`)

```python
# sdd/artifacts/plan/models.py
class ExecutionPlan(BaseModel):        # :272 — name, objective, nodes, metadata
    def topological_order(self) -> List[str]: ...   # :371
class PlanNode(BaseModel):             # :175 — id, tool, args, store_as,
                                       #   depends_on, when, for_each, facets,
                                       #   timeout, retry, description
class ForEach(BaseModel):              # :110 — source, select, alias("as"),
                                       #   max_items, max_concurrency,
                                       #   on_item_error, skip_existing
class ArtifactRef(BaseModel):          # :413 — node_id, keys, entry_type,
                                       #   facets, status, item_count, errors,
                                       #   bytes_stored
class ExecutionManifest(BaseModel):    # :444 — plan_name, objective,
                                       #   session_id, artifacts, node counts,
                                       #   duration_seconds, total_bytes_stored

# sdd/artifacts/plan/validator.py
def validate_plan(plan, tool_manager=None, *, check_guards=True) -> ValidationReport  # :112
class ValidationReport:   # :70 — .issues/.errors/.warnings/.ok/.raise_for_errors()
class ValidationIssue:    # :48 — node_id, code, message, severity
class PlanValidationError(ValueError)  # :101

# sdd/artifacts/plan/compile.py
PLAN_NODE_TYPE = "tool"; START_NODE_ID = "__start__"; END_NODE_ID = "__end__"  # :33-35
def to_flow_definition(plan: ExecutionPlan) -> FlowDefinition  # :38 — edges condition="always"
def ensure_tool_node_registered(node_cls) -> None  # :141 — idempotent; raises on conflict

# sdd/artifacts/plan/node.py
class PlanToolNode(_BaseNode):  # :60 — fields: plan_node, tool_manager,
                                #   working_memory, dependencies, successors,
                                #   permission_context; frozen Pydantic
    async def execute(self, ctx, deps=None, **kwargs) -> ArtifactRef  # :123
MAX_RECORDED_ERRORS = 20  # :47
# also exported: make_tool_node_factory, build_manifest, ToolExecutionError
# _resolve_args (:290) resolves EXACTLY three placeholder families:
#   {nodes.<id>.output} | {artifacts.<id>} | {item}/{item.<field>}/{index}
#   Exact-match placeholder → native value; embedded → text interpolation.
```

#### Plan grammar artifacts

- `sdd/artifacts/execution_plan.schema.json` — verified byte-equivalent to
  `ExecutionPlan.model_json_schema()`. Dual role: planner structured-output
  schema AND validation contract for `plans_dir` files.
- `sdd/artifacts/example_plan.json` — 4-node `daily_security_sweep`;
  its `"date": "{input}"` is UNSUPPORTED (see Does NOT Exist) and must be
  migrated to `{params.date}` in Module 3.

#### Flow engine — `packages/ai-parrot/src/parrot/bots/flows/flow/flow.py`

```python
# from_definition REQUIRES agent_registry unconditionally, even with zero
# agent nodes — the toolkit passes an empty registry:            :494-498
# node_factories: dict[str, Callable[[NodeDefinition, set, set], Node]]
#   closures carry live deps (manager, WM) that cannot travel via config
async def run_flow(ctx, *, on_complete=())          # :896
async def suspend(self) -> FlowCheckpoint           # :1046 (FEAT-399)
async def resume(...)                               # :1074
# registered node types: "decision" :1791, "interactive_decision",
#   "synthesis"; "agent"/"start"/"end" :2027-2029. NO "tool" entry.
# node return value goes VERBATIM into ctx.mark_completed(...)  :~1718
```

#### ToolManager — `packages/ai-parrot/src/parrot/tools/manager.py`

```python
async def execute_tool(tool_name, parameters, permission_context=None) -> Any  # :1431 (main cited 1422)
# unknown tool → returns ToolResult(status='not_found'), does NOT raise  # :1455
# result.status == "error" ⇒ raise ValueError(result.error)  # :1594/:1614 (main cited 1545-1565)
def get_tool(tool_name) -> Optional[Any]   # ~:1118
def list_tools() -> List[str]              # ~:1142
```

#### Tools / WorkingMemory / CEL / crew ToolNode / mixin pattern

```python
# packages/ai-parrot/src/parrot/tools/abstract.py
args_schema: Type[BaseModel] = AbstractToolArgsSchema   # :251

# packages/ai-parrot/src/parrot/tools/working_memory/tool.py
async def store_result(key, data, data_type="auto", description="", metadata=None, turn_id=None)  # :208

# packages/ai-parrot/src/parrot/tools/working_memory/internals.py
class WorkingMemoryCatalog:   # :458 — plain dict: no TTL, no lock, no persistence

# packages/ai-parrot/src/parrot/bots/flows/flow/cel_evaluator.py
# CELPredicateEvaluator(expr); __call__(result, error=None, **ctx) — fail-safe False

# packages/ai-parrot/src/parrot/bots/flows/crew/tool_node.py
class ToolNode(Node):  # :168 — NOT reused: calls tool.execute() directly and
#   serializes payloads into ctx.results (both violate this design)

# packages/ai-parrot/src/parrot/bots/mixins/model_switching.py
secondary_llm: Union[str, dict, AbstractClient, None] = None  # :92 —
#   accepted-formats pattern to copy for planner_llm
```

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `ExecutionPlanToolkit` | `validate_plan()` | direct call, allowlist issues appended | `sdd/artifacts/plan/validator.py:112` |
| `ExecutionPlanToolkit` | `AgentsFlow.from_definition` | empty `AgentRegistry` + `node_factories={"tool": ...}` | `flow.py:494-498` |
| `PlanToolNode` | `ToolManager.execute_tool` | per-node dispatch, catches `ValueError` | `manager.py:1431/:1614` |
| `PlanToolNode` | `WorkingMemoryToolkit.store_result` | payload storage under plan keys | `working_memory/tool.py:208` |
| `PlanPlanner` | `AbstractClient` impls | `planner_llm` format resolution | `model_switching.py:92` (pattern) |
| `ensure_tool_node_registered` | `NODE_REGISTRY` | idempotent registration | `sdd/artifacts/plan/compile.py:141` |

### Does NOT Exist (Anti-Hallucination)

- ~~`NODE_REGISTRY["tool"]`~~ — not registered on `dev` (grep-verified);
  added only via `ensure_tool_node_registered(PlanToolNode)`.
- ~~`parrot/bots/flows/plan/`~~ — not in the package yet; source of truth is
  `sdd/artifacts/plan/` (do NOT ship `_shim.py`).
- ~~`{input}` / `{params.*}` resolution in `PlanToolNode`~~ — the executor
  resolves ONLY the three families listed above (node.py:290-328).
  `{params.<name>}` exists ONLY as load-time substitution in
  `PlanFileStore`, before `model_validate`. Do NOT extend `_resolve_args`.
- ~~`agent.add_system_prompt()`~~ — does not exist
  (`parrot_tools/whatif_toolkit.py:862` calls it; silent no-op). Real
  paths: `PromptBuilder` layers or `ask(system_prompt=…)` (bots/base.py:931).
- ~~`BedrockConverseClient.ask(max_iterations=…)`~~ — no such kwarg; its
  tool loop is unbounded (clients/bedrock.py:738). Out of scope here.
- ~~persistent backend for `WorkingMemoryCatalog`~~ — none; v1 ships
  without one (explicit decision, no guardrail).
- `BasicAgent._inject_answer_memory_into_toolkits()` (bots/agent.py:145)
  never matches wrapped `ToolkitTool`s — do NOT rely on it to share the WM
  instance; constructor injection is the mechanism.
- ~~`FilterLevel.AGGRESSIVE` implementation~~ / ~~`CompressionReport` wired
  to `ToolManager`~~ — declared but unimplemented/unwired; irrelevant here
  (no LLM in the loop).

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- Tool convention: `.agent/workflows/create-parrot-tool.md` —
  `AbstractToolArgsSchema` per tool, `ToolResult` returns, docstrings become
  LLM tool descriptions (keep them short; the whole point is a small prompt
  surface).
- Toolkit-with-shared-state pattern: FEAT-207 (`SkillFileToolkit` /
  `SkillRegistryToolkit`) — one toolkit instance, registry shared across
  its tools; never instantiate the tools individually.
- Live dependencies travel through closures (`node_factories`), never
  through `NodeDefinition.config` — same rule the flow engine already
  documents.
- Async-first: tools here are I/O-bound ⇒ `asyncio.gather`/`create_task`,
  NOT `asyncio.to_thread`. The frozen node already bounds fan-out with
  `asyncio.Semaphore(max_concurrency)`; the flow scheduler already
  dispatches incrementally.
- Pydantic v2 `extra="forbid"` on all new models; Google-style docstrings;
  `self.logger`, never `print`.

### Known Risks / Gotchas

- **RAM pressure**: fan-out over 100s-of-MB reports lives entirely in the
  in-RAM `WorkingMemoryCatalog` for the whole pipeline — accepted v1 risk
  (explicit decision, no guardrail). `bytes_stored`/`total_bytes_stored`
  make cost visible. Persistent backend is a follow-up feature.
- **`WorkingMemoryCatalog` is a lock-free dict** — safe while all writes
  stay on one event loop (they do: pure asyncio). If any write path ever
  moves to threads, it needs a lock first.
- **Process restart** loses the in-RAM run registry (accepted): re-issuing
  the plan redoes only missing work via `skip_existing`. Do not promise
  `plan_resume` in docs.
- **`ToolManager.execute_tool` raises `ValueError` on tool error**
  (manager.py:1614) — `PlanToolNode` catches per-node/per-item; the toolkit
  must NOT add another try/except layer that converts manifests to errors.
- **Guarded skips don't block dependents**: plan edges are
  `condition="always"` by design; a `skipped` `ArtifactRef` flows onward.
  Don't "fix" this.
- **`ensure_tool_node_registered` raises on a conflicting `"tool"`
  registration** — call it lazily (first compile), never at import time,
  to keep import order irrelevant.
- **Soft-timeout must not cancel the run** — on timeout the task keeps
  running; only the tool response shape changes.
- **Planner cost ceiling**: exactly 1 authoring call + ≤1 repair call.
  Execution replan is the agent's decision, outside the tool (Axis 5).

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| (none new) | — | pydantic v2, `cel-python`, PyYAML already in the tree |

---

## Worktree Strategy

- **Default isolation unit**: `per-spec` — one worktree
  (`.claude/worktrees/feat-419-execution-plan-tool`), tasks sequential in
  dependency order (Module 1 → 2 → {3,4,5} → 6).
- Modules 3/4/5 are conceptually parallel but edit the same toolkit package
  and share Module 2's registry — keep them sequential in the single
  worktree; parallel worktrees would conflict on
  `parrot/tools/execution_plan/`.
- **Cross-feature dependencies**: none. Touches `NODE_REGISTRY` only
  additively. The Security Advisory work consumes this feature but is a
  separate spec.

---

## 8. Open Questions

Resolved in brainstorm (carried forward — decisions are reflected in the
body above):

- [x] Axis 1 — who writes the plan? — *Resolved in brainstorm*: hybrid
  (b)+(c): `objective` → internal planner LLM; `plan_name` → versioned repo
  file from `plans_dir`.
- [x] Axis 3 — block or `run_id`? — *Resolved in brainstorm*: hybrid
  soft-timeout (default 60 s, configurable), then background + `plan_status`.
- [x] Axis 4 — partial failure semantics — *Resolved in brainstorm*:
  manifest `partial` returned as success; tool errors only for structural
  failures.
- [x] Tool vs toolkit — *Resolved in brainstorm*: `AbstractToolkit` with
  `plan_execute` / `plan_status` / `plan_artifacts` / `plan_validate`.
- [x] Axis 6 — allowlist — *Resolved in brainstorm*: explicit
  `allowed_tools` in v1; doubles as the planner catalog (resolves Axis 2).
- [x] Axis 7 — WM lifecycle — *Resolved in brainstorm*: explicit
  constructor injection of the shared `WorkingMemoryToolkit`.
- [x] WM persistence — *Resolved in brainstorm*: follow-up feature, no v1
  guardrail; risk accepted and documented.
- [x] Axis 5 — replan — *Resolved in brainstorm*: outside the tool; one
  pre-execution planner repair round allowed.
- [x] Traceability — *Resolved in brainstorm*: `on_node_event` callback +
  manifest persisted in the run registry; wiki/`ReportRef` is follow-up.
- [x] Plan store location — *Resolved in brainstorm*: repo files under
  configurable `plans_dir` (YAML/JSON); DB backend v2.
- [x] Planner LLM config — *Resolved in brainstorm*: `planner_llm=`
  constructor arg, same formats as bots' `llm`; no implicit default.
- [x] `params` grammar — *Resolved in brainstorm*: plan grammar =
  `execution_plan.schema.json` (≡ `ExecutionPlan.model_json_schema()`);
  `{params.<name>}` load-time substitution in the store; missing/unused
  params fail the load; executor untouched.
- [x] `PermissionContext` — *Resolved in brainstorm*: deferred; v1 uses a
  constructor-level optional default forwarded to the node factory.

Resolved in this spec draft (defaults set — flag on review if wrong):

- [x] Run-registry bounds — *Resolved in spec*: `max_completed_runs=50`,
  evict oldest completed/failed; in-flight runs never evicted; no
  `max_concurrent_runs` cap in v1.
- [x] Cross-restart `plan_resume` — *Resolved in spec*: confirmed OUT of
  v1 (Non-Goal); `skip_existing` idempotence is the v1 recovery story.
- [x] Tool naming + `soft_timeout` default — *Resolved in spec*:
  `plan_execute` / `plan_status` / `plan_artifacts` / `plan_validate`;
  `soft_timeout=60.0`.

Still open:

- [ ] Should `plan_validate`'s dry-run response include the *generated*
  plan JSON verbatim in objective mode (useful for promoting ad-hoc plans
  to `plans_dir`), or only the `ValidationReport`? Leaning yes (it enables
  the save-and-promote workflow) — decide at implementation. — *Owner:
  implementation*

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-08-07 | Jesus Lara | Initial draft from brainstorm (Option D) |
