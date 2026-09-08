---
type: feature
base_branch: dev
---

# Feature Specification: Recoverable Task Memory for WorkingMemoryToolkit

**Feature ID**: FEAT-538
**Date**: 2026-09-08
**Author**: Jesus Lara
**Status**: approved
**Target version**: next
**Source**: `sdd/proposals/workingmemory-toolkit.proposal.md`
**Verified implementation commit**: `4f066afcbd9807532e3320ab701c00864e19f1c2`

This specification supersedes the proposal's provisional API sketches and verification markers. The proposal's closed decisions D1–D8 remain authoritative; the refinements below make them implementable against the pinned code. No separate brainstorm exists. The proposal's three referenced design documents were not supplied as independent inputs; their contents are not assumed. Feature identity was allocated by `scripts.sdd.reserve_ids`, not inferred from the proposal's placeholder.

## 1. Motivation & Business Requirements

### Problem Statement

Working memory retains named intermediate results, but does not retain a task's goal, constraints, plan, evidence, decisions, or unresolved failures as a recoverable unit. Conversation compaction and process or REPL worker restarts can leave an agent unable to determine what is complete, which result is authoritative, or what can safely run next. Mutable aliases alone are insufficient evidence of completed work.

### Goals

- Recover actionable task state with one bounded, deterministic recall, without scanning full conversation history or loading datasets.
- Record actual tool attempts and artifact provenance once; never infer step completion from tool success alone.
- Preserve immutable evidence versions while retaining familiar working-memory aliases and the AnswerMemory bridge.
- Support in-process continuity first and durable multi-pod continuity through PostgreSQL, existing file storage, and Redis second.
- Make isolation, failures, concurrency, retention, and opt-in compatibility explicit and testable.

### Non-Goals (explicitly out of scope)

Semantic history search; autonomous planning; preserving model reasoning; running tools or loading REPL variables during recall; arbitrary namespace serialization; resuming interrupted Python execution; exactly-once external effects; LLM-generated Stage 2 summaries; changing provider tool schemas for attribution; SQLite backends.

### Closed Decisions Carried Forward

| ID | Decision |
|---|---|
| D1 | **One artifact store.** `ArtifactStore` **is** the pluggable backend of `WorkingMemoryCatalog`, not a sibling. `ArtifactDescriptor` is a read projection of a versioned entry. Text uses existing `OmissionStore` references; datasets use `artifact_id@version`. |
| D2 | **No SQLite.** PostgreSQL via `asyncpg` owns journal, projection, and artifact index. Redis owns hot associations, leases, and recall cache. In-memory backends are for tests and single-process compatibility. |
| D3 | **Step attribution = turn-scoped declared context**, not per-invocation metadata in tool schemas. Provenance is `declared`, `plan`, `none`, or `ambiguous`; attribution never completes a step. |
| D4 | **RAM snapshot policy:** copy on registration up to 64 MiB; spill larger supported objects when durable storage is configured; otherwise mark evidence unverifiable. Fingerprints detect mutation. |
| D5 | **Reuse compaction primitives:** one dispatcher observer produces `ToolInvocation`; journal events derive from that record. Recall reuses the compaction counter/calibration and is the deterministic Stage 2 candidate. |
| D6 | **Journal is the source of truth; `TaskState` is a pure, versioned reducer projection.** Validators emit events; replay never re-executes validators or tools. |
| D7 | **Retention policies are explicit and configured.** Journal, projection, artifacts, Redis keys, and abandoned tasks each have a rule. |
| D8 | **Failure mode is explicit:** durable mode refuses execution if `tool_started` cannot be persisted. Best-effort operation requires explicit opt-in and reports `tracking_degraded`. |

### Deliveries

Delivery A covers domain, reducer, bounded in-memory backends, instrumentation, task tools, Redis association, bounded recall, and in-process evidence/REPL bindings. It must be labeled non-durable. Delivery B adds PostgreSQL, supported durable payloads, crash reconciliation, migrations, retention scheduling, restart tests, and Stage 2 integration. This feature is complete only after both deliveries; A alone is not durable continuity.

## 2. Architectural Design

### Overview

The toolkit composes a private `TaskMemory` service. The service owns domain commands and reads, and shares a catalog backend and task store with the runtime observer and execution-plan node factory. PostgreSQL owns durable truth; Redis leases improve contention handling but never replace database serialization. Existing file-manager implementations provide blob I/O under the catalog backend; no second task-memory blob service or conversation artifact identity is introduced.

### Component Diagram

```text
Bot turn context ──→ wm_* commands / deterministic recall
       │                     │
       ▼                     ▼
ToolManager observer ──→ TaskMemory ──→ journal + pure reducer + projection
       │                     │                 PostgreSQL / InMemory
       ▼                     ▼
ToolInvocation       WorkingMemoryCatalog
       │                     │
       ▼                     ▼
Conversation memory  catalog ArtifactStore ──→ existing file storage
                             │
                        version descriptors ──→ explicit REPL resolver

Redis: association + leases + recall cache; OmissionStore: existing text refs
```

### Integration Points

| Existing component | Integration | Required behavior |
|---|---|---|
| `WorkingMemoryToolkit` | composition | Optional `task_memory` config; task tools exposed only when enabled; all enabled writes use the catalog's awaited path. |
| `CatalogEntry` and `GenericEntry` | additive metadata | Both entry types receive version metadata and descriptor conversion; existing DataFrame properties remain intact. |
| `ToolManager.execute_tool` | optional observer | Observe both dispatch branches, early denials, exceptions, cancellation, nested calls, and full-result mode without changing guard order. |
| `PlanToolNode` | explicit runtime binding | Carry plan run/node/item/attempt identifiers; store returned payloads with the originating call receipt, after manager execution has returned. |
| `CompressionTee` | existing `store_result` path | Preserve producer correlation and expose persistence failure as degraded tracking; never claim a failed tee is durable evidence. |
| `ConversationTurn` and memory compaction | shared invocation source | Enabled turns consume observer records once; legacy conversion remains the fallback for unobserved turns. |
| `AbstractBot` / `BaseBot` | turn lifetime and rendering | Scope setup/reset for ordinary and streaming entry points; inject bounded recall when the compaction result requests Stage 2. |
| `RedisConversation` | atomic metadata merge | Preserve task association, compaction calibration, and unrelated metadata under concurrent writers. |
| REPL worker bridge | explicit materialization | Strict Arrow/JSON path, worker generation checks, bounded loads; no pickle fallback for task evidence. |

### Data Models

New domain models use Pydantic v2, `schema_version=1`, timezone-aware UTC timestamps, explicit enums, and bounded collections/text. Existing compaction dataclasses retain their serializer. Runtime IDs use existing stdlib `uuid.uuid4()`; Python 3.11 compatibility rules out assuming stdlib `uuid7`, and no ULID dependency is introduced.

