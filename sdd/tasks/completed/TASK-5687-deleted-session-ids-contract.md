# TASK-5687: Backend contract — batched `deleted_session_ids` and session-or-turn `is_deleted`

**Feature**: FEAT-897 — batched session-tombstone read for conversation listing
**Spec**: `sdd/specs/backends-base-tech-debt.spec.md`
**Status**: done
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned
**Discovered-from**: `issue:6393789b3d37`

---

## Context

`ConversationBackend` has a batched TURN-tombstone read (`deleted_turn_ids`) but no batched SESSION-tombstone
read, so `ChatStorage.list_user_conversations` pays one `is_deleted` per listed thread (spec §1 item 1). And
`is_deleted(…, turn_id)` already answers "session OR turn" on all four backends without the contract saying so,
so `_fence_after_write` cannot rely on it (spec §1 item 3). This task adds the batched read to the contract and
every implementer, writes the `is_deleted` semantics down, and covers both in the shared durable contract.
TASK-5688 then uses them in ChatStorage.

---

## Scope

- `base.py`: add `Sequence` to the typing import; new abstract `deleted_session_ids(user_id, agent_id,
  session_ids: Sequence[str]) -> Set[str]` right after `deleted_turn_ids` (docstring per spec §2 "New Public
  Interfaces"); `is_deleted` docstring states: without `turn_id` → session tombstoned; with `turn_id` → the
  session OR that turn is tombstoned.
- SQLite / Postgres / Mongo / DynamoDB: implement `deleted_session_ids` right after their `deleted_turn_ids`,
  exactly as spec §3 Module 1 "Behaviour" says (chunk sizes 500 / one query / 1000 / 100; empty input →
  `set()` without a read; `_require_connection()` first; errors translated like `deleted_turn_ids`).
- DynamoDB `is_deleted(…, turn_id)`: one `_batch_get` of the session and turn tombstone keys
  (`ClientError`/`BotoCoreError` → `StorageUnavailableError`); without `turn_id` keep the single `_get_item`.
- `InstrumentedBackend.deleted_session_ids` → `self._measure("deleted_session_ids", self._inner.deleted_session_ids, …)`.
- `tests/storage/durable_contract.py`: `check_disconnected_raises` also asserts `deleted_session_ids` raises;
  new `check_deleted_session_ids` and `check_is_deleted_turn_includes_session` (spec §4) appended to
  `ALL_CHECKS`.
- Stubs: `_ReferenceBackend` (`test_storage_errors.py`) answers session OR turn and implements
  `deleted_session_ids`; `deleted_session_ids` joins `NEW_ABSTRACT`; `test_base_abc.py` adds it to
  `EXPECTED_ABSTRACT_METHODS` and both stubs; `test_instrumented_backend.py` adds it to `_Stub` and the
  passthrough method list; `test_leaky_abstractions_repaired.py` adds it to `_StubBackend`.

**NOT in scope**: `ChatStorage` (TASK-5688); `query_threads` ordering or its `[]`-on-failure behaviour (separate
ledger issue); any schema change; any wiki page (TASK-5688).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/storage/backends/base.py` | MODIFY | abstract `deleted_session_ids`; `is_deleted` docstring |
| `packages/ai-parrot/src/parrot/storage/backends/sqlite.py` | MODIFY | `deleted_session_ids` |
| `packages/ai-parrot/src/parrot/storage/backends/postgres.py` | MODIFY | `deleted_session_ids` |
| `packages/ai-parrot/src/parrot/storage/backends/mongodb.py` | MODIFY | `deleted_session_ids` |
| `packages/ai-parrot/src/parrot/storage/backends/dynamodb.py` | MODIFY | `deleted_session_ids`; one-round-trip `is_deleted(turn_id)` |
| `packages/ai-parrot/src/parrot/storage/instrumented.py` | MODIFY | measured passthrough |
| `packages/ai-parrot/tests/storage/durable_contract.py` | MODIFY | two new checks; disconnected clause |
| `packages/ai-parrot/tests/storage/test_storage_errors.py` | MODIFY | reference backend + `NEW_ABSTRACT` |
| `packages/ai-parrot/tests/storage/backends/test_base_abc.py` | MODIFY | expected abstract set + stubs |
| `packages/ai-parrot/tests/storage/test_instrumented_backend.py` | MODIFY | stub + passthrough list |
| `packages/ai-parrot/tests/storage/test_leaky_abstractions_repaired.py` | MODIFY | stub |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from parrot.storage.backends.base import ConversationBackend      # base.py:25
from parrot.storage.errors import StorageUnavailableError        # used by every backend already
```

### Existing Signatures to Use

```python
# base.py:186 / :194
async def deleted_turn_ids(self, user_id: str, agent_id: str, session_id: str) -> Set[str]
async def is_deleted(self, user_id: str, agent_id: str, session_id: str, turn_id: Optional[str] = None) -> bool

# sqlite.py:721 deleted_turn_ids — template: self._require_connection(); self._conn.execute(...);
#   sqlite3.Error -> StorageUnavailableError; table conversation_tombstones, session tombstone turn_id = ''
# postgres.py:588 deleted_turn_ids — template: self._pool.acquire(); conn.fetch(...);
#   Exception -> raise self._translate(exc, write=False); table parrot_conversation_tombstones
# mongodb.py:480 deleted_turn_ids — template: self._tombstones.find(filter, projection=...);
#   Exception -> raise self._translate(exc, write=False); session tombstone has turn_id ""
# dynamodb.py
def _build_pk(user_id, agent_id) -> str                  # "USER#<u>#AGENT#<a>"
def _sk_tomb(session_id: str, turn_id: Optional[str] = None) -> str   # TOMB#<s> | TOMB#<s>#TURN#<t>
async def _get_item(self, pk: str, sk: str) -> Optional[dict]          # :226
async def _batch_get(self, keys: List[dict]) -> Dict[str, dict]        # :642 consistent; retries
#   UnprocessedKeys 5x with backoff, then raises StorageUnavailableError; returns {SK: item};
#   does NOT translate ClientError; callers chunk to <= 100 keys (see _load_turns)
# tombstone items carry attribute session_id (put_tombstone)

# instrumented.py:107-111
async def deleted_turn_ids(self, *a, **kw): return await self._measure("deleted_turn_ids", self._inner.deleted_turn_ids, *a, **kw)

# tests/storage/durable_contract.py
USER, AGENT, SESSION = "u-durable", "agent-durable", "s-durable"
class DurableHarness: backend, disconnect, inject_write_failure, seed_legacy, expire_transcript
ALL_CHECKS: List[Callable[[DurableHarness], Awaitable[None]]]          # :216, parametrizes all 4 backends
```

### Does NOT Exist

- `ConversationBackend.deleted_session_ids` — created here.
- `is_session_deleted`, `batch_is_deleted` — do not add.
- `moto` in the shared venv — never install it there.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/storage/backends/base.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/storage/backends/sqlite.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/storage/backends/postgres.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/storage/backends/mongodb.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/storage/backends/dynamodb.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/storage/instrumented.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/storage/durable_contract.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/storage/test_storage_errors.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/storage/backends/test_base_abc.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/storage/test_instrumented_backend.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/storage/test_leaky_abstractions_repaired.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/storage/backends/base.py#ConversationBackend.is_deleted",
    "sym:packages/ai-parrot/src/parrot/storage/backends/base.py#ConversationBackend.deleted_turn_ids",
    "sym:packages/ai-parrot/src/parrot/storage/backends/dynamodb.py#ConversationDynamoDB._batch_get"
  ]
}
```

---

## Implementation Notes

### Key Constraints

- Fail closed: never return an empty set for a failed or disconnected read.
- Only ids from the input are returned; duplicates in the input are harmless.
- Postgres binds the list as `$3::text[]`; never interpolate ids into SQL.
- DynamoDB keys are deduplicated before chunking (BatchGetItem rejects duplicate keys).

### References in Codebase

- `deleted_turn_ids` in each backend (commit `2411081ac6`) — the pattern to mirror.
- `ConversationDynamoDB._load_turns` — chunking for `_batch_get`.

---

## Implementation Blueprint

### Steps (in order)

1. `base.py`: typing import, abstract method, `is_deleted` docstring.
2. The four backends + `InstrumentedBackend`.
3. Test stubs (so the ABC change does not break collection), then the durable-contract checks.
4. Run the Validation Commands; `ruff check` the changed files.

### FILL IN checklist
- [ ] Backend bodies — bounded by spec §3 Module 1 "Behaviour".
- [ ] Contract checks — bounded by spec §4 Unit Tests (M1 rows).

---

## Acceptance Criteria

- [ ] `deleted_session_ids` is abstract on `ConversationBackend` and implemented by the four backends and
      `InstrumentedBackend`.
- [ ] `check_deleted_session_ids`, `check_is_deleted_turn_includes_session` and the extended
      `check_disconnected_raises` pass on SQLite; on Postgres when `POSTGRES_TEST_DSN` is set; on DynamoDB when
      `moto[server]` is importable (ephemeral overlay); Mongo skips only for a missing `MONGO_TEST_DSN`.
- [ ] `ruff check` passes on the changed Python files.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/storage/backends/test_sqlite_durable_contract.py packages/ai-parrot/tests/storage/backends/test_base_abc.py packages/ai-parrot/tests/storage/test_storage_errors.py packages/ai-parrot/tests/storage/test_instrumented_backend.py packages/ai-parrot/tests/storage/test_leaky_abstractions_repaired.py -q`
- `pytest packages/ai-parrot/tests/storage/backends/test_postgres_durable_contract.py packages/ai-parrot/tests/storage/backends/test_mongo_durable_contract.py packages/ai-parrot/tests/storage/backends/test_dynamodb_durable_contract.py -q`

