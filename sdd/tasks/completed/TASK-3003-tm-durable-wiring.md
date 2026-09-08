# TASK-3003: Wire durable backend lifecycle and retention scheduling

**Feature**: FEAT-538 - Recoverable Task Memory for WorkingMemoryToolkit
**Spec**: `sdd/specs/workingmemory-toolkit.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2989, TASK-2993, TASK-3000, TASK-3001
**Assigned-to**: unassigned
**Parallel**: true
**Parallelism notes**: May run with ready disjoint tasks such as TASK-3002 after prerequisites. Shared-file predecessors: TASK-2971, TASK-2989, TASK-2990; do not edit their files concurrently.
**Delivery**: B
**Spec acceptance**: AC8, AC9, AC12, AC13, AC14

---

## Context

Implements §2 Persistence; opt-in integration of the approved specification. Delivery B establishes durable continuity; passing in-memory tests alone does not complete this work. Consume the committed contracts from TASK-2989, TASK-2993, TASK-3000, TASK-3001 before implementation.

## Scope

- Connect configured PostgreSQL task/artifact backends, shared coordinator, blob adapter, leases and recovery to the existing toolkit/observer instances.
- Validate enabled backend prerequisites and explicit migrations, strict mode and finite hot-key retention; no silent durable-to-memory fallback.
- Start/stop in-process retention/recovery scheduling with bounded cancellation, expose run_once for host qworker scheduling and preserve pool/lease ownership cleanup.

**NOT in scope**: Other task deliverables and files not listed here; provider/client schema changes, unrelated refactors, and new dependencies. Later-task APIs may be represented by explicit protocol fixtures, never runtime stubs shipped as complete implementations.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/tools/working_memory/task_memory/config.py` | MODIFY | Scoped implementation |
| `packages/ai-parrot/src/parrot/tools/working_memory/tool.py` | MODIFY | Scoped implementation |
| `packages/ai-parrot/src/parrot/bots/agent.py` | MODIFY | Scoped implementation |
| `packages/ai-parrot/tests/tools/working_memory/task_memory/test_durable_wiring.py` | CREATE | Task-specific verification / fixtures |

Ownership includes only these files and this task's SDD status/completion fields. You are not alone in the codebase: preserve others' edits and coordinate changes to shared files. CREATE refers to new feature outputs; MODIFY may reference a file created by an earlier dependency.

## Codebase Contract (Anti-Hallucination)

Re-read against core source at `0b4920b2f` on 2026-09-08. The core source tree is unchanged from the spec's pinned implementation commit; task artifacts do not implement the new APIs.

### Verified Imports

```python
from parrot.tools.working_memory import WorkingMemoryToolkit  # packages/ai-parrot/src/parrot/tools/working_memory/tool.py:259
from parrot.bots.agent import BasicAgent  # packages/ai-parrot/src/parrot/bots/agent.py:146
from pydantic import BaseModel, Field  # packages/ai-parrot/pyproject.toml:54
from parrot.interfaces.file import FileManagerInterface  # packages/ai-parrot/src/parrot/interfaces/file/__init__.py:18
```

### Existing Signatures to Use

Signature/field excerpts below identify existing APIs, not runnable replacement implementations.

**`packages/ai-parrot/src/parrot/tools/working_memory/tool.py:259`**

```python
async def get_result(self, key: str, max_length: int = 500, include_raw: bool = False) -> dict:
```

Constructor at line 103 has session_id/max_rows/max_cols/tool_locals_registry/answer_memory/thread_offload_cells; store at 194 and store_result at 208 call synchronous catalog methods.

**`packages/ai-parrot/src/parrot/bots/agent.py:146`**

```python
async def configure(self, app=None) -> None:
```

configure awaits its parent and then wires tool namespaces; new async task-memory setup belongs in an enabled lifecycle path.

**`packages/ai-parrot/pyproject.toml:54`**

```python
# Dependency declarations: Python >=3.11; pydantic ==2.12.5;
# pandas >=2.0.0; pyarrow >=25.0; orjson >=3.9;
# existing graphindex-postgres extra: asyncpg >=0.29.
```

Navigator-api >=3.2.2 is declared at 104; pyarrow at 157 and asyncpg optional dependency at 258. Reuse existing libraries and lazy startup checks.

**`packages/ai-parrot/src/parrot/interfaces/file/__init__.py:18`**

