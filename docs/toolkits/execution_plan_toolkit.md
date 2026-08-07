# ExecutionPlanToolkit — Reference

**Feature**: FEAT-419
**Module**: `parrot/tools/execution_plan/`
**Class**: `ExecutionPlanToolkit(AbstractToolkit)`

---

## Overview

`ExecutionPlanToolkit` lets a plain `BasicAgent` run a deterministic
tool-call DAG (an `ExecutionPlan`) through one bounded tool call, with
**zero LLM tokens spent while the plan executes**. A *thinking* model (or a
versioned file) authors the plan once; the toolkit validates it statically
against the live `ToolManager`, compiles it to a `FlowDefinition`, and runs
it on `AgentsFlow`. Tool payloads never enter the agent's context — they
land in `WorkingMemory` under keys the plan itself chose, and only small,
bounded `ArtifactRef`s and an `ExecutionManifest` travel back.

The invoking agent stays a normal `BasicAgent`. It does **not** become a
Flow or a Crew — it *invokes* a flow through a tool.

This is the wrapper around the frozen `parrot.bots.flows.plan` module
(`ExecutionPlan`, `PlanNode`, `PlanToolNode`, `validate_plan`,
`to_flow_definition`, …) — that module's schema and executor semantics are
constraints, not design space, for anything built on top of it.

---

## Wiring

```python
from parrot.bots.agent import BasicAgent
from parrot.tools.execution_plan import ExecutionPlanToolkit
from parrot.tools.working_memory import WorkingMemoryToolkit

working_memory = WorkingMemoryToolkit()

toolkit = ExecutionPlanToolkit(
    tool_manager=agent.tool_manager,   # SAME manager the agent's other tools use
    working_memory=working_memory,     # SAME instance the analyst reads back from
    planner_llm="google:gemini-2.5-flash",  # enables `objective` mode; omit to disable it
    plans_dir="examples/plans",             # enables `plan_name` mode; omit to disable it
    allowed_tools=["s3_filter_reports", "s3_get_latest_report", "compare_scans"],
    soft_timeout=60.0,
)

agent.tool_manager.register_tool(toolkit)
# Also register `working_memory` with the agent so the analyst can read
# back artifacts under the keys the plan chose — constructor injection,
# never auto-detected: `BasicAgent._inject_answer_memory_into_toolkits()`
# does not match wrapped `ToolkitTool`s.
agent.tool_manager.register_tool(working_memory)
```

Both `planner_llm` and `plans_dir` are optional and independent — set
either, both, or neither. Neither one being set means the toolkit only
exposes `plan_status`/`plan_artifacts` (nothing to acquire a plan from).
`allowed_tools=None` (the default) means every tool registered on
`tool_manager` is allowed; setting it is both the security boundary (a plan
naming a tool outside the list fails validation before anything runs) and
the planner's tool catalog.

---

## Tools

### `plan_execute(objective=None, plan_name=None, params=None)`

Acquire → validate → compile → run. Exactly one of `objective` (planner-
authored) or `plan_name` (versioned file under `plans_dir`) must be given.

- **`objective` mode**: the toolkit's internal `PlanPlanner` makes one
  structured-output LLM call to author the plan. If validation fails, the
  planner is re-prompted exactly once with the full `ValidationReport`
  (whose messages are written for this) — then the toolkit gives up.
- **`plan_name` mode**: loads `plans_dir/<plan_name>.(yaml|yml|json)` with
  load-time `{params.<name>}` substitution, then validates. **No repair
  round** — a persisted plan that fails validation is a broken file to fix,
  not something to patch at runtime.

Returns the full `ExecutionManifest` if the run finishes within
`soft_timeout`, else `{run_id, status: "running", nodes_total, nodes_done}`
while execution continues in the background — poll `plan_status(run_id)`.

**Failure semantics**: the manifest is *always* the success payload —
`status` is `completed | partial | failed` with per-node errors inside
(capped at 20). A plan that partially failed is data the agent inspects
and reacts to, not an exception. Tool-level errors are reserved for
structural failures: both/neither plan source given, `params` combined
with `objective`, `objective` without a configured `planner_llm`,
`plan_name` without a configured `plans_dir`, an unreadable plan file, and
**an invalid plan after the repair round** (nothing to run).

### `plan_status(run_id)`

Progress counts (`nodes_total`/`nodes_done`) while a run is still
executing; the final `ExecutionManifest` once it has finished.

### `plan_artifacts(run_id)`

The `ArtifactRef` list produced so far — the WorkingMemory key map the
analyst reads back from, available even while the run is still going.

### `plan_validate(objective=None, plan_name=None, params=None)`

