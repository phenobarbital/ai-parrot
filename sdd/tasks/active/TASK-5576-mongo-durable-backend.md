# TASK-5576: Mongo backend — durable writes, ordered window, tombstones, index state

**Feature**: FEAT-886 — Durable Conversation Memory
**Spec**: `sdd/specs/durable-conversation-memory.spec.md` (Module 7)
**Status**: pending
**Priority**: medium
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-5570
**Assigned-to**: unassigned

---

## Context

M4 (TASK-5570) fixes the new abstract operations of `ConversationBackend`; M5 (TASK-5574) is the
reference implementation on SQLite. This task implements the same contract on
`ConversationMongoBackend` (motor): a compound index for the ordered window, `conversation_tombstones`
and `conversation_index_state` collections, and a tombstone-fenced upsert. Semantics must be IDENTICAL
to the SQLite backend (same ordering key `(timestamp, sequence, turn_id)`, same derived index state,
same error mapping); only the storage mechanics differ.

---

## Scope

- `initialize`: new collections and indexes (compound `conv_turn_chrono`, unique tombstone and index-state keys; NO TTL index on tombstones).
- `put_turn` raises instead of returning silently (`StorageUnavailableError` / `StorageWriteError` / `ConversationDeletedError`); tombstone-fenced two-phase upsert; ordering fields of an existing turn are never changed.
- `query_turns` raises `StorageUnavailableError` instead of returning `[]` when disconnected or failing.
- New operations: `query_turn_window`, `max_sequence`, `put_tombstone`, `is_deleted`, `get_index_state`, `backfill_batch`.
- Tests: shared contract suite + Mongo-specific tests. They SKIP when `MONGO_TEST_DSN` is unset (repo convention, `tests/storage/conftest.py:13`).

**NOT in scope**: the ABC and `durable_contract.py` (TASK-5570); the backfill driver (TASK-5578); `delete_turn` / `delete_thread_cascade` / thread / artifact methods keep their behavior (the cascade deletes from `conversations` and `artifacts` only — it must stay blind to the tombstone collection); do not touch the other backends.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/storage/backends/mongodb.py` | MODIFY | New collections/indexes, `put_turn`/`query_turns` failure contract, the six new operations |
| `packages/ai-parrot/tests/storage/backends/test_mongo_durable_contract.py` | CREATE | Shared contract suite + Mongo-specific durability tests (skip without `MONGO_TEST_DSN`) |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
import asyncio                                                    # stdlib (add)
from datetime import datetime, timedelta, timezone               # mongodb.py:14 (verified)
from parrot.storage.backends.base import ConversationBackend      # mongodb.py:19 (verified)
# --- created by TASK-5570 (read its completion note before use) ---
from parrot.storage.backends.base import BackfillBatch
from parrot.storage.errors import (ConversationDeletedError, IndexNotReadyError, StorageError,
                                   StorageUnavailableError, StorageWriteError)
# --- LAZY imports (inside functions): motor/pymongo are optional dependencies, and `parrot.storage.__init__`
# --- imports this module eagerly (storage/__init__.py: ConversationMongoBackend). NEVER import them at module level.
#   from pymongo import errors as mongo_errors      # ConnectionFailure (parent of AutoReconnect, ServerSelectionTimeoutError, NetworkTimeout), InvalidOperation, WriteError
#   from bson import ObjectId                       # ships with pymongo
```
NOTE: `motor`, `pymongo` and `mongomock` are NOT installed in the shared `.venv` of this repo (checked 2026-11): the Mongo tests cannot run there; they must run (and be reported) against a real `MONGO_TEST_DSN` before the task is closed.

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/storage/backends/mongodb.py
class ConversationMongoBackend(ConversationBackend):               # :22
    def __init__(self, dsn: str, database: str = "parrot", default_ttl_days: int = 180)   # :42  self._client/_db/_conversations/_artifacts/_initialized  :51-55
    async def initialize(self) -> None                              # :62  indexes :73-100: conv_compound_unique (user_id,agent_id,session_id,sort_key; unique), conv_user_agent_time, conv_ttl (expires_at TTL, expireAfterSeconds=0); _initialized=True :102
    async def close(self) -> None                                   # :105  nulls _client/_conversations/_artifacts :118-121
    @property is_connected                                          # :124  _client is not None and _initialized
    def _expires_at(self) -> Optional[datetime]                     # :131
    def _clean(self, doc: dict) -> dict                             # :136  pops _id, isoformat()s updated_at/expires_at
    async def put_turn(self, user_id, agent_id, session_id, turn_id, data) -> None    # :226  silent return when disconnected :234-235; replace_one(upsert=True) of {identity..., kind:'turn', sort_key:'TURN#<id>', turn_id, updated_at, expires_at, **payload}
    async def query_turns(self, user_id, agent_id, session_id, limit=10, newest_first=True) -> List[dict]   # :259  returns [] when disconnected :267-268; find(...).sort("sort_key", dir).limit(limit); _clean each doc
    async def delete_turn / delete_thread_cascade                   # :280 / :296  cascade: delete_many on conversations AND artifacts only (keep it so)
