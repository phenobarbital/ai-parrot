---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Brainstorm: AgentsFlow State Checkpointing (Two-Tier Persistence)

**Date**: 2026-08-01
**Author**: Jesus Lara
**Status**: exploration
**Recommended Option**: A

---

## Problem Statement

LangGraph's most-praised capability is graph-state checkpointing: every step of a
long-running graph is persisted (natively to Postgres), so a run can survive a crash,
a deploy, or a human-in-the-loop pause, and later be resumed from its last completed
node — with a checkpoint history enabling time-travel/re-fork.

AgentsFlow (`parrot/bots/flows/flow/flow.py`, FEAT-163) has no equivalent. Today:

- `PersistenceMixin` (FEAT-147) persists **final execution results** for audit/logs —
  it is not recoverable state; a killed run is simply lost.
- The dev-loop orchestrator explicitly deferred checkpoint/resume
  (FEAT-377 finding F006: gated runs hold a concurrency slot for their entire life
  because there is no way to suspend and resume a flow). This is a **confirmed
  internal consumer** waiting for this feature.
- The scraping `FlowExecutor` (FEAT-222) had to hand-roll its own JSON-file
  checkpointing because the framework offers nothing.

Unlike LangGraph, we do NOT want checkpoints to live primarily in a transactional
DB — that forces cleanup jobs and leaves stalled rows for flows that finished fine.
The design is **two-tier**:

1. **Ephemeral tier (default)**: the live checkpoint stream goes to **Redis** with a
   per-flow retention policy (TTL). Happy-path flows deliver their results and their
   checkpoints simply expire — zero cleanup, zero stalled objects.
2. **Durable tier (opt-in)**: a pluggable client (SQLite, Postgres, Mongo/DocumentDB)
   persists suspended flows indefinitely — on graceful server shutdown, via an
   explicit `suspend()`/`dump()` API, or write-through for flows declared
   `durable=True` — so they can be recovered and re-started later.

**Affected users**: framework developers building long-running/multi-step flows;
ops (server restarts/deploys no longer kill in-flight work); the dev-loop runner
(F006); future HITL flows that pause for hours/days.

## Constraints & Requirements

- **Scope v1**: AgentsFlow only. AgentCrew arrives in a phase 2 on top of the same
  abstraction — the checkpoint plane must not hard-code AgentsFlow internals into
  its storage contract.
- **Recovery semantics**: resume from last completed node (completed nodes are NOT
  re-executed; in-flight nodes re-run from scratch — at-least-once per node), PLUS a
  configurable **checkpoint history** per flow (time-travel / re-fork from an
  earlier checkpoint, LangGraph-style `checkpoints list`).
- **Checkpoint content**: graph state (FlowContext: results, completed set,
  completion order, shared_data, errors) + per-node FSM states + **references** to
  conversational memory (session_id / chatbot_id pointers into the existing Redis
  memory) — the checkpoint does NOT duplicate agent conversational state; resume
  re-attaches the live memory.
- **Serialization**: hybrid — known Pydantic models (AIMessage, FlowResult, …) via
  `model_dump()` + a type registry for faithful round-trips; everything else
  (arbitrary node results, FlowContext internals) via **ormsgpack + custom hooks**
  (resolved: `ormsgpack` over `msgpack` — native Pydantic/datetime/UUID support,
  faster, langgraph-checkpoint precedent). More surface, but more information
  correctly serialized. No pickle (unsafe). Checkpoints carry extracted `results`
  only by default; raw `responses` are opt-in via `checkpoint_include_responses`.
- **Durable dump triggers (all three)**: (a) automatic graceful-shutdown hook,
  (b) explicit `suspend()`/`dump()` API, (c) per-flow `durable=True` write-through.
- **Resume paths**: programmatic API (`AgentsFlow.resume(...)`) + aiohttp HTTP
  handlers (list suspended flows, inspect checkpoint history, resume, delete).
  No auto-resume-on-startup in v1.
