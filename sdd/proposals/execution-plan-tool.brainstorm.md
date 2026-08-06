---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Brainstorm: ExecutionPlanTool — deterministic tool-call DAGs for a BasicAgent

**Date**: 2026-08-07
**Author**: Jesus Lara
**Status**: exploration
**Recommended Option**: D (hybrid B+C, chosen by user in discovery)

---

## Problem Statement

Pipelines like the daily Security Advisory flow (list scanner reports in S3 →
parse each one → diff against the previous scan → map to SOC2/NIST controls)
execute dozens to hundreds of tool calls whose payloads (Prowler/Trivy/
CloudSploit reports, hundreds of MB) do not fit in any model's context window
— and which the model **does not need to see**: they only need to be
executed, stored, and analyzed afterwards.

The obvious solution — an LLM tool-by-tool loop — is worse on every axis: it
pays O(N²) input tokens (history is re-sent every iteration), it is
**inherently serial** (step k+1 cannot be emitted before step k finishes),
and it fails at runtime on unknown tools or invalid args.

The alternative this feature enables: a *thinking* model writes the complete
plan **once** as a structured spec (`ExecutionPlan`); code validates it
statically and executes it on `AgentsFlow` with **zero LLM tokens in the
loop**; payloads go to `WorkingMemory`; the same model later reads back the
artifacts under keys it chose itself.

The plan *execution* machinery already exists and is tested (60 tests, see
Code Context — the `plan/` module attached at `sdd/artifacts/plan/`, destined
for `packages/ai-parrot/src/parrot/bots/flows/plan/`). **This brainstorm is
only about the wrapper: the `AbstractToolkit` that lets a plain `BasicAgent`
trigger a plan, and how it integrates into an agent.** The `ExecutionPlan`
schema and the `PlanToolNode` executor are givens; their contracts are
constraints, not design space.

**Hard user requirement**: the invoking agent stays a normal `BasicAgent`.
It does NOT become a Flow or a Crew — it *invokes* a flow through a tool.

**Affected users**: developers building agents on ai-parrot; secondarily
ops/security people consuming the resulting reports.

**Success looks like**: zero LLM tokens during execution; payloads never in
context; the long-context analyst reads only what it decides to; a 300-report
run is resumable; an invalid plan fails at validation, never at node 47.

## Constraints & Requirements

- Python 3.10+, Pydantic v2, native async. No new dependencies: CEL
  (`cel-python`) is already in the tree.
- The invoking agent remains a `BasicAgent`; no changes to its base class.
- Invariants of the existing `plan/` module (MUST NOT be broken):
  1. No payload ever enters `FlowContext.results` or the tool response —
     only `ArtifactRef` (keys + facets + status + bytes) is published.
  2. Dispatch goes through `ToolManager.execute_tool()`, never
     `tool.execute()` directly.
  3. A plan is **tool-only by type**: `PlanNode` has no `agent_ref`, so
     agent→tool→flow→agent recursion is impossible by construction.
  4. Nothing truncates silently: exceeding `for_each.max_items` raises.
- Registering `"tool"` in `NODE_REGISTRY` must not break
  `AgentCrew.add_tool_node()`, which uses the crew `ToolNode` via another
  path (`ensure_tool_node_registered()` is idempotent and raises on a
  conflicting registration).
- The tool response must be bounded by construction (the example
  `ExecutionManifest` with 4 nodes and fan-out is <2 KB).
- Must follow the tool convention in `.agent/workflows/create-parrot-tool.md`
  (`AbstractTool` + `AbstractToolArgsSchema` + `ToolResult`, async
  `_execute`, pytest-asyncio tests).
- Tools in these pipelines are I/O-bound (S3, HTTP, Postgres) and the library
  is async top to bottom ⇒ `gather`/`create_task`, **not**
  `asyncio.to_thread` (which is only correct for later CPU-bound reduction,
  as `WorkingMemoryToolkit` already does with `thread_offload_cells`).

