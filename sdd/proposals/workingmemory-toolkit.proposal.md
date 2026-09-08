# FEAT-TASK-MEMORY — Recoverable Task Memory for WorkingMemoryToolkit

**Status:** Spec (draft for `/sdd-task`). Date: 2026-09-08.
**Inputs:** `ai-parrot-task-memory-plan.md` (proposal), `claude_per-turn-compaction-deterministic-design.md` (accepted 2026-09-03), `claude_handle-only-execution-design.md`.
**Feature ID:** placeholder — assign at `/sdd-task`.

> ⚠️ Every file/symbol reference below is a **grep anchor**, not a line number. Phase 0 pins the implementation commit and re-verifies each anchor. Anything marked `⚠️ VERIFY` was not confirmed against the working tree during this spec.

---

## 0. Closed decisions

| ID | Decision | Rationale |
|---|---|---|
| **D1** | **One artifact store.** `ArtifactStore` **is** the pluggable backend of `WorkingMemoryCatalog`, not a sibling. `CatalogEntry` gains version/identity fields; `ArtifactDescriptor` is a read projection of a versioned `CatalogEntry`. Zero new blob stores: text payloads referenced from the journal use `OmissionStore` `content_id`s; dataset payloads use `artifact_id@version`. | Handle-only design §10 already requires a pluggable catalog backend with spill; a second store would create three identity spaces. |
| **D2** | **No SQLite.** Durable tier = **PostgreSQL via `asyncpg`** (journal, projection, artifact index). **Redis** = hot/ephemeral tier (task↔conversation association, per-task leases, recall snapshot cache). `InMemory*` backends exist for tests and single-process compatibility only. | Matches the deployed stack (EKS multi-pod, Redis conversation memory, Postgres+asyncpg). SQLite would be throwaway. |
| **D3** | **Step attribution = turn-scoped declared context**, not per-invocation metadata in tool schemas. `wm_update_step(status="running")` publishes a `TaskContext` ContextVar; the dispatcher observer reads it. Attribution provenance is always recorded (`declared` / `plan` / `none` / `ambiguous`). Tool signatures and generated schemas are **not** modified. | Extending every tool schema touches every provider adapter and reintroduces routing-by-parameter. Attribution never completes a step, so its only consumer is recall — cost of schema extension is not justified. |
| **D4** | **RAM snapshot policy** (§6): evidence versions of in-memory objects are **copy-on-register up to `snapshot_max_bytes` (default 64 MiB)**; above that, **spill to the durable artifact tier** if configured, else register with `evidence_verifiable=false`. Every evidence version carries a deterministic `fingerprint`; validators recompute and compare at completion; mismatch emits `artifact_invalidated`. | Versioning a name does not version a mutable object. Copying below a cap is cheap and deterministic; above the cap the durable tier is the only honest snapshot. |
| **D5** | **Reuse compaction primitives:** the single dispatcher observer produces `ToolInvocation` (compaction §2.1); the journal **derives** `tool_*` events from it. Recall budgeting uses `ContextBudget` and the o200k estimator + calibration (compaction §4). `wm_recall_task` is registered as the **deterministic Stage 2 candidate** for the exhausted-prunables trigger. | Two instrumentation points for the same call would double-count and drift. |
| **D6** | **Journal is the source of truth; `TaskState` is a pure, versioned reducer projection.** Validators emit events; replay never re-executes validators or tools. | Event sourcing; deterministic replay. |
| **D7** | **Retention policies are explicit and configured** (§9): journal, projection, artifacts, Redis keys, and abandoned tasks each have a rule; nothing is unbounded. | Plan had no retention; catalog is already flagged as unbounded RAM. |
| **D8** | **Failure mode is explicit:** durable mode refuses to start a call if `tool_started` cannot be persisted; best-effort mode must be opted into and returns `tracking_degraded`. | No fictitious tracking success. |

---

## 1. Scope

**In:** `TaskState` / `TaskStep` / `JournalEvent` / `ArtifactDescriptor` models; pure reducer; single dispatcher observer + catalog observer; public `wm_*` task tools; `wm_recall_task` with deterministic budgeted selection; `TaskMemoryStore` (InMemory, Postgres); `ArtifactStore` as catalog backend (InMemory, Postgres index + blob); Redis association/lease/cache; REPL binding resolver; retention sweeper; opt-in wiring.

**Out:** semantic search over history; autonomous planning; preserving model reasoning; auto-executing steps from recall; arbitrary REPL namespace serialization; resuming interrupted Python code; exactly-once external effects; Stage 2 LLM summaries (only the hook is consumed).

**Deliveries:**
- **A (in-process continuity):** §3–§7 with `InMemory*` backends + Redis association. Not advertised as durable.
- **B (durable continuity):** Postgres backends, blob tier, crash reconciliation, retention sweeper, schema migrations.

