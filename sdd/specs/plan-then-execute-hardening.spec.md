---
type: feature
base_branch: dev
projects: [ai-parrot, docs]
tags: [execution-plan, checkpointing, working-memory, replan, result-policy]
---

# Feature Specification: Plan-then-Execute Hardening

**Feature ID**: FEAT-585
**Date**: 2026-09-21
**Author**: Jesus Lara
**Status**: draft
**Target version**: next

Source of requirements: `sdd/proposals/plan-then-execute-hardening.brainstorm.md`, Option B.
Supporting evidence: `sdd/proposals/plan-then-execute-design-drift.findings.md` and
`sdd/proposals/handle-only-execution-design.input.md`.
This draft is not ready for task decomposition until the approval blockers in §8 are resolved.

## 1. Motivation & Business Requirements

### Problem Statement

FEAT-419 executes a statically validated tool DAG without an LLM in its execution loop,
but keeps its run registry in RAM and explicitly disables flow checkpoints. A process
restart loses the run identity, progress and catalog aliases. A failed plan cannot ask
for a bounded runtime delta. FEAT-538 implements bounded raw reads, but the example
plan wiring leaves that path disabled. Finally, BasicAgent's answer-memory injection
checks wrapped tools as though they were their owning toolkits, so injection does not happen.

### Goals

- D1: Only the agent's explicit `plan_repair` call invokes runtime replanning. Neither
  `plan_execute` execution nor `plan_resume` invokes a planner automatically.
- D2: A repair delta may replace only nodes with an error result or nodes never
  dispatched. It cannot add IDs or execute successful nodes again. Validate against
  the original allowlist and the current manager's permissions.
- D3–D5: Recover a run in a fresh process from its checkpoint, using an explicit
  `plan_resume(run_id)`. The checkpoint is the sole persisted execution state.
- D6–D8: Enable versioned artifacts and the raw-read ceiling on the memory used by
  a plan. Use configured durable artifacts when available; otherwise use memory.
  Missing Redis does not prevent fresh execution. Report actual recovery capability
  as structured data on every run response.
- D9: Fix answer-memory injection without a feature flag; preserve explicit wiring.
- Keep the invoking bot a BasicAgent, preserve soft timeouts, and return only
  manifests, references, progress and bounded errors to the model.
- Preserve the standalone disabled WorkingMemory contract of FEAT-538 AC13.

### Non-Goals (explicitly out of scope)

- Changes to `packages/ai-parrot/src/parrot/bots/flows/plan/`, including its models,
  validator, guards, compiler and argument-resolution semantics.
- Changes to `bots/flows/flow/flow.py`, the shared checkpoint package, or `clients/base.py`.
- Automatic startup recovery, automatic full-plan retries, arbitrary graph expansion,
  production Security Advisory migration, or new dependencies.
- Exactly-once external effects across a crash between tool execution and checkpoint
  acknowledgement. Completed checkpointed nodes must not replay; an interrupted
  tool invocation still requires its own idempotency contract.
- Repairing a `partial` fan-out result by silently treating it as `error`. D2 excludes
  that case; report `no_repairable_nodes` when no error/undispatched nodes exist.

## 2. Architectural Design

### Overview

Introduce a toolkit-local `PlanRunResolver` and immutable checkpoint metadata. Keep
`_runs` only as a bounded live cache and as the source of truth for non-checkpointed
execution. All four run operations (`plan_status`, `plan_artifacts`, `plan_resume`,
`plan_repair`) resolve through the same service. Persist no second RunRecord or
final manifest database. Derive manifests from typed node results, errors and the
effective plan embedded in checkpoint metadata.

Use a full UUID-based opaque run ID and give the same ID to its AgentsFlow. A repair
has a distinct child run/flow ID and immutable `root_run_id`/`parent_run_id` lineage.
The root checkpoint records the accepted repair attempt and child ID before any LLM
call or child dispatch. Root lookup follows this bounded chain and projects the latest
consolidated result. No side index is authoritative for execution state.

### Component Diagram

