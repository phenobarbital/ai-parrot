# TASK-2994: Define PostgreSQL migrations and shared transaction coordinator

**Feature**: FEAT-538 - Recoverable Task Memory for WorkingMemoryToolkit
**Spec**: `sdd/specs/workingmemory-toolkit.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2972
**Assigned-to**: unassigned
**Parallel**: true
**Parallelism notes**: May run with ready disjoint tasks such as TASK-2973, TASK-2974, TASK-2975 after prerequisites. Owns distinct output files; do not modify package exports or shared fixtures outside this scope.
**Delivery**: B
**Spec acceptance**: AC2, AC5, AC11, AC12

---

## Context

Implements §2 Persistence and Recovery tables of the approved specification. Delivery B establishes durable continuity; passing in-memory tests alone does not complete this work. Consume the committed contracts from TASK-2972 before implementation.

## Scope

- Create all six scoped working_memory tables/indexes and explicit migration/version checks with documented rollback procedure.
- Implement lazy asyncpg pool lifecycle and a reusable single-connection transaction coordinator for task/alias/evidence publication.
- Enforce non-null unassociated alias namespaces, unique artifact versions/event IDs and database ownership checks without automatic DDL during tools.

**NOT in scope**: Other task deliverables and files not listed here; provider/client schema changes, unrelated refactors, and new dependencies. Later-task APIs may be represented by explicit protocol fixtures, never runtime stubs shipped as complete implementations.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/tools/working_memory/task_memory/migrations/001_task_memory.sql` | CREATE | Explicit schema migration |
| `packages/ai-parrot/src/parrot/tools/working_memory/task_memory/store/postgres.py` | CREATE | Scoped implementation |
| `packages/ai-parrot/tests/tools/working_memory/task_memory/test_postgres_schema.py` | CREATE | Task-specific verification / fixtures |

Ownership includes only these files and this task's SDD status/completion fields. You are not alone in the codebase: preserve others' edits and coordinate changes to shared files. CREATE refers to new feature outputs; MODIFY may reference a file created by an earlier dependency.

## Codebase Contract (Anti-Hallucination)

Re-read against core source at `0b4920b2f` on 2026-09-08. The core source tree is unchanged from the spec's pinned implementation commit; task artifacts do not implement the new APIs.

### Verified Imports

```python
from pydantic import BaseModel, Field  # packages/ai-parrot/pyproject.toml:54
from parrot.memory.redis import RedisConversation  # packages/ai-parrot/src/parrot/memory/redis.py:238
from parrot.tools.working_memory.internals import WorkingMemoryCatalog, CatalogEntry, GenericEntry  # packages/ai-parrot/src/parrot/tools/working_memory/internals.py:542
```

### Existing Signatures to Use

Signature/field excerpts below identify existing APIs, not runnable replacement implementations.

**`packages/ai-parrot/pyproject.toml:54`**

```python
# Dependency declarations: Python >=3.11; pydantic ==2.12.5;
# pandas >=2.0.0; pyarrow >=25.0; orjson >=3.9;
# existing graphindex-postgres extra: asyncpg >=0.29.
```

Navigator-api >=3.2.2 is declared at 104; pyarrow at 157 and asyncpg optional dependency at 258. Reuse existing libraries and lazy startup checks.

**`packages/ai-parrot/src/parrot/memory/redis.py:238`**

```python
async def update_history(self, history: ConversationHistory) -> None:
# _store_turn at line 261:
async def _store_turn(self, user_id: str, session_id: str, turn: ConversationTurn, chatbot_id: Optional[str] = None, *, compaction_state: Optional[Dict[str, Any]] = None) -> None:
```

_get_key at 65 includes configured prefix, bot, user and session. Both hash and full-history writers can replace metadata; compaction path reads then writes at 290–297.

**`packages/ai-parrot/src/parrot/tools/working_memory/internals.py:542`**

```python
def get(self, key: str) -> CatalogEntry | GenericEntry:
def drop(self, key: str) -> bool:
```

GenericEntry at 70 owns data; CatalogEntry at 175 owns df and computed shape at 189. Catalog constructor at 468 and put/put_generic at 473/499 are synchronous and use a plain dictionary.