- **Durable backends v1 (all three)**: SQLite, Postgres, Mongo/DocumentDB — via the
  already-shipped `asyncdb` drivers, mirroring the FEAT-147 backend pattern.
- Async-first throughout; checkpoint writes must never block or fail the flow
  (fire-and-forget + warning, same contract as `PersistenceMixin._save_result`).
- No LangChain/LangGraph runtime dependency (project rule: LangChain is removed).

---

## Options Explored

### Option A: Dedicated Checkpoint Plane — `FlowCheckpointer` + pluggable `CheckpointStore`

A new sub-package `parrot/bots/flows/core/checkpoint/` that is a **sibling** of the
existing `core/storage/` results plane, deliberately kept separate from it:

- `FlowCheckpoint` (Pydantic): flow_id, checkpoint_id (monotonic), parent
  checkpoint_id, status (`running | suspended | completed | failed`), the
  `FlowDefinition` snapshot (already fully JSON-serializable), the serialized
  FlowContext snapshot, per-node FSM states, and memory refs.
- `CheckpointStore` (ABC): `put / latest / get / history / list_flows /
  delete_flow / close`. Two families: `RedisCheckpointStore` (ephemeral tier —
  per-flow TTL + history trimmed to N via sorted-set) and `DurableCheckpointStore`
  (asyncdb-backed: `sqlite`, `pg`, `mongodb` drivers).
- `FlowStateSerializer`: type-registry layer (Pydantic `model_dump` + type tag for
  registered models) on top of msgpack with default/ext hooks; unregistered objects
  degrade to a tagged repr and mark the checkpoint `lossy=True` instead of failing.
- `FlowCheckpointer`: subscribes to AgentsFlow's existing node-event stream
  (`add_node_event_listener`) and writes a checkpoint after every node completion;
  owns the ephemeral→durable `dump()` movement and the three durable triggers.
- AgentsFlow grows `resume()` (rebuild graph from the checkpoint's FlowDefinition
  via the existing `from_definition()`, pre-seed FlowContext with completed nodes,
  let the event-driven scheduler skip them) and `suspend()`.
- aiohttp handlers under `parrot/handlers/` for the ops surface; a
  `FlowRecoveryService` registers the graceful-shutdown hook (aiohttp
  `on_shutdown` / signal handler) that suspends+dumps all active flows.

✅ **Pros:**
- Clean separation of concerns: recoverable *state* vs. audit *results*
  (FEAT-147 deliberately solved only the latter; its `save(collection, document)`
  contract has no latest-pointer, versioning, or TTL-per-flow semantics).
- Storage contract is executor-agnostic → AgentCrew phase 2 plugs into the same
  plane without rework.
- Zero changes to the hot scheduler path: checkpointing rides the existing
  `_notify_node_event` listener mechanism, already shielded against listener errors.
- Checkpoint history + parent pointers give LangGraph-parity time-travel for free.
- Redis tier self-cleans via TTL — the original design goal.

❌ **Cons:**
- Most new surface of the three options (model + serializer + 2 store families +
  checkpointer + resume + HTTP).
- Listener-driven capture means the checkpoint is only as fresh as the last node
  completion — mid-node progress is not captured (acceptable: at-least-once per
  node is the agreed semantic).
- Programmatic flows built with `add_node()`/`add_edge()` have no `FlowDefinition`
  to rebuild from — resolved: v1 ships a graph→definition export
  (`AgentsFlow.to_definition()`) so they are resumable too; nodes must be in
  `NODE_REGISTRY` to survive the round-trip.

📊 **Effort:** High

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `ormsgpack` >= 1.5 | Binary checkpoint encoding (msgpack format) with native Pydantic/datetime/UUID support | **New dependency** (resolved over `msgpack`); Rust wheels for linux/mac/win; what langgraph-checkpoint uses |
| `asyncdb` >= 2.11.6 | Durable store drivers: `sqlite`, `pg`, `mongodb` | Already a core dependency; same pattern as FEAT-147 backends |
| `redis.asyncio` (via asyncdb `redis` driver) | Ephemeral tier: TTL keys + history zset | Already shipped |
| `pydantic` v2 | `FlowCheckpoint` model + type-registry serialization | Already core |
| `aiohttp` | HTTP resume/ops handlers + `on_shutdown` hook | Already core |