| Model | Required fields and invariants |
|---|---|
| `TaskScope` | `chatbot_id`, `user_id`, `session_id`; supplied by trusted runtime. `chatbot_id` is the bot's stable `memory_key_id`. Every store query, cache lookup, artifact load, and journal read checks this scope. |
| `Constraint` | Runtime `constraint_id`, text ≤500 characters, active flag, revision. |
| `CompletionPolicy` | `mode: validated\|agent_asserted`, code-registered validator names, expected output aliases, `require_note=True`. Unknown validators rejected. |
| `TaskStep` | Runtime `step_id`, title ≤120, description ≤2,000, required flag, dependency IDs, status, completion policy, versioned evidence refs, attempt count, blocked reason, created/updated revisions, completion source. |
| `Decision` | Runtime ID, text/reason ≤500 each, actor, affected step IDs, revision, active flag. |
| `ResumeHint` | Text ≤500, optional step ID, actor, revision, derived stale flag. |
| `TaskState` | ID/scope, goal ≤2,000, constraints, status, `plan_complete=False`, `plan_revision`, monotonic `revision`, steps, decisions, hint, created/updated timestamps, `last_event_seq`. Active and ready step IDs are derived; no persisted duplicate lists. |
| `JournalEvent` | Runtime `event_id`, task ID, backend-assigned contiguous `seq`, UTC timestamp, event type, actor, turn ID, plan revision, optional step/call/parent-call IDs, attribution, bounded typed payload. |
| `ArtifactDescriptor` | Read projection shared by DataFrame and generic entries: ID/version, alias, scope/task/producer IDs, attribution, kind, availability, fingerprint and algorithm version, verification flag, byte size, captured shape/schema, storage reference, optional REPL binding. No data rows or raw payload. |
| `ReplBinding` | Worker generation/session ID, variable name, artifact ID/version; a PID alone is not a generation identity. |
| `TaskContext` | Immutable per-invocation snapshot of scope, task, plan revision, turn, declared step IDs, parent call ID; optionally explicit plan run/node/item correlation. |
| `InvocationRecord` | Runtime call ID, attempt, parent ID, canonical existing `ToolInvocation`, task context snapshot, typed outcome, and artifact receipts. Correlation is internal, not a new tool parameter. |

Task statuses: `active`, `blocked`, `paused`, `completed`, `failed`, `cancelled`. Step statuses: `pending`, `running`, `blocked`, `completed`, `failed`, `cancelled`, `superseded`. Artifact availability: `memory`, `persisted`, `missing`, `expired`; invalidation and `binding_invalid` are separate descriptor flags, not proof that the durable payload disappeared. Actors: `agent`, `runtime`, `validator`, `sweeper`.

Initial configurable limits: 100 open tasks per scope; 1,000 steps, 100 active constraints, and 1,000 active decisions per task; 100 dependency/evidence references per step; identifiers ≤128 characters; reasons/notes ≤2,000; schema-summary serialization ≤4 KiB. Exceeding a limit returns a typed limit error before mutation. Pagination cursors are opaque, scoped, bounded, and validated. Journal payloads have an 8 KiB serialized UTF-8 limit, not Pydantic dictionary-item counting.

Events include all proposal events: `task_started`, `task_paused`, `task_resumed`, `task_completed`, `task_failed`, `task_cancelled`, `plan_updated`, `decision_recorded`, `resume_hint_updated`, `tool_started`, `tool_succeeded`, `tool_failed`, `tool_cancelled`, `tool_outcome_unknown`, `artifact_registered`, `artifact_invalidated`, `step_started`, `step_blocked`, `step_completed`, `step_failed`, `step_reopened`, `tracking_degraded`. Add explicit `task_blocked`, `step_cancelled`, and `retention_scheduled` payload variants for otherwise unrepresented transitions. Supersession is recorded inside `plan_updated`.

### New Public Interfaces

All names below are proposed, not existing contracts. Python method names omit `wm_`; the toolkit's existing prefix generates these tool names. Every method has a docstring and an explicit Pydantic input schema. Internal services remain outside toolkit autodetection.

| Tool | Inputs | Result |
|---|---|---|
| `wm_begin_task` | `goal`, `constraints=[]`, `steps=[]`, `plan_complete=False` | Runtime task/step IDs, revision, compact state; selects the new task after persistence. |
| `wm_update_plan` | `task_id`, `expected_revision`, typed `changes`, `reason` | New revision and affected IDs, or `RevisionConflict` with current compact state. |
| `wm_update_step` | `task_id`, `step_id`, `expected_revision`, `status`, `evidence_refs=[]`, `note=None` | Accepted transition or validation failure. |
| `wm_record_decision` | `task_id`, `text`, `reason`, `affected_step_ids=[]` | Decision ID and revision. |
| `wm_set_resume_hint` | `task_id`, `next_action`, `step_id=None` | Saved hint and revision. |
| `wm_recall_task` | `task_id=None`, `max_tokens=2500`, `recent_calls_limit=8` | Budgeted snapshot and truncation accounting. |
| `wm_list_task_events` | `task_id`, `after_seq=0`, `limit=50` | Ordered bounded events, next sequence/cursor. |
| `wm_list_task_artifacts` | `task_id`, `limit=50`, `cursor=None` | Version descriptors and next cursor. |
| `wm_select_task` | `task_id` | Validated selected association and compact state. This fills the proposal's missing selection operation. |
| `wm_update_task` | `task_id`, `expected_revision`, `status`, `reason=None` | Pause/resume/block/fail/cancel/complete through the same event rules. This fills the missing lifecycle operation. |

Input task/step IDs reference runtime-created identities; they cannot override scope. Initial plans use request-local labels for dependencies, resolved to runtime step IDs before append. `PlanChanges` is a discriminated union of add/update/supersede-step, add/update/deactivate-constraint, and set-plan-complete operations. Existing IDs are immutable; dependencies, criteria, and inputs are validated before any batch is committed.

An omitted task ID resolves only from the authoritative selected association. If multiple open tasks exist without a selection, return `needs_task_selection` and a bounded page of `{task_id, goal[:80], status, updated_at}`. Never use semantic similarity. An explicit same-scope task ID remains usable when conversation metadata is lost; recall does not silently select it. `wm_select_task` repairs the association explicitly.

### Reducer and Completion Rules

`reduce(state: TaskState | None, event: JournalEvent) -> TaskState` is pure and deterministic for supported schemas; malformed or unsupported events raise `ReducerError`. The store validates commands before append. No wall-clock reads, validators, file I/O, tools, or random IDs occur during replay.