```text
BasicAgent -> ExecutionPlanToolkit -> PlanRunResolver -> checkpoints
                    |                       |
                    |                       +-> typed ArtifactRefs -> manifest
                    +-> plan_repair -> PlanPlanner -> delta validator
                    |                                  |
                    +-> PlanFlow <----------------------+
                          |   checkpointed completions + root lease
                          v
                 existing PlanToolNode -> ToolManager
                          |
                          v
                 shared WorkingMemory -> versioned artifact backend
                          |
                    bounded analyst reads
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| ExecutionPlanToolkit | extends | Two new tools; resolver-based status/artifacts; checkpoint-aware execution |
| PlanPlanner | extends | Separate runtime `replan`; existing structural `repair` remains distinct |
| BasicAgent / ToolManager | modifies | Share toolkit-owner discovery; preserve explicit answer memory |
| Frozen plan package | uses | Compile, validate, create tool nodes and build manifests unchanged |
| AgentsFlow / FEAT-399 | uses | Toolkit-local subclass/adapter, existing resume factory and lease APIs |
| WorkingMemoryToolkit | extends | Private plan-only activation hook; refresh existing get-result wrappers |
| WorkingMemoryCatalog | uses | Plan-specific subclass restores versioned entries; standalone catalog unchanged |
| TaskMemoryRuntime | uses | Reuse connected durable stores or own an in-memory runtime |
| Toolkit reference documentation | updates | Correct injection explanation and document recovery limitations |

### Checkpoint contract and recovery

`ContextSnapshot` can preserve ArtifactRefs, but they are not registered by the plan
package today. Register `ArtifactRef` process-wide through `register_checkpoint_type`
before writing OR reading plan checkpoints. Use the existing default qualified type
tag; never invent a second serializer or pickle payloads. Decode results with
`FlowStateSerializer.from_safe` and require the expected type. Reject lossy or malformed
plan state with `checkpoint_invalid`; do not recover references from repr strings.

Persist a versioned JSON `plan_run` document in the allowlisted checkpoint shared-data
projection. It contains the effective validated ExecutionPlan, original root plan,
source, timestamps, frozen allowed tool names, scope/task identity, schema fingerprint,
artifact mode, process identity for memory-only artifacts, root/parent IDs, repair
attempt accounting and the active child ID. It contains no clients, permissions,
raw tool responses, artifact bodies or credentials. The plan and original objective
are execution input, not a duplicate mutable registry. The compiled FlowDefinition
alone is insufficient: it omits some original plan information and runtime policy.

The resolver recomputes a manifest in original node order. It includes completed typed
references, synthesizes bounded error refs for recorded failures, and marks remaining
nodes blocked only when the run is terminal. Running nodes without results are pending,
not failed. A terminal manifest's counters are recomputed, never incremented by adding
parent and child totals. Successful immutable versions remain unchanged. Original
per-node references and definition are sufficient; no persisted final-manifest cache
is necessary. Root/child cycles, missing ancestors and schema mismatches fail closed.

Checkpoint cache entries carry their checkpoint ID. Consult persisted latest state
before any continuation; another process's child completion must invalidate a cached
parent. Status/artifact reads of checkpointed runs refresh from the store; a local
live cache may add explicitly marked uncheckpointed progress but cannot claim durability.
Read both configured checkpoint tiers and select the greatest checkpoint ID for the
same flow, rather than blindly choosing an older durable copy. Equal IDs with different
state are corruption. After acquiring a lease, re-read and compare the revision before
dispatch: a checkpoint loaded before the lease may already be stale.

### Recovery capabilities

| Checkpoints acknowledged | Artifact configuration | Reported `resume_level` | Fresh-process continuation |
|---|---|---|---|
| No | Any | `none` | Refuse `checkpoint_unavailable` |
| Yes | In-memory or process-local scope | `process` | Refuse `artifacts_unavailable` |
| Yes | Durable backend, stable trusted scope, required versions readable | `cross_restart` | Allowed after validation and lease acquisition |

`resume_level` expresses storage capability; `resumable` additionally reflects current
run status, lease ownership and missing/expired artifacts. A completed run is not
resumable even when it has cross-restart storage. Report `checkpoint_enabled`,
`artifact_mode`, `resume_level`, `resumable`, `recovery_reason`, lineage and repair
counts on running summaries, terminal results and artifact responses.

Probe the configured/default checkpoint store with a bounded awaited operation before
first dispatch. A connection outage causes fresh execution without checkpointing;
configuration errors remain explicit. Honor `PlanMetadata.checkpoint=False`. No
network I/O occurs in the toolkit constructor. If persistence fails after a checkpointed
run starts, stop further dispatch and return `checkpoint_write_failed` with observed
progress and last acknowledged checkpoint ID. Do not silently switch that run to
unleased execution or claim its last in-memory progress was persisted.

Implement `PlanFlow` locally under `tools/execution_plan/`. Its constructor forces
required checkpoint barriers only when checkpointing is enabled, projects only
`plan_run`, and excludes raw responses. Its scheduler wrapper writes an initial
checkpoint before dispatch and a terminal checkpoint before releasing its lease.
Use the existing scheduler and checkpoint lifecycle, including cancellation cleanup;
do not reimplement DAG scheduling. `AgentsFlow.from_definition` has no
`checkpoint_required`/`checkpoint_shared_data` parameters, so the subclass constructor
supplies them. Regression tests must verify those options on both fresh and resumed flows.

`plan_resume` rebuilds through `PlanFlow.resume(..., flow_factory=..., seed_context=...)`.
The factory calls the same `make_tool_node_factory` with fresh live dependencies,
current permissions, recorded run identity and step mapping. Prepare the seed context's
validated plan metadata explicitly: supplied seed contexts do not get shared data from
the checkpoint automatically. Revalidate allowed tools and input/definition fingerprints
before any dispatch. Do not use `CheckpointInputMetadata(workflow="execution-plan")`:
that existing model only permits dev-loop/dev-flow; store the plan fingerprint inside
the toolkit's checkpoint envelope instead.

Completed results, including a returned `ArtifactRef(status="error")`, belong to
the scheduler's completed frontier. Resume preserves that frontier. Runtime failures
in a finished run require `plan_repair`; resume is not a free repair round.

### Plan memory binding and recovery reads

Preserve a supplied, enabled TaskMemory composition root and its trusted scope. For
an unbound toolkit, construct a default `TaskMemoryConfig(enabled=True, durable=False)`
and in-memory runtime. A host can supply an already-started TaskMemoryRuntime and
trusted TaskScope for durable operation. Never start a second durable backend beside
an existing runtime. A durable runtime without a trusted scope is a configuration error.
The model cannot supply scope through tool arguments or checkpoint contents.

For legacy local wiring, synthesize one process-local scope per WorkingMemory instance:
`chatbot_id="execution-plan"`, a process-generated user identity and that catalog's
session ID. It is a local namespace, not user authentication, and cannot authorize
cross-restart recovery. Keep scope stable across runs sharing that memory; retain
`plan_run_id` as separate provenance, never invent domain task IDs from node/run IDs.

Activation is prepared by the constructor and completed asynchronously before plan
dispatch. Migrate any pre-existing catalog entries through awaited versioned writes;
swap the memory binding only after successful migration. On failure, preserve the
old catalog and dispatch nothing. Serialize activation with a lock, preserve explicit
answer memory/tool locals/session identity, and update already-generated
`wm_get_result` wrapper schemas in place. Newly generated wrappers must select the
enabled schema too. Do not expose the activation helper as an LLM tool.

Always attach the real TaskMemory config, not just a backend. The existing fallback
`_resolve_raw_budget` accepts a caller's requested bytes without clamping if config
is absent. With config attached, the existing hard clamp and `_apply_raw_policy` work
unchanged: default 2,000,000 bytes; lower requested budgets honored; larger ones
clamped; zero disables raw reads; pagination remains bounded.

Use a toolkit-local `PlanWorkingMemoryCatalog` subclass to restore entries in a new
process. Existing `aget()` only reads `_store`, even with a durable backend. Resolve
the exact `EvidenceRef` from checkpoint `ArtifactRef.versions`, authorize against the
host scope, load using the backend's explicit byte-bound API, and reconstruct entry
metadata without writing a new version or moving the persistent alias. Validate
key/version cardinality. Refuse missing, expired, invalidated or unsupported payloads
before continuation instead of rerunning their successful producers.

Internal executor hydration uses a separate finite `max_restore_bytes` budget,
64 MiB by default, configurable only by the host. It does not change the analyst's
2 MB ceiling. Account cumulative restored bytes per continuation; exceedance returns
`restore_budget_exceeded`. Metadata-only status/artifact calls never materialize bodies.
Pin exact versions for completed nodes during an active continuation. Conflicting
aliases must be rejected (`artifact_alias_conflict`), not silently redirected to a newer
version. Serialize continuations sharing the same in-process memory while bindings
are installed; never rewrite a shared catalog's scope per node.

An interrupted fan-out has no whole-node ArtifactRef yet. Restore existing aliases
through scoped backend metadata where ownership can be verified and preserve
`ForEach.skip_existing`; do not claim item-level exactly-once effects. If ownership
or availability cannot be established, report that limitation explicitly.

### Repair validation, execution and concurrency

The planner emits a `PlanDelta` containing replacement PlanNodes. It is deliberately
not a standalone ExecutionPlan: a replacement can depend on a successful node omitted
from the delta. Merge replacements into the original node set, validate the resulting
ExecutionPlan with `validate_with_allowlist`, and then execute it with non-replaced
terminal nodes seeded as completed. This retains full dependency/facet validation
without changing the frozen validator or dispatching protected nodes.

Eligible IDs are precisely explicit error refs, recorded hard failures and never
dispatched nodes of a terminal failed/partial run. Reject empty deltas, new/duplicate
IDs, ok/skipped/partial replacements, changes to plan-level metadata, changes to
protected nodes, and writes colliding with successful artifact keys. Preserve each
replacement node's `store_as`, dependency list and fan-out identity/source/key mapping;
the planner may repair its tool, arguments, select/facets, guard and bounded retry
policy subject to existing validation. This keeps item identity stable for
`skip_existing` and prevents new nodes from disguising themselves as replacements.
No plan-level or tool-controlled policy can widen the recorded allowlist; intersect it
with current host policy on resume/repair.

`PlanPlanner.replan` makes one AbstractClient call. A malformed or invalid delta gets
at most one separate structural correction call, with the same eligible IDs and
validation rules. Do not pass a PlanDelta to existing `PlanPlanner.repair`, whose
parser expects an ExecutionPlan. Both calls receive only the original plan, bounded
manifest/errors and allowlisted tool descriptions; never artifact bodies. A repair
round includes that optional correction, so an approved limit of N rounds permits
at most 2N planner calls for runtime repair. Reject missing planner configuration
before consuming an attempt.

Serialize the entire continuation operation (validation, planner, dispatch and final
checkpoint) on the root's existing CheckpointStore lease. A plan-local store adapter
must delegate one acquired lease to the flow lifecycle rather than reacquiring the
same root lease under a second holder. It also checks the expected checkpoint revision
under that lease. Heartbeat during planner calls and tool execution; fail on lease loss;
release on cancellation and every error path. Degraded runs use an asyncio lock with
the same non-overlap semantics within their owning process.

Persist the attempt number and allocated child ID in the root checkpoint before
calling the planner. Invalid output, cancellation and crashes after this point consume
the attempt; repeated calls cannot reset the cap. Persist the accepted child definition
and initial child checkpoint before dispatch, seed successful parent refs, and make
the child the active continuation in checkpoint lineage. A crash before a child is
ready must not be interpreted as permission to regenerate an entire plan. Reconcile
root/child checkpoints under the root lease and either resume an accepted child or
return `repair_interrupted`. Never autonomously make another planner call.

The repair limit/default and expired-run policy remain explicit approval blockers in
§8. No implementation may choose them from the recommendations in this draft.

### Data Models

All new models use Pydantic v2, explicit field descriptions and `extra="forbid"`.
Live tasks/clients/flows/locks stay outside persisted models.

| Model | Fields / contract |
|---|---|
| `PlanRecoveryConfig` | `max_repair_rounds` (0–2, default pending §8); `max_restore_bytes=67108864`; `checkpoint_probe_timeout=2.0` positive finite seconds |
| `PlanDelta` | `nodes: list[PlanNode]`, nonempty; no plan-level changes or new IDs |
| `PlanRunMetadata` | `schema_version=1`, root/parent/run IDs, original/effective plan, source, start/end timestamps, scope/task, allowed names, fingerprint, artifact mode, process identity, attempts used/limit, active child |
| `PlanRun` | Derived run metadata, checkpoint ID, status, progress, manifest, recovery capability/reason; never separately persisted |
| `PlanRunManifest` | Extends ExecutionManifest in toolkit models; adds run/lineage IDs, status, recovery fields and repair counts |
| `PlanRunSummary` | Extends RunningSummary for live runs; same additional recovery/lineage fields |
| `PlanResumeArgs`, `PlanRepairArgs` | `run_id: str`; no scope, allowlist, retry limit or automatic-restart argument |
| `PlanRunError` | `code: str`, message bounded to 500 chars; optional bounded manifest; maps to ToolResult error |

Terminal responses preserve existing manifest keys at the top level. Toolkit code
constructs a PlanRunManifest from `build_manifest()` output, keeping the frozen
ExecutionManifest unchanged. This is an additive toolkit response schema change:
strict external consumers that deserialize directly into the frozen `extra="forbid"`
model need to select manifest fields or use the new toolkit model. Document that
migration explicitly; do not describe the JSON as byte-identical.

### New Public Interfaces

`ExecutionPlanToolkit` adds keyword-only `recovery: PlanRecoveryConfig | None = None`,
`checkpoint_store: CheckpointStore | str | None = None`,
`durable_store: CheckpointStore | str | None = None`,
`task_memory_runtime: TaskMemoryRuntime | None = None`, and `scope: TaskScope | None = None`.
All existing constructor arguments retain their meaning. `None` recovery selects
approved defaults after §8 resolution. Store/runtime objects are trusted host inputs.
Borrowed resources are not closed by the toolkit; owned resources are cleaned up.

Errors use `ToolResult(status="error", success=False, error=<bounded text>,
result={"code": ..., ...})`. Stable codes include `unknown_run`, `checkpoint_unavailable`,
`checkpoint_invalid`, `checkpoint_write_failed`, `run_busy`, `run_not_resumable`,
`run_not_repairable`, `no_repairable_nodes`, `repair_limit_reached`, `repair_interrupted`,
`delta_invalid`, `planner_unavailable`, `scope_mismatch`, `policy_mismatch`,
`artifacts_unavailable`, `artifact_alias_conflict`, and `restore_budget_exceeded`.
Expiration-specific codes depend on §8's retained-identity decision. Unknown-run
diagnostics may list only a bounded set of locally known authorized IDs.

## 3. Module Breakdown

Paths below are relative to `packages/ai-parrot/src/parrot/` unless stated otherwise.
Interface skeletons describe proposed signatures, not already-existing APIs.

#### Delegation-eligible modules

| Module | Eligible? | Decided patterns / exact contracts | Why not (if no) |
|---|---|---|---|
| M1 owner discovery | yes | `get_toolkit_owner(tool)`; direct/wrapped owner; explicit injection wins | — |
| M2 memory binding | yes | Private activation, config clamp, scoped exact-version restoration, §2 errors | — |
| M3 run models/resolver | no | Checkpoint projection and serialization decided | Expired-vs-unknown retention decision pending |
| M4 checkpoint lifecycle | no | PlanFlow, revision check, one root lease, factory reconstruction | Identity receipt scope pending |
| M5 delta planner/validator | yes | PlanDelta → merged ExecutionPlan; eligibility and one correction fixed | — |
| M6 toolkit orchestration | no | Two tools, additive metadata, bounded lineage | Repair default and expired-run policy pending |
| M7 integration/docs | no | §4 regression matrix and response migration | Final policy examples depend on §8 |

### Module 1: Toolkit-owner discovery

- **Path**: `tools/manager.py`, `bots/agent.py`.
- **Responsibility**: One owner lookup reused by manager and answer-memory injection;
  deduplicate owner identities; support direct toolkits and wrapped methods.
- **Depends on**: Existing AbstractToolkit/ToolkitTool.
- **Interface Skeleton**:

```python
# Proposed addition in tools/manager.py.
# Owner idiom verified: packages/ai-parrot/src/parrot/tools/manager.py:2573
def get_toolkit_owner(tool: Any) -> AbstractToolkit | None:
    """Return a direct toolkit or a bound wrapper's toolkit; otherwise None."""

