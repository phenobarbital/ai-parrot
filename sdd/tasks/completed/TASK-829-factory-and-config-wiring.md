# TASK-829: Backend Factory and Configuration Wiring

**Feature**: FEAT-116 — Pluggable Storage Backends for Conversations & Artifacts
**Spec**: `sdd/specs/dynamodb-fallback-redis.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-822, TASK-823, TASK-824, TASK-825, TASK-826, TASK-827, TASK-828
**Assigned-to**: unassigned

---

## Context

Final integration task. Wires the `PARROT_STORAGE_BACKEND` configuration into
a factory that instantiates the correct backend. Also wires the overflow
store selection. After this, `ChatStorage.initialize()` no longer imports
`ConversationDynamoDB` directly — it calls the factory, which reads env vars.

Implements **Module 7** of the spec (§3). Note: per the user's answer to
Open Question #1, the default for `PARROT_STORAGE_BACKEND` is **`sqlite`**,
not `dynamodb` — this flips the spec's original lean for back-compat in
favor of "zero-friction new installs". AWS production environments set
`PARROT_STORAGE_BACKEND=dynamodb` explicitly.

---

## Scope

- Modify `packages/ai-parrot/src/parrot/conf.py`: add the six new config knobs after the existing `DYNAMODB_*` block (around line 436).
- Modify `packages/ai-parrot/src/parrot/storage/backends/__init__.py` (the package marker from TASK-822): add `build_conversation_backend()` and `build_overflow_store()` factories.
- Modify `packages/ai-parrot/src/parrot/storage/__init__.py`: re-export `ConversationBackend`, `OverflowStore`, the four concrete backend classes, and the two factory functions.
- Modify `packages/ai-parrot/src/parrot/storage/chat.py`: replace the direct `ConversationDynamoDB(...)` instantiation in `initialize()` (lines ~60-80) with `await build_conversation_backend()`.
- Verify `packages/ai-parrot/pyproject.toml` declares `asyncdb[sqlite,pg,mongo]` extras; add any missing extras under `dependencies`.
- Write unit tests at `packages/ai-parrot/tests/storage/test_factory.py`:
  - `PARROT_STORAGE_BACKEND=sqlite` yields `ConversationSQLiteBackend`.
  - `PARROT_STORAGE_BACKEND=dynamodb` yields `ConversationDynamoDB`.
  - `PARROT_STORAGE_BACKEND=postgres` yields `ConversationPostgresBackend`.
  - `PARROT_STORAGE_BACKEND=mongodb` yields `ConversationMongoBackend`.
  - Unknown value raises `ValueError` at startup.
  - `PARROT_OVERFLOW_STORE=local` yields `OverflowStore` wrapping `LocalFileManager`.
  - `ChatStorage.initialize()` no longer imports `ConversationDynamoDB` (grep test).

**NOT in scope**: Contract test suite (TASK-830). Documentation (TASK-832). Observability (TASK-831). Connection pool tuning. Changes to individual backend implementations.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/conf.py` | MODIFY | Add `PARROT_*` config knobs |
| `packages/ai-parrot/src/parrot/storage/backends/__init__.py` | MODIFY | Add factory functions |
| `packages/ai-parrot/src/parrot/storage/__init__.py` | MODIFY | Re-export new classes and factories |
| `packages/ai-parrot/src/parrot/storage/chat.py` | MODIFY | Use factory in `initialize()` |
| `packages/ai-parrot/pyproject.toml` | MODIFY (conditional) | Ensure asyncdb extras are declared |
| `packages/ai-parrot/tests/storage/test_factory.py` | CREATE | Factory unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# parrot/storage/backends/__init__.py — NEW exports
from parrot.storage.backends.base import ConversationBackend         # from TASK-822
from parrot.storage.backends.dynamodb import ConversationDynamoDB    # from TASK-824
from parrot.storage.backends.sqlite import ConversationSQLiteBackend # from TASK-826
from parrot.storage.backends.postgres import ConversationPostgresBackend  # from TASK-827
from parrot.storage.backends.mongodb import ConversationMongoBackend # from TASK-828

from parrot.storage.overflow import OverflowStore                    # from TASK-823
from parrot.interfaces.file.s3 import S3FileManager                  # parrot/interfaces/file/s3.py:15
from parrot.interfaces.file.gcs import GCSFileManager                # parrot/interfaces/file/gcs.py:16
from parrot.interfaces.file.local import LocalFileManager            # parrot/interfaces/file/local.py:13
from parrot.interfaces.file.tmp import TempFileManager               # parrot/interfaces/file/tmp.py:15