🔗 **Existing Code to Reuse:**
- `parrot/bots/flows/flow/flow.py` — `add_node_event_listener()` (line 307) and
  `_notify_node_event()` (line 322): the event stream the checkpointer subscribes to;
  `from_definition()` (line 362): graph reconstruction on resume.
- `parrot/bots/flows/flow/definition.py` — `FlowDefinition` (line 296): already a
  complete JSON-serializable snapshot of the graph; embed it in the checkpoint.
- `parrot/bots/flows/core/context.py` — `FlowContext` (line 52): the exact state to
  snapshot/restore; `mark_completed()` (line 174) pre-seeds resumed runs.
- `parrot/bots/flows/core/storage/backends/redis.py` — `RedisResultStorage`
  (line 21): AsyncDB-over-Redis + TTL pattern (`CREW_RESULT_STORAGE_REDIS_TTL`,
  default 7 days) to mirror for the ephemeral store.
- `parrot/bots/flows/core/storage/persistence.py` — `PersistenceMixin`: the
  fire-and-forget + `_persist_tasks` + `aclose()` lifecycle discipline to replicate.
- `parrot/bots/flows/core/result.py` — `_serialise_result_value`: existing
  result-serialization helper to fold into the type registry.

---

### Option B: Extend the FEAT-147 Results Plane (`ResultStorage` + `PersistenceMixin`)

Reuse the existing `ResultStorage` ABC and its Redis/Postgres/DocumentDB backends:
add `flow_checkpoints` collections, extend `PersistenceMixin` with
`_save_checkpoint()` / `_load_checkpoint()`, add an SQLite backend, and hang resume
off the existing `fetch()/list()/get()` read API.

✅ **Pros:**
- Least new code: three backends, the factory (`get_result_storage`), env-var
  config, and the mixin lifecycle already exist and are battle-tested.
- One storage configuration story for users (`CREW_RESULT_STORAGE` covers both).

❌ **Cons:**
- Contract mismatch: `save(collection, document)` is append-only audit logging —
  no latest-checkpoint pointer, no compare-and-swap, no per-flow TTL/retention, no
  history trimming. Retrofitting those onto `ResultStorage` bloats an ABC that
  third parties already subclass (its docstring explicitly promises stability).
- Conflates two lifecycles the two-tier design wants opposed: results should
  *persist* after a run; checkpoints should *expire* after a happy run.
- The ephemeral/durable split (Redis → dump → SQLite/PG/Mongo) doesn't map onto a
  single-backend mixin — you'd end up building Option A's checkpointer anyway,
  just entangled with the results plane.
- `RedisResultStorage.list()` does full SCANs — inadequate as a hot checkpoint
  read path.

📊 **Effort:** Medium (deceptively — grows toward High as the contract mismatch surfaces)

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `asyncdb` >= 2.11.6 | Add an SQLite `ResultStorage` backend | Only new backend needed |
| `msgpack` >= 1.0.8 | Same serializer need as Option A | New dependency either way |

🔗 **Existing Code to Reuse:**
- `parrot/bots/flows/core/storage/backends/` — everything (base.py, redis.py,
  postgres.py, documentdb.py, factory.py).
- `parrot/bots/flows/core/storage/persistence.py` — `PersistenceMixin` extended
  in place.

---

### Option C (unconventional): Event-Sourced Journal with Replay (Redis Streams)

Instead of snapshot checkpoints, append every scheduler event
(`node_started`, `node_completed(result)`, `node_failed(error)`, `edge_taken`) to a
per-flow **Redis Stream** (`XADD` with `MAXLEN` trimming; stream TTL = retention
policy). Resume = replay the journal through a fresh FlowContext to reconstruct
state; durable dump = copy the stream into SQLite/Postgres/Mongo as an event table.
Prior art in-repo: `RedisStreamsBackend` (TASK-1789) already does durable
at-least-once Redis Streams for distributed messaging.