```python
# Verified export; external method signatures must be pinned in the Phase 0 task.
FileManagerInterface
```

Navigator file-manager interface plus local/temp managers are re-exported eagerly; S3/GCS are lazy exports.

### Does NOT Exist

- Task-memory opt-in constructor wiring and wm_* task tools do not exist at the verification commit.
- No task-memory backend/sweeper factory is already wired into configure.
- No new qworker/ULID/task-memory dependency is authorized; do not assume stdlib uuid7 on Python 3.11.
- No versioned Parquet task store is provided by this compatibility shim; do not invent external stream/stat methods.
- The new `parrot.tools.working_memory.task_memory` package and new interface contracts are absent at the verification commit. Dependencies in this task are responsible for introducing them; do not claim their proposed signatures are existing imports.

## Implementation Notes

### Pattern to Follow

Do not add qworker or other dependencies; schedule through the existing host application integration.

### Key Constraints

- Use only the approved spec's semantics and defaults; no new dependencies, schema routing parameters, SQLite backend or autonomous retries.
- Existing imports above are verified at the recorded commit. New task-memory symbols are produced by prerequisites; read their committed definitions before importing them.
- Use strict type hints and Pydantic input models for new domain APIs; preserve existing dataclass serializers. Follow black/isort and inherited toolkit logging.
- Keep mutations atomic and scope-bound, heavy work off the event loop, and raw payloads/credentials out of recall and journal context.
- Log focused verification to artifacts/logs/. Re-run existing regressions relevant to touched shared files; service-gated tests must distinguish skipped from passed.

### References in Codebase

- `packages/ai-parrot/src/parrot/tools/working_memory/tool.py:259` — Constructor at line 103 has session_id/max_rows/max_cols/tool_locals_registry/answer_memory/thread_offload_cells; store at 194 and store_result at 208 call synchronous catalog methods.
- `packages/ai-parrot/src/parrot/bots/agent.py:146` — configure awaits its parent and then wires tool namespaces; new async task-memory setup belongs in an enabled lifecycle path.
- `packages/ai-parrot/pyproject.toml:54` — Navigator-api >=3.2.2 is declared at 104; pyarrow at 157 and asyncpg optional dependency at 258. Reuse existing libraries and lazy startup checks.
- `packages/ai-parrot/src/parrot/interfaces/file/__init__.py:18` — Navigator file-manager interface plus local/temp managers are re-exported eagerly; S3/GCS are lazy exports.

## Acceptance Criteria

- [ ] Toolkit, observer and plan factory share the same stores/coordinator; no sibling artifact store appears.
- [ ] Missing migrations/DB/blob prerequisites fail enabled durable startup clearly; disabled mode is unaffected.
- [ ] Cancelled shutdown closes only owned resources, releases owned leases and leaves no periodic task leak.
- [ ] Scope is implemented without changes outside the ownership table, apart from required SDD status/completion updates.
- [ ] Spec criteria AC8, AC9, AC12, AC13, AC14 are verified for this task's scope and failure cases.
- [ ] Focused verification passes: `uv run pytest packages/ai-parrot/tests/tools/working_memory/task_memory/test_durable_wiring.py -q`; retain output in `artifacts/logs/task-3003-tm-durable-wiring.log`.
- [ ] Relevant existing regressions and import/format checks pass; any environmental skip is reported explicitly rather than labeled a passed acceptance case.

## Test Specification

Use deterministic fixtures and assert externally observable behavior, including failure atomicity. The following named cases are required; implement them in the test files above with pytest/pytest-asyncio. For the investigation/benchmark deliverable, verify the equivalent measurements and assertions in its runnable benchmark.

| Required case | Expected result |
|---|---|
| `test_configured_graph` | Toolkit, observer and plan factory share the same stores/coordinator; no sibling artifact store appears. |
| `test_startup_failure` | Missing migrations/DB/blob prerequisites fail enabled durable startup clearly; disabled mode is unaffected. |
| `test_shutdown` | Cancelled shutdown closes only owned resources, releases owned leases and leaves no periodic task leak. |

New test modules should use local fixtures unless the shared fixture task is already completed. PostgreSQL/Redis concurrency and restart claims require real isolated test services; unit doubles verify only local protocol behavior. Never contact production services or use production data for these tests.

## Agent Instructions

