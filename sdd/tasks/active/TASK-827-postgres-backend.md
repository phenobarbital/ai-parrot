# TASK-827: PostgreSQL Backend Implementation

**Feature**: FEAT-116 — Pluggable Storage Backends for Conversations & Artifacts
**Spec**: `sdd/specs/dynamodb-fallback-redis.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-822
**Assigned-to**: unassigned

---

## Context

Production-grade storage backend for GCP deployments (spec §1 case 3) and
dev environments with a shared Postgres. Uses `asyncdb[pg]` (asyncpg under
the hood) with JSONB payload columns — the "relational troubles" referenced
in the original problem statement disappear because JSONB stores and queries
semi-structured data natively.

Implements **Module 5** of the spec (§3). Parallel with TASK-826 and TASK-828.

---

## Scope

- Create `packages/ai-parrot/src/parrot/storage/backends/postgres.py` containing `ConversationPostgresBackend(ConversationBackend)`.
- Constructor: `__init__(self, dsn: str, default_ttl_days: int = 180) -> None`.
- `initialize()` opens the asyncdb `pg` driver connection and creates the two tables + two indexes from spec §2 "Backend-Specific Storage Layouts — Postgres" using `CREATE TABLE IF NOT EXISTS` and `CREATE INDEX IF NOT EXISTS`.
- Implement all 14 abstract methods using JSONB for payload columns.
- TTL strategy: `expires_at TIMESTAMPTZ`; filter with `(expires_at IS NULL OR expires_at > now())`; include a public `async def sweep_expired() -> int` helper.
- Return rows as plain `dict` — asyncdb's pg driver returns `asyncpg.Record` instances; convert via `dict(record)` (see spec §7 "Known Risks — asyncdb Postgres"). Merge JSONB payload into the result dict identically to SQLite (TASK-826) so all backends return the same shape.
- Use `psycopg2`-style `$1, $2` parameter placeholders (asyncpg native) consistently.
- Write unit tests at `packages/ai-parrot/tests/storage/backends/test_postgres_backend.py` that skip cleanly when `POSTGRES_TEST_DSN` is unset.

**NOT in scope**: Factory wiring (TASK-829). Contract test suite parameterization (TASK-830). Any pre-seeded connection pool configuration (backend-internal default per spec open Q #5). `testcontainers`-based integration — if the agent wants to use testcontainers instead of a DSN env var, that's fine, but decision is deferred to TASK-830.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/storage/backends/postgres.py` | CREATE | `ConversationPostgresBackend` |
| `packages/ai-parrot/tests/storage/backends/test_postgres_backend.py` | CREATE | Unit tests (skip without DSN) |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
import json
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from navconfig.logging import logging
from asyncdb import AsyncDB                                          # parrot/handlers/bots.py:3
from asyncdb.exceptions import NoDataFound                           # parrot/handlers/bots.py:4

from parrot.storage.backends.base import ConversationBackend         # from TASK-822
```

### Existing Signatures to Use

```python
# parrot/storage/backends/base.py (from TASK-822) — all 14 abstract methods
# must be implemented. See TASK-822 for the authoritative signatures.

# Reference semantics: parrot/storage/backends/dynamodb.py (from TASK-824).

# Existing asyncdb[pg] usage in the codebase — STUDY BEFORE WRITING:
# - packages/ai-parrot/src/parrot/handlers/bots.py:3 (import pattern)
# - packages/ai-parrot/src/parrot/stores/arango.py:20 (connection pattern)
# - packages/ai-parrot/src/parrot/tools/dataset_manager/sources/sql.py:15
```

### AsyncDB Postgres Driver — Verified Present

```python
# Verified via pkgutil.iter_modules(asyncdb.drivers): "pg" exists.
# Typical usage:
db = AsyncDB("pg", dsn="postgresql://user:pw@host:5432/parrot")
async with await db.connection() as conn:
    await conn.execute("CREATE TABLE IF NOT EXISTS ...")
    rows = await conn.query("SELECT * FROM ... WHERE user_id = $1", ["u"])
    # rows may be list[asyncpg.Record] — convert via [dict(r) for r in rows]
