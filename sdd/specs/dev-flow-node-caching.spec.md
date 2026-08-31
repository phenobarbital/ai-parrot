---
# SDD flow type and base branch (FEAT-145).
type: feature
base_branch: dev
---

# Feature Specification: Dev Flow Node Checkpoint Recovery

**Feature ID**: FEAT-480
**Date**: 2026-08-31
**Author**: Jesus Lara (with Codex)
**Status**: review
**Target version**: next
**Proposal**: `sdd/proposals/dev-flow-node-caching.proposal.md` (research identity FEAT-516)

---

## 1. Motivation & Business Requirements

> Recover interrupted `dev_loop` and proactive `dev_flow` jobs from the last
> successfully persisted node instead of repeating every expensive or
> side-effecting operation.

### Problem Statement

`AgentsFlow` already records node-level checkpoints, but the dev workflows do
not use them safely. They execute explicit-edge graphs with callable predicates
and live dispatcher/toolkit dependencies, while generic `AgentsFlow.resume()`
rebuilds a definition-driven graph. Their runners also reuse one flow instance
whose generated `flow_id` is unrelated to each job's `run_id`. Finally,
checkpoint writes are fire-and-forget and failures are swallowed, so downstream
side effects can start before Redis durably records the upstream completion.

As a result, restarting a failed job repeats bug intake, research, planning, or
development even when those operations completed. Repetition can reproduce an
incident again, duplicate Jira/research activity, redispatch development work,
or lose track of an existing worktree.

### Goals

- Use a caller-supplied stable `run_id` as the recovery identity for a newly
  constructed runner/flow process. A generated new ID is intentionally a cache
  miss.
- Persist a checkpoint after every successfully completed node in `dev_loop`
  and `dev_flow`, and do not route downstream until Redis confirms the write.
- Treat Redis lookup, lease, encoding, or checkpoint-write failures as hard job
  errors for these workflows.
- Rebuild the original explicit-edge graph with fresh live dependencies and a
  fresh `SessionHost`, then restore typed completed-node results and the shared
  projections required by downstream nodes.
- Skip every durably completed node. Rerun the incomplete frontier with
  at-least-once semantics.
- Reuse completed bug-intake, research/planning, and development outputs.
  When development was interrupted, reuse the validated worktree and let the
  existing task index exclude tasks already marked `done`.
- Reject reuse of the same `run_id` when the normalized input, workflow,
  topology version, repository, or execution policy differs.
- Emit structured recovery events so a fresh run, cache hit, restored node,
  rerun node, and fatal checkpoint failure are distinguishable.

### Non-Goals (explicitly out of scope)

- Reuse across different `run_id` values or a semantic cache keyed by prompt.
- Exactly-once execution inside a node that stopped before its completion
  checkpoint.
- Mid-node snapshots of dispatcher progress.
- Serializing or trusting live `SessionHost`, client, dispatcher, toolkit,
  registry, Redis connection, or trace objects.
- Replacing `CheckpointStore`, its Redis key family, or its retention policy.
- Task-granular recovery for single-agent development when no per-spec task
  index exists.
- Generalizing required checkpoint barriers to `AgentCrew`.

---

## 2. Architectural Design

### Overview

This feature extends the existing checkpoint plane rather than adding a second
cache. Each execution gets a dedicated `AgentsFlow` whose checkpoint identity
is `"<workflow>/<run_id>"`, for example `dev-loop/run-abc123`. The slash keeps
the workflow namespace inside the existing `flowckpt:{flow_id}:*` Redis keys
without conflicting with the store's colon-delimited key parsing.

The runner constructs a fresh live `FlowContext` first, including the original
brief, caller policy, and a newly registered `SessionHost`. A shared
`DevCheckpointCoordinator` computes a canonical SHA-256 input fingerprint and
looks up the latest Redis checkpoint:

1. No checkpoint is a normal cache miss. The per-run factory builds the graph
   with checkpointing enabled, the caller's stable identity, the declarative
   graph snapshot, and required-write mode.
2. A checkpoint hit must match the expected fingerprint and acquire the
   existing Redis lease. Mismatch or lease conflict is a hard error.
3. `AgentsFlow.resume()` calls the supplied flow factory, not
   `from_definition()`, preserving custom nodes, explicit predicates, OR joins,
   error edges, and bounded back-edges.