# parrot/conf.py uses navconfig's `config.get(...)` helper — confirm by reading
# parrot/conf.py lines 390-440 for the existing `DYNAMODB_*` block pattern.
```

### Existing Signatures to Use

```python
# parrot/storage/chat.py — current initialize() block around lines 60-80
# (read the current file before editing — line numbers may drift one or two):
async def initialize(self) -> None:
    if self._initialized:
        return
    # Redis branch (unchanged) ...
    if self._dynamo is None:
        try:
            from .dynamodb import ConversationDynamoDB
            from ..conf import (
                DYNAMODB_CONVERSATIONS_TABLE, DYNAMODB_ARTIFACTS_TABLE,
                DYNAMODB_REGION, DYNAMODB_ENDPOINT_URL,
                AWS_ACCESS_KEY, AWS_SECRET_KEY,
            )
            # ... builds dynamo_params, instantiates ConversationDynamoDB
            self._dynamo = ConversationDynamoDB(
                conversations_table=DYNAMODB_CONVERSATIONS_TABLE,
                artifacts_table=DYNAMODB_ARTIFACTS_TABLE,
                dynamo_params=dynamo_params,
            )

# After this task:
async def initialize(self) -> None:
    if self._initialized:
        return
    # Redis branch (unchanged) ...
    if self._dynamo is None:
        from parrot.storage.backends import build_conversation_backend
        self._dynamo = await build_conversation_backend()
    if self._dynamo is not None:
        await self._dynamo.initialize()
    self._initialized = True
```

### Does NOT Exist

- ~~`PARROT_STORAGE_BACKEND`~~ in `parrot/conf.py` today — this task adds it.
- ~~A default that silently picks SQLite when AWS env vars are set~~ — the backend is ALWAYS whatever `PARROT_STORAGE_BACKEND` resolves to. No auto-detection.
- ~~A runtime switching API~~ — the factory runs once during `ChatStorage.initialize()`. Changing backend requires restart.
- ~~`build_conversation_backend` as a synchronous function~~ — it is `async` because some driver init may need awaiting (though the factory itself may not — keep the signature async for symmetry with backend `initialize()`).

---

## Implementation Notes

### `parrot/conf.py` Additions

Add after the existing `DYNAMODB_*` block (around line 436):

```python
# --- Parrot Pluggable Storage (FEAT-116) ---
# Default: sqlite — zero-dependency, works without AWS credentials or Docker.
# Production AWS deployments must explicitly set PARROT_STORAGE_BACKEND=dynamodb.
PARROT_STORAGE_BACKEND = config.get("PARROT_STORAGE_BACKEND", fallback="sqlite")

# SQLite
_parrot_home_default = str(Path.home() / ".parrot")
PARROT_SQLITE_PATH = config.get(
    "PARROT_SQLITE_PATH",
    fallback=str(Path(_parrot_home_default) / "parrot.db"),
)

# Postgres
PARROT_POSTGRES_DSN = config.get("PARROT_POSTGRES_DSN", fallback=None)

# MongoDB
PARROT_MONGODB_DSN = config.get("PARROT_MONGODB_DSN", fallback=None)

# Overflow store selection
PARROT_OVERFLOW_STORE = config.get("PARROT_OVERFLOW_STORE", fallback=None)
PARROT_OVERFLOW_LOCAL_PATH = config.get(
    "PARROT_OVERFLOW_LOCAL_PATH",
    fallback=str(Path(_parrot_home_default) / "artifacts"),
)
```

Ensure `from pathlib import Path` exists at the top of `conf.py` (likely already does — check).

### Factory Implementation

```python
# parrot/storage/backends/__init__.py
from typing import Optional

from parrot.storage.backends.base import ConversationBackend
from parrot.storage.backends.dynamodb import ConversationDynamoDB
from parrot.storage.backends.sqlite import ConversationSQLiteBackend
from parrot.storage.backends.postgres import ConversationPostgresBackend
from parrot.storage.backends.mongodb import ConversationMongoBackend
from parrot.storage.overflow import OverflowStore