---

## 2. Existing base (verified in prior review — re-verify in Phase 0)

| Component | Anchor | Notes |
|---|---|---|
| `WorkingMemoryToolkit` | `packages/ai-parrot/src/parrot/tools/working_memory/tool.py` | Catalog of DataFrames/objects, declarative ops (`wm_compute_and_store`), `AnswerMemory` bridge. `get_result(include_raw=True)` has no byte cap (handle-only §4) — **fix lands in this feature** (§7.4). |
| `WorkingMemoryCatalog`, `CatalogEntry` | `.../working_memory/internals.py` — grep `class WorkingMemoryCatalog`, `class CatalogEntry` | Plain in-process `dict`, no lock, no TTL, no byte limit. `CatalogEntry` has `source_operation`, `parent_keys`, `description`, `turn_id`, `session_id`. |
| `OperationSpecInput` | `.../working_memory/models.py` — grep `class OperationSpecInput` | Declarative ops surface. |
| `ExecutionPlanToolkit`, `ArtifactRef`, `ExecutionManifest`, `build_manifest` | `docs/toolkits/execution_plan_toolkit.md`; `plan/` module (`models.py`, `compile.py`) | Plan keys are assigned by the plan, not by a runtime counter. |
| `ToolManager.execute_tool()` | `parrot/tools/manager.py` — grep `def execute_tool` | ⚠️ VERIFY this is the single dispatch boundary for LLM tool calls **and** for `PlanToolNode`. |
| `ConversationTurn`, `ToolInvocation`, `ToolStatus`, `TurnState` | `parrot/memory/` — per compaction design §2 | ⚠️ VERIFY implementation status of compaction Stage 0/0.5/1 at the pinned commit. If `ToolInvocation` is not yet merged, this feature depends on it (blocking). |
| `ContextBudget`, token counter, `report_usage` calibration | compaction §4 | Reused as-is. |
| `OmissionStore` (`Redis`, `InMemory`), `content_id = "om_" + blake2b(...)` | compaction §5.3 | Reused for large text payloads referenced by journal events. |
| `ConversationHistory.metadata` reserved keys | compaction §2.3 (`compaction` key) | New reserved key `task_memory` (§8.1). |
| `RedisConversation` key scheme | grep `_omitted:` / history key builder | Task keys follow the same `{prefix}:{chatbot_id}:{user_id}:{session_id}` scope. |
| `AbstractToolkit` public-tool autodetection | grep `class AbstractToolkit` | Internal task APIs must be excluded from autodetection (§7.5). |

### 2.1 Does NOT exist (do not assume)

- No `TaskState`, `TaskStep`, `JournalEvent`, `TaskMemoryStore`, `ArtifactStore`, `TaskContext` anywhere in the repo.
- No versioning on `CatalogEntry`; keys are mutable aliases.
- No dispatcher-level observer/hook API on `ToolManager` (⚠️ VERIFY — Phase 0 may find a callback list; do not assume its name or that it covers all routes).
- No lock on `WorkingMemoryCatalog`.
- No byte cap on `wm_get_result(include_raw=True)`.
- No generic "task association" in `ConversationHistory.metadata`.
- No retention sweeper for working memory.

---

## 3. Domain models (`parrot/tools/working_memory/task_memory/models.py`)

All Pydantic v2, `schema_version: int = 1`, explicit enums, `max_length` on every free-text field. IDs are runtime-assigned (`ulid`/`uuid7`); model-authored text is never an identity.