4. Resume seeds the caller's fresh context with typed results and completed
   node IDs. The dev recovery adapter projects those results back to shared
   keys such as `bug_brief`, `bug_findings`, `research_output`,
   `planner_output`, and `development_output`.
5. Recovered research/planning artifacts are validated before any downstream
   dispatch. The worktree must still be registered on the expected branch and
   referenced spec/task artifacts must exist.
6. The scheduler skips completed nodes. The first incomplete node reruns.

Generic checkpointing remains best-effort by default. In required mode the
scheduler performs a dedicated awaited checkpoint call after
`FlowContext.mark_completed()` and after computing any retry invalidation, but
before spawning an outgoing normal or back-edge target. A retry transition
must remove every reset member from both scheduler-local state and
`FlowContext`, so the persisted frontier requests the next development attempt
instead of restoring stale completions. This barrier is not an ordinary
node-event listener because event listeners are telemetry hooks whose failures
are deliberately swallowed.

Only safe checkpoint metadata, registered node results, and an explicit
dev-adapter projection of shared values are serialized. Live shared objects are
supplied by the new process. The flow definition embedded in each checkpoint
comes from the already-built declarative definition retained by the dev
builders; `to_definition()` cannot export their live Python predicates.

### Component Diagram

```text
job system -- stable run_id + brief --> DevLoopRunner / DevFlowRunner
                                          |
                                          v
                                DevCheckpointCoordinator
                                  | fingerprint + latest
                                  v
                         RedisCheckpointStore + lease
                                  |
                         miss ----+---- hit
                          |              |
                          v              v
                 per-run flow factory  AgentsFlow.resume(flow_factory,
                          |              fresh_context, fingerprint)
                          +-------+------+
                                  v
                    explicit-edge AgentsFlow scheduler
                                  |
                        node succeeds + shared projection
                                  |
                                  v
                      awaited required checkpoint barrier
                                  |
                       Redis success --> route downstream
                       Redis failure --> fail the job
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `AgentsFlow` | extends | Required checkpoint mode, external checkpoint definition, factory-based resume, fresh-context seeding, fingerprint validation |
| `FlowCheckpointer` | extends | Awaited `checkpoint()` path that propagates persistence/serialization errors; current listener path stays best-effort |
| `FlowCheckpoint` | extends | Stores immutable workflow/topology/input fingerprint metadata |
| `FlowStateSerializer` | extends | Process-wide registration for dev-loop Pydantic result types |
| `build_dev_loop_flow` / `build_dev_flow` | extends | Build a checkpoint-enabled flow per stable run ID while retaining explicit routing |
| `DevLoopRunner` / `DevFlowRunner` | extends | Select fresh vs resumed execution, bind a fresh host/context, expose recovery telemetry |
| `ResearchNode` worktree guard | extracts/reuses | Shared validator checks recovered branch/worktree safety and required artifacts |
| `TaskScheduler` | uses | Reconstructed from the task index; entries already `done` are excluded |
| Example server and CLI bootstrap | rewires | Pass per-run builders instead of relying only on one shared flow instance |

### Data Models

```python
class CheckpointInputMetadata(BaseModel):
    workflow: Literal["dev-loop", "dev-flow"]
    topology_version: str
    input_fingerprint: str


class FlowCheckpoint(BaseModel):
    # Existing fields remain unchanged.
    input_metadata: CheckpointInputMetadata | None = None
```

The fingerprint is SHA-256 over deterministic JSON with sorted keys and contains
at least:

- workflow kind and topology version;
- normalized Pydantic brief (`model_dump(mode="json")`);
- repository identity/base path;
- routing-relevant execution policy, including QA/approval and pool settings;
- referenced SDD document identity for feature/document runs.

Volatile values such as timestamps, `SessionHost`, trace IDs, Redis clients,
and dispatcher instances are excluded.

### New Public Interfaces

```python
from collections.abc import Callable


def register_checkpoint_type(
    model_cls: type[BaseModel], tag: str | None = None
) -> str:
    """Register a Pydantic type for every checkpoint serializer instance."""


class CheckpointPersistenceError(RuntimeError):
    """A required checkpoint could not be encoded or persisted."""


class CheckpointFingerprintMismatchError(RuntimeError):
    """A run_id was reused with incompatible immutable input metadata."""