- The store deduplicates `event_id` before allocating sequence numbers. An identical redelivery is a no-op; reuse with a different payload is rejected. The reducer ignores already-applied sequences; forward gaps raise. No unbounded in-projection seen-ID set.
- Event sequence increases per appended event. `revision` advances per accepted state-changing command/event batch; `plan_revision` advances only for a plan change. Expected-revision checks and append/reduction share one transaction. Exact redelivery is recognized before stale-revision rejection.
- Plans reject cycles, duplicate IDs, missing dependencies, and illegal statuses. Removed steps become superseded and retain evidence/history. Pending steps are ready only when every dependency is completed; superseded/failed/blocked dependencies do not satisfy readiness.
- Completed criteria or inputs cannot be edited in place. Reopen explicitly, retain previous evidence, and block transitive dependents with `upstream_reopened`; restore readiness only after upstream completion and dependent revalidation, not merely because a tool succeeds.
- A task completes only with `plan_complete=True` and all required, non-superseded steps completed. Exhausted partial plans stay active and show `plan_incomplete`. Terminal tasks do not accept ordinary mutations; create a new task for further work.
- `validated` completion requires all registered policy validators to pass and all expected outputs to bind to exact artifact versions. `agent_asserted` requires at least one accessible evidence ref and the required note; recall always labels this weaker completion source. Unverifiable artifacts cannot satisfy a fingerprint validator.
- Built-ins: `artifact_exists`, `artifact_fingerprint_matches`, `artifact_non_empty` using captured shape, and `no_pending_tool_failures`. Unknown/cancelled outcomes remain unresolved until an explicit later attempt or validated resolution records their disposition; a successful unrelated call cannot clear them.
- Count each attributed physical attempt once on its terminal event. Failure does not auto-fail the step/task; default `max_attempts=3` emits `step_blocked` only for unambiguously attributed failures. Task-level failures remain visible without assigning them to a guessed step.
- Validators run only on requested completion, outside long-held database locks. Commit their results against the same expected task revision and artifact version/fingerprint; any change forces retry/revalidation. Replay consumes the recorded results only.
- Later events affecting a hint's step, dependencies, or evidence mark it stale. Recall and listing commands append no events, including through the observer; repeated reads must not change recall's sequence or fill the journal.

### Single Observer and Turn Context

Install an optional observer around the existing manager dispatch. Keep guard ordering, approval behavior, permissions, compression, full-result envelopes, and cancellation propagation. Authorization denials and unknown tools are classified as unsuccessful dispatch outcomes with an explicit `executed=False`; they do not pretend a tool body ran. Persist `tool_started` after authorization and immediately before an actual execution attempt. Persist the terminal result before reporting tracked success.

For an enabled turn, an internal turn session captures canonical invocation records once and feeds both journal derivation and `ConversationTurn.tool_invocations`. Do not concatenate duplicate `AIMessage.tool_calls` conversions. Unobserved/disabled turns retain the existing constructor path. `ToolInvocation` currently has only completed/error statuses and no call ID: preserve it as the shared normalized payload, with cancellation/unknown/denied status and correlation in `InvocationRecord` and journal events. Do not invent new existing enum members.

Result adapters inspect typed envelopes before payload reduction. Respect `ToolResult.success/status/error`, toolkit `{"status":"error"}` responses, and plan manifest failures/partial results; default ordinary values succeed and exceptions fail. Never parse free text to infer success. Nested plan calls have a parent call ID and separate child attempt IDs. The parent aggregate is distinguishable from the physical attempts and is not counted as a second execution of each child.

`TASK_CONTEXT` is request scoped and always reset in `finally`, including cancelled streams. A ContextVar assignment inside a child task does not publish a new value to its parent or siblings. Therefore, the runtime owns a per-turn session containing a lock-protected declaration registry, referenced through a ContextVar; it creates a frozen `TaskContext` snapshot at each dispatch. Successful running-step updates publish through this shared session. Dispatch after two declarations sees `ambiguous`; dispatch before a later declaration retains its original snapshot. Concurrent control mutations and dependent work must use explicit completion barriers; never retroactively guess attribution.

Zero declared steps gives task-level `none`; exactly one gives `declared`; more than one gives task-level `ambiguous`. An explicit plan-to-task-step mapping overrides this with `plan`. Plan node IDs are not automatically domain step IDs: persist the mapping under plan run/node identity, or keep an unmapped plan call task-level with plan provenance. Plan runs do not create tasks or steps automatically (OQ2 default).

Copy turn context to spawned asyncio tasks and thread work; serialize only a bounded runtime context envelope across the REPL process boundary. Revalidate scope, selected task, worker generation, and fencing token on return. `PlanToolNode` retains the attempt receipt until its post-dispatch `_store` finishes, so artifacts do not lose their `producer_call_id` when the manager resets its invocation context.

### Catalog Backend, Versions, and Evidence

Both `CatalogEntry` and `GenericEntry` receive a shared version-metadata component and `to_descriptor()` projection. Keep the existing computed `CatalogEntry.shape` property; capture metadata under a separate field rather than shadowing it. Descriptors never call `compact_summary()`, `describe()`, or arbitrary object `repr()` during recall.

The catalog's current synchronous `put`, `put_generic`, `get`, and `drop` remain valid for the legacy configuration. Add awaited backend operations (`aput`, `aput_generic`, `aget`, `adrop`) for enabled task memory; migrate enabled toolkit, plan, import, temporary-result, and tee paths to them. A synchronous write against an enabled persistent catalog fails explicitly with guidance to the awaited API; it cannot fire-and-forget persistence or block the event loop. This opt-in restriction is deliberate. CPU-heavy snapshots/hashes/serialization use threads; commit/catalog mutation stays on the owning event loop under an `asyncio.Lock`. Never hold that lock across tool execution.

The artifact-store protocol is defined in new `parrot.interfaces.artifact_store`, independent of the unrelated existing `parrot.storage.artifacts.ArtifactStore`. Use leaf Pydantic metadata models plus stdlib typing; do not import pandas, REPL workers, or concrete database backends into contract modules. Proposed operations are asynchronous `put`, `get_current`, `get_version`, `load_payload(max_bytes=...)`, `invalidate`, `list`, and `evict`. Every operation carries trusted scope; version lookup by globally unique ID alone is not authorization.

Aliases are keyed by `(scope, task_id, key)` for enabled tasks. Within that namespace, first write allocates `artifact_id, version=1`; overwrite atomically increments the same identity's version and moves the alias. Explicit same-scope cross-task evidence references require access validation and pinning; plain keys never search another task. Deleting an alias retains an identity tombstone until retention permits removal, so drop/recreate cannot reuse a version accidentally.

On registration, capture structural metadata and an independent snapshot under the 64 MiB cap. Numeric/text-compatible DataFrames and JSON/text are supported evidence types. A pandas deep copy alone must not be accepted as proof that nested object-dtype contents were detached: unsupported or mutable nested values require a verified safe snapshot adapter or `evidence_verifiable=False`. Arbitrary object copying/hashing failures return an explicit unverifiable descriptor rather than claiming integrity.

Above the cap, spill supported DataFrames as Parquet and JSON/text as canonical bytes using the same backend's file storage. Without a durable tier, retain bounded metadata and mark unverifiable. In Delivery B durable mode, supported artifacts below the cap are also written through to durable storage before their registration succeeds; the cap controls the optional RAM snapshot, not whether evidence survives a restart. Use actual snapshot/payload bytes when available; pandas deep-memory estimates are estimates, and `sys.getsizeof` alone never proves an arbitrary object fits. Enforce byte budgets while serializing and before materialization; account for live and snapshot copies separately.

Fingerprints use `fp_` plus BLAKE2b-8, with a stored algorithm version. DataFrame canonical content includes shape, ordered column names, dtype/index metadata, and stable row/index hashes; JSON/text uses canonical UTF-8 bytes with sorted keys. The serializer must reproduce the same fingerprint across reloads. A blob checksum may be recorded separately; do not compare a Parquet-byte hash with a pandas-content hash. Unsupported values have no valid fingerprint.