```python
class TaskStatus(str, Enum): active="active"; blocked="blocked"; paused="paused"; completed="completed"; failed="failed"; cancelled="cancelled"
class StepStatus(str, Enum): pending="pending"; running="running"; blocked="blocked"; completed="completed"; failed="failed"; cancelled="cancelled"; superseded="superseded"
class CompletionMode(str, Enum): validated="validated"; agent_asserted="agent_asserted"
class Availability(str, Enum): memory="memory"; persisted="persisted"; missing="missing"; expired="expired"
class Attribution(str, Enum): declared="declared"; plan="plan"; none="none"; ambiguous="ambiguous"
class Actor(str, Enum): agent="agent"; runtime="runtime"; validator="validator"; sweeper="sweeper"

class TaskScope(BaseModel):            # resolved by runtime, never by the model
    chatbot_id: str; user_id: str; session_id: str

class Constraint(BaseModel):
    constraint_id: str; text: str = Field(max_length=500); active: bool = True; revision: int

class CompletionPolicy(BaseModel):
    mode: CompletionMode
    validators: list[str] = []          # names in ValidatorRegistry; model may pick, never define
    expected_outputs: list[str] = []    # artifact keys the step must produce (bound to version at completion)
    require_note: bool = True           # agent_asserted only

class TaskStep(BaseModel):
    step_id: str; title: str = Field(max_length=120); description: str = Field(max_length=2000)
    required: bool = True; depends_on: list[str] = []
    status: StepStatus = StepStatus.pending
    completion_policy: CompletionPolicy
    evidence_refs: list[str] = []       # "artifact_id@version" or "om_<content_id>"
    attempt_count: int = 0; blocked_reason: str | None = None
    created_in_revision: int; updated_in_revision: int
    completion_source: Literal["validator", "agent"] | None = None

class Decision(BaseModel):
    decision_id: str; text: str = Field(max_length=500); reason: str = Field(max_length=500)
    source: Actor; affected_step_ids: list[str] = []; revision: int; active: bool = True

class ResumeHint(BaseModel):
    text: str = Field(max_length=500); step_id: str | None; author: Actor; revision: int; stale: bool = False

class TaskState(BaseModel):
    schema_version: int = 1
    task_id: str; scope: TaskScope
    goal: str = Field(max_length=2000)
    constraints: list[Constraint] = []
    status: TaskStatus = TaskStatus.active
    plan_complete: bool = False; plan_revision: int = 0; revision: int = 0
    steps: list[TaskStep] = []; decisions: list[Decision] = []
    resume_hint: ResumeHint | None = None
    created_at: datetime; updated_at: datetime; last_event_seq: int = 0
    # derived, never persisted:
    @computed_field  def active_step_ids(self) -> list[str]: ...
    @computed_field  def ready_step_ids(self) -> list[str]: ...   # pending AND all deps completed
```

`ArtifactDescriptor` is **not** a new stored entity (D1): it is `CatalogEntry.to_descriptor()`.

```python
# additions to CatalogEntry (internals.py)
artifact_id: str                       # stable across versions; runtime-assigned on first store
version: int                           # monotonic per artifact_id
task_id: str | None; producer_step_id: str | None; producer_call_id: str | None
attribution: Attribution = Attribution.none
availability: Availability
fingerprint: str | None                # §6
evidence_verifiable: bool = True       # §6
storage_ref: str | None                # durable tier URI (s3://…, file://…) or None
shape: tuple[int, ...] | None; schema_summary: dict | None   # captured at write, never recomputed on recall
repl_binding: ReplBinding | None       # worker_session_id + variable_name; may be None while persisted
```

`key` remains the alias to the **current** version. Overwriting the alias creates a new version; evidence already bound to `artifact_id@v` is untouched.

### 3.1 `JournalEvent`

```python
class EventType(str, Enum):
    task_started; task_paused; task_resumed; task_completed; task_failed; task_cancelled
    plan_updated; decision_recorded; resume_hint_updated
    tool_started; tool_succeeded; tool_failed; tool_cancelled; tool_outcome_unknown
    artifact_registered; artifact_invalidated
    step_started; step_blocked; step_completed; step_failed; step_reopened
    tracking_degraded

class JournalEvent(BaseModel):
    schema_version: int = 1
    event_id: str                      # unique; idempotency key
    task_id: str; seq: int             # seq assigned by backend, monotonic per task
    timestamp: datetime; event_type: EventType; actor: Actor
    turn_id: str | None; plan_revision: int
    step_id: str | None = None; attribution: Attribution = Attribution.none
    tool_call_id: str | None = None; parent_call_id: str | None = None
    payload: dict = Field(max_length=... )   # enforced by `PAYLOAD_MAX_BYTES` (default 8 KiB) at write
```

Payload rules: title, **redacted** and summarized args, input/output refs (`artifact_id@version` | `om_…`), `elapsed_ms`, attempt, normalized error. Never rows, never full code, never credentials. Redaction reuses the compaction Stage 0 rule set plus a `SecretRedactor` (key-name denylist: `token|secret|password|authorization|api_key`, plus configured extras).

---

## 4. Reducer and consistency rules (`task_memory/reducer.py`)

`reduce(state: TaskState | None, event: JournalEvent) -> TaskState` — pure, total, versioned (`REDUCER_VERSION`).

- Events with `seq <= state.last_event_seq` or an already-seen `event_id` are no-ops (idempotent redelivery).
- `seq` gaps → `ReducerError`; the store must never expose gaps.
- Plan mutations (`plan_updated`) carry `expected_revision`; the **store** rejects mismatches before append and returns current state (optimistic concurrency). The reducer trusts appended events.
- Validation on `plan_updated`: no cycles (Kahn), no duplicate `step_id`, all `depends_on` exist; removed steps become `superseded`, their evidence retained.
- `ready` is derived: `pending` with all `depends_on` in `completed`. Failed/blocked/superseded deps never enable.
- `step_completed` requires `evidence_refs` to be **versioned** refs; a bare key is rejected at the store boundary.
- Changing criteria/inputs of a completed step is only possible via `step_reopened`; dependents transition to `blocked(reason="upstream_reopened")` until revalidated.
- `task_completed` is legal only when `plan_complete=true` and all `required` steps are `completed`.
- `tool_failed` never auto-fails a step or task; it increments `attempt_count` and may emit `step_blocked` per policy (`max_attempts`, default 3).
- Recovery: any `tool_started` without a terminal event at recovery time → the recovery routine appends `tool_outcome_unknown` (actor=`runtime`). No automatic retry.
- `resume_hint.stale = true` when any later event touches `resume_hint.step_id` or its inputs.
- Recall reads (`wm_recall_task`) **do not** produce journal events.