# Existing method modified; verified: packages/ai-parrot/src/parrot/bots/agent.py:234
def _inject_answer_memory_into_toolkits(self) -> None:
    """Inject once per WorkingMemory owner, preserving non-None explicit bindings."""
```

### Module 2: Plan memory activation and catalog recovery

- **Path**: new `tools/execution_plan/memory.py`; private additions to
  `tools/working_memory/tool.py`. Do not alter raw-policy logic or global defaults.
- **Responsibility**: Prepare a real TaskMemory/config, migrate entries, preserve wrapper
  identity, restore immutable evidence and enforce internal restoration budgets.
- **Depends on**: Existing artifact-store protocol, TaskMemoryRuntime and catalog types.
- **Interface Skeleton**:

```python
# New tools/execution_plan/memory.py.
class PlanMemoryBinding:
    """Own plan-only memory preparation and borrowed/owned resource lifetimes."""
    def __init__(self, working_memory: WorkingMemoryToolkit, *,
                 runtime: TaskMemoryRuntime | None, scope: TaskScope | None,
                 max_restore_bytes: int) -> None:
        """Prepare configuration without I/O; retain supplied scope and runtime."""
    async def prepare(self) -> TaskMemory:
        """Enable plan memory atomically; retain legacy state on migration failure."""
    async def restore(self, refs: Sequence[ArtifactRef]) -> None:
        """Restore authorized exact versions within budget, without allocating versions."""
    async def close(self) -> None:
        """Close only owned runtime resources after in-flight operations finish."""