At completion, resolve bare aliases once and bind exact `artifact_id@version` references; reject bare aliases at the journal boundary. Validate the referenced immutable snapshot. For a still-associated live alias/REPL binding of that SAME version, compare its current fingerprint too; mutation invalidates that evidence and blocks completion. If the alias now points at a newer version, this is an overwrite, not mutation of the old version: old evidence must remain valid and resolvable. Previously completed steps depending on truly invalidated evidence are reopened/blocked by explicit events.

`drop_stored` removes the live alias; it does not delete pinned snapshots. Missing or evicted payloads produce explicit expired/invalidated descriptors and events. Persisted evidence remains recoverable even when its live alias or worker binding has gone away.

### ResultPolicy and REPL Recovery

When task memory is enabled, `wm_get_result(include_raw=True)` uses `max_rehydrate_bytes=2_000_000` by default, with `0` meaning never. The configuration is a hard ceiling; a caller may lower it but cannot raise it. Add nonnegative `offset` and bounded positive `limit` (default 100, maximum 1,000) for tabular pages. Enforce both decoded page size and serialized returned bytes; a small page may be read without rehydrating the full table. Over-limit responses contain no raw payload and point to `wm_compute_and_store`. Opaque objects are not made safe by truncating their repr after loading them.

Without task memory, the legacy raw-result behavior and schemas remain unchanged. Choose the enabled input model during tool generation rather than adding fields to the disabled schema. This resolves the proposal's conflict between a new unconditional cap and byte-identical disabled behavior. The opt-in cap is documented as an intentional behavior change.

`ReplBindingResolver.load(scope, artifact_id, version, worker_session_id)` materializes only on explicit request. It verifies scope/version/size and fingerprint, uses strict Arrow IPC for DataFrames or safe JSON values, and returns a generation-bound binding. Existing worker injection can fall back to pickle: add an opt-in strict mode to the transport/handle boundary and reject unsupported types before creating a pickle payload. Do not change legacy transport defaults. Missing worker generations produce `binding_invalid`; a valid persisted artifact remains locatable. Never reconstruct arbitrary namespaces or replay Python code.

### Recall and Stage 2

Recall reads one consistent projection plus bounded indexed event/descriptor pages at `as_of_seq`; no full-journal scan, data load, tool execution, LLM request, or plan execution. Output includes scope-safe identity, goal, constraints, task/plan revision and status, completion source, blockers, active/ready steps with criteria/refs, decisions, hint/staleness, unresolved outcomes, artifacts, and truncation accounting.

Select whole units in this order: (1) identity, goal, active constraints and critical blockers; (2) active/ready steps; (3) active decisions and resume hint; (4) completed required step IDs/titles and recent calls, prioritizing unresolved failures; (5) relevant recent artifact descriptors. Within each class use stable sequence/ID ordering. Record omitted calls/artifacts/steps; never truncate serialized JSON strings.

Reserve envelope and truncation-field costs, serialize canonically, and measure with `get_default_counter()` and the captured compaction calibration. Remove optional units until the complete result fits. If required content cannot fit, return `budget_too_small` with measured `required_min_tokens`. Enforce positive bounded requests (`max_tokens` 1–16,000; `recent_calls_limit` 0–100). With the existing heuristic counter, enforce the proposal's four-bytes-per-token byte ceiling and set `tokens_estimated=True`; this is an estimate, not a guaranteed upper bound on provider tokens.

Cache keys include encoded scope, task ID, task sequence, artifact availability generation, canonical arguments, tokenizer identity, calibration, and recall schema version. Default cache TTL is 10 minutes. Worker generation and expired omission availability can change without a task event: cached overlays must be refreshed or included in the generation key. Determinism means identical captured state, availability snapshot, counter/calibration, and arguments yield identical bytes; it cannot mean that expired content stays available forever at the same task sequence. Treat unknown/expired `om_...` IDs honestly, preserving the existing single `om_` prefix. Existing `OmissionStore.get` loads content: introduce an additive scoped availability probe for the built-in stores, with an unknown fallback for custom stores, so recall never fetches large omitted text just to test existence.

For Stage 2 use `CompactionResult.stage2_needed` at render time, not only the lifecycle event emitted after saving a turn. The existing flag covers watermark overflow or exceeding available budget; there is no separate exhausted-prunables callback registry. Add the deterministic task recall candidate at the bot rendering layer when a task is selected and the signal is present. Account for recall within `ContextBudget.available`, recompute retained history allowance, and include framing/calibration in the final measurement. Preserve verbatim minimums or decline injection with an explicit diagnostic when both cannot fit. Never inject and also instruct the model to call recall in the same turn. Injection is transient context, not a fabricated conversation turn or a claim that LLM summarization occurred. Keep existing event telemetry and the compaction kill switch.

### Persistence and Recovery

`TaskMemoryStore` provides scoped asynchronous creation, atomic `append_events(..., expected_revision)`, snapshot loading, task listing, and event paging. In-memory and PostgreSQL implementations have identical command/reducer semantics. PostgreSQL uses schema `working_memory` with migrations applied explicitly at deployment, not arbitrary schema creation on every tool call.

| Table | Required contract |
|---|---|
| `tasks` | Proposal columns: task PK; scope; status; revision/last sequence; JSONB projection and reducer version; created/updated/terminal timestamps. Index scope/status, terminal timestamp, and nonterminal activity. |
| `task_journal` | `(task_id, seq)` PK, globally unique event ID, event type/time/JSONB; FK to tasks. No gaps from deduplication. |
| `artifacts` | `(artifact_id, version)` PK; scope/task/producer identity; alias/kind/availability; fingerprint algorithm/value; verification flag; storage ref and captured bytes/shape/schema; creation/invalidation fields. |
| `artifact_aliases` | Unique `(scope, task_id, key)` using a non-null namespace representation for unassociated entries; current artifact/version and alias tombstone. Row serialization prevents concurrent writers allocating duplicate versions. |
| `artifact_evidence` | Task/step/artifact/version reference relation. Pinning derives from all nonterminal references, not one mutable boolean or only the producing task. |
| `schema_migrations` | Applied migration version/timestamp; reversible schema migration instructions. |

For append, create/lock the task row (`SELECT ... FOR UPDATE`), verify scope and idempotency, check expected revision, allocate only new contiguous sequences, reduce, insert journal rows, update projection/timestamps, commit. A rejected command changes nothing. Same-task appends serialize in PostgreSQL; different tasks can progress concurrently. Snapshot reads use a consistent transaction or explicit sequence fences for event/artifact pages.

Durable artifact publish order: write immutable blob → verify readability/checksum → atomically commit alias/version index, evidence metadata, and `artifact_registered` on the same database connection/transaction. Publish the in-process cache only after commit. The task and artifact stores share a transaction coordinator; two unrelated pool transactions are insufficient. Orphan blobs are expected after crashes and are swept after a grace period. Never publish a storage reference before its bytes exist.

Lazy projection migration replays the journal under a task lock when the reducer version is older; unknown newer versions are rejected explicitly. Never truncate retained journal prefixes without a separately versioned replay checkpoint design.

Redis association lives in `ConversationHistory.metadata["task_memory"]` with `open_task_ids`, `selected_task_id`, and an association revision. Enabled metadata updates use a single atomic compare-and-merge protocol, including compaction writers and full-history mode; a task-only lock is insufficient when compaction ignores it. Preserve unrelated keys. Task creation commits first, then updates association; if Redis fails, return the committed task ID with association degradation so the caller can recover/select it without duplicating the task. A missing association does not delete PostgreSQL tasks.