---

## 5. Instrumentation (`task_memory/observer.py`, `task_memory/context.py`)

### 5.1 `TaskContext` (D3)

```python
@dataclass(frozen=True)
class TaskContext:
    task_id: str; scope: TaskScope; plan_revision: int; turn_id: str
    declared_step_ids: frozenset[str]        # steps set to running *in this turn*
    parent_call_id: str | None = None

TASK_CONTEXT: ContextVar[TaskContext | None]
```

- Set by the runtime at turn start from the authoritative association (§8.1); `declared_step_ids` grows when `wm_update_step(status="running")` succeeds in the same turn.
- Attribution rule (deterministic): `len(declared_step_ids) == 1` → `attribution=declared, step_id=that`; `== 0` → `none`, task-level; `> 1` → `ambiguous`, task-level. `PlanToolNode` runs override with `attribution=plan, step_id=<plan step>` because plan keys are explicit.
- Propagation across `asyncio.create_task`, `to_thread`, the REPL worker bridge and `PlanToolNode` is **explicit** (`ctx=` parameter / `contextvars.copy_context()`); no globals.

### 5.2 Single dispatcher observer (D5)

One `ToolExecutionObserver` installed at the `ToolManager.execute_tool()` boundary (⚠️ VERIFY hook point in Phase 0). Per invocation it:

1. Reads `TASK_CONTEXT`; if `None` → not task-associated → produces `ToolInvocation` only (compaction path unchanged).
2. Assigns `tool_call_id`, attempt; appends `tool_started` (durable mode: **before** invoking; failure to append aborts the call with `TaskMemoryUnavailable` — D8).
3. Executes; builds `ToolInvocation` (normalized, pruned per compaction policies).
4. Runs the tool family's `ResultAdapter` to classify outcome. Adapters are registered per tool/toolkit (`RESULT_ADAPTER_REGISTRY`, default = "exception ⇒ failed, else succeeded"). `WorkingMemoryToolkit` and `ExecutionPlanToolkit` register adapters that recognize `{"status": "error", ...}` dicts. **No free-text success inference.**
5. Emits terminal event (`tool_succeeded|tool_failed|tool_cancelled`) sharing the `ToolInvocation` as payload source; large I/O strings are replaced by `om_` refs from the `OmissionStore` (same put, idempotent).
6. Catalog writes made during the call carry the same `tool_call_id`; the reducer counts one execution.
7. Runs validators **only** when `wm_update_step(status="completed")` is requested — not on every call (see §7.2).

### 5.3 Catalog observer

`WorkingMemoryCatalog` gains `on_write` / `on_invalidate` callbacks (list, set at construction). Programmatic writes (e.g. from `PlanToolNode`) produce `artifact_registered` with the active `TaskContext`. `drop_stored` removes the alias and marks the current version `availability=expired` if it was evidence; history is never deleted by `drop_stored`.

Also in this feature: `asyncio.Lock` on catalog write path (handle-only §3 item 2).

---

## 6. Artifact identity, snapshots, fingerprints (D1, D4)

### 6.1 Versioning

- First `store(key, obj)` → new `artifact_id`, `version=1`. Subsequent `store(key, obj)` on the same key → same `artifact_id`, `version+1`, alias moves.
- Evidence references are always `artifact_id@version`. `wm_update_step` resolves a bare key to the **current** version at that instant and stores the versioned ref.

### 6.2 Snapshot policy (D4)

On `artifact_registered` for an in-memory object:

| Condition | Action | `evidence_verifiable` |
|---|---|---|
| `estimated_bytes <= snapshot_max_bytes` (default 64 MiB) | `snapshot = deepcopy` (`df.copy(deep=True)` for pandas; `copy.deepcopy` for JSON/objects), stored as the versioned payload; the live object stays bound to the alias | `true` |
| `> snapshot_max_bytes` and durable tier configured | write Parquet (`pyarrow`, no pickle) / JSON to blob, `availability=persisted`, `storage_ref` set | `true` |
| `> snapshot_max_bytes`, no durable tier | register metadata only, no copy | `false` (recall shows it) |

