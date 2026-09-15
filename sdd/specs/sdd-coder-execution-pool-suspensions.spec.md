---
type: feature
base_branch: dev
---

# Feature Specification: SDD coder execution pools and recent suspensions

**Feature ID**: FEAT-559
**Date**: 2026-09-16
**Author**: Codex
**Status**: review
**Target version**: Next release containing the SDD coder pool lifecycle
**Source consumable**: Confirmed discussion in this session; implementation research in `artifacts/plan_sdd_coder_execution_pool.md`.

---

## 1. Motivation & Business Requirements

### Problem Statement

The coder engine probes a roster once and keeps one assigner for the MCP
server process. A failed seat is excluded from the immediate retry of one
task, but remains eligible for subsequent chunks. There is no identifier
for the complete sdd-worker execution: `job_id` identifies a chunk.

The companion `sdd/specs/codex-dispatch-stdin-isolation.spec.md` documents
1800.310s and 1800.323s failures in QuerySource TASK-720 and TASK-721. Its
stdin repair explicitly excludes cross-task quarantine. Even with that
repair, provider outages, timeouts and failed coder deliveries can waste
the same execution budget repeatedly.

The user confirmed two requirements:

1. Each sdd-worker execution owns its own available-agent pool. A coder
   failure suspends its model for the remainder of that execution.
2. Every actual suspension is written to the shared repository SDD work
   ledger. A later execution retrieves recent suspensions and excludes
   those models temporarily, rather than paying for another known failure.

### Goals

- Explicit execution identity spanning all chunks, retries, native agents,
  reviews and cleanup for one worker invocation.
- First qualifying failure removes the model from that execution's pool.
- Preserve the configured roster; expose exclusions and reasons separately.
- Persist and recover recent suspensions before probing or dispatching a
  model in a new execution. Default cooldown: 1800 seconds, configurable.
- Prevent cached plans, aliases and retries from bypassing a suspension.
- Preserve already-running work, attempt attribution and existing review
  feedback. Fall back to the worker when no coder remains available.
- Make unavailable history and failed persistence visible; never claim
  that a model has a clean history when retrieval failed.

### Non-Goals (explicitly out of scope)

- Implementing the companion Codex stdin/process-cleanup hotfix, modifying
  its deadline, or changing provider SDKs or `clients/base.py`.
- Editing roster YAML to remove a model, global account-wide bans, or
  sharing exclusions across unrelated repositories.
- A global mutable pool shared by workers, or cancelling sibling work
  merely because its model was suspended after it started.
- Training model weights, treating platform failures as code lessons,
  replacing feedback metrics, or learning from engine lint/autofixes.
- New provider health-check integrations, autonomous unbounded retries,
  or automatic LLM calls made solely to test whether a cooldown expired.
- Automatic resumption of lost operating-system processes after MCP restart.

---

## 2. Architectural Design

### Overview

Keep configuration immutable. Introduce `ExecutionPool` instances indexed
by a caller-generated UUID `execution_id`, bound immutably to the shared
repository root, feature ID and canonical feature-worktree path.

At startup the worker creates and retains one UUID, calls
`coder_begin_execution`, and uses that ID in every subsequent orchestration
call. Repeating begin with the same ID resumes the same execution; it does
not clear suspensions. An explicit new invocation creates a new ID.

Begin reads durable suspension history FIRST, then probes only eligible
model candidates using the existing roster probe. Each execution owns its
effective seats, assigner, generation counter, cached plan, active attempt
reservations and local suspensions. Server startup must not perform a
model probe before the execution's ledger exclusions are known.

### Component Diagram

```text
Immutable roster + shared repository suspension ledger
                         |
                  begin(execution_id)
                         |
              ExecutionPool A / ExecutionPool B
                |                         |
       own plans/retries/native     own plans/retries/native
                |
        confirmed attempt failure
                |
      suspend locally + append ledger event
                |
     subsequent execution C reads recent exclusions
```

### Pool and history semantics

| Situation | Required behavior |
|---|---|
| Model fails in A | Suspend in A for its remaining lifetime; persist the event |
| B was already active when A failed | B retains its own startup snapshot; no broadcast mutation of B's pool |
| C begins after A's event is durable | Exclude that exact model while its cooldown remains active |
| Cooldown expires while A or C runs | Do not automatically re-enable a model excluded from that execution |
| D begins after expiry | Model is eligible for normal existing readiness checks; no promise of provider recovery |
| Same execution ID is resumed after expiry | Its own suspensions remain effective; expiry is only for new executions |
| Duplicate recording/repeated begin | Do not reset occurrence timestamps or extend a cooldown |
| Another repository starts a worker | No shared exclusion unless it deliberately uses the same configured ledger |

Cross-execution exclusion has a precise boundary: a suspension durably
recorded before begin's history snapshot must be applied. A call already
admitted before that event may finish. This is not a global cancellation
or synchronization service across independent MCP processes.

### Model identity

- `ModelKey = (backend, model)`, with `backend="native"` for native agents.
- Compare exact validated model IDs; seat labels are display aliases and
  must not let a suspended model re-enter under a different label.