### Does NOT Exist

- No new qworker/ULID/task-memory dependency is authorized; do not assume stdlib uuid7 on Python 3.11.
- No atomic task/compaction metadata merge or per-call fenced lease protocol exists.
- No awaited catalog backend, versioned evidence metadata, locks or to_descriptor method exists at this commit.
- The new `parrot.tools.working_memory.task_memory` package and new interface contracts are absent at the verification commit. Dependencies in this task are responsible for introducing them; do not claim their proposed signatures are existing imports.

## Implementation Notes

### Pattern to Follow

Do not implement full task or artifact CRUD here; subsequent tasks own those additions.

### Key Constraints

- Use only the approved spec's semantics and defaults; no new dependencies, schema routing parameters, SQLite backend or autonomous retries.
- Existing imports above are verified at the recorded commit. New task-memory symbols are produced by prerequisites; read their committed definitions before importing them.
- Use strict type hints and Pydantic input models for new domain APIs; preserve existing dataclass serializers. Follow black/isort and inherited toolkit logging.
- Keep mutations atomic and scope-bound, heavy work off the event loop, and raw payloads/credentials out of recall and journal context.
- Log focused verification to artifacts/logs/. Re-run existing regressions relevant to touched shared files; service-gated tests must distinguish skipped from passed.

### References in Codebase

- `packages/ai-parrot/pyproject.toml:54` — Navigator-api >=3.2.2 is declared at 104; pyarrow at 157 and asyncpg optional dependency at 258. Reuse existing libraries and lazy startup checks.
- `packages/ai-parrot/src/parrot/memory/redis.py:238` — _get_key at 65 includes configured prefix, bot, user and session. Both hash and full-history writers can replace metadata; compaction path reads then writes at 290–297.
- `packages/ai-parrot/src/parrot/tools/working_memory/internals.py:542` — GenericEntry at 70 owns data; CatalogEntry at 175 owns df and computed shape at 189. Catalog constructor at 468 and put/put_generic at 473/499 are synchronous and use a plain dictionary.

## Acceptance Criteria

- [ ] Apply migration in isolated PostgreSQL schema, repeat safely, and verify constraints/rollback guidance.
- [ ] Task/artifact callbacks share the same connection/transaction; rollback removes all tentative rows.
- [ ] Disabled configuration does not require a running DB or import concrete backend modules eagerly.
- [ ] Scope is implemented without changes outside the ownership table, apart from required SDD status/completion updates.
- [ ] Spec criteria AC2, AC5, AC11, AC12 are verified for this task's scope and failure cases.
- [ ] Focused verification passes: `uv run pytest packages/ai-parrot/tests/tools/working_memory/task_memory/test_postgres_schema.py -q`; retain output in `artifacts/logs/task-2994-tm-postgres-schema.log`.
- [ ] Relevant existing regressions and import/format checks pass; any environmental skip is reported explicitly rather than labeled a passed acceptance case.

## Test Specification

Use deterministic fixtures and assert externally observable behavior, including failure atomicity. The following named cases are required; implement them in the test files above with pytest/pytest-asyncio. For the investigation/benchmark deliverable, verify the equivalent measurements and assertions in its runnable benchmark.

| Required case | Expected result |
|---|---|
| `test_migration` | Apply migration in isolated PostgreSQL schema, repeat safely, and verify constraints/rollback guidance. |
| `test_coordinator` | Task/artifact callbacks share the same connection/transaction; rollback removes all tentative rows. |
| `test_optional_import` | Disabled configuration does not require a running DB or import concrete backend modules eagerly. |

New test modules should use local fixtures unless the shared fixture task is already completed. PostgreSQL/Redis concurrency and restart claims require real isolated test services; unit doubles verify only local protocol behavior. Never contact production services or use production data for these tests.

## Agent Instructions