`estimated_bytes`: `df.memory_usage(deep=True).sum()` for pandas; `len(orjson.dumps(obj))` for JSON-serializable; `sys.getsizeof` fallback with `evidence_verifiable=false`.

### 6.3 Fingerprint

`fingerprint = "fp_" + blake2b(canonical, digest_size=8)` where `canonical` is:

- pandas: `shape ‖ dtypes ‖ pd.util.hash_pandas_object(df, index=True).values` (uint64 array bytes). Cost is linear and cheap under the cap; above the cap fingerprint is computed at spill time from the same bytes written.
- JSON/text: canonical orjson bytes (sorted keys).
- other: `None`.

Validators for `expected_outputs` recompute the fingerprint of the object currently bound to the alias and compare with the referenced version's fingerprint. Mismatch → `artifact_invalidated(reason="fingerprint_mismatch")` and the step cannot complete with that evidence.

### 6.4 `ArtifactStore` protocol (`parrot/interfaces/artifact_store.py` — Pydantic-only, lazily implemented)

```python
class ArtifactStore(Protocol):
    async def put(self, entry: CatalogEntry, payload: Any) -> CatalogEntry      # assigns version, snapshot, fingerprint
    async def get_current(self, scope: TaskScope, key: str) -> CatalogEntry | None
    async def get_version(self, artifact_id: str, version: int) -> CatalogEntry | None
    async def load_payload(self, artifact_id: str, version: int, *, max_bytes: int) -> Any   # ResultPolicy ceiling
    async def invalidate(self, artifact_id: str, version: int, reason: str) -> None
    async def list(self, scope: TaskScope, *, task_id: str | None, limit: int, cursor: str | None) -> Page[CatalogEntry]
    async def evict(self, policy: RetentionPolicy) -> EvictionReport
```

Implementations: `InMemoryArtifactStore` (LRU by bytes, `max_bytes` default 512 MiB, spill hook), `PostgresArtifactStore` (index in `working_memory.artifacts`, blobs in S3/FS via `storage_ref`). The catalog delegates to it; `WorkingMemoryCatalog` public API is unchanged.

**Publish order (durable):** write blob → verify readable (HEAD/stat) → insert index row + `artifact_registered` in one transaction. A blob without a row is an orphan swept by retention (§9); the reverse order is forbidden.

---

## 7. Public tools (`WorkingMemoryToolkit`, prefix `wm_`)

| Tool | Params | Returns |
|---|---|---|
| `wm_begin_task` | `goal`, `constraints=[]`, `steps=[]`, `plan_complete=false` | `task_id`, `revision`, compact state |
| `wm_update_plan` | `task_id`, `expected_revision`, `changes: PlanChanges`, `reason` | new revision, affected steps — or `RevisionConflict` with current state |
| `wm_update_step` | `task_id`, `step_id`, `expected_revision`, `status`, `evidence_refs=[]`, `note=None` | accepted transition or validation error |
| `wm_record_decision` | `task_id`, `text`, `reason`, `affected_step_ids=[]` | `decision_id`, revision |
| `wm_set_resume_hint` | `task_id`, `next_action`, `step_id=None` | saved hint with revision |
| `wm_recall_task` | `task_id=None`, `max_tokens=2500`, `recent_calls_limit=8` | budgeted snapshot (§7.3) |
| `wm_list_task_events` | `task_id`, `after_seq=0`, `limit=50` | paginated events (no payloads > `PAYLOAD_MAX_BYTES`) |
| `wm_list_task_artifacts` | `task_id`, `limit=50`, `cursor=None` | paginated descriptors |

### 7.1 `task_id` resolution

If `task_id` is omitted, the runtime resolves it from the authoritative association (§8.1). Multiple open tasks and none selected → `needs_task_selection` with `[{task_id, goal[:80], status, updated_at}]`. Never chosen by similarity.

### 7.2 Completion enforcement

`wm_update_step(status="completed")`:
- `validated`: runs the policy's validators from `ValidatorRegistry` (code-registered; signature `async def (step, refs, store) -> ValidatorResult`). Results are appended as `step_completed(payload.validator_results)` or `step_blocked(reason=validator_failed)`. Replay never re-runs them (D6).
- `agent_asserted`: requires `note` (if `require_note`) and ≥1 evidence ref; appends `step_completed(completion_source="agent")`. Recall always labels it as agent-asserted.

Built-in validators: `artifact_exists`, `artifact_fingerprint_matches`, `artifact_non_empty` (uses captured `shape`, not the data), `no_pending_tool_failures`.

### 7.3 `wm_recall_task` contract

Read-only: no plan execution, no REPL loads, no LLM call, no `describe()`. Reads projection `as_of_seq` + descriptors; deterministic for the same `(task_id, seq, args)`.

