# TASK-828: MongoDB Backend Implementation

**Feature**: FEAT-116 — Pluggable Storage Backends for Conversations & Artifacts
**Spec**: `sdd/specs/dynamodb-fallback-redis.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-822
**Assigned-to**: unassigned

---

## Context

Third new backend: MongoDB via `asyncdb[mongo]` (motor). Same document model
as the old DocumentDB (the brainstorm's recurring observation: Mongo and
DocumentDB share the driver), so customers migrating from DocumentDB or
running Mongo-compatible services keep a familiar storage. Also suitable for
GCP deployments (spec §1 case 3) where Postgres isn't the team's preference.

Implements **Module 6** of the spec (§3). Parallel with TASK-826 and TASK-827.

---

## Scope

- Create `packages/ai-parrot/src/parrot/storage/backends/mongodb.py` containing `ConversationMongoBackend(ConversationBackend)`.
- Constructor: `__init__(self, dsn: str, database: str = "parrot", default_ttl_days: int = 180) -> None`.
- `initialize()` opens the asyncdb `mongo` driver connection and creates indexes on the two collections `conversations` and `artifacts` per spec §2 "Backend-Specific Storage Layouts — MongoDB":
  - `conversations`: unique `{user_id, agent_id, session_id, sort_key}`; non-unique `{user_id, agent_id, updated_at: -1}`; TTL index on `expires_at`.
  - `artifacts`: unique `{user_id, agent_id, session_id, artifact_id}`; TTL index on `expires_at`.
- Implement all 14 abstract methods using Mongo's native `insert_one`, `find_one_and_replace`, `find`, `delete_many`, etc.
- TTL strategy: Mongo's native TTL indexes on `expires_at` field (no manual filtering needed on read paths). Set `expires_at = datetime.utcnow() + timedelta(days=default_ttl_days)` on write.
- Return documents as plain `dict`. Strip the `_id` field on return (Mongo adds it automatically).
- Write unit tests at `packages/ai-parrot/tests/storage/backends/test_mongo_backend.py` that skip cleanly when `MONGO_TEST_DSN` is unset.

**NOT in scope**: Factory wiring (TASK-829). Contract test suite parameterization (TASK-830). Support for Mongo transactions (not needed — `delete_thread_cascade` uses `delete_many` atomically per-collection). Change streams or any read-preference config.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/storage/backends/mongodb.py` | CREATE | `ConversationMongoBackend` |
| `packages/ai-parrot/tests/storage/backends/test_mongo_backend.py` | CREATE | Unit tests (skip without DSN) |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from navconfig.logging import logging
from asyncdb import AsyncDB                                          # parrot/handlers/bots.py:3
from asyncdb.exceptions import NoDataFound                           # parrot/handlers/bots.py:4

from parrot.storage.backends.base import ConversationBackend         # from TASK-822
```

### Existing Signatures to Use

```python
# parrot/storage/backends/base.py (from TASK-822) — all 14 abstract methods.

# Reference semantics: parrot/storage/backends/dynamodb.py (from TASK-824).

# AsyncDB Mongo Driver verified via pkgutil.iter_modules(asyncdb.drivers): "mongo" present.
# Typical usage (check an existing asyncdb call-site for the exact API convention):
db = AsyncDB("mongo", params={"host": "localhost", "port": 27017, "database": "parrot"})
# ... or dsn-based:
db = AsyncDB("mongo", dsn="mongodb://user:pw@host:27017/parrot")
```

> Study `packages/ai-parrot/src/parrot/tools/databasequery/tool.py` for existing `AsyncDB` call patterns in this codebase.

### Does NOT Exist

- ~~Direct `motor` or `pymongo` imports~~ — go through `asyncdb`.
- ~~`asyncdb.drivers.mongo.MongoDriver`~~ — instantiate via `AsyncDB("mongo", ...)`.
- ~~Multi-document transactions~~ — `delete_thread_cascade` uses two `delete_many` calls in sequence; acceptable per spec "partial write" risk note.
- ~~A sync fallback~~ — fully async.
- ~~Schema validation~~ — out of scope.
- ~~Support for DocumentDB-only features or restrictions~~ — target standard MongoDB; DocumentDB compatibility is a byproduct of driver reuse, not a spec requirement.

---

## Implementation Notes

### Index Creation

On `initialize()`, after connecting to the `parrot` database, create indexes:

```python
# Pseudocode — adjust to asyncdb's mongo API
conversations = db["conversations"]
await conversations.create_index(
    [("user_id", 1), ("agent_id", 1), ("session_id", 1), ("sort_key", 1)],
    unique=True,
)
await conversations.create_index([("user_id", 1), ("agent_id", 1), ("updated_at", -1)])
await conversations.create_index("expires_at", expireAfterSeconds=0)

artifacts = db["artifacts"]
await artifacts.create_index(
    [("user_id", 1), ("agent_id", 1), ("session_id", 1), ("artifact_id", 1)],
    unique=True,
)
await artifacts.create_index("expires_at", expireAfterSeconds=0)
```

`create_index` is idempotent — same spec produces the same index name, no-op on re-run.

### Document Shape (Matching SQLite/DynamoDB)

For threads:
```python
{
    "user_id": "u", "agent_id": "a", "session_id": "s",
    "kind": "thread", "sort_key": "THREAD",
    "updated_at": datetime,  # Mongo stores native BSON Date
    "expires_at": datetime,
    # merged payload fields:
    "title": "...", "created_at": "...", ...
}
```

For turns:
```python
{
    "user_id": "u", "agent_id": "a", "session_id": "s",
    "kind": "turn", "sort_key": "TURN#001",
    "turn_id": "001",
    "updated_at": datetime, "expires_at": datetime,
    # merged payload: user_message, assistant_response, ...
}
```

For artifacts:
```python
{
    "user_id": "u", "agent_id": "a", "session_id": "s",
    "artifact_id": "aid",
    "updated_at": datetime, "expires_at": datetime,
    # merged payload: artifact_type, title, definition, ...
}
```

On return, strip `_id`:
```python
doc = await collection.find_one({...})
if doc:
    doc.pop("_id", None)
    doc["updated_at"] = doc["updated_at"].isoformat() if doc["updated_at"] else None