class FlowCheckpointer:
    async def checkpoint(
        self, ctx: FlowContext, *, status: str = "running"
    ) -> FlowCheckpoint:
        """Build and synchronously persist one required checkpoint."""


class FlowContext:
    def reset_completed(self, node_ids: set[str]) -> None:
        """Remove invalidated retry-loop nodes from recoverable state."""


class AgentsFlow:
    def __init__(
        self,
        name: str,
        *,
        checkpoint: bool = False,
        checkpoint_required: bool = False,
        checkpoint_definition: FlowDefinition | None = None,
        checkpoint_input: CheckpointInputMetadata | None = None,
        checkpoint_shared_data: Callable[[FlowContext], dict[str, Any]] | None = None,
        flow_id: str | None = None,
        **kwargs: Any,
    ) -> None: ...

    @classmethod
    async def resume(
        cls,
        flow_id: str,
        checkpoint_id: int | None = None,
        *,
        agent_registry: AgentRegistry,
        store: str | CheckpointStore | None = None,
        durable_store: str | CheckpointStore | None = None,
        flow_factory: Callable[[FlowDefinition], "AgentsFlow"] | None = None,
        seed_context: FlowContext | None = None,
        expected_input: CheckpointInputMetadata | None = None,
    ) -> "AgentsFlow": ...


class DevCheckpointCoordinator:
    async def prepare(
        self,
        *,
        workflow: Literal["dev-loop", "dev-flow"],
        run_id: str,
        brief: BaseModel,
        live_context: FlowContext,
        flow_factory: Callable[..., AgentsFlow],
        execution_policy: dict[str, Any],
    ) -> tuple[AgentsFlow, Literal["fresh", "resumed"]]: ...
```

The existing constructor and resume call shapes remain valid. Required mode is
opt-in and enabled by the two dev workflow factories only.

---

## 3. Module Breakdown

### Module 1: Typed Checkpoint Registration and Resume Factory
- **Path**: `packages/ai-parrot/src/parrot/bots/flows/core/checkpoint/serializer.py`, `checkpoint/__init__.py`, `packages/ai-parrot/src/parrot/bots/flows/flow/flow.py`
- **Responsibility**: Add process-wide Pydantic registration; let resume rebuild through a caller factory; validate completed node IDs; seed a caller-created live context.
- **Depends on**: Existing `FlowStateSerializer`, `AgentsFlow.resume()`, and precedent commit `8d7657b23` (adapt after full review; do not cherry-pick blindly).

### Module 2: Required Checkpoint Barrier and Fingerprint
- **Path**: `packages/ai-parrot/src/parrot/bots/flows/core/checkpoint/model.py`, `errors.py`, `checkpointer.py`, `packages/ai-parrot/src/parrot/bots/flows/core/context.py`, `packages/ai-parrot/src/parrot/bots/flows/flow/flow.py`
- **Responsibility**: Add immutable input metadata, explicit failure types, external checkpoint definition and safe shared-data projection support, recoverable retry invalidation, and an awaited post-success/post-routing-decision/pre-dispatch write path. Preserve current best-effort behavior when `checkpoint_required=False`.
- **Depends on**: Module 1 and the existing `CheckpointStore.put()` contract.

### Module 3: Dev Workflow Recovery Adapter
- **Path**: `packages/ai-parrot/src/parrot/flows/dev_loop/checkpoint.py` (new)
- **Responsibility**: Stable namespaced flow IDs, deterministic fingerprints, fresh/miss/resume selection, shared-state restoration from typed node results, recovered worktree/spec/task validation, and structured recovery events.
- **Depends on**: Modules 1-2, `ResearchOutput`, `DevelopmentOutput`, `PlannerOutput`, and existing worktree/task-index rules.

### Module 4: Dev Loop Per-Run Lifecycle
- **Path**: `packages/ai-parrot/src/parrot/flows/dev_loop/flow.py`, `runner.py`, `models/__init__.py`, `models/base.py`
- **Responsibility**: Produce a new checkpoint-enabled explicit graph per run, register all result types needed for routing/restoration, and recover bug intake, research, and development without restoring live host/tool objects.
- **Depends on**: Module 3.

### Module 5: Proactive Dev Flow Integration
- **Path**: `packages/ai-parrot/src/parrot/flows/dev_flow/flow.py`, `runner.py`, `models.py`
- **Responsibility**: Apply the same per-run lifecycle to `dev_flow`; restore dev intake/ideation/planner/development projections and validate planner-created SDD/worktree artifacts.
- **Depends on**: Modules 3-4.

### Module 6: Runtime Wiring and Regression Coverage
- **Path**: `examples/dev_loop/server.py`, `examples/dev_loop/server_dev.py`, `packages/ai-parrot/src/parrot/cli/devloop/bootstrap.py`, checkpoint/dev-flow/dev-loop test modules
- **Responsibility**: Wire production entry points to per-run factories and verify recovery, failure, compatibility, and observability contracts.
- **Depends on**: Modules 1-5.

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_required_checkpoint_awaits_put_before_routing` | Module 2 | Downstream node cannot start until `CheckpointStore.put()` succeeds |
| `test_required_checkpoint_put_failure_raises` | Module 2 | Redis/store failure raises `CheckpointPersistenceError` and downstream dispatch count stays zero |
| `test_best_effort_checkpoint_behavior_unchanged` | Module 2 | Default generic flow still logs/swallow writes as before |
| `test_resume_flow_factory_preserves_explicit_graph` | Module 1 | Callable predicates, OR joins, error edges, and a bounded back-edge retain behavior |
| `test_resume_factory_rejects_missing_completed_node` | Module 1 | Rebuilt graph cannot silently omit a checkpointed node |
| `test_registered_dev_models_round_trip` | Modules 1/4 | `ResearchOutput`, `PlannerOutput`, `DevelopmentOutput`, and relevant brief/output models keep their Pydantic types |
| `test_fingerprint_is_deterministic` | Module 3 | Equivalent normalized inputs produce the same digest |
| `test_same_run_id_different_input_rejected` | Module 3 | Changed brief/topology/policy raises fingerprint mismatch |
| `test_live_shared_objects_are_not_restored` | Module 3 | Fresh `SessionHost` wins and serialized live values are ignored |
| `test_retry_checkpoint_restores_post_reset_frontier` | Module 2 | Crash after a repair back-edge restores the invalidated cycle and reruns development |
| `test_recovered_worktree_requires_expected_branch` | Module 3 | Missing, unregistered, or wrong-branch worktree fails explicitly |
| `test_scheduler_excludes_done_tasks_after_restart` | Module 4 | Pool recovery dispatches only unfinished task-index entries |
| `test_single_agent_recovery_is_node_granular` | Module 4 | Interrupted single-agent development may rerun and is not claimed task-granular |

