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
# Also register `working_memory` with the agent so the analyst can read back
# artifacts under the keys the plan chose. `BasicAgent` auto-injects its
# `answer_memory` into the toolkit once (FEAT-585); an explicit
# `WorkingMemoryToolkit(answer_memory=...)` still takes precedence.
agent.tool_manager.register_tool(working_memory)
```

### Recovery inputs (FEAT-585)

| Keyword | Type | Meaning |
|---|---|---|
| `recovery` | `PlanRecoveryConfig \| None` | `max_repair_rounds` (0–2, default 2, host-only), `max_restore_bytes` (64 MiB), `checkpoint_probe_timeout` (2.0 s). `None` = defaults. |
| `checkpoint_store` | `CheckpointStore \| str \| None` | Ephemeral tier (e.g. `"redis"`). `None` = no checkpointing; runs report `resume_level: "none"`. |
| `durable_store` | `CheckpointStore \| str \| None` | Durable tier (`"sqlite"`/`"postgres"`/`"mongodb"`). Required for `cross_restart`. |
| `task_memory_runtime` | `TaskMemoryRuntime \| None` | An already-started runtime to share; with `scope` it enables durable artifacts. Borrowed, never closed. |
| `scope` | `TaskScope \| None` | Trusted host scope. A durable runtime without a scope is a configuration error. |

Without any of these inputs, the toolkit uses in-memory plan memory, process-local scope, and fresh execution — no checkpointing, no cross-process recovery.

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

### `plan_resume(run_id)`

Continue an interrupted **checkpointed** run — in this process or, with a durable tier and a
host-supplied scope, in a fresh one. Completed nodes are never re-dispatched; their exact
`artifact_id@version` evidence is restored under a host-only byte budget. Never calls a
planner. Refuses with `run_not_resumable`, `checkpoint_unavailable`, `artifacts_unavailable`,
`scope_mismatch`, `policy_mismatch` or `run_busy`.

### `plan_repair(run_id)`

Spend **one** repair attempt on a terminal `failed`/`partial` run: the planner may replace only
nodes that errored or were never dispatched (never `ok`/`skipped`/`partial` nodes, never new
ids), the delta is validated against the original allowlist ∩ current policy, and the child
run inherits every successful result. At most one structural correction call per attempt;
the attempt is persisted **before** the planner is called, so a crash consumes it.
Refuses with `no_repairable_nodes`, `repair_limit_reached`, `planner_unavailable`,
`run_not_repairable`, `delta_invalid`, `repair_interrupted` or `run_busy`.

All four run tools (`plan_status`, `plan_artifacts`, `plan_resume`, `plan_repair`) return the
recovery envelope: `run_id`, `root_run_id`, `parent_run_id`, `checkpoint_enabled`,
`artifact_mode`, `resume_level`, `resumable`, `recovery_reason`, `repair_attempts_used`,
`max_repair_rounds`, `active_child_run_id`.

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

## Recovery model (FEAT-585)

| Checkpoints acknowledged | Artifact configuration | `resume_level` | Fresh-process `plan_resume` |
|---|---|---|---|
| No | any | `none` | refused: `checkpoint_unavailable` |
| Yes | in-memory / process-local scope | `process` | refused: `artifacts_unavailable` |
| Yes | durable backend + stable trusted scope | `cross_restart` | allowed after validation and lease acquisition |

**Unknown vs missing_or_expired**: When a run ID is not found, the error code depends on the configured store tiers:
- If a durable store is configured and `latest(run_id)` returns `None`, the run was never durably recorded (durable storage has no TTL), so the code is `unknown_run`.
- If only an ephemeral store (Redis) is configured, the run may have expired after 24 hours (the default `FLOW_CHECKPOINT_REDIS_TTL`). Since no evidence remains, the code is `missing_or_expired`.

**Lineage**: Every run has a `root_run_id` (the original run) and `parent_run_id` (the run that spawned this continuation). Repair creates a child run with its own ID; the parent records the child ID. When resolving a run, the toolkit traverses the lineage chain to find the latest consolidated result. The manifest counters are recomputed from the current state, not accumulated from parent + child.

**Error codes**: The toolkit returns these stable error codes:

| Code | Meaning |
|---|---|
| `unknown_run` | Durable store configured but no checkpoint exists for this run ID |
| `missing_or_expired` | Ephemeral-only store, or run expired from Redis |
| `checkpoint_unavailable` | No checkpoint store configured at all |
| `checkpoint_invalid` | Checkpoint data is corrupted or schema-mismatched |
| `checkpoint_write_failed` | Persistence failed mid-run; progress reported |
| `run_busy` | Another continuation is already in progress on this run |
| `run_not_resumable` | Run is completed, or lease cannot be acquired |
| `run_not_repairable` | Run is not in a terminal failed/partial state |
| `no_repairable_nodes` | No error nodes or undispatched nodes to replace |
| `repair_limit_reached` | `max_repair_rounds` exhausted (default 2) |
| `repair_interrupted` | Crash after attempt was reserved but before child dispatch |
| `delta_invalid` | Repair delta failed validation |
| `planner_unavailable` | No `planner_llm` configured for repair |
| `scope_mismatch` | Host scope does not match the run's scope |
| `policy_mismatch` | Current allowed tools are stricter than original |
| `artifacts_unavailable` | Process scope cannot access the artifacts |
| `artifact_alias_conflict` | Two restored artifacts claim the same key |
| `restore_budget_exceeded` | Exceeded 64 MiB restoration budget |

## Response schema migration

Terminal responses keep every `ExecutionManifest` key at the top level and **add** the
recovery envelope plus `status`. The frozen `parrot.bots.flows.plan.ExecutionManifest` is
unchanged and remains `extra="forbid"`, so a strict consumer that validated the raw JSON into
that model must now either select the manifest fields or validate into
`parrot.tools.execution_plan.PlanRunManifest`. The JSON is additive, not byte-identical.

## Caveats and limitations

- **`WorkingMemory` is in-RAM, with no guardrail.** Every payload a plan
  fetches — including a 300-item fan-out over hundreds of MB of scanner
  reports — lives in the process's memory for the whole run and beyond,
  until something explicitly drops it. There is no size cap, no eviction,
  no spill-to-disk. `bytes_stored` (per `ArtifactRef`) and
  `total_bytes_stored` (on the manifest) make the cost *visible*; they do
  not bound it. A persistent `WorkingMemory` backend is a separate,
  future feature. Plan memory (activated only for plans) uses versioned
  artifacts when a durable backend is configured.
- **Recovery is explicit.** Nothing resumes on its own after a restart; the agent calls
  `plan_resume(run_id)`. Without a checkpoint store, runs execute exactly as before and say so
  (`resume_level: "none"`).
- **No exactly-once for interrupted external calls.** A completed, checkpointed node is never
  replayed, but a tool invocation interrupted between its external effect and the checkpoint
  acknowledgement has no acknowledgement to consult. Such tools need their own idempotency
  contract; `for_each` nodes still get `skip_existing` on stored item keys.
- **Two different byte limits.** The analyst's raw-read ceiling (`max_rehydrate_bytes`, default
  2,000,000) bounds what `wm_get_result` returns; the executor's `max_restore_bytes` (64 MiB,
  host-only) bounds exact-version restoration during a continuation. Neither is a process RAM cap.
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
- `packages/ai-parrot/tests/tools/execution_plan/test_run_resolution.py` — run ID resolution, lineage traversal.
- `packages/ai-parrot/tests/tools/execution_plan/test_checkpoint_resume.py` — checkpoint restoration, cross-process resume.
- `packages/ai-parrot/tests/tools/execution_plan/test_runtime_repair.py` — repair delta validation, attempt accounting.
- `packages/ai-parrot/tests/tools/execution_plan/test_integration_recovery.py` — end-to-end recovery scenarios.
- `packages/ai-parrot/tests/tools/execution_plan/test_integration_repair.py` — end-to-end repair scenarios.
- `packages/ai-parrot/tests/tools/execution_plan/test_toolkit_owner.py` — answer-memory injection fix (FEAT-585).
- `packages/ai-parrot/tests/tools/execution_plan/test_toolkit_recovery.py` — recovery envelope fields.