Redis key families follow the existing configured prefix and stable bot/user/session scope: `_task_lease`, `_task_recall`, `_task_ctx`, with collision-safe component encoding. Lease TTL 30 seconds, renewed only by the owner; recall 10 minutes; context 24 hours. Context cache is never authoritative for task state. Association follows configured history retention; task-memory mode requires an explicit finite hot-key retention when the underlying history has no TTL.

Recovery appends `tool_outcome_unknown` only for a started call whose owner is provably no longer live or whose fenced call ownership expired. Keep per-call ownership/heartbeats for long-running calls; the short append lease alone cannot identify a crash. Reconcile idempotently under the task lock. Late results from an old owner cannot overwrite a newer terminal decision. Never retry unknown external effects automatically, including through a plan retry policy; expose a typed non-retryable outcome for this condition.

Durable journal-start failure raises `TaskMemoryUnavailable` before execution. If the external effect ran but terminal persistence failed, return an explicit unknown/degraded outcome, preserve the durable start, and avoid reporting success or inviting automatic retry. Cancellation recording is bounded and shielded where feasible, then cancellation is re-raised. If best-effort tracking is explicitly enabled, surface degradation in the result even when the journal is unavailable; persist a truthful gap/degradation event after recovery, without inventing lost events. A failed tee/storage write follows the same honesty rule.

### Retention and Redaction

Configuration uses `navconfig` under `TASK_MEMORY_*`. `RetentionSweeper.run_once` is idempotent and accepts an injected clock. Host applications may schedule it through their existing qworker deployment; single-process deployments use an asyncio periodic task with explicit startup/shutdown. No mandatory new queue dependency.

| Object | Policy/default |
|---|---|
| Active task without activity | Append inactivity pause after 7 days; reads do not reset activity. |
| Task paused for inactivity | Cancel after 30 days measured from that pause, recording the reason and terminal time. |
| Terminal journal/projection | Retain 90 days from `terminal_at`; optional JSONL archive must succeed and verify before deletion. |
| Journal size | 8 KiB payload cap. At 50,000 events stop retaining optional recent-call material in recall; configure a hard cap of 100,000 plus 1,000 reserved terminal/recovery/retention events. Refuse new foreground work before exhaustion; never silently discard history. |
| Artifact snapshots | Protect nonterminal evidence. Unpinned noncurrent versions expire after 24 hours; terminal current versions follow 90-day retention. Cross-task pins defer deletion. |
| In-memory artifacts | Default 512 MiB LRU accounting for retained payload copies. Spill pinned supported evidence when configured. If no tier can retain it, record invalidation and retain a metadata tombstone; Delivery A cannot promise retained bytes. |
| Orphan blobs | Sweep after 1 hour only when no live index, pending publish lease, or archive references the blob. |
| Redis | TTLs above; renew leases with compare-owner semantics and release only the current owner's lease. |
| Journal omission refs | Existing omission retention applies; expired references remain explicitly expired. In-memory omission storage does not provide durable retention guarantees. |

Retention appends its intent/invalidation events before destructive work. Terminal deletion necessarily removes the local journal containing that intent: when archive is configured, archive includes the final retention event; without archive, deletion is deliberately irreversible and leaves only bounded operational audit logs. Do not claim permanent in-journal audit after deleting the journal. Failed archive/deletion retries are idempotent. No eviction silently removes evidence while leaving a step labeled valid.

Normalize journal text using existing Stage 0 primitives, then apply a new secret redactor before storage/offload. Stage 0 normalization is not a secret-redaction policy. Deny sensitive key names (`token`, `secret`, `password`, `authorization`, `api_key`, configured additions), constrain argument depth/size, and omit arbitrary full code/rows/credentials rather than embedding them in journal payloads. Redact errors too. Journal omission references contain only permitted redacted content; storage and cache keys never contain credentials. Task data recalled into the prompt is untrusted data, not higher-priority instructions.

## 3. Module Breakdown

Paths are relative to the repository root. All new paths below are proposed and do not claim existing modules.

| Module | Paths | Responsibility and dependencies |
|---|---|---|
| M1 — Domain and contracts | `packages/ai-parrot/src/parrot/interfaces/task_memory.py`, `packages/ai-parrot/src/parrot/interfaces/artifact_store.py`; `packages/ai-parrot/src/parrot/tools/working_memory/task_memory/{__init__,models,config,reducer}.py` | Leaf typed contracts, limits, errors, reducer and config; no concrete backend import at module load. |
| M2 — Catalog and snapshots | `packages/ai-parrot/src/parrot/tools/working_memory/{internals,tool,models}.py`; new `task_memory/{artifacts,snapshots}.py` | Awaited catalog path, both entry types, scope/version metadata, bounded memory backend, ResultPolicy; depends on M1. |
| M3 — Task service and memory store | new `task_memory/{service,validators}.py`, `task_memory/store/{__init__,_base,memory}.py` | Atomic command validation, completion, event store, projection; depends on M1/M2. |
| M4 — Observation and attribution | new `task_memory/{context,observer,adapters,redaction}.py`; `packages/ai-parrot/src/parrot/tools/{manager.py,compression/tee.py}` | Shared invocation collector, lifecycle observer, receipts, fail-closed/degraded handling; depends on M3. Preserve manager clone and shared-tool behavior. |
| M5 — Task tools and recall | new `task_memory/{tools,recall,association}.py`; working-memory `tool.py`, `models.py`, `__init__.py` | Explicit tool schemas, enabled-only exposure, deterministic selection, pagination and cache; depends on M3/M4. |
| M6 — Bot and compaction integration | `packages/ai-parrot/src/parrot/bots/{abstract,base,agent}.py`; `packages/ai-parrot/src/parrot/memory/{abstract,redis}.py`; `packages/ai-parrot/src/parrot/memory/compaction/omission.py` | Context lifetimes, canonical invocation handoff, atomic metadata, bounded Stage 2 candidate and omission availability probe; depends on M4/M5. Reuse compaction models/functions without making clients own memory. |
| M7 — Plan and REPL adapters | `packages/ai-parrot/src/parrot/bots/flows/plan/{node,models}.py`; `packages/ai-parrot/src/parrot/tools/execution_plan/toolkit.py`; new `task_memory/repl.py`; `packages/ai-parrot/src/parrot/tools/repl_worker/{handle,protocol,transport,worker,inprocess}.py` | Plan mapping/receipts, strict serialization, generation-bound rehydration, compatible in-process worker path; depends on M2/M4. |
| M8 — Durable stores and retention | new `task_memory/store/postgres.py`, `task_memory/{blob,retention}.py`, `task_memory/migrations/001_task_memory.sql` | Shared transaction coordinator, aliases/pins, file-manager adapter, crash reconciliation, archive/sweep; depends on M1–M4/M7. |
| M9 — Verification and documentation | new `packages/ai-parrot/tests/tools/working_memory/task_memory/`; existing WM/plan/REPL/compaction regression suites; new `docs/memory/recoverable-task-memory.md` | Unit, concurrent DB, restart, primary acceptance scenario, benchmarks and configuration/migration docs; depends on applicable modules. |