✅ **Pros:**
- The full history requirement falls out naturally — every intermediate state is
  reconstructible, not just N retained snapshots; perfect audit trail.
- Appends are tiny and fast (only the delta, never the whole context) — cheapest
  hot path of the three for large flows.
- Composable with future distributed execution (streams are consumable by workers).

❌ **Cons:**
- Replay correctness is a hard invariant: every event type must serialize/replay
  deterministically forever; schema evolution of events is much harder than
  versioning one snapshot model.
- Resume latency grows with flow length unless periodic snapshot compaction is
  added — at which point you've built Option A *plus* a journal.
- Significantly harder to inspect/debug operationally ("what state is flow X in?"
  requires a replay, not a `GET`).
- Overkill for the agreed semantics (resume-from-last-completed + N-history).

📊 **Effort:** High

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `redis.asyncio` | XADD/XRANGE/XTRIM per-flow streams | Already shipped |
| `msgpack` >= 1.0.8 | Event payload encoding | New dependency |
| `asyncdb` | Durable event-table dump | Already shipped |

🔗 **Existing Code to Reuse:**
- `RedisStreamsBackend` (TASK-1789) — durable at-least-once streams pattern.
- Same AgentsFlow event-listener hook as Option A.

---

### Option D (evaluated and rejected): Adopt `langgraph-checkpoint`

Using LangChain's `langgraph-checkpoint` / `langgraph-checkpoint-postgres` packages
directly (or subclassing `BaseCheckpointSaver`) is rejected outright: the project
rule is "Never subclass LangChain components — LangChain is removed". Their schema
is nonetheless a useful *reference*: checkpoint = (channel values + versions +
pending writes), ormsgpack encoding, thread_id/checkpoint_id addressing, parent
pointers for time-travel — Option A's `FlowCheckpoint` mirrors those concepts
without the dependency.

---

## Recommendation

**Option A** is recommended because:

- It is the only option whose storage contract actually matches the agreed
  requirements: latest-pointer reads, per-flow TTL retention, bounded history with
  parent pointers, and an ephemeral→durable dump lifecycle. Option B would have to
  retrofit all four onto a stable third-party-subclassed ABC whose semantics are
  append-only audit logging — the "less effort" is illusory.
- It keeps the two planes (recoverable state vs. audit results) independently
  configurable, which is the core of the two-tier idea: checkpoints *expire* on
  success, results *persist*. FEAT-147 got that separation right for results;
  checkpointing deserves the same.
- Option C's journal is elegant but trades our actual requirement
  (resume-from-last-completed, N snapshots) for replay-forever complexity; if
  distributed flow execution ever lands, a journal can be added *under* Option A's
  `CheckpointStore` contract later.
- What we trade off: more upfront surface (model, serializer, two store families,
  checkpointer, resume, HTTP). Mitigated by heavy reuse — the AsyncDB backend
  pattern, the fire-and-forget lifecycle, and the node-event stream all exist; and
  the serializer/store/HTTP pieces decompose into cleanly bounded tasks.

---

## Feature Description

### User-Facing Behavior

- **Opt-in per flow**: `AgentsFlow(name=..., checkpoint=True, checkpoint_retention=86400, checkpoint_history=10, checkpoint_include_responses=False, durable=False)` — or via `FlowMetadata` in a `FlowDefinition`. Default off (zero behavior change for existing users). Defaults: retention 24h, history 10, results-only checkpoints.
- Every node completion produces a checkpoint in Redis. For a flow that finishes
  normally, its checkpoints silently expire after the retention window — the user
  never manages them.
- `durable=True` flows write-through every checkpoint to the configured durable
  backend (`sqlite`, `pg`, `mongodb` — env var `FLOW_CHECKPOINT_DURABLE_STORE`,
  mirroring the `CREW_RESULT_STORAGE` convention).