- Explicit configured primary/fallback IDs are checked before any probe
  of those IDs. A configured fallback may be used only if it independently
  passes the same exclusion gate; never invent a fallback.
- Native model defaults to the existing explicit `haiku` identity.
- An MCP seat with an empty/unknown model ID is excluded with
  `model_identity_required`, before a paid call. Resolve it by explicit
  roster configuration, not by guessing a provider default.
- Store both configured and resolved model IDs. If the dispatcher reports
  a different resolved model on failure, suspend both the actual model and
  the configured dispatch route in that execution/history, as one incident.
  This prevents a configured alias from routing straight back to the failure.
- Do not suspend all models of a provider/backend from one model's failure.

### Failure policy

| Trigger | Execution suspension | Durable recent exclusion | Code feedback |
|---|---|---|---|
| Dispatch timeout, including wrapped TimeoutError | Yes, first occurrence | Yes | Never automatically |
| Dispatch exception/nonzero CLI exit/provider unavailable | Yes, after dispatcher invocation begins | Yes | Never automatically |
| Invalid DevelopmentOutput / exhausted unsuccessful delivery | Yes | Yes | Only reviewed code defects |
| Dirty delivery or file-fidelity violation attributable to coder | Yes | Yes | Only reviewed code defects |
| Worker confirms a critical code-review defect | Yes, explicit attempt-bound report | Yes | Existing reviewed model-lesson policy applies |
| Existing configured smoke probe fails for that model | Unavailable in new pool | Yes, probe-bound incident | No |
| Lint finding, engine formatter/autofix or residual style debt | No | No | No |
| Recoverable edit/test error within an ultimately successful attempt | No | No | Only if separately confirmed by reviewer |
| Git merge conflict, worktree creation failure, task/spec mismatch | No model suspension | No | Existing task/host failure handling |
| User cancellation, MCP shutdown, caller wait timeout | No model suspension | No | No |

Classify failures where their phase and exception are known. Do not infer
platform availability by searching arbitrary stderr or model prose. Traverse
the bounded exception cause chain to recognize `TimeoutError` wrapped by
`DispatchExecutionError`; distinguish the dispatch deadline from a
`coder_wait` polling deadline. Other dispatch failures may use the generic
`dispatch_error` reason without claiming a more specific cause.

All qualifying suspensions use the configured cooldown, including
review-critical incidents. The reason remains structured so a later policy
can tune different categories without conflating them with code feedback.

### Durable ledger plane

Add `knowledge/wiki/ledger/coder_suspensions.py`. Reuse
`LedgerService.from_root(...).log`, `LedgerLog.append/iter_events`,
`LedgerEvent(kind="insight.recorded")` and `InsightRecordedPayload`.
Use category `coder_suspension`, with versioned typed JSON in `fact`.
This parallels `coder_feedback` and `coder_review` but is a distinct plane.

No new `LedgerEventKind` or SQLite issue schema is needed. The issue reducer
does not materialize insights; replay this category explicitly. Never use
`ledger_context` to retrieve suspensions: it returns open code issues.

Each `SuspensionRecord` contains:

- `schema_version=1`, stable `suspension_id`, `execution_id`, `feature_id`;
- `task_id`, `attempt_uid`, `job_id` when an actual attempt exists; otherwise
  a distinct `probe_uid` and `source="probe"`;
- `source`: `engine|worker_review|native_report|probe`;
- `seat_label`, backend, configured/resolved IDs, `blocked_keys` (one or two);
- reason enum: `timeout|dispatch_error|invalid_output|dirty_delivery|fidelity_violation|review_critical|probe_failed`;
- aware UTC `occurred_at`, immutable `expires_at`, nonnegative observed
  `duration_s`, exception class name and bounded evidence references;
- a sanitized template-generated explanation, not a raw prompt, provider
  response, environment dump, credential or unbounded stderr transcript.

The stable ID hashes execution ID, source, attempt/probe UID and reason;
duplicate replay counts one incident. Keep the FIRST occurrence timestamp
and expiry for duplicate IDs. A distinct real failure creates a new
incident. Effective exclusion lasts until the maximum unexpired expiry
among matching incidents. Reading, restarting and inheriting an exclusion
never append a new suspension or prolong it.

Default `SuspensionPolicy.cooldown_seconds=1800`, validated range
60..86400; `history_max_tokens=1200`, range 0..4000, affects only the
human-readable summary. Selection uses all structured matching records,
even if the displayed summary is truncated. Time tests use an injected
aware UTC clock; suspend records with impossible timestamps are not trusted
as valid history. Policy changes apply to future incidents, not by rewriting
existing expiry timestamps.

Record begin/close metadata separately as category `coder_execution` to
bind the ID to its scope and roster fingerprint across restarts. Never put
an entire roster or job transcript in one ledger event. All events respect
the existing 4096-byte cap. Build compact deterministic payloads and reject
oversize evidence explicitly instead of silently dropping a suspension.

### Admission, concurrency and cache invalidation

1. Maintain an `asyncio.Condition` per execution. Under its lock, inspect
   availability, plan generation and active reservations; reserve the
   selected model before dispatch. Do not hold the lock during an LLM call.
