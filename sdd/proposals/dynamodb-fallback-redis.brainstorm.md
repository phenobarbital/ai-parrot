# Brainstorm: Pluggable Storage Backends for Conversations & Artifacts

**Date**: 2026-04-22
**Author**: Jesus Lara
**Status**: exploration
**Recommended Option**: B

---

## Problem Statement

Since FEAT-103 (`agent-artifact-persistency`), chat history, conversation threads
(`session_id`), message turns, and artifacts (JSON, serialized text, binaries)
are persisted in **DynamoDB**, migrated away from DocumentDB. Large artifact
definitions (>200 KB) overflow to **S3** via `S3OverflowManager`.

This design works in AWS production but breaks in three real situations:

1. **Engineer laptops without Docker** — data-analysts using `PandasAgent` locally
   have no DynamoDB, no `docker run amazon/dynamodb-local`, and no S3. Today, the
   backend silently disconnects (`is_connected == False`) and nothing is persisted.
2. **Dev environment with no AWS credentials** — developers running Parrot
   integration tests locally cannot provision throw-away DynamoDB tables.
3. **Production deployments outside AWS** — we are targeting Google Cloud for
   certain customers. DynamoDB is not available there at all, and paying AWS
   cross-cloud egress for a persistence layer is unacceptable.

The original framing was "a dev-only fallback", but item (3) means this must be
a **production-grade storage abstraction** with multiple pluggable backends. A
fallback-on-failure model would silently lose data; an explicit backend selector
(by configuration) is correct.

**Users affected:** framework engineers (testing), data-analysts (local agent runs),
platform engineers (GCP deployments), and anyone reproducing a prod bug on their
laptop.

## Constraints & Requirements

- **Explicit backend selection** via configuration (`PARROT_STORAGE_BACKEND=dynamodb|postgres|sqlite|mongodb`).
  Do NOT silently fall back — data loss from silent failover is worse than a loud error.
- **Common abstract interface** that all backends implement; `ConversationDynamoDB`
  must be refactored to be *one implementation* of this interface, not the primary API.
- **Domain-level interface** (`put_thread`, `query_turns`, `put_artifact`, …) — not
  DynamoDB-shaped (`get_item(pk, sk)`). Each backend uses its native machinery.
- **Zero-dependency option required** — at least one backend must work on a stock
  Python install with no Docker, no server, no AWS credentials (SQLite via stdlib).
- **Pluggable overflow layer** — large artifact storage must be decoupled from the
  primary backend. Any backend can pair with any overflow target (S3, GCS,
  LocalFilesystem), reusing the existing `FileManagerInterface` family.
- **Auto-create schema on first initialize** — tables / collections / indexes are
  provisioned automatically so a new engineer gets a working system with zero DBA work.
- **Reuse `asyncdb` drivers** — `asyncdb` is already in core deps and exposes
  `mongo`, `pg`, `sqlite`, and `dynamodb` drivers. Reusing them keeps the connection
  machinery consistent with the rest of the codebase.
- **Behavioral equivalence** — every backend must pass a shared parametrized
  pytest contract suite so `ChatStorage` and `ArtifactStore` are genuinely
  backend-agnostic.
- **Preserve the existing public API** of `ChatStorage` and `ArtifactStore` — no
  caller outside `parrot/storage/` should need to change.

---

## Options Explored

### Option A: Keep DynamoDB as primary, add fallback shim

Do the minimum: add a runtime auto-fallback inside `ConversationDynamoDB` — when
`is_connected == False`, transparently delegate to a local JSON-file store.

✅ **Pros:**
- Smallest possible diff; no refactor of the existing classes.
- Engineers without AWS "just work" silently.

❌ **Cons:**
- **Silent failover is a data-integrity anti-pattern** — if a prod DynamoDB blip
  occurs, turns would write to an ephemeral local store and be lost when the pod
  restarts. Loud errors are safer than silent divergence.
- Does not address the GCP production case at all — you can't deploy "auto-fallback
  to filesystem" as your primary storage in production.
- Every new backend would require touching `ConversationDynamoDB` internals.
- Fails constraint "Common abstract interface".

📊 **Effort:** Low

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| (stdlib `json`, `pathlib`) | Local JSON file store | No new deps |