Phase 0 precedes implementation: revalidate this pinned integration map on the implementation base; inventory any additional direct catalog/manager call sites; benchmark snapshot/hash at 8/64/256 MiB; verify actual file-manager stream/stat methods before coding its adapter. This is bounded validation, not permission to assume absent interfaces or expand into a general memory refactor.

## 4. Test Specification

### Unit Tests

| Test group | Required cases |
|---|---|
| Domain/reducer | Exact event replay, duplicate IDs and sequence gaps, conflict without mutation, unsupported versions, cycles/missing dependencies, supersession, partial plans, reopen propagation, task completion guard, hint staleness. |
| Validators | Expected-output binding, unknown registry names, empty/error artifacts, asserted labels/notes, mutation during validation, old version after overwrite, unresolved failure handling. |
| Snapshot/backend | DataFrames and generic entries, nested mutable values, hash/schema changes, 64 MiB boundary, unsafe object fallback, byte-accounted LRU, alias race, drop/recreate, multiple-task pins. |
| Observer | Both manager branches and full-result mode; success, error-as-data, typed denial, missing tool, exception, timeout/cancellation, nested plan, retries, terminal-write failure and no false success. |
| Context | Same-turn declaration barriers; zero/one/multiple declarations; child task publication; thread propagation; finally reset; concurrent users/tasks; plan post-dispatch storage receipt. |
| Recall | Exact deterministic serialization with captured calibration/availability, priority selection, complete JSON, minimal budget error, Unicode/heuristic bytes, cache isolation/invalidation, bounded queries, no rows/describe/REPL load/events. |
| ResultPolicy | Exact byte boundary, disabled raw reads, pagination without full load, unsupported objects, no payload on error, unchanged legacy schema/output when disabled. |
| Retention | Injected clocks, 7-day pause, 30-day abandonment, 90-day terminal expiry, archive failure, reserved-event limits, pins, orphans during live publication, TTL/missing refs. |

Use deterministic event fixtures and generated event permutations within pytest; no new property-testing dependency is required. Existing seeded WM fixtures may be reused, but enabled-mode fixtures must use awaited registration rather than direct legacy catalog writes.

### Integration Tests

| Test | Required result |
|---|---|
| Primary continuity | Synthetic large dataset → task with four steps → two completions (validated and asserted) → recoverable failure → discard conversation context → recall with explicit same-scope task ID → preserve constraints/version refs and next ready step without repeating work. |
| Durable restart | Repeat primary scenario after host and worker restart; supported payloads reload, stale binding is reported, and unavailable omission content is labeled honestly. |
| Crash matrix | Crash before/after blob write, index/journal transaction, tool start, external effect, terminal append, archive, and deletion; no phantom refs or automatic uncertain-effect retries. |
| Multi-pod append | Real PostgreSQL connections race expected revisions, duplicate events, task creation, and alias versions; contiguous sequences and one committed winner where appropriate. |
| Redis metadata race | Task selection races compaction calibration and full-history saves in both Redis storage modes; no lost metadata, scope crossing, or double task creation after association failure. |
| Plan/tee | Child attempts share manager instrumentation; post-dispatch artifact receipts retain provenance; parent aggregate is not counted as repeated child execution; errors/partial manifests are not valid completion evidence. |
| Live call recovery | A healthy long-running call survives another pod's reconciliation scan; expired fenced ownership becomes unknown once; late stale completion cannot rewrite it. |
| Stage 2 | Ordinary and streaming turns inject at most one snapshot when signaled, within combined history budget; no task or kill switch preserves current rendering. |
| Strict worker transport | Arrow/JSON round-trip, unsupported dtype fails without pickle creation, generation mismatch, size rejection, cancellation and shared-memory cleanup. |

### Test Data / Fixtures

Use injected UUID/clock providers for deterministic fixtures, numeric/string and nested-object DataFrames, mutable JSON, oversized Unicode text, malformed plans, typed error tool results, a side-effect counter tool, isolated PostgreSQL schemas, isolated Redis prefixes, temporary file storage, and real worker subprocesses for restart tests. Integration tests must clearly skip when configured services are unavailable; mocks alone do not establish durable correctness.

Planned focused command: `uv run pytest packages/ai-parrot/tests/tools/working_memory/task_memory/ -q`. Run existing working-memory tests at `packages/ai-parrot/src/parrot/tools/working_memory/tests/`, execution-plan tests at `packages/ai-parrot/tests/tools/execution_plan/`, and worker tests at `packages/ai-parrot/tests/repl_worker/`, plus affected manager/compaction regression tests discovered during task decomposition. Store logs in `artifacts/logs/`.

## 5. Acceptance Criteria

- [ ] AC1: One explicit task ID plus one recall restores goal, constraints, active/ready work, refs, unresolved failures, and truthful completion sources after context loss.
- [ ] AC2: In-process and PostgreSQL stores pass identical reducer, idempotence, revision, plan-validation, and scope-isolation tests.
- [ ] AC3: Tool error values, exceptions, denial, cancellation, and uncertain outcomes never automatically complete a step; actual attempts are counted once.
- [ ] AC4: Concurrent declared steps yield ambiguous attribution; explicit plan mappings preserve per-step provenance and post-dispatch artifact correlation.
- [ ] AC5: Overwriting an alias preserves older evidence; mutation of the same bound version invalidates it; nested mutable data never receives a false verification claim.
- [ ] AC6: Oversized unsupported/unspilled objects are explicitly unverifiable; raw reads enforce configured byte ceilings and tabular pagination.
- [ ] AC7: Replanning retains history and blocks affected dependents; exhausted partial plans remain active; required-step and plan-complete checks gate task completion.
- [ ] AC8: Durable startup/terminal persistence failures are surfaced accurately; unknown external outcomes are reconciled once and never automatically retried.
- [ ] AC9: Restart recovers task projections and supported persisted payloads; stale REPL bindings are diagnosed and only explicit strict loads materialize evidence.
- [ ] AC10: Recall is read-only, deterministic for captured inputs, bounded by the configured estimator/byte policy, and avoids raw payloads, expensive summaries, and unbounded scans.
- [ ] AC11: Explicit task selection and scoped reads prevent cross-task/session/user/agent mixing; Redis metadata races preserve association and compaction state.
- [ ] AC12: The retention table, hard limits, pins, archive verification, and failure retries are implemented with auditable intent and no silently valid expired evidence.
- [ ] AC13: Disabled task memory preserves existing public schemas, outputs, AnswerMemory behavior, guardrails, permissions, and compression behavior.
- [ ] AC14: Enabled ordinary/streaming turns share canonical invocation capture and bounded Stage 2 injection; context never leaks after exit or cancellation.
- [ ] AC15: All focused unit and provisioned integration tests pass; affected existing regressions pass; migration, opt-in configuration, A/B limitations, and recovery operations are documented.
- [ ] AC16: Record recall tokens/build time, observer overhead, invalid-ref rate, repeated-operation count after recovery, and snapshot/hash cost at 8/64/256 MiB. No latency SLO is claimed before measurement; deterministic byte/token caps remain mandatory.

## 6. Codebase Contract

All anchors below were read at the pinned implementation commit. The import block passed an actual import smoke check; output is retained in `artifacts/logs/workingmemory_spec_imports.log`. Proposed symbols elsewhere in this document are not permission to import them before implementation. Line numbers refer to existing code, not generated files.