### Integration Tests

| Test | Description |
|---|---|
| `test_dev_loop_restart_after_bug_intake` | New runner/process with same `run_id` does not reproduce/re-enrich the bug again |
| `test_dev_loop_restart_after_research` | Research/Jira dispatcher counts do not increase; typed output and validated worktree are restored |
| `test_dev_loop_restart_after_development` | Development dispatcher is not called again and execution continues at QA |
| `test_dev_flow_restart_after_planner` | Planner/ideation are skipped and planner-created artifacts restore downstream state |
| `test_dev_flow_restart_after_development` | Completed proactive development is not redispatched |
| `test_restart_with_new_run_id_is_cache_miss` | Same brief under a different ID executes normally |
| `test_concurrent_resume_lease_conflict` | Two processes cannot both resume one workflow/run identity |
| `test_exception_restart_preserves_completed_frontier` | A downstream exception followed by restart skips every prior durably completed node |
| `test_runtime_entrypoints_build_per_run_flows` | Server and CLI wiring no longer depend on one checkpoint identity shared across jobs |

### Test Data / Fixtures

```python
@pytest.fixture
def checkpoint_store() -> FakeCheckpointStore:
    return FakeCheckpointStore()


@pytest.fixture
def failing_checkpoint_store() -> FakeCheckpointStore:
    store = FakeCheckpointStore()
    store.put = AsyncMock(side_effect=ConnectionError("redis unavailable"))
    return store


@pytest.fixture
def restarted_runner(flow_factory, checkpoint_store):
    # Construct a distinct runner/flow process boundary with the same store.
    return DevLoopRunner(
        flow_factory=flow_factory,
        checkpoint_store=checkpoint_store,
    )
```

Tests must use execution counters and assert the pre-restart node actually ran;
cache assertions must not pass vacuously. Redis integration tests may use the
existing Redis test fixture, while unit tests remain service-independent.