2. Suspension changes the local state and increments `pool_generation`
   before waiting for disk I/O. No later admission in that execution can
   select that model. An already-reserved attempt is in flight, not a new
   admission, and is allowed to settle normally.
3. Persist the incident before scheduling the failed task's replacement.
   An idempotent repeat returns the original suspension receipt.
4. Store plans per execution with `pool_generation`. `run_chunk` rejects a
   stale plan as `plan_stale` before creating a job or worktree. The worker
   replans; no attempt is consumed for that rejection.
5. Check the pool again inside each attempt admission and retry. If a
   previously accepted queued task loses its seat before admission, return
   `TaskResult.outcome="not_dispatched"`, with a reason and no fake attempt.
   Replan that task or use the established worker fallback.
6. Retries exclude all suspended models and previous models tried by that
   task. Preserve the existing limit of two MCP attempts before worker
   implementation; skipped admissions do not consume an attempt.
7. At most one active attempt per ModelKey per execution. If a healthy
   retry seat is busy, wait on the condition until it settles or the pool
   becomes exhausted/closed; wake on completion, suspension and cancellation.
   Native reservations are not eligible for an automatic MCP retry. Preserve
   the existing dispatch deadlines; do not add an unbounded provider call.

Each pool has its own assigner rotation. Sharing the immutable roster or a
read-only history service is allowed; sharing effective seats, exclusion
sets, plan caches or rotation state is not.

### Execution lifecycle, ownership and recovery

- State: `active|exhausted|recovery_required|closed`. Exhausted means no
  eligible coder remains, not that all tasks are complete. `fallback_required`
  and a structured reason tell the worker to execute its sequential loop.
- Begin is idempotent for a matching UUID/scope/roster fingerprint. A mismatched
  feature/worktree is `execution_scope_mismatch`; a changed fingerprint on
  resume is `execution_config_mismatch`. A closed ID cannot start fresh work.
- Only one active execution may own a canonical feature worktree; a second
  ID receives `execution_in_progress`. Different worktrees/features can use
  independent pools on the same server. This restriction protects SDD state
  and Git merges, not the model roster.
- Namespace managers, latest attempts, native inflight tracking, plan caches,
  job ownership and feedback/review attribution by execution. Never let
  `cleanup(A)` enumerate/delete managers owned by B.
- Use worker IDs `TASK-N.a<attempt>.<execution_uuid_hex>` when calling the
  existing SubWorktreeManager. Its dot-to-dash conversion produces unique
  branches/paths across successive executions. Centralize derived names;
  remove duplicated hard-coded branch construction from dispatch/merge paths.
  Recognize legacy orphan names for reporting/adoption; never auto-delete them.
- Add `execution_id` to job, attempt, native prep, plan, outcome and usage
  records. `run_id=job_id` remains unchanged at the dispatcher boundary.
- Journal per-execution state under
  `<feature-worktree>/.sdd-coder/executions/<uuid>.json`, using atomic replace
  off the event loop. Include attempt ownership, native reservations and
  outstanding job IDs; preserve existing job journals.
- On MCP restart, explicit begin with the same UUID replays its own
  suspensions regardless of expiry and restores the startup exclusions.
  A restored running/prepared attempt requires reconciliation from existing
  worktree/job evidence; mark `recovery_required` and admit no replacement
  until the worker resolves it. Do not assume a lost native child exited.
- End refuses while known attempts/reservations are in flight, records a
  durable close after they settle, and releases the worktree ownership.
  End does not remove branches or clear recent suspension history.
- Native Agent failures are reported by the worker through an attempt-bound
  suspension tool. Reporting a failure/suspension alone does not release a
  live native reservation or authorize deleting its worktree. Completion or
  confirmed termination must be established before cleanup/end.

### Persistence failure behavior

- At begin, unreadable/invalid suspension history yields an exhausted pool
  with `fallback_required=true`, reason `suspension_history_unavailable`.
  Do not probe providers under an invented empty history.
- If suspension persistence fails after a delivery, keep it suspended locally,
  mark the execution `persistence_degraded`, expose `persisted=false`, and
  require worker fallback instead of further coder dispatch. Retry persistence
  idempotently at the next status/end operation; never claim durable success
  until append succeeds. Already-running work may settle.
- Invalid/partial matching ledger records must be surfaced as degraded
  history, not silently ignored as healthy. The new store must validate its
  own records and detect truncated lines; the existing LedgerLog reader's
  warning-and-skip behavior alone is insufficient for admission decisions.
- No design can recover an event that could not be durably written and was
  then lost in a machine failure. Report that limit explicitly; do not fall
  back to code-feedback records as fabricated operational history.

### Integration Points

| Component | Change |
|---|---|
| SddCoderEngine.open | Initialization only; move availability probing into execution begin |
| RosterProbe / available_seats | Gate primary and configured fallback before probing; produce execution-local results |
| ChunkAssigner | Operate on an execution's eligible seats; preserve distinct-seat rotation |
| plan / run_chunk / _run_attempt / _run_task | Carry execution ownership, invalidate stale plans, gate admissions and retries |
| prepare_native / merge / cleanup | Carry native identity, explicit reports and execution-scoped ownership |
| JobTable / existing journals / telemetry | Carry execution ID and scoped running-task queries |
| coder_feedback / coder_review | Continue reviewed-code lessons and metrics; add execution attribution, no platform lessons |
| Worker prompts and MCP toolkit | Explicit begin/use/end, suspension reports, visible exclusions and fallback |