🔗 **Existing Code to Reuse:**
- `packages/ai-parrot/src/parrot/storage/dynamodb.py` — would be patched in-place

**Verdict:** Rejected. Violates the "explicit backend selection" constraint and
does not solve the GCP deployment problem.

---

### Option B: `ConversationBackend` ABC + three concrete asyncdb-powered backends + pluggable `OverflowStore`

Introduce a domain-level abstract base class that defines the full persistence
surface (`put_thread`, `update_thread`, `query_threads`, `put_turn`, `query_turns`,
`delete_thread_cascade`, `put_artifact`, `get_artifact`, `query_artifacts`,
`delete_artifact`, `delete_session_artifacts`). Refactor `ConversationDynamoDB`
to be one implementation of this ABC, and ship three additional implementations:

- **`ConversationSQLiteBackend`** — zero-dependency, uses `asyncdb[sqlite]`.
  Single-file DB at `$PARROT_HOME/parrot.db`. Tables `conversations`, `artifacts`
  with JSON payload columns. Auto-created on first `initialize()`. Perfect for
  data-analyst laptops with no Docker.
- **`ConversationPostgresBackend`** — production-grade for GCP. Uses `asyncdb[pg]`
  (asyncpg). Leverages **JSONB** columns (the "relational trouble" vanishes — JSONB
  has native indexing and path queries). Tables use `user_id`, `agent_id`,
  `session_id` as natural keys with B-tree indexes plus a GIN index on the JSONB
  payload for metadata queries.
- **`ConversationMongoBackend`** — same document model as DocumentDB. Uses
  `asyncdb[mongo]` (motor). Two collections: `conversations`, `artifacts`. Makes
  "even the DocumentDB backend could return from the dead" trivial — Mongo and
  DocumentDB share the driver.

Decouple overflow: rename `S3OverflowManager` → `OverflowStore` and make it
accept **any** `FileManagerInterface` (already exists at
`parrot/interfaces/file/abstract.py:18` with concrete S3, GCS, Local, Temp
implementations). Each backend is configured with its own `OverflowStore`
pointing at whichever file target fits:
- DynamoDB backend → `S3FileManager` or `GCSFileManager` or `LocalFileManager`
- Postgres/Mongo/SQLite → `LocalFileManager` or any of the above

Backend selected by env var `PARROT_STORAGE_BACKEND` (default: `dynamodb`).
`ChatStorage` and `ArtifactStore` accept the ABC type and are unchanged.

A parametrized pytest contract suite verifies all backends behave identically.

✅ **Pros:**
- Solves both real problems (docker-less laptop *and* GCP deployment) with
  backends that are legitimately production-grade.
- `FileManagerInterface` is already polymorphic — overflow becomes a one-line swap.
- `asyncdb` drivers are already in core deps; no new top-level dependencies for
  SQLite; `asyncpg` is already used elsewhere (see `parrot/handlers/bots.py:3`).
- Contract test suite catches drift early — future backends (e.g., Firestore)
  have a clear "passes the suite → ready" bar.
- JSONB in Postgres and BSON in Mongo mean no serialization friction — both
  speak "document store" natively.
- Refactor yields a cleaner storage architecture than we have today.

❌ **Cons:**
- Larger refactor than Option A. Touches `ConversationDynamoDB`, `ChatStorage`,
  `ArtifactStore`, config, and tests.
- Each backend needs its own `put_turn` / `query_turns` query logic (though
  this is bounded — the domain surface has ~11 methods).
- Schema auto-creation adds a small bootstrap cost on first run (acceptable).

📊 **Effort:** Medium

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `asyncdb[sqlite]` | SQLite async driver | Already in asyncdb; uses `aiosqlite` under the hood. Stdlib SQLite has JSON1 extension. |
| `asyncdb[pg]` | Postgres async driver | Already used throughout codebase. Uses asyncpg. JSONB + GIN indexes. |
| `asyncdb[mongo]` | MongoDB async driver | Same driver as DocumentDB — credential swap only. Uses motor. |
| `asyncdb[dynamodb]` | DynamoDB driver | Already in use indirectly (FEAT-103 uses aioboto3 directly — could migrate or keep separate). |
| (no new top-level deps) | — | Everything rides on `asyncdb` already declared in core deps. |

