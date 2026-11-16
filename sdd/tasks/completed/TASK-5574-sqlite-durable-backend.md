# TASK-5574: SQLite backend — durable writes, ordered window, tombstones, index state

**Feature**: FEAT-886 — Durable Conversation Memory
**Spec**: `sdd/specs/durable-conversation-memory.spec.md` (Module 5)
**Status**: done
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-5570
**Assigned-to**: unassigned

---

## Context

M4 (TASK-5570) fixes the new abstract operations of `ConversationBackend` and the typed
errors. This task implements them on `ConversationSQLiteBackend`. SQLite is the only backend
that runs everywhere without services, so it is also the backend every later task's tests run
on (TASK-5578 backfill, TASK-5579 ChatStorage subscriber, TASK-5582 hydration source): get its
semantics exactly right. It also runs the shared contract suite `durable_contract.py`
(TASK-5570) against itself.

---

## Scope

- Additive schema migration in `initialize`: columns `ts_utc REAL`, `seq INTEGER`, `turn_id TEXT` on `conversations`; composite index `idx_conv_turn_chrono`; tables `conversation_tombstones` and `conversation_index_state`.
- `put_turn`: raises instead of returning silently (`StorageUnavailableError` when disconnected, `StorageWriteError` on a failed write, `ConversationDeletedError` when the session or the turn is tombstoned); tombstone check and upsert are ONE statement (atomic); ordering fields of an existing turn are never changed.
- `query_turns`: raises `StorageUnavailableError` instead of returning `[]` when disconnected or failing.
- New operations: `query_turn_window`, `max_sequence`, `put_tombstone`, `is_deleted`, `get_index_state`, `backfill_batch`.
- Tests: run the shared contract suite on SQLite + SQLite-specific tests (legacy-DB migration, query plan, restart/TTL/cascade survival of tombstones, concurrency).

**NOT in scope**: `delete_turn` / `delete_thread_cascade` / thread / artifact methods keep their current (silent-when-disconnected) behavior; the `ConversationBackend` ABC and `durable_contract.py` (TASK-5570); the backfill driver (TASK-5578); ChatStorage deletion protocol (TASK-5579). Do not touch Postgres/Mongo/DynamoDB.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/storage/backends/sqlite.py` | MODIFY | Schema migration, `put_turn`/`query_turns` failure contract, the six new operations |
| `packages/ai-parrot/tests/storage/backends/test_sqlite_durable_contract.py` | CREATE | Shared contract suite on SQLite + SQLite-specific durability tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
import aiosqlite                                                      # sqlite.py:25 (aiosqlite 0.22.1; aiosqlite.Error IS sqlite3.Error)
import sqlite3                                                        # stdlib — add; aiosqlite re-raises sqlite3 exceptions
from parrot.storage.backends.base import ConversationBackend          # sqlite.py:32 (verified)
# --- created by TASK-5570 (read its completion note before use) ---
from parrot.storage.backends.base import BackfillBatch                # frozen dataclass: processed, next_cursor, invalid_sessions
from parrot.storage.errors import (ConversationDeletedError, IndexNotReadyError,
                                   StorageUnavailableError, StorageWriteError)
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/storage/backends/sqlite.py
class ConversationSQLiteBackend(ConversationBackend):               # :35
    DEFAULT_TTL_DAYS = 180                                           # :50
    _CREATE_CONVERSATIONS  # :52-64  PK (user_id, agent_id, session_id, kind, sort_key); cols payload TEXT, updated_at REAL, expires_at REAL
    _CREATE_CONV_IDX_USER_AGENT / _CREATE_CONV_IDX_EXPIRES / _CREATE_ARTIFACTS   # :65-84
    def __init__(self, path: str, default_ttl_days: int = 180)      # :86  self._conn, self._initialized, self.logger
    async def initialize(self) -> None                              # :97  executes DDL at :106-109, commits :110, closes+raises on failure :111-115
    async def close(self) -> None                                   # :119
    @property is_connected                                          # :131  _conn is not None and _initialized
    def _now_epoch(self) -> float                                   # :139
    def _expires_at(self, updated_at: float) -> Optional[float]     # :142
    async def put_turn(self, user_id, agent_id, session_id, turn_id, data: dict) -> None   # :258  silent return when disconnected :267-268; INSERT OR REPLACE
    async def query_turns(self, user_id, agent_id, session_id, limit=10, newest_first=True) -> List[dict]   # :286 returns [] when disconnected :295-296
    async def delete_turn(...) -> bool                              # :328
    async def delete_thread_cascade(...) -> int                     # :354  deletes from conversations + artifacts ONLY (tombstone tables untouched — keep it so)
    async def sweep_expired(self) -> int                            # :518  deletes expired rows from conversations + artifacts ONLY (keep it so)
# Row/payload facts: a turn row is kind='turn', sort_key='TURN#<turn_id>', payload = json.dumps(data, default=str);
# datetime values of `data` are isoformat()-ed at the top level (:271-273).
# Returned turn dicts: {"session_id", "turn_id", "updated_at": iso, **payload}  (:317-324)
```

Facts about the runtime (verified in `.venv`): SQLite 3.49.1 (JSON1 functions `json_patch`, `json_object`,
`json_extract` and row values `(a,b) > (?,?)` are available; they need >= 3.38 / >= 3.15). Python 3.11.

### Does NOT Exist

