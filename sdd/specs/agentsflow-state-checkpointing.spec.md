---
# SDD flow type and base branch (FEAT-145).
type: feature
base_branch: dev
---

# Feature Specification: AgentsFlow State Checkpointing (Two-Tier Persistence)

**Feature ID**: FEAT-399
**Date**: 2026-08-01
**Author**: Jesus Lara
**Status**: approved
**Target version**: next
**Brainstorm**: `sdd/proposals/agentsflow-state-checkpointing.brainstorm.md` (Option A)

---

## 1. Motivation & Business Requirements

> Give AgentsFlow LangGraph-parity state checkpointing — resume a long-running
> flow from its last completed node after a crash, deploy, or suspension —
> with a two-tier storage design: ephemeral Redis (TTL, self-cleaning) for the
> live checkpoint stream, and opt-in durable backends (SQLite/Postgres/Mongo)
> for indefinite persistence and later recovery.

### Problem Statement

LangGraph's most-praised capability is graph-state checkpointing: every step of
a long-running graph is persisted, so a run survives a crash, a deploy, or a
human-in-the-loop pause, and can be resumed from its last completed node — with
a checkpoint history enabling time-travel/re-fork. AgentsFlow has no equivalent:

- `PersistenceMixin` (FEAT-147) persists **final execution results** for
  audit — not recoverable state. A killed run is simply lost.
- The dev-loop orchestrator explicitly deferred checkpoint/resume (FEAT-377
  finding F006): gated runs hold a concurrency slot for their entire life
  because flows cannot suspend. A **confirmed internal consumer** is waiting.
- The scraping `FlowExecutor` (FEAT-222) hand-rolled JSON-file checkpointing
  because the framework offers nothing.

Unlike LangGraph, checkpoints must NOT live primarily in a transactional DB
(cleanup jobs, stalled rows). The design is two-tier: happy-path flows write
checkpoints to Redis and let them **expire** (retention policy per flow); only
suspended/durable flows are written to disk-backed stores for indefinite
recovery.

### Goals

- Checkpoint AgentsFlow state after every node completion, opt-in per flow,
  with zero behavior change when disabled.
- Resume from the last completed node (completed nodes never re-execute;
  in-flight nodes re-run — at-least-once per node), from any retained
  historical checkpoint (re-fork), on a fresh process.
- Ephemeral tier: Redis with per-flow retention TTL (default **24h**) and
  bounded history (default **10** checkpoints).
- Durable tier (opt-in): SQLite, Postgres, Mongo/DocumentDB via `asyncdb`,
  fed by three triggers — graceful-shutdown hook (15s deadline), explicit
  `suspend()`/`dump()` API, and per-flow `durable=True` write-through.
- Hybrid serialization: Pydantic type registry + **ormsgpack** hooks; never
  pickle. Checkpoints carry extracted `results` only by default
  (`checkpoint_include_responses=True` opt-in).
- Checkpoints reference conversational memory (session/chatbot ids) — they do
  NOT duplicate agent memory; resume re-attaches it.
- Programmatic flows (`add_node`/`add_edge`) are checkpointable via a new
  graph→definition export (`AgentsFlow.to_definition()`).
- Concurrency safety: Redis lease + heartbeat per flow_id; concurrent resume
  fails fast with `FlowLockedError`.
- Ops surface: aiohttp handlers to list/inspect/resume/delete, using the
  existing `parrot/handlers/` auth conventions.

### Non-Goals (explicitly out of scope)

- **AgentCrew checkpointing** — phase 2, separate spec, consuming the same
  `CheckpointStore` contract.
- **Dev-loop F006 integration** (suspend gated runs to release concurrency
  slots) — separate follow-up spec built on this feature.
- **Auto-resume-on-startup** — resume is programmatic or via HTTP only (v1).
- **Mid-node progress capture** — checkpoint granularity is node completion;
  nodes with side effects must be idempotent (documented).
- **Event-sourcing journal** (Redis Streams replay) — rejected in brainstorm
  Option C; a journal can later be added *under* the `CheckpointStore`
  contract if distributed execution lands.
- **Extending the FEAT-147 `ResultStorage` plane** — rejected in brainstorm
  Option B (contract mismatch: append-only audit vs. latest-pointer/TTL/
  history state).
- **LangGraph/`langgraph-checkpoint` dependency** — rejected (LangChain is
  removed); reference-only for schema concepts.
- Migration of the scraping `FlowExecutor` (FEAT-222) to this plane.

---

## 2. Architectural Design