Selection algorithm (units are whole; JSON is never string-truncated):

1. Reserve budget for identity, goal, active constraints, critical blockers (`required_min`).
2. Active + ready steps with criteria and required refs.
3. Active decisions + resume hint (with `stale`).
4. Completed required steps (ids/titles only) + `recent_calls` newest-first, unresolved failures first.
5. Most recent relevant artifacts (descriptors), counting omitted ones.
6. Serialize; measure with the compaction token counter × calibration from `ConversationHistory.metadata.compaction.calibration`; drop optional units from the tail of the priority list until within `max_tokens`.

If step 1 alone exceeds `max_tokens` → `{"error": "budget_too_small", "required_min_tokens": N}`. Without a tokenizer → conservative byte limit (4 bytes/token) and `"tokens_estimated": true`. Response includes `truncation: {truncated, omitted_calls, omitted_artifacts, omitted_steps}`.

Snapshot cache: Redis key `{prefix}_task_recall:{task_id}:{as_of_seq}:{args_hash}`, TTL 10 min (§9).

### 7.4 `ResultPolicy` (from handle-only §4, lands here)

`wm_get_result(include_raw=True)` gains `max_rehydrate_bytes` (default 2 MB, `0` = never) enforced via `ArtifactStore.load_payload(max_bytes=…)`, plus `offset/limit` pagination for tabular data. Over-limit error text redirects to `wm_compute_and_store`.

### 7.5 Autodetection

Internal task APIs (`TaskMemoryStore`, reducer, observer) live outside `AbstractToolkit` autodetection: they are not methods of the toolkit class; the toolkit composes them (`self._task_memory: TaskMemory | None`).

---

## 8. Persistence tiers (D2)

### 8.1 Redis (hot tier)

| Key | Content | TTL |
|---|---|---|
| `ConversationHistory.metadata["task_memory"]` | `{"open_task_ids": [...], "selected_task_id": str \| None}` — the authoritative association | history TTL |
| `{prefix}_task_lease:{task_id}` | `SET NX PX` lease held by the pod appending events (multi-pod safety) | 30 s, renewed |
| `{prefix}_task_recall:{task_id}:{seq}:{h}` | recall snapshot cache | 10 min |
| `{prefix}_task_ctx:{task_id}` | last `TaskContext` published (for worker bridge revalidation) | 24 h |

Redis is never the journal: no `XADD` stream — atomic append+projection is a Postgres transaction.

### 8.2 PostgreSQL (`asyncpg`, schema `working_memory`)

```sql
CREATE SCHEMA IF NOT EXISTS working_memory;

CREATE TABLE working_memory.tasks (
  task_id        text PRIMARY KEY,
  chatbot_id     text NOT NULL, user_id text NOT NULL, session_id text NOT NULL,
  status         text NOT NULL,
  revision       int  NOT NULL DEFAULT 0,
  last_event_seq bigint NOT NULL DEFAULT 0,
  projection     jsonb NOT NULL,            -- TaskState, reducer_version inside
  reducer_version int NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  terminal_at timestamptz                   -- set on completed/failed/cancelled (retention anchor)
);
CREATE INDEX ON working_memory.tasks (chatbot_id, user_id, session_id, status);
CREATE INDEX ON working_memory.tasks (terminal_at) WHERE terminal_at IS NOT NULL;
CREATE INDEX ON working_memory.tasks (updated_at) WHERE terminal_at IS NULL;

CREATE TABLE working_memory.task_journal (
  task_id   text NOT NULL REFERENCES working_memory.tasks(task_id) ON DELETE CASCADE,
  seq       bigint NOT NULL,
  event_id  text NOT NULL UNIQUE,
  event_type text NOT NULL,
  ts        timestamptz NOT NULL,
  event     jsonb NOT NULL,
  PRIMARY KEY (task_id, seq)
);

CREATE TABLE working_memory.artifacts (
  artifact_id text NOT NULL, version int NOT NULL,
  chatbot_id text NOT NULL, user_id text NOT NULL, session_id text NOT NULL,
  key text NOT NULL, task_id text, producer_step_id text, producer_call_id text,
  kind text NOT NULL, availability text NOT NULL,
  fingerprint text, evidence_verifiable boolean NOT NULL DEFAULT true,
  storage_ref text, bytes bigint, shape jsonb, schema_summary jsonb,
  pinned boolean NOT NULL DEFAULT false,        -- evidence of a non-terminal task
  created_at timestamptz NOT NULL DEFAULT now(),
  invalidated_at timestamptz, invalidated_reason text,
  PRIMARY KEY (artifact_id, version)
);
CREATE INDEX ON working_memory.artifacts (chatbot_id, user_id, session_id, key, version DESC);
CREATE INDEX ON working_memory.artifacts (task_id);
CREATE INDEX ON working_memory.artifacts (created_at) WHERE pinned = false;

CREATE TABLE working_memory.schema_migrations (version int PRIMARY KEY, applied_at timestamptz DEFAULT now());
```

