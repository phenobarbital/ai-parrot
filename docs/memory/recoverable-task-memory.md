# Recoverable Task Memory (FEAT-538)

Task memory gives an agent a durable, evidence-bound record of what it is
doing, so that losing conversational context does not mean losing the
work. It is **opt-in and off by default**: with `task_memory` unset,
`WorkingMemoryToolkit` publishes exactly the tool set it always did and
persists exactly the history it always did.

The problem it solves is narrow and specific. When earlier turns are
compacted out of context, an agent that has already loaded, cleaned and
verified a dataset has no way to know that — so it does it again. Task
memory records the plan, the decisions and the *evidence* for each
finished step, so recovery resumes at the next unfinished step instead of
starting over.

---

## 1. Two deliveries, and what each actually guarantees

| | Delivery A | Delivery B |
|---|---|---|
| Storage | in-process (dicts) | PostgreSQL + blob store |
| Survives context loss in a live process | yes | yes |
| Survives a process restart | **no** | yes |
| Survives a pod moving | **no** | yes |

**Delivery A is NOT durable.** It is in-process continuity only. A fresh
store loses the task, and the test suite asserts exactly that
(`test_primary_continuity_is_in_process_only_not_durable`) so that no
green run can be misread as a durability claim. Do not deploy A and tell
operators their work survives a restart, because it does not.

Delivery B adds PostgreSQL, durable payloads, crash reconciliation,
migrations, retention scheduling and Stage 2 recall injection.

---

## 2. Enabling it

Task memory is configured on the toolkit, and the bot adopts whatever the
toolkit holds.

```python
from parrot.tools.working_memory import TaskMemory, WorkingMemoryToolkit
from parrot.tools.working_memory.task_memory.artifacts import InMemoryArtifactStore
from parrot.tools.working_memory.task_memory.models import TaskScope
from parrot.tools.working_memory.task_memory.store.memory import InMemoryTaskMemoryStore

scope = TaskScope(chatbot_id="my-agent", user_id="u-1", session_id="s-1")
task_memory = TaskMemory(InMemoryTaskMemoryStore(), InMemoryArtifactStore(), scope)
toolkit = WorkingMemoryToolkit(task_memory=task_memory)
```

For Delivery B, let the runtime build and connect the backends. It builds
**one** task store and **one** artifact store over it, so the toolkit,
the observer and the plan factory all share a backend and a transaction
coordinator:

```python
from parrot.tools.working_memory import WorkingMemoryToolkit
from parrot.tools.working_memory.task_memory.config import TaskMemoryConfig, TaskMemoryRuntime

config = TaskMemoryConfig(
    enabled=True,
    durable=True,
    dsn="postgresql://user:pass@host:5432/parrot",
)
runtime = TaskMemoryRuntime(config, file_manager=my_file_manager)
await runtime.start()
toolkit = WorkingMemoryToolkit.from_runtime(runtime, scope)
```

`BasicAgent` starts and stops a runtime for you if you set
`agent.task_memory_runtime` before `configure()`.

**There is no silent fallback.** `durable=True` without a `dsn` is
refused at construction, and a missing blob backend, an unreachable
database or an un-applied migration each fail *startup* with a message
naming what is absent. Degrading to an in-memory dict would be the worst
available outcome: the deployment looks healthy right up until the
restart it was supposed to survive.

### Configuration

Every setting can come from `TaskMemoryConfig(...)` directly or from the
environment via `TaskMemoryConfig.from_env()`. Environment names are the
field names prefixed with `TASK_MEMORY_`:

| Variable | Default | Meaning |
|---|---|---|
| `TASK_MEMORY_ENABLED` | `false` | Master switch. |
| `TASK_MEMORY_DURABLE` | `false` | Requires a DSN. |
| `TASK_MEMORY_BEST_EFFORT_TRACKING` | `false` | Opt in to running untracked when the journal is unavailable, reporting `tracking_degraded`. Off means fail closed. |
| `TASK_MEMORY_SNAPSHOT_MAX_BYTES` | 64 MiB | Above this, a payload is persisted to a blob rather than snapshotted in RAM. |
| `TASK_MEMORY_MEMORY_CACHE_MAX_BYTES` | 512 MiB | In-memory artifact cache ceiling. |
| `TASK_MEMORY_MAX_REHYDRATE_BYTES` | 2 000 000 | Hard ceiling on a raw read. A caller may lower it, never raise it; `0` means never rehydrate. |
| `TASK_MEMORY_RAW_PAGE_LIMIT_DEFAULT` / `_MAX` | 100 / 1 000 | Tabular paging. |
| `TASK_MEMORY_RECALL_MAX_TOKENS` | 2 500 | Recall budget. |
| `TASK_MEMORY_RECALL_CACHE_TTL` | 600 s | Recall cache lifetime. |
| `TASK_MEMORY_LEASE_TTL` | 30 s | Append-lease TTL. |
| `TASK_MEMORY_CONTEXT_TTL` | 86 400 s | Association key lifetime. |
| `TASK_MEMORY_INACTIVITY_PAUSE_DAYS` | 7 | Auto-pause threshold. |
| `TASK_MEMORY_ABANDONED_CANCEL_DAYS` | 30 | Auto-cancel threshold; must exceed the pause threshold. |
| `TASK_MEMORY_TERMINAL_RETENTION_DAYS` | 90 | Archive/delete threshold for terminal tasks. |
| `TASK_MEMORY_ORPHAN_BLOB_GRACE_HOURS` | 1 | Grace before an unreferenced blob may be swept. |
| `TASK_MEMORY_JOURNAL_SOFT_LIMIT` / `_HARD_LIMIT` | 50 000 / 100 000 | Journal pressure thresholds. |
| `TASK_MEMORY_JOURNAL_RESERVED_EVENTS` | 1 000 | Reserved headroom for recovery events. |
| `TASK_MEMORY_MAX_OPEN_TASKS_PER_SCOPE` | 100 | Bound on simultaneously open tasks. |
| `TASK_MEMORY_ARCHIVE_URI` | unset | Archive destination. Requires an `archive=` writer on the runtime. |
| `TASK_MEMORY_EXTRA_REDACTED_KEYS` | empty | Additional key names to redact from journalled payloads. |

---

## 3. The ten tools

All ten appear **only** when task memory is enabled. When it is not, they
are added to `exclude_tools` and the published tool set is unchanged.

| Tool | Arguments | Returns |
|---|---|---|
| `wm_begin_task` | `goal`, `constraints=[]`, `steps=[]`, `plan_complete=False` | Task and step ids, revision, compact state. Selects the new task. |
| `wm_update_plan` | `task_id`, `expected_revision`, `changes`, `reason` | New revision, or a typed `revision_conflict` carrying current state. |
| `wm_update_step` | `task_id`, `step_id`, `expected_revision`, `status`, `evidence_refs=[]`, `note` | The accepted transition, or a typed validation failure. |
| `wm_record_decision` | `task_id`, `text`, `reason`, `affected_step_ids=[]` | Decision id and revision. |
| `wm_set_resume_hint` | `task_id`, `next_action`, `step_id=None` | The saved hint. |
| `wm_recall_task` | `task_id=None`, `max_tokens=2500`, `recent_calls_limit=8` | A budgeted snapshot with truncation accounting. |
| `wm_list_task_events` | `task_id`, `after_seq=0`, `limit=50` | Ordered events and the next sequence. |
| `wm_list_task_artifacts` | `task_id`, `limit=50`, `cursor=None` | Version descriptors and the next cursor. |
| `wm_select_task` | `task_id` | The validated selection. |
| `wm_update_task` | `task_id`, `expected_revision`, `status`, `reason=None` | Pause / resume / block / fail / cancel / complete. |

Failures come back as typed data rather than exceptions — `error` is a
discriminator the model can branch on (`revision_conflict`,
`completion_refused`, `evidence_mutated`, `bare_alias`,
`needs_task_selection`, `budget_too_small`, …). A model acts on a
structured answer far better than on a traceback.

### Explicit task selection

An omitted `task_id` resolves **only** from the authoritative selected
association. With several tasks open and none selected, the answer is
`needs_task_selection` plus a bounded page of `{task_id, goal, status,
updated_at}` to choose from. Never a similarity guess.