### Overview

A new sub-package `parrot/bots/flows/core/checkpoint/` — a **sibling** of the
existing `core/storage/` results plane, deliberately separate from it
(recoverable *state* expires on success; audit *results* persist):

- **`FlowCheckpoint`** (Pydantic): flow identity + monotonic `checkpoint_id` +
  `parent_checkpoint_id` (time-travel chain), run `status`
  (`running | suspended | completed | failed`), the embedded `FlowDefinition`
  snapshot, the serialized FlowContext snapshot (results, completed set,
  completion order, shared_data, structured errors), per-node FSM states,
  memory refs (session_id/chatbot_id/user_id), and a `lossy` flag.
- **`FlowStateSerializer`**: type-registry layer (registered Pydantic models
  round-trip via `model_dump()` + type tag) over **ormsgpack** with
  default-hooks for everything else; unregistered objects degrade to a tagged
  repr and set `lossy=True` instead of failing the flow.
- **`CheckpointStore`** (ABC): `put / latest / get / history / list_flows /
  delete_flow / acquire_lease / renew_lease / release_lease / close`. Two
  families:
  - `RedisCheckpointStore` — ephemeral tier: per-flow latest pointer +
    history sorted-set trimmed to N, TTL refreshed on every write
    (default 86400s / history 10).
  - `DurableCheckpointStore` — asyncdb-backed: `sqlite`, `pg`, `mongodb`
    drivers (one parametrized implementation, FEAT-147 backend pattern).
- **`FlowCheckpointer`**: subscribes to AgentsFlow's node-event stream
  (`add_node_event_listener`), snapshots after each node completion,
  writes fire-and-forget (pending-task set awaited in `aclose()`, the
  `PersistenceMixin` discipline), owns write-through (`durable=True`),
  `dump()` (Redis → durable, mark `suspended`), and the resume lease
  (~60s TTL, heartbeat-renewed while the flow runs).
- **AgentsFlow API**: constructor opts (`checkpoint=True`,
  `checkpoint_retention=86400`, `checkpoint_history=10`,
  `checkpoint_include_responses=False`, `durable=False`), `suspend()`,
  classmethod `resume(flow_id, checkpoint_id=None, agent_registry=...)`
  (rebuild via `from_definition()`, pre-seed FlowContext with
  `mark_completed()`, scheduler executes only the frontier), and
  `to_definition()` (graph→`FlowDefinition` export; requires all nodes in
  `NODE_REGISTRY`, clear error otherwise).
- **`FlowRecoveryService`**: registers aiohttp `on_shutdown` / SIGTERM hook;
  suspends+dumps all active checkpointed flows within a 15s configurable
  deadline; flows that miss it are logged ERROR with their flow_ids (their
  last Redis checkpoint stays recoverable until TTL).
- **HTTP handlers** (`parrot/handlers/`): list suspended/recoverable flows,
  inspect checkpoint history, trigger resume, delete — behind the existing
  handlers auth conventions.

### Component Diagram

```
AgentsFlow.run_flow()
   │  node completed/failed events (add_node_event_listener)
   ▼
FlowCheckpointer ──serialize──▶ FlowStateSerializer (type registry + ormsgpack)
   │                                     │
   │ put() fire-and-forget               ▼
   ├──────────────▶ RedisCheckpointStore   (ephemeral: TTL 24h, history 10, lease)
   │                       │ dump() on suspend/shutdown
   │ write-through         ▼
   └─(durable=True)─▶ DurableCheckpointStore (asyncdb: sqlite | pg | mongodb)
                            ▲
AgentsFlow.resume(flow_id) ─┘ latest()/get() ─▶ from_definition() ─▶ run_flow()
FlowRecoveryService (on_shutdown, 15s) ─▶ suspend all active flows
HTTP handlers (list/history/resume/delete) ─▶ CheckpointStore
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `parrot/bots/flows/flow/flow.py` (`AgentsFlow`) | extends | constructor kwargs, listener wiring, `suspend()`, `resume()`, `to_definition()` |
| `parrot/bots/flows/flow/definition.py` (`FlowMetadata`) | extends | optional checkpoint config block |
| `parrot/bots/flows/core/context.py` (`FlowContext`) | extends | `to_snapshot()` helper + seed-from-snapshot; no field changes |
| `parrot/bots/flows/core/result.py` | depends on | fold `_serialise_result_value` into the type registry |
| `parrot/bots/flows/core/storage/` (FEAT-147) | pattern reuse only | AsyncDB backend pattern + fire-and-forget lifecycle; NO code coupling |
| `parrot/handlers/` | new handlers | checkpoint ops API + shutdown hook registration |
| `parrot/conf.py` | extends | `FLOW_CHECKPOINT_*` env vars |
| `pyproject.toml` | new dependency | `ormsgpack >= 1.5` |
| AgentCrew (`bots/flows/crew/`) | unaffected in v1 | phase 2 consumes the same `CheckpointStore` contract |

No breaking changes: everything is opt-in; default behavior is byte-identical.

### Data Models

```python
# parrot/bots/flows/core/checkpoint/model.py (NEW)
class MemoryRefs(BaseModel):
    session_id: Optional[str] = None
    chatbot_id: Optional[str] = None
    user_id: Optional[str] = None