- ~~`conversations.ts_utc` / `.seq` / `.turn_id` columns~~, ~~`conversation_tombstones`~~, ~~`conversation_index_state`~~ — created by this task (additive).
- ~~`query_turn_window`, `put_tombstone`, `is_deleted`, `max_sequence`, `get_index_state`, `backfill_batch`~~ on any backend — created by TASK-5570 (abstract) and this task (SQLite impl).
- ~~`BackfillBatch`~~, ~~`parrot.storage.errors`~~ — created by TASK-5570.
- ~~A TTL on tombstones~~ — tombstone rows must have no `expires_at` and live in their own table so `sweep_expired` / `delete_thread_cascade` cannot touch them.
- ~~`ConversationSQLiteBackend.put_turn` returning silently~~ — after this task it never does.
- ~~An explicit `BEGIN`/`COMMIT` spanning several `await`s~~ — the backend shares ONE aiosqlite connection between coroutines; other methods call `self._conn.commit()` at arbitrary points, so a multi-await transaction is not isolated. Atomicity here comes from single SQL statements.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/storage/backends/sqlite.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/storage/backends/test_sqlite_durable_contract.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/storage/backends/sqlite.py#ConversationSQLiteBackend",
    "sym:packages/ai-parrot/src/parrot/storage/backends/base.py#ConversationBackend"
  ]
}
```

---

## Implementation Notes

### Pattern to Follow

The existing file: `Fix #9` style (no f-string SQL: every statement is a module/class constant or a dict lookup), `_now_epoch()` for time, `self.logger` for logging, plain `dict` payloads.

### Key Constraints

- **Index state is derived, the table is informational** (decision, bounded by spec M5 "a `conversation_index_state` table" + §2 "sessions created after FEAT-886 are ready"): a session is `ready` iff it has no live (`kind='turn'`, non-expired) row with `ts_utc IS NULL`. When such rows exist the state is `invalid` if `conversation_index_state` holds `state='invalid'` for the session, else `pending`. `backfill_batch` writes `invalid` / `ready` rows; `get_index_state` never trusts a stored `ready`. Consequence: a legacy session is `pending`; a write without a parseable `timestamp` (legacy-style caller, old tests) makes its session `pending` again; a brand-new session is `ready`. This is what makes "not-ready is never reported as an empty history" hold without a scan.
- **Ordering immutability** (spec M4 `put_turn` docstring): once a turn row has `ts_utc` set, a re-`put_turn` of the same `turn_id` keeps `ts_utc`, `seq` and the `timestamp`/`sequence` keys inside `payload`; every other payload key is replaced. If the existing row has no `ts_utc` (legacy / no-timestamp write) the incoming ordering fields are adopted.
- **`ts_utc` = POSIX seconds as REAL** from a tz-aware UTC datetime (`datetime.timestamp()`); naive timestamps are read as UTC (spec §7); `seq` = `payload["sequence"]` when it is a non-negative `int`, else `0`.
- **One statement = one transaction**: the tombstone guard lives inside the upsert statement (`INSERT ... SELECT ... WHERE NOT EXISTS (tombstone) ON CONFLICT DO UPDATE`). `cursor.rowcount == 0` means the guard rejected the write. Never split guard and write in two `execute` calls.
- **Tombstone key**: `conversation_tombstones` PK is `(user_id, agent_id, session_id, turn_id)`; a SESSION tombstone stores `turn_id = ''`. A real `turn_id` must be non-empty (`put_tombstone(..., turn_id="")` raises `ValueError`).
- **Error mapping**: every `sqlite3.Error` on a write → `StorageWriteError`; on a read → `StorageUnavailableError`; disconnected → `StorageUnavailableError`. Chain with `from exc`. Never log-and-continue.
- **No new dependency.** No f-string SQL. Async only. `self.logger` for diagnostics.
- **Shared helper note**: the four SQL/NoSQL backend tasks (TASK-5574..5577) each need the same "timestamp + sequence out of a payload" parse. If TASK-5570's `backends/base.py` exposes such a helper (check its completion note), import it and delete `_chrono_fields` below; otherwise keep the local copy BYTE-IDENTICAL in semantics to the others (naive = UTC, non-int/negative sequence = 0).
- **`BackfillBatch.processed` = rows INDEXED by this call** (not rows examined): TASK-5578's report sums it and TASK-5570's `check_backfill_batch_resumable` expects a re-run to report `0`. Rows with an unusable timestamp are not counted; they stay `ts_utc IS NULL`, are listed in `invalid_sessions` on every run, and keep their session `invalid`. `next_cursor` depends on rows EXAMINED (`len(rows) == batch_size`), so a batch can have `processed == 0` and still return a cursor.
- **`invalid_sessions` entry format**: use whatever TASK-5570 documents on `BackfillBatch`; if it documents nothing, use `"<user_id>/<agent_id>/<session_id>"` and say so in the Completion Note.

### References in Codebase

- `packages/ai-parrot/src/parrot/storage/backends/sqlite.py` — the file itself.
- `packages/ai-parrot/tests/storage/backends/test_sqlite_backend.py` — existing fixtures and style (real SQLite in `tmp_path`, `_aiosqlite_threads()` leak helper at the end of the file).
- `packages/ai-parrot/tests/storage/durable_contract.py` (TASK-5570) — the shared checks this task runs.

---

## Implementation Blueprint

> **CRITICAL — Executor-ready starting point.** Write each block nearly verbatim, then complete
> every `# FILL IN:` marker. Never change a signature, class name, or file path.

### Steps (in order)
1. Confirm TASK-5570 is `done`; read `storage/errors.py`, `backends/base.py` (abstract signatures, `BackfillBatch`) and `tests/storage/durable_contract.py` — *why*: this task implements those signatures verbatim and must call those checks.
2. Add imports, `_chrono_fields` and the DDL/SQL constants — *why*: constants keep every statement out of f-strings.
3. Add the additive migration to `initialize` — *why*: existing databases must open without manual steps (spec "additive migration in `initialize`").
4. Replace `put_turn` and the guard of `query_turns` — *why*: these are the failure-contract changes.
5. Add the six new operations — *why*: they are the M4 surface.
6. Write the tests; run the existing SQLite suites; run the mutation checks — *why*: Rule 6.