### Data Models

All new data structures are Pydantic v2 models with `extra="forbid"`.
Runtime locks/conditions belong to the runtime pool, not serialized models.

| Model | Required contract |
|---|---|
| ModelKey | frozen backend/model strings, exact matching, nonempty model |
| SuspensionPolicy | cooldown_seconds=1800, history_max_tokens=1200 with bounds above |
| SuspensionRecord | Versioned incident and attribution fields specified above |
| PoolSeatView | configured seat + effective ModelKey + available/busy/suspended/probe_unavailable + reason/IDs/expiry |
| ExecutionPoolView | UUID, scope, status, generation, seats, fallback_required/reason, persistence status |
| SuspensionReceipt | suspension_id, execution_id, blocked_keys, persisted, expires_at, pool_generation |
| SuspendModelArgs | execution_id, attempt_uid, reason, evidence_ref; target model resolved by engine, never caller-invented |
| ExecutionSnapshot | scope/fingerprint, admitted attempts, reservations, local/inherited exclusions, status/generation |

### New Public Interfaces

MCP tool surface (all return the existing `CoderResult` envelope):

```text
coder_begin_execution(feature: str, worktree: str, execution_id: str)
coder_end_execution(execution_id: str)
coder_suspend_model(execution_id: str, attempt_uid: str, reason: str, evidence_ref: str)
```

Add required `execution_id` to `coder_plan`, `coder_run_chunk`,
`coder_prepare_native`, `coder_merge`, `coder_cleanup`, `coder_record_feedback`
and `coder_record_review`. Validate existing feature/worktree arguments
against that binding. `coder_wait/status(job_id)` derive ownership from the
job and include its pool view. The repository-wide feedback report stays
read-only and does not create/resume a pool.

Missing execution IDs fail explicitly (`execution_required`) before any
model call; do not create an implicit global or per-chunk execution.
Update all in-scope callers and schema tests together. This is a deliberate
versioned MCP protocol change requiring worker/server upgrades together.

New error codes: `execution_required`, `execution_not_found`,
`execution_scope_mismatch`, `execution_config_mismatch`, `execution_closed`,
`execution_in_progress`, `execution_busy`, `execution_recovery_required`,
`plan_stale`, `model_suspended`, `suspension_history_unavailable`,
`suspension_persistence_failed`. Expected pool exhaustion is an OK result
with `fallback_required`, not an unclassified internal error.

---

## 3. Module Breakdown

#### Delegation-eligible modules

| Module | Eligible? | Decided patterns / exact contracts | Why not |
|---|---|---|---|
| M1: Suspension store and models | yes | Insight categories, bounded payload, identity, deduplication, expiry, strict replay | — |
| M2: Execution pool runtime | yes | UUID/scope binding, generation, condition, ownership, lifecycle, fallback | — |
| M3: Engine and roster wiring | yes | Admission boundary, failure matrix, primary/fallback gates, attempt limits | — |
| M4: MCP and worker lifecycle | yes | Three new tools, required execution IDs, native reporting, prompt twins | — |
| M5: Regression tests and documentation | yes | Explicit scenarios and assertions in §4–5 | — |

Eligibility applies after this spec is approved and implementation packets
resolve the exact current anchors. It does not delegate architecture changes.

### M1: Durable suspension plane

- **Create** `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/coder_suspensions.py`.
- **Responsibility**: Typed records, canonical identity/IDs, strict replay,
  UTC expiry, execution lifecycle metadata and bounded history rendering.
- **Depends on**: Existing ledger log/service and Pydantic; no schema migration.
- **Interface skeleton** (new declarations, not existing APIs):

```python
class CoderSuspensionStore:
    """Shared-repository operational history, separate from code feedback."""
    @classmethod
    def from_root(cls, root: Path) -> CoderSuspensionStore:
        """Resolve the same canonical ledger as LedgerService."""
    async def record(self, suspension: SuspensionRecord) -> SuspensionReceipt:
        """Append one durable bounded incident; preserve idempotent identity."""
    async def recent(self, keys: list[ModelKey], now: datetime) -> list[SuspensionRecord]:
        """Return all matching unexpired incidents or raise history unavailable."""
    async def for_execution(self, execution_id: str) -> list[SuspensionRecord]:
        """Return that execution's incidents regardless of cooldown expiry."""
```

### M2: Execution-owned pool and lifecycle

- **Create** `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/pool.py`.
- **Modify** `sdd_coder/models.py`, `sdd_coder/jobs.py` in the same source root.
- **Responsibility**: ExecutionPool runtime, scoped caches/reservations,
  generation checks, status/snapshot models and job ownership filtering.