class NodeStateSnapshot(BaseModel):
    node_id: str
    fsm_state: str                      # AgentTaskMachine state name
    completed_at: Optional[datetime] = None

class ContextSnapshot(BaseModel):
    initial_task: str
    results: dict[str, Any]             # serialized via FlowStateSerializer
    responses: Optional[dict[str, Any]] = None   # only when include_responses
    completed_tasks: list[str]
    completion_order: list[str]
    shared_data: dict[str, Any]
    errors: dict[str, dict[str, str]]   # node_id -> {type, message, repr}

class FlowCheckpoint(BaseModel):
    flow_id: str
    flow_name: str
    checkpoint_id: int                  # monotonic per flow
    parent_checkpoint_id: Optional[int] = None
    created_at: datetime
    status: Literal["running", "suspended", "completed", "failed"]
    definition: FlowDefinition          # embedded graph snapshot
    context: ContextSnapshot
    node_states: list[NodeStateSnapshot]
    memory_refs: MemoryRefs
    lossy: bool = False                 # a value degraded to tagged repr
```

### New Public Interfaces

```python
# parrot/bots/flows/core/checkpoint/store/base.py (NEW)
class CheckpointStore(ABC):
    async def put(self, checkpoint: FlowCheckpoint) -> None: ...
    async def latest(self, flow_id: str) -> Optional[FlowCheckpoint]: ...
    async def get(self, flow_id: str, checkpoint_id: int) -> Optional[FlowCheckpoint]: ...
    async def history(self, flow_id: str, limit: int = 10) -> list[FlowCheckpoint]: ...
    async def list_flows(self, status: Optional[str] = None) -> list[dict[str, Any]]: ...
    async def delete_flow(self, flow_id: str) -> None: ...
    async def acquire_lease(self, flow_id: str, holder: str, ttl: int = 60) -> bool: ...
    async def renew_lease(self, flow_id: str, holder: str, ttl: int = 60) -> bool: ...
    async def release_lease(self, flow_id: str, holder: str) -> None: ...
    async def close(self) -> None: ...

def get_checkpoint_store(arg: str | CheckpointStore | None) -> CheckpointStore: ...
    # factory, FEAT-147 get_result_storage() pattern:
    # "redis" | "sqlite" | "postgres" | "mongodb" | instance | None (env fallback)

# parrot/bots/flows/flow/flow.py (EXTENDED)
class AgentsFlow(PersistenceMixin):
    def __init__(self, name: str, *, checkpoint: bool = False,
                 checkpoint_retention: int = 86400, checkpoint_history: int = 10,
                 checkpoint_include_responses: bool = False,
                 durable: bool = False, **kwargs): ...
    def to_definition(self) -> FlowDefinition: ...          # NEW export
    async def suspend(self) -> FlowCheckpoint: ...           # NEW
    @classmethod
    async def resume(cls, flow_id: str, checkpoint_id: Optional[int] = None,
                     *, agent_registry: AgentRegistry,
                     store: str | CheckpointStore | None = None) -> "AgentsFlow": ...