- **Suspend**: `await flow.suspend()` checkpoints with `status=suspended` and dumps
  Redis state to the durable backend. On graceful server shutdown, a registered
  hook does the same for every active checkpointed flow automatically.
- **Resume**: `flow = await AgentsFlow.resume(flow_id, checkpoint_id=None, agent_registry=...)`
  rebuilds the graph from the checkpoint's embedded `FlowDefinition`, restores
  FlowContext (completed nodes are not re-executed), re-attaches conversational
  memory via the stored session/chatbot refs, and continues `run_flow()` from the
  frontier. Passing an older `checkpoint_id` re-forks from that point in history.
- **HTTP ops surface** (aiohttp handlers): list suspended/recoverable flows,
  inspect a flow's checkpoint history, trigger resume, delete a flow's checkpoints.

### Internal Behavior

1. `FlowCheckpointer` is constructed by AgentsFlow when checkpointing is enabled
   and registered through `add_node_event_listener()`.
2. On each `completed`/`failed` node event it snapshots FlowContext (results,
   completed_tasks, completion_order, shared_data, structured errors), per-node FSM
   states, and memory refs; the serializer encodes it (type registry → msgpack);
   the store `put()`s it fire-and-forget (pending-task set awaited in `aclose()`,
   same discipline as `PersistenceMixin`).
3. `RedisCheckpointStore` keeps, per flow: a latest pointer, a history sorted-set
   trimmed to `checkpoint_history`, and TTL = `checkpoint_retention` refreshed on
   every write.
4. `dump()` copies a flow's retained checkpoints from Redis into the durable store
   and marks the flow `suspended`; write-through mode writes both tiers on every
   checkpoint.
5. `resume()` loads the checkpoint (durable store first, Redis fallback), calls
   `AgentsFlow.from_definition()` on the embedded definition, replays
   `ctx.mark_completed()` for each completed node, and starts the event-driven
   scheduler — whose existing readiness logic naturally schedules only the frontier.
6. The recovery service hooks aiohttp `on_shutdown` (and SIGTERM for standalone
   runners) to suspend+dump all active flows within a configurable deadline.

### Edge Cases & Error Handling

- **Checkpoint write failure**: logged warning, flow continues — persistence must
  never take down a run (FEAT-147 contract).
- **Non-serializable node result**: type-registry miss → msgpack hook fallback →
  tagged repr + `lossy=True` on the checkpoint; resume of a lossy checkpoint warns
  that the affected dependency results are degraded strings.
- **Resume with unregistered agents**: `FlowContext.resolve_agent` already raises
  `AgentNotFoundError` — `resume()` surfaces it before scheduling anything.
- **Resume of a programmatic (add_node/add_edge) flow**: the checkpointer calls
  `AgentsFlow.to_definition()` (new in v1) to embed an exported definition; if any
  node is a custom subclass not present in `NODE_REGISTRY`, enabling checkpointing
  fails with a clear error naming the offending node.
- **Concurrent resume of the same flow**: Redis lease per flow_id with short TTL
  (~60s) renewed by heartbeat while the flow runs; a second resume fails fast with
  `FlowLockedError`; a dead holder's lease expires and takeover becomes possible.
- **In-flight node at crash time**: re-executed from scratch on resume
  (at-least-once); nodes with side effects must be idempotent — documented.
- **Expired checkpoints** (TTL elapsed before resume): `resume()` raises
  checkpoint-not-found; the HTTP list endpoint only shows live/durable flows.
- **Shutdown deadline exceeded**: default deadline 15s (fits inside a typical 30s
  k8s/aiohttp grace period), configurable. Flows that cannot dump in time are
  logged as ERROR with their flow_ids; their last per-node checkpoint in Redis
  remains recoverable until its TTL expires.

---

## Capabilities

### New Capabilities
- `flow-checkpoint-plane`: `FlowCheckpoint` model, hybrid serializer (type
  registry + msgpack hooks), `CheckpointStore` ABC.
