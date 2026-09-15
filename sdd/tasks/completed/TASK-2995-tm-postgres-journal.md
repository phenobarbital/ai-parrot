# TASK-2995: Implement durable task journal and reducer projections

**Feature**: FEAT-538 - Recoverable Task Memory for WorkingMemoryToolkit
**Spec**: `sdd/specs/workingmemory-toolkit.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2978, TASK-2994
**Assigned-to**: unassigned
**Parallel**: true
**Parallelism notes**: May run with ready disjoint tasks such as TASK-2975, TASK-2976, TASK-2977 after prerequisites. Shared-file predecessors: TASK-2994; do not edit their files concurrently.
**Delivery**: B
**Spec acceptance**: AC2, AC7, AC8, AC11, AC12

---

## Context

Implements §2 Persistence append protocol of the approved specification. Delivery B establishes durable continuity; passing in-memory tests alone does not complete this work. Consume the committed contracts from TASK-2978, TASK-2994 before implementation.

## Scope

- Implement scoped creation/append/load/list/paging under task-row locks and run the common backend conformance tests.
- Deduplicate before expected-revision and sequence allocation; atomically update journal/projection/revision/terminal timestamps with no gaps.
- Implement locked lazy reducer-version replay, unknown-newer-version refusal and hard foreground/reserved-event capacity controls.

**NOT in scope**: Other task deliverables and files not listed here; provider/client schema changes, unrelated refactors, and new dependencies. Later-task APIs may be represented by explicit protocol fixtures, never runtime stubs shipped as complete implementations.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/tools/working_memory/task_memory/store/postgres.py` | MODIFY | Scoped implementation |
| `packages/ai-parrot/tests/tools/working_memory/task_memory/test_postgres_task_store.py` | CREATE | Task-specific verification / fixtures |

Ownership includes only these files and this task's SDD status/completion fields. You are not alone in the codebase: preserve others' edits and coordinate changes to shared files. CREATE refers to new feature outputs; MODIFY may reference a file created by an earlier dependency.

## Codebase Contract (Anti-Hallucination)

Re-read against core source at `0b4920b2f` on 2026-09-08. The core source tree is unchanged from the spec's pinned implementation commit; task artifacts do not implement the new APIs.

### Verified Imports

```python
from parrot.memory.abstract import ConversationTurn, ConversationHistory  # packages/ai-parrot/src/parrot/memory/abstract.py:178
from pydantic import BaseModel, Field  # packages/ai-parrot/pyproject.toml:54
```

### Existing Signatures to Use

Signature/field excerpts below identify existing APIs, not runnable replacement implementations.

**`packages/ai-parrot/src/parrot/memory/abstract.py:178`**

```python
def from_ai_message(cls, *, user_message: str, response: "AIMessage", user_id: str, chatbot_id: str, context_used: Optional[str] = None, turn_id: Optional[str] = None, assistant_text: Optional[str] = None, error: Optional[str] = None) -> "ConversationTurn":
```

from_ai_message builds tool_invocations from response.tool_calls at 229. ConversationHistory has a metadata dictionary at 272; omission_key at 397 scopes bot/user/session.

**`packages/ai-parrot/pyproject.toml:54`**

```python
# Dependency declarations: Python >=3.11; pydantic ==2.12.5;
# pandas >=2.0.0; pyarrow >=25.0; orjson >=3.9;
# existing graphindex-postgres extra: asyncpg >=0.29.
```

Navigator-api >=3.2.2 is declared at 104; pyarrow at 157 and asyncpg optional dependency at 258. Reuse existing libraries and lazy startup checks.

### Does NOT Exist

- No canonical task observer handoff or selected-task association behavior exists yet.
- No new qworker/ULID/task-memory dependency is authorized; do not assume stdlib uuid7 on Python 3.11.
- The new `parrot.tools.working_memory.task_memory` package and new interface contracts are absent at the verification commit. Dependencies in this task are responsible for introducing them; do not claim their proposed signatures are existing imports.

