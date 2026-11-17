---
type: feature
base_branch: dev
feature_id: FEAT-897
projects: [ai-parrot]
tags: [storage, durable-conversation-memory, tombstones, ledger-fix]
discovered_from: issue:6393789b3d37
docs:
  policy: required
  pages:
    - wiki/stores/storage-backends.md
    - wiki/memory/durable-conversation-memory.md
  api_modules:
    - parrot.storage.backends.base
---

# Feature Specification: batched session-tombstone read for conversation listing

**Feature ID**: FEAT-897
**Date**: 2026-11-14
**Author**: Jesus Lara
**Status**: approved
**Target version**: next patch

---

## 1. Motivation & Business Requirements

### Problem Statement

FEAT-886 ("Deletion wins", G7) fences every read with durable tombstones. Three costs and one correctness
gap remain in the ChatStorage ↔ `ConversationBackend` boundary (`issue:6393789b3d37`, follow-up of
`issue:2eb281efebe1` / PR #2123):

1. **N+1 on listing.** `ChatStorage.list_user_conversations` hides tombstoned threads by calling
   `ConversationBackend.is_deleted` once per listed thread (`chat.py:561` `_sessions_deleted`). PR #2123 made
   those calls concurrent (at most 8 in flight) but the request count is unchanged: a 50-thread page costs 50
   tombstone reads. The contract already has a batched TURN read (`deleted_turn_ids`, commit `2411081ac6`) but
   no batched SESSION read.
2. **Short pages.** `list_user_conversations` passes `limit` to `query_threads` and hides tombstoned threads
   afterwards, so a page holds fewer than `limit` live conversations whenever a tombstoned thread is still in
   the window (cleanup lag or a failed cleanup). The turn reads had the same defect and were fixed in
   `2411081ac6`; the listing was not.
3. **Two reads per stored turn.** `ChatStorage._fence_after_write` (`chat.py:220`) calls
   `is_deleted(user, agent, session)` and then `is_deleted(user, agent, session, turn_id)`. All four backends
   already answer the second call as "session OR turn tombstoned" (SQL `turn_id IN ('', $4)`, Mongo
   `$in: ["", turn_id]`, DynamoDB two `GetItem`s), so the first call is redundant on the common live path —
   but `ConversationBackend.is_deleted` does not state that semantics, the shared durable contract does not
   assert it, and the reference backend in `tests/storage/test_storage_errors.py` answers turn-only. The fence
   cannot rely on a guarantee nobody wrote down.

### Goals

- **G1** — `ConversationBackend.deleted_session_ids(user_id, agent_id, session_ids)` returns the subset of
  `session_ids` that carry a SESSION tombstone in one bounded read per backend (SQLite/Postgres/Mongo: one
  query per chunk; DynamoDB: consistent `BatchGetItem` in chunks of ≤ 100 keys, `UnprocessedKeys` retried),
  fails closed (`StorageUnavailableError`, never an empty set on failure), and is covered by the shared
  durable contract on all four backends.
- **G2** — `ConversationBackend.is_deleted(..., turn_id)` is documented and contract-tested as "the session
  OR that turn is tombstoned"; DynamoDB answers it in one `BatchGetItem` round trip instead of two `GetItem`s.
- **G3** — `list_user_conversations` makes ONE `deleted_session_ids` call per distinct agent per window
  (no per-thread `is_deleted`) and returns up to `limit` LIVE threads: `limit` is applied after hiding
  tombstoned threads. Order, the `since` filter and fail-closed behaviour are unchanged.
- **G4** — `_fence_after_write` makes ONE tombstone read on the live path; the second read happens only when
  the first one reports a deletion (to choose session cleanup vs. turn cleanup).
- **G5** — The storage wiki pages describe both batched reads and the `is_deleted` semantics.

### Non-Goals (explicitly out of scope)

- Moving the deletion filter INTO `query_threads` (backend-side exclusion). Rejected: it changes the
  semantics of the only thread-listing primitive for every caller, moves the G7 guard out of ChatStorage,
  and would turn the raw `query_threads` probes in the subscriber tests into tautologies.
- Caching "not deleted" verdicts (rejected in PR #2123: every process would have to hear about deletes, and
  the delete event is not the deletion authority).
- DynamoDB `query_threads` ordering by sort key (`THREAD#<session_id>`) instead of `updated_at`, and every
  backend's `query_threads` returning `[]` when disconnected / on a DynamoDB `ClientError`. Pre-existing,
  tracked as a separate ledger issue discovered from this spec.

---

## Governing Decisions

<!-- decision-audit: input_digest=sha256:c537e36fa1b6820ee77cd5a4e3801c469e6a2cde4d7262225915cb14dd2e0a8e evaluation_digest=sha256:41d0630df8533d4bb0dfbf18b0968f71cc2f0b7c6d74b0dc5959cbdad27be774 rules_version=1 status=pass -->

## 2. Architectural Design

### Overview

One new abstract read on the backend contract, used by ChatStorage in place of the per-thread fan-out:

```
list_user_conversations(user, agent?, limit, since?)
  window = limit
  loop:
    threads = query_threads(user, agent, window)            # newest first (updated_at DESC)
    apply since
    for each distinct thread agent (thread["agent_id"] or agent):
        gone |= deleted_session_ids(user, that_agent, [sessions not yet checked])   # ONE read per agent
    live = [t for t in threads if (agent, session) not in gone]
    stop when: len(live) >= limit
            or len(threads) < window                         # backend exhausted
            or no thread in this window was tombstoned       # the shortfall is not ours to fix
            or since was given and a row in the window predates it   # cut-off reached (rows are newest first)
    window = max(limit + tombstoned_seen, 2 * window)        # geometric growth bounds the rounds
  return live[:limit]
```

Verdicts are cached by `(agent, session_id)` within one call, so a re-query never re-checks a thread.
A failed tombstone read raises (fail closed) exactly as today.

`_fence_after_write`:

```
if not is_deleted(user, agent, session, turn_id):   # session OR turn — ONE read on the live path
    return
session_gone = is_deleted(user, agent, session)     # only after a positive answer
...existing cleanup + ConversationDeletedError...
```

### Component Diagram

```
ChatStorage.list_user_conversations ──► ConversationBackend.query_threads
                                    └─► ConversationBackend.deleted_session_ids  (new, 1 per agent)
ChatStorage._fence_after_write ───────► ConversationBackend.is_deleted (turn form: session OR turn)
InstrumentedBackend.deleted_session_ids ──► inner backend (measured like every other call)
```

### Integration Points

| Existing component | Change |
|---|---|
| `parrot.storage.backends.base.ConversationBackend` | new abstract `deleted_session_ids`; `is_deleted` docstring states session-OR-turn |
| `ConversationSQLiteBackend` / `ConversationPostgresBackend` / `ConversationMongoBackend` | implement `deleted_session_ids` |
| `ConversationDynamoDB` | implement `deleted_session_ids` via `_batch_get`; `is_deleted(turn_id)` uses one `_batch_get` |
| `parrot.storage.instrumented.InstrumentedBackend` | measured passthrough |
| `parrot.storage.chat.ChatStorage` | `_sessions_deleted` batched per agent; listing applies `limit` after filtering; one-read fence |

### Data Models

None. No schema change: every backend already stores session tombstones as `turn_id = ''` (SQL, Mongo) or
`SK = TOMB#<session_id>` (DynamoDB).

### New Public Interfaces

```python
# parrot.storage.backends.base.ConversationBackend
@abstractmethod
async def deleted_session_ids(self, user_id: str, agent_id: str, session_ids: Sequence[str]) -> Set[str]:
    """The members of ``session_ids`` that carry a SESSION tombstone, in one bounded read.

    Turn tombstones are ignored. An empty ``session_ids`` returns ``set()`` without touching the store.

    Raises:
        StorageUnavailableError: If it cannot be determined — never returns an empty set on failure
            (also when the backend is disconnected).
    """
```

`ChatStorage.TOMBSTONE_LOOKUP_CONCURRENCY` (added by PR #2123) is removed: there is no per-thread fan-out left
to bound.

---

## 3. Module Breakdown

### Module 1: Backend contract — `deleted_session_ids` and session-or-turn `is_deleted`

- **Files**: `storage/backends/base.py`, `sqlite.py`, `postgres.py`, `mongodb.py`, `dynamodb.py`,
  `storage/instrumented.py`; tests `tests/storage/durable_contract.py`, `test_storage_errors.py`,
  `backends/test_base_abc.py`, `test_instrumented_backend.py`, `test_leaky_abstractions_repaired.py`.
- **Behaviour**:
  - SQLite: `... AND turn_id = '' AND session_id IN (?, ?, …)`, chunks of ≤ 500 ids (below SQLite's variable
    limit); errors → `StorageUnavailableError`; disconnected → `_require_connection()` raises.
  - Postgres: `... AND turn_id = '' AND session_id = ANY($3::text[])` in one query; errors via `_translate`.
  - Mongo: `find({"user_id", "agent_id", "session_id": {"$in": [...]}, "turn_id": ""})`, chunks of ≤ 1000;
    errors via `_translate`.
  - DynamoDB: keys `{PK, SK: TOMB#<session_id>}` deduplicated, chunks of ≤ 100, `_batch_get` (consistent,
    `UnprocessedKeys` retried, raises when keys stay unprocessed); `ClientError`/`BotoCoreError` →
    `StorageUnavailableError`. `is_deleted(turn_id=…)` fetches the session and turn tombstone keys in one
    `_batch_get`; `is_deleted()` without a turn keeps its single `GetItem`.
  - Every backend: an empty input returns `set()` without a read; duplicates in the input are harmless;
    only ids from the input are returned.
  - `InstrumentedBackend.deleted_session_ids` → `self._measure("deleted_session_ids", …)`.
  - Shared contract: new `check_deleted_session_ids` (session tombstones only — not turn tombstones, not
    another agent's, not another user's; empty input; ≥ 150 ids so DynamoDB crosses a 100-key chunk) and
    `check_is_deleted_turn_includes_session` (a session tombstone makes `is_deleted(…, any_turn)` True; a
    turn tombstone does not make the session deleted); `check_disconnected_raises` also covers
    `deleted_session_ids`. Both new checks are appended to `ALL_CHECKS`.
  - Test stubs: `_ReferenceBackend.is_deleted` answers session OR turn and implements `deleted_session_ids`;
    the stubs in `test_base_abc.py`, `test_instrumented_backend.py`, `test_leaky_abstractions_repaired.py`
    implement it; `deleted_session_ids` joins `EXPECTED_ABSTRACT_METHODS`, `NEW_ABSTRACT` and the
    instrumented-passthrough method list.

### Module 2: ChatStorage — batched listing guard, `limit` after filtering, one-read fence, docs

- **Files**: `storage/chat.py`; tests `tests/unit/storage/test_chat_storage_subscriber.py`,
  `tests/test_chat_storage.py`, `tests/docs/test_durable_memory_docs.py` (all under `packages/ai-parrot/`),
  and the repo-root `tests/storage/test_chat_storage_dynamodb.py` and
  `tests/storage/test_integration_artifact_persistence.py` (run by CI's `pytest tests/`); docs
  `wiki/stores/storage-backends.md`, `wiki/memory/durable-conversation-memory.md`.
- **Mocks**: the three `AsyncMock` backend fixtures (`test_chat_storage.py`, `test_chat_storage_dynamodb.py`,
  `test_integration_artifact_persistence.py`) declare `deleted_session_ids = AsyncMock(return_value=set())`
  next to their `is_deleted` mock. `_sessions_deleted` treats the result as an iterable of ids
  (`set(result)`), never relying on set-only operators.
- **Behaviour**: as in §2 Overview. `_sessions_deleted(user_id, keys)` keeps its signature and order-preserving
  `List[bool]` result, groups `keys` by agent, issues one `deleted_session_ids` per distinct agent
  (concurrently via `asyncio.gather(..., return_exceptions=True)`; the first failure is raised after every
  read settles), and returns `[False] * len(keys)` without a cold store. The two PR #2123 tests that pin the
  per-thread fan-out (`test_listing_checks_tombstones_concurrently_bounded_and_in_order`,
  `test_listing_fails_closed_when_one_tombstone_lookup_fails`) and the `_InFlightBackend` helper are replaced.
- **Docs**: the Tombstones bullet of `storage-backends.md` names `deleted_turn_ids` / `deleted_session_ids`
  and the session-or-turn meaning of `is_deleted(…, turn_id)`; the migration note of
  `durable-conversation-memory.md` lists `deleted_turn_ids` and `deleted_session_ids` among the methods a
  custom `ConversationBackend` must implement. `test_durable_memory_docs.METHODS` gains both names.

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `check_deleted_session_ids` (via each `test_*_durable_contract.py`) | M1 | returns exactly the session-tombstoned ids of the input; ignores turn tombstones, other agents/users and unknown ids; `[]` → `set()`; 150 ids with 3 tombstoned → exactly those 3 |
| `check_is_deleted_turn_includes_session` (same) | M1 | session tombstone ⇒ `is_deleted(u, a, s, "any")` is True; turn tombstone ⇏ `is_deleted(u, a, s)` |
| `check_disconnected_raises` (extended) | M1 | `deleted_session_ids` raises `StorageUnavailableError` when disconnected |
| `test_base_abc.py::test_abstract_methods_are_complete` | M1 | `deleted_session_ids` is abstract |
| `test_instrumented_backend.py` passthrough list | M1 | `deleted_session_ids` is measured and delegated |
| `test_storage_errors.py` | M1 | reference backend satisfies the new contract clauses |
| `test_listing_reads_session_tombstones_once_per_agent_and_keeps_order` | M2 | 20 threads, 3 tombstoned → 17 in order; 1 `deleted_session_ids`, 0 `is_deleted` |
| `test_listing_returns_limit_live_threads_when_tombstoned_ones_fill_the_window` | M2 | 10 threads, the 3 newest tombstoned, `limit=5` → the 5 newest live threads |
| `test_listing_does_not_requery_past_the_since_cutoff` | M2 | window reaches `since` → one `query_threads` call even with a tombstoned thread in it |
| `test_listing_groups_tombstone_reads_by_agent` | M2 | threads of two payload agents → exactly 2 `deleted_session_ids` calls |
| `test_listing_fails_closed_when_the_batched_tombstone_read_fails` | M2 | `deleted_session_ids` raises → `StorageUnavailableError` |
| `test_fence_makes_one_tombstone_read_on_a_live_session` | M2 | `_fence_after_write` on a live turn → exactly one `is_deleted` call |
| `test_fence_still_cleans_up_session_and_turn_deletions` | M2 | session tombstone → session cleanup + `ConversationDeletedError`; turn tombstone → hot-turn cleanup + `ConversationDeletedError` |
| existing `test_chat_storage.py`, `test_durable_memory_docs.py` | M2 | still pass with the extended mock and method list |
| existing root `tests/storage/test_chat_storage_dynamodb.py`, `tests/storage/test_integration_artifact_persistence.py` | M2 | listing tests still pass with the extended mocks |

### Integration Tests

| Test | Description |
|---|---|
| — | none; the shared durable contract runs on real SQLite always, on Postgres / Mongo with `POSTGRES_TEST_DSN` / `MONGO_TEST_DSN`, and on DynamoDB with `moto[server]` |

### Validation Contract

tests:
- packages/ai-parrot/tests/storage/backends/test_sqlite_durable_contract.py
- packages/ai-parrot/tests/storage/backends/test_postgres_durable_contract.py
- packages/ai-parrot/tests/storage/backends/test_mongo_durable_contract.py
- packages/ai-parrot/tests/storage/backends/test_dynamodb_durable_contract.py
- packages/ai-parrot/tests/storage/backends/test_base_abc.py
- packages/ai-parrot/tests/storage/test_storage_errors.py
- packages/ai-parrot/tests/storage/test_instrumented_backend.py
- packages/ai-parrot/tests/storage/test_leaky_abstractions_repaired.py
- packages/ai-parrot/tests/unit/storage/test_chat_storage_subscriber.py
- packages/ai-parrot/tests/test_chat_storage.py
- packages/ai-parrot/tests/docs/test_durable_memory_docs.py
- tests/storage/test_chat_storage_dynamodb.py
- tests/storage/test_integration_artifact_persistence.py
markers: none

### Test Data / Fixtures

No new fixtures. The durable contract uses each backend's existing `DurableHarness`; the ChatStorage tests use
the real SQLite `cold` fixture and the existing `_CountingBackend` wrapper of
`test_chat_storage_subscriber.py`.

---

## 5. Acceptance Criteria

- [ ] `ConversationBackend.deleted_session_ids` is abstract and implemented by SQLite, Postgres, Mongo, DynamoDB
      and `InstrumentedBackend`; it never returns an empty set for a failed or disconnected read.
- [ ] `ConversationBackend.is_deleted`'s docstring states the session-OR-turn semantics, and the shared contract
      asserts it on all four backends.
- [ ] Listing N threads of one agent costs one `query_threads` + one `deleted_session_ids` call (no
      `is_deleted`) when no tombstoned thread forces a re-query.
- [ ] A listing returns `limit` live threads whenever at least `limit` live threads exist, even if tombstoned
      threads are newer.
- [ ] `_fence_after_write` makes exactly one tombstone read for a live session.
- [ ] Every Validation Contract file passes from the worktree with `PYTHONPATH=packages/ai-parrot/src`
      (Postgres / Mongo / DynamoDB contract modules may skip only for a missing DSN / `moto[server]`).
- [ ] `ruff check` passes on the changed Python files; changed lines add no new `black --check` (line length
      120) differences.
- [ ] `parrot sdd techwiki check` passes for the two pages in §10.

---

## 6. Codebase Contract

### Verified Imports

```python
from parrot.storage.backends.base import ConversationBackend        # base.py:25
from parrot.storage.errors import StorageUnavailableError, ConversationDeletedError
from parrot.storage.instrumented import InstrumentedBackend          # instrumented.py:17
from parrot.storage.chat import ChatStorage                          # chat.py:37
```

### Existing Class Signatures

```python
# packages/ai-parrot/src/parrot/storage/backends/base.py
async def deleted_turn_ids(self, user_id: str, agent_id: str, session_id: str) -> Set[str]   # :186
async def is_deleted(self, user_id, agent_id, session_id, turn_id: Optional[str] = None) -> bool  # :194
async def query_threads(self, user_id: str, agent_id: str, limit: int = 50) -> List[dict]  # :79

# packages/ai-parrot/src/parrot/storage/backends/dynamodb.py
def _sk_tomb(session_id: str, turn_id: Optional[str] = None) -> str        # :207 staticmethod
def _build_pk(...) -> str                                                   # "USER#<u>#AGENT#<a>"
async def _get_item(self, pk: str, sk: str) -> Optional[dict]               # :226
async def _batch_get(self, keys: List[dict]) -> Dict[str, dict]             # :642 consistent, retries
                                                                            #   UnprocessedKeys, maps SK -> item;
                                                                            #   callers chunk to <= 100 keys

# packages/ai-parrot/src/parrot/storage/chat.py
class ChatStorage:                                                          # :37
    TOMBSTONE_LOOKUP_CONCURRENCY = 8                                        # :43 (removed by this spec)
    async def _fence_after_write(self, turn: ChatStorageTurn) -> None       # :220
    async def list_user_conversations(self, user_id, agent_id=None, limit=DEFAULT_LIST_LIMIT, since=None)  # :385
    async def _sessions_deleted(self, user_id: str, keys: List[Tuple[str, str]]) -> List[bool]  # :561
```

Typing imports: `base.py:13` has `List, Optional, Set, Tuple` (add `Sequence`); `sqlite.py:24`,
`postgres.py:20`, `mongodb.py:16`, `dynamodb.py:16` have `Set` (add `Sequence`); `instrumented.py:11` has
`List, Optional`.

### Integration Points

- The SQL backends store a session tombstone as `turn_id = ''` (`sqlite.py:111`, `postgres.py:127`); Mongo as
  `turn_id: ""` (`mongodb.py:211`); DynamoDB as `SK = TOMB#<session_id>` with a `session_id` attribute
  (`put_tombstone`).
- `query_threads` is called only by `ChatStorage.list_user_conversations` in source; SQLite / Postgres / Mongo
  order by `updated_at DESC`.

### Does NOT Exist (Anti-Hallucination)

- `ConversationBackend.deleted_session_ids` — created by this spec.
- `ConversationBackend.is_session_deleted`, `ConversationBackend.batch_is_deleted` — do not exist; do not add.
- A cursor / offset argument on `query_threads` — does not exist; re-query with a larger `limit`.
- `moto` is not installed in the shared venv; never `uv add` / `uv pip install` it there.

### Edit Sites (Blueprint Anchors)

Verified against: `4cfa863e10`

| File | Action | Verbatim anchor line | Verified at | Occurrences |
|---|---|---|---|---|
| `packages/ai-parrot/src/parrot/storage/backends/base.py` | MODIFY | `from typing import List, Optional, Set, Tuple` | `base.py:13` | 1 |
| `packages/ai-parrot/src/parrot/storage/backends/base.py` | MODIFY | `    async def deleted_turn_ids(self, user_id: str, agent_id: str, session_id: str) -> Set[str]:` | `base.py:186` | 1 |
| `packages/ai-parrot/src/parrot/storage/backends/base.py` | MODIFY | `    async def is_deleted(` | `base.py:194` | 1 |
| `packages/ai-parrot/src/parrot/storage/backends/sqlite.py` | MODIFY | `    async def is_deleted(` | `sqlite.py:734` | 1 |
| `packages/ai-parrot/src/parrot/storage/backends/postgres.py` | MODIFY | `    async def is_deleted(` | `postgres.py:601` | 1 |
| `packages/ai-parrot/src/parrot/storage/backends/mongodb.py` | MODIFY | `    async def is_deleted(` | `mongodb.py:490` | 1 |
| `packages/ai-parrot/src/parrot/storage/backends/dynamodb.py` | MODIFY | `    async def is_deleted(` | `dynamodb.py:714` | 1 |
| `packages/ai-parrot/src/parrot/storage/instrumented.py` | MODIFY | `    async def is_deleted(self, *a, **kw) -> bool:` | `instrumented.py:110` | 1 |
| `packages/ai-parrot/src/parrot/storage/chat.py` | MODIFY | `    TOMBSTONE_LOOKUP_CONCURRENCY = 8` | `chat.py:43` | 1 |
| `packages/ai-parrot/src/parrot/storage/chat.py` | MODIFY | `    async def _fence_after_write(self, turn: ChatStorageTurn) -> None:` | `chat.py:220` | 1 |
| `packages/ai-parrot/src/parrot/storage/chat.py` | MODIFY | `            threads = await self._dynamo.query_threads(` | `chat.py:401` | 1 |
| `packages/ai-parrot/src/parrot/storage/chat.py` | MODIFY | `    async def _sessions_deleted(self, user_id: str, keys: List[Tuple[str, str]]) -> List[bool]:` | `chat.py:561` | 1 |
| `packages/ai-parrot/tests/storage/durable_contract.py` | MODIFY | `        await b.is_deleted(USER, AGENT, "s-disc")` | `durable_contract.py:74` | 1 |
| `packages/ai-parrot/tests/storage/durable_contract.py` | MODIFY | `async def check_deleted_turn_ids(h: DurableHarness) -> None:` | `durable_contract.py:200` | 1 |
| `packages/ai-parrot/tests/storage/durable_contract.py` | MODIFY | `    check_deleted_turn_ids,` | `durable_contract.py:226` | 1 |
| `packages/ai-parrot/tests/storage/test_storage_errors.py` | MODIFY | `NEW_ABSTRACT = {` | `test_storage_errors.py:26` | 1 |
| `packages/ai-parrot/tests/storage/test_storage_errors.py` | MODIFY | `        return (user_id, agent_id, session_id, turn_id) in self.tombs` | `test_storage_errors.py:147` | 1 |
| `packages/ai-parrot/tests/storage/backends/test_base_abc.py` | MODIFY | `"query_turn_window", "max_sequence", "put_tombstone", "is_deleted",` | `test_base_abc.py:16` | 1 |
| `packages/ai-parrot/tests/storage/backends/test_base_abc.py` | MODIFY | `        async def is_deleted(self, *a, **kw): return False` | `test_base_abc.py:59` | 2 |
| `packages/ai-parrot/tests/storage/test_instrumented_backend.py` | MODIFY | `    async def is_deleted(self, *a, **kw): raise RuntimeError("guard-boom")` | `test_instrumented_backend.py:49` | 1 |
| `packages/ai-parrot/tests/storage/test_instrumented_backend.py` | MODIFY | `"backfill_batch", "put_tombstone", "is_deleted",` | `test_instrumented_backend.py:131` | 1 |
| `packages/ai-parrot/tests/storage/test_leaky_abstractions_repaired.py` | MODIFY | `    async def is_deleted(self, *a, **kw): return False` | `test_leaky_abstractions_repaired.py:58` | 1 |
| `packages/ai-parrot/tests/unit/storage/test_chat_storage_subscriber.py` | MODIFY | `class _InFlightBackend(_CountingBackend):` | `test_chat_storage_subscriber.py:439` | 1 |
| `packages/ai-parrot/tests/unit/storage/test_chat_storage_subscriber.py` | MODIFY | `async def test_listing_checks_tombstones_concurrently_bounded_and_in_order(cold):` | `test_chat_storage_subscriber.py:469` | 1 |
| `packages/ai-parrot/tests/unit/storage/test_chat_storage_subscriber.py` | MODIFY | `async def test_listing_fails_closed_when_one_tombstone_lookup_fails(cold, monkeypatch):` | `test_chat_storage_subscriber.py:484` | 1 |
| `packages/ai-parrot/tests/test_chat_storage.py` | MODIFY | `    dynamo.is_deleted = AsyncMock(return_value=False)` | `test_chat_storage.py:60` | 1 |
| `packages/ai-parrot/tests/docs/test_durable_memory_docs.py` | MODIFY | `"is_deleted", "get_index_state", "backfill_batch"],` | `test_durable_memory_docs.py:40` | 1 |
| `tests/storage/test_chat_storage_dynamodb.py` | MODIFY | `    dynamo.is_deleted = AsyncMock(return_value=False)` | `test_chat_storage_dynamodb.py:31` | 1 |
| `tests/storage/test_integration_artifact_persistence.py` | MODIFY | `    backend.is_deleted = AsyncMock(return_value=False)` | `test_integration_artifact_persistence.py:60` | 1 |
| `wiki/stores/storage-backends.md` | MODIFY | `` - **Tombstones.** `put_tombstone` / `is_deleted` record session- and turn-scoped deletions durably, outside `` | `storage-backends.md:228` | 1 |
| `wiki/memory/durable-conversation-memory.md` | MODIFY | `` `StorageWriteError`) instead of returning silently. Custom `ConversationBackend` subclasses must implement `` | `durable-conversation-memory.md:182` | 1 |

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- Follow `deleted_turn_ids` (commit `2411081ac6`) for each backend: same scoping, same error translation,
  same "never an empty set on failure" rule.
- DynamoDB: reuse `_batch_get`; chunk like `_load_turns` (≤ 100 keys per request).
- `black` line length 120; Google-style docstrings; strict type hints; `self.logger`, never `print`.

### Known Risks / Gotchas

- In a worktree the shared venv imports the main checkout: run pytest with `PYTHONPATH=packages/ai-parrot/src`.
- `moto` is not in the shared venv. Run the DynamoDB contract through an ephemeral overlay
  (`uv run --no-sync --with 'moto[server]' pytest …`) — never install into the shared venv.
- The re-query loop relies on `query_threads` returning newest first; SQLite / Postgres / Mongo do. DynamoDB
  orders by sort key (pre-existing, out of scope); the loop still terminates there (window growth + exhaustion)
  and is never worse than today.
- `since` compares the payload's ISO `updated_at`; SQLite orders by its insertion-time column. Tests must seed
  the two in the same order.
- `test_durable_memory_docs.py` rejects pages containing `TODO`, `TASK-` or the word "worktree".

### External Dependencies

None.

---

## Decisions

```yaml
schema_version: 1
document_id: backends-base-tech-debt
entries:
  - id: is-deleted-turn-form-includes-session
    statement: ConversationBackend.is_deleted called with a turn_id answers whether the session OR that turn is tombstoned, on every backend.
    relation: constrains
    about: [memory]
    targets: ["sym:packages/ai-parrot/src/parrot/storage/backends/base.py#ConversationBackend.is_deleted"]
    contradicts: []
    supersedes: []
    rationale: All four backends already behave this way; writing it into the contract lets ChatStorage fence a write with one read.
    rejected_alternatives: ["turn-only semantics (forces two reads per stored turn)"]
  - id: listing-guard-stays-in-chatstorage
    statement: ChatStorage hides session-tombstoned threads from a listing with one batched deleted_session_ids read per agent and applies limit after hiding them; query_threads stays unfiltered.
    relation: constrains
    about: [memory]
    targets: ["sym:packages/ai-parrot/src/parrot/storage/chat.py#ChatStorage.list_user_conversations"]
    contradicts: []
    supersedes: []
    rationale: Keeps the G7 deletion guard in one owner and leaves the thread-listing primitive's semantics unchanged for every caller.
    rejected_alternatives: ["backend-side exclusion inside query_threads", "per-thread is_deleted fan-out"]
```

## Consequences

<!-- decision-audit: input_digest=sha256:c537e36fa1b6820ee77cd5a4e3801c469e6a2cde4d7262225915cb14dd2e0a8e evaluation_digest=sha256:41d0630df8533d4bb0dfbf18b0968f71cc2f0b7c6d74b0dc5959cbdad27be774 rules_version=1 status=pass -->

Audit status: `pass` (exit 0)

Findings:
- `blast-radius` [advisory]; waived_by: not recorded; participants: adr:spec:backends-base-tech-debt#is-deleted-turn-form-includes-session@1; scope: sym:packages/ai-parrot/src/parrot/storage/backends/base.py#ConversationBackend.is_deleted; message: sym:packages/ai-parrot/src/parrot/storage/backends/base.py#ConversationBackend.is_deleted impacts 3 dependent(s): sym:packages/ai-parrot/tests/storage/durable_contract.py#check_disconnected_raises, sym:packages/ai-parrot/tests/storage/durable_contract.py#check_tombstone_blocks_put, sym:packages/ai-parrot/tests/storage/durable_contract.py#check_tombstone_survives_cleanup
- `blast-radius` [advisory]; waived_by: not recorded; participants: adr:spec:backends-base-tech-debt#listing-guard-stays-in-chatstorage@1; scope: sym:packages/ai-parrot/src/parrot/storage/chat.py#ChatStorage.list_user_conversations; message: sym:packages/ai-parrot/src/parrot/storage/chat.py#ChatStorage.list_user_conversations impacts 9 dependent(s): sym:packages/ai-parrot/tests/test_chat_storage.py#TestChatStorageListConversations.test_list_empty, sym:packages/ai-parrot/tests/unit/storage/test_chat_storage_subscriber.py#test_listing_checks_tombstones_concurrently_bounded_and_in_order, sym:packages/ai-parrot/tests/unit/storage/test_chat_storage_subscriber.py#test_listing_fails_closed_when_one_tombstone_lookup_fails, sym:packages/ai-parrot/tests/unit/storage/test_chat_storage_subscriber.py#test_reads_between_tombstone_and_cleanup_refuse_the_conversation, sym:packages/ai-parrot/tests/unit/storage/test_chat_storage_subscriber.py#test_storage_errors_on_reads_are_raised_not_emptied, sym:tests/storage/test_chat_storage_dynamodb.py#TestListUserConversations.test_empty_when_no_dynamo, sym:tests/storage/test_chat_storage_dynamodb.py#TestListUserConversations.test_returns_thread_metadata, sym:tests/storage/test_integration_artifact_persistence.py#TestConversationLifecycle.test_list_conversations, sym:tests/storage/test_integration_artifact_persistence.py#TestGracefulDegradation.test_no_dynamo_list_returns_empty

Diagnostics:
- none

Coverage:
- Subsystems: bots, clients, config, flows, knowledge-graphindex, knowledge-pageindex, knowledge-wiki, memory, skills, tools
- Unmapped tags: durable-conversation-memory, ledger-fix, storage, tombstones
- Targets resolved: 2/2
- Impact complete: true
- Inventory complete: true
- Omitted ids: not recorded

```json
{
  "coverage": {
    "impact_complete": true,
    "inventory_complete": true,
    "omitted_ids": [],
    "subsystems": [
      "bots",
      "clients",
      "config",
      "flows",
      "knowledge-graphindex",
      "knowledge-pageindex",
      "knowledge-wiki",
      "memory",
      "skills",
      "tools"
    ],
    "targets_resolved": 2,
    "targets_total": 2,
    "unmapped_tags": [
      "durable-conversation-memory",
      "ledger-fix",
      "storage",
      "tombstones"
    ]
  },
  "diagnostics": [],
  "evaluation_digest": "sha256:41d0630df8533d4bb0dfbf18b0968f71cc2f0b7c6d74b0dc5959cbdad27be774",
  "exit_code": 0,
  "findings": [
    {
      "blocking": false,
      "fingerprint": "sha256:ed9477001c4e0b68698783fbf3aa4fc5f3728ace98a4efd9b314d76b46f6fe12",
      "kind": "blast-radius",
      "message": "sym:packages/ai-parrot/src/parrot/storage/backends/base.py#ConversationBackend.is_deleted impacts 3 dependent(s): sym:packages/ai-parrot/tests/storage/durable_contract.py#check_disconnected_raises, sym:packages/ai-parrot/tests/storage/durable_contract.py#check_tombstone_blocks_put, sym:packages/ai-parrot/tests/storage/durable_contract.py#check_tombstone_survives_cleanup",
      "participants": [
        {
          "decision_id": "adr:spec:backends-base-tech-debt#is-deleted-turn-form-includes-session",
          "revision": 1
        }
      ],
      "rule_version": 1,
      "scope": [
        "sym:packages/ai-parrot/src/parrot/storage/backends/base.py#ConversationBackend.is_deleted"
      ],
      "waived_by": null
    },
    {
      "blocking": false,
      "fingerprint": "sha256:fe1bd05c044a66df3b0ba3303432e94088d0f667fe69d7df434056e2bb4f832d",
      "kind": "blast-radius",
      "message": "sym:packages/ai-parrot/src/parrot/storage/chat.py#ChatStorage.list_user_conversations impacts 9 dependent(s): sym:packages/ai-parrot/tests/test_chat_storage.py#TestChatStorageListConversations.test_list_empty, sym:packages/ai-parrot/tests/unit/storage/test_chat_storage_subscriber.py#test_listing_checks_tombstones_concurrently_bounded_and_in_order, sym:packages/ai-parrot/tests/unit/storage/test_chat_storage_subscriber.py#test_listing_fails_closed_when_one_tombstone_lookup_fails, sym:packages/ai-parrot/tests/unit/storage/test_chat_storage_subscriber.py#test_reads_between_tombstone_and_cleanup_refuse_the_conversation, sym:packages/ai-parrot/tests/unit/storage/test_chat_storage_subscriber.py#test_storage_errors_on_reads_are_raised_not_emptied, sym:tests/storage/test_chat_storage_dynamodb.py#TestListUserConversations.test_empty_when_no_dynamo, sym:tests/storage/test_chat_storage_dynamodb.py#TestListUserConversations.test_returns_thread_metadata, sym:tests/storage/test_integration_artifact_persistence.py#TestConversationLifecycle.test_list_conversations, sym:tests/storage/test_integration_artifact_persistence.py#TestGracefulDegradation.test_no_dynamo_list_returns_empty",
      "participants": [
        {
          "decision_id": "adr:spec:backends-base-tech-debt#listing-guard-stays-in-chatstorage",
          "revision": 1
        }
      ],
      "rule_version": 1,
      "scope": [
        "sym:packages/ai-parrot/src/parrot/storage/chat.py#ChatStorage.list_user_conversations"
      ],
      "waived_by": null
    }
  ],
  "input_digest": "sha256:c537e36fa1b6820ee77cd5a4e3801c469e6a2cde4d7262225915cb14dd2e0a8e",
  "snapshot": {
    "approvals_digest": "6e5b5a5fb07d04ec7e7cdbf3afac1a634711ea195aa4061a8261bcf61b19992f",
    "config_digest": "sha256:a6bce9c0800713c30eaa78146ad0c06399f6ec0e9b083129e494abb6fd073343",
    "inventory": {
      "adr:doc:171b17ccd26bdbd2d71040746b22371a335d364d": "b22c79daae2a187f2091ea23449825e8769e2c07",
      "adr:doc:34394c36f5bf140678b8e17d43c3628e3d2c1440": "3fa15352d0e9ed972bd5de7ac1fd60e06906e60b",
      "adr:doc:666d8f740c695673063f76777db7b7b0e9d95a2e": "47f1bebe56724843f6c0981f67bbba72917b4b0b",
      "adr:doc:87781d348dff80cbfb25c253989a8940badd08d1": "49458f64f4bb614a9ff42750b53d9caa806f81a0",
      "adr:doc:89e808b78adee5c727e047ac239817bfd29e5cfe": "9feeb90ec52cb53395d978a3b946323a7b9072ab",
      "adr:doc:96dabb33251cd210186d7ab5c456ded102a4b025": "b537050f62f77a85b651af8c2595f4dc7fd4cebe",
      "adr:doc:c3c29b415ba46e730ee37c6fc520914a1905d022": "0cd9cc9f082b9d988da023e3886d310f8eed8eae",
      "adr:doc:c6b0e17a26d4b1ae2be8569a33db9a3aeedc0fbd": "804496ec336c99570df5502580ff980a38f56bfc",
      "adr:doc:e7c5ae770b06db3b35cdd4cba93001a58bfa7bef": "394f4656c71618a256427d81350fdc32335fa791"
    },
    "rules_version": 1,
    "structural_revision": "sha256:d4ea9ca0f9a0a7ebba15913cd014dec4fc44c42be4cabc0d746d0b6c671d9947",
    "taxonomy_digest": "65548b9a71329b13ab44f4904dff99814e1aac0da4bb2b58171a7201e3a9ba39"
  },
  "status": "pass"
}
```

## 8. Open Questions

- [x] Q1. Batched read in ChatStorage vs. exclusion inside `query_threads`? — *Resolved (/sdd-fix)*: batched
  read; see Non-Goals and decision `listing-guard-stays-in-chatstorage`.
- [x] Q2. Reuse FEAT-886? — *Resolved (/sdd-fix plan)*: new feature; FEAT-886 is completed (`open: false`).

---

## 9. Design Research Cross-Check

> Model: — · Status: skipped (no accepted exploration document; spec authored by /sdd-fix from a ledger issue)

| # | Suggestion (kind) | Disposition | Reason | Landed in |
|---|---|---|---|---|

Summary: **0** confirmed · **0** rejected · **0** escalated.

---

## 10. Documentation

- **Policy**: `required` — the backend contract gains a method custom backends must implement.
- **Pages**:
  - `wiki/stores/storage-backends.md` — update: Tombstones bullet (batched reads, `is_deleted` semantics)
  - `wiki/memory/durable-conversation-memory.md` — update: migration note (methods a custom backend implements)
- **API modules**: `parrot.storage.backends.base` (docstrings of `deleted_session_ids` and `is_deleted`).

---

## Worktree Strategy

One feature worktree `feat-FEAT-897-backends-base-tech-debt` off `origin/dev`; two sequential tasks.

- Module graph: M1 → M2 (M2 calls the method M1 adds).
- Shared files: none between the modules.
- Exclusive resources: none.
- Cross-feature: FEAT-892 (agent-memory-mixin) refers to the FEAT-886 delete contract but none of its tasks
  edits `storage/chat.py` or `storage/backends/` (checked against `origin/dev` at `4cfa863e10`).

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-11-14 | Jesus Lara | Created by /sdd-fix from `issue:6393789b3d37` (fixgroup:e3c400582081) |