### Verified Imports

```python
from parrot.tools.working_memory import WorkingMemoryToolkit  # packages/ai-parrot/src/parrot/tools/working_memory/__init__.py:2
from parrot.tools.working_memory.internals import CatalogEntry, GenericEntry, WorkingMemoryCatalog  # packages/ai-parrot/src/parrot/tools/working_memory/internals.py:70
from parrot.tools.toolkit import AbstractToolkit  # packages/ai-parrot/src/parrot/tools/working_memory/tool.py:9
from parrot.tools.manager import ToolManager  # packages/ai-parrot/src/parrot/tools/manager.py:249
from parrot.memory.compaction.models import ToolInvocation, ToolStatus, ContextBudget  # packages/ai-parrot/src/parrot/memory/compaction/models.py:24
from parrot.memory.compaction.tokens import get_default_counter  # packages/ai-parrot/src/parrot/memory/compaction/tokens.py:89
from parrot.memory.compaction.normalize import normalize_invocation  # packages/ai-parrot/src/parrot/memory/compaction/normalize.py:129
from parrot.memory.compaction.omission import OmissionStore  # packages/ai-parrot/src/parrot/memory/compaction/omission.py:48
from parrot.bots.flows.plan.models import ArtifactRef, ExecutionManifest  # packages/ai-parrot/src/parrot/bots/flows/plan/models.py:413
from parrot.bots.flows.plan.node import PlanToolNode, build_manifest  # packages/ai-parrot/src/parrot/bots/flows/plan/node.py:57
```

### Existing Class Signatures

| Existing API | Exact signature/shape | Verified at |
|---|---|---|
| Toolkit constructor | `__init__(self, session_id: Optional[str] = None, max_rows: int = 10, max_cols: int = 30, tool_locals_registry: Optional[dict[str, dict]] = None, answer_memory: Optional[Any] = None, thread_offload_cells: Optional[int] = None, **kwargs)` | `packages/ai-parrot/src/parrot/tools/working_memory/tool.py:103` |
| DataFrame registration | `async store(self, key: str, df: pd.DataFrame, description: str = "", turn_id: Optional[str] = None) -> dict` | `packages/ai-parrot/src/parrot/tools/working_memory/tool.py:194` |
| Generic registration | `async store_result(self, key: str, data: Any, data_type: str = "auto", description: str = "", metadata: Optional[dict] = None, turn_id: Optional[str] = None) -> dict` | `packages/ai-parrot/src/parrot/tools/working_memory/tool.py:208` |
| Result reading | `async get_result(self, key: str, max_length: int = 500, include_raw: bool = False) -> dict`; raw payload only for generic entries today | `packages/ai-parrot/src/parrot/tools/working_memory/tool.py:259` |
| Catalog construction | `__init__(self, session_id: Optional[str] = None) -> None`; `_store: dict[str, CatalogEntry \| GenericEntry]` | `packages/ai-parrot/src/parrot/tools/working_memory/internals.py:468` |
| Catalog reads/writes | `put(...) -> CatalogEntry`, `put_generic(...) -> GenericEntry`, `get(self, key: str) -> CatalogEntry \| GenericEntry`, `drop(self, key: str) -> bool` are synchronous | `packages/ai-parrot/src/parrot/tools/working_memory/internals.py:473`, `:499`, `:542`, `:548` |
| Dispatcher | `async execute_tool(self, tool_name: str, parameters: Dict[str, Any], permission_context: Optional[PermissionContext] = None, *, return_tool_result: bool = False) -> Any` | `packages/ai-parrot/src/parrot/tools/manager.py:1514` |
| Omission writes/reads | `async put(self, session_key: str, content: str, *, turn_id: Optional[str] = None) -> str`; `async get(self, session_key: str, content_id: str) -> Optional[str]` | `packages/ai-parrot/src/parrot/memory/compaction/omission.py:61`, `:87` |
| Bot rendering | `async render_context_history(self, history: Optional[ConversationHistory]) -> Tuple[List[HistoryMessage], Optional[CompactionResult]]` | `packages/ai-parrot/src/parrot/bots/abstract.py:1742` |
| Plan manifest builder | `build_manifest(plan: Any, refs: Sequence[ArtifactRef], *, session_id: Optional[str] = None, duration_seconds: float = 0.0) -> Any` | `packages/ai-parrot/src/parrot/bots/flows/plan/node.py:568` |
| Worker injection | `async inject_dataframe(self, name: str, df: Any) -> None` | `packages/ai-parrot/src/parrot/tools/repl_worker/handle.py:1036` |

### Integration Points and Verified Corrections

| New component | Connects to | Verified fact / anchor |
|---|---|---|
| Enabled catalog backend | Both existing entry classes | `GenericEntry` owns `data`; `CatalogEntry` owns `df`, with computed shape and costly summary. `packages/ai-parrot/src/parrot/tools/working_memory/internals.py:70`, `:175`, `:189`, `:203`. |
| Tool exposure | `_generate_tools()` | Public async methods are discovered, excluding `_` and `exclude_tools`. `store` is already excluded; prefix is `wm`. `packages/ai-parrot/src/parrot/tools/toolkit.py:539`; `packages/ai-parrot/src/parrot/tools/working_memory/tool.py:78`. |
| Canonical invocation handoff | `ConversationTurn.from_ai_message()` | Existing list comprehension constructs invocations from tool calls; the enabled path must replace, not duplicate, it. `packages/ai-parrot/src/parrot/memory/abstract.py:178`, `:229`. |
| Journal normalization | `normalize_invocation()` | Canonicalizes text/JSON and condenses tracebacks; contains no credential redactor. `packages/ai-parrot/src/parrot/memory/compaction/normalize.py:129`. |
| Plan receipts | `_call_with_retry()` → `_store()` | Manager dispatch at `packages/ai-parrot/src/parrot/bots/flows/plan/node.py:431`; payload registration at `:350`; raw synchronous catalog reads at `:404`. |
| Compression capture | `CompressionTee.store()` | Awaits `store_result`; catches storage errors and returns `None`; retention calls `drop_stored`. `packages/ai-parrot/src/parrot/tools/compression/tee.py:95`, `:127`, `:140`. |
| Association | Redis key/metadata methods | Key includes prefix/bot/user/session; `_store_turn` reads and rewrites the metadata blob non-atomically. `packages/ai-parrot/src/parrot/memory/redis.py:65`, `:290`. |
| Stable bot identity | `memory_key_id` | Uses explicit chatbot ID or stable bot name, not the autogenerated process ID. `packages/ai-parrot/src/parrot/bots/abstract.py:1864`. |
| Stage 2 candidate | Render result and save event | Render returns `CompactionResult`; the lifecycle event fires only on persisted false→true after save. `packages/ai-parrot/src/parrot/bots/abstract.py:1793`, `:1983`; actual overflow signal at `packages/ai-parrot/src/parrot/memory/compaction/compact.py:325`. |
| REPL strict adapter | Existing transport | `encode_dataframe` catches conversion failure and emits pickle; strict task-evidence mode must prevent that branch. `packages/ai-parrot/src/parrot/tools/repl_worker/transport.py:55`, `:74`. |
| Blob I/O adapter | File-manager compatibility shim | `packages/ai-parrot/src/parrot/interfaces/file/__init__.py:18` re-exports the navigator file managers. Existing overflow is JSON-definition oriented, not a versioned Parquet backend: `packages/ai-parrot/src/parrot/storage/overflow.py:20`. |