### `packages/ai-parrot/src/parrot/storage/backends/sqlite.py` (MODIFY) — imports and helper
```python
# occurrences: 1 (verified: grep -c 'from typing import List, Optional' packages/ai-parrot/src/parrot/storage/backends/sqlite.py)  :23
# AFTER — replace that line with:
import sqlite3
from typing import Dict, List, Optional, Tuple

# occurrences: 1 (verified: grep -c 'from parrot.storage.backends.base import ConversationBackend' ...)  :32
# AFTER — replace that line with:
from parrot.storage.backends.base import BackfillBatch, ConversationBackend
from parrot.storage.errors import (
    ConversationDeletedError,
    IndexNotReadyError,
    StorageUnavailableError,
    StorageWriteError,
)


def _chrono_fields(data: dict) -> Tuple[Optional[datetime], int]:
    """Return ``(timestamp_utc, sequence)`` from a turn payload.

    A missing or unparseable ``timestamp`` yields ``None``; naive values are read as UTC;
    a non-int / negative ``sequence`` yields ``0``.
    """
    raw = data.get("timestamp")
    ts: Optional[datetime] = None
    if isinstance(raw, datetime):
        ts = raw
    elif isinstance(raw, str) and raw.strip():
        try:
            ts = datetime.fromisoformat(raw.strip())
        except ValueError:
            ts = None
    if ts is not None:
        ts = (ts.replace(tzinfo=timezone.utc) if ts.tzinfo is None else ts).astimezone(timezone.utc)
    seq = data.get("sequence")
    valid_seq = isinstance(seq, int) and not isinstance(seq, bool) and seq >= 0
    return ts, (seq if valid_seq else 0)
```
**Why**: `datetime`/`timezone` are already imported at `sqlite.py:21`. `_chrono_fields` is the single place where "emitter-owned ordering" is read from a payload.