- `flow-checkpoint-stores`: `RedisCheckpointStore` (ephemeral, TTL + history) and
  AsyncDB durable stores (SQLite, Postgres, Mongo/DocumentDB).
- `flow-suspend-resume`: AgentsFlow wiring — checkpointer lifecycle, `suspend()`,
  `resume()` (with Redis lease + heartbeat locking), write-through mode,
  graceful-shutdown recovery service.
- `flow-definition-export`: `AgentsFlow.to_definition()` — graph→`FlowDefinition`
  export so programmatic (`add_node`/`add_edge`) flows are checkpointable and
  resumable in v1 (requires all nodes registered in `NODE_REGISTRY`).
- `flow-checkpoint-http-api`: aiohttp handlers to list/inspect/resume/delete.

### Modified Capabilities
- `agentsflow-refactor-spec3` (FEAT-163): AgentsFlow constructor/metadata grow
  checkpoint options; no behavior change when disabled.

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `parrot/bots/flows/core/checkpoint/` (new) | new package | model, serializer, stores, checkpointer |
| `parrot/bots/flows/flow/flow.py` | extends | constructor kwargs, listener wiring, `suspend()`, `resume()` classmethod, `to_definition()` export |
| `parrot/bots/flows/flow/definition.py` | extends | optional checkpoint block in `FlowMetadata` |
| `parrot/bots/flows/core/context.py` | extends | `to_snapshot()` / seed-from-snapshot helpers (no field changes) |
| `parrot/bots/flows/core/result.py` | depends on | fold `_serialise_result_value` into the type registry |
| `parrot/handlers/` | new handlers | checkpoint ops API + `on_shutdown` recovery hook |
| `parrot/conf.py` | extends | `FLOW_CHECKPOINT_*` env vars (store DSNs, TTL, history N, shutdown deadline) |
| `pyproject.toml` | new dependency | `ormsgpack >= 1.5` |
| `parrot/flows/dev_loop/runner.py` | future consumer | F006: gated runs can suspend instead of holding a concurrency slot (follow-up feature) |
| AgentCrew (`bots/flows/crew/`) | unaffected in v1 | phase 2 consumes the same `CheckpointStore` contract |

No breaking changes: everything is opt-in; default behavior is byte-identical.

---

## Code Context

### User-Provided Code

(None — user provided requirements verbally, no code snippets.)

### Verified Codebase References