🔗 **Existing Code to Reuse:**
- `parrot/storage/dynamodb.py:20` — `ConversationDynamoDB` (refactor target: subclass the new ABC)
- `parrot/storage/chat.py:25` — `ChatStorage` (change type annotation from `ConversationDynamoDB` to new ABC)
- `parrot/storage/artifacts.py:20` — `ArtifactStore` (same — ABC-typed)
- `parrot/storage/s3_overflow.py:19` — `S3OverflowManager` (rename/generalize to `OverflowStore`)
- `parrot/storage/models.py` — `ChatMessage`, `Artifact`, `ThreadMetadata` Pydantic/dataclass models (unchanged; all backends serialize these)
- `parrot/interfaces/file/abstract.py:18` — `FileManagerInterface` ABC (overflow target)
- `parrot/interfaces/file/s3.py:15` — `S3FileManager` (concrete overflow for AWS)
- `parrot/interfaces/file/gcs.py:16` — `GCSFileManager` (concrete overflow for GCP)
- `parrot/interfaces/file/local.py:13` — `LocalFileManager` (concrete overflow for laptops)
- `parrot/conf.py:429-436` — DynamoDB config (add parallel `PARROT_STORAGE_BACKEND`, `SQLITE_PATH`, `POSTGRES_DSN`, `MONGODB_DSN` vars)

---

### Option C: Filesystem-only dev backend (JSON-per-file)

Ship a single `ConversationFilesystemBackend` that writes each thread and
artifact as a JSON file under `$PARROT_HOME/chat/<user>/<agent>/<session>.json`
and `$PARROT_HOME/artifacts/<...>/<artifact_id>.json`. No server, no schema,
no queries — just file I/O. No support for Postgres or Mongo.

✅ **Pros:**
- Trivial to implement and understand (~200 LOC total).
- Zero dependencies.
- Trivially portable — engineers can tar up their `$PARROT_HOME` and share a reproducer.

❌ **Cons:**
- No concurrent access safety (`query_threads` with limit ordering requires
  reading every file).
- Doesn't address GCP production — filesystem on a container is ephemeral.
- Not scalable — a chatty agent produces thousands of files per user.
- Doesn't use `asyncdb`, so it's a one-off implementation that breaks the
  consistency principle of the rest of the storage layer.
- Fails the "production-grade backends for GCP" constraint from Round 2.

📊 **Effort:** Low

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| (stdlib `aiofiles`) | Async file I/O | Already a transitive dep of aiohttp ecosystem. |

🔗 **Existing Code to Reuse:**
- `parrot/interfaces/file/local.py:13` — `LocalFileManager` could back it.

**Verdict:** Rejected as the primary solution. Could still ship as a *fourth*
backend in a later iteration if demand exists, but SQLite dominates it on every
axis (concurrency, query capability, persistence semantics, disk usage) while
remaining zero-dep.

---

## Recommendation

**Option B** is recommended because it is the only option that satisfies all
three use cases (docker-less laptop, dev environment, GCP production) with a
coherent architecture. It delivers:

1. **SQLite** for data-analysts and docker-less laptops — zero-dep, persistent, queryable.
2. **Postgres (JSONB)** for GCP production — genuinely production-grade, horizontally replicable.
3. **Mongo** as a drop-in for anyone migrating from the old DocumentDB — same
   asyncdb driver, credential swap only.
4. **DynamoDB** stays first-class for AWS production — the refactor moves it
   *into* a clean abstraction rather than replacing it.

The tradeoff accepted: a medium refactor touching five files in
`parrot/storage/`, plus a new ABC, plus new contract tests. In exchange we get
a future-proof storage layer where adding a fifth backend (Firestore, Cassandra,
etc.) is an isolated change. Option A's silent-fallback shim is explicitly
rejected as a data-integrity hazard; Option C is dominated by SQLite on every axis.

---

## Feature Description

### User-Facing Behavior

Engineers and operators set `PARROT_STORAGE_BACKEND` in their environment:

| Environment | Typical config |
|---|---|
| AWS production | `PARROT_STORAGE_BACKEND=dynamodb` + DynamoDB env vars (current) + `S3FileManager` overflow |
| GCP production | `PARROT_STORAGE_BACKEND=postgres` + `POSTGRES_DSN` + `GCSFileManager` overflow |
| Data-analyst laptop | `PARROT_STORAGE_BACKEND=sqlite` (default when no other config) + `LocalFileManager` overflow |
| Dev container | `PARROT_STORAGE_BACKEND=mongodb` + `MONGODB_DSN` + `LocalFileManager` overflow |
| CI / unit tests | `PARROT_STORAGE_BACKEND=sqlite` with ephemeral path |

Application code does not change — `ChatStorage` and `ArtifactStore` are used
identically regardless of backend. `list_threads`, `get_turns(session_id)`,
`save_artifact(...)`, etc. all behave the same way.

On first run, the selected backend's schema is provisioned automatically:
- SQLite: `CREATE TABLE IF NOT EXISTS conversations(…)` on initialize
- Postgres: same, plus `CREATE INDEX IF NOT EXISTS idx_user_agent` and GIN on JSONB
- Mongo: `create_index` on natural keys at startup
- DynamoDB: unchanged (tables are provisioned by infrastructure-as-code)

Documentation is extended with a `docs/storage-backends.md` covering:
- Backend selection matrix.
- `docker-compose.yml` for engineers who *do* want DynamoDB Local (with the
  `-sharedDb` flag and a volume mount so data persists across restarts).
- Production deployment notes for each backend.

### Internal Behavior

**Layered architecture:**

```
ChatStorage / ArtifactStore     (unchanged domain API, callers unaffected)
        │
        ▼
ConversationBackend (ABC)       (NEW — parrot/storage/backends/base.py)
        │
        ├── ConversationDynamoDB        (refactored — existing)
        ├── ConversationSQLiteBackend   (NEW)
        ├── ConversationPostgresBackend (NEW)
        └── ConversationMongoBackend    (NEW)
        │
        ▼
OverflowStore (generalized S3OverflowManager)
        │
        └── accepts any FileManagerInterface
              ├── S3FileManager         (existing)
              ├── GCSFileManager        (existing)
              ├── LocalFileManager      (existing)
              └── TempFileManager       (existing)
```

**Factory / selection:** A `build_conversation_backend(config)` factory in
`parrot/storage/backends/__init__.py` reads `PARROT_STORAGE_BACKEND` and
instantiates the appropriate implementation with the appropriate
`OverflowStore`. `ChatStorage.initialize()` and `ArtifactStore`'s setup call
the factory rather than importing `ConversationDynamoDB` directly.

**Serialization contract:** All backends accept and return the same Pydantic
models (`Artifact`, `ThreadMetadata`) and dataclasses (`ChatMessage`). Each
backend is responsible for translating to/from its native representation:
- DynamoDB: `TypeSerializer` / `TypeDeserializer` (current)
- SQLite: `json.dumps` into TEXT columns; JSON1 `json_extract` for filtered queries
- Postgres: native JSONB with `asyncpg` codec; GIN index for metadata queries
- Mongo: native BSON — Pydantic `.model_dump()` → insert

**Schema bootstrapping:** Each backend has an internal `_ensure_schema()`
called by `initialize()`. For SQL backends it issues `CREATE TABLE IF NOT
EXISTS`. For Mongo it ensures indexes. Idempotent and fast on warm start.

**Overflow:** Unchanged flow — on `put_artifact`, the backend asks the
configured `OverflowStore` whether the definition fits inline. If not, the
overflow store uploads via its `FileManagerInterface` and returns a reference
(key / path / URI) that the backend stores in place of the inline payload.
On `get_artifact`, the backend resolves the reference through the same store.

### Edge Cases & Error Handling

| Scenario | Behavior |
|---|---|
| `PARROT_STORAGE_BACKEND` unset | Default to `sqlite` at `~/.parrot/parrot.db`. Log the choice at INFO. |
| `PARROT_STORAGE_BACKEND` unknown value | Raise `ValueError` at startup — fail fast, do not silently pick a default. |
| Backend unavailable at startup (e.g., Postgres down) | Raise `StorageUnavailableError` — **no silent fallback**. Caller decides (retry, crash, degrade). |
| Backend unavailable at runtime (connection drop) | Log WARN, re-raise; `ChatStorage` surfaces the error. Same as today's DynamoDB behavior. |
| SQLite concurrent writers | `asyncdb[sqlite]` serializes writes through a single connection; document that SQLite is single-writer in the selection matrix. |
| Overflow store unavailable | Log WARN, store inline as a last resort (preserves today's `S3OverflowManager` fallback semantics). If payload exceeds backend's inline limit (e.g., DynamoDB's 400 KB), raise. |
| Schema migration (new columns in a future version) | Out of scope for v1. Handled by explicit migration scripts when the time comes; auto-create only handles "empty DB → v1 schema". |
| Backend switch with existing data | Out of scope — users do not migrate between backends. Each backend is a separate persistent store. Document this clearly. |
| Partial write during `delete_thread_cascade` | Each backend implements cascade in a transaction where native (SQL), or best-effort batched delete where not (Mongo, DynamoDB). Already today's reality for DynamoDB. |

---

## Capabilities

### New Capabilities
- `pluggable-storage-backends`: Abstract `ConversationBackend` interface plus SQLite, Postgres, Mongo implementations, with explicit backend selection via configuration and auto-created schemas.

### Modified Capabilities
- `agent-artifact-persistency` (`sdd/specs/agent-artifact-persistency.spec.md`): `ConversationDynamoDB` is refactored to implement the new ABC; `S3OverflowManager` is generalized into a pluggable `OverflowStore`. No behavior change in the AWS path.

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `parrot/storage/dynamodb.py` | modifies | Becomes a subclass of new `ConversationBackend` ABC. Public methods unchanged. |
| `parrot/storage/chat.py` | modifies | `ChatStorage._dynamo` attribute retyped to ABC; construction goes through factory. |
| `parrot/storage/artifacts.py` | modifies | `ArtifactStore._db` retyped to ABC; `_overflow` retyped to generalized `OverflowStore`. |
| `parrot/storage/s3_overflow.py` | modifies | Renamed/generalized to `overflow.py::OverflowStore` accepting any `FileManagerInterface`. `S3OverflowManager` kept as a thin alias for back-compat. |
| `parrot/storage/backends/` (NEW) | adds | `base.py` (ABC), `sqlite.py`, `postgres.py`, `mongodb.py`, and `__init__.py` (factory). |
| `parrot/storage/__init__.py` | modifies | Re-exports `ConversationBackend`, `OverflowStore`, and backend classes. |
| `parrot/conf.py` | modifies | Adds `PARROT_STORAGE_BACKEND`, `SQLITE_PATH`, `POSTGRES_DSN`, `MONGODB_DSN`, `OVERFLOW_STORE`, `OVERFLOW_LOCAL_PATH` config knobs. |
| `tests/storage/` | extends | Adds parametrized contract suite `test_backend_contract.py` that runs against all backends. Existing DynamoDB tests kept. |
| `docs/storage-backends.md` (NEW) | adds | Backend selection matrix, docker-compose for DynamoDB Local, production deployment notes. |
| `packages/ai-parrot/pyproject.toml` | modifies | Ensure `asyncdb[sqlite,pg,mongo]` extras are pulled in (already partly declared). |
| Callers of `ConversationDynamoDB` directly | audit | Grep confirms only `ChatStorage`, `ArtifactStore`, and tests import it — minimal blast radius. |

---

## Code Context

### User-Provided Code
No code snippets were provided during the discussion. The user's input was
architectural: ABC-based pluggable backends, asyncdb as the driver layer,
pluggable overflow store, auto-created schemas, Postgres JSONB preferred over
raw relational columns, Mongo as a DocumentDB successor.

### Verified Codebase References

#### Classes & Signatures

```python
# parrot/storage/dynamodb.py:20
class ConversationDynamoDB:
    DEFAULT_TTL_DAYS = 180                                   # line 38
    def __init__(self, conversations_table: str, artifacts_table: str, dynamo_params: dict) -> None: ...  # line 40
    async def initialize(self) -> None: ...                  # line 59
    async def close(self) -> None: ...                       # line 86
    @property
    def is_connected(self) -> bool: ...                      # line 98
    async def put_thread(self, user_id, agent_id, session_id, metadata: dict) -> None: ...       # line 133
    async def update_thread(self, user_id, agent_id, session_id, **updates) -> None: ...         # line 177
    async def query_threads(self, user_id, agent_id, limit: int = 50) -> List[dict]: ...         # line 224
    async def put_turn(...) -> None: ...                     # line 262
    async def query_turns(...) -> List[dict]: ...            # line 308
    async def delete_thread_cascade(...) -> None: ...        # line 346
    async def put_artifact(...) -> None: ...                 # line 406
    async def get_artifact(...) -> Optional[dict]: ...       # line 452
    async def query_artifacts(...) -> List[dict]: ...        # line 484
    async def delete_artifact(...) -> None: ...              # line 526
    async def delete_session_artifacts(...) -> None: ...     # line 553

# parrot/storage/chat.py:25
class ChatStorage:
    HOT_TTL_HOURS = 48                                       # line 20 (module-level constant)
    def __init__(self, redis_conversation=None, dynamodb=None, document_db=None): ...  # line 28
    async def initialize(self) -> None: ...                  # line 46

# parrot/storage/artifacts.py:20
class ArtifactStore:
    def __init__(self, dynamodb: ConversationDynamoDB, s3_overflow: S3OverflowManager) -> None: ...  # line 31
    async def save_artifact(...) -> None: ...                # line 44
    async def get_artifact(...) -> Optional[Artifact]: ...   # line 82
    async def list_artifacts(...) -> List[ArtifactSummary]: ...  # line 113
    async def update_artifact(...) -> None: ...              # line 149
    async def delete_artifact(...) -> None: ...              # line 199

# parrot/storage/s3_overflow.py:19
class S3OverflowManager:
    INLINE_THRESHOLD: int = 200 * 1024                       # line 32
    def __init__(self, s3_file_manager: S3FileManager) -> None: ...  # line 34
    async def maybe_offload(self, data: Dict[str, Any], key_prefix: str) -> Tuple[Optional[Dict[str, Any]], Optional[str]]: ...  # line 42

# parrot/interfaces/file/abstract.py:18
class FileManagerInterface(ABC):
    async def download_file(self, source: str, destination) -> Path: ...  # line 37
    async def delete_file(self, path: str) -> bool: ...                   # line 47
    async def create_from_bytes(self, path: str, data) -> bool: ...       # line 72

# Concrete FileManagerInterface implementations (all verified to exist)
# parrot/interfaces/file/s3.py:15     → class S3FileManager(FileManagerInterface)
# parrot/interfaces/file/gcs.py:16    → class GCSFileManager(FileManagerInterface)
# parrot/interfaces/file/local.py:13  → class LocalFileManager(FileManagerInterface)
# parrot/interfaces/file/tmp.py:15    → class TempFileManager(FileManagerInterface)
```

#### Verified Imports

```python
# All confirmed to work from the project root with the venv activated:
from parrot.storage import ChatStorage, ArtifactStore, ConversationDynamoDB, S3OverflowManager
from parrot.storage.models import ChatMessage, Conversation, Artifact, ThreadMetadata, ArtifactType
from parrot.interfaces.file.abstract import FileManagerInterface
from parrot.interfaces.file.s3 import S3FileManager
from parrot.interfaces.file.gcs import GCSFileManager
from parrot.interfaces.file.local import LocalFileManager
from asyncdb import AsyncDB            # packages/ai-parrot/src/parrot/handlers/bots.py:3
from asyncdb.exceptions import NoDataFound
```

#### Key Attributes & Constants

- `ConversationDynamoDB.DEFAULT_TTL_DAYS` → `180` (`parrot/storage/dynamodb.py:38`)
- `S3OverflowManager.INLINE_THRESHOLD` → `200 * 1024` (`parrot/storage/s3_overflow.py:32`)
- Module constants in `chat.py`: `HOT_TTL_HOURS = 48`, `DEFAULT_LIST_LIMIT = 50`, `DEFAULT_CONTEXT_TURNS = 10` (lines 20–22)
- `parrot/conf.py:429-436`: `DYNAMODB_CONVERSATIONS_TABLE`, `DYNAMODB_ARTIFACTS_TABLE`, `DYNAMODB_REGION`, `DYNAMODB_ENDPOINT_URL`
- `parrot/conf.py:396-397`: `AWS_ACCESS_KEY`, `AWS_SECRET_KEY`
- `asyncdb` driver availability (verified via `pkgutil`): `dynamodb`, `mongo`, `pg`, `sqlite` all present.

### Does NOT Exist (Anti-Hallucination)

- ~~`parrot.storage.backends`~~ — does not exist yet; this feature creates it.
- ~~`parrot.storage.ConversationBackend`~~ — no ABC exists today; `ConversationDynamoDB` is the concrete-only class.
- ~~`parrot.storage.OverflowStore`~~ — today only `S3OverflowManager` exists; the generalized name is new.
- ~~`parrot.storage.ConversationSQLiteBackend`~~, ~~`ConversationPostgresBackend`~~, ~~`ConversationMongoBackend`~~ — none exist; all are new in this feature.
- ~~`PARROT_STORAGE_BACKEND`~~, ~~`SQLITE_PATH`~~, ~~`POSTGRES_DSN`~~, ~~`MONGODB_DSN`~~ — no such config vars in `parrot/conf.py` today.
- ~~Firestore / Cassandra / Cosmos backends~~ — explicitly out of scope; listed only as future extension points.
- ~~A migration tool between backends~~ — explicitly out of scope for v1.
- ~~Connection pooling configuration API on the ABC~~ — pools are a backend-internal concern; not surfaced in the abstract interface.

---

## Parallelism Assessment

- **Internal parallelism**: High. Once the `ConversationBackend` ABC and the
  parametrized contract suite are in place, each concrete backend
  (SQLite, Postgres, Mongo) is an independent implementation that can be built
  and validated in parallel by separate engineers or agents. The DynamoDB
  refactor is also independent once the ABC is frozen.
- **Cross-feature independence**: Touches `parrot/storage/` exclusively.
  Conflicts with any in-flight work on `agent-artifact-persistency` — we should
  check `git log sdd/specs/agent-artifact-persistency.spec.md` before starting
  and coordinate timing. No other in-flight feature touches this area.
- **Recommended isolation**: `mixed`.
  - Phase 1 (ABC + contract suite + DynamoDB refactor + overflow generalization)
    → one worktree, strictly sequential. This is the foundation every other
    task depends on.
  - Phase 2 (SQLite backend, Postgres backend, Mongo backend) → each backend
    can run in its own worktree in parallel once Phase 1 lands on `dev`.
  - Phase 3 (config wiring + factory + docs) → sequential on top of Phase 2.
- **Rationale**: The ABC is the contract that all three new backends depend on.
  Building it first and locking it down prevents three teams from each reshaping
  the interface as they go. Once locked, the three backend implementations are
  genuinely independent — they touch different files, depend on different
  drivers, and only need to pass the shared contract tests.

---

## Open Questions

- [ ] **Binary storage path for non-DynamoDB backends** — today binaries are
  text-serialized and offloaded to S3 via `S3OverflowManager`. When the overflow
  store is `LocalFileManager`, should binaries land under a dedicated
  `$PARROT_HOME/artifacts/bin/` tree, or mingled with JSON overflow? *Owner: Jesus*
- [ ] **TTL in SQL backends** — DynamoDB has native TTL. Postgres/SQLite need
  either a background sweeper task or a `WHERE ttl > now()` predicate on every
  read. Which approach? *Owner: Jesus*
- [ ] **Connection lifecycle** — should the factory return a long-lived backend
  per process (today's model with DynamoDB) or a short-lived per-request
  connection for SQL backends? Likely long-lived with an internal pool, but
  needs confirmation for Postgres. *Owner: Jesus + backend implementer*
- [ ] **Default when no config is provided** — SQLite at `~/.parrot/parrot.db`
  is friendly, but could surprise production users who forgot to set the var.
  Should the default be "fail-loudly-unset" instead? *Owner: Jesus*
- [ ] **Migration tooling from DynamoDB → Postgres** — not in v1 scope, but we
  should decide if customers migrating off AWS need a one-shot dumper. *Owner: Jesus + platform*
- [ ] **Observability** — the ABC could optionally expose query-level metrics
  (latency, error rates) so a Grafana dashboard can compare backends. In scope
  for v1 or follow-up? *Owner: Jesus*
