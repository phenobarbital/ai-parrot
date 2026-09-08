# TASK-2986: Implement task association and atomic Redis metadata merging

**Feature**: FEAT-538 - Recoverable Task Memory for WorkingMemoryToolkit
**Spec**: `sdd/specs/workingmemory-toolkit.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2979
**Assigned-to**: unassigned
**Parallel**: true
**Parallelism notes**: May run with ready disjoint tasks such as TASK-2980, TASK-2981, TASK-2982 after prerequisites. Owns distinct output files; do not modify package exports or shared fixtures outside this scope.
**Delivery**: A
**Spec acceptance**: AC1, AC11, AC13

---

## Context

Implements §2 Public task selection; Persistence of the approved specification. Delivery A establishes in-process continuity and must not be advertised as durable. Consume the committed contracts from TASK-2979 before implementation.

## Scope

- Implement selected/open task association with scope-safe keys, association revisions, finite configured TTL and explicit selection recovery.
- Add enabled atomic compare-and-merge for task/compaction/unrelated metadata in hash and full-history modes, including update_history and turn writers.
- On post-creation Redis failure return the committed task ID and association degradation without duplicating tasks; missing metadata does not delete tasks.

**NOT in scope**: Other task deliverables and files not listed here; provider/client schema changes, unrelated refactors, and new dependencies. Later-task APIs may be represented by explicit protocol fixtures, never runtime stubs shipped as complete implementations.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/tools/working_memory/task_memory/association.py` | CREATE | Scoped implementation |
| `packages/ai-parrot/src/parrot/memory/redis.py` | MODIFY | Scoped implementation |
| `packages/ai-parrot/tests/tools/working_memory/task_memory/test_task_association.py` | CREATE | Task-specific verification / fixtures |

Ownership includes only these files and this task's SDD status/completion fields. You are not alone in the codebase: preserve others' edits and coordinate changes to shared files. CREATE refers to new feature outputs; MODIFY may reference a file created by an earlier dependency.

## Codebase Contract (Anti-Hallucination)

Re-read against core source at `0b4920b2f` on 2026-09-08. The core source tree is unchanged from the spec's pinned implementation commit; task artifacts do not implement the new APIs.

### Verified Imports

```python
from parrot.memory.redis import RedisConversation  # packages/ai-parrot/src/parrot/memory/redis.py:238
from parrot.memory.abstract import ConversationTurn, ConversationHistory  # packages/ai-parrot/src/parrot/memory/abstract.py:178
```

### Existing Signatures to Use

Signature/field excerpts below identify existing APIs, not runnable replacement implementations.

**`packages/ai-parrot/src/parrot/memory/redis.py:238`**

```python
async def update_history(self, history: ConversationHistory) -> None:
# _store_turn at line 261:
async def _store_turn(self, user_id: str, session_id: str, turn: ConversationTurn, chatbot_id: Optional[str] = None, *, compaction_state: Optional[Dict[str, Any]] = None) -> None:
```

_get_key at 65 includes configured prefix, bot, user and session. Both hash and full-history writers can replace metadata; compaction path reads then writes at 290–297.

**`packages/ai-parrot/src/parrot/memory/abstract.py:178`**

```python
def from_ai_message(cls, *, user_message: str, response: "AIMessage", user_id: str, chatbot_id: str, context_used: Optional[str] = None, turn_id: Optional[str] = None, assistant_text: Optional[str] = None, error: Optional[str] = None) -> "ConversationTurn":
```

from_ai_message builds tool_invocations from response.tool_calls at 229. ConversationHistory has a metadata dictionary at 272; omission_key at 397 scopes bot/user/session.

### Does NOT Exist

- No atomic task/compaction metadata merge or per-call fenced lease protocol exists.
- No canonical task observer handoff or selected-task association behavior exists yet.
- The new `parrot.tools.working_memory.task_memory` package and new interface contracts are absent at the verification commit. Dependencies in this task are responsible for introducing them; do not claim their proposed signatures are existing imports.

## Implementation Notes

### Pattern to Follow