---

## 5. Acceptance Criteria

- [ ] A caller can restart `dev_loop` or `dev_flow` in a new process with the
  same `run_id` and resume from the latest retained checkpoint.
- [ ] A different/new `run_id` never hits another run's checkpoint.
- [ ] Every successful node in both workflows completes an awaited Redis write
  before any newly eligible downstream node starts.
- [ ] Redis lookup, encoding, lease, heartbeat, and write failures fail the job;
  no downstream side effect begins after a failed required barrier.
- [ ] Bug intake is not repeated after its successful checkpoint, including
  reproduction/enrichment and validation-event side effects.
- [ ] Research is not redispatched after its successful checkpoint; Jira key,
  excerpts, typed `ResearchOutput`, and worktree identity are restored.
- [ ] Completed development is not redispatched and typed `DevelopmentOutput`
  is restored.
- [ ] Interrupted pool development rebuilds `TaskScheduler` from the worktree
  index and dispatches only tasks not persisted as `done`.
- [ ] Interrupted single-agent development is documented and tested as
  node-granular at-least-once recovery.
- [ ] `dev_flow` restores intake/ideation/planner/development projections and
  continues through its original explicit-edge graph.
- [ ] A crash after a QA/feedback retry decision restores the post-reset
  frontier and reruns the bounded repair cycle rather than skipping it.
- [ ] Recovered worktrees are registered on the expected branch and required
  SDD spec/task artifacts exist before development/QA continues.
- [ ] Reusing a `run_id` with a changed brief, workflow, topology version,
  repository, or routing policy raises a fingerprint mismatch.
- [ ] Concurrent resume attempts for one workflow/run identity cannot both
  acquire the lease.
- [ ] A fresh `SessionHost`, trace context, dispatchers, and toolkits are bound
  on restart; serialized live objects are never trusted.
- [ ] Generic `AgentsFlow` checkpoint users retain best-effort behavior unless
  they explicitly request required mode.
- [ ] Existing dev-loop/dev-flow routing, gate parking, run bundles, and public
  runner call shapes remain backward compatible.
- [ ] Structured events/logs cover cache miss, checkpoint committed, resume
  started, node restored, node rerun, artifact failure, fingerprint mismatch,
  lease conflict, and fatal checkpoint failure.
- [ ] Focused checkpoint, dev-loop, dev-flow, and runtime-wiring test suites pass.

---

## 6. Codebase Contract

> **CRITICAL - Anti-Hallucination Anchor**
> Implementation agents MUST re-verify any import or signature not listed here.

### Verified Imports

```python
from parrot.bots.flows import AgentsFlow, FlowContext
# verified: packages/ai-parrot/src/parrot/bots/flows/__init__.py:30,75

from parrot.bots.flows.core.checkpoint import (
    CheckpointNotFoundError,
    CheckpointStore,
    FlowCheckpoint,
    FlowCheckpointer,
    FlowLockedError,
    FlowStateSerializer,
    RedisCheckpointStore,
    get_checkpoint_store,
)
# verified: packages/ai-parrot/src/parrot/bots/flows/core/checkpoint/__init__.py:7

from parrot.flows.dev_loop.models import (
    DevelopmentOutput,
    PlannerOutput,
    ResearchOutput,
    WorkBrief,
)
# verified: packages/ai-parrot/src/parrot/flows/dev_loop/models/__init__.py:21

from parrot.flows.dev_loop.task_scheduler import TaskScheduler
# verified: packages/ai-parrot/src/parrot/flows/dev_loop/task_scheduler.py:43
```

### Existing Class Signatures

