# TASK-1766: ResultStorage.fetch() — read API by execution_id in 3 backends

**Feature**: FEAT-306 — Crew Per-Agent Result Persistence & Deterministic Execution Document
**Spec**: `sdd/specs/crew-per-agent-result-persistence.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Implements **Module 2** of FEAT-306. `ResultStorage` today is write-only (`save`/`close`).
To reconstruct a complete execution document from storage (`CrewExecutionDocument.from_storage`,
TASK-1768), every backend needs a `fetch(collection, execution_id)` read path, and the
backends must index/route documents by the new crew-level `execution_id` field.

---

## Scope

- `backends/base.py`: add **non-abstract** method to `ResultStorage`:
  ```python
  async def fetch(self, collection: str, execution_id: str) -> list[dict[str, Any]]:
  ```
  Default body raises `NotImplementedError` (keeps third-party subclasses importable —
  do NOT use `@abstractmethod`).
- `backends/documentdb.py`: implement `fetch()` querying documents where
  `execution_id == <value>` in the given collection.
- `backends/redis.py`:
  - `save()`: when `document` contains a non-empty `"execution_id"`, use key
    `{collection}:{execution_id}:{suffix}` where suffix is `document.get("node_execution_id")`
    if present else `"crew"`. Documents WITHOUT `execution_id` keep the legacy key
    `{collection}:{crew_name}:{ts_ms}` (line 67) unchanged. TTL logic unchanged for both.
  - `fetch()`: cursor-based `SCAN` (never `KEYS`) with `MATCH {collection}:{execution_id}:*`,
    then `GET` each key and `json.loads` the values. Return `[]` when nothing matches.
- `backends/postgres.py`:
  - `_ensure_table()`: add `execution_id text` column to the `CREATE TABLE` DDL, add
    `ALTER TABLE {table} ADD COLUMN IF NOT EXISTS execution_id text` (covers pre-existing
    tables), and `CREATE INDEX IF NOT EXISTS {table}_execution_id_idx ON {table} (execution_id)`.
  - `save()`: extract `execution_id` from the document into the named column (add it to
    `_NAMED_COLUMNS` so it is NOT duplicated inside `payload`); keep it inside payload too
    is NOT desired — named column only, mirroring `session_id` handling.
  - `fetch()`: `SELECT` rows by `execution_id`, returning the reconstructed documents
    (named columns merged with the `payload` jsonb).
- Extend the existing backend test files (see Test Specification).

**NOT in scope**: `_save_agent_result` (TASK-1767), `CrewExecutionDocument` (TASK-1768),
crew.py wiring (TASK-1769), factory changes (none needed), new conf.py settings.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/flows/core/storage/backends/base.py` | MODIFY | Add non-abstract `fetch()` raising NotImplementedError |
| `packages/ai-parrot/src/parrot/bots/flows/core/storage/backends/documentdb.py` | MODIFY | Implement `fetch()` |
| `packages/ai-parrot/src/parrot/bots/flows/core/storage/backends/redis.py` | MODIFY | New key scheme + `fetch()` via SCAN |
| `packages/ai-parrot/src/parrot/bots/flows/core/storage/backends/postgres.py` | MODIFY | DDL execution_id column/index + `fetch()` |
| `tests/bots/flows/core/storage/test_base.py` | MODIFY | Default `fetch()` raises NotImplementedError |
| `tests/bots/flows/core/storage/test_documentdb_backend.py` | MODIFY | fetch filter test (mocked) |
| `tests/bots/flows/core/storage/test_redis_backend.py` | MODIFY | Key-scheme + SCAN fetch tests (mocked conn) |
| `tests/bots/flows/core/storage/test_postgres_backend.py` | MODIFY | DDL + fetch tests (mocked conn) |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: Use these exact references. Verify anything not listed before using it.

### Verified Imports
```python
from parrot.bots.flows.core.storage.backends import (   # backends/__init__.py exports all 5
    ResultStorage, get_result_storage,
    DocumentDbResultStorage, RedisResultStorage, PostgresResultStorage,
)
from parrot.conf import (                                # conf.py:309-312
    CREW_RESULT_STORAGE, CREW_RESULT_STORAGE_PG_DSN,
    CREW_RESULT_STORAGE_REDIS_URL, CREW_RESULT_STORAGE_REDIS_TTL,
)
from asyncdb import AsyncDB                              # used by redis.py:12 and postgres.py
```

### Existing Signatures to Use
```python
# backends/base.py
class ResultStorage(ABC):                                                 # line 8
    @abstractmethod
    async def save(self, collection: str, document: dict[str, Any]) -> None   # line 18
    @abstractmethod
    async def close(self) -> None                                         # line 27
    # NO other methods exist.

# backends/redis.py
class RedisResultStorage(ResultStorage):                                  # line 21
    def __init__(self, dsn=None, ttl=None) -> None                        # line 29
    async def _ensure(self) -> AsyncDB                                    # line 46 — AsyncDB("redis", dsn=...)
    async def save(self, collection, document) -> None                    # line 53
        # key = f"{collection}:{crew_name}:{ts_ms}"                       # line 67 — LEGACY scheme, keep for no-execution_id docs
        # value = json.dumps(document, default=str)                       # line 68
        # TTL: conn.execute("SET", key, value, "EX", str(self._ttl))      # line 70
    async def close(self) -> None                                         # line 80

# backends/postgres.py
class PostgresResultStorage(ResultStorage):                               # line 23
    def __init__(self, dsn=None) -> None                                  # line 35
    async def _ensure(self) -> AsyncDB                                    # line 47 — AsyncDB("pg", dsn=...)
    async def _ensure_table(self, conn, table) -> None                    # line 54
        # DDL columns (lines 66-77): id uuid PK, crew_name text, method text,
        #   user_id text, session_id text, timestamp timestamptz, payload jsonb
        # _TABLE_RE safe-name validation at line 62-65; indexes on crew_name, session_id
    async def save(self, collection, document) -> None                    # line 85
        # payload_dict = {k: v for k, v in document.items() if k not in _NAMED_COLUMNS}   # line 108
        # INSERT with positional $1..$6 params                            # lines 114-125

# backends/documentdb.py
class DocumentDbResultStorage(ResultStorage):                             # line 17
    def __init__(self) -> None                                            # line 25
    async def save(self, collection, document) -> None                    # line 28
    async def close(self) -> None                                         # line 45
    # READ documentdb.py:1-50 BEFORE implementing fetch() — confirm the wrapped
    # DocumentDb client's query/find API; do not guess method names.
```