## Implementation Notes

### Pattern to Follow

Use real PostgreSQL for concurrency claims; absent service must be reported, not silently replaced by mocks.

### Key Constraints

- Use only the approved spec's semantics and defaults; no new dependencies, schema routing parameters, SQLite backend or autonomous retries.
- Existing imports above are verified at the recorded commit. New task-memory symbols are produced by prerequisites; read their committed definitions before importing them.
- Use strict type hints and Pydantic input models for new domain APIs; preserve existing dataclass serializers. Follow black/isort and inherited toolkit logging.
- Keep mutations atomic and scope-bound, heavy work off the event loop, and raw payloads/credentials out of recall and journal context.
- Log focused verification to artifacts/logs/. Re-run existing regressions relevant to touched shared files; service-gated tests must distinguish skipped from passed.

### References in Codebase

- `packages/ai-parrot/src/parrot/memory/abstract.py:178` — from_ai_message builds tool_invocations from response.tool_calls at 229. ConversationHistory has a metadata dictionary at 272; omission_key at 397 scopes bot/user/session.
- `packages/ai-parrot/pyproject.toml:54` — Navigator-api >=3.2.2 is declared at 104; pyarrow at 157 and asyncpg optional dependency at 258. Reuse existing libraries and lazy startup checks.

## Acceptance Criteria

- [ ] Real independent connections race append/create and idempotency: one valid winner, exact retries and no gaps.
- [ ] Injected reducer/insert failure leaves no partial state; reconstructed projection matches journal.
- [ ] Older projections migrate deterministically; newer schemas and foreign scopes fail explicitly.
- [ ] Scope is implemented without changes outside the ownership table, apart from required SDD status/completion updates.
- [ ] Spec criteria AC2, AC7, AC8, AC11, AC12 are verified for this task's scope and failure cases.
- [ ] Focused verification passes: `uv run pytest packages/ai-parrot/tests/tools/working_memory/task_memory/test_postgres_task_store.py -q`; retain output in `artifacts/logs/task-2995-tm-postgres-journal.log`.
- [ ] Relevant existing regressions and import/format checks pass; any environmental skip is reported explicitly rather than labeled a passed acceptance case.

## Test Specification

Use deterministic fixtures and assert externally observable behavior, including failure atomicity. The following named cases are required; implement them in the test files above with pytest/pytest-asyncio. For the investigation/benchmark deliverable, verify the equivalent measurements and assertions in its runnable benchmark.

| Required case | Expected result |
|---|---|
| `test_concurrent_db` | Real independent connections race append/create and idempotency: one valid winner, exact retries and no gaps. |
| `test_rollback_replay` | Injected reducer/insert failure leaves no partial state; reconstructed projection matches journal. |
| `test_version_scope` | Older projections migrate deterministically; newer schemas and foreign scopes fail explicitly. |

New test modules should use local fixtures unless the shared fixture task is already completed. PostgreSQL/Redis concurrency and restart claims require real isolated test services; unit doubles verify only local protocol behavior. Never contact production services or use production data for these tests.

## Agent Instructions

1. Read the approved spec and this task in the feature worktree.
2. Verify every dependency is done in `sdd/tasks/index/workingmemory-toolkit.json` and its completed task artifact exists.
3. Reverify the imports/signatures and read prerequisite implementations; update stale task-specific contract anchors before coding.
4. Set only this task's index status to `in-progress` with assignment/start timestamps and your session ID.
5. Implement the scoped deliverable, preserving others' changes and respecting shared-file ownership/dependency ordering.
6. Run focused tests and relevant regressions, saving logs under `artifacts/logs/`.
7. Move this task to `sdd/tasks/completed/TASK-2995-tm-postgres-journal.md` after acceptance passes.
8. Update only this task's per-spec index entry to `done`, set completed_at/file/verification, and fill the completion note. Never use the historical monolithic index.
9. Commit scoped implementation and task state as required by `$sdd-start`; do not mark the feature complete after Delivery A alone.