Reads never select. `wm_recall_task`, `wm_list_task_events` and
`wm_list_task_artifacts` append nothing and change no association —
selecting as a side effect of reading would silently change what every
later command means. `wm_select_task` is the explicit repair when the
association is lost.

---

## 4. Evidence and completion sources

A step completes with one of two recorded sources:

- **`validated`** — the evidence was resolved to exact artifact versions
  and checked (the artifact exists, is non-empty, its fingerprint still
  matches, and no tool failure for that step is unresolved).
- **`agent_asserted`** — the agent asserted completion without evidence
  that could be verified. It is recorded as such, permanently, and
  recall reports it as weaker evidence.

A tool call that merely succeeded is never, on its own, evidence that a
step is done.

Evidence references are exact versions, written `artifact_id@version`. A
bare alias is rejected: an alias moves, so binding evidence to one would
mean "whatever is under that name now", which is not evidence at all.

**Overwrite versus mutation.** Writing a new value under an existing
alias allocates `version + 1` and leaves the bound version valid — that
is an overwrite, and it is normal. If the *content behind a bound
version* changes, that is a mutation: the binding is invalidated and
anything completed against it must be reopened.

---

## 5. Raw reads (ResultPolicy)

`wm_get_result(..., include_raw=True)` is bounded when task memory is
enabled. The ceiling is `max_rehydrate_bytes`; a caller may lower it but
never raise it, and `0` disables rehydration entirely. Tabular payloads
can be paged with `offset`/`limit` instead of materialised whole. When a
payload cannot be returned within the ceiling, the read is **refused with
a reason and the true byte size**, so the caller learns how far over it
was rather than receiving a silently truncated value.

With task memory disabled, `get_result` keeps its original schema and
behaviour exactly.

---

## 6. Safe REPL loads

Loading an artifact into a REPL worker uses a strict transport: values
cross the process boundary as Arrow IPC over shared memory, and anything
that would require pickle is **refused** rather than silently downgraded.
A refusal is explicit (`StrictTransportError`), because the point of a
strict load is that what arrives in the worker is provably what left.

Worker handles carry a generation. A binding made against one worker
generation does not silently resolve against a replacement worker.

---

## 7. Recovery: what an operator actually does

### Unknown outcomes

If a process dies after a tool started but before its terminal event was
recorded, the call is **unresolved**. Reconciliation appends exactly one
`tool_outcome_unknown` for it, and only when the owner is *provably*
dead.

This matters more than it sounds. A crashed call and a slow one look
identical in the journal — a start with no terminal event. Liveness is
what separates them, and liveness is **tri-state**: alive, dead, or
unestablished. Only a definite *dead* is reconciled. An unreachable Redis
returns "unestablished" and settles nothing, because inventing a death
is how a healthy call gets its external side effect run a second time.

**External effects are never re-run for you.** An unknown outcome is
surfaced as a non-retryable, explicit state for a human or an agent to
resolve. Repeated scans and concurrent reconcilers append at most one
unknown outcome.

### Association repair

If the conversation metadata is lost, an explicit same-scope task id
still works: call `wm_select_task`. Recall will not silently adopt such a
task for you.

### Strict serialization

Appends are serialized per task, under an optimistic `expected_revision`
check plus a per-task lock. A stale revision is reported as a conflict
carrying the current state, so the caller can recover in one round trip
rather than overwriting someone else's work. A task in a terminal status
accepts no further ordinary mutation — create a new task rather than
resurrecting one.

### Retention and archive limitations

Terminal tasks are archived and deleted after
`TASK_MEMORY_TERMINAL_RETENTION_DAYS`. The intent is appended **first**,
so the archive contains the event recording its own deletion; the archive
is then read back and **verified before anything is deleted**. Archive
keys are deterministic, so a crash-then-retry converges on one archive
rather than accumulating copies.

Known limitations, stated plainly:

- Deleting a journal destroys the local audit trail for that task.
  `SweepReport.audit_destroyed` records `(task_id, archive_reference)`,
  with `None` when no archive was configured — the honest statement that
  the trail is gone, not relocated.
