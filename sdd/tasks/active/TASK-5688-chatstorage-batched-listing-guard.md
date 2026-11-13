# TASK-5688: ChatStorage — batched listing guard, `limit` after filtering, one-read fence, docs

**Feature**: FEAT-897 — batched session-tombstone read for conversation listing
**Spec**: `sdd/specs/backends-base-tech-debt.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-5687
**Assigned-to**: unassigned
**Discovered-from**: `issue:6393789b3d37`

---

## Context

With `deleted_session_ids` on the contract and `is_deleted(…, turn_id)` defined as session-OR-turn (TASK-5687),
ChatStorage can drop its per-thread tombstone fan-out, return `limit` LIVE threads per page, and fence a stored
turn with one read (spec §1 items 1-3, §2 Overview). The storage wiki pages document the contract change.

---

## Scope

- `chat.py`:
  - Remove `TOMBSTONE_LOOKUP_CONCURRENCY`.
  - `_sessions_deleted(user_id, keys)`: same signature and order-preserving `List[bool]` result; groups `keys`
    by agent; one `deleted_session_ids(user_id, agent, [unique sessions of that agent])` per distinct agent,
    run with `asyncio.gather(..., return_exceptions=True)`; raises the first failure after every read settles;
    `[False] * len(keys)` without a cold store; empty `keys` → `[]` without a read; treats each result as an
    iterable of ids (`set(result)`).
  - `list_user_conversations`: the re-query loop of spec §2 Overview (window starts at `limit`; stop when
    `limit` live rows, backend exhausted, no tombstoned row in the window, or the `since` cutoff is reached;
    next window `max(limit + tombstoned_seen, 2 * window)`; verdicts cached by `(agent, session_id)` within
    the call; result order = backend order; internal fields stripped as today). Exceptions handled as today.
  - `_fence_after_write`: one `is_deleted(*key, turn.turn_id)`; return when False; otherwise
    `session_gone = is_deleted(*key)` and the existing cleanup / retry / `ConversationDeletedError` path.
- `tests/unit/storage/test_chat_storage_subscriber.py`: replace `_InFlightBackend`,
  `test_listing_checks_tombstones_concurrently_bounded_and_in_order` and
  `test_listing_fails_closed_when_one_tombstone_lookup_fails` with the M2 tests of spec §4.
- `AsyncMock` backend fixtures in `packages/ai-parrot/tests/test_chat_storage.py`,
  `tests/storage/test_chat_storage_dynamodb.py`, `tests/storage/test_integration_artifact_persistence.py`:
  add `deleted_session_ids = AsyncMock(return_value=set())` next to the `is_deleted` mock.
- Docs: `wiki/stores/storage-backends.md` Tombstones bullet; `wiki/memory/durable-conversation-memory.md`
  migration note; `test_durable_memory_docs.METHODS` gains `deleted_turn_ids` and `deleted_session_ids` for
  `ConversationBackend`.

**NOT in scope**: backend code (TASK-5687); `query_threads` semantics; `_ensure_not_deleted`; caching verdicts
across calls; other read paths.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/storage/chat.py` | MODIFY | batched guard, limit after filtering, one-read fence |
| `packages/ai-parrot/tests/unit/storage/test_chat_storage_subscriber.py` | MODIFY | replace two fan-out tests, add M2 tests |
| `packages/ai-parrot/tests/test_chat_storage.py` | MODIFY | mock `deleted_session_ids` |
| `packages/ai-parrot/tests/docs/test_durable_memory_docs.py` | MODIFY | `METHODS` |
| `tests/storage/test_chat_storage_dynamodb.py` | MODIFY | mock `deleted_session_ids` |
| `tests/storage/test_integration_artifact_persistence.py` | MODIFY | mock `deleted_session_ids` |
| `wiki/stores/storage-backends.md` | MODIFY | Tombstones bullet |
| `wiki/memory/durable-conversation-memory.md` | MODIFY | migration note |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from parrot.storage.chat import ChatStorage                        # chat.py:37
from parrot.storage.errors import ConversationDeletedError, StorageUnavailableError, StorageError
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/storage/chat.py
DEFAULT_LIST_LIMIT = 50                                                     # :33
class ChatStorage:
    TOMBSTONE_LOOKUP_CONCURRENCY = 8                                        # :43 (remove)
    async def _fence_after_write(self, turn: ChatStorageTurn) -> None       # :220
    async def list_user_conversations(self, user_id, agent_id=None, limit=DEFAULT_LIST_LIMIT, since=None)  # :385
    async def _sessions_deleted(self, user_id: str, keys: List[Tuple[str, str]]) -> List[bool]  # :561
    async def _cleanup_conversation(self, user_id, agent_id, session_id) -> Tuple[..., List[Exception]]
    async def _delete_hot_turn(self, user_id, session_id, turn_id, agent_id) -> ...
    def _schedule_cleanup_retry(self, user_id, agent_id, session_id, turn_id=None) -> None