- **Depends on**: M1, existing RosterSeat/PlannedTask/ChunkAssigner.
- **Interfaces**: `ExecutionPool.view() -> ExecutionPoolView`,
  `async admit(task_id: str, key: ModelKey) -> str` returns the reservation
  UID; `async release(attempt_uid: str) -> None` wakes waiters;
  `async suspend(record: SuspensionRecord) -> SuspensionReceipt` removes
  all aliases before persistence. Membership and generation changes are
  atomic under the execution's condition.

### M3: Engine dispatch, retry, probe and recovery integration

- **Modify** `sdd_coder/engine.py`, `sdd_coder/roster.py`,
  `sdd_coder/telemetry.py` in the core source root.
- **Modify** `knowledge/wiki/ledger/coder_feedback.py` and
  `knowledge/wiki/ledger/coder_reviews.py` only for additive execution
  attribution; retain legacy-record read compatibility.
- **Responsibility**: Move cached process-wide selection into pools, qualify
  failures at source, persist before retry, safe native/worktree ownership,
  execution snapshots and exposure/usage attribution.
- **Depends on**: M1–M2 and existing feedback/review work noted in §6.
- **Interfaces**: Engine methods mirror the new MCP lifecycle names without
  the `coder_` prefix. Extend existing orchestration methods with an explicit
  execution ID. Extend `RosterProbe.probe` with an exclusion set used by
  both primary and fallback checks. Preserve the dispatcher protocol.

### M4: MCP surface and worker instructions

- **Modify** `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/toolkit.py`.
- **Modify** `.claude/agents/sdd-worker.md` and
  `packages/ai-parrot/src/parrot/flows/dev_loop/_subagent_data/sdd-worker.md`.
- **Responsibility**: New input schemas/tool registration; worker generates
  one UUID, begins before plan/probes, propagates identity, reports native
  failure/critical review, displays recent exclusions, and ends once work
  settles. `plan_stale` means replan, `not_dispatched` remains pending;
  exhausted pools enter the existing sequential worker loop. Never treat
  `chunks=[]` with pending tasks as completion.
- **Depends on**: M1–M3. Preserve the previous per-delivery code feedback and
  review measurement instructions. Suspension evidence is shown to the
  worker, not injected as a code lesson into another model's prompt.

### M5: Tests and operational documentation

- **Create** package tests under `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/`:
  `test_pool.py`, `test_suspensions.py`, `test_execution_pool_integration.py`.
- **Modify** existing tests in that directory:
  `conftest.py`, `test_engine_plan_merge.py`, `test_engine_dispatch.py`,
  `test_integration_chunk.py`, `test_roster.py`, `test_jobs.py`,
  `test_models.py`, `test_toolkit.py`, `test_mcp_local.py`,
  `test_telemetry.py`, `test_feedback.py` to pass explicit execution IDs
  and assert execution-owned contracts.
- **Modify** `docs/dev_loop/sdd-coder-orchestrator.md`.
- **Depends on**: M1–M4. Do not modify the standalone Codex dispatcher tests
  owned by the companion stdin hotfix.

---

## 4. Test Specification

### Unit Tests

| Test | Module | Required assertion |
|---|---|---|
| `test_pool_private_state` | M2 | Two execution instances share no mutable seats/rotation/exclusions |
| `test_suspend_first_failure` | M2 | One qualifying incident excludes the model and every label alias |
| `test_expiry_is_new_execution_only` | M1–M2 | Exact UTC boundary eligible for a new ID; original ID stays suspended |
| `test_duplicate_incident_preserves_expiry` | M1 | Repeated append/replay cannot increment incidents or extend cooldown |
| `test_latest_real_incident_extends_exclusion` | M1 | Distinct failures use maximum matching expiry |
| `test_summary_budget_does_not_limit_exclusion` | M1 | All structured exclusions apply even with a zero-token summary |
| `test_identity_and_fallback_gate` | M3 | Configured/resolved aliases and fallback IDs cannot bypass checks |
| `test_empty_model_is_not_probed` | M3 | Unknown model excluded before dispatcher/probe invocation |
| `test_timeout_cause_classification` | M3 | Wrapped TimeoutError is operational timeout; poll timeout is not |
| `test_non_model_failures_do_not_suspend` | M3 | Cancellation, Git errors, merge conflicts and lint do not enter history |
| `test_stale_plan_admits_nothing` | M2–M3 | Stale generation rejects before worktree/job creation |
| `test_retry_uses_only_healthy_free_model` | M3 | Failed model never retries; active healthy seat cannot be double-booked |
| `test_suspension_wakes_retry_waiter` | M2 | Pool exhaustion ends waiting and requests worker fallback |
| `test_native_report_is_attempt_bound` | M3–M4 | Unknown/mismatched attempt cannot suspend arbitrary models |
| `test_suspension_does_not_settle_native` | M3 | Suspended live native reservation still protects cleanup/end |
| `test_persistence_failure_is_explicit` | M1–M3 | Local exclusion holds; persisted=false; fallback; idempotent flush |
| `test_corrupt_history_is_not_empty_history` | M1 | Malformed/truncated history prevents speculative startup calls |
| `test_event_payload_and_redaction_bounds` | M1 | <=4096 bytes; no raw provider output/secrets; invalid payload rejected |
| `test_missing_execution_rejected` | M4 | Old dispatch calls fail before any model work; status/report remain scoped |

