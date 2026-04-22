# Feature Specification: Pluggable Storage Backends for Conversations & Artifacts

**Feature ID**: FEAT-116
**Date**: 2026-04-22
**Author**: Jesus Lara
**Status**: draft
**Target version**: 1.x (next minor)

> **Source**: This spec is derived from `sdd/proposals/dynamodb-fallback-redis.brainstorm.md` (Option B — accepted).

---

## 1. Motivation & Business Requirements

### Problem Statement

Since FEAT-103 (`agent-artifact-persistency`), chat history, conversation
threads (`session_id`), message turns, and artifacts (JSON, text, serialized
binaries) are persisted in **DynamoDB** (migrated from DocumentDB). Large
artifact definitions (>200 KB) overflow to **S3** via `S3OverflowManager`.

This design works in AWS production but breaks in three real situations:

1. **Engineer laptops without Docker** — data-analysts running `PandasAgent`
   locally have no DynamoDB and no S3. Today `ConversationDynamoDB.initialize()`
   silently flips `is_connected` to `False` and nothing is persisted (every
   `put_*` becomes a no-op).
2. **Dev environment with no AWS credentials** — integration tests cannot
   provision throw-away DynamoDB tables.
3. **Production deployments outside AWS** — Google Cloud customers cannot use
   DynamoDB at all, and AWS cross-cloud egress is unacceptable as a primary
   persistence layer.

Cases (1) and (2) need a zero-dependency option that persists data locally.
Case (3) demands a **production-grade** alternative — a silent fallback is
unacceptable because it would mask outages and cause cross-region data
divergence. The correct answer is **explicit backend selection** via
configuration, backed by a common abstract interface.

### Goals

- Introduce a domain-level `ConversationBackend` ABC covering the full
  persistence surface used today by `ChatStorage` and `ArtifactStore`.
- Refactor `ConversationDynamoDB` to be one implementation of the ABC
  (behavior unchanged — the AWS production path is a pure refactor).
- Ship three new implementations: `ConversationSQLiteBackend`,
  `ConversationPostgresBackend`, `ConversationMongoBackend`, each using
  its native machinery via `asyncdb`.
- Decouple overflow storage: generalize `S3OverflowManager` into an
  `OverflowStore` that accepts **any** `FileManagerInterface`
  (S3, GCS, Local, Temp).
- Select the backend explicitly via `PARROT_STORAGE_BACKEND` environment variable.
- Auto-create tables/collections/indexes on first `initialize()`.
- Ship a shared parametrized pytest contract suite so every backend is
  validated against identical behavioral expectations.
- Preserve the public API of `ChatStorage` and `ArtifactStore` — no caller
  outside `parrot/storage/` needs to change.

### Non-Goals (explicitly out of scope)

- Runtime fallback-on-failure between backends (silent failover is an
  anti-pattern; see Problem Statement).
- Cross-backend data migration tooling (DynamoDB → Postgres dump/load, etc.).
  Acknowledged as a future feature.
- Schema evolution / versioned migrations. Auto-create only handles
  "empty store → v1 schema". A later feature will handle upgrades.
- Additional backends (Firestore, Cassandra, Cosmos). The ABC is designed
  to permit them, but they are not shipped in v1.
- A JSON-per-file filesystem backend (Option C in the brainstorm).
  SQLite dominates it on every axis.
- Redis as a cold-storage backend. Redis remains the hot cache layer inside
  `ChatStorage`; it is not a durable backend candidate.
- Changes to the Pydantic/dataclass models in `parrot/storage/models.py`.
  All backends serialize the same models.

---

## 2. Architectural Design

### Overview

The storage layer gains a new `ConversationBackend` ABC in
`parrot/storage/backends/base.py`. The existing `ConversationDynamoDB` is
moved to `parrot/storage/backends/dynamodb.py` and made to subclass the ABC.
Three new implementations are added alongside. `ChatStorage` and
`ArtifactStore` hold references to the ABC (not a concrete class) and are
instantiated via a factory that reads `PARROT_STORAGE_BACKEND`.

`S3OverflowManager` is renamed `OverflowStore` and generalized to accept any
`FileManagerInterface`. `S3OverflowManager` is kept as a thin subclass for
back-compat (tests in `tests/storage/test_artifact_store.py` reference it).

### Component Diagram