### Does NOT Exist
- ~~`ResultStorage.fetch()`~~ / ~~`.get()`~~ / ~~`.query()`~~ — THIS TASK creates `fetch()`.
- ~~`execution_id` column in the Postgres DDL~~ — not there yet (postgres.py:66-77).
- ~~`_NAMED_COLUMNS` containing `execution_id`~~ — you must ADD it to that set.
- ~~`conn.scan()` helper on AsyncDB redis~~ — VERIFY the asyncdb redis driver's SCAN calling
  convention (`conn.execute("SCAN", cursor, "MATCH", pattern, ...)` or a native method) by
  reading the asyncdb redis driver in `.venv` before use; do not guess.
- ~~`CREW_AGENT_RESULTS_COLLECTION` conf setting~~ — collection names are plain call args.

---

## Implementation Notes

### Pattern to Follow
```python
# Non-abstract default on the ABC (base.py) — mirrors docstring style of save():
async def fetch(self, collection: str, execution_id: str) -> list[dict[str, Any]]:
    """Return all documents in *collection* matching *execution_id*.

    Default implementation raises NotImplementedError so pre-existing
    third-party subclasses keep working until they opt in.
    """
    raise NotImplementedError(
        f"{type(self).__name__} does not implement fetch()"
    )
```

### Key Constraints
- Redis `fetch()` MUST loop the SCAN cursor until it returns 0 — a single SCAN call is
  incomplete. Never use `KEYS`.
- `fetch()` in concrete backends returns `[]` on no-match; it may raise on connection errors
  (callers handle) — do NOT swallow exceptions into `[]` silently, but DO log.
- Postgres: run the `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` inside `_ensure_table` (it is
  idempotent and covers tables created before this feature).
- All async; warning-style logging via each backend's existing `self.logger`.

### References in Codebase
- `backends/redis.py:53-78` — save/TTL/except pattern to mirror in fetch.
- `backends/postgres.py:85-130` — named-column extraction pattern.
- `tests/bots/flows/core/storage/test_redis_backend.py` — existing mocked-conn test style.

---

## Acceptance Criteria

- [ ] Base `fetch()` raises `NotImplementedError`; class still imports and subclasses without `fetch` still instantiate
- [ ] Redis: doc WITH execution_id → key `{col}:{exec_id}:{suffix}`; doc WITHOUT → legacy key unchanged
- [ ] Redis `fetch()` iterates SCAN cursor fully and returns parsed dicts
- [ ] Postgres DDL includes execution_id column + index + ALTER for existing tables; save() routes execution_id to the named column
- [ ] DocumentDB `fetch()` filters by execution_id
- [ ] All tests pass: `pytest tests/bots/flows/core/storage/ -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/bots/flows/core/storage/backends/`

---

## Test Specification

```python
# tests/bots/flows/core/storage/test_base.py — ADD:
async def test_fetch_default_raises():
    class Minimal(ResultStorage):
        async def save(self, collection, document): ...
        async def close(self): ...
    with pytest.raises(NotImplementedError):
        await Minimal().fetch("c", "eid")


# tests/bots/flows/core/storage/test_redis_backend.py — ADD (mocked conn style):
async def test_save_uses_execution_id_key(mock_conn_storage):
    storage, conn = mock_conn_storage
    await storage.save("crew_agent_results",
                       {"execution_id": "E1", "node_execution_id": "N1", "crew_name": "c"})
    key = conn.execute.call_args_list[0].args[1]
    assert key == "crew_agent_results:E1:N1"

async def test_save_without_execution_id_keeps_legacy_key(mock_conn_storage):
    storage, conn = mock_conn_storage
    await storage.save("crew_executions", {"crew_name": "c"})
    key = conn.execute.call_args_list[0].args[1]
    assert key.startswith("crew_executions:c:")

async def test_fetch_scans_and_parses(mock_conn_storage): ...
    # SCAN returns (cursor=0, [k1, k2]) then GETs return JSON strings


# tests/bots/flows/core/storage/test_postgres_backend.py — ADD:
async def test_ddl_includes_execution_id(...):   # assert column + ALTER + index in executed SQL
async def test_save_extracts_execution_id_to_column(...):
async def test_fetch_selects_by_execution_id(...):
```

---

## Agent Instructions

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — none for this task
3. **Verify the Codebase Contract** before writing ANY code — especially the asyncdb
   redis SCAN convention and the DocumentDb query API (read those sources first)
4. **Update status** in `sdd/tasks/index/crew-per-agent-result-persistence.json` → `"in-progress"`
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-1766-resultstorage-fetch-backends.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