async def build_conversation_backend(override: Optional[str] = None) -> ConversationBackend:
    """Instantiate the backend specified by PARROT_STORAGE_BACKEND.

    Raises:
        ValueError: if the backend name is unknown.
        RuntimeError: if the backend requires a DSN that is not configured.
    """
    from parrot.conf import (
        PARROT_STORAGE_BACKEND,
        PARROT_SQLITE_PATH,
        PARROT_POSTGRES_DSN,
        PARROT_MONGODB_DSN,
        DYNAMODB_CONVERSATIONS_TABLE, DYNAMODB_ARTIFACTS_TABLE,
        DYNAMODB_REGION, DYNAMODB_ENDPOINT_URL,
        AWS_ACCESS_KEY, AWS_SECRET_KEY,
    )
    name = (override or PARROT_STORAGE_BACKEND or "sqlite").lower()
    if name == "sqlite":
        return ConversationSQLiteBackend(path=PARROT_SQLITE_PATH)
    if name == "postgres":
        if not PARROT_POSTGRES_DSN:
            raise RuntimeError("PARROT_POSTGRES_DSN is required for postgres backend")
        return ConversationPostgresBackend(dsn=PARROT_POSTGRES_DSN)
    if name == "mongodb":
        if not PARROT_MONGODB_DSN:
            raise RuntimeError("PARROT_MONGODB_DSN is required for mongodb backend")
        return ConversationMongoBackend(dsn=PARROT_MONGODB_DSN)
    if name == "dynamodb":
        params = {"region_name": DYNAMODB_REGION}
        if DYNAMODB_ENDPOINT_URL:
            params["endpoint_url"] = DYNAMODB_ENDPOINT_URL
        if AWS_ACCESS_KEY:
            params["aws_access_key_id"] = AWS_ACCESS_KEY
        if AWS_SECRET_KEY:
            params["aws_secret_access_key"] = AWS_SECRET_KEY
        return ConversationDynamoDB(
            conversations_table=DYNAMODB_CONVERSATIONS_TABLE,
            artifacts_table=DYNAMODB_ARTIFACTS_TABLE,
            dynamo_params=params,
        )
    raise ValueError(
        f"Unknown PARROT_STORAGE_BACKEND={name!r}. "
        "Valid values: sqlite, postgres, mongodb, dynamodb."
    )


def build_overflow_store(override: Optional[str] = None) -> OverflowStore:
    """Instantiate the OverflowStore specified by PARROT_OVERFLOW_STORE.

    Defaults:
      - dynamodb backend → s3
      - everything else → local (filesystem under PARROT_OVERFLOW_LOCAL_PATH)
    """
    from parrot.conf import (
        PARROT_STORAGE_BACKEND, PARROT_OVERFLOW_STORE, PARROT_OVERFLOW_LOCAL_PATH,
    )
    from parrot.interfaces.file.s3 import S3FileManager
    from parrot.interfaces.file.gcs import GCSFileManager
    from parrot.interfaces.file.local import LocalFileManager
    from parrot.interfaces.file.tmp import TempFileManager

    name = (override or PARROT_OVERFLOW_STORE or "").lower()
    if not name:
        name = "s3" if PARROT_STORAGE_BACKEND == "dynamodb" else "local"

    if name == "s3":
        return OverflowStore(file_manager=S3FileManager())
    if name == "gcs":
        return OverflowStore(file_manager=GCSFileManager())
    if name == "local":
        return OverflowStore(file_manager=LocalFileManager(base_path=PARROT_OVERFLOW_LOCAL_PATH))
    if name == "tmp":
        return OverflowStore(file_manager=TempFileManager())
    raise ValueError(
        f"Unknown PARROT_OVERFLOW_STORE={name!r}. "
        "Valid values: s3, gcs, local, tmp."
    )
```

> **IMPORTANT**: `S3FileManager()` / `GCSFileManager()` / `LocalFileManager(base_path=...)` constructor calls above are illustrative. Before writing the real factory, **read** each concrete file manager's `__init__` signature to pass the right arguments. The factory should match what `ArtifactStore` callers do today.

### `ChatStorage.initialize()` Change

Before:
```python
if self._dynamo is None:
    try:
        from .dynamodb import ConversationDynamoDB
        from ..conf import (...)
        # ... builds params, instantiates ...
```

After:
```python
if self._dynamo is None:
    from parrot.storage.backends import build_conversation_backend
    self._dynamo = await build_conversation_backend()
if self._dynamo is not None:
    await self._dynamo.initialize()