#### Classes & Signatures
```python
# From packages/ai-parrot/src/parrot/bots/flows/flow/flow.py
class AgentsFlow(PersistenceMixin):                                   # line 159
    def add_node(self, node: Node) -> None: ...                       # line 234
    def add_edge(self, from_, to, ...) -> None: ...                   # line 251
    def add_node_event_listener(self, callback) -> None: ...          # line 307
    def _notify_node_event(self, event, node_id, info) -> None: ...   # line 322 (shielded — listener errors never break the scheduler)
    @classmethod
    def from_definition(cls, definition, ...) -> "AgentsFlow": ...    # line 362
    async def _run_node(self, node, ctx, deps, queue) -> None: ...    # line 556 (manages FSM, pushes CompletionEvent)
    async def run_flow(self, ctx) -> FlowResult: ...                  # line 693 (event-driven scheduler)

# From packages/ai-parrot/src/parrot/bots/flows/core/context.py
@dataclass
class FlowContext:                                                    # line 52
    initial_task: str                                                 # line 68
    results: Dict[str, Any]                                           # line 69
    responses: Dict[str, Any]                                         # line 72
    node_metadata: Dict[str, NodeExecutionInfo]                       # line 75
    completion_order: List[str]                                       # line 78
    errors: Dict[str, Exception]                                      # line 81  (Exception objects — need structured serialization)
    active_tasks: Set[str]                                            # line 84
    completed_tasks: Set[str]                                         # line 87
    shared_data: Dict[str, Any]                                       # line 90
    agent_registry: Optional["AgentRegistry"]                         # line 93  (NOT serializable — re-bound on resume)
    synthesis_client: Optional[Any]                                   # line 100 (NOT serializable — re-bound on resume)
    trace_context: Optional["TraceContext"]                           # line 108 (re-seeded on resume)
    def resolve_agent(self, agent_ref: AgentRef) -> AgentLike: ...    # line 119 (raises AgentNotFoundError)
    def mark_completed(self, node_id, result=None, response=None, metadata=None) -> None: ...  # line 174

# From packages/ai-parrot/src/parrot/bots/flows/core/storage/backends/base.py
class ResultStorage(ABC):                                             # line 8
    async def save(self, collection: str, document: dict[str, Any]) -> None: ...  # line 18
    async def close(self) -> None: ...                                # line 27
    async def fetch(self, collection, execution_id) -> list[dict]: ...# line 30 (non-abstract read API)

# From packages/ai-parrot/src/parrot/bots/flows/core/storage/backends/redis.py
class RedisResultStorage(ResultStorage):                              # line 21
    def __init__(self, dsn=None, ttl=None): ...                       # line 29 (AsyncDB redis driver; TTL default CREW_RESULT_STORAGE_REDIS_TTL = 604800s)

# From packages/ai-parrot/src/parrot/bots/flows/flow/definition.py
class NodeDefinition(BaseModel): ...                                  # line 125
class EdgeDefinition(BaseModel): ...                                  # line 195
class FlowMetadata(BaseModel): ...                                    # line 254
class FlowDefinition(BaseModel): ...                                  # line 296 (full JSON round-trip: model_validate / model_dump_json)

# From packages/ai-parrot/src/parrot/bots/flows/core/fsm.py
class AgentTaskMachine(StateMachine): ...                             # (statemachine lib; per-node lifecycle states running/completed/failed)
```

#### Verified Imports
```python
# These imports have been confirmed to work:
from parrot.bots.flows.core.context import FlowContext, AgentNotFoundError
from parrot.bots.flows.core.storage import PersistenceMixin           # core/storage/__init__.py re-exports
from parrot.bots.flows.core.storage.backends import ResultStorage, get_result_storage
from parrot.bots.flows.flow.definition import FlowDefinition, NodeDefinition
from parrot.bots.flows.core.result import _serialise_result_value    # imported by flow.py:33
```

#### Key Attributes & Constants
- `CREW_RESULT_STORAGE_REDIS_TTL` → `int`, 604800s default (`parrot/conf.py`, used at backends/redis.py:16,42) — naming precedent for `FLOW_CHECKPOINT_REDIS_TTL`.
- `get_result_storage(arg)` factory (backends/factory.py:34) — supports `redis | postgres | documentdb`; precedent for a `get_checkpoint_store()` factory.
- `asyncdb.AsyncDB` — driver façade already used by all FEAT-147 backends; ships `sqlite`, `pg`, `mongodb`, `redis` drivers (pyproject: `asyncdb>=2.11.6`, extras line 143).
- Prior art: `packages/ai-parrot-tools/src/parrot_tools/scraping/flow_executor.py` — `_write_checkpoint/_load_checkpoint/run(resume_from=...)` (FEAT-222, JSON-file checkpoints; to be superseded conceptually, not touched).
- Confirmed consumer: `sdd/state/FEAT-377/findings/F006-g6-checkpoint-resume.md` — dev-loop gated runs need suspend/resume; spec R8 deferred it to v2.

### Does NOT Exist (Anti-Hallucination)
- ~~`parrot/bots/flows/core/checkpoint/`~~ — no checkpoint package exists yet.
- ~~`AgentsFlow.resume()` / `AgentsFlow.suspend()` / `AgentsFlow.to_definition()`~~ — no resume/suspend/export API on any executor.
- ~~`msgpack` / `ormsgpack` in pyproject.toml~~ — NOT currently a dependency; `ormsgpack` must be added.
- ~~SQLite `ResultStorage` backend~~ — FEAT-147 factory only knows `redis | postgres | documentdb`.
- ~~`FlowContext.to_snapshot()` / `from_snapshot()`~~ — no serialization helpers on FlowContext today.
- ~~`CheckpointStore`, `FlowCheckpoint`, `FlowCheckpointer`, `FlowStateSerializer`~~ — all new names proposed by this brainstorm.
- ~~LangGraph/`langgraph-checkpoint` anywhere in the tree~~ — LangChain is removed; reference-only.