```python
# packages/ai-parrot/src/parrot/bots/flows/flow/flow.py:209
class AgentsFlow(PersistenceMixin):
    def __init__(  # line 258
        self,
        name: str,
        *,
        definition: FlowDefinition | None = None,
        agent_registry: AgentRegistry | None = None,
        on_node_event: Callable[..., Any] | Sequence[Callable[..., Any]] | None = None,
        checkpoint: bool = False,
        checkpoint_retention: int | None = None,
        checkpoint_history: int | None = None,
        checkpoint_include_responses: bool = False,
        durable: bool = False,
        checkpoint_store: str | CheckpointStore | None = None,
        durable_store: str | CheckpointStore | None = None,
        flow_id: str | None = None,
        **kwargs: Any,
    ) -> None: ...

    async def run_flow(
        self,
        ctx: FlowContext | str | None = None,
        *,
        on_complete: tuple[Callable[..., Awaitable[None]], ...] = (),
    ) -> FlowResult: ...  # line 1156

    @classmethod
    async def resume(
        cls,
        flow_id: str,
        checkpoint_id: int | None = None,
        *,
        agent_registry: AgentRegistry,
        store: str | CheckpointStore | None = None,
        durable_store: str | CheckpointStore | None = None,
    ) -> "AgentsFlow": ...  # line 1332


# packages/ai-parrot/src/parrot/bots/flows/core/checkpoint/checkpointer.py:49
class FlowCheckpointer:
    def make_listener(
        self, ctx: FlowContext
    ) -> Callable[[str, str, dict[str, Any]], None]: ...  # line 207

    async def aclose(self) -> None: ...  # line 327


# packages/ai-parrot/src/parrot/bots/flows/core/checkpoint/store/base.py:17
class CheckpointStore(ABC):
    async def put(self, checkpoint: FlowCheckpoint) -> None: ...  # line 29
    async def latest(self, flow_id: str) -> FlowCheckpoint | None: ...  # line 37
    async def acquire_lease(
        self, flow_id: str, holder: str, ttl: int = 60
    ) -> bool: ...  # line 93


# packages/ai-parrot/src/parrot/flows/dev_loop/runner.py:1028
class DevLoopRunner:
    async def run(
        self,
        brief: WorkBrief | FeatureBrief,
        *,
        run_id: str | None = None,
        initial_task: str = "",
        extra_shared: dict[str, Any] | None = None,
    ) -> FlowResult: ...


# packages/ai-parrot/src/parrot/flows/dev_flow/runner.py:37
class DevFlowRunner(DevLoopRunner):
    async def run(
        self,
        brief: DevRequestBrief | FeatureBrief,
        *,
        run_id: str | None = None,
        initial_task: str = "",
        extra_shared: dict[str, Any] | None = None,
    ) -> FlowResult: ...  # line 55
```

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| Required barrier | Scheduler completion | after `ctx.mark_completed()`, before downstream dispatch | `flow.py:1980`, `flow.py:2006` |
| Retry-safe snapshot | Explicit back-edge reset | synchronize reset members into `FlowContext` before the barrier | `flow.py:1812`, `flow.py:1836`, `flow.py:1855` |
| Flow factory resume | `AgentsFlow.resume()` | replace optional `from_definition()` rebuild | `flow.py:1419` |
| External checkpoint definition | `AgentsFlow._ensure_checkpointer()` | avoid `to_definition()` for callable edges | `flow.py:1276`, `flow.py:652` |
| Typed result registry | `FlowStateSerializer` | process-wide defaults read by every serializer | `serializer.py:61` |
| Bug state restoration | `BugIntakeNode.execute()` | restore result plus `bug_findings`/`bug_brief` projection | `bug_intake.py:85`, `bug_intake.py:119` |
| Research restoration | `ResearchNode.execute()` | restore Jira/excerpts/output and validate worktree | `research.py:257`, `research.py:334`, `research.py:472`, `research.py:1228` |
| Development continuation | `DevelopmentNode.execute()` | recovered `research_output`; task-index or single-agent path | `development.py:142`, `development.py:190`, `development.py:533` |
| Pool continuation | `TaskScheduler` | constructor seeds `_done` from status `done` | `task_scheduler.py:43`, `task_scheduler.py:69` |
| Dev-flow planner bridge | `PlannerNode.execute()` | restore `planner_output` and derived `research_output` | `planner.py:105`, `planner.py:173` |
| Runtime construction | server/CLI | replace shared-only flow wiring with per-run factory | `examples/dev_loop/server.py:1559`, `examples/dev_loop/server_dev.py:490`, `bootstrap.py:324` |

### Does NOT Exist (Anti-Hallucination)

- ~~`AgentsFlow.resume(flow_factory=...)`~~ - not present on `dev`; it exists
  only as non-ancestor precedent in commit `8d7657b23`.
- ~~`AgentsFlow(checkpoint_required=True)`~~ - required/fatal persistence mode
  does not exist.