# parrot/bots/flows/core/checkpoint/errors.py (NEW)
class FlowLockedError(RuntimeError): ...
class CheckpointNotFoundError(LookupError): ...
class FlowNotExportableError(ValueError): ...   # unregistered custom node
```

Configuration (in `parrot/conf.py`, mirroring `CREW_RESULT_STORAGE*` naming):

| Env var | Default | Purpose |
|---|---|---|
| `FLOW_CHECKPOINT_STORE` | `redis` | ephemeral store backend |
| `FLOW_CHECKPOINT_DURABLE_STORE` | unset | durable backend: `sqlite \| postgres \| mongodb` |
| `FLOW_CHECKPOINT_REDIS_TTL` | `86400` | retention (24h, resolved OQ4) |
| `FLOW_CHECKPOINT_HISTORY` | `10` | retained checkpoints per flow (resolved OQ4) |
| `FLOW_CHECKPOINT_SHUTDOWN_DEADLINE` | `15` | seconds for shutdown dump (resolved OQ6) |
| `FLOW_CHECKPOINT_LEASE_TTL` | `60` | resume lease TTL, heartbeat-renewed (resolved OQ3) |

---

## 3. Module Breakdown

### Module 1: Checkpoint Model + Errors
- **Path**: `parrot/bots/flows/core/checkpoint/model.py`, `errors.py`
- **Responsibility**: `FlowCheckpoint`, `ContextSnapshot`, `NodeStateSnapshot`,
  `MemoryRefs` Pydantic models; `FlowLockedError`, `CheckpointNotFoundError`,
  `FlowNotExportableError`.
- **Depends on**: existing `FlowDefinition` (flow/definition.py).

### Module 2: FlowStateSerializer (type registry + ormsgpack)
- **Path**: `parrot/bots/flows/core/checkpoint/serializer.py`
- **Responsibility**: register known Pydantic models (AIMessage, FlowResult, …)
  with type tags; ormsgpack encode/decode with default-hooks; tagged-repr
  degradation + `lossy` signaling; fold in `_serialise_result_value` behavior.
- **Depends on**: Module 1; new `ormsgpack` dependency.

### Module 3: CheckpointStore ABC + factory + config
- **Path**: `parrot/bots/flows/core/checkpoint/store/base.py`, `factory.py`;
  `parrot/conf.py` additions.
- **Responsibility**: the store contract (incl. lease methods),
  `get_checkpoint_store()` factory, `FLOW_CHECKPOINT_*` env vars.
- **Depends on**: Module 1.

### Module 4: RedisCheckpointStore (ephemeral tier)
- **Path**: `parrot/bots/flows/core/checkpoint/store/redis.py`
- **Responsibility**: latest pointer + history zset trimmed to N + TTL refresh
  per write; lease via `SET NX PX` + ownership-checked renew/release.
- **Depends on**: Modules 1–3; AsyncDB `redis` driver (FEAT-147 pattern).

### Module 5: DurableCheckpointStore (sqlite | pg | mongodb)
- **Path**: `parrot/bots/flows/core/checkpoint/store/durable.py`
- **Responsibility**: one asyncdb-parametrized implementation covering the
  three drivers; schema/collection for checkpoints keyed
  `(flow_id, checkpoint_id)`; `list_flows(status="suspended")`.
- **Depends on**: Modules 1–3; `asyncdb` (already shipped).

### Module 6: FlowCheckpointer
- **Path**: `parrot/bots/flows/core/checkpoint/checkpointer.py`
- **Responsibility**: node-event subscription; snapshot assembly (FlowContext
  → ContextSnapshot, FSM states, memory refs); fire-and-forget writes +
  `aclose()`; write-through mode; `dump()`; lease acquire/heartbeat/release.
- **Depends on**: Modules 1–5.

### Module 7: AgentsFlow wiring + `to_definition()` export
- **Path**: `parrot/bots/flows/flow/flow.py`, `flow/definition.py`,
  `core/context.py`
- **Responsibility**: constructor opts; checkpointer lifecycle;
  `to_definition()` (NODE_REGISTRY round-trip validation,
  `FlowNotExportableError`); `suspend()`; `resume()` (load → lease →
  `from_definition()` → seed `mark_completed()` → run frontier);
  `FlowContext.to_snapshot()`; `FlowMetadata` checkpoint block.
- **Depends on**: Modules 1–6.

### Module 8: FlowRecoveryService (graceful shutdown)
- **Path**: `parrot/bots/flows/core/checkpoint/recovery.py`
- **Responsibility**: track active checkpointed flows; aiohttp `on_shutdown` /
  SIGTERM hook; 15s-deadline parallel suspend+dump; ERROR log with flow_ids
  for misses.
- **Depends on**: Modules 6–7.

### Module 9: HTTP ops handlers
- **Path**: `parrot/handlers/flows/checkpoints.py` (follow existing handlers
  layout/auth conventions)
- **Responsibility**: list suspended/recoverable flows; checkpoint history;
  trigger resume; delete flow checkpoints.
- **Depends on**: Modules 3–7.

### Module 10: Documentation + examples
- **Path**: `docs/orchestration/agentsflow.md` (extend),
  `examples/flow/agentsflow_checkpointing.py` (new)
- **Responsibility**: user guide (opt-in, two tiers, suspend/resume,
  idempotency caveat), runnable example.
- **Depends on**: Modules 1–9.

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_flow_checkpoint_model_roundtrip` | M1 | FlowCheckpoint JSON/dict round-trip incl. embedded FlowDefinition |
| `test_serializer_registered_pydantic_roundtrip` | M2 | AIMessage-like registered model survives encode/decode with type identity |
| `test_serializer_unregistered_degrades_lossy` | M2 | Unknown object → tagged repr, `lossy=True`, no exception |
| `test_serializer_errors_structured` | M2 | `FlowContext.errors` Exceptions → {type, message, repr} |
| `test_factory_backend_selection_and_env_fallback` | M3 | arg > env > default resolution; unknown name raises |
| `test_redis_store_latest_history_trim_ttl` | M4 | latest pointer, zset trimmed to N=10, TTL refreshed on write |
| `test_redis_lease_acquire_conflict_renew_expiry` | M4 | second acquire fails; renew only by holder; expiry allows takeover |
| `test_durable_store_put_get_list_suspended` | M5 | sqlite driver: put/get/history/list_flows(status) round-trip |
| `test_checkpointer_writes_on_node_completion` | M6 | node event → checkpoint with parent chain and monotonic ids |
| `test_checkpointer_write_failure_does_not_break_flow` | M6 | store raising → warning logged, flow result unaffected |
| `test_checkpointer_results_only_vs_include_responses` | M6 | responses absent by default, present with flag |
| `test_to_definition_roundtrip` | M7 | programmatic add_node/add_edge flow → definition → from_definition equivalence |
| `test_to_definition_unregistered_node_raises` | M7 | custom Node not in NODE_REGISTRY → FlowNotExportableError naming it |
| `test_resume_skips_completed_nodes` | M7 | seeded FlowContext: completed nodes not re-executed, frontier runs |
| `test_resume_locked_raises_flowlockederror` | M7 | active lease → FlowLockedError |
| `test_resume_expired_checkpoint_raises` | M7 | TTL-expired / missing → CheckpointNotFoundError |
| `test_recovery_service_suspends_within_deadline` | M8 | active flows dumped on shutdown; miss → ERROR with flow_ids |
| `test_http_list_history_resume_delete` | M9 | handler contract incl. auth wiring |