# Base verified: packages/ai-parrot/src/parrot/tools/working_memory/internals.py:778
class PlanWorkingMemoryCatalog(WorkingMemoryCatalog):
    """Plan-scoped catalog with explicit immutable-version recovery."""
    async def restore_version(self, key: str, ref: EvidenceRef, *, max_bytes: int) -> None:
        """Authorize, load and publish a local entry; never move the backend alias."""
    async def aget(self, key: str) -> CatalogEntry | GenericEntry:
        """Read a bound version or restore its scoped alias; refuse mismatched evidence."""

# Private addition; constructor verified: packages/ai-parrot/src/parrot/tools/working_memory/tool.py:105
async def _enable_plan_memory(self, task_memory: TaskMemory,
                              catalog: WorkingMemoryCatalog) -> None:
    """Install a prepared binding and refresh cached wrapper schemas without exposing a tool."""
```

### Module 3: Run models and checkpoint-derived resolver

- **Path**: `tools/execution_plan/models.py`, new `tools/execution_plan/runs.py`.
- **Responsibility**: Models in §2, deterministic manifest projection, type registration,
  cache revisioning, root/child traversal and honest recovery capability.
- **Depends on**: M2 and existing FEAT-399 models/serializer.
- **Interface Skeleton**:

```python
# New tools/execution_plan/runs.py.
def register_plan_checkpoint_types() -> None:
    """Idempotently register ArtifactRef before any checkpoint encode or decode."""

def project_run(checkpoint: FlowCheckpoint, *, metadata: PlanRunMetadata) -> PlanRun:
    """Derive typed refs, progress and manifest; reject lossy or inconsistent state."""

class PlanRunResolver:
    """Resolve every agent-facing run operation from the same authority."""
    def __init__(self, *, store: CheckpointStore | None,
                 durable_store: CheckpointStore | None,
                 scope: TaskScope, cache: dict[str, PlanRun]) -> None:
        """Bind trusted scope and store handles, never serialized clients."""
    async def resolve(self, run_id: str) -> PlanRun:
        """Resolve latest authorized lineage; distinguish errors only with retained evidence."""
```

M3's optional identity-receipt interface and file ownership are intentionally deferred
to §8. Do not fill this gap with an invented `CheckpointStore.exists()` method.

### Module 4: Checkpoint lifecycle and continuation lease

- **Path**: new `tools/execution_plan/checkpoint.py`.
- **Responsibility**: Factory bindings, required checkpoint writes, fresh/resumed parity,
  root lease delegation, revision validation and release on every exit.
- **Depends on**: M2–M3; existing CheckpointStore and FlowCheckpointer.
- **Interface Skeleton**:

```python
# New tools/execution_plan/checkpoint.py.
# Base verified: packages/ai-parrot/src/parrot/bots/flows/flow/flow.py:296
class PlanFlow(AgentsFlow):
    """Apply plan-specific checkpoint policy around the existing scheduler."""
    def __init__(self, name: str, **kwargs: Any) -> None:
        """Force required persistence and plan-only projection when checkpointing is enabled."""
    async def _run_flow_scheduler(self, ctx: FlowContext, *,
        on_complete: tuple[Callable[[FlowContext, FlowResult], Awaitable[None]], ...] = (),
    ) -> FlowResult:
        """Checkpoint start/terminal state inside the lease lifetime; delegate scheduling."""

class PlanContinuation:
    """Hold one root lease across validation, authoring and flow execution."""
    def __init__(self, run: PlanRun, *, store: CheckpointStore | None) -> None:
        """Bind the root identity and expected checkpoint revision."""
    async def __aenter__(self) -> PlanContinuation:
        """Acquire and renew the root lease, then reject stale snapshots or conflicts."""
    async def __aexit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        """Stop heartbeat and release only the owned lease, including on cancellation."""
    def flow_store(self) -> CheckpointStore:
        """Return a delegating store so flow resume does not reacquire the root lease."""

def build_plan_flow(plan: ExecutionPlan, *, run: PlanRunMetadata,
                    tool_manager: Any, working_memory: WorkingMemoryToolkit,
                    agent_registry: AgentRegistry, permission_context: Any,
                    step_mapping: Mapping[str, str], store: CheckpointStore | None,
                    durable_store: CheckpointStore | None) -> PlanFlow:
    """Compile with the existing factory, bind the run ID and checkpoint projection."""
```

The adapter returned by `flow_store()` implements all CheckpointStore abstract methods
by delegation; no changes to the global backend contract. It serializes writes per
flow, checks ownership/revision and does not permit delayed older writes to replace a
newer latest checkpoint. M4 is not delegation-ready until its TASK enumerates that
adapter's full lease-handoff state machine and final receipt policy.

### Module 5: Runtime delta authoring and validation

- **Path**: `tools/execution_plan/planner.py`; new `tools/execution_plan/repair.py`.
- **Responsibility**: Separate delta parsing/prompts from structural full-plan repair;
  derive eligibility; merge and validate; preserve protected nodes.
- **Depends on**: M3 and existing catalog/validator.
- **Interface Skeleton**:

```python
# Existing class extended; verified: packages/ai-parrot/src/parrot/tools/execution_plan/planner.py:127
class PlanPlanner:
    """Existing plan author plus explicit runtime delta authoring."""
    async def replan(self, plan: ExecutionPlan, manifest: ExecutionManifest, *,
                     eligible_node_ids: frozenset[str]) -> PlanDelta:
        """Make one planner call for replacements only; raise on malformed output."""
    async def repair_delta(self, delta_json: dict[str, Any], report: ValidationReport, *,
                           plan: ExecutionPlan, eligible_node_ids: frozenset[str]) -> PlanDelta:
        """Make one structural correction call, retaining runtime delta restrictions."""

# New tools/execution_plan/repair.py.
def eligible_repair_nodes(run: PlanRun) -> frozenset[str]:
    """Return explicit errors and terminal undispatched IDs, excluding partial/ok/skipped."""