- ~~`AgentsFlow(checkpoint_definition=...)`~~ - explicit graphs with callable
  predicates currently fail `to_definition()`.
- ~~`register_checkpoint_type()`~~ - current serializers only pre-register
  `AIMessage`.
- ~~`DevLoopRunner.resume_job()`~~ - `resume_run()` only resumes an in-memory
  parked gate; it is not process-restart recovery.
- ~~A serialized `SessionHost` recovery API~~ - live session hosts are held in
  the runner registry and must be recreated.
- ~~Task-level single-agent checkpoints~~ - only pool mode has the persisted
  per-spec task-index continuation contract.

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- Keep generic checkpoint behavior backward compatible; required mode is an
  explicit engine option used by `dev_loop` and `dev_flow`.
- Use Pydantic models for fingerprint metadata and dev outputs.
- Use deterministic structured serialization; never pickle and never hash
  `repr()` output.
- Reuse `CheckpointStore` and the existing Redis lease rather than adding keys
  outside the checkpoint namespace.
- Build a distinct flow per active run. Do not mutate one shared flow's
  `flow_id`, checkpointer, publisher holder, or resume seed concurrently.
- Make checkpoint completion monotonic: do not advance the in-memory parent ID
  until the required store write succeeds.
- For bounded retry edges, compute and apply the reset to scheduler state and
  `FlowContext` before checkpointing, then dispatch the retry target only after
  that checkpoint succeeds.
- Checkpoint only after node success and shared-state projection. Failed or
  cancelled nodes are never added to `completed_tasks`.
- Keep telemetry listener shielding unchanged. Required persistence is a core
  execution barrier, not a telemetry callback.
- Restore only from registered types and explicit projection rules. Reject a
  lossy critical result instead of continuing with a string representation.
- Configure dev flows with an allowlisted shared-data projector; never pass the
  complete live `shared_data` mapping to required persistence.
- Rebind trace/session/tool resources from the current process.
- Preserve gate parking semantics and the runner's exactly-once semaphore
  release bookkeeping.

### Known Risks / Gotchas

- **Callable predicates are not exportable.** Pass the existing declarative
  definition to the checkpointer while executing the separately rebuilt
  explicit graph.
- **Shared flow instances are concurrent today.** Per-run construction is
  mandatory; simply replacing `flow.flow_id` before `run_flow()` races.
- **Required write ordering changes failure behavior.** Cancel/settle any
  already active siblings when a barrier fails and release the lease without
  allowing new downstream work.
- **Lease heartbeat loss is a Redis failure.** Required mode must surface it to
  the active job rather than only logging from a background task.
- **Task index truth is on disk.** Pool restart must reread it; never restore an
  in-memory `TaskScheduler` snapshot.
- **A completed node can have external effects immediately before Redis fails.**
  Such a node will rerun. This is the documented at-least-once frontier and
  requires node-level idempotency; the feature does not claim distributed
  exactly-once execution.
- **Redis retention can expire.** An expired checkpoint is a cache miss only
  when the caller has not otherwise recorded that recovery was mandatory;
  ordinary new execution remains supported.

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| None | N/A | Existing `asyncdb`, Redis checkpoint store, Pydantic, and standard-library `hashlib` are sufficient |

---

## 8. Open Questions

- [x] **Cache identity scope** - Reuse is limited to the same stable `run_id`.
  A restarted job creates a new flow instance and supplies that existing ID;
  automatically generating another ID is a cache miss. *Resolved by user,
  2026-08-31.*
- [x] **Redis failure policy** - Any checkpoint persistence failure is a hard
  error and fails the job before downstream side effects execute. *Resolved by
  user, 2026-08-31.*

No unresolved design questions block task decomposition.

---

## 9. Worktree Strategy

**Isolation**: per-spec

Use one FEAT-480 worktree for all tasks. The engine barrier, serializer/resume
contract, dev-loop coordinator, and both runners change one execution protocol
and share tests; separate worktrees would force speculative interface commits
and repeated conflict resolution in `flow.py` and `runner.py`. Tasks should
still be committed atomically in dependency order: core registration/resume,
core required barrier, shared dev coordinator, dev-loop integration, dev-flow
integration, then runtime wiring/tests.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-08-31 | Jesus Lara (with Codex) | Initial formal spec from accepted FEAT-516 proposal and verified codebase contracts |