### Integration Tests
| Test | Description |
|---|---|
| `test_e2e_checkpoint_kill_resume` | Run flow, stop after node K, resume in fresh objects, assert nodes ≤K not re-executed and final FlowResult correct |
| `test_e2e_refork_from_historical_checkpoint` | Resume with `checkpoint_id` < latest re-runs downstream nodes only |
| `test_e2e_durable_write_through` | `durable=True` writes both tiers on every checkpoint |
| `test_e2e_suspend_dump_resume_from_durable` | suspend() → Redis flushed to sqlite → resume from durable store |
| `test_e2e_memory_refs_reattach` | resumed flow re-binds agent_registry + memory refs, no memory duplication |

### Test Data / Fixtures
```python
@pytest.fixture
def linear_flow_definition():
    """3-node declarative FlowDefinition (start → agent → end) with fake agents."""

@pytest.fixture
def fake_checkpoint_store():
    """In-memory CheckpointStore for checkpointer/AgentsFlow tests (no Redis)."""

@pytest.fixture
def redis_store():
    """RedisCheckpointStore against test Redis; skipped when unavailable."""
```

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] With checkpointing disabled (default), AgentsFlow behavior and public
      API are byte-identical — existing test suite passes unmodified.
- [ ] A flow run with `checkpoint=True` writes one checkpoint per completed
      node to Redis, with TTL 86400s and history trimmed to 10 by default,
      both overridable per-flow and via `FLOW_CHECKPOINT_REDIS_TTL` /
      `FLOW_CHECKPOINT_HISTORY`.
- [ ] `AgentsFlow.resume(flow_id)` on a fresh process continues from the last
      completed node: completed nodes are not re-executed (verified by
      counters), in-flight nodes re-run.
- [ ] `resume(flow_id, checkpoint_id=<older>)` re-forks from that checkpoint.
- [ ] Checkpoints serialize via type registry + ormsgpack; no pickle anywhere;
      unregistered values degrade to tagged reprs with `lossy=True` and never
      fail the flow.
- [ ] Checkpoints contain extracted `results` only by default; raw `responses`
      included only with `checkpoint_include_responses=True`.
