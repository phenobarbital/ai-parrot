# TASK-5575: Postgres backend — durable writes, ordered window, tombstones, index state

**Feature**: FEAT-886 — Durable Conversation Memory
**Spec**: `sdd/specs/durable-conversation-memory.spec.md` (Module 6)
**Status**: done
**Priority**: medium
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-5570
**Assigned-to**: unassigned

---

## Context

M4 (TASK-5570) fixes the new abstract operations of `ConversationBackend`; M5 (TASK-5574) is the
reference implementation on SQLite. This task implements the same contract on
`ConversationPostgresBackend` (asyncpg): `parrot_conversations` gains the chronological columns and
index, two new tables hold tombstones and index state, and `put_turn` takes a per-conversation
advisory lock so the tombstone check and the upsert are serialized transactionally with
`put_tombstone` (spec M6). Semantics must be IDENTICAL to the SQLite backend (same ordering key
`(timestamp, sequence, turn_id)`, same derived index state, same error mapping); only the SQL differs.

---

## Scope

- Additive migration in `initialize`: `ts_utc TIMESTAMPTZ`, `seq BIGINT`, `turn_id TEXT` on `parrot_conversations`; composite index; tables `parrot_conversation_tombstones` and `parrot_conversation_index_state`.
- `put_turn` raises instead of returning silently (`StorageUnavailableError` / `StorageWriteError` / `ConversationDeletedError`); one transaction under `pg_advisory_xact_lock` does tombstone check + upsert; ordering fields of an existing turn are never changed.
- `query_turns` raises `StorageUnavailableError` instead of returning `[]` when disconnected or failing.
- New operations: `query_turn_window`, `max_sequence`, `put_tombstone`, `is_deleted`, `get_index_state`, `backfill_batch`.
- Tests: the shared contract suite against a scratch Postgres database + Postgres-specific tests. They SKIP when `POSTGRES_TEST_DSN` is unset (repo convention, `tests/storage/conftest.py:12`).

**NOT in scope**: the ABC and `durable_contract.py` (TASK-5570); the backfill driver (TASK-5578); `delete_turn` / `delete_thread_cascade` / thread / artifact methods keep their behavior (the cascade must keep NOT touching the tombstone table); do not touch the other backends.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/storage/backends/postgres.py` | MODIFY | Schema migration, `put_turn`/`query_turns` failure contract, the six new operations |
| `packages/ai-parrot/tests/storage/backends/test_postgres_durable_contract.py` | CREATE | Shared contract suite + Postgres-specific durability tests (skip without `POSTGRES_TEST_DSN`) |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
import asyncpg                       # LAZY: postgres.py imports it inside initialize() (:104). Keep it lazy everywhere in this module —
                                     # `parrot.storage.__init__` imports this module eagerly and asyncpg is an optional dependency.
from parrot.storage.backends.base import ConversationBackend          # postgres.py:23 (verified)
# --- created by TASK-5570 (read its completion note before use) ---
from parrot.storage.backends.base import BackfillBatch
from parrot.storage.errors import (ConversationDeletedError, IndexNotReadyError, StorageError,
                                   StorageUnavailableError, StorageWriteError)
```
Verified in the installed asyncpg 0.32 (`.venv`): `asyncpg.InterfaceError`, `asyncpg.PostgresConnectionError`, `asyncpg.PostgresError`, `asyncpg.RaiseError` exist.

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/storage/backends/postgres.py
async def _set_jsonb_codec(conn) -> None                            # :30  registers dict<->jsonb (encoder=json.dumps, decoder=json.loads)
class ConversationPostgresBackend(ConversationBackend):            # :40
    _CREATE_CONVERSATIONS    # :55-67  parrot_conversations(user_id, agent_id, session_id, kind, sort_key, payload JSONB, updated_at TIMESTAMPTZ DEFAULT now(), expires_at TIMESTAMPTZ, PK(user_id, agent_id, session_id, kind, sort_key))
    _CREATE_CONV_IDX_USER_AGENT / _CREATE_CONV_IDX_GIN / _CREATE_ARTIFACTS   # :68-87
    def __init__(self, dsn: str, default_ttl_days: int = 180)      # :89  self._dsn, self._pool, self._initialized, self.logger
    async def initialize(self) -> None                             # :100  pool via asyncpg.create_pool(init=_set_jsonb_codec) :107; DDL on one connection :110-114; _initialized=True :115
    @property is_connected                                         # :130  _pool is not None and _initialized
    def _expires_at(self) -> Optional[datetime]                    # :137
    def _not_expired_cond(self) -> datetime                        # :145  now(UTC)
    def _row_to_turn(self, record) -> dict                         # :159  {"session_id","turn_id" (from sort_key),"updated_at" iso, **payload}; needs columns session_id, sort_key, payload, updated_at
    def _encode_payload(self, data: dict) -> dict                  # :182  datetime values -> isoformat (top level)
    async def put_turn(self, user_id, agent_id, session_id, turn_id, data) -> None   # :280  silent return when disconnected :288-289; INSERT ... ON CONFLICT DO UPDATE overwrite
    async def query_turns(self, user_id, agent_id, session_id, limit=10, newest_first=True) -> List[dict]  # :305  returns [] when disconnected :313-314
    async def delete_turn / delete_thread_cascade                  # :330 / :352  cascade deletes parrot_conversations + parrot_artifacts ONLY (keep it so)
```
Payload facts: the JSONB codec means `payload` reads/writes as a Python `dict` (no `json.dumps` at call sites). A turn row is `kind='turn'`, `sort_key='TURN#<turn_id>'`.
Postgres facts used: `pg_advisory_xact_lock(bigint)`, `hashtextextended(text, bigint)` (PG 11+; the module docstring already requires PG 12+), `ADD COLUMN IF NOT EXISTS` (PG 9.6+), `jsonb_strip_nulls`, row-value comparison.

### Does NOT Exist

- ~~`parrot_conversations.ts_utc` / `.seq` / `.turn_id`~~, ~~`parrot_conversation_tombstones`~~, ~~`parrot_conversation_index_state`~~ — created by this task.
- ~~`query_turn_window`, `put_tombstone`, `is_deleted`, `max_sequence`, `get_index_state`, `backfill_batch`~~ on any backend — abstract in TASK-5570; implemented here.
- ~~`BackfillBatch`~~, ~~`parrot.storage.errors`~~ — created by TASK-5570.
- ~~A TTL / `expires_at` on tombstones~~ — they live in their own table, which `delete_thread_cascade` never touches.
- ~~Module-level `import asyncpg`~~ in `postgres.py` — must stay lazy.
- ~~A Postgres sweeper for expired rows~~ — the backend only filters `expires_at` on reads; tests simulate expiry by moving `expires_at` into the past.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/storage/backends/postgres.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/storage/backends/test_postgres_durable_contract.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/storage/backends/postgres.py#ConversationPostgresBackend",
    "sym:packages/ai-parrot/src/parrot/storage/backends/base.py#ConversationBackend"
  ]
}
```

---

## Implementation Notes

### Pattern to Follow

The existing module: SQL as class constants (no f-string SQL; `Fix #9`), the pool acquired per operation (`async with self._pool.acquire() as conn`), `self.logger`, plain-dict payloads. The reference semantics are TASK-5574 (SQLite): if a behavior is unclear, match it.

### Key Constraints

- **Index state is derived** (same decision as SQLite): `ready` iff the session has no live turn row (`kind='turn'`, `expires_at IS NULL OR > now()`) with `ts_utc IS NULL`; otherwise `invalid` when `parrot_conversation_index_state` holds `state='invalid'`, else `pending`. `backfill_batch` writes `invalid` / `ready` rows; `get_index_state` never trusts a stored `ready`. A write without a parseable `timestamp` leaves `ts_utc NULL` (legacy-style callers and the existing tests keep working) and makes the session `pending`.
- **Ordering immutability**: on `ON CONFLICT`, once a row has `ts_utc` it keeps `ts_utc`, `seq` and the `timestamp`/`sequence` keys of its payload; everything else is replaced. A row without `ts_utc` adopts the incoming ordering fields.
- **Serialization**: `put_turn`, `put_tombstone` and the per-session part of `backfill_batch` each run in ONE transaction that starts with `SELECT pg_advisory_xact_lock(hashtextextended($1, 0))` on the key `"<user_id>\x1f<agent_id>\x1f<session_id>"`. That is what makes "tombstone committed" visible to every later write (spec M6: "per-conversation advisory lock").
- **Tie-break collation (important)**: `turn_id` is ordered with `COLLATE "C"` in BOTH the index and the `ORDER BY` (byte order = the code-point order SQLite, Mongo and DynamoDB give). A locale collation (`en_US.UTF-8`) would reorder equal-timestamp turns differently and break the cross-backend "same newest window" criterion. The test DB must not be created with `C` collation by accident: make the equal-timestamp check use turn ids that differ in case (`"B"`, `"a"`) so the collations disagree.
- **Time**: `ts_utc` is `TIMESTAMPTZ` (microsecond resolution), bound as a tz-aware UTC `datetime`; naive timestamps are read as UTC (spec §7); `seq` is `payload["sequence"]` when a non-negative `int`, else `0`.
- **Error mapping** (helper `_translate(exc, *, write)`): `OSError`, `asyncio.TimeoutError`, `asyncpg.InterfaceError` (includes "pool is closed"), `asyncpg.PostgresConnectionError` → `StorageUnavailableError`; any other exception → `StorageWriteError` for writes, `StorageUnavailableError` for reads. Typed `StorageError`s raised inside the transaction (e.g. `ConversationDeletedError`) pass through untouched (`except StorageError: raise` BEFORE the generic handler). Always `raise ... from exc`; nothing is swallowed.
- **`BackfillBatch.processed` = rows INDEXED by the call** (TASK-5578 sums it; TASK-5570's `check_backfill_batch_resumable` expects a re-run to report `0`); rows with an unusable timestamp stay `ts_utc NULL`, are listed in `invalid_sessions` on every run and keep their session `invalid`. `next_cursor` depends on rows EXAMINED (`len(rows) == batch_size`).
- **`invalid_sessions` entry format**: whatever TASK-5570 documents on `BackfillBatch`; otherwise `"<user_id>/<agent_id>/<session_id>"` (state it in the Completion Note).
- **`_chrono_fields`**: if TASK-5570's `backends/base.py` exposes a shared timestamp/sequence parser, import it; otherwise keep the local copy below, semantically identical to the SQLite/Mongo/DynamoDB copies.
- Async only; no new dependency; no module-level asyncpg import; Google-style docstrings; type hints.

### References in Codebase

- `packages/ai-parrot/src/parrot/storage/backends/postgres.py` — the file itself.
- `packages/ai-parrot/tests/storage/backends/test_postgres_backend.py` — existing skip pattern (`POSTGRES_TEST_DSN`) and fixtures.
- `packages/ai-parrot/tests/storage/durable_contract.py` (TASK-5570) — `DurableHarness`, `ALL_CHECKS`.
- TASK-5574 (`sdd/tasks/active/TASK-5574-sqlite-durable-backend.md`) — reference semantics.

---

## Implementation Blueprint

> **CRITICAL — Executor-ready starting point.** Write each block nearly verbatim, then complete
> every `# FILL IN:` marker. Never change a signature, class name, or file path.

### Steps (in order)
1. Confirm TASK-5570 is `done`; read `storage/errors.py`, the new abstract signatures and `tests/storage/durable_contract.py` — *why*: implemented verbatim.
2. Add imports, `_chrono_fields`, DDL/SQL constants — *why*: no f-string SQL.
3. Extend `initialize` with the migration (under a DDL advisory lock) — *why*: several pods may start together.
4. Replace `put_turn`, patch `query_turns` — *why*: failure contract.
5. Add the six operations — *why*: the M4 surface.
6. Write the tests; run mutation checks — *why*: Rule 6.

### `packages/ai-parrot/src/parrot/storage/backends/postgres.py` (MODIFY) — imports and helper
```python
# occurrences: 1 (verified: grep -c 'from typing import List, Optional' packages/ai-parrot/src/parrot/storage/backends/postgres.py)  :19
# AFTER — replace that line with:
import asyncio
from typing import Dict, List, Optional, Tuple

# occurrences: 1 (verified: grep -c 'from parrot.storage.backends.base import ConversationBackend' ...)  :23
# AFTER — replace that line with:
from parrot.storage.backends.base import BackfillBatch, ConversationBackend
from parrot.storage.errors import (
    ConversationDeletedError,
    IndexNotReadyError,
    StorageError,
    StorageUnavailableError,
    StorageWriteError,
)


def _chrono_fields(data: dict) -> Tuple[Optional[datetime], int]:
    """Return ``(timestamp_utc, sequence)`` from a turn payload (``None`` timestamp when unusable)."""
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
**Why**: `datetime`, `timedelta`, `timezone` are already imported at `postgres.py:18`.

### `packages/ai-parrot/src/parrot/storage/backends/postgres.py` (MODIFY) — DDL and SQL constants
```python
# occurrences: 1 (verified: grep -c '    def __init__(self, dsn: str, default_ttl_days: int = 180) -> None:' ...)  :89
# AFTER — insert directly ABOVE that line (inside the class body):
    _ADD_COLUMNS = (
        "ALTER TABLE parrot_conversations ADD COLUMN IF NOT EXISTS ts_utc TIMESTAMPTZ",
        "ALTER TABLE parrot_conversations ADD COLUMN IF NOT EXISTS seq BIGINT",
        "ALTER TABLE parrot_conversations ADD COLUMN IF NOT EXISTS turn_id TEXT",
    )
    _CREATE_CHRONO_IDX = """
        CREATE INDEX IF NOT EXISTS idx_parrot_conv_turn_chrono
        ON parrot_conversations (user_id, agent_id, session_id, kind, ts_utc DESC, seq DESC, turn_id COLLATE "C" DESC)
    """
    _CREATE_TOMBSTONES = """
        CREATE TABLE IF NOT EXISTS parrot_conversation_tombstones (
            user_id    TEXT NOT NULL,
            agent_id   TEXT NOT NULL,
            session_id TEXT NOT NULL,
            turn_id    TEXT NOT NULL DEFAULT '',
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (user_id, agent_id, session_id, turn_id)
        )
    """
    _CREATE_INDEX_STATE = """
        CREATE TABLE IF NOT EXISTS parrot_conversation_index_state (
            user_id    TEXT NOT NULL,
            agent_id   TEXT NOT NULL,
            session_id TEXT NOT NULL,
            state      TEXT NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (user_id, agent_id, session_id)
        )
    """
    _LOCK_SQL = "SELECT pg_advisory_xact_lock(hashtextextended($1, 0))"
    _DDL_LOCK_KEY = "parrot_conversations:ddl"
    _TOMBSTONE_SQL = (
        "SELECT 1 FROM parrot_conversation_tombstones"
        " WHERE user_id=$1 AND agent_id=$2 AND session_id=$3 AND turn_id IN ('', $4) LIMIT 1"
    )
    # $1..$9: user, agent, session, sort_key, payload, expires_at, ts_utc, seq, turn_id
```
*(continued — same file, same block, keep the order)*
```python
    _UPSERT_TURN = """
        INSERT INTO parrot_conversations
            (user_id, agent_id, session_id, kind, sort_key, payload, updated_at, expires_at,
             ts_utc, seq, turn_id)
        VALUES ($1, $2, $3, 'turn', $4, $5, now(), $6, $7, $8, $9)
        ON CONFLICT (user_id, agent_id, session_id, kind, sort_key) DO UPDATE SET
            payload = CASE WHEN parrot_conversations.ts_utc IS NULL THEN EXCLUDED.payload
                ELSE ((EXCLUDED.payload - 'timestamp' - 'sequence') || jsonb_strip_nulls(
                    jsonb_build_object('timestamp', parrot_conversations.payload->'timestamp',
                                       'sequence',  parrot_conversations.payload->'sequence'))) END,
            updated_at = now(),
            expires_at = EXCLUDED.expires_at,
            seq = CASE WHEN parrot_conversations.ts_utc IS NULL THEN EXCLUDED.seq
                       ELSE parrot_conversations.seq END,
            turn_id = EXCLUDED.turn_id,
            ts_utc = COALESCE(parrot_conversations.ts_utc, EXCLUDED.ts_utc)
    """
    _SELECT_WINDOW = """
        SELECT c.session_id, c.sort_key, c.payload, c.updated_at FROM parrot_conversations AS c
        WHERE c.user_id=$1 AND c.agent_id=$2 AND c.session_id=$3 AND c.kind='turn'
          AND c.ts_utc IS NOT NULL AND (c.expires_at IS NULL OR c.expires_at > $4)
          AND NOT EXISTS (
              SELECT 1 FROM parrot_conversation_tombstones t
              WHERE t.user_id=c.user_id AND t.agent_id=c.agent_id
                AND t.session_id=c.session_id AND t.turn_id=c.turn_id)
        ORDER BY c.ts_utc DESC, c.seq DESC, c.turn_id COLLATE "C" DESC
        LIMIT $5
    """
    _HAS_UNINDEXED = """
        SELECT 1 FROM parrot_conversations
        WHERE user_id=$1 AND agent_id=$2 AND session_id=$3 AND kind='turn'
          AND ts_utc IS NULL AND (expires_at IS NULL OR expires_at > $4) LIMIT 1
    """
    _SELECT_LEGACY = """
        SELECT c.user_id, c.agent_id, c.session_id, c.sort_key, c.payload
        FROM parrot_conversations AS c
        WHERE c.kind='turn' AND c.ts_utc IS NULL AND (c.expires_at IS NULL OR c.expires_at > $1)
          AND (c.user_id, c.agent_id, c.session_id, c.sort_key) > ($2, $3, $4, $5)
          AND NOT EXISTS (
              SELECT 1 FROM parrot_conversation_tombstones t
              WHERE t.user_id=c.user_id AND t.agent_id=c.agent_id AND t.session_id=c.session_id
                AND t.turn_id IN ('', substr(c.sort_key, 6)))
        ORDER BY c.user_id, c.agent_id, c.session_id, c.sort_key
        LIMIT $6
    """
    _INDEX_ROW_SQL = (
        "UPDATE parrot_conversations SET ts_utc=$1, seq=$2, turn_id=$3"
        " WHERE user_id=$4 AND agent_id=$5 AND session_id=$6 AND kind='turn' AND sort_key=$7"
        " AND ts_utc IS NULL"
    )
    _UPSERT_STATE_SQL = """
        INSERT INTO parrot_conversation_index_state (user_id, agent_id, session_id, state, updated_at)
        VALUES ($1, $2, $3, $4, now())
        ON CONFLICT (user_id, agent_id, session_id) DO UPDATE SET state = EXCLUDED.state, updated_at = now()
    """
```
**Why**: `substr(c.sort_key, 6)` strips the 5-character `TURN#`. `jsonb_strip_nulls` drops the `timestamp`/`sequence` keys when the stored payload had none (they are never re-invented). The `CASE` branches are the same rule as SQLite: ordering is immutable once set, adopted when absent.

### `packages/ai-parrot/src/parrot/storage/backends/postgres.py` (MODIFY) — `initialize` and helpers
```python
# occurrences: 1 (verified: python3 count of "            await conn.execute(self._CREATE_ARTIFACTS)\n        self._initialized = True" in postgres.py)  :114-115
# AFTER — insert between those two lines (still inside `async with self._pool.acquire() as conn:`):
            await self._migrate_chrono_schema(conn)

# occurrences: 1 (verified: grep -c '    def _encode_payload(self, data: dict) -> dict:' ...)  :182
# AFTER — insert directly ABOVE it:
    async def _migrate_chrono_schema(self, conn) -> None:
        """Additive, idempotent migration; serialized across pods with a transaction-scoped advisory lock."""
        async with conn.transaction():
            await conn.execute(self._LOCK_SQL, self._DDL_LOCK_KEY)
            for statement in self._ADD_COLUMNS:
                await conn.execute(statement)
            await conn.execute(self._CREATE_CHRONO_IDX)
            await conn.execute(self._CREATE_TOMBSTONES)
            await conn.execute(self._CREATE_INDEX_STATE)

    def _require_connection(self) -> None:
        """Raise ``StorageUnavailableError`` when the backend is not connected."""
        if not self.is_connected:
            raise StorageUnavailableError("Postgres conversation backend is not connected")

    @staticmethod
    def _translate(exc: BaseException, *, write: bool) -> StorageError:
        """Map a driver/transport exception to the typed storage error (never swallow)."""
        import asyncpg  # lazy: optional dependency
        transport = (OSError, asyncio.TimeoutError, asyncpg.InterfaceError, asyncpg.PostgresConnectionError)
        if isinstance(exc, transport):
            return StorageUnavailableError(f"Postgres unavailable: {exc}")
        cls = StorageWriteError if write else StorageUnavailableError
        return cls(f"Postgres operation failed: {exc}")

    @staticmethod
    def _lock_key(user_id: str, agent_id: str, session_id: str) -> str:
        return f"{user_id}\x1f{agent_id}\x1f{session_id}"
```
**Why**: the DDL lock key is a constant string so concurrent `initialize()` calls queue instead of racing on `ADD COLUMN`.

### `packages/ai-parrot/src/parrot/storage/backends/postgres.py` (MODIFY) — `put_turn` and `query_turns`
```python
# occurrences: 1 (verified: grep -c 'async def put_turn(' ...)  :280
# REPLACE the whole method (def line :280 through its closing `)` of conn.execute :303) with:
    async def put_turn(
        self,
        user_id: str,
        agent_id: str,
        session_id: str,
        turn_id: str,
        data: dict,
    ) -> None:
        """Idempotent upsert by ``turn_id``; tombstone check + upsert in one locked transaction.

        Raises:
            StorageUnavailableError: not connected / transport failure.
            ConversationDeletedError: the session or this turn is tombstoned.
            StorageWriteError: the durable write failed (nothing is swallowed).
        """
        self._require_connection()
        payload = self._encode_payload(data)
        ts, seq = _chrono_fields(data)
        try:
            async with self._pool.acquire() as conn:
                async with conn.transaction():
                    await conn.execute(self._LOCK_SQL, self._lock_key(user_id, agent_id, session_id))
                    if await conn.fetchval(self._TOMBSTONE_SQL, user_id, agent_id, session_id, turn_id):
                        raise ConversationDeletedError(
                            f"session {session_id} or turn {turn_id} is tombstoned; write rejected")
                    await conn.execute(
                        self._UPSERT_TURN, user_id, agent_id, session_id, f"TURN#{turn_id}",
                        payload, self._expires_at(), ts, seq, turn_id,
                    )
        except StorageError:
            raise
        except Exception as exc:
            raise self._translate(exc, write=True) from exc

# occurrences: 1 (verified: grep -c '# Fix #9: avoid f-string SQL — ORDER direction is boolean-derived,' ...)  :316
# In query_turns (:305-328): replace the guard at :313-314
#     if not self.is_connected:
#         return []
# with `self._require_connection()`, and wrap the fetch (:326-327)
#     async with self._pool.acquire() as conn:
#         rows = await conn.fetch(sql, user_id, agent_id, session_id, now, limit)
# AFTER:
        try:
            async with self._pool.acquire() as conn:
                rows = await conn.fetch(sql, user_id, agent_id, session_id, now, limit)
        except Exception as exc:
            raise self._translate(exc, write=False) from exc
```
**Why**: `put_turn`'s guard and write can never interleave with `put_tombstone`: both take the same advisory lock inside their transactions, so a write either commits before the tombstone (and the deletion protocol's cascade then removes it) or sees the tombstone and is rejected.

### `packages/ai-parrot/src/parrot/storage/backends/postgres.py` (MODIFY) — new operations (insert above the `# Artifacts` banner)
```python
# occurrences: 1 (verified: grep -c '    # Artifacts' ...)  :372 — insert the block ABOVE the `# ----` banner line that precedes it
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
            async with self._pool.acquire() as conn:
                rows = await conn.fetch(
                    self._SELECT_WINDOW, user_id, agent_id, session_id, self._not_expired_cond(), limit)
        except Exception as exc:
            raise self._translate(exc, write=False) from exc
        window = [self._row_to_turn(r) for r in rows]
        window.reverse()
        return window

    async def max_sequence(self, user_id: str, agent_id: str, session_id: str) -> int:
        """Highest stored sequence for the session, ``0`` when none (durable maximum)."""
        self._require_connection()
        try:
            async with self._pool.acquire() as conn:
                return int(await conn.fetchval(
                    "SELECT COALESCE(MAX(seq), 0) FROM parrot_conversations"
                    " WHERE user_id=$1 AND agent_id=$2 AND session_id=$3 AND kind='turn'",
                    user_id, agent_id, session_id))
        except Exception as exc:
            raise self._translate(exc, write=False) from exc

    async def put_tombstone(
        self, user_id: str, agent_id: str, session_id: str, turn_id: Optional[str] = None
    ) -> None:
        """Durably record a session (``turn_id=None``) or turn deletion. Idempotent; no TTL."""
        self._require_connection()
        if turn_id == "":
            raise ValueError("turn_id must be non-empty (use None for a session tombstone)")
        try:
            async with self._pool.acquire() as conn:
                async with conn.transaction():
                    await conn.execute(self._LOCK_SQL, self._lock_key(user_id, agent_id, session_id))
                    await conn.execute(
                        "INSERT INTO parrot_conversation_tombstones (user_id, agent_id, session_id, turn_id)"
                        " VALUES ($1, $2, $3, $4) ON CONFLICT DO NOTHING",
                        user_id, agent_id, session_id, turn_id or "")
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
            async with self._pool.acquire() as conn:
                row = await conn.fetchval(self._TOMBSTONE_SQL, user_id, agent_id, session_id, turn_id or "")
        except Exception as exc:
            raise self._translate(exc, write=False) from exc
        return row is not None

    async def get_index_state(self, user_id: str, agent_id: str, session_id: str) -> str:
        """``'ready'`` | ``'pending'`` | ``'invalid'`` (derived; see Key Constraints)."""
        self._require_connection()
        try:
            async with self._pool.acquire() as conn:
                unindexed = await conn.fetchval(
                    self._HAS_UNINDEXED, user_id, agent_id, session_id, self._not_expired_cond())
                if unindexed is None:
                    return "ready"
                state = await conn.fetchval(
                    "SELECT state FROM parrot_conversation_index_state"
                    " WHERE user_id=$1 AND agent_id=$2 AND session_id=$3", user_id, agent_id, session_id)
        except Exception as exc:
            raise self._translate(exc, write=False) from exc
        return "invalid" if state == "invalid" else "pending"
```
**Why**: `_TOMBSTONE_SQL` with `turn_id IN ('', $4)` and `turn_id or ""` makes `is_deleted(..., None)` check the session tombstone only and `is_deleted(..., "x")` check session OR turn. `ON CONFLICT DO NOTHING` keeps the first tombstone.

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

    async def _index_session(self, conn, key: Tuple[str, str, str], rows: list) -> Tuple[int, bool]:
        """Index one session's legacy rows under its advisory lock; returns ``(indexed, saw_invalid)``."""
        indexed, saw_invalid = 0, False
        async with conn.transaction():
            await conn.execute(self._LOCK_SQL, self._lock_key(*key))
            if await conn.fetchval(self._TOMBSTONE_SQL, *key, ""):     # tombstoned since the SELECT: leave it
                return 0, False
            for row in rows:
                ts, seq = _chrono_fields(row["payload"])
                if ts is None:
                    saw_invalid = True
                    continue
                await conn.execute(self._INDEX_ROW_SQL, ts, seq, row["sort_key"][5:], *key, row["sort_key"])
                indexed += 1
            state = "invalid" if saw_invalid else None
            if not saw_invalid and await conn.fetchval(
                    self._HAS_UNINDEXED, *key, self._not_expired_cond()) is None:
                state = "ready"
            if state is not None:
                await conn.execute(self._UPSERT_STATE_SQL, *key, state)
        return indexed, saw_invalid

    async def backfill_batch(self, cursor: Optional[str], batch_size: int) -> BackfillBatch:
        """Index up to ``batch_size`` legacy turns after ``cursor`` (resumable, safe next to new writes)."""
        self._require_connection()
        groups: Dict[Tuple[str, str, str], list] = {}
        indexed_total, invalid = 0, []
        try:
            async with self._pool.acquire() as conn:
                rows = await conn.fetch(
                    self._SELECT_LEGACY, self._not_expired_cond(), *self._decode_cursor(cursor), batch_size)
                for row in rows:
                    groups.setdefault((row["user_id"], row["agent_id"], row["session_id"]), []).append(row)
                for key, session_rows in groups.items():
                    done, bad = await self._index_session(conn, key, session_rows)
                    indexed_total += done
                    if bad:
                        invalid.append("/".join(key))
        except Exception as exc:
            raise self._translate(exc, write=True) from exc
        next_cursor = self._encode_cursor(rows[-1]) if rows and len(rows) == batch_size else None
        return BackfillBatch(processed=indexed_total, next_cursor=next_cursor, invalid_sessions=tuple(invalid))
```
**Why**: rows are examined in PK order after the cursor; a session whose legacy rows straddle two batches is finalized only when no unindexed row remains; sessions with an unusable timestamp are marked `invalid` and never `ready`; tombstoned sessions are excluded by `_SELECT_LEGACY` and re-checked under the lock. Backfill never touches rows written after FEAT-886 (they carry `ts_utc`), so it is safe next to live traffic.

### FILL IN checklist
- [ ] `_index_session` — the key tuple passed to `_TOMBSTONE_SQL` is `(user, agent, session, "")`; double-check parameter arity against the final SQL; bounded by "session tombstone only".
- [ ] `_chrono_fields` — import a shared helper if TASK-5570 provides one; bounded by "identical semantics across backends".
- [ ] `invalid_sessions` entry format — bounded by TASK-5570's `BackfillBatch` docstring.
- [ ] Test file: the `DurableHarness` keyword names (see Test Specification) — bounded by TASK-5570's actual dataclass.
- [ ] Test file: the scratch-database DSN helper for the DSN forms the CI uses (`postgresql://...`); key/value DSNs may `pytest.skip`.

---

## Acceptance Criteria

- [ ] `put_turn` never returns silently: disconnected / closed pool → `StorageUnavailableError`; failed write → `StorageWriteError`; tombstoned session or turn → `ConversationDeletedError` (spec §5 "No silent backend writes").
- [ ] Repeated `put_turn` with the same `turn_id` leaves one row with unchanged `ts_utc`/`seq` and unchanged payload `timestamp`/`sequence` (spec §4 contract suite).
- [ ] `query_turn_window` returns the same newest window, ascending, for random and reverse-lexical IDs, equal timestamps and more rows than `limit`; the plan uses `idx_parrot_conv_turn_chrono` with no Sort node (with `enable_seqscan=off`) (spec §5 "Chronological hydration").
- [ ] Concurrent `put_turn` × N and `put_tombstone` followed by `delete_thread_cascade` leave nothing visible and every later `put_turn` raises `ConversationDeletedError` (advisory-lock serialization; spec §5 "Deletion races").
- [ ] Tombstones survive `delete_thread_cascade`, `expires_at` expiry and a backend restart.
- [ ] `get_index_state`: `pending` for legacy sessions, `invalid` for a bad timestamp after backfill, `ready` for new sessions; `query_turn_window` on a non-ready session raises `IndexNotReadyError` (spec §5 "Backfill").
- [ ] `backfill_batch` is resumable by cursor, skips tombstoned sessions, ignores post-FEAT-886 rows, never marks an unusable-timestamp session `ready`.
- [ ] A database with the pre-FEAT-886 `parrot_conversations` table opens, gains columns/index/tables and keeps its data.
- [ ] The existing `test_postgres_backend.py` stays green (its turns carry no timestamp); `ruff check` clean; no module-level `import asyncpg`.
- [ ] **Mutation checks** (record in the Completion Note): (1) delete the tombstone `fetchval` guard in `put_turn` → tombstone-blocks-put check RED; (2) remove the `pg_advisory_xact_lock` execute from `put_tombstone` OR `put_turn` → the concurrency test goes RED (flaky-RED is acceptable evidence only if it fails within 20 runs: loop it); (3) change `ORDER BY ... DESC` to `ASC` in `_SELECT_WINDOW` → window check RED; (4) drop `turn_id COLLATE "C" DESC` → tie-break check RED (on a non-C-collated database; with ids `"B"`/`"a"`); (5) make `get_index_state` return `"ready"` when a NULL-`ts_utc` row exists → `IndexNotReady` check and legacy-migration test RED.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/storage/backends/test_postgres_durable_contract.py -q`
- `pytest packages/ai-parrot/tests/storage/backends/test_postgres_backend.py -q`
- `pytest packages/ai-parrot/tests/storage/test_backend_contract.py -q`

(The three Postgres-dependent suites SKIP without `POSTGRES_TEST_DSN`; run them once against a real server — e.g. `POSTGRES_TEST_DSN=postgresql://user:pw@localhost:5432/postgres` on a role that may `CREATE DATABASE` — before closing the task, and record it.)

---

## Test Specification

> Real Postgres, isolated per test in a scratch database; no mocks. A failed durable write is
> injected for real with a trigger that raises.

```python
# packages/ai-parrot/tests/storage/backends/test_postgres_durable_contract.py
import asyncio
import json
import os
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit, urlunsplit

import pytest

from parrot.storage.backends.postgres import ConversationPostgresBackend
from parrot.storage.errors import (ConversationDeletedError, IndexNotReadyError,
                                   StorageUnavailableError, StorageWriteError)
from .. import durable_contract          # TASK-5570: DurableHarness + ALL_CHECKS (NOT collected: no test_ prefix)

DSN = os.environ.get("POSTGRES_TEST_DSN")
pytestmark = pytest.mark.skipif(not DSN, reason="POSTGRES_TEST_DSN not set — skipping Postgres durable contract")

UTC = timezone.utc
T0 = datetime(2026, 11, 1, 10, 0, 0, tzinfo=UTC)
LEGACY_TABLE = """CREATE TABLE parrot_conversations (
    user_id TEXT NOT NULL, agent_id TEXT NOT NULL, session_id TEXT NOT NULL, kind TEXT NOT NULL,
    sort_key TEXT NOT NULL, payload JSONB NOT NULL, updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at TIMESTAMPTZ, PRIMARY KEY (user_id, agent_id, session_id, kind, sort_key))"""


def _dsn_for(dbname: str) -> str:
    parts = urlsplit(DSN)
    return urlunsplit(parts._replace(path=f"/{dbname}"))


@pytest.fixture
async def scratch_dsn():
    """A throw-away database per test: tombstones are retained forever by design, so isolate, don't clean."""
    import asyncpg
    name = f"parrot_durable_{uuid.uuid4().hex[:12]}"
    try:
        admin = await asyncpg.connect(DSN)
        await admin.execute(f'CREATE DATABASE "{name}"')
    except Exception as exc:                       # no CREATEDB privilege / unreachable server
        pytest.skip(f"cannot create a scratch database: {exc}")
    yield _dsn_for(name)
    await admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
    await admin.close()


@pytest.fixture
async def backend(scratch_dsn):
    b = ConversationPostgresBackend(dsn=scratch_dsn)
    await b.initialize()
    yield b
    await b.close()


async def _raw(dsn: str):
    import asyncpg
    return await asyncpg.connect(dsn)


@asynccontextmanager
async def _inject_write_failure(dsn: str):
    """REAL failure: a trigger makes every write to parrot_conversations raise."""
    conn = await _raw(dsn)
    await conn.execute("""CREATE OR REPLACE FUNCTION parrot_test_fail_write() RETURNS trigger
        LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'injected write failure'; END $$""")
    await conn.execute("CREATE TRIGGER parrot_test_fail BEFORE INSERT OR UPDATE ON parrot_conversations"
                       " FOR EACH ROW EXECUTE FUNCTION parrot_test_fail_write()")
    try:
        yield
    finally:
        await conn.execute("DROP TRIGGER parrot_test_fail ON parrot_conversations")
        await conn.close()


async def _seed_legacy(dsn: str, session_id: str, rows: list) -> None:
    conn = await _raw(dsn)
    for row in rows:
        await conn.execute(
            "INSERT INTO parrot_conversations (user_id, agent_id, session_id, kind, sort_key, payload)"
            " VALUES ($1, $2, $3, 'turn', $4, $5::jsonb)",
            durable_contract.USER, durable_contract.AGENT, session_id, f"TURN#{row['turn_id']}", json.dumps(row))
    await conn.close()


async def _expire(dsn: str, session_id: str) -> None:
    conn = await _raw(dsn)
    await conn.execute("UPDATE parrot_conversations SET expires_at = now() - interval '1 day'"
                       " WHERE session_id = $1", session_id)
    await conn.close()


@pytest.fixture
def harness(backend, scratch_dsn):
    # FILL IN: adapt the keyword names to the `DurableHarness` dataclass TASK-5570 actually wrote
    # (expected hooks: disconnect, inject_write_failure, seed_legacy, expire_transcript) — adapt THIS
    # call site, never the shared checks; record any mismatch in the Completion Note.
    return durable_contract.DurableHarness(
        backend=backend,
        disconnect=backend.close,
        inject_write_failure=lambda: _inject_write_failure(scratch_dsn),
        seed_legacy=lambda sid, rows: _seed_legacy(scratch_dsn, sid, rows),
        expire_transcript=lambda sid: _expire(scratch_dsn, sid),
    )


@pytest.mark.parametrize("check", durable_contract.ALL_CHECKS, ids=lambda c: c.__name__)
async def test_postgres_durable_contract(check, harness):
    await check(harness)


def _row(i: int, ts: datetime, seq: int = 0, **extra) -> dict:
    return {"timestamp": ts.isoformat(), "sequence": seq, "user_message": f"q{i}",
            "assistant_response": f"a{i}", **extra}


# --- Postgres-specific ----------------------------------------------------------------------
async def test_disconnected_backend_raises_everywhere(scratch_dsn):
    b = ConversationPostgresBackend(dsn=scratch_dsn)                   # never initialized
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
    assert turn["assistant_response"] == "retry"
    assert turn["timestamp"] == T0.isoformat() and turn["sequence"] == 5


async def test_tombstone_serialized_with_writes(backend):
    results = await asyncio.gather(
        *[backend.put_turn("u", "a", "s", f"t{i}", _row(i, T0 + timedelta(seconds=i))) for i in range(40)],
        backend.put_tombstone("u", "a", "s"),
        return_exceptions=True,
    )
    assert all(r is None or isinstance(r, ConversationDeletedError) for r in results)
    await backend.delete_thread_cascade("u", "a", "s")                 # tombstone first, then clear
    with pytest.raises(ConversationDeletedError):
        await backend.put_turn("u", "a", "s", "late", _row(0, T0))
    with pytest.raises(ConversationDeletedError):
        await backend.query_turn_window("u", "a", "s", 10)


async def test_tombstones_survive_cascade_expiry_and_restart(scratch_dsn):
    b = ConversationPostgresBackend(dsn=scratch_dsn)
    await b.initialize()
    await b.put_tombstone("u", "a", "s")
    await b.put_tombstone("u", "a", "s2", turn_id="t9")
    await b.delete_thread_cascade("u", "a", "s")
    await b.close()
    b2 = ConversationPostgresBackend(dsn=scratch_dsn)
    await b2.initialize()
    assert await b2.is_deleted("u", "a", "s") is True
    assert await b2.is_deleted("u", "a", "s2") is False
    assert await b2.is_deleted("u", "a", "s2", turn_id="t9") is True
    await b2.close()


async def test_window_plan_uses_chrono_index(backend):
    async with backend._pool.acquire() as conn:
        await conn.execute("SET enable_seqscan = off")                 # tiny tables: force the planner's hand
        plan = "\n".join(r[0] for r in await conn.fetch(
            "EXPLAIN " + backend._SELECT_WINDOW.replace("$1", "'u'").replace("$2", "'a'").replace(
                "$3", "'s'").replace("$4", "now()").replace("$5", "5")))
    assert "idx_parrot_conv_turn_chrono" in plan and "Sort" not in plan


async def test_legacy_table_migrates_and_backfills(scratch_dsn):
    raw = await _raw(scratch_dsn)
    await raw.execute(LEGACY_TABLE)                                     # pre-FEAT-886 schema, no chrono columns
    await raw.close()
    legacy = [("zz-late", T0 + timedelta(minutes=2)), ("aa-early", T0), ("mm-same", T0 + timedelta(minutes=2))]
    await _seed_legacy(scratch_dsn, "good", [{"turn_id": t, "timestamp": ts.isoformat()} for t, ts in legacy])
    await _seed_legacy(scratch_dsn, "bad", [{"turn_id": "x", "timestamp": "garbage"}])
    b = ConversationPostgresBackend(dsn=scratch_dsn)
    await b.initialize()                                                # additive migration
    ids = (durable_contract.USER, durable_contract.AGENT)
    assert await b.get_index_state(*ids, "good") == "pending"
    with pytest.raises(IndexNotReadyError):
        await b.query_turn_window(*ids, "good", 10)
    batch = await b.backfill_batch(None, 100)
    assert batch.processed == 3 and batch.next_cursor is None and len(batch.invalid_sessions) == 1
    assert await b.get_index_state(*ids, "good") == "ready"
    assert await b.get_index_state(*ids, "bad") == "invalid"
    window = await b.query_turn_window(*ids, "good", 10)
    assert [t["turn_id"] for t in window] == ["aa-early", "mm-same", "zz-late"]
    await b.close()


async def test_failed_write_is_typed_and_recoverable(backend, scratch_dsn):
    async with _inject_write_failure(scratch_dsn):
        with pytest.raises(StorageWriteError):
            await backend.put_turn("u", "a", "s", "t1", _row(1, T0))
    await backend.put_turn("u", "a", "s", "t1", _row(1, T0))
```
`# FILL IN: test_backfill_resumable_skips_tombstoned_and_new_rows — legacy rows over 3 sessions seeded with _seed_legacy, one session tombstoned, one NEW turn written via put_turn between batches, backfill_batch(cursor, 2) looped with a re-created backend between batches; assert the tombstoned session is never indexed/ready, the new turn's ts_utc is untouched, sum(processed) == indexable rows — bounded by spec §4 test_backfill_resumable and §5 Backfill.`

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`parrot sdd worktree ensure --slug durable-conversation-memory --feature-id FEAT-886`)
2. **Read the spec** at `sdd/specs/durable-conversation-memory.spec.md` (§2 Piece 1/2, §3 Modules 4 and 6, §4 backend contract suite, §5) and TASK-5574 (reference semantics)
3. **Check dependencies** — TASK-5570 must be `"done"` in `sdd/tasks/index/durable-conversation-memory.json`
4. **Verify the Codebase Contract** — confirm every signature above and the abstract signatures TASK-5570 wrote; update the contract first if something changed
5. **Update status** in the per-spec index → `"in-progress"` (set `started_at`) and commit only that index file
6. **Implement** from the Blueprint; complete every `# FILL IN:`; never change a fixed signature or path
7. **Verify** all acceptance criteria and run the Validation Commands against a real Postgres; record the mutation-check results
8. **Commit the code** — stage only the two files this task lists
9. **Close the task** with `parrot sdd task close TASK-5575 durable-conversation-memory verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

Implemented the durable contract on ConversationPostgresBackend exactly per the blueprint (additive migration under a DDL advisory lock, advisory-lock-serialized put_turn/put_tombstone/backfill sessions, COLLATE "C" tie-break, derived index state, typed error translation, lazy asyncpg).

**Completed by**: sdd-worker (sequential fallback)
**Date**: 2026-11-13
**STATUS: done-with-issues — NOT EXERCISED AGAINST A REAL POSTGRES.** No server or POSTGRES_TEST_DSN exists in this environment. What ran: import/abstractness check (backend is instantiable, no abstract methods left), ruff (E9,F63,F7,F82,F401: only the pre-existing unused-`timedelta` module import is noted), and the new test file collects; all 22 tests of test_postgres_durable_contract.py + test_postgres_backend.py SKIP (POSTGRES_TEST_DSN not set). The SQL has therefore never been executed.
**Mutation checks**: not run (they need the server).
**Action for a reviewer**: run `POSTGRES_TEST_DSN=postgresql://… pytest -p no:xdist packages/ai-parrot/tests/storage/backends/test_postgres_durable_contract.py test_postgres_backend.py` on a role with CREATE DATABASE, then the five mutation checks of the Acceptance Criteria.
**Notes**: invalid_sessions entries are "<user_id>/<agent_id>/<session_id>". The DurableHarness fields matched TASK-5570.

**Deviations from spec**: none