```

### Does NOT Exist

- ~~`asyncdb.drivers.pg.PgDriver`~~ — you instantiate via `AsyncDB("pg", dsn=...)`.
- ~~A synchronous fallback~~ — this backend is fully async.
- ~~Support for Postgres < 12~~ — JSONB and GIN indexes are assumed available (standard in 12+).
- ~~Schema migrations / versioning~~ — non-goal (spec §1).
- ~~`asyncpg` imported directly~~ — go through `asyncdb`, do NOT import `asyncpg`.

---

## Implementation Notes

### Schema (from spec §2)

```sql
CREATE TABLE IF NOT EXISTS parrot_conversations (
    user_id     TEXT NOT NULL,
    agent_id    TEXT NOT NULL,
    session_id  TEXT NOT NULL,
    kind        TEXT NOT NULL,
    sort_key    TEXT NOT NULL,
    payload     JSONB NOT NULL,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at  TIMESTAMPTZ,
    PRIMARY KEY (user_id, agent_id, session_id, kind, sort_key)
);
CREATE INDEX IF NOT EXISTS idx_parrot_conv_user_agent ON parrot_conversations(user_id, agent_id, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_parrot_conv_payload_gin ON parrot_conversations USING GIN (payload);

CREATE TABLE IF NOT EXISTS parrot_artifacts (
    user_id     TEXT NOT NULL,
    agent_id    TEXT NOT NULL,
    session_id  TEXT NOT NULL,
    artifact_id TEXT NOT NULL,
    payload     JSONB NOT NULL,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at  TIMESTAMPTZ,
    PRIMARY KEY (user_id, agent_id, session_id, artifact_id)
);
```

### Row-to-Dict Shape

Identical to SQLite backend (TASK-826) so the contract suite (TASK-830) sees
the same shape across all backends. asyncpg returns `JSONB` as a Python dict
already — no need to `json.loads`.

```python
def _row_to_turn(record) -> dict:
    d = dict(record)
    payload = d.pop("payload") or {}
    return {
        "session_id": d["session_id"],
        "turn_id": d["sort_key"].replace("TURN#", "", 1),
        "updated_at": d["updated_at"].isoformat() if d["updated_at"] else None,
        **payload,
    }
```

### UPSERT Pattern

Use `INSERT ... ON CONFLICT (...) DO UPDATE SET payload = EXCLUDED.payload, updated_at = EXCLUDED.updated_at, expires_at = EXCLUDED.expires_at`. DynamoDB's `put_item` semantics are overwrite-or-create, so every backend must match that.

### Key Constraints

- **Normalize records**: always `dict(record)` before returning to callers.
- **JSONB params**: asyncpg accepts Python dicts for `JSONB` columns — pass the dict directly, no `json.dumps` needed.
- **Idempotent schema creation**: `IF NOT EXISTS` everywhere.
- **Logger**: `self.logger = logging.getLogger("parrot.storage.ConversationPostgresBackend")`.
- **`is_connected`**: true after successful `initialize()` and before `close()`.
- **Postgres < 12 unsupported**: document in module docstring.

### Skip Test Pattern

```python
import os
import pytest

DSN = os.environ.get("POSTGRES_TEST_DSN")
pytestmark = pytest.mark.skipif(
    not DSN,
    reason="POSTGRES_TEST_DSN not set — skipping Postgres backend tests",
)
```

### References in Codebase

- `parrot/storage/backends/base.py` (TASK-822) — interface.
- `parrot/storage/backends/dynamodb.py` (TASK-824) — reference semantics.
- `parrot/stores/arango.py:20` — example of `AsyncDB` usage with a DB URL.

---

## Acceptance Criteria

- [ ] `parrot/storage/backends/postgres.py` defines `ConversationPostgresBackend(ConversationBackend)`.
- [ ] All 14 abstract methods are implemented.
- [ ] Schema is created idempotently on first `initialize()`.
- [ ] All reads filter on `expires_at`.
- [ ] All payloads are stored and retrieved through JSONB (verified by a query that inserts `{"nested": {"k": "v"}}` and reads it back unchanged).
- [ ] `from parrot.storage.backends.postgres import ConversationPostgresBackend` resolves.
- [ ] Unit tests pass when `POSTGRES_TEST_DSN` points at a disposable Postgres instance; otherwise they skip with a clear message.
- [ ] No import of `asyncpg` directly — all access goes through `asyncdb`.

---

## Test Specification

```python
# packages/ai-parrot/tests/storage/backends/test_postgres_backend.py
import os
import pytest
from parrot.storage.backends.postgres import ConversationPostgresBackend

DSN = os.environ.get("POSTGRES_TEST_DSN")
pytestmark = pytest.mark.skipif(
    not DSN,
    reason="POSTGRES_TEST_DSN not set — skipping Postgres backend tests",
)


@pytest.fixture
async def backend():
    b = ConversationPostgresBackend(dsn=DSN)
    await b.initialize()
    # Clean start for tests
    yield b
    # Teardown: delete only our test rows (no DROP TABLE)
    await b.delete_thread_cascade("u", "a", "s1")
    await b.close()


@pytest.mark.asyncio
async def test_initialize_is_idempotent():
    b = ConversationPostgresBackend(dsn=DSN)
    await b.initialize()
    await b.initialize()
    assert b.is_connected is True
    await b.close()


@pytest.mark.asyncio
async def test_put_and_query_thread(backend):
    await backend.put_thread("u", "a", "s1", {"title": "Hello"})
    threads = await backend.query_threads("u", "a", limit=10)
    assert any(t["session_id"] == "s1" and t["title"] == "Hello" for t in threads)


@pytest.mark.asyncio
async def test_jsonb_roundtrip_preserves_nested(backend):
    await backend.put_artifact("u", "a", "s1", "art-1", {
        "artifact_type": "chart",
        "title": "c",
        "definition": {"nested": {"a": 1, "b": [1, 2, 3]}},
    })
    got = await backend.get_artifact("u", "a", "s1", "art-1")
    assert got["definition"] == {"nested": {"a": 1, "b": [1, 2, 3]}}


@pytest.mark.asyncio
async def test_query_threads_newest_first(backend):
    for i, title in enumerate(["first", "second", "third"]):
        await backend.put_thread("u", "a", f"sess-{i}", {"title": title})
    threads = await backend.query_threads("u", "a", limit=10)
    # Newest by updated_at DESC
    titles = [t["title"] for t in threads if t.get("title") in {"first", "second", "third"}]
    assert titles[0] == "third"
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at §2 "Backend-Specific Storage Layouts — Postgres", §3 Module 5, §7 "Known Risks — asyncdb Postgres".
2. **Check dependencies** — TASK-822 in `sdd/tasks/completed/`.
3. **Study an existing asyncdb[pg] call-site** in this codebase (e.g., `parrot/handlers/bots.py`, `parrot/stores/arango.py`) — you MUST match the project's convention for AsyncDB connection/query.
4. **Verify the Codebase Contract**.
5. **Update status** in `sdd/tasks/.index.json` → `"in-progress"`.
6. **Implement** — schema first; basic thread/turn; then artifacts; finally cascade and sweep.
7. **Run tests** with a test Postgres (if available); verify the skip path works otherwise.
   - Optionally `docker run -e POSTGRES_PASSWORD=test -p 55432:5432 -d postgres:15` and `export POSTGRES_TEST_DSN=postgresql://postgres:test@localhost:55432/postgres`.
   - `source .venv/bin/activate && pytest packages/ai-parrot/tests/storage/backends/test_postgres_backend.py -v`
8. **Move** this file to `sdd/tasks/completed/`.
9. **Update index** → `"done"`.
10. **Fill in the Completion Note**.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none | describe if any