- [ ] Checkpoints store memory references (session/chatbot/user ids), not
      conversational memory content.
- [ ] All three durable triggers work: `suspend()`/`dump()` API; `durable=True`
      write-through; graceful-shutdown hook dumping active flows within a 15s
      default deadline and logging ERROR with flow_ids for misses.
- [ ] All three durable backends pass the store contract suite: `sqlite`,
      `postgres` (skipped-if-unavailable), `mongodb` (skipped-if-unavailable).
- [ ] Concurrent resume of the same flow_id fails fast with `FlowLockedError`
      while a heartbeat-renewed lease (~60s TTL) is held; takeover possible
      after holder death (lease expiry).
- [ ] Programmatic flows export via `to_definition()` and are resumable;
      unregistered custom nodes raise `FlowNotExportableError` naming the node.
- [ ] HTTP handlers (list/history/resume/delete) work behind the existing
      `parrot/handlers/` auth conventions.
- [ ] Checkpoint write failures never fail or block a flow (warning only).
- [ ] All unit + integration tests above pass (`pytest`); docs updated
      (`docs/orchestration/agentsflow.md`) + runnable example added.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> Verified against `dev` on 2026-08-01 (this session).

### Verified Imports
```python
# These imports have been confirmed to work:
from parrot.bots.flows.core.context import FlowContext, AgentNotFoundError
from parrot.bots.flows.core.storage import PersistenceMixin            # core/storage/__init__.py re-exports
from parrot.bots.flows.core.storage.backends import ResultStorage, get_result_storage
from parrot.bots.flows.flow.definition import FlowDefinition, NodeDefinition
from parrot.bots.flows.core.result import _serialise_result_value     # imported by flow/flow.py:33
```