Dry run: same arbitration, acquisition and (in `objective` mode) repair
round as `plan_execute`, but **never executes a tool**. Returns the
acquired plan JSON **verbatim** — including a planner-generated plan in
`objective` mode — plus the full `ValidationReport` (`ok` flag and every
issue's `node_id`/`code`/`message`/`severity`). Because the response
always includes the plan JSON, even when `ok` is `false`, this is also the
save-and-promote workflow: inspect what the planner produced, fix it by
hand if needed, and drop it into `plans_dir` as a new versioned
`plan_name`.

---

## The plan file + `{params.<name>}` contract

A `plan_name`-mode file is a plain YAML or JSON document matching
`ExecutionPlan.model_json_schema()` (see
`sdd/artifacts/execution_plan.schema.json`), with one addition: string
leaves may contain `{params.<name>}` placeholders, substituted **before**
validation:

- A leaf that is *exactly* one placeholder resolves to the parameter's
  native value (an `int` param stays an `int`).
- A leaf with an embedded placeholder is interpolated as text.
- Every placeholder in the file must have a matching key in `params`, and
  every key in `params` must be referenced somewhere in the file — nothing
  is silently missing or silently unused.

`{params.<name>}` is a **load-time-only** concept, handled entirely by
`PlanFileStore` before the plan ever reaches the executor. It is distinct
from — and never touches — the executor's own runtime placeholder
families, which are resolved per-node while the plan runs:

| Placeholder | Resolved by | When |
|---|---|---|
| `{params.<name>}` | `PlanFileStore.load()` | Load time, `plan_name` mode only |
| `{nodes.<id>.output}` | `PlanToolNode._resolve_args` | Runtime — the small published `ArtifactRef` |
| `{artifacts.<id>}` | `PlanToolNode._resolve_args` | Runtime — the full stored body (code reads it, never a model) |
| `{item}` / `{item.<field>}` / `{index}` | `PlanToolNode._resolve_args` | Runtime, inside a `for_each` node |

See `examples/plans/daily_security_sweep.json` for a complete example
(4-node plan: list reports → fan out and fetch each → diff against the
previous scan → map new findings to SOC2 controls), using `{params.date}`.

```python
result = await toolkit.plan_execute(
    plan_name="daily_security_sweep",
    params={"date": "2026-08-06"},
)
```

---

## Soft-timeout / `run_id` flow

`plan_execute` waits up to `soft_timeout` seconds (default `60.0`) for the
run to finish. If it finishes in time, the full manifest comes back
directly. If not, the run keeps going in the background — the timeout
**never cancels it** — and the tool call returns a small summary instead:

```json
{"run_id": "run_ab12cd", "status": "running", "nodes_total": 4, "nodes_done": 1}
```

The agent then polls:

```python
status = await toolkit.plan_status(run_id="run_ab12cd")
# → RunningSummary again while it's still going, or the final
#   ExecutionManifest once it's done.
```

This is how a 300-item fan-out over minutes of wall-clock time coexists
with a normal per-tool-call timeout on the agent side.

---

## v1 caveats (read before relying on this in production)

- **`WorkingMemory` is in-RAM, with no guardrail.** Every payload a plan
  fetches — including a 300-item fan-out over hundreds of MB of scanner
  reports — lives in the process's memory for the whole run and beyond,
  until something explicitly drops it. There is no size cap, no eviction,
  no spill-to-disk. `bytes_stored` (per `ArtifactRef`) and
  `total_bytes_stored` (on the manifest) make the cost *visible*; they do
  not bound it. A persistent `WorkingMemory` backend is a separate,
  future feature.
- **The run registry is lost on a process restart.** `RunRecord`s and the
  live `asyncio.Task`s behind them are toolkit-instance state, not
  persisted anywhere. There is **no `plan_resume(run_id)`** — do not build
  workflows that assume one exists.
- **Recovery is re-issue + `skip_existing`, not resume.** If a process
  dies mid-run, re-issuing the *same* `plan_execute(plan_name=..., params=
  ...)` call redoes only the work that never got stored — every `for_each`
  node defaults to `skip_existing=True`, so a `store_as` key already
  present in `WorkingMemory` is not re-fetched. This is idempotence, not
  checkpoint/resume; a plan with no `for_each` nodes has no such recovery
  story and simply re-runs from the top.
- **Run-registry bounds**: completed/failed runs beyond
  `max_completed_runs` (default `50`) are evicted oldest-first. In-flight
  runs are never evicted, and there is no cap on concurrent runs in v1.
- **`allowed_tools=None` means "trust every tool on this `ToolManager`".**
  If the manager is shared with components that register tools you would
  not want a planner-authored plan to invoke, set `allowed_tools`
  explicitly.

---

## See also

- `sdd/specs/execution-plan-tool.spec.md` — the full design spec (FEAT-419).
- `parrot/bots/flows/plan/` — the frozen plan schema/validator/compiler/executor.
- `examples/plans/daily_security_sweep.json` — the shipped example plan.
- `packages/ai-parrot/tests/tools/execution_plan/test_integration.py` — the
  end-to-end proof (zero-token execution, resumable fan-out, allowlist
  enforcement, `AgentCrew.add_tool_node()` regression).