### Integration Tests

| Test | Scenario |
|---|---|
| `test_timeout_then_next_chunk` | A fake Codex attempt times out; later chunks and retries invoke it zero times |
| `test_new_execution_uses_durable_history` | Fresh engine/store, same repository: suspended model is excluded before smoke probe |
| `test_new_execution_after_expiry` | Advance fake clock past expiry: fresh execution can use model; old execution cannot |
| `test_overlapping_workers_isolated` | A fails while B is already active: B state remains unchanged; C begun after append inherits exclusion |
| `test_all_seats_exhausted` | No divide-by-zero/empty ChunkAssigner; pending tasks survive; worker fallback is explicit |
| `test_restart_same_execution` | Reconstruct engine with original UUID: suspension remains after TTL; inflight evidence requires reconciliation |
| `test_close_then_new_execution` | Reusing closed UUID fails; new UUID recovers recent history without a new suspension event |
| `test_cleanup_cannot_cross_execution` | Separate worktrees on one engine; A cleanup preserves B's branches, native reservations and jobs |
| `test_model_aliases_and_parallel_admission` | Multiple labels for one model and raced suspension cannot admit new work after local transition |
| `test_review_and_feedback_coexist` | Critical reviewed code defect produces suspension plus valid code lesson; timeout produces suspension only |
| `test_legacy_history_and_telemetry` | Existing feedback/review/events still load; new rows carry execution ID; no fabricated attempts for skips |
| `test_mcp_and_prompt_twins` | Actual registered tool schemas and both worker prompts implement the same lifecycle/fallback |

### Test Data / Fixtures

Use `git_sandbox_feature`, fake dispatchers, isolated ledger roots and a
fake aware UTC clock. Extend fixtures to begin an execution explicitly.
Use asyncio events/barriers to control races, not sleeps. Inject an immediate
TimeoutError; never wait 1800 seconds in a test. No live provider calls,
network, account credentials or QuerySource writes are required.

---

## 5. Acceptance Criteria

- [ ] AC-1: One worker UUID spans all its chunks/native/retry/review operations; no implicit global execution exists.
- [ ] AC-2: Every qualifying first failure prevents further model admission in that execution, including cached plans/retries/aliases.
- [ ] AC-3: Suspension history is durably recorded with validated attribution, reason, timestamp and fixed expiry; no code-feedback pollution.
- [ ] AC-4: A new execution excludes all unexpired matching records BEFORE any primary/fallback smoke probe or dispatcher call.
- [ ] AC-5: Cooldown expiry only affects new executions; duplicate begin/record/replay does not refresh expiry or clear local bans.
- [ ] AC-6: Active pools remain independent; another execution's cleanup/cache/model rotation cannot mutate them.
- [ ] AC-7: No native or MCP child is cancelled or deleted merely because its model was suspended; reservations settle explicitly.
- [ ] AC-8: Exhausted/unavailable-history pools trigger worker fallback while pending tasks remain pending; no infinite replanning.
- [ ] AC-9: Ledger write/read failures are explicit and do not silently admit a known suspended model or assert clean history.
- [ ] AC-10: Restart/resume restores the same UUID's exclusions and requires reconciliation of uncertain inflight attempts.
- [ ] AC-11: Execution identity is present in plans/jobs/attempts/usage/outcomes/reviews, without changing dispatcher run_id semantics.
- [ ] AC-12: Summaries include excluded model, incident ID, source task/execution, reason and remaining cooldown; truncation cannot affect selection.
- [ ] AC-13: The fake timeout integration test proves zero subsequent invocations of that model within the execution and within cooldown on restart.
- [ ] AC-14: Offline package tests pass; Black, scoped Ruff and git diff --check pass; logs saved under artifacts/logs/.
- [ ] AC-15: Both worker prompt copies, MCP schema tests and documentation reflect explicit begin/use/end and fallback semantics.

---

## 6. Codebase Contract

### Research provenance and prerequisites

Anchors below were inspected on 2026-09-16 in the shared workspace at
initial HEAD `445c05773115a75c05c640ce8ddbc68662fccbce` **plus local changes**;
final anchor verification used HEAD `8270c39e0ef18cedce5f85af943fb83d0f567a91`
plus the remaining working changes. The feedback/review implementation
from this session is absent from clean origin/dev snapshot `99f6f7b92`
used for ID allocation. Land or explicitly
integrate that work before implementation; do not invent those modules if
an isolated feature worktree lacks them. Reverify anchors when creating tasks.

Other concurrent local changes affect roster probing, lint, scheduling and
telemetry. Preserve them and rebase the contracts, rather than treating the
current line numbers as frozen code. The stdin hotfix is complementary and
not an implementation dependency; this feature can classify wrapped timeout
errors through the existing exception chain.

### Verified Imports

Paths below are relative to `packages/ai-parrot/src/` unless stated otherwise.