**Append protocol** (`PostgresTaskMemoryStore.append_events`), single transaction:

```
BEGIN;
SELECT last_event_seq, revision, projection FROM tasks WHERE task_id=$1 FOR UPDATE;
-- reject expected_revision mismatch → return current projection
INSERT INTO task_journal ... seq = last_event_seq + i  (ON CONFLICT (event_id) DO NOTHING → skip event)
UPDATE tasks SET projection=$reduced, last_event_seq=$new, revision=$rev, updated_at=now(), terminal_at=... ;
COMMIT;
```

`FOR UPDATE` on the task row is the per-task serialization point; the Redis lease is a fast-fail guard, not the correctness mechanism.

`load_snapshot(task_id)` returns the projection; if `reducer_version` is older than current, replay the journal and rewrite the projection (lazy migration).

### 8.3 REPL

`ReplBindingResolver.load(artifact_id, version, worker_session_id) -> ReplBinding` materializes a persisted version into the active worker (Arrow IPC over the bridge; no pickle) and returns the binding. On worker restart, all `repl_binding.worker_session_id != current` are reported as `binding_invalid` by recall; the artifact stays locatable via `storage_ref`.

---

## 9. Retention policies (D7)

All configured via `navconfig` under `TASK_MEMORY_*`; defaults below. Enforced by `RetentionSweeper` (a `qworker` periodic job in production; an asyncio periodic task in single-process), each run appends its actions as events (`actor=sweeper`) so retention itself is auditable.

| Object | Rule | Default |
|---|---|---|
| Open task with no events for `inactive_after` | sweeper appends `task_paused(reason="inactivity")`; recall shows it | 7 days |
| Paused-by-inactivity task for `abandon_after` | `task_cancelled(reason="abandoned")`, `terminal_at` set | 30 days |
| Terminal task journal + projection | deleted (`ON DELETE CASCADE`) after `terminal_retention` — optional archive to S3 JSONL before delete when `archive_uri` set | 90 days |
| Journal payload size | hard cap per event, excess → `om_` ref or dropped with `payload_truncated=true` | 8 KiB |
| Journal length per task | soft cap; beyond it, `wm_list_task_events` still pages but recall uses only the projection | 50 000 events |
| Artifact version pinned (`pinned=true`) | never evicted while its task is non-terminal | — |
| Artifact version unpinned, not current alias | evicted after `artifact_stale_after` | 24 h |
| Artifact version current alias, task terminal | evicted after `terminal_retention` | 90 days |
| Orphan blobs (blob without index row) | deleted after `orphan_grace` | 1 h |
| `InMemoryArtifactStore` | LRU by bytes, `max_bytes`; pinned entries spill to durable tier (if any) instead of eviction; with no durable tier, eviction of a pinned entry sets `availability=expired` + `artifact_invalidated(reason="evicted")` | 512 MiB |
| Redis keys | TTLs per §8.1; `task_memory` metadata rides the history TTL | — |
| `OmissionStore` refs from journal | unchanged (`omission_ttl`, compaction decision); an expired `om_` ref in recall renders as `expired` | — |

Retention never deletes evidence of a non-terminal task; it can only mark it `expired`/`invalidated` with an event.

---

## 10. Agent-cycle integration

- Prompt guidance: on complex work, call `wm_begin_task`; partial plans (`plan_complete=false`) are valid.
- Turn start: runtime loads `metadata.task_memory`, publishes `TaskContext` (D3).
- Compaction Stage 2 hook: when the exhausted-prunables trigger fires **and** a `selected_task_id` exists, the runtime injects the `wm_recall_task` snapshot as the summary block (deterministic Stage 2). It never both injects and asks the model to call recall in the same turn.
- Opt-in: `WorkingMemoryToolkit(task_memory=TaskMemoryConfig(...))`; without it, all existing tools keep exact behavior and the observer only produces `ToolInvocation`.
- Instances shared explicitly between toolkit, dispatcher observer, `PlanToolNode` factory (closure, as in handle-only §6a).

---

## 11. Implementation phases