# Turn document shape: the payload keys are spread at the TOP LEVEL of the document (no nested "payload").
```

### Does NOT Exist

- ~~`ts_utc` / `seq` fields on turn documents~~, ~~`conv_turn_chrono` index~~, ~~`conversation_tombstones` / `conversation_index_state` collections~~ — created by this task.
- ~~`query_turn_window`, `put_tombstone`, `is_deleted`, `max_sequence`, `get_index_state`, `backfill_batch`~~ on any backend — abstract in TASK-5570; implemented here.
- ~~`BackfillBatch`~~, ~~`parrot.storage.errors`~~ — created by TASK-5570.
- ~~A TTL index on the tombstone or index-state collections~~ — tombstones are retained indefinitely (spec §2 "Deletion").
- ~~A `ts_utc` stored as a BSON date~~ — BSON dates have MILLISECOND resolution; this backend stores `ts_utc` as an int64 count of MICROSECONDS since the epoch so ordering matches the µs-resolution backends exactly (decision recorded in Key Constraints).
- ~~`mongomock` / a motor fake in the repo~~ — there is none; tests run against a real server.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/storage/backends/mongodb.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/storage/backends/test_mongo_durable_contract.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/storage/backends/mongodb.py#ConversationMongoBackend",
    "sym:packages/ai-parrot/src/parrot/storage/backends/base.py#ConversationBackend"
  ]
}
```

---

## Implementation Notes

### Pattern to Follow

The existing module: plain `dict` documents, `replace_one(..., upsert=True)`, `self.logger`, motor collections held on `self`. The reference semantics are TASK-5574 (SQLite): if a behavior is unclear, match it.

### Key Constraints