---

## Options Explored

All options share the same fixed backend pipeline (already built):
`validate_plan()` → `to_flow_definition()` → `AgentsFlow.from_definition()`
with a `node_factories["tool"]` closure carrying the live `ToolManager` +
`WorkingMemoryToolkit` → `run_flow()` → `build_manifest()`. They differ on
**Axis 1: who writes the `ExecutionPlan`**.

### Option A: The agent's own LLM emits the plan (plan-as-tool-args)

A single `execute_plan` tool whose `args_schema` embeds the full
`ExecutionPlan` JSON Schema. The agent's LLM authors the plan directly as
tool-call arguments; the tool validates and executes it.

✅ **Pros:**
- One model, zero extra LLM calls — no planner client to configure.
- The plan lives verbatim in the agent's own conversation, so the analyst
  phase literally sees the keys it wrote (the "planner names the artifacts"
  property holds trivially).
- Smallest implementation: no planner prompt, no plan store.

❌ **Cons:**
- The `ExecutionPlan` JSON Schema (~2.9K tokens) sits permanently in the
  agent's tool prompt, paid on every turn whether or not a plan is run.
- The plan competes with the agent's output window; a 300-node plan is a
  large single completion from a conversational model that may not have
  thinking enabled.
- Plan quality is tied to the agent's model config; you can't give planning
  a different (higher-thinking) model without switching the whole agent.

📊 **Effort:** Low–Medium

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| (none new) | — | pydantic v2 + cel-python already in tree |

🔗 **Existing Code to Reuse:**
- `sdd/artifacts/plan/` (→ `parrot/bots/flows/plan/`) — the whole pipeline.
- `parrot/tools/abstract.py` — `AbstractTool`, `args_schema` (line 251).

---

### Option B: `objective` in, internal planner LLM (plan-as-a-service)

The tool receives a natural-language `objective`; internally it calls a
dedicated planner client (configurable model, high thinking, structured
output = `ExecutionPlan`), validates, and executes. Matches the brief's
`[1] PLANNER — one call, thinking on` architecture box.

✅ **Pros:**
- The agent's tool prompt stays tiny — the 2.9K-token schema lives in the
  planner's request, paid only when a plan actually runs.
- Planner model/config is independent of the agent (thinking budget,
  provider, structured output) — same precedent as `ModelSwitchingMixin`'s
  `secondary_llm` and the LLM reranker (`parrot/rerankers/`): an LLM inside
  a non-agent component is an established parrot pattern.
- `ValidationReport` messages are "phrased so a planner model can correct
  the plan from it directly" (validator.py docstring) — enables one bounded
  internal repair round on validation failure.