| Phase | Work | Exit criterion |
|---|---|---|
| **0. Integration spike** | Pin commit. Confirm: `execute_tool` as single boundary; hook API (or add `observers: list[ToolExecutionObserver]`); compaction `ToolInvocation` merged; `PlanToolNode` write path; REPL bridge API; `AbstractToolkit` autodetection rule. Measure `df.copy` + `hash_pandas_object` cost at 8/64/256 MiB. | Integration map with anchors; snapshot cap default confirmed or adjusted by measurement. |
| 1. Domain | Models, reducer, validation, `InMemoryTaskMemoryStore`, `InMemoryArtifactStore` with versioning + fingerprints. | Replay reproduces state; invalid plans/conflicts rejected; property tests on idempotence. |
| 2. Instrumentation | `TaskContext`, observer, `ResultAdapter` registry, catalog callbacks + lock, `OmissionStore` refs. | Success/error-as-data/cancel/nested/concurrent calls recorded once each; non-task path byte-identical to before. |
| 3. Tools + recall | `wm_*` tools, Redis association, budgeted selection using `ContextBudget` counter, `ResultPolicy` cap. | One recall yields actionable state, no rows, deterministic bytes for same `(task, seq, args)`. |
| 4. Artifacts + REPL | Snapshot policy, evidence binding, `ReplBindingResolver`, `ExecutionPlanToolkit` manifest adapter. | Overwrites and worker restarts never yield false evidence. |
| 5. Durability | `PostgresTaskMemoryStore`, `PostgresArtifactStore` + blob tier, recovery (`tool_outcome_unknown`), migrations, `RetentionSweeper`. | Process restart recovers state and supported artifacts; uncertain outcomes flagged; sweeper actions audited. |
| 6. Integration + docs | Multi-turn scenario, opt-in config, compaction Stage 2 injection, docs, measurements. | Acceptance suite green; existing WM tests unchanged. |

Delivery A = phases 0–4. Delivery B = 5–6.

Module layout: `parrot/tools/working_memory/task_memory/{models,reducer,context,observer,adapters,recall,validators,store/_base,store/memory,store/postgres,retention}.py`; `parrot/interfaces/artifact_store.py`, `parrot/interfaces/task_memory.py` (contracts only, always importable).

---

## 12. Acceptance criteria

| Case | Required result |
|---|---|
| Context lost after two steps | `task_id` + one recall restores goal/constraints and names the next ready step with its refs. |
| Tool returns `{"status":"error"}` without raising | `tool_failed`; step not completed; empty error DataFrame not accepted as evidence. |
| Two concurrent calls, two declared steps in one turn | Both recorded at task level with `attribution=ambiguous`; plan-run calls keep `attribution=plan` per step. |
| Duplicate event / replay | No double count; identical `TaskState` for identical sequence. |
| Key overwrite after evidence bound | Old evidence still resolves to its version and fingerprint; new version is current alias. |
| REPL mutates a DataFrame bound as evidence | Validator fingerprint mismatch → `artifact_invalidated`; step cannot complete with that ref. |
| Object above `snapshot_max_bytes`, no durable tier | Registered with `evidence_verifiable=false`; recall surfaces it. |
| Replan after completed step | History retained; dependents `blocked(upstream_reopened)`. |
| Partial plan exhausted | Task stays `active`; recall flags `plan_complete=false`. |
| Crash between `tool_started` and result | `tool_outcome_unknown` on recovery; no auto-retry. |
| Worker restarted | `binding_invalid`; persisted artifact reloadable via resolver. |
| Large catalog/history | Recall within budget; no `describe()`, no rows; `truncation` populated. |
| `wm_get_result(include_raw=True)` over cap | Error redirecting to `wm_compute_and_store`; nothing dumped. |
| Multiple tasks in session | `needs_task_selection`; no cross-task mixing. |
| Postgres unavailable (durable mode) | Tool call refused with `TaskMemoryUnavailable`; best-effort mode returns `tracking_degraded` event. |
| Inactive task 7 d / 30 d | Sweeper appends `task_paused` / `task_cancelled` with `actor=sweeper`. |
| Terminal task after 90 d | Journal, projection, unpinned artifacts removed; archive written when configured. |
| `task_memory` not configured | Existing WM tools byte-identical; observer emits only `ToolInvocation`. |

**Primary integration test:** synthetic large dataset → begin task with 4 steps → complete two (one validated, one agent-asserted) → inject a recoverable failure → discard conversation history → continue using only `task_id` + recall → verify versions, constraints, no repeated work, validated completion. Delivery B repeats with process + worker restart and a forced crash mid-call.

**Metrics:** recall tokens vs `list_stored + history` baseline; recall build time; observer overhead per call; invalid-ref rate; repeated operations after recovery; snapshot cost distribution. No latency SLO committed until measured.

---

## 13. Open questions (non-blocking for `/sdd-task`)

- **OQ1** Archive format on terminal deletion: JSONL to S3 vs. keep 1-row summary in `tasks`. Default: JSONL when `archive_uri` set, else delete.
- **OQ2** Should `ExecutionPlanToolkit` runs auto-create a `TaskStep` per plan when no task is open? Proposal: no — only attribute when a task exists (`attribution=plan`).
- **OQ3** `snapshot_max_bytes` default (64 MiB) pending Phase 0 measurement.