def validate_delta(delta: PlanDelta, *, run: PlanRun,
                   tool_manager: Any, allowed_tools: Sequence[str]) -> ValidationReport:
    """Validate merged topology and tool policy plus protected-node/key invariants."""
def merge_delta(plan: ExecutionPlan, delta: PlanDelta) -> ExecutionPlan:
    """Replace existing IDs in original order; never add IDs or change plan metadata."""
```

### Module 6: Agent-facing orchestration and response metadata

- **Path**: `tools/execution_plan/toolkit.py`, `tools/execution_plan/__init__.py`.
- **Responsibility**: Wire M1–M5; preserve acquisition/validation modes and soft timeout;
  enforce approved repair budgets; expose two new tools with explicit schemas.
- **Depends on**: M2–M5 and §8 policy decisions.
- **Interface Skeleton**:

```python
# Existing class modified; verified: packages/ai-parrot/src/parrot/tools/execution_plan/toolkit.py:99
class ExecutionPlanToolkit(AbstractToolkit):
    """Execute, inspect and explicitly continue bounded deterministic plans."""
    async def plan_resume(self, run_id: str) -> ToolResult:
        """Resume an interrupted checkpointed run without authoring a plan or replaying completions."""
    async def plan_repair(self, run_id: str) -> ToolResult:
        """Spend one permitted repair attempt on failed/blocked IDs; never restart a whole run implicitly."""
    async def plan_status(self, run_id: str) -> ToolResult:
        """Return current lineage progress or manifest with actual recovery capability."""
    async def plan_artifacts(self, run_id: str) -> ToolResult:
        """Return authorized immutable references and recovery metadata without reading bodies."""
```

Retain `RunRecord` and `RunningSummary` exports for existing consumers; introduce new
models without silently changing their old meanings. Export PlanRecoveryConfig,
PlanDelta, PlanRunManifest and the new tool-argument models from the toolkit package.

### Module 7: Regression evidence and documentation

- **Path**: `packages/ai-parrot/tests/tools/execution_plan/` (new
  `test_run_resolution.py`, `test_checkpoint_resume.py`, `test_runtime_repair.py`,
  `test_plan_memory.py`, `test_toolkit_owner.py`); extend existing integration tests;
  `docs/toolkits/execution_plan_toolkit.md`.
- **Responsibility**: Prove §4/§5, including real serialization/restart boundaries.
- **Depends on**: M1–M6.
- **Interface Skeleton** (test interfaces only; documentation adds no Python API):

```python
async def test_resume_in_fresh_process_preserves_completed_nodes() -> None:
    """Recover typed references and durable payloads without executing completed producers."""
async def test_repair_is_bounded_across_restart_and_concurrent_callers() -> None:
    """Assert one root lease and persisted attempt accounting before planner calls."""
async def test_plan_binding_caps_existing_registered_get_result() -> None:
    """Exercise enabled policy through a wrapper obtained before plan activation."""
```

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_toolkit_owner` | M1 | Direct instance, wrapped method, unrelated tool, duplicate wrappers and explicit binding |
| `test_artifact_ref_checkpoint_roundtrip` | M3 | Real serializer/store bytes round trip; fresh registry setup; no repr degradation |
| `test_manifest_projection` | M3 | ok/skipped/partial/error, hard failure and pending-vs-blocked; original order; accurate counters |
| `test_resolver_refreshes_lineage` | M3 | Stale cache, active child, missing ancestor, cycle, changed schema and checkpoint tiers |
| `test_scope_and_policy_rejection` | M3–M6 | Another scope/run ID cannot read or continue; current policy cannot widen original tools |
| `test_delta_validation` | M5 | New/duplicate/protected IDs, changed dependency/key identity, key collisions and disallowed tools |
| `test_delta_dependency_on_success` | M5 | Delta omits successful parent but merged validation succeeds without executing that parent |
| `test_partial_is_not_error` | M5 | Partial fan-out cannot be reclassified to bypass D2; no eligible IDs consumes no planner call |
| `test_delta_structural_correction` | M5 | One author + at most one correction; all restrictions rechecked |
| `test_attempt_accounting` | M6 | Persist before LLM; cancellation/invalid output consumes attempt; missing planner does not |
| `test_plan_memory_activation` | M2 | Existing entries retained, atomic failure, shared runtime reused, explicit scope preserved |
| `test_read_ceiling` | M2 | 40 MB JSON refusal; 2 MB default; attempts to raise budget clamped; zero/paging honored |
| `test_existing_wrapper_schema` | M2 | Already-registered wrappers receive enabled fields; standalone disabled wrappers unchanged |
| `test_restore_exact_version` | M2 | No new versions, no alias movement, bounded loads, eviction/refusal and scope mismatch |
| `test_checkpoint_outage` | M4 | Before dispatch degrades fresh execution; mid-run failure halts new dispatch and reports actual state |
| `test_checkpoint_lifecycle` | M4 | Required barriers fresh/resumed; start/terminal records; no raw responses; cancellation releases lease |
| `test_continuation_conflict` | M4 | Root/child resume-vs-repair competition, heartbeat loss, stale snapshot, no double acquisition |

### Integration Tests

| Test | Description |
|---|---|
| Fresh process recovery | Execute A→B→C, acknowledge A/B, terminate process, use new toolkit/runtime and recover C; A/B dispatch counters unchanged |
| Large fan-out restart | Interrupt a 300-item plan after acknowledged work; persisted successful nodes are skipped and available item aliases preserve skip_existing semantics |
| Actual durable artifacts | Use the existing supported durable runtime fixture, reconnect in a fresh process, restore payload/version identity and complete a downstream artifact reference |
| Serialized fake-store recovery | Always-run test destroys all toolkit/catalog state and reloads serialized checkpoints/artifacts; complements, does not replace, real backend integration |
| In-memory downgrade | Checkpoint survives but original process artifacts do not; status works from metadata and resume explicitly refuses |
| Repair chain crash matrix | Crash before attempt reservation, after reservation, after delta acceptance, during child execution and before final consolidation |
| Concurrency across processes | Two callers contend on the same root lease; loser spends zero LLM calls and dispatches zero tools |
| Standalone compatibility | Existing FEAT-538 disabled surface/turn-shape regression remains intact |
| Expiration identity | Conditional on §8: demonstrate expired vs unknown using retained evidence, including receipt retention boundary |

### Test Data / Fixtures

Use deterministic scripted planner responses, counted fake tools and explicit asyncio
events instead of timing-sensitive sleeps. Include scalar and tabular artifact bodies,
an error-only node, a partial fan-out, a guarded skip, a blocked descendant, and a
successful producer read by a delta node. Use real FlowStateSerializer bytes in store
fakes; a Python object dict alone cannot catch missing type registration.

Reuse existing tests under `packages/ai-parrot/tests/tools/execution_plan/`,
`packages/ai-parrot/tests/flows/checkpoint/` and
`packages/ai-parrot/tests/tools/working_memory/task_memory/`. Preserve the frozen plan
suite discovered under the distribution's tests. Run with the activated repository
environment; store pytest/ruff logs in `artifacts/logs/`. Real service tests must
report missing infrastructure as an explicit skip, not a successful recovery proof.