❌ **Cons:**
- Every ad-hoc run pays one planner call (latency + cost).
- The agent never sees the plan body — the key map only comes back via the
  `ExecutionManifest` (which is sufficient, but the "analyst already has the
  map" property is now mediated by the manifest).
- An LLM inside a tool must be configured explicitly (who owns the client?).

📊 **Effort:** Medium

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| (none new) | — | planner uses existing `AbstractClient` implementations |

🔗 **Existing Code to Reuse:**
- `parrot/bots/mixins/model_switching.py:92` — `secondary_llm` accepted
  formats (`"provider:model"` | dict | `AbstractClient`) as the pattern for
  `planner_llm`.
- `sdd/artifacts/plan/validator.py` — `validate_plan()` report feeds the
  repair round.

---

### Option C: Persisted plans only (plan-as-configuration)

The tool receives a `plan_name` (+ optional `params`); plans are versioned
YAML/JSON files in a configurable `plans_dir`, validated on load, with
`params` substituted into declared placeholders.

✅ **Pros:**
- Zero planning cost per run; deterministic, auditable, git-diffable —
  ideal for the *daily scheduled* Security Advisory pipeline.
- No LLM inside the tool at all; the simplest possible failure surface.
- Plans get code review like any other artifact.

❌ **Cons:**
- Not adaptive: any new objective requires a human (or a separate session)
  to author a plan file first.
- Parameter substitution grammar is a mini-design of its own.
- Doesn't serve the exploratory/ad-hoc case at all.

📊 **Effort:** Low–Medium

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `PyYAML` | parse plan files | already a transitive dep in tree |

🔗 **Existing Code to Reuse:**
- `sdd/artifacts/plan/models.py` — `ExecutionPlan.model_validate()` on load.
- `parrot/bots/flows/flow/loader.py:226-233` — fail-fast predicate
  validation pattern for load-time checks.

---

### Option D: Hybrid B+C toolkit — `ExecutionPlanToolkit` ⭐

One `AbstractToolkit` exposing `plan_execute(objective=… | plan_name=…,
params=…)` plus `plan_status`, `plan_artifacts` and `plan_validate`.
`objective` routes to the internal planner (Option B); `plan_name` loads a
versioned plan file (Option C). Exactly one of the two must be provided.

✅ **Pros:**
- Covers both real usage modes in v1: persisted plan for the daily pipeline
  (auditable, zero planning cost), planner for ad-hoc objectives.
- The toolkit shape (shared state across tools) is required anyway by the
  async run registry — same pattern as `SkillFileToolkit` /
  `WorkingMemoryToolkit` (FEAT-207).
- A plan authored ad-hoc by the planner can be saved as a file and promoted
  to the persisted catalog later (natural v2: `plan_save`).

❌ **Cons:**
- Largest v1 surface: planner + plan store + run registry + 4 tools.
- Two entry modes means two documentation paths in the tool description
  (must stay short enough for the agent prompt).

📊 **Effort:** Medium

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| (none new) | — | pydantic v2, cel-python, PyYAML all in tree |

🔗 **Existing Code to Reuse:**
- Everything listed under A, B and C.
- `parrot/skills/` toolkits (FEAT-207) — the "toolkit initialized once with
  shared state" pattern.

---

## Recommendation

**Option D** — chosen explicitly by the user in discovery (Round 1) and
consistent with the tradeoffs above:

- The primary use case (daily Security Advisory) wants Option C's
  audit/diff/zero-cost properties; the exploratory case wants Option B. A
  hybrid costs little more than B alone because the plan store in v1 is
  just "load file → `ExecutionPlan.model_validate` → substitute params".
- Option A was rejected because the 2.9K-token schema would sit in the
  agent's tool prompt on every turn and the plan would compete with the
  agent's output window — the exact token overheads this design exists to
  remove.
- The toolkit surface is mandated by the async decision anyway (see below):
  `plan_status`/`plan_artifacts` need shared run state, which is what
  `AbstractToolkit` is for.

**Decisions locked in discovery (Rounds 0–3):**

| Axis | Decision |
|---|---|
| Axis 1 — plan author | Hybrid (b)+(c): `objective` → internal planner; `plan_name` → repo file |
| Axis 2 — tool catalog for planner | Resolved by Axis 6: catalog = allowlist ∩ `ToolManager` tools (name + description + `args_schema` summary) |
| Axis 3 — sync/async | Hybrid soft-timeout: block up to N seconds (default 60, configurable); if still running return `run_id` + partial counts; `plan_status` polls |
| Axis 4 — partial failure | Always return `ExecutionManifest` (status `completed\|partial\|failed`); tool-level error only for structural failures (invalid plan, unknown `run_id`, planner unconfigured) |
| Axis 5 — replan | Outside the tool: the agent reads the manifest errors and decides. (One bounded *pre-execution* planner repair round on validation failure is allowed — that is plan repair, not execution replan.) |
| Axis 6 — allowlist | Explicit `allowed_tools` in the toolkit constructor in v1; doubles as the planner catalog. Unset ⇒ all manager tools. |
| Axis 7 — WorkingMemory | Explicit constructor injection: `ExecutionPlanToolkit(tool_manager=…, working_memory=…)`; the developer guarantees executor and analyst share the instance |
| Surface | `AbstractToolkit` with `plan_execute`, `plan_status`, `plan_artifacts`, `plan_validate` |
| WM persistence | Follow-up feature, **no guardrail in v1** (user decision): v1 is pure in-RAM `WorkingMemoryCatalog`; `bytes_stored`/`total_bytes_stored` in the manifest give visibility; the pluggable spill-to-disk/S3 backend (pattern: `PostgresS3SecurityReportStore`) gets its own spec |
| Traceability | Toolkit accepts an `on_node_event` callback (re-emits `AgentsFlow` lifecycle events) + the final `ExecutionManifest` persists in the run registry, queryable via `plan_status` after completion. Execution-wiki / `ReportRef` integration is follow-up |
| Plan store (mode c) | Files in repo: configurable `plans_dir`, YAML/JSON, validated on load, `plan_name` = file name. DB backend is v2 |
| Planner LLM | `planner_llm=` constructor arg accepting the same formats as bots' `llm` (`"provider:model"` \| `AbstractClient` class/instance \| model_config dict), same as `secondary_llm`. No implicit default: unset + `objective` ⇒ clear error; only `plan_name` mode works |

---

## Feature Description

### User-Facing Behavior

A developer wires the toolkit into a plain `BasicAgent`:

```
toolkit = ExecutionPlanToolkit(
    tool_manager=agent.tool_manager,      # or a dedicated read-only manager
    working_memory=shared_wm_toolkit,     # SAME instance the analyst uses
    planner_llm="anthropic:claude-fable-5",   # optional; enables objective mode
    plans_dir="plans/",                   # optional; enables plan_name mode
    allowed_tools=["s3_filter_reports", "s3_get_latest_report", ...],
    soft_timeout=60.0,
    on_node_event=my_listener,            # optional telemetry hook
)
```

The agent's LLM then sees four small tools:

- **`plan_execute(objective=None, plan_name=None, params=None)`** — exactly
  one of `objective`/`plan_name`. Runs the plan. If it finishes within
  `soft_timeout`, returns the full `ExecutionManifest` (<2 KB by
  construction). Otherwise returns `{run_id, status: "running",
  nodes_total, nodes_done}` and execution continues in the background.
- **`plan_status(run_id)`** — progress counts while running; the final
  `ExecutionManifest` once done (kept in the run registry after
  completion).
- **`plan_artifacts(run_id)`** — the list of `ArtifactRef`s so far: the
  WorkingMemory key map the analyst reads from.
- **`plan_validate(objective=None, plan_name=None, params=None)`** —
  dry-run: generates/loads the plan, validates, returns the plan JSON plus
  the `ValidationReport` without executing anything.

The agent never sees a payload: it sees the manifest, decides which
WorkingMemory keys to rehydrate through the analyst-side WM tools, and — on
`partial` — decides itself whether to re-invoke `plan_execute` with a
corrective objective (Axis 5: replan lives outside).

### Internal Behavior

`plan_execute` pipeline (all code, LLM only in step 1a):

1. **Acquire the plan.**
   - (a) `objective` mode: build the planner prompt from the tool catalog
     (allowlist ∩ manager: name, description, `args_schema` summary per
     tool) + the objective; one structured-output call on the configured
     `planner_llm` → `ExecutionPlan`. If validation (step 2) fails, one
     bounded repair round: re-prompt with the `ValidationReport` (whose
     messages are written for exactly this), then give up with a structural
     error.
   - (b) `plan_name` mode: load `plans_dir/<plan_name>.(yaml|json)`,
     substitute `params` into declared placeholders,
     `ExecutionPlan.model_validate()`.
2. **Validate** — `validate_plan(plan, tool_manager)` plus the toolkit's
   allowlist check layered as extra `ValidationIssue`s (`tool_not_allowed`).
   All issues reported in one pass; errors block execution.
3. **Compile** — `ensure_tool_node_registered(PlanToolNode)` (idempotent),
   `to_flow_definition(plan)`.
4. **Execute** — `AgentsFlow.from_definition(definition,
   agent_registry=<empty registry>, node_factories={"tool":
   make_tool_node_factory(tool_manager, working_memory,
   permission_context)})`, then `run_flow(ctx)` as an `asyncio.Task`
   registered in the run registry under a fresh `run_id`. `plan_execute`
   awaits the task with `asyncio.wait_for`-style soft timeout; on timeout it
   returns the running summary instead of cancelling.
5. **Manifest** — on completion, `build_manifest()` produces the
   `ExecutionManifest`; the run registry keeps it (bounded registry:
   evict oldest completed runs beyond a cap).

The run registry is toolkit-instance state shared by all four tools — the
FEAT-207 shared-registry pattern. `on_node_event` listeners attach to the
flow before `run_flow` for live telemetry.

Permission propagation: the `permission_context` reaching the toolkit's own
execution is forwarded into `make_tool_node_factory` so every planned tool
call goes through `ToolManager.execute_tool(..., permission_context=...)`
with the same Layer-2 enforcement as a direct agent call.

### Edge Cases & Error Handling

- **Both or neither of `objective`/`plan_name`** → immediate `ToolResult`
  error with usage guidance (no LLM call spent).
- **`objective` without `planner_llm` configured** → clear structural error
  naming the missing constructor arg; `plan_name` mode unaffected.
- **Planner emits an invalid plan** → Pydantic/`validate_plan` errors feed
  one repair round; second failure returns the full `ValidationReport` as
  the tool error so the *agent* can adjust the objective (transparency over
  hidden loops).
- **Plan references a tool outside the allowlist** → `tool_not_allowed`
  validation error *before* execution — even if the tool exists in a shared
  `ToolManager`. This is the defense for the read-only Security analyst
  invariant (`tests/test_security_advisor.py`).
- **3 of 300 nodes fail** → manifest `status="partial"`, per-node errors
  inside (capped: `MAX_RECORDED_ERRORS=20`, 300 chars each). The tool call
  itself SUCCEEDS. `PlanToolNode` already catches the `ValueError` that
  `ToolManager.execute_tool` raises on `status=="error"` (manager.py:1614)
  — that is its contract.
- **Unknown `run_id`** in `plan_status`/`plan_artifacts` → tool error listing
  currently known run ids.
- **Agent never polls a background run** → run finishes anyway; registry
  keeps the manifest until evicted by the cap. Artifacts stay in
  WorkingMemory regardless (cleanup is the WM owner's concern — Axis 7:
  whoever injected the shared instance).
- **Process restart mid-run** → v1 loses the in-RAM run registry; the flow's
  checkpoint metadata (`PlanMetadata.checkpoint=True` →
  `FlowMetadata.checkpoint`) plus `ForEach.skip_existing` idempotence mean a
  re-issued `plan_execute` of the same plan only redoes missing work.
  Cross-restart `plan_resume(run_id)` is an open question (v2).
- **RAM pressure from fan-out** → known, accepted v1 risk (user decision:
  no guardrail). The manifest's `bytes_stored`/`total_bytes_stored` make
  the cost visible; the persistent-WM follow-up feature removes it.
- **Guard evaluates false** → node publishes a `skipped` `ArtifactRef`;
  dependents still dispatch (edges are `condition="always"` by design).

---

## Capabilities

### New Capabilities
- `execution-plan-tool`: `ExecutionPlanToolkit` (plan_execute / plan_status /
  plan_artifacts / plan_validate) wrapping the `plan/` module for
  `BasicAgent` integration, including the in-repo plan file store, the
  internal planner client, the allowlist, and the run registry. Also covers
  landing the attached `plan/` module at
  `packages/ai-parrot/src/parrot/bots/flows/plan/` with its 60 tests.

### Modified Capabilities
- (none — `NODE_REGISTRY` gains a `"tool"` entry via the idempotent
  `ensure_tool_node_registered()`, without touching existing node types or
  `AgentCrew.add_tool_node()`.)

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `parrot/bots/flows/plan/` (new) | adds | Drop-in of the attached, tested module (`sdd/artifacts/plan/`, minus `_shim.py` which only exists for standalone testing) |
| `parrot/tools/execution_plan/` (new) | adds | The `ExecutionPlanToolkit` per `.agent/workflows/create-parrot-tool.md` conventions |
| `parrot/bots/flows/flow/flow.py` `NODE_REGISTRY` | extends | `"tool"` registered lazily via `ensure_tool_node_registered()`; no existing registration touched |
| `AgentsFlow.from_definition` | depends on | Requires an `agent_registry` even for agent-free plans (flow.py:494-498) — toolkit passes an empty registry; no core change in v1 |
| `ToolManager` | depends on | All dispatch via `execute_tool` (manager.py:1431) with `permission_context` forwarded |
| `WorkingMemoryToolkit` | depends on | Shared instance injected by constructor (Axis 7); catalog stays in-RAM in v1 |
| Security Advisory pipeline | consumer | First user: daily plan as a versioned file in `plans_dir` |
| `AgentCrew.add_tool_node()` | unaffected | Uses crew `ToolNode` directly, not `NODE_REGISTRY` |

**Related cheap fixes (independent tasks, NOT designed here):**
`BedrockConverseClient.ask()` unbounded `while True:` tool loop (no
`max_iterations`, clients/bedrock.py:738), and
`BasicAgent._inject_answer_memory_into_toolkits()` never matching wrapped
`ToolkitTool`s (bots/agent.py:145). Both worth their own small tasks.

**Follow-up features (out of scope here):** pluggable persistent
`WorkingMemory` backend (spill to disk/S3 + Postgres index, pattern
`PostgresS3SecurityReportStore`); cross-restart `plan_resume`; DB-backed
plan store; execution-wiki / `ReportRef` traceability integration.

---

## Code Context

Line numbers verified on `dev` on 2026-08-07 (the user's brief was verified
on `main`; drift noted where found).

### User-Provided Code

```python
# Source: user-provided (brief) — for_each node example, matches models.py
{
  "id": "parse_all",
  "for_each": "$.list_reports.output.keys[*]",   # brief sketch; the real
  "tool": "s3_get_latest_report",                # syntax is ForEach(source=
  "args": {"key": "{item}"},                     # "{artifacts.list}", select="keys[]")
  "store_as": "report_{index}",
  "max_concurrency": 8
}
```

### Verified Codebase References

#### The attached plan module (source of truth: `sdd/artifacts/plan/`, destination `parrot/bots/flows/plan/`)
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
class ValidationReport:   # :70 — .issues / .errors / .warnings / .ok / .raise_for_errors()
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
```

#### Flow engine (`packages/ai-parrot/src/parrot/bots/flows/flow/flow.py`)
```python
# from_definition REQUIRES agent_registry unconditionally, even with zero
# agent nodes — the toolkit must pass an empty registry:            :494-498
# node_factories: dict[str, Callable[[NodeDefinition, set, set], Node]]
#   "close over live dependencies … that cannot travel through config"
async def suspend(self) -> FlowCheckpoint          # :1046  (FEAT-399)
async def resume(...)                              # :1074
# registered node types: "decision" :1791, "interactive_decision",
#   "synthesis", and "agent"/"start"/"end" :2027-2029.
# run_flow(ctx, *, on_complete=()) :896; scheduler = create_task per node,
#   incremental dispatch; node return value goes VERBATIM into
#   ctx.mark_completed(nid, result=event.result) :1718
```

#### ToolManager (`packages/ai-parrot/src/parrot/tools/manager.py`)
```python
async def execute_tool(tool_name, parameters, permission_context=None) -> Any  # :1431 (main: 1422)
# unknown tool → returns ToolResult(status='not_found'), does NOT raise  # :1455
# result.status == "error" ⇒ raise ValueError(result.error)   # :1594/:1614 (main: 1545-1565)
def get_tool(tool_name) -> Optional[Any]   # ~:1118
def list_tools() -> List[str]              # ~:1142
```

#### Tools / WorkingMemory / CEL / crew ToolNode
```python
# packages/ai-parrot/src/parrot/tools/abstract.py
args_schema: Type[BaseModel] = AbstractToolArgsSchema   # :251 — static arg validation

# packages/ai-parrot/src/parrot/tools/working_memory/tool.py
async def store_result(key, data, data_type="auto", description="", metadata=None, turn_id=None)  # :208
# get_result(include_raw=True) returns entry.data WHOLE, uncapped  # :280-288 (main)

# packages/ai-parrot/src/parrot/tools/working_memory/internals.py
class WorkingMemoryCatalog:   # :458 — plain dict: no TTL, no lock, no persistence

# packages/ai-parrot/src/parrot/bots/flows/flow/cel_evaluator.py
# CELPredicateEvaluator(expr); __call__(result, error=None, **ctx) — celpy; fail-safe False

# packages/ai-parrot/src/parrot/bots/flows/crew/tool_node.py
class ToolNode(Node):  # :168 — NOT reused as-is: _invoke() calls
#   self.tool.execute() directly (skips manager/hooks/permissions) and
#   extract_tool_output() serialises the payload into ctx.results

# packages/ai-parrot/src/parrot/bots/mixins/model_switching.py
secondary_llm: Union[str, dict, AbstractClient, None] = None  # :92 —
#   the accepted-formats pattern to copy for planner_llm
```

#### Verified Imports
```python
from parrot.bots.flows.flow.definition import (   # used by compile.py
    EdgeDefinition, FlowDefinition, FlowMetadata, NodeDefinition,
)
from parrot.bots.flows.flow.flow import NODE_REGISTRY, register_node
from parrot.bots.flows.core.node import Node      # PlanToolNode base
from parrot.bots.flows.core.fsm import AgentTaskMachine
from ..abstract import AbstractTool, AbstractToolArgsSchema, ToolResult  # tool convention
```

### Does NOT Exist (Anti-Hallucination)

- ~~`NODE_REGISTRY["tool"]`~~ — `"tool"` is NOT registered (grep-verified on
  dev); must be added via `ensure_tool_node_registered(PlanToolNode)`.
- ~~`parrot/bots/flows/plan/`~~ — the module is NOT in the package yet; it
  lives at `sdd/artifacts/plan/` (with a `_shim.py` used only for
  standalone tests — do not ship the shim).
- ~~`agent.add_system_prompt()`~~ — does not exist;
  `parrot_tools/whatif_toolkit.py:862` calls it and it is a silent no-op.
  Real paths: `PromptBuilder` `PromptLayer`, or `ask(system_prompt=…)`
  (bots/base.py:931).
- ~~`BedrockConverseClient.ask(max_iterations=…)`~~ — its tool loop is
  `while True:` with no cap (clients/bedrock.py:738). `bots/base.py:1292-1304`
  only forwards the kwarg if the client declares it.
- ~~persistent backend for `WorkingMemoryCatalog`~~ — none exists; v1 ships
  without one (explicit user decision).
- ~~`FilterLevel.AGGRESSIVE` implementation~~ — declared
  (tools/compression/levels.py:30) but no codec implements it. Irrelevant
  here anyway: no LLM in the execution loop.
- `BasicAgent._inject_answer_memory_into_toolkits()` (bots/agent.py:145)
  does `isinstance(tool, WorkingMemoryToolkit)` on `ToolkitTool` wrappers
  and **never matches** — do NOT rely on it to share the WM instance; the
  constructor-injection decision (Axis 7) exists partly because of this.
- ~~`CompressionReport` wired to `ToolManager`~~ — not wired (its own
  docstring says so).

---

## Parallelism Assessment

- **Internal parallelism**: Low. The natural task split is sequential:
  (1) land `plan/` module + its 60 tests in the package, (2) toolkit
  skeleton + run registry, (3) plan store (`plans_dir`), (4) planner client
  + repair round, (5) allowlist + permission propagation, (6) integration
  test with a `BasicAgent`. Tasks 3–5 all edit the same toolkit module;
  parallel worktrees would conflict.
- **Cross-feature independence**: No conflicts with in-flight specs
  detected. Touches `NODE_REGISTRY` only additively (new `"tool"` key);
  FEAT-417 (commcenter-notify) is unrelated. The Security Advisory
  proposal consumes this feature but does not modify the same files.
- **Recommended isolation**: `per-spec` — one worktree, tasks in
  dependency order.
- **Rationale**: single new module cluster with a hard internal dependency
  chain (toolkit depends on the landed `plan/` module); splitting across
  worktrees buys nothing and risks divergence on the shared toolkit file.

(Runtime parallelism — distinct from development parallelism — needs no new
code: `run_flow()` already dispatches `asyncio.create_task` per node
incrementally, and `PlanToolNode` bounds fan-out with
`asyncio.Semaphore(max_concurrency)`. I/O-bound tools ⇒ pure asyncio, no
`to_thread`. `WorkingMemoryCatalog` is a lock-free dict — safe on one event
loop; if any write path ever moves to threads, it needs a lock.)

---

## Open Questions

- [x] Axis 1 — who writes the plan? — *Owner: jesuslara*: Hybrid (b)+(c);
  `objective` → internal planner LLM, `plan_name` → versioned repo file.
- [x] Axis 3 — block or `run_id`? — *Owner: jesuslara*: hybrid soft-timeout
  (default 60 s, configurable), then background + `plan_status`.
- [x] Axis 4 — partial failure semantics — *Owner: jesuslara*: manifest
  `partial` returned as success; tool errors only for structural failures.
- [x] Tool vs toolkit — *Owner: jesuslara*: `AbstractToolkit` with
  `plan_execute` / `plan_status` / `plan_artifacts` / `plan_validate`.
- [x] Axis 6 — allowlist — *Owner: jesuslara*: explicit `allowed_tools` in
  v1; doubles as the planner catalog (resolves Axis 2).
- [x] Axis 7 — WM lifecycle — *Owner: jesuslara*: explicit constructor
  injection of the shared `WorkingMemoryToolkit`.
- [x] WM persistence — *Owner: jesuslara*: follow-up feature, no v1
  guardrail; risk accepted and documented.
- [x] Axis 5 — replan — *Owner: jesuslara*: outside the tool; agent decides
  from the manifest. One pre-execution planner repair round allowed.
- [x] Traceability — *Owner: jesuslara*: `on_node_event` callback + manifest
  persisted in the run registry; wiki/ReportRef is follow-up.
- [x] Plan store location — *Owner: jesuslara*: repo files under a
  configurable `plans_dir` (YAML/JSON); DB backend v2.
- [x] Planner LLM config — *Owner: jesuslara*: `planner_llm=` constructor
  arg, same formats as bots' `llm`; no implicit default.
- [ ] `params` substitution grammar for persisted plans (which fields are
  parameterizable, escaping, missing-param behavior) — *Owner: spec phase*
- [ ] Run-registry bounds: max retained runs / eviction policy, and whether
  a `max_concurrent_runs` cap is needed in v1 — *Owner: spec phase*
- [ ] How the toolkit obtains the invoking agent's `PermissionContext` at
  call time (per-call forwarding vs constructor default) — *Owner: spec
  phase, check ToolkitTool dispatch path*
- [ ] Cross-restart `plan_resume(run_id)` on top of FEAT-399 checkpoints —
  v2 candidate; confirm it stays out of v1 — *Owner: jesuslara*
- [ ] Exact tool names (`plan_execute` vs `execute_plan` prefix convention)
  and default `soft_timeout` value — *Owner: spec phase*