```
                  ChatStorage / ArtifactStore          (public API, unchanged)
                              │
                              ▼
              ConversationBackend (ABC)                (NEW)
                    [parrot/storage/backends/base.py]
                              │
      ┌─────────────┬─────────┴─────────┬─────────────┐
      ▼             ▼                   ▼             ▼
 Dynamo (aioboto3) SQLite (asyncdb)   Postgres      Mongo
   [backends/     [backends/       (asyncdb/JSONB) (asyncdb/
    dynamodb.py]   sqlite.py]      [backends/       motor)
                                    postgres.py]   [backends/
                                                    mongodb.py]

 build_conversation_backend(config) → ConversationBackend   (factory)
                              ▲
                              │
                    PARROT_STORAGE_BACKEND

                    OverflowStore  (generalized S3OverflowManager)
                              │
                              ▼
                    FileManagerInterface
                      [existing]
                              │
            ┌───────┬─────────┼─────────┬──────────┐
            ▼       ▼         ▼         ▼          ▼
        S3File   GCSFile   LocalFile  TempFile   (future)
        Manager  Manager   Manager    Manager
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `ChatStorage` (`parrot/storage/chat.py:25`) | modifies | `_dynamo` retyped `ConversationBackend`; calls the factory in `initialize()` instead of instantiating `ConversationDynamoDB` directly; uses new `delete_turn()` ABC method instead of reaching into `_dynamo._conv_table.delete_item`. |
| `ArtifactStore` (`parrot/storage/artifacts.py:20`) | modifies | `_db` retyped `ConversationBackend`; `_overflow` retyped `OverflowStore`; stops calling `ConversationDynamoDB._build_pk` directly (see **Leaky Abstractions** in §7). |
| `ConversationDynamoDB` (`parrot/storage/dynamodb.py:20`) | moves + modifies | Relocated to `parrot/storage/backends/dynamodb.py`; made a subclass of `ConversationBackend`; public method surface unchanged. An import shim (`parrot/storage/dynamodb.py` re-exports) is kept for one release cycle. |
| `S3OverflowManager` (`parrot/storage/s3_overflow.py:19`) | generalizes | Renamed logical class to `OverflowStore` in new `parrot/storage/overflow.py`; constructor accepts `FileManagerInterface` instead of `S3FileManager` specifically. `S3OverflowManager` remains as a thin subclass binding `S3FileManager`, for existing test compatibility. |
| `FileManagerInterface` (`parrot/interfaces/file/abstract.py:18`) | reuses | No change — already polymorphic. `S3FileManager`, `GCSFileManager`, `LocalFileManager`, `TempFileManager` all plug in as overflow targets. |
| `parrot/conf.py` | modifies | Adds `PARROT_STORAGE_BACKEND`, `PARROT_SQLITE_PATH`, `PARROT_POSTGRES_DSN`, `PARROT_MONGODB_DSN`, `PARROT_OVERFLOW_STORE`, `PARROT_OVERFLOW_LOCAL_PATH` config knobs. Existing `DYNAMODB_*` vars unchanged. |
| `parrot/storage/__init__.py` | extends | Re-exports `ConversationBackend`, `OverflowStore`, and the new backend classes. |
| `asyncdb` | uses | `AsyncDB("sqlite", …)`, `AsyncDB("pg", …)`, `AsyncDB("mongo", …)` — all drivers verified present (§6). |

### Data Models

No new data models — all backends serialize the existing Pydantic and
dataclass models in `parrot/storage/models.py`:

- `ChatMessage` (dataclass, `models.py:72`)
- `Conversation` (dataclass, `models.py:158`)
- `Artifact` (Pydantic, `models.py:272`) — includes `definition: Optional[Dict]`, `definition_ref: Optional[str]` for overflow
- `ArtifactSummary` (Pydantic, `models.py:260`)
- `ThreadMetadata` (Pydantic, `models.py:291`)
- `ArtifactType`, `ArtifactCreator` (enums, `models.py:244`/`253`)

Each backend translates these to/from its native representation (DynamoDB
items, SQLite JSON columns, Postgres JSONB, Mongo BSON).

### New Public Interfaces

```python
# parrot/storage/backends/base.py (NEW)
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional


class ConversationBackend(ABC):
    """Abstract storage backend for conversations, threads, turns, and artifacts.

    All implementations MUST preserve the semantics of the DynamoDB reference
    implementation (see backends/dynamodb.py). Verified by the shared contract
    test suite in tests/storage/test_backend_contract.py.
    """

    # Lifecycle
    @abstractmethod
    async def initialize(self) -> None: ...
    @abstractmethod
    async def close(self) -> None: ...
    @property
    @abstractmethod
    def is_connected(self) -> bool: ...

    # Threads
    @abstractmethod
    async def put_thread(self, user_id: str, agent_id: str, session_id: str, metadata: dict) -> None: ...
    @abstractmethod
    async def update_thread(self, user_id: str, agent_id: str, session_id: str, **updates) -> None: ...
    @abstractmethod
    async def query_threads(self, user_id: str, agent_id: str, limit: int = 50) -> List[dict]: ...

    # Turns
    @abstractmethod
    async def put_turn(self, user_id: str, agent_id: str, session_id: str, turn_id: str, data: dict) -> None: ...
    @abstractmethod
    async def query_turns(self, user_id: str, agent_id: str, session_id: str, limit: int = 10, newest_first: bool = True) -> List[dict]: ...
    @abstractmethod
    async def delete_turn(self, user_id: str, agent_id: str, session_id: str, turn_id: str) -> bool: ...
    @abstractmethod
    async def delete_thread_cascade(self, user_id: str, agent_id: str, session_id: str) -> int: ...

    # Artifacts
    @abstractmethod
    async def put_artifact(self, user_id: str, agent_id: str, session_id: str, artifact_id: str, data: dict) -> None: ...
    @abstractmethod
    async def get_artifact(self, user_id: str, agent_id: str, session_id: str, artifact_id: str) -> Optional[dict]: ...
    @abstractmethod
    async def query_artifacts(self, user_id: str, agent_id: str, session_id: str) -> List[dict]: ...
    @abstractmethod
    async def delete_artifact(self, user_id: str, agent_id: str, session_id: str, artifact_id: str) -> None: ...
    @abstractmethod
    async def delete_session_artifacts(self, user_id: str, agent_id: str, session_id: str) -> int: ...

    # Identity / overflow key namespacing (replaces direct use of DynamoDB PK)
    def build_overflow_prefix(self, user_id: str, agent_id: str, session_id: str, artifact_id: str) -> str:
        """Return a stable key prefix for overflow storage.

        Default implementation yields a DynamoDB-compatible shape so existing
        S3 layouts do not change. Backends MAY override if they want a
        different overflow layout (e.g., filesystem-friendly paths).
        """
        return f"artifacts/USER#{user_id}#AGENT#{agent_id}/THREAD#{session_id}/{artifact_id}"


# parrot/storage/overflow.py (generalized S3OverflowManager)
class OverflowStore:
    """Generic artifact overflow store backed by any FileManagerInterface."""

    INLINE_THRESHOLD: int = 200 * 1024  # 200 KB (matches current S3OverflowManager)

    def __init__(self, file_manager: FileManagerInterface) -> None: ...

    async def maybe_offload(self, data: Dict[str, Any], key_prefix: str) -> Tuple[Optional[Dict[str, Any]], Optional[str]]: ...
    async def resolve(self, inline: Optional[Dict[str, Any]], ref: Optional[str]) -> Optional[Dict[str, Any]]: ...
    async def delete(self, ref: str) -> bool: ...