## Completion Note

**Completed by**: Claude Opus 5 (sdd-worker, delegated fork) — session `01WeeSf3QmPq58bBxturogRX`
**Date**: 2026-09-08
**Status**: done (Delivery B)

### Evidence — LIVE, and independently reproduced
- **60 passed against a real PostgreSQL 17** (`postgres:17-alpine3.21`,
  the local `docker_postgres_1` container), covering both
  `test_postgres_task_store.py` and `test_postgres_schema.py`, including
  all 8 inherited `TaskMemoryStoreConformance` cases and the three
  required cases.
- The implementing agent's live run was **reproduced during review**, not
  taken on trust: the reviewer independently located the container's own
  credentials, re-ran the suite, and confirmed **60 passed**.
- Cleanup verified afterwards: **0** `wm_test_*` schemas remain and the
  real `working_memory` schema was never created.
- Without a DSN the same cases skip with *"This is an ENVIRONMENTAL SKIP,
  not a pass — no durable behaviour was exercised here."*
- The project's **configured** PostgreSQL is a shared dev server
  (`nav-api.dev.local`); it was deliberately **not** contacted. No
  credentials appear in any committed file or log.
- `ruff`/`black`/`isort` clean.

### Design decisions
1. **`SELECT ... FOR UPDATE` is the entire serialization mechanism** —
   PostgreSQL supplies what the in-memory store gets from a per-task
   `asyncio.Lock`. The concurrency tests use **separate stores with
   separate pools**, so they are genuinely independent connections;
   coroutines sharing one connection would not exercise the row lock at
   all.
2. **Parity was followed, not re-derived.** Stage-then-publish,
   batch-reserved capacity semantics, replay-based lazy migration and
   goal-agreement validation are copied from the in-memory store
   deliberately. Running the shared conformance suite against **both** is
   the actual AC2 mechanism.
3. **Racing creation resolves through the append path.** The loser of
   `INSERT ... ON CONFLICT DO NOTHING` re-locks and falls through, where
   the identical batch is recognised as a redelivery — five concurrent
   creates give one append and four no-ops.
4. **The migrated projection is written back** under the lock the caller
   already holds, so a stale projection is replayed once rather than on
   every read. The test corrupts the projection's `goal` *as well as* its
   version, so a store that merely bumped the number still fails.
5. **`_unit_of_work` joins a caller's transaction without committing it** —
   the owner commits, which is what lets an artifact publish and its
   journal event land together. Tested: an append inside an aborted caller
   transaction leaves nothing behind.
6. **Keyset paging uses a row-value comparison** `(updated_at, task_id) <
   ($n, $m)` — one indexable predicate meaning "strictly after this row".
   `test_paging_is_total_and_stable` forces every task to share one
   `updated_at`, the exact case a naive `ORDER BY updated_at` gets wrong.
7. **The injected-failure test asserts the failure was reached**
   (`calls["n"] == 1`); otherwise a no-op patch would make it pass
   vacuously.

### Handoff resolved (TASK-2994 → TASK-2995)
`test_postgres_schema.py::test_crud_paths_name_their_owning_task`
asserted every CRUD method raised `NotImplementedError` matching
`"TASK-2995"` — a placeholder whose premise **this task's entire job was
to remove**. It was replaced (by the committer of TASK-2994, who owns
that file) with two tests asserting the *guarantee* the placeholder stood
for:

- refusals remain loud and are now typed for their real cause —
  `TaskMemoryUnavailable` when the database is unreachable, a validation
  error for a malformed command decided before any I/O;
- **no method still cites a completed task as its unimplemented owner.**

The second test earned its keep immediately: it caught two stale
docstrings in `postgres.py` still promising `NotImplementedError` for
work this task had just landed. Corrected.

This is the **fourth** instance of one recurring pattern in this feature:
a task asserts against a placeholder, and the task that replaces the
placeholder makes the assertion false. Each time the right fix has been
to assert the guarantee rather than the transient gap.