---

## Test Specification

See spec §4 Unit Tests (M1 rows).

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`parrot sdd worktree ensure --slug backends-base-tech-debt --feature-id FEAT-897`)
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — none
4. **Verify the Codebase Contract** before writing any code
5. **Update status** in `sdd/tasks/index/backends-base-tech-debt.json` → `"in-progress"` (set `started_at`) and commit only that index file
6. **Implement** from the Implementation Blueprint
7. **Verify** all acceptance criteria — run the Validation Commands with `PYTHONPATH=packages/ai-parrot/src`
8. **Commit the code** — stage only the files listed above
9. **Close the task** with `parrot sdd task close TASK-5687 backends-base-tech-debt verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

**Completed by**: Claude Code (/sdd-fix, actor agent:sdd-fix:814f17e6)
**Date**: 2026-11-14
**Notes**: Implemented in commit 8a2ae9c09e. `deleted_session_ids` is abstract on `ConversationBackend` and implemented
by SQLite (one query per 500 ids), Postgres (one `ANY($3::text[])` query), Mongo (one `$in` query per 1000 ids) and
DynamoDB (`_batch_get` of deduplicated `TOMB#<session>` keys, ≤ 100 per request, `ClientError`/`BotoCoreError` →
`StorageUnavailableError`), plus the measured `InstrumentedBackend` passthrough. `is_deleted`'s docstring states the
session-OR-turn meaning; DynamoDB answers the turn form with one `_batch_get`. The shared contract gained
`check_deleted_session_ids` (150 ids, so DynamoDB crosses a chunk) and `check_is_deleted_turn_includes_session`, and
`check_disconnected_raises` covers the new read.
Validation (`PYTHONPATH=packages/ai-parrot/src`): SQLite contract + `test_base_abc` + `test_storage_errors` +
`test_instrumented_backend` + `test_leaky_abstractions_repaired` → 57 passed; DynamoDB contract through an ephemeral
`uv run --no-project --with 'moto[server]'` overlay (shared venv unchanged; needs `SITE_ROOT` for navconfig) → 20
passed, both new checks included. Postgres and Mongo contracts skipped: `POSTGRES_TEST_DSN` / `MONGO_TEST_DSN` not
set. Mutation check: dropping `turn_id=''` from the SQLite query fails `check_deleted_session_ids`; a turn-only
reference `is_deleted` fails `check_is_deleted_turn_includes_session`. `ruff check`: only the 5 findings already
present at base (B905 ×2, E402 ×2, C416).
**Resolves**: `issue:6393789b3d37` (together with TASK-5688)
**Deviations from spec**: the new one-line stub methods in `test_base_abc.py`, `test_instrumented_backend.py` and
`test_leaky_abstractions_repaired.py` follow those files' compact one-line style, which `black` would expand (as it
would every neighbouring stub). All other changed lines add no `black` differences. `NEW_ABSTRACT` /
`EXPECTED_ABSTRACT_METHODS` also gained `deleted_turn_ids`, which was abstract but missing from both sets.