# parrot/storage/backends/__init__.py — factory
async def build_conversation_backend(config: Dict[str, Any] | None = None) -> ConversationBackend:
    """Instantiate the backend specified by PARROT_STORAGE_BACKEND.

    Raises ValueError for unknown backend values (no silent default swap).
    """
    ...
```

### Backend-Specific Storage Layouts

**SQLite** (`$PARROT_HOME/parrot.db`, default `~/.parrot/parrot.db`):
```sql
CREATE TABLE IF NOT EXISTS conversations (
    user_id     TEXT NOT NULL,
    agent_id    TEXT NOT NULL,
    session_id  TEXT NOT NULL,
    kind        TEXT NOT NULL,           -- 'thread' | 'turn'
    sort_key    TEXT NOT NULL,           -- 'THREAD' | f'TURN#{turn_id}'
    payload     TEXT NOT NULL,           -- JSON serialized dict
    updated_at  REAL NOT NULL,           -- epoch seconds
    expires_at  REAL,                    -- epoch seconds; NULL = no expiry
    PRIMARY KEY (user_id, agent_id, session_id, kind, sort_key)
);
CREATE INDEX IF NOT EXISTS idx_conv_user_agent ON conversations(user_id, agent_id, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_conv_expires ON conversations(expires_at);

CREATE TABLE IF NOT EXISTS artifacts (
    user_id     TEXT NOT NULL,
    agent_id    TEXT NOT NULL,
    session_id  TEXT NOT NULL,
    artifact_id TEXT NOT NULL,
    payload     TEXT NOT NULL,           -- JSON (small definitions stay inline here)
    updated_at  REAL NOT NULL,
    expires_at  REAL,
    PRIMARY KEY (user_id, agent_id, session_id, artifact_id)
);
```

**Postgres** (DSN via `PARROT_POSTGRES_DSN`):
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

**MongoDB** (DSN via `PARROT_MONGODB_DSN`):
- Database: `parrot`
- Collections: `conversations`, `artifacts`
- Indexes (idempotent, built on `initialize()`):
  - `conversations`: `{user_id: 1, agent_id: 1, session_id: 1, sort_key: 1}` (unique); `{user_id: 1, agent_id: 1, updated_at: -1}`; TTL index on `expires_at`.
  - `artifacts`: `{user_id: 1, agent_id: 1, session_id: 1, artifact_id: 1}` (unique); TTL index on `expires_at`.

**DynamoDB** (unchanged): `parrot-conversations`, `parrot-artifacts` tables,
single-table-style with `PK`/`SK` composite key, `ttl` attribute.

### Backend Selection

| `PARROT_STORAGE_BACKEND` | Constructor | Default overflow |
|---|---|---|
| `dynamodb` (default) | `ConversationDynamoDB(...)` from existing env vars | `S3FileManager` (existing) |
| `sqlite` | `ConversationSQLiteBackend(path=PARROT_SQLITE_PATH)` | `LocalFileManager` pointing at `PARROT_OVERFLOW_LOCAL_PATH` |
| `postgres` | `ConversationPostgresBackend(dsn=PARROT_POSTGRES_DSN)` | value of `PARROT_OVERFLOW_STORE` (`local` \| `gcs` \| `s3`) |
| `mongodb` | `ConversationMongoBackend(dsn=PARROT_MONGODB_DSN)` | value of `PARROT_OVERFLOW_STORE` |
| any other value | `ValueError` raised at startup | — |

---

## 3. Module Breakdown

> Tasks in Phase 2 map 1:1 to modules. Task decomposition should yield ~9 tasks:
> 1 ABC + 1 overflow generalization + 1 DynamoDB refactor + 3 new backends +
> 1 factory/config + 1 contract suite + 1 docs.

### Module 1: `ConversationBackend` ABC
- **Path**: `parrot/storage/backends/base.py` (NEW)
- **Responsibility**: Define the abstract storage interface listed in §2
  "New Public Interfaces" (threads, turns, artifacts, lifecycle,
  `build_overflow_prefix` helper). Pure ABC with no concrete state.
- **Depends on**: `parrot/storage/models.py` (types only — the ABC itself
  operates on `dict` payloads; model serialization is done in `ChatStorage`
  and `ArtifactStore`).

### Module 2: `OverflowStore` generalization
- **Path**: `parrot/storage/overflow.py` (NEW, replaces the logical contents
  of `s3_overflow.py`)
- **Responsibility**: `OverflowStore` class accepting any
  `FileManagerInterface`. Preserves existing `INLINE_THRESHOLD` (200 KB) and
  the `maybe_offload` / `resolve` / `delete` method shape. `s3_overflow.py`
  keeps `S3OverflowManager` as a thin `OverflowStore` subclass bound to
  `S3FileManager` (for `tests/storage/test_artifact_store.py` compatibility).
- **Depends on**: `parrot/interfaces/file/abstract.py:18` (`FileManagerInterface`).

### Module 3: `ConversationDynamoDB` refactor
- **Path**: `parrot/storage/backends/dynamodb.py` (moved from
  `parrot/storage/dynamodb.py`)
- **Responsibility**: Keep the existing `ConversationDynamoDB` behavior
  **byte-identical**; only inherit from `ConversationBackend`, add the new
  `delete_turn` method (extracting logic currently inlined in `chat.py:572`),
  and remove the private `_build_pk` leak by overriding `build_overflow_prefix`
  to preserve the current S3 key layout
  (`artifacts/USER#u/AGENT#a/THREAD#s/art-id`). `parrot/storage/dynamodb.py`
  becomes a one-line re-export shim for back-compat.
- **Depends on**: Module 1.

### Module 4: SQLite backend
- **Path**: `parrot/storage/backends/sqlite.py` (NEW)
- **Responsibility**: `ConversationSQLiteBackend` using `asyncdb[sqlite]`.
  Creates the two tables defined in §2 on first `initialize()`. Serializes
  payload dicts with `json.dumps(default=str)`. Implements TTL via
  `expires_at <= now()` predicates on read paths plus a `sweep_expired()`
  helper called opportunistically (no background thread in v1; see §8).
- **Depends on**: Module 1.

### Module 5: Postgres backend
- **Path**: `parrot/storage/backends/postgres.py` (NEW)
- **Responsibility**: `ConversationPostgresBackend` using `asyncdb[pg]`
  (asyncpg). Uses JSONB for payloads and `->>`/`@>` operators for metadata
  filters (though v1 queries do not rely on JSONB filtering — the GIN index
  is defensive for future queries). `CREATE TABLE IF NOT EXISTS` on
  `initialize()`. TTL handled the same way as SQLite.
- **Depends on**: Module 1.

### Module 6: Mongo backend
- **Path**: `parrot/storage/backends/mongodb.py` (NEW)
- **Responsibility**: `ConversationMongoBackend` using `asyncdb[mongo]`
  (motor). Two collections with the indexes listed in §2. TTL uses native
  MongoDB TTL indexes on `expires_at`.
- **Depends on**: Module 1.

### Module 7: Factory + config wiring
- **Path**: `parrot/storage/backends/__init__.py` (NEW),
  `parrot/storage/__init__.py` (modified), `parrot/conf.py` (modified)
- **Responsibility**: `build_conversation_backend(config)` factory that
  reads `PARROT_STORAGE_BACKEND` and returns the appropriate backend.
  Also `build_overflow_store(config)` that reads `PARROT_OVERFLOW_STORE` and
  returns an `OverflowStore` wrapping the right `FileManagerInterface`.
  Update `ChatStorage.initialize()` (`chat.py:46`) to call the factory
  instead of instantiating `ConversationDynamoDB` directly.
- **Depends on**: Modules 1–6.

### Module 8: Contract test suite
- **Path**: `tests/storage/test_backend_contract.py` (NEW)
- **Responsibility**: Parametrized pytest suite that exercises every method
  on the ABC against every backend (SQLite in-memory, Postgres via `testcontainers` or a DSN env var,
  Mongo via `testcontainers` or DSN, DynamoDB via `moto` or DynamoDB Local). Covers:
  round-trip put/get, list ordering, TTL behavior, cascade delete, overflow
  integration, concurrent put.
- **Depends on**: Modules 1–6.

### Module 9: Documentation
- **Path**: `docs/storage-backends.md` (NEW)
- **Responsibility**: Backend selection matrix, env var reference, sample
  `docker-compose.yml` for DynamoDB Local (with `-sharedDb` flag and volume
  mount so data persists), production deployment notes for Postgres and
  Mongo on GCP. Note: MinIO is explicitly NOT documented (rejected in
  brainstorm Round 2 as complexity with no benefit).
- **Depends on**: Modules 1–8 (for accurate config names).

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_backend_abc_requires_all_methods` | 1 | Verifies `ConversationBackend.__abstractmethods__` contains every documented method. |
| `test_build_overflow_prefix_default_matches_dynamodb_layout` | 1 | Default implementation yields `artifacts/USER#u/AGENT#a/THREAD#s/aid`. |
| `test_overflow_store_inline_under_threshold` | 2 | Payload < 200 KB stays inline, no file manager call. |
| `test_overflow_store_offload_over_threshold` | 2 | Payload ≥ 200 KB is passed to `file_manager.create_from_bytes`. |
| `test_overflow_store_delete_calls_file_manager` | 2 | `delete(ref)` calls `file_manager.delete_file(ref)`. |
| `test_s3_overflow_manager_back_compat` | 2 | `S3OverflowManager(s3_mgr)` still works and uses `s3_mgr` internally. |
| `test_dynamodb_backend_still_implements_public_api` | 3 | All existing DynamoDB tests in `tests/storage/test_dynamodb_backend.py` pass unchanged. |
| `test_dynamodb_backend_delete_turn` | 3 | New `delete_turn` method removes the single turn item. |
| `test_sqlite_initialize_creates_tables` | 4 | Second `initialize()` call is idempotent. |
| `test_sqlite_put_get_thread` | 4 | Round-trip a thread metadata dict. |
| `test_sqlite_query_turns_newest_first` | 4 | Ordering matches DynamoDB reference. |
| `test_sqlite_ttl_expiry` | 4 | Rows with `expires_at < now()` are not returned. |
| `test_postgres_initialize_creates_tables` | 5 | Idempotent schema creation. |
| `test_postgres_put_get_thread` | 5 | JSONB round-trip preserves types. |
| `test_postgres_query_threads_by_user_agent` | 5 | Uses the B-tree index, returns newest first. |
| `test_mongo_initialize_creates_indexes` | 6 | TTL index and compound indexes present. |
| `test_mongo_put_get_artifact` | 6 | BSON round-trip preserves types including nested dicts. |
| `test_factory_selects_backend_from_env` | 7 | `PARROT_STORAGE_BACKEND=sqlite` yields `ConversationSQLiteBackend`. |
| `test_factory_unknown_backend_raises` | 7 | `PARROT_STORAGE_BACKEND=foo` raises `ValueError` at startup. |
| `test_chat_storage_uses_factory` | 7 | `ChatStorage.initialize()` no longer imports `ConversationDynamoDB` directly. |
| `test_artifact_store_no_longer_uses_build_pk` | 7 | `artifacts.py` does not reference `ConversationDynamoDB._build_pk`. |

### Integration Tests

| Test | Description |
|---|---|
| `test_backend_contract[dynamodb]` | All ABC methods pass the shared contract suite against DynamoDB (moto / DynamoDB Local). |
| `test_backend_contract[sqlite]` | Same suite passes against an in-memory SQLite backend. |
| `test_backend_contract[postgres]` | Same suite passes against Postgres (testcontainers). Skipped if `POSTGRES_TEST_DSN` is unset. |
| `test_backend_contract[mongodb]` | Same suite passes against Mongo (testcontainers). Skipped if `MONGO_TEST_DSN` is unset. |
| `test_end_to_end_chat_storage_with_sqlite` | `ChatStorage` writes a thread + 3 turns through SQLite, reads them back, cascade-deletes. |
| `test_end_to_end_artifact_store_with_local_overflow` | `ArtifactStore` saves a >200 KB artifact with SQLite backend + `LocalFileManager` overflow; file lands on disk, reference is stored in SQLite, `get_artifact` re-assembles. |
| `test_back_compat_s3_overflow_manager_in_existing_tests` | `tests/storage/test_artifact_store.py` passes with no changes. |

### Test Data / Fixtures

```python
# tests/storage/conftest.py — add
@pytest.fixture
def sqlite_backend(tmp_path):
    from parrot.storage.backends.sqlite import ConversationSQLiteBackend
    backend = ConversationSQLiteBackend(path=str(tmp_path / "parrot.db"))
    return backend

@pytest.fixture(params=["dynamodb", "sqlite", "postgres", "mongodb"])
def any_backend(request, tmp_path):
    """Parametrized fixture — skips unavailable ones (e.g. Postgres without DSN)."""
    ...

@pytest.fixture
def local_overflow(tmp_path):
    from parrot.interfaces.file.local import LocalFileManager
    from parrot.storage.overflow import OverflowStore
    return OverflowStore(file_manager=LocalFileManager(base_path=str(tmp_path)))
```

---

## 5. Acceptance Criteria

- [ ] `parrot/storage/backends/base.py` defines `ConversationBackend` ABC with all 14 methods listed in §2.
- [ ] `ConversationDynamoDB` inherits from `ConversationBackend`; all existing DynamoDB tests (`tests/storage/test_dynamodb_backend.py`, `tests/storage/test_integration_artifact_persistence.py`, `tests/handlers/test_auto_save.py`, `tests/storage/test_artifact_store.py`, `tests/storage/test_chat_storage_dynamodb.py`) pass unchanged.
- [ ] `parrot/storage/overflow.py` exposes `OverflowStore`; `S3OverflowManager` in `parrot/storage/s3_overflow.py` is a subclass retaining the existing constructor signature.
- [ ] `ConversationSQLiteBackend`, `ConversationPostgresBackend`, `ConversationMongoBackend` exist and pass the shared contract suite (`tests/storage/test_backend_contract.py`) when their DSN is available.
- [ ] SQLite contract tests run unconditionally in CI (no external dependency). Postgres/Mongo contract tests run when `POSTGRES_TEST_DSN` / `MONGO_TEST_DSN` env vars are set; they skip otherwise with a clear message.
- [ ] `build_conversation_backend(config)` reads `PARROT_STORAGE_BACKEND` and instantiates the correct backend; unknown values raise `ValueError` at startup.
- [ ] `ChatStorage.initialize()` uses the factory; no direct import of `ConversationDynamoDB` from `chat.py`.
- [ ] `ArtifactStore` no longer references `ConversationDynamoDB._build_pk`; key-prefix computation goes through `backend.build_overflow_prefix(...)`.
- [ ] `ChatStorage` has a `delete_turn` code path that calls `backend.delete_turn(...)` instead of reaching into `_conv_table.delete_item` (`chat.py:572-582` cleanup).
- [ ] `docs/storage-backends.md` exists and includes the backend selection matrix, env var reference, and a working DynamoDB Local `docker-compose.yml`.
- [ ] `packages/ai-parrot/pyproject.toml` declares the `asyncdb[sqlite,pg,mongo]` extras (if not already covered by existing asyncdb declarations — verify first).
- [ ] No breaking changes to the public API of `ChatStorage` or `ArtifactStore` — `git grep -n "ChatStorage(" packages/` results are unchanged.
- [ ] `pytest tests/storage/ -v` passes with `PARROT_STORAGE_BACKEND=sqlite` on a machine with no Docker, no AWS credentials.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> Every reference below has been verified by reading the source file on 2026-04-22.

### Verified Imports

```python
# All confirmed to resolve with the venv active:
from parrot.storage import ChatStorage, ArtifactStore, ConversationDynamoDB, S3OverflowManager  # parrot/storage/__init__.py:1-15
from parrot.storage.models import (                                                                # parrot/storage/models.py
    ChatMessage, Conversation, MessageRole, ToolCall, Source,                                      # dataclasses
    Artifact, ArtifactSummary, ArtifactType, ArtifactCreator, ThreadMetadata,                      # Pydantic
    CanvasBlock, CanvasBlockType, CanvasDefinition,
)
from parrot.interfaces.file.abstract import FileManagerInterface   # parrot/interfaces/file/abstract.py:18
from parrot.interfaces.file.s3 import S3FileManager                # parrot/interfaces/file/s3.py:15
from parrot.interfaces.file.gcs import GCSFileManager              # parrot/interfaces/file/gcs.py:16
from parrot.interfaces.file.local import LocalFileManager          # parrot/interfaces/file/local.py:13
from parrot.interfaces.file.tmp import TempFileManager             # parrot/interfaces/file/tmp.py:15
from asyncdb import AsyncDB                                        # parrot/handlers/bots.py:3
from asyncdb.exceptions import NoDataFound                         # parrot/handlers/bots.py:4
# Verified asyncdb drivers present via pkgutil: dynamodb, mongo, pg, sqlite
```

### Existing Class Signatures

```python
# parrot/storage/dynamodb.py
class ConversationDynamoDB:                                                            # line 20
    DEFAULT_TTL_DAYS = 180                                                             # line 38
    def __init__(self, conversations_table: str, artifacts_table: str, dynamo_params: dict) -> None: ...  # line 40
    async def initialize(self) -> None: ...                                            # line 59
    async def close(self) -> None: ...                                                 # line 86
    @property
    def is_connected(self) -> bool: ...                                                # line 98
    @staticmethod
    def _build_pk(user_id: str, agent_id: str) -> str: ...                             # line 108
    @staticmethod
    def _ttl_epoch(updated_at: datetime, days: int = 180) -> int: ...                  # line 113
    async def put_thread(self, user_id, agent_id, session_id, metadata: dict) -> None: ...         # line 133
    async def update_thread(self, user_id, agent_id, session_id, **updates) -> None: ...           # line 177
    async def query_threads(self, user_id, agent_id, limit: int = 50) -> List[dict]: ...            # line 224
    async def put_turn(self, user_id, agent_id, session_id, turn_id: str, data: dict) -> None: ...  # line 262
    async def query_turns(self, user_id, agent_id, session_id, limit: int = 10, newest_first: bool = True) -> List[dict]: ...  # line 308
    async def delete_thread_cascade(self, user_id, agent_id, session_id) -> int: ...                # line 346
    async def put_artifact(self, user_id, agent_id, session_id, artifact_id: str, data: dict) -> None: ...  # line 406
    async def get_artifact(self, user_id, agent_id, session_id, artifact_id: str) -> Optional[dict]: ...    # line 452
    async def query_artifacts(self, user_id, agent_id, session_id) -> List[dict]: ...               # line 484
    async def delete_artifact(self, user_id, agent_id, session_id, artifact_id: str) -> None: ...   # line 526
    async def delete_session_artifacts(self, user_id, agent_id, session_id) -> int: ...             # line 553

# parrot/storage/chat.py
# Module constants: HOT_TTL_HOURS = 48 (line 20), DEFAULT_LIST_LIMIT = 50 (line 21), DEFAULT_CONTEXT_TURNS = 10 (line 22)
class ChatStorage:                                                                     # line 25
    def __init__(self, redis_conversation=None, dynamodb=None, document_db=None): ...  # line 28
    async def initialize(self) -> None: ...                                            # line 46
    # Note: chat.py:572 reaches into self._dynamo._build_pk and self._dynamo._conv_table — these leaks
    # are removed by this feature via the new backend.delete_turn() method.

# parrot/storage/artifacts.py
class ArtifactStore:                                                                   # line 20
    def __init__(self, dynamodb: ConversationDynamoDB, s3_overflow: S3OverflowManager) -> None: ...  # line 31
    async def save_artifact(self, user_id, agent_id, session_id, artifact: Artifact) -> None: ...     # line 44
    async def get_artifact(self, user_id, agent_id, session_id, artifact_id: str) -> Optional[Artifact]: ...  # line 82
    async def list_artifacts(self, user_id, agent_id, session_id) -> List[ArtifactSummary]: ...       # line 113
    async def update_artifact(self, user_id, agent_id, session_id, artifact_id: str, definition: Dict[str, Any]) -> None: ...  # line 149
    async def delete_artifact(self, user_id, agent_id, session_id, artifact_id: str) -> bool: ...     # line 199
    # Note: artifacts.py:65 and artifacts.py:177 call ConversationDynamoDB._build_pk directly —
    # this leak is removed by the new backend.build_overflow_prefix() method.

# parrot/storage/s3_overflow.py
class S3OverflowManager:                                                               # line 19
    INLINE_THRESHOLD: int = 200 * 1024                                                 # line 32
    def __init__(self, s3_file_manager: S3FileManager) -> None: ...                    # line 34
    async def maybe_offload(self, data: Dict[str, Any], key_prefix: str) -> Tuple[Optional[Dict[str, Any]], Optional[str]]: ...  # line 42

# parrot/interfaces/file/abstract.py
class FileManagerInterface(ABC):                                                       # line 18
    async def download_file(self, source: str, destination) -> Path: ...               # line 37
    async def delete_file(self, path: str) -> bool: ...                                # line 47
    async def create_from_bytes(self, path: str, data) -> bool: ...                    # line 72

# Concrete FileManagerInterface implementations (all verified present):
# parrot/interfaces/file/s3.py:15      → class S3FileManager(FileManagerInterface)
# parrot/interfaces/file/gcs.py:16     → class GCSFileManager(FileManagerInterface)
# parrot/interfaces/file/local.py:13   → class LocalFileManager(FileManagerInterface)
# parrot/interfaces/file/tmp.py:15     → class TempFileManager(FileManagerInterface)
```

### Configuration References

```python
# parrot/conf.py — existing (do NOT redefine)
AWS_ACCESS_KEY                      # line 396
AWS_SECRET_KEY                      # line 397
DYNAMODB_CONVERSATIONS_TABLE        # line 429 (default "parrot-conversations")
DYNAMODB_ARTIFACTS_TABLE            # line 432 (default "parrot-artifacts")
DYNAMODB_REGION                     # line 435
DYNAMODB_ENDPOINT_URL               # line 436 (already plumbed for DynamoDB Local)

# NEW config to add in this feature:
PARROT_STORAGE_BACKEND              # "dynamodb" | "sqlite" | "postgres" | "mongodb"; default "dynamodb"
PARROT_SQLITE_PATH                  # default "~/.parrot/parrot.db"
PARROT_POSTGRES_DSN                 # e.g. "postgresql://user:pw@host:5432/parrot"
PARROT_MONGODB_DSN                  # e.g. "mongodb://user:pw@host:27017/parrot"
PARROT_OVERFLOW_STORE               # "s3" | "gcs" | "local" | "tmp"; default inferred from backend
PARROT_OVERFLOW_LOCAL_PATH          # default "~/.parrot/artifacts"
```

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `ConversationBackend` ABC | `ChatStorage._dynamo` | typed composition | `parrot/storage/chat.py:36` |
| `ConversationBackend` ABC | `ArtifactStore._db` | typed composition | `parrot/storage/artifacts.py:36` |
| `build_conversation_backend()` | `ChatStorage.initialize()` | factory call | `parrot/storage/chat.py:46` |
| `OverflowStore` | `ArtifactStore._overflow` | typed composition | `parrot/storage/artifacts.py:37` |
| `OverflowStore.__init__` | `FileManagerInterface` (any) | constructor arg | `parrot/interfaces/file/abstract.py:18` |
| `ConversationBackend.build_overflow_prefix()` | `ArtifactStore.save_artifact` / `update_artifact` | method call replacing `ConversationDynamoDB._build_pk` | `parrot/storage/artifacts.py:65`, `:177` |
| `ConversationBackend.delete_turn()` | `ChatStorage.delete_turn` (existing) | method call replacing `_conv_table.delete_item` | `parrot/storage/chat.py:572-582` |
| `ConversationSQLiteBackend` | `asyncdb` driver `sqlite` | `AsyncDB("sqlite", {...})` | verified via `pkgutil.iter_modules(asyncdb.drivers)` |
| `ConversationPostgresBackend` | `asyncdb` driver `pg` | `AsyncDB("pg", {...})` | same |
| `ConversationMongoBackend` | `asyncdb` driver `mongo` | `AsyncDB("mongo", {...})` | same |

### Does NOT Exist (Anti-Hallucination)

- ~~`parrot.storage.backends`~~ — does not exist today; this feature creates it.
- ~~`parrot.storage.ConversationBackend`~~ — no ABC exists yet.
- ~~`parrot.storage.OverflowStore`~~ — only `S3OverflowManager` exists today (`parrot/storage/s3_overflow.py:19`); the generalized class is new.
- ~~`parrot.storage.ConversationSQLiteBackend`~~, ~~`ConversationPostgresBackend`~~, ~~`ConversationMongoBackend`~~ — none exist; all three are new.
- ~~`parrot.storage.backends.base.ConversationBackend.delete_turn`~~ was not in the original `ConversationDynamoDB` — it is **new** in this feature, extracted from the inlined logic in `chat.py:572-582`.
- ~~`PARROT_STORAGE_BACKEND`~~, ~~`PARROT_SQLITE_PATH`~~, ~~`PARROT_POSTGRES_DSN`~~, ~~`PARROT_MONGODB_DSN`~~, ~~`PARROT_OVERFLOW_STORE`~~, ~~`PARROT_OVERFLOW_LOCAL_PATH`~~ — none exist in `parrot/conf.py` today.
- ~~Firestore / Cassandra / Cosmos / DynamoDB-via-asyncdb backends~~ — not in scope.
- ~~A MinIO-based overflow option~~ — explicitly rejected in brainstorm Round 2.
- ~~A JSON-per-file filesystem backend (`ConversationFilesystemBackend`)~~ — rejected (Option C in brainstorm).
- ~~Cross-backend migration tooling~~ — out of scope.
- ~~A `Redis` conversation backend for cold storage~~ — Redis stays as hot cache only.
- ~~A `ConversationBackend.get_item(pk, sk)` method~~ — the ABC is domain-level, not DynamoDB-shaped.
- ~~Runtime fallback-on-failure (auto-switch backends)~~ — explicitly rejected; backend is selected at startup and failures raise.
- ~~Background TTL sweeper thread~~ — v1 uses read-path predicates only for SQL backends; Mongo uses native TTL indexes; DynamoDB uses its native TTL. A background sweeper is a future enhancement if needed.

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- **Async-first**: every backend method is `async def`. Internally use the
  `asyncdb` driver API — no `requests`, no blocking I/O.
- **Logger per class**: `self.logger = logging.getLogger(f"parrot.storage.{class_name}")`
  — follow the `ConversationDynamoDB` pattern at `dynamodb.py:53`.
- **Idempotent `initialize()`**: each backend must be safe to call
  `initialize()` twice. Use `IF NOT EXISTS` for SQL and `create_indexes(...)`
  with safe options for Mongo.
- **TTL uniformity**: SQL backends store `expires_at` as the ISO string or
  epoch and filter on read. Mongo uses a TTL index on `expires_at`. DynamoDB
  uses its native `ttl` attribute (existing behavior). Default retention:
  180 days (match `ConversationDynamoDB.DEFAULT_TTL_DAYS`).
- **Serialization is the caller's responsibility**: the ABC operates on
  `dict` payloads. Pydantic → dict conversion happens in `ChatStorage` and
  `ArtifactStore`, exactly as today. This keeps backends simple.
- **Dataclass/Pydantic unchanged**: do not modify `parrot/storage/models.py`.

### Leaky Abstractions to Repair

The current codebase has three leaks of DynamoDB-specific detail into
supposedly generic classes:

1. **`ArtifactStore` calls `ConversationDynamoDB._build_pk` directly**
   (`artifacts.py:65` and `:177`). This computes the S3 overflow key
   prefix. Fix: add `build_overflow_prefix(user_id, agent_id, session_id, artifact_id)`
   to the ABC (default implementation preserves today's layout). Callers
   use `self._db.build_overflow_prefix(...)` instead.
2. **`ChatStorage.delete_turn` reaches into `_dynamo._conv_table.delete_item`**
   (`chat.py:572-582`). Fix: add `delete_turn(user_id, agent_id, session_id, turn_id) -> bool`
   to the ABC and move the DynamoDB-specific `delete_item` call into
   `ConversationDynamoDB.delete_turn`.
3. **`chat.py` imports `botocore.exceptions` inline at line 574**. Fix: once
   `delete_turn` is on the ABC, this import is unnecessary in `chat.py`.

### Known Risks / Gotchas

- **asyncdb Postgres — row vs. dict results**: asyncdb's `pg` driver typically
  returns rows as tuples or `asyncpg.Record`. Backend must normalize to `dict`
  using `dict(row)` or equivalent before returning. Verify against other
  asyncdb usages in the codebase (e.g. `parrot/handlers/bots.py`).
- **SQLite single-writer**: multiple worker processes writing to the same
  SQLite file will serialize / possibly block. Document SQLite as a
  "single-process dev backend" in §9 docs. For multi-worker local setups,
  recommend Postgres via Docker.
- **Mongo TTL index granularity**: Mongo's TTL reaper runs once per minute.
  Tests must not assert instant expiry — poll with a timeout or skip timing
  assertions for Mongo.
- **S3 key prefix back-compat**: existing S3 artifacts under
  `artifacts/USER#u/AGENT#a/THREAD#s/aid` must remain readable by the
  refactored DynamoDB backend. The default `build_overflow_prefix` yields
  exactly this layout — do not change it.
- **`_build_pk` is a staticmethod on a module-level import**: `artifacts.py`
  imports `ConversationDynamoDB` at module scope. After the move to
  `parrot/storage/backends/dynamodb.py`, keep a shim re-export in
  `parrot/storage/dynamodb.py` so any third-party importer (including tests)
  does not break.
- **`pyproject.toml` extras**: `asyncdb` is already in core deps, but the
  sqlite/pg/mongo extras may not all be pulled. Verify with
  `uv pip show asyncdb` during Module 7 implementation; add missing extras
  to `packages/ai-parrot/pyproject.toml` under the `dependencies` key.
- **Contract test skip messages**: when `POSTGRES_TEST_DSN` is absent, skip
  with `pytest.skip("POSTGRES_TEST_DSN not set — skipping Postgres contract suite")`
  so the CI log makes it clear why it was skipped.

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| `asyncdb[sqlite]` | existing | SQLite async driver (uses `aiosqlite` internally). |
| `asyncdb[pg]` | existing | Postgres async driver (uses `asyncpg`). |
| `asyncdb[mongo]` | existing | Mongo async driver (uses `motor`). |
| `testcontainers[postgresql,mongodb]` | `>=4.0` (dev) | Ephemeral Postgres / Mongo for contract tests. Dev-only. |
| `moto` | existing (dev) | DynamoDB mocking for contract tests without AWS. |

No new top-level runtime dependencies. All additions are dev-only.

---

## 8. Open Questions

- [ ] **Default backend when unset** — should `PARROT_STORAGE_BACKEND` default to `dynamodb` (preserves existing behavior) or to `sqlite` (friendlier for new installs)? Leaning `dynamodb` for back-compat; document the choice loudly. — *Owner: Jesus*
- [ ] **SQL TTL strategy** — v1 ships read-path `WHERE expires_at > now()` predicates plus an idempotent `sweep_expired()` helper. Is that sufficient, or do we need a periodic background task from day one? Mongo has native TTL already. — *Owner: Jesus*
- [ ] **`AsyncDB` driver for DynamoDB** — the brainstorm mentioned `asyncdb[dynamodb]` exists. Should `ConversationDynamoDB` be migrated to use it (for consistency across backends) or kept on `aioboto3` (lower risk, feature-identical)? Recommend keeping `aioboto3` in v1; migrate in a separate follow-up if desired. — *Owner: Jesus*
- [ ] **Binary overflow path for `LocalFileManager`** — binaries are serialized via `OverflowStore`. Should they land under `$PARROT_OVERFLOW_LOCAL_PATH/artifacts/bin/...` separated from JSON overflow, or mingled? Default: mingled (simpler). — *Owner: Jesus*
- [ ] **Connection pooling on the ABC** — should pool size/timeout be surfaced as ABC configuration, or kept inside each backend as a driver-specific concern? Recommend backend-internal for v1. — *Owner: backend implementer*
- [ ] **Observability hooks** — should the ABC expose optional metrics (per-method latency, error counters) so a Grafana dashboard can compare backends? Out of scope for v1 unless low-cost. — *Owner: Jesus*
- [ ] **Cross-backend migration tooling** — future feature; should we capture the requirement as a follow-up brainstorm now or wait until a customer actually requests it? — *Owner: Jesus + platform*

---

## Worktree Strategy

**Default isolation unit**: `mixed`.

- **Phase A (sequential)** — one worktree, tasks in order:
  1. Module 1: `ConversationBackend` ABC (freezes the contract for all later work).
  2. Module 2: `OverflowStore` generalization (independent but needed by ArtifactStore refactor).
  3. Module 3: DynamoDB refactor + move to `backends/dynamodb.py` + add `delete_turn` + override `build_overflow_prefix`.
  4. Module 7 (part A): Update `ChatStorage` and `ArtifactStore` to consume the ABC. Ship this alongside Module 3 so the AWS path is fully working before anything else lands.

- **Phase B (parallel — optional)** — each of these can run in its own worktree once Phase A is merged:
  - Module 4: SQLite backend.
  - Module 5: Postgres backend.
  - Module 6: Mongo backend.

- **Phase C (sequential)** — after Phase B:
  - Module 7 (part B): Factory + config wiring (needs all backends present).
  - Module 8: Contract test suite (validates all of Phase B).
  - Module 9: Documentation.

**Cross-feature dependencies**: No in-flight spec currently touches
`parrot/storage/`. `agent-artifact-persistency.spec.md` (FEAT-103) is complete
(all tasks in `sdd/tasks/completed/`). Safe to start.

**Rationale**: The ABC is the single contract all backends depend on. Freezing
it first and locking the refactor of `ChatStorage`/`ArtifactStore` onto the
ABC prevents interface drift during parallel backend development in Phase B.
Phase B backends touch different files, use different drivers, and only
interact through the ABC plus contract suite — genuine parallelism.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-04-22 | Jesus Lara | Initial draft derived from accepted brainstorm Option B |