return doc
```

### UPSERT Pattern

Use `replace_one(filter, document, upsert=True)` to match DynamoDB's put_item overwrite semantics.

### Query Ordering

- `query_threads`: `find({...}).sort("updated_at", -1).limit(limit)`.
- `query_turns(newest_first=True)`: `find({...}).sort("sort_key", -1).limit(limit)`; when `False`, sort ascending.

### Key Constraints

- **Native TTL**: Mongo's TTL reaper runs once per minute — tests must NOT assert instant expiry (spec §7 "Mongo TTL index granularity"). Use `sweep_expired` as a no-op that returns 0 for test determinism OR skip instant-expiry assertions for Mongo in the contract suite.
- **Idempotent initialize**: `create_index` is idempotent; also guard with an `_initialized` flag.
- **Logger**: `self.logger = logging.getLogger("parrot.storage.ConversationMongoBackend")`.
- **`is_connected`**: true after successful `initialize()`.
- **Database name**: default `"parrot"`; customizable via constructor arg.

### References in Codebase

- `parrot/storage/backends/base.py` (TASK-822) — interface.
- `parrot/storage/backends/dynamodb.py` (TASK-824) — reference semantics.
- Existing asyncdb usage patterns in the codebase.

---

## Acceptance Criteria

- [ ] `parrot/storage/backends/mongodb.py` defines `ConversationMongoBackend(ConversationBackend)`.
- [ ] All 14 abstract methods are implemented.
- [ ] `initialize()` creates all five indexes (conversations: 3; artifacts: 2) idempotently.
- [ ] TTL index exists on `expires_at` for both collections with `expireAfterSeconds=0`.
- [ ] Nested document round-trip preserves types (dict-in-dict, list, integer).
- [ ] `_id` is never exposed to callers.
- [ ] `from parrot.storage.backends.mongodb import ConversationMongoBackend` resolves.
- [ ] Unit tests pass when `MONGO_TEST_DSN` is set; skip cleanly otherwise.
- [ ] No direct import of `motor` or `pymongo`.

---

## Test Specification

```python
# packages/ai-parrot/tests/storage/backends/test_mongo_backend.py
import os
import pytest

from parrot.storage.backends.mongodb import ConversationMongoBackend

DSN = os.environ.get("MONGO_TEST_DSN")
pytestmark = pytest.mark.skipif(
    not DSN,
    reason="MONGO_TEST_DSN not set — skipping MongoDB backend tests",
)


@pytest.fixture
async def backend():
    b = ConversationMongoBackend(dsn=DSN, database="parrot_test")
    await b.initialize()
    yield b
    await b.delete_thread_cascade("u", "a", "s1")
    await b.delete_session_artifacts("u", "a", "s1")
    await b.close()


@pytest.mark.asyncio
async def test_initialize_creates_indexes(backend):
    # A smoke test — try to insert two docs with the same compound key; the second should fail.
    await backend.put_thread("u", "a", "s1", {"title": "first"})
    # Overwrite via upsert is allowed; but two DIFFERENT sort_keys yield distinct docs.
    await backend.put_turn("u", "a", "s1", "001", {"text": "x"})
    await backend.put_turn("u", "a", "s1", "001", {"text": "y"})  # upsert
    turns = await backend.query_turns("u", "a", "s1", limit=10)
    assert len(turns) == 1
    assert turns[0]["text"] == "y"


@pytest.mark.asyncio
async def test_nested_roundtrip(backend):
    await backend.put_artifact("u", "a", "s1", "art", {
        "artifact_type": "chart",
        "title": "c",
        "definition": {"nested": {"a": 1, "b": [1, 2, 3]}},
    })
    got = await backend.get_artifact("u", "a", "s1", "art")
    assert got["definition"]["nested"] == {"a": 1, "b": [1, 2, 3]}
    assert "_id" not in got  # never exposed


@pytest.mark.asyncio
async def test_query_turns_newest_first(backend):
    await backend.put_thread("u", "a", "s1", {"title": "t"})
    for i in range(3):
        await backend.put_turn("u", "a", "s1", f"{i:03d}", {"text": f"t-{i}"})
    turns = await backend.query_turns("u", "a", "s1", limit=10, newest_first=True)
    assert [t["turn_id"] for t in turns] == ["002", "001", "000"]
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at §2 "Backend-Specific Storage Layouts — MongoDB", §3 Module 6, §7 "Mongo TTL index granularity".
2. **Check dependencies** — TASK-822 in `sdd/tasks/completed/`.
3. **Study existing asyncdb call-sites** in the project — the exact `AsyncDB("mongo", ...)` convention (params vs dsn) must match the codebase.
4. **Verify the Codebase Contract**.
5. **Update status** in `sdd/tasks/.index.json` → `"in-progress"`.
6. **Implement** — connection + index creation first, then CRUD, then cascade.
7. **Run tests** with a test Mongo:
   - `docker run -d -p 57017:27017 mongo:7`
   - `export MONGO_TEST_DSN=mongodb://localhost:57017`
   - `source .venv/bin/activate && pytest packages/ai-parrot/tests/storage/backends/test_mongo_backend.py -v`
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