- **Index state is derived** (same decision as SQLite/Postgres): a session is `ready` iff it has no turn document with `ts_utc: None` (missing or null); otherwise `invalid` when `conversation_index_state` holds `state='invalid'`, else `pending`. `backfill_batch` writes `invalid`/`ready` documents; `get_index_state` never trusts a stored `ready`. A write without a parseable `timestamp` stores `ts_utc: None` (legacy-style callers and the existing tests keep working) and makes the session `pending`. No expiry filter is applied (the TTL reaper owns expiry here, as in `query_turns`).
- **Ordering immutability**: before the upsert, read the existing document's `ts_utc`/`seq`/`timestamp`/`sequence` (`find_one` with a projection); if it has a non-null `ts_utc`, keep those four values and replace everything else; otherwise adopt the incoming ordering fields.
- **`ts_utc` = int64 microseconds since the epoch** computed with integer arithmetic (`(ts - EPOCH) // timedelta(microseconds=1)`), never `ts.timestamp() * 1e6` (float drift). Naive timestamps are read as UTC (spec §7); a negative result is treated as unusable (`None`). `seq` = `data["sequence"]` when a non-negative `int`, else `0`.
- **Tombstone-fenced upsert = guarded two-phase write** (spec M7 fallback, valid on every deployment including standalone `mongod`): (1) `_is_tombstoned` → `ConversationDeletedError`; (2) `replace_one(upsert=True)`; (3) `_is_tombstoned` again — if a tombstone landed in between, `delete_one` the document just written and raise `ConversationDeletedError`. Because ChatStorage commits the tombstone BEFORE clearing (TASK-5579), any document written before the tombstone is removed by the cascade and any document written after it is caught by phase 3. A transaction-based variant is OPTIONAL (spec: "where the deployment supports it"): do not add one unless you can test it on a replica set; the Completion Note must say which you shipped.
- **Collections**: `conversation_tombstones` (key `(user_id, agent_id, session_id, turn_id)`, a SESSION tombstone stores `turn_id=""`) and `conversation_index_state` (key `(user_id, agent_id, session_id)`). Both unique-indexed, no TTL. `put_tombstone` uses `update_one({key}, {"$setOnInsert": {"created_at": now}}, upsert=True)` (idempotent, first `created_at` wins). `turn_id == ""` raises `ValueError`.
- **Internal fields do not leak**: `_clean` must also drop `ts_utc` and `seq` from returned documents (the returned `timestamp`/`sequence` payload keys carry the same information in their original form).
- **Error mapping** (`_translate(exc, *, write)`): `pymongo.errors.ConnectionFailure` (covers `AutoReconnect`, `ServerSelectionTimeoutError`, `NetworkTimeout`), `pymongo.errors.InvalidOperation` (client closed), `OSError`, `asyncio.TimeoutError` → `StorageUnavailableError`; any other exception → `StorageWriteError` for writes, `StorageUnavailableError` for reads. Typed `StorageError`s raised in the body pass through (`except StorageError: raise` BEFORE the generic handler). `raise ... from exc`; nothing is swallowed.
- **`BackfillBatch.processed` = documents INDEXED by the call** (TASK-5578 sums it; TASK-5570's `check_backfill_batch_resumable` expects a re-run to report `0`); unusable-timestamp documents stay `ts_utc: None`, are listed in `invalid_sessions` on every run and keep their session `invalid`; `next_cursor` depends on documents EXAMINED (`len(docs) == batch_size`). The cursor is `str(ObjectId)` of the last examined document (`_id` order).
- **`invalid_sessions` entry format**: whatever TASK-5570 documents on `BackfillBatch`; otherwise `"<user_id>/<agent_id>/<session_id>"` (state it in the Completion Note).
- **`_chrono_fields`**: if TASK-5570's `backends/base.py` exposes a shared parser, import it (adapting to microseconds if needed); otherwise keep the local copy below, semantically identical to the SQLite/Postgres/DynamoDB ones (naive = UTC, bad sequence = 0).
- Async only; no new dependency; lazy pymongo/bson imports; Google-style docstrings; type hints.

### References in Codebase

- `packages/ai-parrot/src/parrot/storage/backends/mongodb.py` — the file itself.
- `packages/ai-parrot/tests/storage/backends/test_mongo_backend.py` — existing skip pattern (`MONGO_TEST_DSN`) and per-test database names.
- `packages/ai-parrot/tests/storage/durable_contract.py` (TASK-5570) — `DurableHarness`, `ALL_CHECKS`.
- TASK-5574 (`sdd/tasks/active/TASK-5574-sqlite-durable-backend.md`) — reference semantics.

---

## Implementation Blueprint

> **CRITICAL — Executor-ready starting point.** Write each block nearly verbatim, then complete
> every `# FILL IN:` marker. Never change a signature, class name, or file path.

### Steps (in order)
1. Confirm TASK-5570 is `done`; read `storage/errors.py`, the abstract signatures and `tests/storage/durable_contract.py` — *why*: implemented verbatim.
2. Add imports, `_chrono_fields`, `_EPOCH` — *why*: one place reads ordering from a payload.
3. Extend `__init__`/`initialize`/`close` and `_clean` — *why*: new collections/indexes without leaking internals.
4. Replace `put_turn`, patch `query_turns` — *why*: failure contract.
5. Add the six operations — *why*: the M4 surface.
6. Write the tests; run mutation checks against a real server — *why*: Rule 6.

### `packages/ai-parrot/src/parrot/storage/backends/mongodb.py` (MODIFY) — imports and helper
```python
# occurrences: 1 (verified: grep -c 'from typing import List, Optional' packages/ai-parrot/src/parrot/storage/backends/mongodb.py)  :15
# AFTER — replace that line with:
import asyncio
from typing import Any, Dict, List, Optional, Tuple

# occurrences: 1 (verified: grep -c 'from parrot.storage.backends.base import ConversationBackend' ...)  :19
# AFTER — replace that line with:
from parrot.storage.backends.base import BackfillBatch, ConversationBackend
from parrot.storage.errors import (
    ConversationDeletedError,
    IndexNotReadyError,
    StorageError,
    StorageUnavailableError,
    StorageWriteError,
)

_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)
_ONE_US = timedelta(microseconds=1)
_RESERVED = ("_id", "user_id", "agent_id", "session_id", "kind", "sort_key", "turn_id", "ts_utc", "seq")


def _chrono_fields(data: dict) -> Tuple[Optional[int], int]:
    """Return ``(ts_utc_microseconds, sequence)`` from a turn payload (``None`` when unusable)."""
    raw = data.get("timestamp")
    ts: Optional[datetime] = None
    if isinstance(raw, datetime):
        ts = raw
    elif isinstance(raw, str) and raw.strip():
        try:
            ts = datetime.fromisoformat(raw.strip())
        except ValueError:
            ts = None
    micros: Optional[int] = None
    if ts is not None:
        ts = (ts.replace(tzinfo=timezone.utc) if ts.tzinfo is None else ts).astimezone(timezone.utc)
        micros = (ts - _EPOCH) // _ONE_US
        micros = micros if micros >= 0 else None
    seq = data.get("sequence")
    valid_seq = isinstance(seq, int) and not isinstance(seq, bool) and seq >= 0
    return micros, (seq if valid_seq else 0)
```
**Why**: `datetime`, `timedelta`, `timezone` are already imported at `mongodb.py:14`; `_RESERVED` lists the keys a payload must never override (the fixed keys win).

### `packages/ai-parrot/src/parrot/storage/backends/mongodb.py` (MODIFY) — lifecycle and `_clean`
```python
# occurrences: 1 (verified: grep -c '        self._initialized: bool = False' ...)  :55  (inside __init__)
# AFTER — insert directly ABOVE it:
        self._tombstones = None
        self._index_state = None

# occurrences: 1 (verified: grep -c '        # Artifacts indexes' ...)  :89 (the `# Artifacts indexes` comment inside initialize; the count of the bare
#   phrase '# Artifacts' is 2 in the file, so match THIS exact string)
# AFTER — insert directly ABOVE that comment (inside initialize, after the conv_ttl index):
        self._tombstones = self._db["conversation_tombstones"]
        self._index_state = self._db["conversation_index_state"]
        await self._conversations.create_index(
            [("user_id", 1), ("agent_id", 1), ("session_id", 1), ("kind", 1),
             ("ts_utc", 1), ("seq", 1), ("turn_id", 1)],
            name="conv_turn_chrono",
        )
        await self._tombstones.create_index(          # NO TTL: tombstones are kept indefinitely
            [("user_id", 1), ("agent_id", 1), ("session_id", 1), ("turn_id", 1)],
            unique=True, name="tomb_unique",
        )
        await self._index_state.create_index(
            [("user_id", 1), ("agent_id", 1), ("session_id", 1)], unique=True, name="idxstate_unique",
        )

# occurrences: 1 (verified: grep -c '                self._artifacts = None' ...)  :120 (inside close)
# AFTER — add two lines directly below it, same indentation:
                self._tombstones = None
                self._index_state = None

# occurrences: 1 (verified: grep -c '        for k in ("updated_at", "expires_at"):' ...)  :139 (inside _clean)
# AFTER — insert directly ABOVE that line:
        doc.pop("ts_utc", None)
        doc.pop("seq", None)
```
**Why**: the index key order mirrors the SQL backends' composite index; Mongo walks it backwards for the descending sort, so one ascending index serves `ORDER BY ... DESC`. The unique `tomb_unique` index makes concurrent `put_tombstone` upserts safe.

### `packages/ai-parrot/src/parrot/storage/backends/mongodb.py` (MODIFY) — error helpers, `put_turn`, `query_turns`
```python
# occurrences: 1 (verified: grep -c '    def _clean(self, doc: dict) -> dict:' ...)  :136
# AFTER — insert directly ABOVE it:
    def _require_connection(self) -> None:
        """Raise ``StorageUnavailableError`` when the backend is not connected."""
        if not self.is_connected:
            raise StorageUnavailableError("MongoDB conversation backend is not connected")

    @staticmethod
    def _translate(exc: BaseException, *, write: bool) -> StorageError:
        """Map a driver/transport exception to the typed storage error (never swallow)."""
        from pymongo import errors as mongo_errors  # lazy: optional dependency
        transport = (mongo_errors.ConnectionFailure, mongo_errors.InvalidOperation, OSError, asyncio.TimeoutError)
        if isinstance(exc, transport):
            return StorageUnavailableError(f"MongoDB unavailable: {exc}")
        cls = StorageWriteError if write else StorageUnavailableError
        return cls(f"MongoDB operation failed: {exc}")

    async def _is_tombstoned(
        self, user_id: str, agent_id: str, session_id: str, turn_id: Optional[str] = None
    ) -> bool:
        """Session tombstone, or (when ``turn_id`` is given) session OR turn tombstone."""
        found = await self._tombstones.find_one(
            {"user_id": user_id, "agent_id": agent_id, "session_id": session_id,
             "turn_id": {"$in": ["", turn_id or ""]}},
            projection={"_id": 1},
        )
        return found is not None

    async def _build_turn_doc(self, key: Dict[str, Any], turn_id: str, data: dict) -> dict:
        """Document to write: payload spread at top level, fixed keys last, ordering kept if already set."""
        payload = {k: (v.isoformat() if isinstance(v, datetime) else v)
                   for k, v in data.items() if k not in _RESERVED}
        ts_us, seq = _chrono_fields(data)
        existing = await self._conversations.find_one(
            key, projection={"ts_utc": 1, "seq": 1, "timestamp": 1, "sequence": 1})
        if existing is not None and existing.get("ts_utc") is not None:
            ts_us, seq = existing["ts_utc"], existing.get("seq", 0)
            for name in ("timestamp", "sequence"):         # immutable once set
                if name in existing:
                    payload[name] = existing[name]
                else:
                    payload.pop(name, None)
        return {**payload, **key, "kind": "turn", "turn_id": turn_id,
                "updated_at": datetime.now(timezone.utc), "expires_at": self._expires_at(),
                "ts_utc": ts_us, "seq": seq}
```
```python
# occurrences: 1 (verified: grep -c 'async def put_turn(' ...)  :226
# REPLACE the whole method (def line :226 through its closing `)` of replace_one :257) with:
    async def put_turn(
        self,
        user_id: str,
        agent_id: str,
        session_id: str,
        turn_id: str,
        data: dict,
    ) -> None:
        """Idempotent upsert by ``turn_id`` fenced by a tombstone check before AND after the write.

        Raises:
            StorageUnavailableError: not connected / transport failure.
            ConversationDeletedError: the session or this turn is tombstoned.
            StorageWriteError: the write failed (nothing is swallowed).
        """
        self._require_connection()
        key = {"user_id": user_id, "agent_id": agent_id, "session_id": session_id,
               "sort_key": f"TURN#{turn_id}"}
        try:
            if await self._is_tombstoned(user_id, agent_id, session_id, turn_id):
                raise ConversationDeletedError(
                    f"session {session_id} or turn {turn_id} is tombstoned; write rejected")
            doc = await self._build_turn_doc(key, turn_id, data)
            await self._conversations.replace_one(key, doc, upsert=True)
            if await self._is_tombstoned(user_id, agent_id, session_id, turn_id):   # phase 3: lost the race
                await self._conversations.delete_one(key)
                raise ConversationDeletedError(
                    f"session {session_id} or turn {turn_id} was tombstoned during the write; rolled back")
        except StorageError:
            raise
        except Exception as exc:
            raise self._translate(exc, write=True) from exc

# occurrences: 1 (verified: python3 count of "        if not self.is_connected:\n            return []\n        sort_dir = -1 if newest_first else 1" in mongodb.py)  :267-269
# In query_turns: replace `if not self.is_connected:\n            return []` with `self._require_connection()` and wrap the cursor loop
# (:270-277, from `cursor = self._conversations.find(` to `result.append(doc)`) in:
        try:
            ...  # the existing find/sort/limit and `async for` loop, unchanged
        except Exception as exc:
            raise self._translate(exc, write=False) from exc
```
**Why**: the unique index `conv_compound_unique` serializes two racing first writes of the same turn (one `replace_one` upsert may raise `DuplicateKeyError`: treat as `StorageWriteError` — the bus retries and the retry finds the document; do not special-case it). Phase 3 closes the window left by a non-transactional write.

### `packages/ai-parrot/src/parrot/storage/backends/mongodb.py` (MODIFY) — new operations (insert above the `# Artifacts` banner)
```python
# occurrences: 2 for the bare phrase '    # Artifacts' (:89 `# Artifacts indexes`, :313) — anchor on the banner comment block that
# immediately precedes `async def put_artifact(` (:316): insert the block ABOVE that banner.
    # ------------------------------------------------------------------
    # FEAT-886: ordered window, tombstones, index state, backfill
    # ------------------------------------------------------------------

    async def query_turn_window(
        self, user_id: str, agent_id: str, session_id: str, limit: int
    ) -> List[dict]:
        """Newest ``limit`` turns by (ts_utc, seq, turn_id), limit applied descending, returned ascending."""
        self._require_connection()
        if await self.is_deleted(user_id, agent_id, session_id):
            raise ConversationDeletedError(f"session {session_id} is tombstoned")
        if await self.get_index_state(user_id, agent_id, session_id) != "ready":
            raise IndexNotReadyError(f"chronological index of session {session_id} is not ready")
        if limit <= 0:
            return []
        scope = {"user_id": user_id, "agent_id": agent_id, "session_id": session_id}
        try:
            gone = [d["turn_id"] async for d in self._tombstones.find(
                {**scope, "turn_id": {"$ne": ""}}, projection={"turn_id": 1})]
            cursor = (
                self._conversations.find({**scope, "kind": "turn", "ts_utc": {"$ne": None},
                                          "turn_id": {"$nin": gone}})
                .sort([("ts_utc", -1), ("seq", -1), ("turn_id", -1)])
                .hint("conv_turn_chrono")
                .limit(limit)
            )
            window = [self._clean(doc) async for doc in cursor]
        except Exception as exc:
            raise self._translate(exc, write=False) from exc
        window.reverse()
        return window

    async def max_sequence(self, user_id: str, agent_id: str, session_id: str) -> int:
        """Highest stored sequence for the session, ``0`` when none (durable maximum)."""
        self._require_connection()
        pipeline = [
            {"$match": {"user_id": user_id, "agent_id": agent_id, "session_id": session_id, "kind": "turn"}},
            {"$group": {"_id": None, "m": {"$max": "$seq"}}},
        ]
        try:
            rows = await self._conversations.aggregate(pipeline).to_list(length=1)
        except Exception as exc:
            raise self._translate(exc, write=False) from exc
        return int(rows[0]["m"]) if rows and rows[0].get("m") is not None else 0

    async def put_tombstone(
        self, user_id: str, agent_id: str, session_id: str, turn_id: Optional[str] = None
    ) -> None:
        """Durably record a session (``turn_id=None``) or turn deletion. Idempotent; no TTL."""
        self._require_connection()
        if turn_id == "":
            raise ValueError("turn_id must be non-empty (use None for a session tombstone)")
        try:
            await self._tombstones.update_one(
                {"user_id": user_id, "agent_id": agent_id, "session_id": session_id, "turn_id": turn_id or ""},
                {"$setOnInsert": {"created_at": datetime.now(timezone.utc)}},
                upsert=True,
            )
        except Exception as exc:
            raise self._translate(exc, write=True) from exc
```
*(continued — same file, same block, keep the order)*
```python
    async def is_deleted(
        self, user_id: str, agent_id: str, session_id: str, turn_id: Optional[str] = None
    ) -> bool:
        """Whether the session (or session OR this turn) is tombstoned; raises when it cannot be determined."""
        self._require_connection()
        try:
            return await self._is_tombstoned(user_id, agent_id, session_id, turn_id)
        except Exception as exc:
            raise self._translate(exc, write=False) from exc

    async def get_index_state(self, user_id: str, agent_id: str, session_id: str) -> str:
        """``'ready'`` | ``'pending'`` | ``'invalid'`` (derived; see Key Constraints)."""
        self._require_connection()
        scope = {"user_id": user_id, "agent_id": agent_id, "session_id": session_id}
        try:
            unindexed = await self._conversations.find_one(
                {**scope, "kind": "turn", "ts_utc": None}, projection={"_id": 1})
            if unindexed is None:
                return "ready"
            state = await self._index_state.find_one(scope, projection={"state": 1})
        except Exception as exc:
            raise self._translate(exc, write=False) from exc
        return "invalid" if state is not None and state.get("state") == "invalid" else "pending"
```
**Why**: `.hint("conv_turn_chrono")` makes a missing index an error instead of a silent collection scan (spec §5: "no request path performs a full-table scan"). `tombstoned turns` are excluded in the query itself (`$nin`), so a turn that is tombstoned but not yet physically deleted never hydrates. The `$ne: None` filter excludes both missing and `null` `ts_utc`.

```python
    async def _finalize_session(self, scope: Dict[str, str], saw_invalid: bool) -> None:
        """Write ``invalid`` / ``ready`` for a session touched by a batch (otherwise leave it pending)."""
        if saw_invalid:
            state = "invalid"
        elif await self._conversations.find_one({**scope, "kind": "turn", "ts_utc": None},
                                                projection={"_id": 1}) is None:
            state = "ready"
        else:
            return
        await self._index_state.update_one(
            scope, {"$set": {"state": state, "updated_at": datetime.now(timezone.utc)}}, upsert=True)

    async def backfill_batch(self, cursor: Optional[str], batch_size: int) -> BackfillBatch:
        """Index up to ``batch_size`` legacy turns after ``cursor`` (resumable, safe next to new writes)."""
        from bson import ObjectId  # lazy: ships with pymongo
        self._require_connection()
        query: Dict[str, Any] = {"kind": "turn", "ts_utc": None}
        if cursor is not None:
            query["_id"] = {"$gt": ObjectId(cursor)}
        touched: Dict[Tuple[str, str, str], bool] = {}
        skipped: Dict[Tuple[str, str, str], bool] = {}
        indexed_count = 0
        try:
            docs = [d async for d in self._conversations.find(query).sort("_id", 1).limit(batch_size)]
            for doc in docs:
                key = (doc["user_id"], doc["agent_id"], doc["session_id"])
                if key not in skipped:
                    skipped[key] = await self._is_tombstoned(*key)
                if skipped[key] or await self._is_tombstoned(*key, doc.get("turn_id")):
                    continue                                   # tombstoned sessions / turns are never indexed
                ts_us, seq = _chrono_fields(doc)
                if ts_us is None:
                    touched[key] = True
                    continue
                result = await self._conversations.update_one(
                    {"_id": doc["_id"], "ts_utc": None}, {"$set": {"ts_utc": ts_us, "seq": seq}})
                indexed_count += result.modified_count
                touched.setdefault(key, False)
            for key, saw_invalid in touched.items():
                scope = dict(zip(("user_id", "agent_id", "session_id"), key))
                await self._finalize_session(scope, saw_invalid)
        except Exception as exc:
            raise self._translate(exc, write=True) from exc
        invalid = tuple("/".join(k) for k, bad in touched.items() if bad)
        next_cursor = str(docs[-1]["_id"]) if docs and len(docs) == batch_size else None
        return BackfillBatch(processed=indexed_count, next_cursor=next_cursor, invalid_sessions=invalid)
```
**Why**: documents are examined in `_id` order after the cursor; `{"_id": ..., "ts_utc": None}` in the update filter makes a concurrent `put_turn` of the same turn win; tombstoned sessions are skipped and never marked `ready`; unusable-timestamp documents keep `ts_utc: None` and flip their session to `invalid`.

### FILL IN checklist
- [ ] `put_turn` — whether to also ship the OPTIONAL transaction path; bounded by spec M7 and "must be testable on a replica set"; default NO (two-phase only), state the choice in the Completion Note.
- [ ] `_chrono_fields` — use a shared helper if TASK-5570 provides one; bounded by "identical semantics across backends".
- [ ] `invalid_sessions` entry format — bounded by TASK-5570's `BackfillBatch` docstring.
- [ ] `query_turns` wrapper — keep the existing sort/limit/`_clean` logic byte-for-byte inside the `try`.
- [ ] Test file: `DurableHarness` keyword names (see Test Specification) — bounded by TASK-5570's actual dataclass.

---

## Acceptance Criteria

- [ ] `put_turn` never returns silently: disconnected → `StorageUnavailableError`; failed write → `StorageWriteError`; tombstoned session/turn → `ConversationDeletedError` (spec §5 "No silent backend writes").
- [ ] Repeated `put_turn` with the same `turn_id` leaves one document with unchanged `ts_utc`/`seq`/`timestamp`/`sequence` (spec §4 contract suite).
- [ ] `query_turn_window` returns the same newest window, ascending, for random and reverse-lexical IDs, equal timestamps and more rows than `limit`; it uses the `conv_turn_chrono` index (`hint`, plus an `explain` check without `COLLSCAN`) (spec §5 "Chronological hydration").
- [ ] A tombstone that lands between the first check and the write is caught by phase 3: the document is deleted and `ConversationDeletedError` raised (race-injection test).
- [ ] Tombstones survive `delete_thread_cascade`, deletion of the transcript documents (TTL reaper simulation) and a backend restart; the tombstone collection has no TTL index.
- [ ] `get_index_state`: `pending` for legacy sessions, `invalid` for a bad timestamp after backfill, `ready` for new sessions; `query_turn_window` on a non-ready session raises `IndexNotReadyError` (spec §5 "Backfill").
- [ ] `backfill_batch` is resumable by cursor, skips tombstoned sessions, ignores post-FEAT-886 documents, never marks an unusable-timestamp session `ready`; `processed` counts indexed documents only.
- [ ] Returned documents never contain `ts_utc`, `seq` or `_id`.
- [ ] Existing `test_mongo_backend.py` stays green (its turns carry no timestamp); `ruff check` clean; no module-level `motor`/`pymongo`/`bson` import.
- [ ] **Mutation checks** (record in the Completion Note, run against a real server): (1) remove phase 3 (the second `_is_tombstoned`) → the race-injection test RED; (2) remove the first `_is_tombstoned` check → tombstone-blocks-put check RED; (3) sort the window `("ts_utc", 1)` → window check RED; (4) drop `("turn_id", -1)` from the sort → equal-timestamp tie-break check RED; (5) make `get_index_state` return `"ready"` when a `ts_utc: None` document exists → `IndexNotReady` check and legacy-backfill test RED.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/storage/backends/test_mongo_durable_contract.py -q`
- `pytest packages/ai-parrot/tests/storage/backends/test_mongo_backend.py -q`
- `pytest packages/ai-parrot/tests/storage/test_backend_contract.py -q`

(These SKIP without `MONGO_TEST_DSN`; motor/pymongo are not in the shared `.venv`. Run them once against a real MongoDB — `uv pip install motor` in a scratch environment, `MONGO_TEST_DSN=mongodb://localhost:27017` — before closing the task, and record it.)

---

## Test Specification

> Real MongoDB, one database per test dropped at teardown; no mocks. A failed durable write is
> injected for real with a collection validator that rejects the test user's documents; the
> two-phase race is injected by writing a real tombstone at the exact interleaving point.

```python
# packages/ai-parrot/tests/storage/backends/test_mongo_durable_contract.py
import asyncio
import os
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

import pytest

from parrot.storage.backends.mongodb import ConversationMongoBackend
from parrot.storage.errors import (ConversationDeletedError, IndexNotReadyError,
                                   StorageUnavailableError, StorageWriteError)
from .. import durable_contract          # TASK-5570: DurableHarness + ALL_CHECKS (NOT collected: no test_ prefix)

DSN = os.environ.get("MONGO_TEST_DSN")
pytestmark = pytest.mark.skipif(not DSN, reason="MONGO_TEST_DSN not set — skipping Mongo durable contract")

UTC = timezone.utc
T0 = datetime(2026, 11, 1, 10, 0, 0, tzinfo=UTC)


@pytest.fixture
async def backend():
    b = ConversationMongoBackend(dsn=DSN, database=f"parrot_durable_{uuid.uuid4().hex[:12]}")
    await b.initialize()
    yield b
    try:
        await b._client.drop_database(b._database)
    finally:
        await b.close()


@asynccontextmanager
async def _inject_write_failure(backend):
    """REAL failure: a collection validator rejects every document of the contract user."""
    db = backend._db
    await db.command("collMod", "conversations", validator={"user_id": {"$ne": durable_contract.USER}},
                     validationLevel="strict", validationAction="error")
    try:
        yield
    finally:
        await db.command("collMod", "conversations", validator={}, validationLevel="off")


async def _seed_legacy(backend, session_id: str, rows: list) -> None:
    """Insert pre-FEAT-886 documents: payload keys at top level, no ts_utc / seq."""
    await backend._conversations.insert_many([
        {"user_id": durable_contract.USER, "agent_id": durable_contract.AGENT, "session_id": session_id,
         "kind": "turn", "sort_key": f"TURN#{r['turn_id']}", **r} for r in rows])


async def _expire(backend, session_id: str) -> None:
    """Simulate the TTL reaper: the transcript documents disappear, tombstones must not."""
    await backend._conversations.delete_many({"session_id": session_id})


@pytest.fixture
def harness(backend):
    # FILL IN: adapt the keyword names to the `DurableHarness` dataclass TASK-5570 actually wrote
    # (expected hooks: disconnect, inject_write_failure, seed_legacy, expire_transcript) — adapt THIS
    # call site, never the shared checks; record any mismatch in the Completion Note.
    return durable_contract.DurableHarness(
        backend=backend,
        disconnect=backend.close,
        inject_write_failure=lambda: _inject_write_failure(backend),
        seed_legacy=lambda sid, rows: _seed_legacy(backend, sid, rows),
        expire_transcript=lambda sid: _expire(backend, sid),
    )


@pytest.mark.parametrize("check", durable_contract.ALL_CHECKS, ids=lambda c: c.__name__)
async def test_mongo_durable_contract(check, harness):
    await check(harness)


def _row(i: int, ts: datetime, seq: int = 0, **extra) -> dict:
    return {"timestamp": ts.isoformat(), "sequence": seq, "user_message": f"q{i}",
            "assistant_response": f"a{i}", **extra}


# --- Mongo-specific ------------------------------------------------------------------------
async def test_disconnected_backend_raises_everywhere():
    b = ConversationMongoBackend(dsn=DSN, database="parrot_never_initialized")   # never initialized
    for call in (lambda: b.put_turn("u", "a", "s", "t", {}), lambda: b.query_turns("u", "a", "s"),
                 lambda: b.query_turn_window("u", "a", "s", 5), lambda: b.is_deleted("u", "a", "s"),
                 lambda: b.get_index_state("u", "a", "s"), lambda: b.put_tombstone("u", "a", "s")):
        with pytest.raises(StorageUnavailableError):
            await call()


async def test_upsert_preserves_ordering_fields_and_hides_internals(backend):
    await backend.put_turn("u", "a", "s", "t1", _row(1, T0, seq=5, assistant_response="first"))
    await backend.put_turn("u", "a", "s", "t1", _row(1, T0 + timedelta(hours=9), seq=99,
                                                      assistant_response="retry"))
    [turn] = await backend.query_turn_window("u", "a", "s", 10)
    assert turn["assistant_response"] == "retry"
    assert turn["timestamp"] == T0.isoformat() and turn["sequence"] == 5
    assert not {"ts_utc", "seq", "_id"} & set(turn)


async def test_microsecond_ordering_is_exact(backend):                       # BSON dates would collapse these
    base = T0.replace(microsecond=0)
    await backend.put_turn("u", "a", "s", "a", _row(1, base + timedelta(microseconds=2)))
    await backend.put_turn("u", "a", "s", "b", _row(2, base + timedelta(microseconds=1)))
    # same millisecond: only exact µs ordering gives ["b", "a"]; a tie would fall back to turn_id -> ["a", "b"]
    assert [t["turn_id"] for t in await backend.query_turn_window("u", "a", "s", 5)] == ["b", "a"]


class _TombstoneAfterWrite:
    """Delegating proxy: after a real replace_one, a real tombstone lands (the phase-2/3 race)."""
    def __init__(self, real, backend):
        self._real, self._backend = real, backend

    def __getattr__(self, name):
        return getattr(self._real, name)

    async def replace_one(self, *a, **kw):
        result = await self._real.replace_one(*a, **kw)
        await self._backend.put_tombstone("u", "a", "s")
        return result


async def test_tombstone_landing_mid_write_rolls_the_document_back(backend):
    backend._conversations = _TombstoneAfterWrite(backend._conversations, backend)
    with pytest.raises(ConversationDeletedError):
        await backend.put_turn("u", "a", "s", "t1", _row(1, T0))
    assert await backend._conversations.find_one({"session_id": "s", "kind": "turn"}) is None


async def test_tombstones_survive_cascade_reaper_and_restart():
    name = f"parrot_durable_{uuid.uuid4().hex[:12]}"
    b = ConversationMongoBackend(dsn=DSN, database=name)
    await b.initialize()
    await b.put_tombstone("u", "a", "s")
    await b.put_tombstone("u", "a", "s2", turn_id="t9")
    await b.delete_thread_cascade("u", "a", "s")
    await b._conversations.delete_many({})                                  # reaper emptied the transcript
    await b.close()
    b2 = ConversationMongoBackend(dsn=DSN, database=name)
    await b2.initialize()
    assert await b2.is_deleted("u", "a", "s") is True
    assert await b2.is_deleted("u", "a", "s2") is False
    assert await b2.is_deleted("u", "a", "s2", turn_id="t9") is True
    ttl = [i for i in (await b2._tombstones.index_information()).values() if "expireAfterSeconds" in i]
    assert ttl == []                                                        # no TTL on tombstones
    await b2._client.drop_database(name)
    await b2.close()


async def test_window_uses_chrono_index_without_collscan(backend):
    await backend.put_turn("u", "a", "s", "t1", _row(1, T0))
    plan = await backend._conversations.find(
        {"user_id": "u", "agent_id": "a", "session_id": "s", "kind": "turn", "ts_utc": {"$ne": None}}
    ).sort([("ts_utc", -1), ("seq", -1), ("turn_id", -1)]).hint("conv_turn_chrono").limit(5).explain()
    assert "COLLSCAN" not in str(plan)


async def test_legacy_documents_backfill_and_become_ready(backend):
    legacy = [("zz-late", T0 + timedelta(minutes=2)), ("aa-early", T0), ("mm-same", T0 + timedelta(minutes=2))]
    await _seed_legacy(backend, "good", [{"turn_id": t, "timestamp": ts.isoformat()} for t, ts in legacy])
    await _seed_legacy(backend, "bad", [{"turn_id": "x", "timestamp": "garbage"}])
    ids = (durable_contract.USER, durable_contract.AGENT)
    assert await backend.get_index_state(*ids, "good") == "pending"
    with pytest.raises(IndexNotReadyError):
        await backend.query_turn_window(*ids, "good", 10)
    batch = await backend.backfill_batch(None, 100)
    assert batch.processed == 3 and batch.next_cursor is None and len(batch.invalid_sessions) == 1
    assert await backend.get_index_state(*ids, "good") == "ready"
    assert await backend.get_index_state(*ids, "bad") == "invalid"
    assert [t["turn_id"] for t in await backend.query_turn_window(*ids, "good", 10)] == [
        "aa-early", "mm-same", "zz-late"]


async def test_failed_write_is_typed_and_recoverable(backend):
    async with _inject_write_failure(backend):
        with pytest.raises(StorageWriteError):
            await backend.put_turn(durable_contract.USER, "a", "s", "t1", _row(1, T0))
    await backend.put_turn(durable_contract.USER, "a", "s", "t1", _row(1, T0))
```
`# FILL IN: test_backfill_resumable_skips_tombstoned_and_new_rows — legacy documents over 3 sessions via _seed_legacy, one session tombstoned, one NEW turn written through put_turn between batches, backfill_batch(cursor, 2) looped with a re-created backend between batches; assert the tombstoned session is never indexed/ready, the new turn's ts_utc is untouched, sum(processed) == indexable documents — bounded by spec §4 test_backfill_resumable and §5 Backfill.`

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`parrot sdd worktree ensure --slug durable-conversation-memory --feature-id FEAT-886`)
2. **Read the spec** at `sdd/specs/durable-conversation-memory.spec.md` (§2 Piece 1/2, §3 Modules 4 and 7, §4 backend contract suite, §5) and TASK-5574 (reference semantics)
3. **Check dependencies** — TASK-5570 must be `"done"` in `sdd/tasks/index/durable-conversation-memory.json`
4. **Verify the Codebase Contract** — confirm every signature above and the abstract signatures TASK-5570 wrote; update the contract first if something changed
5. **Update status** in the per-spec index → `"in-progress"` (set `started_at`) and commit only that index file
6. **Implement** from the Blueprint; complete every `# FILL IN:`; never change a fixed signature or path
7. **Verify** all acceptance criteria and run the Validation Commands against a real MongoDB; record the mutation-check results
8. **Commit the code** — stage only the two files this task lists
9. **Close the task** with `parrot sdd task close TASK-5576 durable-conversation-memory verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