Compose the service/backend contracts from completed prerequisites. Keep new methods private unless the spec explicitly lists an LLM-facing tool. Keep the disabled path behavior and schemas unchanged.

### Key Constraints

- Use only the approved spec's semantics and defaults; no new dependencies, schema routing parameters, SQLite backend or autonomous retries.
- Existing imports above are verified at the recorded commit. New task-memory symbols are produced by prerequisites; read their committed definitions before importing them.
- Use strict type hints and Pydantic input models for new domain APIs; preserve existing dataclass serializers. Follow black/isort and inherited toolkit logging.
- Keep mutations atomic and scope-bound, heavy work off the event loop, and raw payloads/credentials out of recall and journal context.
- Log focused verification to artifacts/logs/. Re-run existing regressions relevant to touched shared files; service-gated tests must distinguish skipped from passed.

### References in Codebase

- `packages/ai-parrot/src/parrot/memory/redis.py:238` — _get_key at 65 includes configured prefix, bot, user and session. Both hash and full-history writers can replace metadata; compaction path reads then writes at 290–297.
- `packages/ai-parrot/src/parrot/memory/abstract.py:178` — from_ai_message builds tool_invocations from response.tool_calls at 229. ConversationHistory has a metadata dictionary at 272; omission_key at 397 scopes bot/user/session.

## Acceptance Criteria

- [ ] Race selection with calibration/turn save using real Redis; retain all metadata.
- [ ] Repeat for full-history mode and stale histories; no lost selected task/calibration.
- [ ] Multiple unselected tasks return needs_task_selection; explicit ID recovery never crosses scope.
- [ ] Scope is implemented without changes outside the ownership table, apart from required SDD status/completion updates.
- [ ] Spec criteria AC1, AC11, AC13 are verified for this task's scope and failure cases.
- [ ] Focused verification passes: `uv run pytest packages/ai-parrot/tests/tools/working_memory/task_memory/test_task_association.py -q`; retain output in `artifacts/logs/task-2986-tm-redis-association.log`.
- [ ] Relevant existing regressions and import/format checks pass; any environmental skip is reported explicitly rather than labeled a passed acceptance case.

## Test Specification

Use deterministic fixtures and assert externally observable behavior, including failure atomicity. The following named cases are required; implement them in the test files above with pytest/pytest-asyncio. For the investigation/benchmark deliverable, verify the equivalent measurements and assertions in its runnable benchmark.

| Required case | Expected result |
|---|---|
| `test_race_hash` | Race selection with calibration/turn save using real Redis; retain all metadata. |
| `test_race_full` | Repeat for full-history mode and stale histories; no lost selected task/calibration. |
| `test_selection` | Multiple unselected tasks return needs_task_selection; explicit ID recovery never crosses scope. |

New test modules should use local fixtures unless the shared fixture task is already completed. PostgreSQL/Redis concurrency and restart claims require real isolated test services; unit doubles verify only local protocol behavior. Never contact production services or use production data for these tests.

## Agent Instructions

1. Read the approved spec and this task in the feature worktree.
2. Verify every dependency is done in `sdd/tasks/index/workingmemory-toolkit.json` and its completed task artifact exists.
3. Reverify the imports/signatures and read prerequisite implementations; update stale task-specific contract anchors before coding.
4. Set only this task's index status to `in-progress` with assignment/start timestamps and your session ID.
5. Implement the scoped deliverable, preserving others' changes and respecting shared-file ownership/dependency ordering.
6. Run focused tests and relevant regressions, saving logs under `artifacts/logs/`.
7. Move this task to `sdd/tasks/completed/TASK-2986-tm-redis-association.md` after acceptance passes.
8. Update only this task's per-spec index entry to `done`, set completed_at/file/verification, and fill the completion note. Never use the historical monolithic index.
9. Commit scoped implementation and task state as required by `$sdd-start`; do not mark the feature complete after Delivery A alone.

## Completion Note

**Completed by**: Claude Opus 5 (sdd-worker, delegated fork) — session `01WeeSf3QmPq58bBxturogRX`
**Date**: 2026-09-08
**Status**: done