1. Read the approved spec and this task in the feature worktree.
2. Verify every dependency is done in `sdd/tasks/index/workingmemory-toolkit.json` and its completed task artifact exists.
3. Reverify the imports/signatures and read prerequisite implementations; update stale task-specific contract anchors before coding.
4. Set only this task's index status to `in-progress` with assignment/start timestamps and your session ID.
5. Implement the scoped deliverable, preserving others' changes and respecting shared-file ownership/dependency ordering.
6. Run focused tests and relevant regressions, saving logs under `artifacts/logs/`.
7. Move this task to `sdd/tasks/completed/TASK-2994-tm-postgres-schema.md` after acceptance passes.
8. Update only this task's per-spec index entry to `done`, set completed_at/file/verification, and fill the completion note. Never use the historical monolithic index.
9. Commit scoped implementation and task state as required by `$sdd-start`; do not mark the feature complete after Delivery A alone.

## Completion Note

**Completed by**: Claude Opus 5 (sdd-worker, delegated fork) — session `01WeeSf3QmPq58bBxturogRX`
**Date**: 2026-09-08
**Status**: done (Delivery B)

### Evidence and its limits — read this before trusting the numbers
- In the **reviewing** environment no `TASK_MEMORY_TEST_DSN` is set, so
  the 6 live cases **SKIP**, with messages that read verbatim: *"This is
  an ENVIRONMENTAL SKIP, not a pass — the migration was not applied
  here."* Result here: **24 passed, 6 skipped**.
- The implementing agent reported running them against a **real
  PostgreSQL 17.3** (30 passed; unique `wm_test_<hex>` schemas created and
  dropped in a `finally`; zero left behind afterwards). **That run could
  not be reproduced during review** — a server is listening on
  `localhost:5432` but with different credentials, and hunting for working
  credentials was out of scope. It is recorded as the agent's claim, not
  as verified evidence.
- Everything checkable **without** a server was verified directly during
  review: all six tables present; `task_ns TEXT NOT NULL DEFAULT ''` and
  part of the primary key; no `pinned` column anywhere; the down migration
  present; no module-level `import asyncpg`; no real credentials in any
  committed file (the only DSNs are obviously fake — `postgresql://unused/db`,
  `nonexistent.invalid`).
- `ruff`/`black`/`isort` clean. Contract re-verified; **no stale anchors**.

### Design decisions
1. **`artifact_aliases.task_ns` is `TEXT NOT NULL DEFAULT ''`**, not a
   nullable `task_id`. In SQL `NULL <> NULL`, so a unique constraint over
   a nullable column permits unlimited duplicate rows in the unassociated
   namespace, and two concurrent writers would each allocate version 1 for
   the same key. It is part of the PK, which is stronger still.
2. **Pinning is derived, never stored.** A test asserts no
   `pinned BOOLEAN` column exists. A single flag cannot express "two tasks
   reference this, one has finished", and consulting only the producing
   task would let a cross-task reference be swept out from under its
   holder.
3. **Constraints live in the database, not only in Pydantic.**
   `artifacts_verifiable_needs_fingerprint` mirrors `ArtifactDescriptor`'s
   validator, so a direct SQL writer cannot claim verifiable evidence
   without a fingerprint. `tasks_terminal_consistent` stops a live task
   carrying a terminal timestamp, which a retention sweep would otherwise
   expire.
4. **`PostgresTransaction.connection` raises after completion** rather
   than returning a connection that would silently run *outside* the
   transaction — the exact failure the coordinator exists to prevent.
5. **CRUD raises `NotImplementedError` naming TASK-2995**, rather than
   returning a plausible empty result. A store that accepted an append and
   persisted nothing is worse than one that refuses.
6. **The optional-import test measures a delta, not an absolute.**
   Importing anything under `parrot.tools.working_memory` already loads
   `asyncpg` via that package's eager `__init__` — the same baseline
   TASK-2972 recorded. The delta probe is paired with an AST check for a
   module-level import and a companion test that fails deliberately if M5
   later makes that import lazy.

### FOLLOW-UP for whoever owns `store/__init__.py`
It documents a `postgres` backend but exports nothing from it. Left
untouched deliberately: a plain import there would defeat the lazy-driver
guarantee, so the owner should decide on a lazy `__getattr__` export.