## 5. Acceptance Criteria

- [ ] AC1: The plan package, shared flow/checkpoint implementation and clients/base.py remain unchanged.
- [ ] AC2: No LLM calls occur in execution/resume; runtime repair is explicit, bounded and allowlist-validated.
- [ ] AC3: Completed checkpointed producers are not dispatched after restart, and downstream tools read their exact durable versions.
- [ ] AC4: Status and artifacts reconstruct after process loss without a second persisted RunRecord/manifest.
- [ ] AC5: Every run response declares actual recovery capability, including no-Redis and memory-artifact degradation.
- [ ] AC6: Required checkpoint failures and lost leases prevent further dispatch; no falsely durable terminal success.
- [ ] AC7: Delta execution preserves ok/skipped/partial nodes, rejects new IDs, and consolidates counters without double counting.
- [ ] AC8: Approved repair limits survive invalid output, cancellation, child runs, restarts and concurrent callers.
- [ ] AC9: Fresh/resumed flows use the same live factory contracts and trusted scope/policy checks.
- [ ] AC10: Plan memory enforces the raw-read ceiling through wrappers registered both before and after activation.
- [ ] AC11: Standalone disabled WorkingMemory retains FEAT-538 AC13; existing constructor inputs and explicit answer memory continue to work.
- [ ] AC12: Owner discovery injects once per actual toolkit, and the documentation's wrapper workaround is removed.
- [ ] AC13: Metadata-only reads load zero artifact payload bytes; restoration is bounded and never mutates evidence versions.
- [ ] AC14: Soft timeout returns progress without cancellation; background task errors become bounded structured results.
- [ ] AC15: §4 unit/regression suites pass; real durable/process recovery evidence is recorded separately from fake-store tests.
- [ ] AC16: §8 policy and retention blockers are resolved and reflected consistently in config defaults, tests and docs before approval.
- [ ] AC17: Documentation explains the additive terminal schema and the exactly-once limitation for interrupted external calls.

## 6. Codebase Contract

Verified against local dev at `d4d83dac0c9a91f09af0346a5beb3e10dcf16668` on 2026-09-21.
The earlier brainstorm's line numbers were rechecked; source paths below are repository-relative.
Unrelated concurrent working-tree edits were not used as contracts for this feature.

### Verified Imports

These declarations were verified by reading their defining/exporting modules; this
specification task did not initialize provider clients or live storage dependencies.

```python
from parrot.tools.execution_plan import ExecutionPlanToolkit, PlanPlanner, RunRecord, RunningSummary
# verified: packages/ai-parrot/src/parrot/tools/execution_plan/__init__.py:14
from parrot.tools.execution_plan.catalog import build_catalog, validate_with_allowlist
# verified: packages/ai-parrot/src/parrot/tools/execution_plan/catalog.py:68
from parrot.bots.flows.plan import (
    ArtifactRef, ExecutionManifest, ExecutionPlan, PlanNode, PlanToolNode,
    build_manifest, make_tool_node_factory, to_flow_definition, ensure_tool_node_registered,
)
# verified: packages/ai-parrot/src/parrot/bots/flows/plan/__init__.py:13
from parrot.bots.flows.core.checkpoint import (
    CheckpointStore, FlowCheckpoint, ContextSnapshot, FlowCheckpointer,
    FlowStateSerializer, register_checkpoint_type, get_checkpoint_store,
)
# verified: packages/ai-parrot/src/parrot/bots/flows/core/checkpoint/__init__.py:8
from parrot.bots.flows.flow.flow import AgentsFlow
# verified: packages/ai-parrot/src/parrot/bots/flows/flow/flow.py:296
from parrot.tools.working_memory.internals import WorkingMemoryCatalog, CatalogEntry, GenericEntry, VersionMetadata
# verified: packages/ai-parrot/src/parrot/tools/working_memory/internals.py:98
from parrot.tools.working_memory.task_memory.config import TaskMemoryConfig, TaskMemoryRuntime
# verified: packages/ai-parrot/src/parrot/tools/working_memory/task_memory/config.py:57
from parrot.tools.working_memory.task_memory.models import TaskScope, EvidenceRef
# verified: packages/ai-parrot/src/parrot/tools/working_memory/task_memory/models.py:571
from parrot.tools.working_memory.task_memory.tools import TaskMemory
# verified: packages/ai-parrot/src/parrot/tools/working_memory/task_memory/tools.py:105
from parrot.interfaces.artifact_store import ArtifactStore
# verified: packages/ai-parrot/src/parrot/interfaces/artifact_store.py:152
```

### Existing Class Signatures

| Existing symbol / exact callable contract | Verified at |
|---|---|
| `ExecutionPlanToolkit._run_plan(self, plan: ExecutionPlan, *, source: str) -> ToolResult` | `packages/ai-parrot/src/parrot/tools/execution_plan/toolkit.py:175` |
| `plan_status(self, run_id: str) -> ToolResult`; `plan_artifacts(self, run_id: str) -> ToolResult` (async) | `packages/ai-parrot/src/parrot/tools/execution_plan/toolkit.py:388` |
| `PlanPlanner.repair(self, plan_json: Dict[str, Any], report: ValidationReport) -> ExecutionPlan` (async) | `packages/ai-parrot/src/parrot/tools/execution_plan/planner.py:174` |
| `FlowContext.to_snapshot(self, *, serializer: FlowStateSerializer, include_responses: bool = False, lossy_out: Optional[list] = None) -> ContextSnapshot` | `packages/ai-parrot/src/parrot/bots/flows/core/context.py:287` |
| `ContextSnapshot.results`, `completed_tasks`, `completion_order`, `shared_data`, `errors` | `packages/ai-parrot/src/parrot/bots/flows/core/checkpoint/model.py:56` |
| `register_checkpoint_type(model_cls: type[BaseModel], tag: str \| None = None) -> str` | `packages/ai-parrot/src/parrot/bots/flows/core/checkpoint/serializer.py:43` |
| `FlowCheckpointer.checkpoint(self, ctx: FlowContext, *, status: str = "running") -> FlowCheckpoint` (async) | `packages/ai-parrot/src/parrot/bots/flows/core/checkpoint/checkpointer.py:268` |
| `CheckpointStore.acquire_lease(self, flow_id: str, holder: str, ttl: int = 60) -> bool` (async); holder-checked renew/release | `packages/ai-parrot/src/parrot/bots/flows/core/checkpoint/store/base.py:100` |
| `RedisCheckpointStore.latest(self, flow_id: str) -> FlowCheckpoint \| None` (async) | `packages/ai-parrot/src/parrot/bots/flows/core/checkpoint/store/redis.py:112` |
| `TaskMemoryRuntime.start(self, *, start_scheduler: bool = True) -> TaskMemoryRuntime` (async) | `packages/ai-parrot/src/parrot/tools/working_memory/task_memory/config.py:466` |
| `TaskMemoryRuntime.task_memory(self, scope: Any, **kwargs: Any) -> Any` | `packages/ai-parrot/src/parrot/tools/working_memory/task_memory/config.py:628` |
| `WorkingMemoryCatalog(session_id=None, *, backend=None, scope=None, task_id=None)` requires scope with backend | `packages/ai-parrot/src/parrot/tools/working_memory/internals.py:794` |
| `WorkingMemoryCatalog.aget(self, key: str) -> CatalogEntry \| GenericEntry` (async), local-only lookup | `packages/ai-parrot/src/parrot/tools/working_memory/internals.py:1204` |
| `VersionMetadata.from_descriptor(cls, descriptor: ArtifactDescriptor) -> VersionMetadata` | `packages/ai-parrot/src/parrot/tools/working_memory/internals.py:163` |
| `ArtifactStore.get_version(self, scope: TaskScope, ref: EvidenceRef, *, task_id: Optional[str] = None) -> Optional[ArtifactDescriptor]` (async) | `packages/ai-parrot/src/parrot/interfaces/artifact_store.py:242` |
| `ArtifactStore.load_payload(self, scope: TaskScope, ref: EvidenceRef, *, max_bytes: int, offset: Optional[int] = None, limit: Optional[int] = None) -> PayloadResult` (async) | `packages/ai-parrot/src/parrot/interfaces/artifact_store.py:266` |