```python
from parrot.flows.dev_loop.sdd_coder.models import RosterConfig, RosterSeat, AttemptRecord, CoderJob
# parrot/flows/dev_loop/sdd_coder/models.py:45,116,181,251
from parrot.flows.dev_loop.sdd_coder.roster import RosterProbe, ChunkAssigner, available_seats
# parrot/flows/dev_loop/sdd_coder/roster.py:21,126,115
from parrot.flows.dev_loop.sdd_coder.engine import SddCoderEngine, CoderFailure
# parrot/flows/dev_loop/sdd_coder/engine.py:291,78
from parrot.flows.dev_loop.sdd_coder.jobs import JobTable
# parrot/flows/dev_loop/sdd_coder/jobs.py:17
from parrot.flows.dev_loop.dispatchers._shared import DispatchExecutionError, DispatchOutputValidationError
# parrot/flows/dev_loop/dispatchers/_shared.py:418,427
from parrot.flows.dev_loop.worktree_manager import SubWorktreeManager
# parrot/flows/dev_loop/worktree_manager.py:75
from parrot.knowledge.wiki.ledger.service import LedgerService
# parrot/knowledge/wiki/ledger/service.py:96
from parrot.knowledge.wiki.ledger.log import LedgerLog
# parrot/knowledge/wiki/ledger/log.py:10
from parrot.knowledge.wiki.ledger.events import LedgerEvent, InsightRecordedPayload
# parrot/knowledge/wiki/ledger/events.py:83,55
from parrot.knowledge.wiki.ledger.coder_feedback import CoderFeedbackStore
# LOCAL prerequisite: parrot/knowledge/wiki/ledger/coder_feedback.py:78
from parrot.knowledge.wiki.ledger.coder_reviews import CoderReviewStore
# LOCAL prerequisite: parrot/knowledge/wiki/ledger/coder_reviews.py:68
```

### Existing Class Signatures

| Symbol | Current signature / behavior | Verified anchor |
|---|---|---|
| SddCoderEngine.open | async open() -> None; probes once and caches self.seats/_assigner | engine.py:367 |
| SddCoderEngine.plan | async plan(feature, worktree) -> CoderPlan; cache keyed only by feature_id | engine.py:457 |
| SddCoderEngine._run_task | async _run_task(ctx, task, seat, *, job_id) -> TaskResult; retry excludes only failed label | engine.py:1057 |
| SddCoderEngine.prepare_native | async prepare_native(feature, worktree, task_id) -> NativePrep | engine.py:512 |
| SddCoderEngine.cleanup | async cleanup(feature, worktree, keep_conflicted=True) -> CleanupReport; currently enumerates all managers | engine.py:777 |
| SddCoderEngine._journal | async _journal(worktree, job) -> None; .sdd-coder/jobs/job_id.json | engine.py:823 |
| RosterProbe.probe | async probe(roster: RosterConfig) -> List[SeatProbeResult] | roster.py:35 |
| RosterProbe._probe_one | async _probe_one(seat); primary and fallback smoke calls handled here | roster.py:50 |
| ChunkAssigner.retry_seat | retry_seat(failed_label: str, exclude: Set[str]) -> Optional[RosterSeat] | roster.py:169 |
| JobTable.create | create(feature_id, task_ids, runner) -> CoderJob; chunk UUID | jobs.py:25 |
| JobTable.running_task_ids | running_task_ids() -> set[str]; currently unscoped | jobs.py:59 |
| SubWorktreeManager.create | async create(worker_id: str) -> str; substitutes dots with dashes | worktree_manager.py:146 |
| LedgerService.from_root | from_root(root: Path \| None = None) -> LedgerService; shared checkout resolution | ledger/service.py:117 |
| LedgerLog.append | append(event: LedgerEvent) -> tuple[str, int]; fsync, <=4096 bytes | ledger/log.py:21 |
| LedgerLog.iter_events | iter_events(from_offset=0); warns and skips malformed lines | ledger/log.py:83 |
| CoderFeedbackStore.context | async context(backend, model, files, max_tokens=1800, max_age_days=90) -> str | ledger/coder_feedback.py:127 |
| CoderReviewStore.report | async report() -> CoderReviewReport | ledger/coder_reviews.py:130 |

### Integration Points

| New component | Connects to | Via | Verified at |
|---|---|---|---|
| Suspension store | LedgerService.log | insight.recorded category + strict replay | ledger/events.py:17; ledger/index.py:119 |
| ExecutionPool | RosterProbe/ChunkAssigner | execution-local eligible roster, gate before fallback smoke | roster.py:35,50,126 |
| Failure classifier | Dispatcher errors | typed cause chain, no stderr pattern matching | dispatchers/codex.py:168–184; _shared.py:418 |
| Pool reporting | SddCoderToolkit | arg_models validation, CoderResult serialization | sdd_coder/toolkit.py:43,81,92,126 |
| Per-execution telemetry | AttemptUsageRow/OutcomeRow | additive execution_id and existing sinks | sdd_coder/telemetry.py:40,76,255,259 |
| Worker lifecycle | Claude + packaged worker prompts | new tool allowlist, begin/end, fallback | .claude/agents/sdd-worker.md:217,267 |

### Does NOT Exist (Anti-Hallucination)