```

### Key Constraints

- **Default is `sqlite`** (per Open Question #1 answer in the spec).
- **No silent defaults on error** — if `PARROT_STORAGE_BACKEND=postgres` but no DSN → `RuntimeError`, not fallback.
- **Unknown backend → `ValueError`** at startup (fails fast).
- **`pyproject.toml`**: if `asyncdb[sqlite,pg,mongo]` is not already declared, add it. Check the current state first.
- **Circular imports**: import from `parrot.conf` INSIDE the factory function (delayed), not at module top, to avoid circular issues between `conf.py` ← `storage` ← `backends`.

### References in Codebase

- `parrot/conf.py:429-436` — existing DYNAMODB config pattern to mirror.
- `parrot/storage/chat.py:46-100` — current init path to rewire.
- `parrot/interfaces/file/local.py:13` — `LocalFileManager` signature to verify.

---

## Acceptance Criteria

- [ ] `parrot/conf.py` exposes `PARROT_STORAGE_BACKEND`, `PARROT_SQLITE_PATH`, `PARROT_POSTGRES_DSN`, `PARROT_MONGODB_DSN`, `PARROT_OVERFLOW_STORE`, `PARROT_OVERFLOW_LOCAL_PATH`.
- [ ] `parrot.storage.backends.build_conversation_backend()` and `build_overflow_store()` are callable and exported from `parrot.storage`.
- [ ] `ChatStorage.initialize()` uses the factory (grep test: no `ConversationDynamoDB(` in `chat.py` anymore).
- [ ] Unknown backend values raise `ValueError` at startup with a clear message listing valid values.
- [ ] Missing DSN for postgres/mongodb raises `RuntimeError` (not silent fallback).
- [ ] `asyncdb[sqlite,pg,mongo]` extras are declared in `packages/ai-parrot/pyproject.toml` under `dependencies`.
- [ ] All existing storage tests still pass: `pytest packages/ai-parrot/tests/storage/ -v`.
- [ ] New factory tests pass: `pytest packages/ai-parrot/tests/storage/test_factory.py -v`.
- [ ] Smoke: `PARROT_STORAGE_BACKEND=sqlite pytest packages/ai-parrot/tests/storage/ -v` green on a machine with NO Docker and NO AWS credentials.

---

## Test Specification

```python
# packages/ai-parrot/tests/storage/test_factory.py
from pathlib import Path

import pytest

from parrot.storage.backends import (
    build_conversation_backend,
    build_overflow_store,
    ConversationBackend,
    ConversationSQLiteBackend,
    ConversationDynamoDB,
    ConversationPostgresBackend,
    ConversationMongoBackend,
)
from parrot.storage.overflow import OverflowStore


@pytest.mark.asyncio
async def test_factory_returns_sqlite(monkeypatch, tmp_path):
    monkeypatch.setenv("PARROT_STORAGE_BACKEND", "sqlite")
    monkeypatch.setenv("PARROT_SQLITE_PATH", str(tmp_path / "parrot.db"))
    backend = await build_conversation_backend()
    assert isinstance(backend, ConversationSQLiteBackend)
    assert isinstance(backend, ConversationBackend)


@pytest.mark.asyncio
async def test_factory_returns_dynamodb(monkeypatch):
    monkeypatch.setenv("PARROT_STORAGE_BACKEND", "dynamodb")
    backend = await build_conversation_backend()
    assert isinstance(backend, ConversationDynamoDB)


@pytest.mark.asyncio
async def test_factory_postgres_requires_dsn(monkeypatch):
    monkeypatch.setenv("PARROT_STORAGE_BACKEND", "postgres")
    monkeypatch.delenv("PARROT_POSTGRES_DSN", raising=False)
    with pytest.raises(RuntimeError, match="PARROT_POSTGRES_DSN"):
        await build_conversation_backend()


@pytest.mark.asyncio
async def test_factory_unknown_backend_raises(monkeypatch):
    monkeypatch.setenv("PARROT_STORAGE_BACKEND", "firebase")
    with pytest.raises(ValueError, match="Unknown PARROT_STORAGE_BACKEND"):
        await build_conversation_backend()


def test_overflow_local(monkeypatch, tmp_path):
    monkeypatch.setenv("PARROT_OVERFLOW_STORE", "local")
    monkeypatch.setenv("PARROT_OVERFLOW_LOCAL_PATH", str(tmp_path))
    store = build_overflow_store()
    assert isinstance(store, OverflowStore)


def test_chat_storage_no_direct_dynamodb_import():
    src = (Path(__file__).resolve().parents[2] / "src" / "parrot" / "storage" / "chat.py").read_text()
    assert "from .dynamodb import ConversationDynamoDB" not in src
    assert "from parrot.storage.dynamodb import ConversationDynamoDB" not in src
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at §2 "Backend Selection", §3 Module 7, and the notes in this task.
2. **Check dependencies** — TASKs 822–828 all in `sdd/tasks/completed/`.
3. **Verify the Codebase Contract** — especially check that the earlier tasks produced the classes listed under Verified Imports.
4. **Read the current `parrot/conf.py`** lines 390-440 to match the project's navconfig `config.get(...)` idiom.
5. **Read each `FileManager.__init__`** to confirm the real constructor args before writing the overflow factory.
6. **Update status** in `sdd/tasks/.index.json` → `"in-progress"`.
7. **Implement** in order: conf.py → factories → chat.py rewire → pyproject.toml check → tests.
8. **Run tests**:
   - `source .venv/bin/activate && pytest packages/ai-parrot/tests/storage/ -v`
   - `PARROT_STORAGE_BACKEND=sqlite pytest packages/ai-parrot/tests/storage/ -v`
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