- Evidence pinned by any **non-terminal** task is retained regardless of
  age.
- The packaged `JsonlArchiveWriter` is scope-bound, while
  `TaskMemoryRuntime` is deliberately scope-agnostic. The runtime
  therefore does **not** construct one; pass `archive=` explicitly. With
  `archive_uri` set and no writer supplied, the runtime warns and does
  not archive.
- `HotKeyCleaner` clears only the append-lease key. Recall and context
  keys are scope-scoped rather than task-scoped, so purging one task must
  not evict a live sibling's cache; they are TTL-bounded instead.

---

## 8. Migration and rollback

The PostgreSQL schema is `working_memory`, applied **explicitly at
deployment**. Nothing creates schema on a tool call.

```bash
python -m parrot.tools.working_memory.task_memory.store.postgres \
    --dsn "postgresql://user:pass@host:5432/parrot" --apply

python -m parrot.tools.working_memory.task_memory.store.postgres \
    --dsn "postgresql://user:pass@host:5432/parrot" --verify
```

`--revert` is **destructive**: it drops the schema and everything in it.

The migration is `packages/ai-parrot/src/parrot/tools/working_memory/task_memory/migrations/001_task_memory.sql`,
carrying both an UP and a DOWN half. `apply_migrations()` records the
version in `working_memory.schema_migrations`; `verify_schema()` refuses
startup when the migration is absent, incomplete, or *newer* than the
running build implements.

---

## 9. Stage 2 recall injection

When compaction reports `stage2_needed` and a task is selected, the bot
prepends one bounded recall snapshot to the rendered history. It is
transient context for a single provider call — it carries no `turn_id`,
is never persisted, and is not a claim that an LLM summarised anything.

The snapshot competes with history for one `ContextBudget.available`,
with framing and calibration inside the measurement. If both cannot fit,
the injection is **declined with a diagnostic** rather than overrunning:
an over-budget prompt is a provider error, whereas a missing snapshot
merely costs the model some context. It never injects a snapshot *and*
instructs the model to call recall in the same turn.

The compaction kill switch (`context_budget=False` /
`PARROT_COMPACTION_DISABLED=1`) preserves the plain rendering path
untouched.

---

## 10. Validation evidence

Both delivery gates and the crash matrix are runnable:

| Gate | Module |
|---|---|
| Delivery A acceptance | `packages/ai-parrot/tests/tools/working_memory/task_memory/test_delivery_a.py` |
| Disabled-mode parity | `packages/ai-parrot/tests/tools/working_memory/task_memory/test_disabled_compatibility.py` |
| Delivery B restart / multi-pod | `packages/ai-parrot/tests/tools/working_memory/task_memory/test_delivery_b.py` |
| Crash boundaries | `packages/ai-parrot/tests/tools/working_memory/task_memory/test_crash_matrix.py` |
| Durable wiring / lifecycle | `packages/ai-parrot/tests/tools/working_memory/task_memory/test_durable_wiring.py` |
| Fenced call recovery | `packages/ai-parrot/tests/tools/working_memory/task_memory/test_call_recovery.py` |
| AC16 metrics | `packages/ai-parrot/tests/tools/working_memory/task_memory/bench_task_memory.py` |
| Payload snapshot costs | `packages/ai-parrot/tests/tools/working_memory/task_memory/bench_snapshot_costs.py` |

Run the durable gates with real services:

```bash
export TASK_MEMORY_TEST_DSN="postgresql://user:pass@127.0.0.1:5432/scratch_db"
PYTHONPATH=packages/ai-parrot/src python -m pytest -q \
  packages/ai-parrot/tests/tools/working_memory
```

**Provisioning matters to how you read the result.** Without
`TASK_MEMORY_TEST_DSN` the durable cases **skip explicitly** and say so;
a skip is never a pass. At the time of writing the suite reports
**932 passed / 0 failed with services** and **842 passed / 90 skipped /
0 failed without** — the 90 skips are precisely the durable cases.

Metrics are recorded, not asserted as SLOs:

```bash
PYTHONPATH=packages/ai-parrot/src \
  python packages/ai-parrot/tests/tools/working_memory/task_memory/bench_task_memory.py
```

It reports recall tokens and build time, observer overhead, the
invalid-reference refusal rate, repeated operations after recovery, and
snapshot/fingerprint cost at 8, 64 and 256 MiB, each alongside the
environment that produced it. Set `TM_BENCH_MAX_MIB` to cap the largest
size on a small machine; sizes above the cap are reported as `skipped`.

### Measured results (AC16)

Recorded on Linux / Python 3.12 / pandas 2.x on a developer workstation,
with the in-memory backends. **These are observations, not SLOs**, and
the absolute numbers will differ on your hardware — reproduce them with
the command above rather than quoting these.

**Recall** (budget 2 500 tokens):

| Plan steps | Estimated tokens | Median build |
|---|---|---|
| 5 | 647 | 0.6 ms |
| 25 | 2 339 | 2.0 ms |
| 100 | 2 429 | 313 ms |

The token cap holds at every size — that part is asserted. The **build
time is markedly non-linear**: a 100-step plan costs roughly 150× a
25-step one while producing barely more output, because the selector is
doing far more work deciding what to *drop*. If you routinely run plans
of that size, measure before assuming recall is cheap. This is a known
characteristic, not a regression.

**Observer overhead**, per dispatch: ≈48 µs capture-only, ≈197 µs with
an in-memory journal append. The journalled figure is **not**
representative of PostgreSQL, which adds a real round trip.

**Invalid references**: 3 of 3 unverifiable references refused (rate
1.0), and 3 of 3 bare aliases rejected at parse time. This one *is*
asserted — accepting unverifiable evidence is the failure the feature
exists to prevent.

**Repeated operations after recovery**: 0. Two steps executed before the
simulated context loss, two different steps after, no re-execution.
Counted from real executions, not from a status field.

**Snapshot and fingerprint cost**:

| Payload | Size | Snapshot | Fingerprint | Peak RSS |
|---|---|---|---|---|
| DataFrame (numeric+string) | 8 MiB | 0.001 s | 0.29 s | 4 MiB |
| DataFrame | 64 MiB | 0.007 s | 2.32 s | 32 MiB |
| DataFrame | 256 MiB | 0.037 s | 9.36 s | 129 MiB |
| JSON text (orjson) | 8 MiB | 0.050 s | 0.012 s | 32 MiB |
| JSON text | 64 MiB | 0.402 s | 0.112 s | 254 MiB |
| JSON text | 256 MiB | 1.619 s | 0.423 s | 1 014 MiB |

**This measurement is what justifies the 64 MiB snapshot cap (D4).**
Fingerprinting a 256 MiB DataFrame takes ~9 s, and canonicalising 256 MiB
of JSON peaks at roughly 1 GB resident — because encoding holds the live
value and its encoded form at once. Snapshotting payloads of that size in
RAM on a request path is not viable, so above the cap the value is
persisted to a blob instead. The default stays 64 MiB.

Captured logs live in `artifacts/logs/`, one per task
(`task-3004-tm-delivery-b.log`, `task-3005-tm-docs-metrics.log`, …).

---

## 11. Design decisions worth knowing

| | Decision |
|---|---|
| D1 | One artifact store. A sibling store means writes land in one place and evidence is validated against another. |
| D2 | No SQLite backend. |
| D3 | Attribution is turn-scoped declared context, not inference. |
| D4 | 64 MiB RAM snapshot policy; above it, persist. |
| D5 | Reuse the compaction primitives; one observer produces the canonical `ToolInvocation`, and both the journal and `ConversationTurn.tool_invocations` derive from that one record. |
| D6 | The journal is the source of truth; `TaskState` is a pure reducer projection with no clock and no randomness. |
| D7 | Retention policies are explicit, never implicit. |
| D8 | Fail closed by default when the journal is unavailable; `best_effort_tracking` is an explicit opt-in that reports degradation. |

The full specification is `sdd/specs/workingmemory-toolkit.spec.md`, and
the Phase 0 integration survey is
`docs/memory/task-memory-integration-map.md`.