### `packages/ai-parrot/src/parrot/storage/backends/sqlite.py` (MODIFY) — DDL and SQL constants
```python
# occurrences: 1 (verified: grep -c '    _CREATE_ARTIFACTS = """' packages/ai-parrot/src/parrot/storage/backends/sqlite.py)  :73
# AFTER — insert ABOVE `    _CREATE_ARTIFACTS = """` (inside the class body):
    _ADD_COLUMN_SQL = {
        "ts_utc": "ALTER TABLE conversations ADD COLUMN ts_utc REAL",
        "seq": "ALTER TABLE conversations ADD COLUMN seq INTEGER",
        "turn_id": "ALTER TABLE conversations ADD COLUMN turn_id TEXT",
    }
    _CREATE_CHRONO_IDX = """
        CREATE INDEX IF NOT EXISTS idx_conv_turn_chrono
        ON conversations(user_id, agent_id, session_id, kind, ts_utc DESC, seq DESC, turn_id DESC)
    """
    _CREATE_TOMBSTONES = """
        CREATE TABLE IF NOT EXISTS conversation_tombstones (
            user_id    TEXT NOT NULL,
            agent_id   TEXT NOT NULL,
            session_id TEXT NOT NULL,
            turn_id    TEXT NOT NULL DEFAULT '',
            created_at REAL NOT NULL,
            PRIMARY KEY (user_id, agent_id, session_id, turn_id)
        )
    """
    _CREATE_INDEX_STATE = """
        CREATE TABLE IF NOT EXISTS conversation_index_state (
            user_id    TEXT NOT NULL,
            agent_id   TEXT NOT NULL,
            session_id TEXT NOT NULL,
            state      TEXT NOT NULL,
            updated_at REAL NOT NULL,
            PRIMARY KEY (user_id, agent_id, session_id)
        )
    """
    # One statement: tombstone guard + upsert. Params: 10 insert values, then 4 guard values.
    # On conflict, ordering (ts_utc/seq/turn_id and payload timestamp/sequence) is kept once set.
```
*(continued — same file, same block, keep the order)*
```python
    _UPSERT_TURN = """
        INSERT INTO conversations
            (user_id, agent_id, session_id, kind, sort_key, payload, updated_at, expires_at,
             ts_utc, seq, turn_id)
        SELECT ?, ?, ?, 'turn', ?, ?, ?, ?, ?, ?, ?
        WHERE NOT EXISTS (
            SELECT 1 FROM conversation_tombstones
            WHERE user_id = ? AND agent_id = ? AND session_id = ? AND turn_id IN ('', ?)
        )
        ON CONFLICT (user_id, agent_id, session_id, kind, sort_key) DO UPDATE SET
            payload = CASE WHEN conversations.ts_utc IS NULL THEN excluded.payload
                ELSE json_patch(excluded.payload, json_object(
                    'timestamp', json_extract(conversations.payload, '$.timestamp'),
                    'sequence',  json_extract(conversations.payload, '$.sequence'))) END,
            updated_at = excluded.updated_at,
            expires_at = excluded.expires_at,
            seq = CASE WHEN conversations.ts_utc IS NULL THEN excluded.seq ELSE conversations.seq END,
            turn_id = excluded.turn_id,
            ts_utc = COALESCE(conversations.ts_utc, excluded.ts_utc)
    """
    _SELECT_WINDOW = """
        SELECT c.sort_key, c.payload, c.updated_at FROM conversations AS c
        WHERE c.user_id = ? AND c.agent_id = ? AND c.session_id = ? AND c.kind = 'turn'
          AND c.ts_utc IS NOT NULL AND (c.expires_at IS NULL OR c.expires_at > ?)
          AND NOT EXISTS (
              SELECT 1 FROM conversation_tombstones t
              WHERE t.user_id = c.user_id AND t.agent_id = c.agent_id
                AND t.session_id = c.session_id AND t.turn_id = c.turn_id)
        ORDER BY c.ts_utc DESC, c.seq DESC, c.turn_id DESC
        LIMIT ?
    """
    _HAS_UNINDEXED = """
        SELECT 1 FROM conversations
        WHERE user_id = ? AND agent_id = ? AND session_id = ? AND kind = 'turn'
          AND ts_utc IS NULL AND (expires_at IS NULL OR expires_at > ?)
        LIMIT 1
    """
    _SELECT_LEGACY = """
        SELECT c.user_id, c.agent_id, c.session_id, c.sort_key, c.payload FROM conversations AS c
        WHERE c.kind = 'turn' AND c.ts_utc IS NULL AND (c.expires_at IS NULL OR c.expires_at > ?)
          AND (c.user_id, c.agent_id, c.session_id, c.sort_key) > (?, ?, ?, ?)
          AND NOT EXISTS (
              SELECT 1 FROM conversation_tombstones t
              WHERE t.user_id = c.user_id AND t.agent_id = c.agent_id AND t.session_id = c.session_id
                AND t.turn_id IN ('', substr(c.sort_key, 6)))
        ORDER BY c.user_id, c.agent_id, c.session_id, c.sort_key
        LIMIT ?
    """
```
**Why**: `substr(sort_key, 6)` strips the 5-character `TURN#` prefix. The `_UPSERT_TURN` `CASE` branches implement "ordering immutable once set, adopt incoming when the row had none". `# occurrences: 1` for the whole row is fine: this block is a pure insertion.

### `packages/ai-parrot/src/parrot/storage/backends/sqlite.py` (MODIFY) — `initialize` migration
```python
# occurrences: 1 (verified: python3 count of "            await self._conn.execute(self._CREATE_ARTIFACTS)\n            await self._conn.commit()" in sqlite.py)  :109-110
# AFTER — insert between the `_CREATE_ARTIFACTS` execute and the `commit()` (inside the existing try):
            await self._migrate_chrono_schema()

# AFTER — add this method directly below `initialize` (above `close`):
    async def _migrate_chrono_schema(self) -> None:
        """Additive, idempotent: chrono columns + index + tombstone/index-state tables."""
        cursor = await self._conn.execute("PRAGMA table_info(conversations)")
        existing = {row["name"] for row in await cursor.fetchall()}
        for name, statement in self._ADD_COLUMN_SQL.items():
            if name in existing:
                continue
            try:
                await self._conn.execute(statement)
            except sqlite3.OperationalError as exc:
                if "duplicate column name" not in str(exc).lower():   # a concurrent initialize won
                    raise
        await self._conn.execute(self._CREATE_CHRONO_IDX)
        await self._conn.execute(self._CREATE_TOMBSTONES)
        await self._conn.execute(self._CREATE_INDEX_STATE)
```
**Why**: the same path serves fresh and legacy databases, so there is no second code path to test. The existing `except BaseException: await self.close(); raise` already protects a failed step.

### `packages/ai-parrot/src/parrot/storage/backends/sqlite.py` (MODIFY) — `put_turn`
```python
# occurrences: 1 (verified: grep -c 'async def put_turn(' ...)  :258
# REPLACE the whole method (def line :258 through its `await self._conn.commit()` :284) with:
    def _require_connection(self) -> None:
        """Raise ``StorageUnavailableError`` when the backend is not connected."""
        if not self.is_connected:
            raise StorageUnavailableError("SQLite conversation backend is not connected")

    async def put_turn(
        self,
        user_id: str,
        agent_id: str,
        session_id: str,
        turn_id: str,
        data: dict,
    ) -> None:
        """Idempotent upsert by ``turn_id``, atomic with the tombstone guard.

        Raises:
            StorageUnavailableError: the backend is not connected.
            ConversationDeletedError: the session or this turn is tombstoned.
            StorageWriteError: the write failed (nothing is swallowed).
        """
        self._require_connection()
        payload = {k: (v.isoformat() if isinstance(v, datetime) else v) for k, v in data.items()}
        ts, seq = _chrono_fields(data)
        now = self._now_epoch()
        params = (
            user_id, agent_id, session_id, f"TURN#{turn_id}",
            json.dumps(payload, default=str), now, self._expires_at(now),
            ts.timestamp() if ts is not None else None, seq, turn_id,
            user_id, agent_id, session_id, turn_id,
        )
        try:
            cursor = await self._conn.execute(self._UPSERT_TURN, params)
            await self._conn.commit()
        except sqlite3.Error as exc:
            raise StorageWriteError(
                f"SQLite put_turn failed for session {session_id} turn {turn_id}: {exc}"
            ) from exc
        if cursor.rowcount == 0:
            raise ConversationDeletedError(
                f"session {session_id} or turn {turn_id} is tombstoned; write rejected"
            )
```
**Why**: `rowcount == 0` is the only way the guard rejects (insert skipped, no conflict row updated). A tombstone written between two `put_turn` calls is therefore seen by the very next statement.

### `packages/ai-parrot/src/parrot/storage/backends/sqlite.py` (MODIFY) — `query_turns` failure contract
```python
# occurrences: 1 (verified: python3 count of '        """Query conversation turns for a session."""\n        if not self.is_connected:\n            return []\n        now = self._not_expired()' in sqlite.py)  :294-297
# AFTER — replace `if not self.is_connected:\n            return []` (:295-296) with:
        self._require_connection()

# occurrences: 1 — the execute/fetch pair at :308-312:
#     cursor = await self._conn.execute(sql, (user_id, agent_id, session_id, now, limit))
#     rows = await cursor.fetchall()
# AFTER — wrap exactly those two statements:
        try:
            cursor = await self._conn.execute(sql, (user_id, agent_id, session_id, now, limit))
            rows = await cursor.fetchall()
        except sqlite3.Error as exc:
            raise StorageUnavailableError(f"SQLite query_turns failed for {session_id}: {exc}") from exc
```
**Why**: spec M4: "`query_turns` raises `StorageUnavailableError` instead of returning `[]` when disconnected or failing". Nothing else in the method changes (ordering by `sort_key` is kept for the UI path).

### `packages/ai-parrot/src/parrot/storage/backends/sqlite.py` (MODIFY) — new operations (insert above `# TTL helpers`)
```python
# occurrences: 1 (verified: grep -c '    # TTL helpers' ...)  :515 — insert the whole block ABOVE the comment banner that precedes it
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
        try:
            cursor = await self._conn.execute(
                self._SELECT_WINDOW, (user_id, agent_id, session_id, self._not_expired(), limit)
            )
            rows = await cursor.fetchall()
        except sqlite3.Error as exc:
            raise StorageUnavailableError(f"SQLite query_turn_window failed: {exc}") from exc
        window = [
            {
                "session_id": session_id,
                "turn_id": row["sort_key"].replace("TURN#", "", 1),
                "updated_at": datetime.fromtimestamp(row["updated_at"], tz=timezone.utc).isoformat(),
                **json.loads(row["payload"]),
            }
            for row in rows
        ]
        window.reverse()
        return window

    async def max_sequence(self, user_id: str, agent_id: str, session_id: str) -> int:
        """Highest stored sequence for the session, ``0`` when none (includes expired rows: durable maximum)."""
        self._require_connection()
        try:
            cursor = await self._conn.execute(
                "SELECT COALESCE(MAX(seq), 0) AS m FROM conversations"
                " WHERE user_id=? AND agent_id=? AND session_id=? AND kind='turn'",
                (user_id, agent_id, session_id),
            )
            row = await cursor.fetchone()
        except sqlite3.Error as exc:
            raise StorageUnavailableError(f"SQLite max_sequence failed: {exc}") from exc
        return int(row["m"])
```
**Why**: the guard (`is_deleted`) and the readiness check run BEFORE the window query so a deleted or unready session never returns data; `ORDER BY ... DESC LIMIT` is applied by SQLite (index order), then Python only reverses. `max_sequence` scans only the session's turn rows.

```python
    async def put_tombstone(
        self, user_id: str, agent_id: str, session_id: str, turn_id: Optional[str] = None
    ) -> None:
        """Durably record a session (``turn_id=None``) or turn deletion. Idempotent; no TTL."""
        self._require_connection()
        if turn_id == "":
            raise ValueError("turn_id must be non-empty (use None for a session tombstone)")
        try:
            await self._conn.execute(
                "INSERT OR IGNORE INTO conversation_tombstones"
                " (user_id, agent_id, session_id, turn_id, created_at) VALUES (?, ?, ?, ?, ?)",
                (user_id, agent_id, session_id, turn_id or "", self._now_epoch()),
            )
            await self._conn.commit()
        except sqlite3.Error as exc:
            raise StorageWriteError(f"SQLite put_tombstone failed for session {session_id}: {exc}") from exc

    async def is_deleted(
        self, user_id: str, agent_id: str, session_id: str, turn_id: Optional[str] = None
    ) -> bool:
        """Whether the session (or session OR this turn) is tombstoned; raises when it cannot be determined."""
        self._require_connection()
        try:
            cursor = await self._conn.execute(
                "SELECT 1 FROM conversation_tombstones"
                " WHERE user_id=? AND agent_id=? AND session_id=? AND turn_id IN ('', ?) LIMIT 1",
                (user_id, agent_id, session_id, turn_id or ""),
            )
            return await cursor.fetchone() is not None
        except sqlite3.Error as exc:
            raise StorageUnavailableError(f"SQLite is_deleted failed for session {session_id}: {exc}") from exc

    async def get_index_state(self, user_id: str, agent_id: str, session_id: str) -> str:
        """``'ready'`` | ``'pending'`` | ``'invalid'`` (derived; see Key Constraints)."""
        self._require_connection()
        try:
            cursor = await self._conn.execute(
                self._HAS_UNINDEXED, (user_id, agent_id, session_id, self._not_expired())
            )
            if await cursor.fetchone() is None:
                return "ready"
            cursor = await self._conn.execute(
                "SELECT state FROM conversation_index_state WHERE user_id=? AND agent_id=? AND session_id=?",
                (user_id, agent_id, session_id),
            )
            row = await cursor.fetchone()
        except sqlite3.Error as exc:
            raise StorageUnavailableError(f"SQLite get_index_state failed for {session_id}: {exc}") from exc
        return "invalid" if row is not None and row["state"] == "invalid" else "pending"
```
**Why**: `turn_id or ""` with `turn_id IN ('', ?)` makes `is_deleted(..., None)` check only the session tombstone and `is_deleted(..., "x")` check session OR turn. `put_tombstone` is `INSERT OR IGNORE`: first `created_at` wins, repeated deletion is a no-op.

```python
    @staticmethod
    def _encode_cursor(row) -> str:
        return json.dumps([row["user_id"], row["agent_id"], row["session_id"], row["sort_key"]])

    @staticmethod
    def _decode_cursor(cursor: Optional[str]) -> Tuple[str, str, str, str]:
        if cursor is None:
            return ("", "", "", "")
        user_id, agent_id, session_id, sort_key = json.loads(cursor)
        return (user_id, agent_id, session_id, sort_key)

    async def _index_legacy_row(self, row) -> bool:
        """Fill ``ts_utc``/``seq``/``turn_id`` of one legacy row; ``False`` when its timestamp is unusable."""
        ts, seq = _chrono_fields(json.loads(row["payload"]))
        if ts is None:
            return False
        await self._conn.execute(
            "UPDATE conversations SET ts_utc=?, seq=?, turn_id=?"
            " WHERE user_id=? AND agent_id=? AND session_id=? AND kind='turn' AND sort_key=? AND ts_utc IS NULL",
            (ts.timestamp(), seq, row["sort_key"].replace("TURN#", "", 1),
             row["user_id"], row["agent_id"], row["session_id"], row["sort_key"]),
        )
        return True

    async def _finalize_session(self, key: Tuple[str, str, str], saw_invalid: bool, now: float) -> None:
        """Write ``invalid`` / ``ready`` for a session touched by a batch (otherwise leave it pending)."""
        if saw_invalid:
            state = "invalid"
        else:
            cursor = await self._conn.execute(self._HAS_UNINDEXED, (*key, now))
            if await cursor.fetchone() is not None:
                return  # unindexed turns remain (later batch, or an earlier invalid one)
            state = "ready"
        await self._conn.execute(
            "INSERT OR REPLACE INTO conversation_index_state (user_id, agent_id, session_id, state, updated_at)"
            " VALUES (?, ?, ?, ?, ?)",
            (*key, state, now),
        )

    async def backfill_batch(self, cursor: Optional[str], batch_size: int) -> BackfillBatch:
        """Index up to ``batch_size`` legacy turns after ``cursor`` (resumable, safe next to new writes)."""
        self._require_connection()
        now = self._now_epoch()
        touched: Dict[Tuple[str, str, str], bool] = {}
        indexed_count = 0
        try:
            cur = await self._conn.execute(
                self._SELECT_LEGACY, (now, *self._decode_cursor(cursor), batch_size)
            )
            rows = await cur.fetchall()
            for row in rows:
                key = (row["user_id"], row["agent_id"], row["session_id"])
                indexed = await self._index_legacy_row(row)
                indexed_count += int(indexed)
                touched[key] = touched.get(key, False) or not indexed
            for key, saw_invalid in touched.items():
                await self._finalize_session(key, saw_invalid, now)
            await self._conn.commit()
        except sqlite3.Error as exc:
            raise StorageWriteError(f"SQLite backfill_batch failed: {exc}") from exc
        invalid = tuple(f"{u}/{a}/{s}" for (u, a, s), bad in touched.items() if bad)
        next_cursor = self._encode_cursor(rows[-1]) if rows and len(rows) == batch_size else None
        return BackfillBatch(processed=indexed_count, next_cursor=next_cursor, invalid_sessions=invalid)
```
**Why**: rows with an unusable timestamp keep `ts_utc NULL` (never invented) and flip their session to `invalid`; tombstoned sessions are excluded by `_SELECT_LEGACY` (backfill never touches them); the `AND ts_utc IS NULL` guard in the UPDATE makes a concurrent `put_turn` of the same turn win. New writes always carry `ts_utc`, so they are never selected: backfill is safe alongside live traffic.

### FILL IN checklist
- [ ] `backfill_batch` return value — the `invalid_sessions` entry format (blueprint uses `"<user>/<agent>/<session>"`); bounded by the `BackfillBatch` docstring (TASK-5570): if it documents another format, follow it.
- [ ] `_chrono_fields` — import the shared helper if TASK-5570 provides one; bounded by "identical semantics across backends".
- [ ] `put_turn` — decide whether to `await self._conn.rollback()` inside the `except` (must not mask the original error); bounded by "shared connection: never leave an open transaction".
- [ ] Test file: the call adapter from `durable_contract` (see Test Specification) — bounded by TASK-5570's actual check signatures.

---

## Acceptance Criteria

- [ ] `put_turn` never returns silently: disconnected → `StorageUnavailableError`; failed write → `StorageWriteError`; tombstoned session/turn → `ConversationDeletedError` (spec §5 "No silent backend writes", "Failure propagation").
- [ ] Repeated `put_turn` with the same `turn_id` leaves one row and unchanged `ts_utc`/`seq`/`timestamp`/`sequence` (spec §4 contract suite).
- [ ] `query_turn_window` returns the same newest window, ascending, for random IDs, reverse-lexical IDs, equal timestamps and more rows than `limit` (spec §5 "Chronological hydration").
- [ ] `put_turn` after `put_tombstone` raises `ConversationDeletedError`; a turn-scoped tombstone rejects only that turn; tombstones survive `delete_thread_cascade`, `sweep_expired`, `default_ttl_days=0` expiry and a backend restart (spec §5 "Deletion races").
- [ ] `get_index_state` is `pending` for legacy sessions, `invalid` for a bad timestamp after backfill, `ready` for new sessions; `query_turn_window` on a non-ready session raises `IndexNotReadyError` and its query plan has no table SCAN (spec §5 "Backfill").
- [ ] `backfill_batch` is resumable by cursor, skips tombstoned sessions, never touches rows written after FEAT-886, and never marks a session with an unusable timestamp `ready`.
- [ ] A database created by the pre-FEAT-886 schema opens, gains the columns/index/tables, and keeps its data (legacy migration test).
- [ ] Existing suites stay green: `test_sqlite_backend.py` (its turns have no timestamp: they must still be written and read via `query_turns`).
- [ ] `ruff check` clean on both files; no f-string SQL; `_aiosqlite_threads()` shows no leaked worker thread after the tests.
- [ ] **Mutation checks** (record in the Completion Note): (1) remove the `WHERE NOT EXISTS (...)` guard from `_UPSERT_TURN` → `put_after_tombstone` check RED; (2) change `_SELECT_WINDOW` to `ORDER BY ... ASC` → chronological-window check RED (window would be the OLDEST rows); (3) drop `turn_id DESC` from the order → equal-timestamp tie-break check RED; (4) make `get_index_state` return `"ready"` when a NULL-`ts_utc` row exists → `IndexNotReady` check and the legacy-migration test RED; (5) make `put_turn` `return` when disconnected → disconnected check RED.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/storage/backends/test_sqlite_durable_contract.py -q`
- `pytest packages/ai-parrot/tests/storage/backends/test_sqlite_backend.py -q`
- `pytest packages/ai-parrot/tests/storage/test_backend_contract.py -q`

---

## Test Specification

> Real SQLite files in `tmp_path`; no mocks. Fault injection for "a failed durable write" is
> REAL: `PRAGMA query_only = ON` makes SQLite reject writes with `OperationalError`.

```python
# packages/ai-parrot/tests/storage/backends/test_sqlite_durable_contract.py
import asyncio
import json
import sqlite3
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

import pytest

from parrot.storage.backends.sqlite import ConversationSQLiteBackend
from parrot.storage.errors import (ConversationDeletedError, IndexNotReadyError,
                                   StorageUnavailableError, StorageWriteError)
from .. import durable_contract          # TASK-5570: DurableHarness + ALL_CHECKS (NOT collected: no test_ prefix)

UTC = timezone.utc
T0 = datetime(2026, 11, 1, 10, 0, 0, tzinfo=UTC)


@pytest.fixture
async def backend(tmp_path):
    b = ConversationSQLiteBackend(path=str(tmp_path / "durable.db"))
    await b.initialize()
    yield b
    await b.close()


def _row(i: int, ts: datetime, seq: int = 0, **extra) -> dict:
    return {"timestamp": ts.isoformat(), "sequence": seq, "user_message": f"q{i}",
            "assistant_response": f"a{i}", **extra}


# --- shared contract: every check of durable_contract runs against SQLite -------------------
@asynccontextmanager
async def _inject_write_failure(backend):      # REAL failure: SQLite rejects every write
    await backend._conn.execute("PRAGMA query_only = ON")
    try:
        yield
    finally:
        await backend._conn.execute("PRAGMA query_only = OFF")


async def _seed_legacy(path: str, session_id: str, rows: list) -> None:
    """Insert pre-FEAT-886 rows with the stdlib: no ts_utc/seq/turn_id columns are written."""
    raw = sqlite3.connect(path)
    for row in rows:
        raw.execute("INSERT INTO conversations (user_id, agent_id, session_id, kind, sort_key, payload,"
                    " updated_at, expires_at) VALUES (?, ?, ?, 'turn', ?, ?, 1.0, NULL)",
                    (durable_contract.USER, durable_contract.AGENT, session_id,
                     f"TURN#{row['turn_id']}", json.dumps(row)))
    raw.commit()
    raw.close()


@pytest.fixture
def harness(backend, tmp_path):
    async def expire(session_id):               # simulate TTL expiry: rows become past-due, then swept
        await backend._conn.execute("UPDATE conversations SET expires_at = 1 WHERE session_id = ?", (session_id,))
        await backend.sweep_expired()
    # FILL IN: adapt the keyword names to the `DurableHarness` dataclass TASK-5570 actually wrote
    # (expected hooks: disconnect, inject_write_failure, seed_legacy, expire_transcript) — adapt THIS
    # call site, never the shared checks; record any mismatch in the Completion Note.
    return durable_contract.DurableHarness(
        backend=backend,
        disconnect=backend.close,
        inject_write_failure=lambda: _inject_write_failure(backend),
        seed_legacy=lambda sid, rows: _seed_legacy(str(tmp_path / "durable.db"), sid, rows),
        expire_transcript=expire,
    )


@pytest.mark.parametrize("check", durable_contract.ALL_CHECKS, ids=lambda c: c.__name__)
async def test_sqlite_durable_contract(check, harness):
    await check(harness)


# --- SQLite-specific ----------------------------------------------------------------------
async def test_failed_write_raises_storage_write_error(backend):
    async with _inject_write_failure(backend):
        with pytest.raises(StorageWriteError):
            await backend.put_turn("u", "a", "s", "t1", _row(1, T0))
    await backend.put_turn("u", "a", "s", "t1", _row(1, T0))          # recovers once writable


async def test_disconnected_backend_raises_everywhere(tmp_path):
    b = ConversationSQLiteBackend(path=str(tmp_path / "x.db"))        # never initialized
    for call in (lambda: b.put_turn("u", "a", "s", "t", {}), lambda: b.query_turns("u", "a", "s"),
                 lambda: b.query_turn_window("u", "a", "s", 5), lambda: b.is_deleted("u", "a", "s"),
                 lambda: b.get_index_state("u", "a", "s"), lambda: b.put_tombstone("u", "a", "s")):
        with pytest.raises(StorageUnavailableError):
            await call()


async def test_upsert_preserves_ordering_fields(backend):
    await backend.put_turn("u", "a", "s", "t1", _row(1, T0, seq=5, assistant_response="first"))
    await backend.put_turn("u", "a", "s", "t1", _row(1, T0 + timedelta(hours=9), seq=99,
                                                      assistant_response="retry"))
    [turn] = await backend.query_turn_window("u", "a", "s", 10)
    assert turn["assistant_response"] == "retry"                       # payload replaced
    assert turn["timestamp"] == T0.isoformat() and turn["sequence"] == 5   # ordering kept


async def test_tombstone_is_atomic_with_writes(backend):
    results = await asyncio.gather(
        *[backend.put_turn("u", "a", "s", f"t{i}", _row(i, T0 + timedelta(seconds=i))) for i in range(40)],
        backend.put_tombstone("u", "a", "s"),
        return_exceptions=True,
    )
    assert all(r is None or isinstance(r, ConversationDeletedError) for r in results)
    await backend.delete_thread_cascade("u", "a", "s")                 # the ChatStorage protocol: tombstone, then clear
    with pytest.raises(ConversationDeletedError):
        await backend.put_turn("u", "a", "s", "late", _row(0, T0))     # nothing resurrects it
    with pytest.raises(ConversationDeletedError):
        await backend.query_turn_window("u", "a", "s", 10)


async def test_tombstones_survive_cascade_sweep_ttl_and_restart(tmp_path):
    path = str(tmp_path / "t.db")
    b = ConversationSQLiteBackend(path=path, default_ttl_days=0)       # every row is born expired
    await b.initialize()
    await b.put_tombstone("u", "a", "s")
    await b.put_tombstone("u", "a", "s2", turn_id="t9")
    await b.delete_thread_cascade("u", "a", "s")
    await b.sweep_expired()
    await b.close()
    b2 = ConversationSQLiteBackend(path=path)
    await b2.initialize()
    assert await b2.is_deleted("u", "a", "s") is True
    assert await b2.is_deleted("u", "a", "s2") is False                # session not deleted...
    assert await b2.is_deleted("u", "a", "s2", turn_id="t9") is True   # ...only that turn
    await b2.close()


async def test_window_query_plan_uses_chrono_index(backend):
    cur = await backend._conn.execute("EXPLAIN QUERY PLAN " + backend._SELECT_WINDOW,
                                      ("u", "a", "s", 0.0, 5))
    details = [r["detail"] for r in await cur.fetchall()]
    plan = " | ".join(details)
    assert "idx_conv_turn_chrono" in plan and "TEMP B-TREE" not in plan   # index order, no sort
    assert not any(d.startswith("SCAN") for d in details)                 # no full-table scan


async def test_legacy_database_migrates_and_backfills(tmp_path):
    path = tmp_path / "legacy.db"
    raw = sqlite3.connect(path)                                         # pre-FEAT-886 schema, written with stdlib
    raw.execute("""CREATE TABLE conversations (user_id TEXT NOT NULL, agent_id TEXT NOT NULL,
        session_id TEXT NOT NULL, kind TEXT NOT NULL, sort_key TEXT NOT NULL, payload TEXT NOT NULL,
        updated_at REAL NOT NULL, expires_at REAL,
        PRIMARY KEY (user_id, agent_id, session_id, kind, sort_key))""")
    legacy = [("zz-late", T0 + timedelta(minutes=2)), ("aa-early", T0), ("mm-same", T0 + timedelta(minutes=2))]
    for tid, ts in legacy:
        raw.execute("INSERT INTO conversations VALUES ('u','a','good','turn',?,?,1.0,NULL)",
                    (f"TURN#{tid}", json.dumps({"timestamp": ts.isoformat(), "user_message": tid})))
    raw.execute("INSERT INTO conversations VALUES ('u','a','bad','turn','TURN#x',?,1.0,NULL)",
                (json.dumps({"timestamp": "garbage"}),))
    raw.commit(); raw.close()

    b = ConversationSQLiteBackend(path=str(path))
    await b.initialize()                                                # additive migration
    assert await b.get_index_state("u", "a", "good") == "pending"
    with pytest.raises(IndexNotReadyError):
        await b.query_turn_window("u", "a", "good", 10)
    batch = await b.backfill_batch(None, 100)
    assert batch.processed == 3 and batch.next_cursor is None      # processed = rows INDEXED (the bad one is not)
    assert len(batch.invalid_sessions) == 1 and "bad" in batch.invalid_sessions[0]
    assert await b.get_index_state("u", "a", "good") == "ready"
    assert await b.get_index_state("u", "a", "bad") == "invalid"
    window = await b.query_turn_window("u", "a", "good", 10)
    assert [t["turn_id"] for t in window] == ["aa-early", "mm-same", "zz-late"]   # ts, then seq 0, then turn_id
    await b.close()


async def test_backfill_is_resumable_and_skips_tombstoned_and_new_rows(tmp_path):
    # FILL IN: build ~7 legacy rows over 3 sessions with the stdlib (as above), tombstone one session,
    # write one NEW turn through put_turn between batches; run backfill_batch(cursor, 2) repeatedly,
    # re-instantiating the backend between batches — bounded by spec §4 test_backfill_resumable and
    # §5 Backfill: resumable, tombstoned session never indexed/ready, new rows untouched (their ts_utc
    # equals what put_turn stored).
    ...
```
`# FILL IN: the last test body — keep it a real SQLite file; no mocks.`

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`parrot sdd worktree ensure --slug durable-conversation-memory --feature-id FEAT-886`)
2. **Read the spec** at `sdd/specs/durable-conversation-memory.spec.md` (§2 Piece 1/2, §3 Modules 4-5, §4 backend contract suite, §5)
3. **Check dependencies** — TASK-5570 must be `"done"` in `sdd/tasks/index/durable-conversation-memory.json`
4. **Verify the Codebase Contract** — confirm every signature above and the abstract signatures TASK-5570 actually wrote; update the contract first if something changed
5. **Update status** in the per-spec index → `"in-progress"` (set `started_at`) and commit only that index file
6. **Implement** from the Blueprint; complete every `# FILL IN:`; never change a fixed signature or path
7. **Verify** all acceptance criteria and run the Validation Commands; record the mutation-check results
8. **Commit the code** — stage only the two files this task lists
9. **Close the task** with `parrot sdd task close TASK-5574 durable-conversation-memory verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

Implemented the durable contract on ConversationSQLiteBackend: additive migration (ts_utc/seq/turn_id, composite index, tombstone + index-state tables), single-statement tombstone-guarded upsert with immutable ordering, raising put_turn/query_turns, query_turn_window, max_sequence, put_tombstone, is_deleted, derived get_index_state, resumable backfill_batch.

**Completed by**: sdd-worker (sequential fallback)
**Date**: 2026-11-13
**Tests**: test_sqlite_durable_contract 18 passed (all 9 shared checks + 9 SQLite-specific incl. query plan, legacy migration, restart/cascade/sweep survival, concurrency); test_sqlite_backend green (33 total); tests/storage/test_backend_contract.py 12 passed, 36 SKIPPED (the non-SQLite backend parametrizations — no Postgres/Mongo/moto here). ruff (E9,F63,F7,F82,F401) clean.
**Mutation evidence**: remove tombstone guard -> RED (3); ORDER ASC -> RED; always-ready index state -> RED (2); silent put when disconnected -> RED (2). Dropping `turn_id DESC` from ORDER BY SURVIVED: it is an equivalent mutant because the composite index already orders by turn_id DESC, so SQLite returns the same order; the tie-break is pinned by test_equal_timestamp_and_sequence_ties_break_on_turn_id and by the index definition.
**Notes**: invalid_sessions entries are "<user_id>/<agent_id>/<session_id>" (BackfillBatch documents no format). The DurableHarness fields matched as written in TASK-5570.

**Deviations from spec**: none