---

## Parallelism Assessment

- **Internal parallelism**: Moderate. The checkpoint plane (model + serializer +
  stores) is independent of the AgentsFlow wiring, and the three durable-store
  drivers are mutually independent; the HTTP handlers depend only on the store
  contract. But `flow.py` wiring + `resume()` is one sequential core everything
  else converges on.
- **Cross-feature independence**: Touches `bots/flows/flow/flow.py` and
  `core/context.py` — no in-flight spec currently owns those files (FEAT-306/307
  saved-crews work lives in `bots/flows/crew/`). Low conflict risk.
- **Recommended isolation**: per-spec (single worktree, tasks sequenced:
  plane → stores → wiring/resume → shutdown service → HTTP → docs).
- **Rationale**: the shared `FlowCheckpoint` model and serializer are upstream of
  every other task; splitting worktrees would serialize on merges anyway. Within
  the single worktree, store-backend tasks can still be dispatched to parallel
  subagents if desired.

---

## Open Questions

All resolved interactively with the author on 2026-08-01:

- [x] `msgpack` vs `ormsgpack` (Rust, faster, what langgraph uses) — pick at spec time. — *Owner: Jesus*: **`ormsgpack`** — native Pydantic/datetime/UUID serialization (fewer manual hooks), faster, langgraph-checkpoint precedent.
- [x] Checkpoint `responses` (raw AIMessage objects) or only extracted `results`? Raw responses can be large; results may suffice for `get_input_for_node()` on resume. — *Owner: Jesus*: **Only `results` by default** — sufficient for `get_input_for_node()` on resume — plus an opt-in `checkpoint_include_responses=True` flag for full-fidelity (heavier) checkpoints.
- [x] Concurrent-resume locking: Redis lease per flow_id — TTL, takeover semantics, and behavior when the lease holder dies. — *Owner: Jesus*: **Redis lease + heartbeat** — short-TTL lock (~60s) per flow_id, renewed while the flow runs; a second resume fails fast with `FlowLockedError`; if the holder dies the lease expires and another process may take over.
- [x] Defaults: retention TTL and history N. — *Owner: Jesus*: **TTL 24h / history 10** — aggressive Redis hygiene: happy-path flows vanish within a day; both configurable per-flow and via env vars (`FLOW_CHECKPOINT_REDIS_TTL=86400`, `FLOW_CHECKPOINT_HISTORY=10`).
- [x] HTTP handlers auth model. — *Owner: Jesus*: **Reuse the existing auth conventions of `parrot/handlers/`** (service auth middleware) — no new security surface; the spec references the existing pattern.
- [x] Graceful-shutdown deadline default and what to log/do for flows that miss it. — *Owner: Jesus*: **15s default** (fits aiohttp/k8s 30s grace), configurable. Flows that miss the deadline are logged as ERROR with their flow_ids; their last per-node checkpoint in Redis remains recoverable until TTL.
- [x] v1 restriction: resume only for definition-based flows? — *Owner: Jesus*: **No — v1 includes a graph→definition export** (`AgentsFlow.to_definition()`) so programmatic `add_node()`/`add_edge()` flows are also resumable. Caveat to handle at spec time: custom Node subclasses must be in `NODE_REGISTRY` to survive the round-trip; unregistered nodes make the flow non-exportable (clear error).
- [x] Phase 2 scope. — *Owner: Jesus*: **Two separate follow-up specs**: (a) AgentCrew (4 run modes) consuming the same `CheckpointStore` plane; (b) dev-loop F006 integration — gated runs suspend (releasing their concurrency slot) and resume when the gate opens. (Graph→definition export moved into v1 per the previous answer.)