Important exact factory/resume signatures:

```python
# verified: packages/ai-parrot/src/parrot/bots/flows/flow/flow.py:1421
async def resume(cls, flow_id: str, checkpoint_id: Optional[int] = None, *,
                 agent_registry: AgentRegistry,
                 store: Optional[Union[str, CheckpointStore]] = None,
                 durable_store: Optional[Union[str, CheckpointStore]] = None,
                 flow_factory: Optional[Callable[[FlowDefinition], "AgentsFlow"]] = None,
                 seed_context: Optional[FlowContext] = None,
                 expected_input: Optional[CheckpointInputMetadata] = None) -> "AgentsFlow":
    """Existing classmethod; returns a seeded flow, does not run it."""

# verified: packages/ai-parrot/src/parrot/bots/flows/plan/node.py:1072
def make_tool_node_factory(tool_manager: Any, working_memory: Any, *,
                           permission_context: Optional[Any] = None,
                           plan_run_id: Optional[str] = None,
                           step_mapping: Optional[Mapping[str, str]] = None
                           ) -> Callable[[Any, Set[str], Set[str]], PlanToolNode]:
    """Existing factory; live dependencies stay outside NodeDefinition.config."""

# verified: packages/ai-parrot/src/parrot/bots/flows/plan/node.py:1124
def build_manifest(plan: Any, refs: Sequence[ArtifactRef], *,
                   session_id: Optional[str] = None, duration_seconds: float = 0.0) -> Any:
    """Existing projection; counts partial refs as failed."""
```

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| Owner helper | Existing wrapped-tool detection | `bound_method.__self__` | `packages/ai-parrot/src/parrot/tools/manager.py:2589` |
| Plan memory binding | Existing schema selection | Cached wrapper `args_schema = EnabledGetResultInput` | `packages/ai-parrot/src/parrot/tools/working_memory/tool.py:170` |
| Config binding | Existing raw ceiling | `_resolve_raw_budget` uses `_task_memory.config` | `packages/ai-parrot/src/parrot/tools/working_memory/tool.py:274` |
| Restore catalog | Existing executor reads | `await catalog.aget(key)` | `packages/ai-parrot/src/parrot/bots/flows/plan/node.py:594` |
| PlanFlow | Existing lifecycle | Scheduler runs within acquired lease, cleanup afterward | `packages/ai-parrot/src/parrot/bots/flows/flow/flow.py:1289` |
| Resume factory | Existing reconstruction | Seed completion_order and restore registered result types | `packages/ai-parrot/src/parrot/bots/flows/flow/flow.py:1638` |
| Delta merge | Frozen compiler | Full node config stored in NodeDefinition | `packages/ai-parrot/src/parrot/bots/flows/plan/compile.py:71` |

### Does NOT Exist (Anti-Hallucination)

- `PlanPlanner.replan`, `repair_delta`, `plan_resume`, `plan_repair`, PlanRunResolver,
  PlanFlow and PlanDelta are new in this spec, not available APIs.
- `WorkingMemoryCatalog.attach_backend`, `enable`, `set_backend` and durable read-through
  `aget` do not exist. Backend attachment is constructor-only today.
- `AgentsFlow.resume(node_factories=...)` does not exist; use `flow_factory`.
- `AgentsFlow.from_definition(checkpoint_required=..., checkpoint_shared_data=...)`
  does not exist. Those options belong to its constructor.
- `CheckpointStore.exists`, `was_created`, TTL tombstones and expired-vs-unknown lookup
  do not exist. Redis lookup metadata expires with the checkpoint.
- `CheckpointInputMetadata(workflow="execution-plan")` is invalid with today's Literal.
- ArtifactRef is not automatically registered by the plan module for checkpoint serialization.
- `ExecutionManifest.run_id`/`resume_level` do not exist; add toolkit models rather than
  modifying the frozen model.
- `bots/flows/core/checkpoint/models.py` and `bots/flows/plan/manifest.py` are not files;
  use `checkpoint/model.py` and `plan/node.py`, respectively.
- The design's WorkingMemory `ResultPolicy` dataclass, HandleOnlyCodec and per-tool
  describe_fn are not existing extension points. The MCP result policy is unrelated.

## 7. Implementation Notes & Constraints

### Patterns to Follow

- Async I/O, Pydantic v2, existing AbstractClient calls and self.logger; no new libraries.
- Plan helper methods begin with `_` when attached to a toolkit to avoid accidental
  LLM exposure. New agent-facing methods use explicit tool schemas.
- Do not close borrowed stores or runtimes. Owned background tasks/leases/runtime
  resources require cancellation-safe cleanup and observable failure results.
- Freeze permissions at the correct boundary: persist allowed names and fingerprints,
  never a PermissionContext or credentials. Bind current host permissions on recovery.
- Preserve resolved brainstorm answers below verbatim. Recommendations still awaiting
  their owner are not implementation instructions.

### Known Risks / Gotchas

- Required persistence must be tested with the definition-bound plan scheduler, not
  only an explicit-edge dev-loop graph. Both fresh and resumed setup paths matter.
- Snapshotting a live shared-data mapping can persist unwanted objects. Project only
  the validated plan envelope and explicitly reject lossy data.
- Redis `put` uses several operations and has no general revision CAS. Serialize
  plan writes under the root lease; tests must include interrupted writes and older
  snapshots. Do not claim stronger store atomicity than the backend provides.
- `AgentsFlow.resume` constructs its checkpointer before the factory and normally
  loads durable first. The plan adapter must preserve required policy and choose/check
  the intended revision; merely supplying a factory is insufficient.
- Partial fan-out is a terminal scheduler completion but a failed manifest result.
  D2 intentionally keeps it outside this repair surface.
- The raw-read cap is not a process RAM cap. Exact-version restoration has its own
  bounded budget; a large dependency may be unavailable for continuation under it.
- Statement-level crash safety cannot remove external side effects already performed
  before an acknowledgement. No successful-node replay is not an exactly-once promise.