- No `execution_id` field or begin/end lifecycle in current sdd_coder models.
- No `ExecutionPool`, `CoderSuspensionStore`, `coder_suspend_model` or recent-suspension API.
- No process-global failure set may be repurposed as this execution pool.
- No `LedgerEventKind="model.suspended"`; adding that string alone would be invalid.
- Existing `ledger_context` does not query insight categories or closed code lessons.
- Existing `CoderFeedback` is a reviewed-code contract; timeout/platform errors do not belong in it.
- No automatic native Agent status polling tool exists in the worker instructions.
- Current job journals are write-only snapshots, not an implemented crash-resume service.

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- Python, Pydantic v2, async-first; use the existing toolkit and ledger.
- Filesystem replay/snapshots run off the event loop; all locks are scoped
  to one execution. No sleeps for polling, and no new provider SDK calls.
- Keep the feature separate from the Codex hotfix and engine lint changes.
- Existing code feedback is keyed by backend/model; additive execution
  attribution must retain readability of earlier events and their IDs.
- Check ledger state on begin; keep the execution snapshot immutable with
  respect to external suspensions after begin. Own incidents still update it.
- A repeated task attempt counter must not collide with a previous execution's
  branch, journal or review record; use the execution UUID and attempt UID.
- Do not shorten an existing suspension by changing policy or replaying an
  older event; do not silently extend it on reads.

### Known Risks / Gotchas

- A 30-minute cooldown cannot fix a persistent outage. It bounds repeated
  attempts across starts; after expiry a new failure establishes a new window.
- An already-active independent execution can still incur its own first
  failure. Avoiding that requires global coordination, outside this design.
- The current configured/resolved-model mismatch must be recorded explicitly;
  silently persisting only a seat nickname would make later filtering ineffective.
- Process-global auto_open currently probes too early. Moving only `plan()`
  filtering would still incur unwanted probe cost and is not sufficient.
- Dirty worktree failures must be attributed to the coder's actual delivery,
  not new engine journal files or sibling merges.
- Cached plans and a selected-but-not-admitted coroutine are separate races;
  both require the checks in §2.
- Live provider calls and native process status cannot be reconstructed from
  a model's text summary. Preserve uncertainty and require reconciliation.

### External Dependencies

No new dependencies. Pydantic is already declared in
`packages/ai-parrot/pyproject.toml:53`; asyncio, datetime, hashlib, json,
pathlib and uuid are standard library. Reuse the existing ledger's I/O
and configuration rather than creating a second database backend.

### Worktree Strategy

Isolation: **per-spec**. After approval/decomposition, use
`feat-FEAT-559-sdd-coder-execution-pool-suspensions` based on `origin/dev`
through the standard SDD worktree provisioning rule.

Implement M1 → M2 → M3 → M4 → M5. M3 owns engine/roster/telemetry integration;
M2 owns models/jobs/pool. Do not run overlapping edits to these modules in
parallel. Coordinate the local feedback, lint, roster and scheduling work
before decomposing tasks. Their final base contracts must exist in the
feature worktree; this spec does not authorize discarding those changes.

---

## 8. Open Questions

- [x] Scope of active availability — user confirmed a pool per sdd-worker execution, not global server state.
- [x] First failure policy — user confirmed timeout/failed attempt and explicit critical review suspend for that execution.
- [x] Cross-execution protection — user requested durable recent suspension history and exclusion in new executions.
- [x] Code feedback separation — preserve confirmed review lessons; do not turn lint/platform errors into model code lessons.
- [x] Cooldown mechanism — configurable expiry; 1800-second default is the author's initial assumption after an optional preference question; not an explicit user-selected duration.
- [x] Flow metadata — no explicit type flags; resolve_flow() returned feature/dev. This spec adds an orchestrator lifecycle and ledger plane.
- [x] Same execution after restart — restore bans; reconcile uncertain children before dispatch, never silently generate another UUID.
- [x] Independence from stdin repair — retained; each addresses a different failure boundary.

No unresolved architecture blocker. The cooldown default and the proposed
MCP protocol change remain reviewable policy choices before approval.

---

## 9. Design Research Cross-Check

Status: **skipped** — source is the confirmed direct conversation, not an
accepted exploration document. No independent LLM review or paid model probe
was run. The following are author cross-checks, not reviewer endorsements.

| # | Check | Disposition | Reason | Landed in |
|---|---|---|---|---|
| S1 | Distinguish chunk job from worker execution | CONFIRM | job_id resets each chunk | §2 lifecycle |
| S2 | Shared history vs global mutable pool | CONFIRM | User requests both privacy and recent exclusions | §2 semantics |
| S3 | Filter before auto_open smoke probing | CONFIRM | Startup probing currently precedes plan | §2 admission, M3 |
| S4 | Stale plans, aliases, concurrent retries | CONFIRM | Filtering only next plan leaves bypass paths | §2 admission, §4 |
| S5 | Persist code lessons for platform timeouts | REJECT | Violates previously confirmed feedback-source policy | §1 non-goals |
| S6 | Expiry automatically revives current pool | REJECT | Violates suspension for the rest of that execution | §2 semantics |

Summary: 4 author checks confirmed, 2 rejected, 0 escalated. Independent
review remains an optional approval-stage activity.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-09-16 | Codex | Initial specification from the confirmed execution-pool and recent-suspension requirements |