### Does NOT Exist (Anti-Hallucination)

- No `parrot.tools.working_memory.task_memory` package, task-memory store/protocol, task context, versioned descriptor API, task association command, catalog lock, or awaited catalog backend at the pinned commit.
- No generic `ToolExecutionObserver` registry on `ToolManager`; existing guards, compression hooks, and the REPL resource observer are different mechanisms.
- No call ID, cancelled, or unknown status in the current compaction `ToolInvocation` model; only `ToolStatus.COMPLETED` and `ERROR` exist.
- No Stage 2 summary-provider registration API or recall injection currently exists. The lifecycle event is a signal, not an implemented summary hook.
- The proposal's repository-wide claim that `TaskState` and `ArtifactStore` do not exist is false: `packages/ai-parrot/src/parrot/a2a/models.py:34` defines an unrelated A2A `TaskState`; `packages/ai-parrot/src/parrot/storage/artifacts.py:27` defines conversation artifact CRUD. Neither is the task-memory contract.
- Execution-plan code is in core `parrot.bots.flows.plan` and `parrot.tools.execution_plan`, not `parrot_tools.plan`. Its manifest currently stores alias keys, not immutable evidence versions.
- The REPL bridge is not currently pickle-free. A strict resolver cannot simply call its existing injection API and assume safety.
- The catalog does not contain only DataFrames. Adding metadata exclusively to `CatalogEntry` misses `GenericEntry`, plan results, and compression tee payloads.

## 7. Implementation Notes & Constraints

### Patterns to Follow

Async-first service/backend methods; strict type hints; explicit Pydantic tool schemas; inherited toolkit logger; private lifecycle helpers; lazy optional backend imports. Preserve existing public defaults. No changes to provider schemas or `parrot/clients/base.py` are planned. Task context carries trusted runtime identity; no tool-authored scope. No backend I/O while holding a lock across a tool execution. Tests use pytest/pytest-asyncio, Python code follows black/isort, and logs live under `artifacts/logs/`.

### Known Risks / Gotchas

The implementation must validate synchronization across legacy synchronous catalog users, worker threads, and enabled awaited writes. Redis association repair cannot be treated as a PostgreSQL transaction. Evidence snapshots can double memory usage and hashes consume CPU; measure the proposed cap. Large serialized pages can exceed memory limits even with few rows. Retention can race publication and validation; share transaction/lease rules. New call observers must preserve all existing early return and guardrail paths. Shared toolkit/manager instances require request-local context and scope-qualified cache/alias identities.

Phase 0 must inspect the installed file-manager API and select supported byte-stream/stat operations; this specification deliberately does not invent external method names. Durable use of local filesystem storage requires a shared, persistent mount across pods; an ordinary pod-local temporary directory is not durable. S3 uses the already-configurable file-manager backend.

### External Dependencies

| Package | Existing declaration | Use |
|---|---|---|
| Python stdlib | `requires-python >=3.11`, core pyproject line 18 | UUID4, ContextVar, asyncio, hashlib, enums and typing. |
| pydantic | `==2.12.5`, `packages/ai-parrot/pyproject.toml:54` | New domain models/input contracts. |
| pandas | `>=2.0.0`, core pyproject line 147 | Existing DataFrame operations and snapshots. |
| pyarrow | `>=25.0`, core pyproject line 157 | Parquet/strict Arrow IPC; already core. |
| orjson | `>=3.9`, core pyproject line 173 | Canonical serialized JSON and byte accounting. |
| asyncpg | `>=0.29` in existing `graphindex-postgres` extra, core pyproject line 258; also in workspace lock | Lazy PostgreSQL task backend; verify availability at enabled-backend startup. |
| Redis / navconfig / tiktoken | Already resolved in `uv.lock`; Redis is already used by `RedisConversation`, compaction owns its optional counter | Existing hot storage/config/token-count integrations; reuse installed versions. |
| navigator-api | `>=3.2.2`, core pyproject line 104 | Existing file-manager abstraction for blob transport. |

No new library is authorized or required by this spec. qworker scheduling is a host integration, not a new core dependency. A separate task-memory extra, if desired later, requires its own dependency review; no dependency additions are hidden in module work.

### Worktree Strategy

- **Isolation**: `per-spec`.
- **Base**: `dev`; create one feature worktree during `$sdd-task`, with all task changes coordinated there.
- **Rationale**: Catalog, dispatcher, bot turn ownership, and compaction serialization have coupled contracts. Splitting them into independent feature branches risks inconsistent runtime behavior.
- **Dependency order**: M1 → M2/M3 → M4 → M5; M6 and M7 follow their prerequisite contracts; M8 durability requires M7's safe serialization; M9 verification accompanies each module and closes both deliveries.
- **Cross-feature dependencies**: Existing FEAT-525 compaction models/budget/omissions are present, so the proposal's conditional blocker is cleared. Existing FEAT-380 worker/compression and FEAT-536 full-result dispatch behavior must be preserved. No unmerged handle-only design is assumed. Reverify these shared files before implementation if `dev` advances.
- **Parallelism**: Pure reducer tests, recall selection, and documentation may be developed independently after their interfaces stabilize; shared catalog/manager/bot edits need one owner at a time. This spec-generation run does not dispatch implementation agents.

## 8. Open Questions

These preserve the proposal's unresolved OQ1–OQ3 and their defaults. They do not block specification review or initial task decomposition.

- [ ] **OQ1** Archive format on terminal deletion: JSONL to S3 vs. keep 1-row summary in `tasks`. Default: JSONL when `archive_uri` set, else delete. — Owner: Jesus Lara.
- [ ] **OQ2** Should `ExecutionPlanToolkit` runs auto-create a `TaskStep` per plan when no task is open? Proposal: no — only attribute when a task exists (`attribution=plan`). — Owner: Jesus Lara. Explicit node-to-step mapping remains required when a task does exist.
- [ ] **OQ3** `snapshot_max_bytes` default (64 MiB) pending Phase 0 measurement. — Owner: implementation owner.
- [x] Flow metadata: feature on dev, resolved with `scripts.sdd.sdd_meta.resolve_flow()`.
- [x] Existing proposal is an authorized exception to the dirty-worktree precondition; preserve its contents.
- [x] Draft status, target `next`, author Jesus Lara follow the proposal/repository convention; no release number is promised.
- [x] Compaction primitives are implemented. The dispatcher observer and deterministic Stage 2 injection are new work in this feature, not pre-existing APIs.
- [x] Review refinements: enabled-only result cap; explicit selection/lifecycle tools; scoped version lookups; both catalog entry types; additive awaited catalog API; strict worker transport; atomic metadata merging; revision-safe validation; truthful cache/retention/recovery semantics. These are specified design requirements subject to approval with this draft.

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-09-08 | Jesus Lara / Codex | Initial FEAT-538 draft from the existing proposal; verified integration contracts and resolved implementation contradictions. |