- `agent.py` and `manager.py` are high-traffic files; keep owner discovery changes local.
- Source audit found synchronous catalog writes in WorkingMemory's disabled branches
  (`tool.py:237`, `:252`, `:265`) and its embedded demonstration (`tests.py:70`). The
  runtime write helpers already switch to awaited operations when enabled. PlanToolNode
  already uses `aput_generic` (`node.py:535`). No production direct synchronous write
  was found outside these branches by the focused `_catalog`/`catalog` call-site search;
  this is a bounded audit, not proof about arbitrary third-party integrations.

### External Dependencies

| Package | Existing declaration | Reason |
|---|---|---|
| pydantic | `==2.12.5` | Models and tool schemas |
| asyncdb | `>=2.16.2` | Existing checkpoint and durable storage backends |
| ormsgpack | `>=1.5` | Existing checkpoint serialization |

Verified in `packages/ai-parrot/pyproject.toml:54`, `:126`, `:129`. No dependency
changes. Follow the distribution's declared Python support; the brainstorm's Python
3.10 statement does not expand the package's supported interpreter range.

### Worktree Strategy

- **Isolation**: `per-spec`.
- **Base branch**: `dev`; future implementation branch `feat/FEAT-585-plan-then-execute-hardening`.
- **Execution order**: M1, M2, M3, M4, M5, M6, M7. M1/M2 design is independent,
  but implement sequentially in one worktree to avoid competing toolkit edits.
- Central ownership: all run/checkpoint/repair integration stays in this spec's worktree.
  Recheck overlaps at task decomposition; the brainstorm's list of active features
  is historical, not a reservation of shared files.

## 8. Open Questions

Resolved exploration answers carried forward verbatim:

- [x] ¿Quién dispara el replan? — *Owner: Jesus Lara*: una tool separada; el agente
  decide. Preserva "cero tokens LLM durante la ejecución".
- [x] ¿Hasta dónde llega la reanudación? — *Owner: Jesus Lara*: cross-restart real,
  otro proceso recoge el `run_id`.
- [x] ¿Cómo se enciende el techo de rehidratación sin romper AC13? — *Owner: Jesus
  Lara*: sólo en contexto de plan; el default global de `WorkingMemoryToolkit` no
  se invierte.
- [x] ¿Qué pasa sin Redis? — *Owner: Jesus Lara*: se ejecuta sin checkpoint y el
  manifiesto lo declara como dato.
- [x] ¿Dónde vive el estado del run? — *Owner: Jesus Lara*: se deriva del
  checkpoint; nada de un segundo objeto persistido que pueda desincronizarse.
- [x] ¿Quién dispara la reanudación tras el reinicio? — *Owner: Jesus Lara*: el
  agente, con una tool. Nada se reanuda solo.
- [x] ¿Por qué mecanismo se enciende el techo? — *Owner: Jesus Lara*: adjuntando un
  backend de artefactos in-memory, asumiendo el versionado que trae consigo.
- [x] ¿Cómo se trata el cambio de conducta del helper? — *Owner: Jesus Lara*: se
  arregla sin flag; es la conducta que el código siempre dijo tener.
- [x] In-memory + cross-restart se contradicen, ¿cómo se resuelve? — *Owner: Jesus
  Lara*: durable si está configurado, in-memory si no, y el manifiesto declara el
  nivel de reanudación del run.
- [x] ¿Qué puede tocar el plan delta? — *Owner: Jesus Lara*: sólo nodos fallidos o
  bloqueados, mismo allowlist, nunca un nodo ok ni nodos nuevos.

Exploration questions resolved by this codebase investigation:

- [x] ¿Basta el checkpoint para reconstruir los `ArtifactRef` del manifiesto, o hay
  que persistir algo más? — Resolved: typed result registration plus the original/effective
  plan and policy envelope within that same checkpoint suffice. No second mutable
  RunRecord or stored final manifest; see §2 and ContextSnapshot/serializer anchors.
- [x] ¿De dónde sale el `TaskScope` que exige un catálogo con backend? — Resolved:
  inherit a trusted runtime scope; otherwise synthesize a process-local scope per WM
  instance. Only stable host-provided scope permits cross-restart recovery. See §2.
- [x] Auditar qué llamadores síncronos del catálogo existen fuera de `PlanToolNode` —
  Completed focused source audit; findings and limits recorded in §7.

Approval blockers (questions sent to Jesus Lara during specification work):

- [ ] Q1: ¿Cuál es el tope de rondas de replan por defecto, y es configurable por plan o
  por toolkit? — *Owner: Jesus Lara*. Recommendation: toolkit-only 0–2 rounds, default
  2; a default of 1 was offered as an alternative. Neither default is approved yet.
- [ ] Q2: ¿`plan_repair` sobre un run expirado por TTL debe poder autorizar una
  re-ejecución completa, o negarse? — *Owner: Jesus Lara*. Recommendation: refuse;
  a fresh execution requires an explicit `plan_execute`. No automatic restart is authorized.
- [ ] Q3: Expired-vs-unknown contradicts the available TTL lookup contract unless
  identity survives expiry. — *Owner: Jesus Lara*. Approve a minimal retained identity
  receipt in the execution-plan layer (scope and run identity only, no duplicated run
  state), or relax the requirement to `missing_or_expired`. If receipts are approved,
  specify their backend/retention and limits before approving M3/M4: finite receipt
  retention only supports distinction within that retention window. The current
  immutable ID alone cannot establish that a run ever existed.

Target version uses `next`, consistent with the related WorkingMemory specification;
author is inherited from the brainstorm. Status remains draft until these blockers
and the normal spec review are complete.

## 9. Design Research Cross-Check

Independent design seat: **skipped** — this invocation ran a single-agent specification
workflow; no independent review or transcript is claimed. The accepted brainstorm's
options and decisions were consumed and all new contract claims were checked against
source. No files were written under the pre-existing `sdd/state/FEAT-585/` directory.

| # | Research finding | Disposition | Reason | Landed in |
|---|---|---|---|---|
| R1 | ArtifactRef loses type without registration | CONFIRM | Process-wide serializer registry is the existing supported hook | §2, M3, AC3 |
| R2 | Durable artifacts do not hydrate catalog aliases | CONFIRM | Current aget is local-only | §2, M2, AC3/13 |
| R3 | Backend without config does not impose a hard raw-read cap | CONFIRM | Fallback accepts caller override | §2, M2, AC10 |
| R4 | TTL removes evidence needed for expired-vs-unknown | ESCALATE | Requires retained identity or a changed requirement | §8 Q3 |
| R5 | Delta is not independently valid when it references successful parents | CONFIRM | Merge then validate full topology; seed protected results | §2, M5 |
| R6 | Returned error/partial refs may be scheduler-completed | CONFIRM | Resume and repair must not conflate frontier and manifest status | §2, §4 |

These are the spec author's source cross-checks, not suggestions from an independent reviewer.
Summary: 5 confirmed · 0 rejected · 1 escalated.

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-09-21 | Jesus Lara / Codex | Initial researched draft; policy and identity-retention decisions pending |