# listing strips ("PK", "SK", "type", "ttl"); keys are (t.get("agent_id") or agent, t.get("session_id", ""))

# ConversationBackend (after TASK-5687)
async def deleted_session_ids(self, user_id: str, agent_id: str, session_ids: Sequence[str]) -> Set[str]
async def query_threads(self, user_id: str, agent_id: str, limit: int = 50) -> List[dict]  # newest first

# tests/unit/storage/test_chat_storage_subscriber.py
class _CountingBackend          # :376, records self.calls by method name
async def _seed_threads(cold, count: int) -> None   # threads s00..s{count-1}, agent bot1
# fixtures: cold (real SQLite ConversationSQLiteBackend), storage
```

### Does NOT Exist

- `ChatStorage.TOMBSTONE_LOOKUP_CONCURRENCY` after this task.
- An offset / cursor argument on `query_threads`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/storage/chat.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/unit/storage/test_chat_storage_subscriber.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/test_chat_storage.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/docs/test_durable_memory_docs.py", "action": "MODIFY"},
    {"path": "tests/storage/test_chat_storage_dynamodb.py", "action": "MODIFY"},
    {"path": "tests/storage/test_integration_artifact_persistence.py", "action": "MODIFY"},
    {"path": "wiki/stores/storage-backends.md", "action": "MODIFY"},
    {"path": "wiki/memory/durable-conversation-memory.md", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/storage/chat.py#ChatStorage.list_user_conversations",
    "sym:packages/ai-parrot/src/parrot/storage/chat.py#ChatStorage._fence_after_write",
    "sym:packages/ai-parrot/src/parrot/storage/chat.py#ChatStorage._sessions_deleted"
  ]
}
```

---

## Implementation Notes

### Key Constraints

- Fail closed: a failed tombstone read raises (`StorageError` unchanged, anything else →
  `StorageUnavailableError`), never an empty or partial listing.
- No verdict cache across calls.
- Wiki text must not contain `TODO`, `TASK-` or the word "worktree" (`test_durable_memory_docs.py`).
- In SQLite tests, seed thread payload `updated_at` (ISO) in insertion order: SQLite orders by an insertion-time
  column, `since` compares the payload value.

### References in Codebase

- `ChatStorage._load_cold` (legacy fallback: `limit + len(gone)`, filter, then `[:limit]`) — same intent.

---

## Implementation Blueprint

### Steps (in order)

1. `_sessions_deleted`, then the listing loop, then the fence.
2. Mocks and the subscriber tests.
3. Wiki pages and `test_durable_memory_docs.METHODS`.
4. Run the Validation Commands; `ruff check` the changed Python files.

### FILL IN checklist
- [ ] Listing loop — bounded by spec §2 Overview.
- [ ] Tests — spec §4 Unit Tests (M2 rows).

---

## Acceptance Criteria

- [ ] Listing one agent's threads makes one `query_threads` and one `deleted_session_ids` call and no
      `is_deleted` call when no re-query is needed.
- [ ] A listing returns `limit` live threads whenever at least `limit` exist, newest tombstoned ones included.
- [ ] `_fence_after_write` makes exactly one `is_deleted` call on a live session.
- [ ] `parrot sdd techwiki check` passes for the two wiki pages.
- [ ] `ruff check` passes on the changed Python files.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/unit/storage/test_chat_storage_subscriber.py packages/ai-parrot/tests/test_chat_storage.py packages/ai-parrot/tests/docs/test_durable_memory_docs.py tests/storage/test_chat_storage_dynamodb.py tests/storage/test_integration_artifact_persistence.py -q`

---

## Test Specification

See spec §4 Unit Tests (M2 rows).

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`parrot sdd worktree ensure --slug backends-base-tech-debt --feature-id FEAT-897`)
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — TASK-5687 must be `done`
4. **Verify the Codebase Contract** before writing any code
5. **Update status** in `sdd/tasks/index/backends-base-tech-debt.json` → `"in-progress"` (set `started_at`) and commit only that index file
6. **Implement** from the Implementation Blueprint
7. **Verify** all acceptance criteria — run the Validation Commands with `PYTHONPATH=packages/ai-parrot/src`
8. **Commit the code** — stage only the files listed above
9. **Close the task** with `parrot sdd task close TASK-5688 backends-base-tech-debt verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:
**Resolves**:
**Deviations from spec**:
