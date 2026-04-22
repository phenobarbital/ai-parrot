# TASK-826: SQLite Backend Implementation

**Feature**: FEAT-116 — Pluggable Storage Backends for Conversations & Artifacts
**Spec**: `sdd/specs/dynamodb-fallback-redis.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-822
**Assigned-to**: unassigned

---

## Context

First-class, zero-dependency storage backend for data-analyst laptops and CI.
Uses `asyncdb[sqlite]` (which wraps `aiosqlite`) for async SQLite access.
Critical because this is the only backend that works with no Docker, no
server, and no credentials — it must unblock local development per spec §1
case (1) and (2).

Implements **Module 4** of the spec (§3). Parallel with TASK-827 and TASK-828.

---

## Scope

- Create `packages/ai-parrot/src/parrot/storage/backends/sqlite.py` containing `ConversationSQLiteBackend(ConversationBackend)`.
- Constructor: `__init__(self, path: str, default_ttl_days: int = 180) -> None`. Default `path` value is computed by the factory (TASK-829), not here.
- `initialize()` opens the asyncdb `sqlite` driver connection and creates the two tables + two indexes from spec §2 "Backend-Specific Storage Layouts — SQLite". Use `IF NOT EXISTS` for idempotency.
- Implement all 14 abstract methods (11 CRUD + `initialize`/`close`/`is_connected`) using the schema from spec §2:
  - `conversations(user_id, agent_id, session_id, kind, sort_key, payload TEXT, updated_at REAL, expires_at REAL)` with composite PK.
  - `artifacts(user_id, agent_id, session_id, artifact_id, payload TEXT, updated_at REAL, expires_at REAL)` with composite PK.
- TTL strategy: store `expires_at = updated_at + default_ttl_days * 86400` on write; filter with `WHERE (expires_at IS NULL OR expires_at > ?)` on read paths. Add a public `async def sweep_expired() -> int` helper that runs `DELETE FROM ... WHERE expires_at <= now()` and returns the delete count. The sweeper is NOT called automatically in v1 — callers invoke it when desired (per open Q answer #2).
- Serialize payload dicts with `json.dumps(default=str)`; deserialize with `json.loads(row["payload"])`. Merge the `session_id`, `user_id`, `agent_id`, `turn_id`, `artifact_id`, `updated_at`, `expires_at` back into the returned dict so callers see the same shape that DynamoDB returns (with keys like `session_id`, `turn_id`, etc.).
- `delete_thread_cascade` and `delete_session_artifacts` must delete every row matching `(user_id, agent_id, session_id)` in both tables; return the count.
- Write unit tests at `packages/ai-parrot/tests/storage/backends/test_sqlite_backend.py`. Use `tmp_path / "parrot.db"` for test isolation.

**NOT in scope**: Factory wiring (TASK-829). Contract test suite parameterization (TASK-830). Any changes outside `backends/sqlite.py` and its test file. Adding `sqlite:memory:` support (v1 uses file paths only; document this in the module docstring).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/storage/backends/sqlite.py` | CREATE | `ConversationSQLiteBackend` |
| `packages/ai-parrot/tests/storage/backends/test_sqlite_backend.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from navconfig.logging import logging
from asyncdb import AsyncDB                                          # parrot/handlers/bots.py:3
from asyncdb.exceptions import NoDataFound                           # parrot/handlers/bots.py:4

from parrot.storage.backends.base import ConversationBackend         # from TASK-822
```

### Existing Signatures to Use

```python
# parrot/storage/backends/base.py (from TASK-822)
class ConversationBackend(ABC):
    # all 14 abstract methods — see TASK-822 for the authoritative list
    def build_overflow_prefix(self, user_id, agent_id, session_id, artifact_id) -> str:
        return f"artifacts/USER#{user_id}#AGENT#{agent_id}/THREAD#{session_id}/{artifact_id}"

# Reference semantics (study before implementing): parrot/storage/backends/dynamodb.py
# (from TASK-824). Your method semantics (ordering, return shapes) must match
# closely enough that the contract suite in TASK-830 passes for both backends.
```

### AsyncDB SQLite Driver — Verified

```python
# Verified present via pkgutil.iter_modules(asyncdb.drivers): "sqlite" exists.
# Typical usage pattern (study parrot/handlers/bots.py and parrot/tools/databasequery/tool.py
# for existing asyncdb patterns):
db = AsyncDB("sqlite", params={"database": "/path/to/parrot.db"})
async with await db.connection() as conn:
    await conn.execute("CREATE TABLE IF NOT EXISTS ...")
    rows = await conn.query("SELECT ... WHERE ...", params)
```

> **CRITICAL**: Before writing code, read `packages/ai-parrot/src/parrot/tools/databasequery/tool.py` lines 1-30 and a representative method to learn the correct asyncdb API shape for this codebase. Method names like `execute`/`query`/`queryrow` may differ from SQL-driver-standard; use whatever pattern the codebase already uses.

### Does NOT Exist

- ~~`asyncdb.drivers.SQLiteDriver`~~ — you instantiate via `AsyncDB("sqlite", params=...)`, not by importing a driver class.
- ~~A built-in background TTL sweeper~~ — expired rows are filtered on read; the explicit `sweep_expired()` helper deletes them on demand.
- ~~Support for `:memory:` databases in v1~~ — the factory always uses a file path.
- ~~A migration framework~~ — schema is created idempotently with `IF NOT EXISTS`. Versioned migrations are explicit non-goals (spec §1).
- ~~`json.dumps(data, cls=SomeEncoder)` with a custom encoder~~ — use `json.dumps(data, default=str)` to handle `datetime` values.
- ~~Concurrent multi-writer support~~ — SQLite serializes writes. Document as single-process backend (spec §7 "SQLite single-writer").

---

## Implementation Notes

### Schema (from spec §2)

```sql
CREATE TABLE IF NOT EXISTS conversations (
    user_id     TEXT NOT NULL,
    agent_id    TEXT NOT NULL,
    session_id  TEXT NOT NULL,
    kind        TEXT NOT NULL,           -- 'thread' | 'turn'
    sort_key    TEXT NOT NULL,           -- 'THREAD' | f'TURN#{turn_id}'
    payload     TEXT NOT NULL,
    updated_at  REAL NOT NULL,
    expires_at  REAL,
    PRIMARY KEY (user_id, agent_id, session_id, kind, sort_key)
);
CREATE INDEX IF NOT EXISTS idx_conv_user_agent ON conversations(user_id, agent_id, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_conv_expires ON conversations(expires_at);

CREATE TABLE IF NOT EXISTS artifacts (
    user_id     TEXT NOT NULL,
    agent_id    TEXT NOT NULL,
    session_id  TEXT NOT NULL,
    artifact_id TEXT NOT NULL,
    payload     TEXT NOT NULL,
    updated_at  REAL NOT NULL,
    expires_at  REAL,
    PRIMARY KEY (user_id, agent_id, session_id, artifact_id)
);
```

### Row-to-Dict Shape (Matching DynamoDB)

Each returned row must look like the dicts that `ConversationDynamoDB` returns
today so the contract suite (TASK-830) sees identical shapes. Example for a
turn row:

```python
payload_dict = json.loads(row["payload"])
return {
    "session_id": row["session_id"],
    "turn_id": row["sort_key"].replace("TURN#", "", 1),   # derive from sort_key
    "updated_at": datetime.fromtimestamp(row["updated_at"], tz=timezone.utc).isoformat(),
    **payload_dict,   # includes user_message, assistant_response, etc.
}
```

Similarly for threads (`kind == 'thread'`, `sort_key == 'THREAD'`) and
artifacts (flat row → dict with `artifact_id` key).

### Query Ordering

- `query_threads(user_id, agent_id, limit)` → `SELECT ... WHERE kind='thread' AND user_id=? AND agent_id=? ORDER BY updated_at DESC LIMIT ?`.
- `query_turns(user_id, agent_id, session_id, limit, newest_first=True)` → `ORDER BY sort_key DESC` when `newest_first`, else `ASC`. (Since `sort_key` for turns is `TURN#001`, `TURN#002`, ... lexicographic sort matches numerical sort as long as turn IDs are zero-padded. Document this constraint in the module docstring.)

### Key Constraints

- **Idempotent initialize**: second call must be a no-op — guard with an `_initialized` flag and use `CREATE TABLE IF NOT EXISTS`.
- **TTL filtering on read**: every `SELECT` must include `AND (expires_at IS NULL OR expires_at > ?)` with the current epoch.
- **Logger**: `self.logger = logging.getLogger("parrot.storage.ConversationSQLiteBackend")`.
- **`is_connected`** returns `True` when the connection has been initialized and not closed.
- **Directory creation**: in `initialize()`, `Path(self._path).parent.mkdir(parents=True, exist_ok=True)` before opening the connection (so `~/.parrot/parrot.db` works out of the box).
- **Turn ID format**: write `sort_key = f"TURN#{turn_id}"` exactly as DynamoDB does at `dynamodb.py:282`.

### References in Codebase

- `parrot/storage/backends/base.py` (TASK-822) — interface.
- `parrot/storage/backends/dynamodb.py` (TASK-824) — reference semantics.
- `parrot/tools/databasequery/tool.py` — asyncdb usage pattern in this codebase.
- `parrot/handlers/bots.py` — another asyncdb usage example.

---

## Acceptance Criteria

- [ ] `parrot/storage/backends/sqlite.py` defines `ConversationSQLiteBackend(ConversationBackend)`.
- [ ] All 14 abstract methods are implemented.
- [ ] `initialize()` creates both tables + both indexes idempotently (second call is a no-op and does not error).
- [ ] `put_thread` / `put_turn` / `put_artifact` set `expires_at = updated_at + DEFAULT_TTL * 86400`.
- [ ] `query_threads` / `query_turns` / `query_artifacts` filter out rows with `expires_at <= now()`.
- [ ] `delete_thread_cascade` removes all `(user_id, agent_id, session_id)` rows from both tables and returns the total count.
- [ ] `delete_turn` returns `True` when the row existed and was deleted, `False` otherwise.
- [ ] `sweep_expired()` exists and returns the number of rows deleted.
- [ ] `from parrot.storage.backends.sqlite import ConversationSQLiteBackend` resolves.
- [ ] All unit tests pass: `source .venv/bin/activate && pytest packages/ai-parrot/tests/storage/backends/test_sqlite_backend.py -v`.

---

## Test Specification

```python
# packages/ai-parrot/tests/storage/backends/test_sqlite_backend.py
import asyncio
import time
import pytest

from parrot.storage.backends.sqlite import ConversationSQLiteBackend


@pytest.fixture
async def backend(tmp_path):
    b = ConversationSQLiteBackend(path=str(tmp_path / "parrot.db"))
    await b.initialize()
    yield b
    await b.close()


@pytest.mark.asyncio
async def test_initialize_is_idempotent(tmp_path):
    path = str(tmp_path / "parrot.db")
    b = ConversationSQLiteBackend(path=path)
    await b.initialize()
    await b.initialize()  # second call should NOT raise
    assert b.is_connected is True
    await b.close()


@pytest.mark.asyncio
async def test_put_and_query_thread(backend):
    await backend.put_thread("u", "a", "s1", {"title": "Hello", "created_at": "2026-04-22T00:00:00"})
    threads = await backend.query_threads("u", "a", limit=10)
    assert len(threads) == 1
    assert threads[0]["session_id"] == "s1"
    assert threads[0]["title"] == "Hello"


@pytest.mark.asyncio
async def test_put_and_query_turns_newest_first(backend):
    await backend.put_thread("u", "a", "s1", {"title": "t"})
    for i in range(3):
        await backend.put_turn("u", "a", "s1", f"{i:03d}", {"text": f"turn-{i}"})
    turns = await backend.query_turns("u", "a", "s1", limit=10, newest_first=True)
    assert [t["turn_id"] for t in turns] == ["002", "001", "000"]


@pytest.mark.asyncio
async def test_delete_turn_returns_true_when_deleted(backend):
    await backend.put_thread("u", "a", "s1", {"title": "t"})
    await backend.put_turn("u", "a", "s1", "001", {"text": "x"})
    ok = await backend.delete_turn("u", "a", "s1", "001")
    assert ok is True
    ok2 = await backend.delete_turn("u", "a", "s1", "does-not-exist")
    assert ok2 is False


@pytest.mark.asyncio
async def test_ttl_expiry_hides_row(backend, monkeypatch):
    import parrot.storage.backends.sqlite as mod
    past = time.time() - 1
    # Put with a custom expires_at in the past (you'll need a test seam or
    # re-open with default_ttl_days=0 to force immediate expiry).
    b2 = ConversationSQLiteBackend(path=backend._path, default_ttl_days=0)
    await b2.initialize()
    await b2.put_thread("u", "a", "sX", {"title": "expired"})
    threads = await b2.query_threads("u", "a", limit=10)
    assert not any(t["session_id"] == "sX" for t in threads)
    await b2.close()


@pytest.mark.asyncio
async def test_delete_thread_cascade_removes_turns_and_artifacts(backend):
    await backend.put_thread("u", "a", "s1", {"title": "t"})
    await backend.put_turn("u", "a", "s1", "001", {"text": "x"})
    await backend.put_artifact("u", "a", "s1", "art1", {"artifact_type": "chart", "title": "c"})
    deleted = await backend.delete_thread_cascade("u", "a", "s1")
    assert deleted >= 2
    assert await backend.query_turns("u", "a", "s1") == []
    assert await backend.query_artifacts("u", "a", "s1") == []


@pytest.mark.asyncio
async def test_sweep_expired(tmp_path):
    b = ConversationSQLiteBackend(path=str(tmp_path / "parrot.db"), default_ttl_days=0)
    await b.initialize()
    await b.put_thread("u", "a", "sX", {"title": "expired"})
    count = await b.sweep_expired()
    assert count >= 1
    await b.close()
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at §2 "Backend-Specific Storage Layouts — SQLite", §3 Module 4, §7 "SQLite single-writer".
2. **Check dependencies** — TASK-822 must be in `sdd/tasks/completed/`.
3. **Read an existing asyncdb usage** in the codebase (e.g. `parrot/tools/databasequery/tool.py`) to learn the current project's call conventions for `AsyncDB("sqlite", ...)`.
4. **Verify** `asyncdb[sqlite]` is installed: `uv pip show asyncdb` (if sqlite extra is missing, flag in Completion Note — TASK-829 will handle pyproject.toml).
5. **Verify the Codebase Contract**.
6. **Update status** in `sdd/tasks/.index.json` → `"in-progress"`.
7. **Implement** in this order: `initialize()` + schema, `put/query_thread`, `put/query_turn`, `delete_turn`, `delete_thread_cascade`, `put/get/query/delete_artifact`, `delete_session_artifacts`, `update_thread`, `sweep_expired`.
8. **Run tests**: `source .venv/bin/activate && pytest packages/ai-parrot/tests/storage/backends/test_sqlite_backend.py -v`.
9. **Move** this file to `sdd/tasks/completed/`.
10. **Update index** → `"done"`.
11. **Fill in the Completion Note**.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none | describe if any