### Existing Class Signatures
```python
# packages/ai-parrot/src/parrot/bots/flows/flow/flow.py
class AgentsFlow(PersistenceMixin):                                   # line 159
    def add_node(self, node: Node) -> None: ...                       # line 234
    def add_edge(self, from_, to, ...) -> None: ...                   # line 251
    def add_node_event_listener(self, callback) -> None: ...          # line 307
    def _notify_node_event(self, event, node_id, info) -> None: ...   # line 322 (shielded — listener errors never break the scheduler)
    @classmethod
    def from_definition(cls, definition, ...) -> "AgentsFlow": ...    # line 362
    async def _run_node(self, node, ctx, deps, queue) -> None: ...    # line 556 (manages FSM, pushes CompletionEvent)
    async def run_flow(self, ctx) -> FlowResult: ...                  # line 693 (event-driven scheduler)

# packages/ai-parrot/src/parrot/bots/flows/core/context.py
@dataclass
class FlowContext:                                                    # line 52
    initial_task: str                                                 # line 68
    results: Dict[str, Any]                                           # line 69
    responses: Dict[str, Any]                                         # line 72
    node_metadata: Dict[str, NodeExecutionInfo]                       # line 75
    completion_order: List[str]                                       # line 78
    errors: Dict[str, Exception]                                      # line 81  (live Exceptions — must serialize structured)
    active_tasks: Set[str]                                            # line 84
    completed_tasks: Set[str]                                         # line 87
    shared_data: Dict[str, Any]                                       # line 90
    agent_registry: Optional["AgentRegistry"]                         # line 93  (NOT serializable — re-bound on resume)
    synthesis_client: Optional[Any]                                   # line 100 (NOT serializable — re-bound on resume)
    trace_context: Optional["TraceContext"]                           # line 108 (re-seeded on resume)
    def resolve_agent(self, agent_ref: AgentRef) -> AgentLike: ...    # line 119 (raises AgentNotFoundError)
    def mark_completed(self, node_id, result=None, response=None, metadata=None) -> None: ...  # line 174

# packages/ai-parrot/src/parrot/bots/flows/core/storage/backends/base.py
class ResultStorage(ABC):                                             # line 8  (pattern reference ONLY — checkpoints get their own ABC)
    async def save(self, collection: str, document: dict[str, Any]) -> None: ...  # line 18
    async def close(self) -> None: ...                                # line 27

# packages/ai-parrot/src/parrot/bots/flows/core/storage/backends/redis.py
class RedisResultStorage(ResultStorage):                              # line 21
    def __init__(self, dsn=None, ttl=None): ...                       # line 29 (AsyncDB redis driver; TTL default CREW_RESULT_STORAGE_REDIS_TTL = 604800s)

# packages/ai-parrot/src/parrot/bots/flows/flow/definition.py
class NodeDefinition(BaseModel): ...                                  # line 125
class EdgeDefinition(BaseModel): ...                                  # line 195
class FlowMetadata(BaseModel): ...                                    # line 254
class FlowDefinition(BaseModel): ...                                  # line 296 (full JSON round-trip: model_validate / model_dump_json)

# packages/ai-parrot/src/parrot/bots/flows/core/fsm.py
class AgentTaskMachine(StateMachine): ...                             # statemachine lib; per-node states running/completed/failed
```

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `FlowCheckpointer` | `AgentsFlow.add_node_event_listener()` | listener registration | `flow/flow.py:307` |
| `FlowCheckpointer` | `AgentsFlow._notify_node_event()` | receives shielded events | `flow/flow.py:322` |
| `AgentsFlow.resume()` | `AgentsFlow.from_definition()` | graph reconstruction | `flow/flow.py:362` |
| `AgentsFlow.resume()` | `FlowContext.mark_completed()` | pre-seed completed nodes | `core/context.py:174` |
| `get_checkpoint_store()` | `get_result_storage()` pattern | factory precedent (copy, don't couple) | `core/storage/backends/factory.py:34` |
| `RedisCheckpointStore` | AsyncDB redis driver | connection pattern | `core/storage/backends/redis.py:29` |
| `FlowStateSerializer` | `_serialise_result_value` | fold into type registry | `core/result.py` (imported at `flow/flow.py:33`) |

### Key Constants & Prior Art
- `CREW_RESULT_STORAGE_REDIS_TTL` → `int`, 604800s default (`parrot/conf.py`;
  used at `backends/redis.py:16,42`) — naming precedent for `FLOW_CHECKPOINT_*`.
- `asyncdb >= 2.11.6` already a core dependency (pyproject line 75); extras
  incl. `mongodb` at line 143; drivers: `sqlite`, `pg`, `mongodb`, `redis`.
- Prior art (reference only, do not modify):
  `packages/ai-parrot-tools/src/parrot_tools/scraping/flow_executor.py`
  (`_write_checkpoint/_load_checkpoint/run(resume_from=...)`, FEAT-222).
- Confirmed consumer: `sdd/state/FEAT-377/findings/F006-g6-checkpoint-resume.md`.

### Does NOT Exist (Anti-Hallucination)
- ~~`parrot/bots/flows/core/checkpoint/`~~ — no checkpoint package exists yet;
  every module in §3 is new.
- ~~`AgentsFlow.resume()` / `AgentsFlow.suspend()` / `AgentsFlow.to_definition()`~~ — no resume/suspend/export API exists on any executor.
- ~~`ormsgpack` / `msgpack` in pyproject.toml~~ — NOT currently a dependency; `ormsgpack` must be added.
- ~~SQLite `ResultStorage` backend~~ — FEAT-147 factory only knows `redis | postgres | documentdb`; do not "reuse" a sqlite results backend.
- ~~`FlowContext.to_snapshot()` / `from_snapshot()`~~ — no serialization helpers exist on FlowContext today.
- ~~`CheckpointStore`, `FlowCheckpoint`, `FlowCheckpointer`, `FlowStateSerializer`, `FlowRecoveryService`, `FlowLockedError`~~ — all names introduced by this spec.
- ~~LangGraph / `langgraph-checkpoint` anywhere in the tree~~ — LangChain is removed; reference-only.

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- **FEAT-147 backend pattern** (`core/storage/backends/`): AsyncDB-based
  stores, factory with arg > env > default resolution, lazy `_ensure()`
  connection, idempotent `close()` — replicate for `checkpoint/store/`.
- **PersistenceMixin lifecycle discipline** (`core/storage/persistence.py`):
  fire-and-forget writes tracked in a pending-task set, awaited in `aclose()`;
  failures log a warning and never propagate into the flow.
- Async-first throughout; Pydantic models for all structures; Google-style
  docstrings + strict type hints; `self.logger` (never print).
- HTTP handlers follow the existing `parrot/handlers/` layout and auth
  conventions (resolved OQ5) — no new auth mechanism.
- Config additions in `parrot/conf.py` mirror `CREW_RESULT_STORAGE*` naming.

### Known Risks / Gotchas
- **`FlowContext.errors` holds live `Exception` objects** — serialize as
  structured `{type, message, repr}`; never attempt to reconstruct Exception
  instances on resume.
- **`agent_registry` / `synthesis_client` / `trace_context` are not
  serializable** — excluded from `ContextSnapshot`; re-bound/re-seeded by
  `resume()` (registry is a required resume argument).
- **At-least-once node semantics** — a node in-flight at crash time re-runs
  entirely on resume; document the idempotency requirement for nodes with
  side effects.
- **Lossy checkpoints** — unregistered result types degrade to tagged reprs;
  a resume from a lossy checkpoint logs a warning that dependency results for
  affected nodes are degraded strings.
- **`to_definition()` coverage** — only nodes present in `NODE_REGISTRY`
  survive the export round-trip; enabling checkpointing on a flow with an
  unregistered custom node must fail early (`FlowNotExportableError`), not at
  resume time.
- **Shutdown deadline** — 15s default fits a 30s k8s grace period; many large
  active flows may exceed it — write-through (`durable=True`) is the
  recommended mode for critical flows; misses are ERROR-logged, not silent.
- **Redis lease is advisory** — protects against double-resume, not against
  split-brain writes from a zombie holder that lost its lease mid-node;
  acceptable for v1 (documented), matches at-least-once semantics.
- **History trimming vs. re-fork** — re-fork targets must be within the
  retained window (10 by default); older checkpoints are gone by design.
- **Checkpoint size** — results-only default keeps Redis values small;
  `checkpoint_include_responses=True` is documented as heavy.

### External Dependencies
| Package | Version | Reason |
|---|---|---|
| `ormsgpack` | `>= 1.5` | Binary checkpoint encoding (msgpack format); native Pydantic/datetime/UUID serialization; Rust wheels (resolved OQ1) |
| `asyncdb` | `>= 2.11.6` (existing) | Durable store drivers (`sqlite`, `pg`, `mongodb`) + Redis driver |
| `aiohttp` | existing | HTTP ops handlers + `on_shutdown` hook |
| `pydantic` | v2 (existing) | checkpoint models + type registry |

---

## Worktree Strategy

- **Default isolation unit**: `per-spec` — all tasks sequential in one
  worktree (`feat-399-agentsflow-state-checkpointing`).
- **Rationale**: the `FlowCheckpoint` model and serializer (M1–M2) are
  upstream of every other module; splitting worktrees would serialize on
  merges anyway. Within the single worktree, M4/M5 (store backends) and M9
  (HTTP) are good candidates for parallel subagent dispatch once M1–M3 land.
- **Cross-feature dependencies**: none — no in-flight spec owns
  `bots/flows/flow/flow.py` or `core/context.py` (FEAT-306/307 saved-crews
  work lives in `bots/flows/crew/`).

---

## 8. Open Questions

> All brainstorm questions were resolved interactively on 2026-08-01; echoed
> here for the audit trail. No unresolved questions block implementation.

- [x] `msgpack` vs `ormsgpack` — *Resolved in brainstorm*: **`ormsgpack`** — native Pydantic/datetime/UUID serialization, faster, langgraph-checkpoint precedent.
- [x] Checkpoint raw `responses` or only extracted `results`? — *Resolved in brainstorm*: **Only `results` by default** (sufficient for `get_input_for_node()` on resume) + opt-in `checkpoint_include_responses=True`.
- [x] Concurrent-resume locking — *Resolved in brainstorm*: **Redis lease + heartbeat** — ~60s TTL lock per flow_id renewed while running; second resume fails fast with `FlowLockedError`; dead holder's lease expires → takeover possible.
- [x] Defaults: retention TTL and history N — *Resolved in brainstorm*: **TTL 24h (86400s) / history 10** — configurable per-flow and via `FLOW_CHECKPOINT_REDIS_TTL` / `FLOW_CHECKPOINT_HISTORY`.
- [x] HTTP handlers auth model — *Resolved in brainstorm*: **Reuse existing `parrot/handlers/` auth conventions** — no new security surface.
- [x] Graceful-shutdown deadline — *Resolved in brainstorm*: **15s default**, configurable; misses logged ERROR with flow_ids; last Redis checkpoint stays recoverable until TTL.
- [x] Resume only for definition-based flows? — *Resolved in brainstorm*: **No — v1 includes `AgentsFlow.to_definition()`** so programmatic flows are resumable; nodes must be in `NODE_REGISTRY` (clear error otherwise).
- [x] Phase 2 scope — *Resolved in brainstorm*: two separate follow-up specs — (a) AgentCrew on the same `CheckpointStore`; (b) dev-loop F006 gated-run suspend/resume.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-08-01 | Jesus Lara | Initial draft from brainstorm (Option A, all OQs resolved) |