### Evidence — LIVE against real Redis
- **13 passed, 0 skipped.** Redis was reachable at `localhost:6379` (db
  15), so all three required cases (`test_race_hash`, `test_race_full`,
  `test_selection`) plus the lease and TTL cases **ran live**. Isolated
  `tmassoc_<hex>` prefix per test, deleted in a `finally`. Reachability
  re-confirmed independently during review.
- Regressions: memory suite **158 passed**; `test_legacy_rekey.py`
  **24 passed**. `ruff`/`black`/`isort` clean.

### The defect fixed
`RedisConversation._store_turn` did `hget("metadata")` → mutate in Python
→ `hset` — a non-atomic read-modify-write. A concurrent task-association
write and a compaction write lose one of the two. A task-only lock cannot
fix it **because the compaction writer never takes one**: correctness
cannot depend on every writer cooperating, only on all of them going
through Redis. Replaced with server-side `WATCH`/`MULTI`/`EXEC`.

### The race test is discriminating — and that was verified
A passing live race is weak evidence, because real Redis only *sometimes*
interleaves. `_InterleavingRedis` injects the competing write
deterministically between the watched read and the write. Run against the
naive read-modify-write it **silently erased** the competing writer's
`compaction` block; the CAS retains it after one abort. Without that
check the test could have passed against the bug.

### A regression this task introduced and fixed
The first CAS version broke `tests/unit/memory/test_legacy_rekey.py`
(24 passed → 19 failed): its `_FakeRedis` has no `pipeline()`. Confirmed
by swapping the committed `redis.py` back in (baseline 24) and restoring
md5-identically. Fixed in `redis.py` rather than in the test (which this
task does not own): `_supports_cas()` probes for `pipeline` and falls back
to the pre-FEAT-538 direct write. A single-process double has no competing
writer for a CAS to protect against, so the fallback costs nothing there —
and crashing on such clients is a behaviour regression the atomicity work
is not entitled to cause.

### Backoff was necessary, not cosmetic
With 20 concurrent writers the first version exhausted its retry budget
and raised: every loser re-read at the same instant and collided again.
Jittered exponential backoff (2 ms base, 100 ms cap, 16 attempts)
converges — which is why the budget is not simply "8 retries".

### PRE-EXISTING PRODUCTION BUG found, deliberately NOT fixed
`RedisConversation.create_history` in **hash mode** builds its `mapping`
and **never calls `hset`**. The record is not persisted at all: metadata
passed at creation is silently discarded and the key does not exist until
the first turn is saved.

Verified independently during review against committed `HEAD`:
- the `if self.use_hash_storage:` branch ends after building `mapping`,
  with no write, while the `else` branch does `await self.redis.set(...)`;
- **`use_hash_storage` defaults to `True`** and is documented as
  "RECOMMENDED", so this is the default path;
- reached from 7 production call sites, including all four `bots/base.py`
  entry points, `bots/abstract.py:1907`, `storage/chat.py:203` and
  `outputs/a2ui/runtime/adapters.py:185`.

Out of scope for this task and left alone. **It warrants its own task.**
The association path is unaffected, because `merge_metadata` performs its
own write; these tests seed via `update_history` instead.

### Other decisions
- `mutate` is documented as a **pure** function, since a CAS abort re-runs
  it.
- Association writes report `degraded` rather than raising, so a Redis
  failure can never tempt a caller into creating a **second** task for
  work already committed to PostgreSQL.
- Closing the selected task **clears** the selection rather than guessing
  a replacement.
- Lease renew/release use Lua so read-and-act is atomic: a separate
  `GET` + `PEXPIRE` could extend someone else's lease.

### Environment gaps reported, not silently patched
`hypothesis` is missing from the pruned venv, so `test_compact.py` and
`test_normalize.py` could not be collected. `test_chat_storage.py` also
fails to import (`CONVERSATIONS_COLLECTION` missing from
`parrot.storage.chat`), unrelated to this change.