1. Read the approved spec and this task in the feature worktree.
2. Verify every dependency is done in `sdd/tasks/index/workingmemory-toolkit.json` and its completed task artifact exists.
3. Reverify the imports/signatures and read prerequisite implementations; update stale task-specific contract anchors before coding.
4. Set only this task's index status to `in-progress` with assignment/start timestamps and your session ID.
5. Implement the scoped deliverable, preserving others' changes and respecting shared-file ownership/dependency ordering.
6. Run focused tests and relevant regressions, saving logs under `artifacts/logs/`.
7. Move this task to `sdd/tasks/completed/TASK-3003-tm-durable-wiring.md` after acceptance passes.
8. Update only this task's per-spec index entry to `done`, set completed_at/file/verification, and fill the completion note. Never use the historical monolithic index.
9. Commit scoped implementation and task state as required by `$sdd-start`; do not mark the feature complete after Delivery A alone.

## Completion Note

**Completed by**: sdd-worker (Claude Opus 5) — 2026-09-09
**Commit**: `ec59fa570`

### What was built

`TaskMemoryRuntime` and `DurableStartupError` in `config.py`, plus the
durable connection settings (`dsn`, pool bounds, `blob_prefix`,
`retention_interval_seconds`). The runtime builds **one** task store and
**one** artifact store over it, so the toolkit, observer and plan factory
share a backend and a transaction coordinator (D1).
`WorkingMemoryToolkit.from_runtime(runtime, scope)` is the wiring entry
point; `BasicAgent.task_memory_runtime` (None by default) is started in
`configure()` and stopped in `shutdown()` under `asyncio.shield`.

It lives in `config.py` because that is the wiring the configuration
describes, and because `config.py` is this task's owned home for it —
no new module was permitted by the ownership table.

### No silent fallback, by design

`durable=True` without a `dsn` is refused at construction; a missing blob
backend, an unreachable database, or an un-applied migration each fail
**startup** with a message naming what is absent. Startup failure is
deliberately allowed to fail `configure()`. Degrading to the in-memory
store would be the worst outcome available: the deployment looks healthy
right up until the restart it was supposed to survive.

`run_once(scopes)` is exposed so a host qworker or cron can drive
retention without this package taking a queue dependency; the in-process
`PeriodicRetention` loop is opt-out via `start_scheduler=False`.

### A correction mutation testing forced

Shutdown originally skipped `store.close()` whenever the pool was
borrowed. But the store **already** tracks pool ownership and leaves a
borrowed pool open, so gating on the runtime's own flag skipped the
store's cleanup entirely — a different leak dressed up as a safeguard.
The store is now always closed.

That same mutation exposed a **vacuous test of my own**: the
borrowed-pool case ran on the in-memory path, where no pool exists at
all, so it asserted that a pool nothing could have closed was not
closed. It passed regardless of the implementation. It now runs on the
durable path and proves the borrowed pool still **serves queries** after
shutdown, with a counterpart test that a self-created pool IS closed.

### Verification evidence

- `test_durable_wiring.py`: **10/10 against live PostgreSQL 17.3**. Two
  cases skip explicitly without a DSN; a skip is never reported as a
  pass. Log: `artifacts/logs/task-3003-tm-durable-wiring.log`.
- `tests/tools/working_memory`: **924 passed / 0 failed** with services;
  **842 passed / 82 skipped / 0 failed** without.
- `tests/bots`: FAILED-set **identical** to the dev baseline (84
  pre-existing) — the check that matters, since `agent.py` was edited.
- 5 mutations, each caught by the intended test: silent durable-to-memory
  fallback, closing a borrowed pool, an unstopped retention loop,
  unreleased leases, and a sibling artifact store.
- `ruff` clean apart from one pre-existing F401 in `tool.py`
  (`AnswerMemory` under `TYPE_CHECKING`), previously verified to exist on
  `dev` and left alone as out of scope.

### Notes for the reviewer

- The runtime does **not** invent a scope. A scope is per user/session
  and is unknown at `configure()` time, so binding a toolkit to the
  runtime is the host's call via `from_runtime(runtime, scope)`. The
  agent adopts whatever the toolkit already holds (TASK-2990).
- `verify_schema()` already existed from TASK-2997/2998 and is reused
  rather than reimplemented; it names the missing table or migration.
- Shutdown never raises: each step is independent and reports, so one
  failing close cannot skip the rest and leak the others.

### Approved deviations

None.
