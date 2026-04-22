# TASK-823: OverflowStore Generalization

**Feature**: FEAT-116 — Pluggable Storage Backends for Conversations & Artifacts
**Spec**: `sdd/specs/dynamodb-fallback-redis.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Generalizes the existing `S3OverflowManager` into a backend-agnostic
`OverflowStore` that accepts any `FileManagerInterface` (S3, GCS, Local, Temp).
This decouples "where large artifacts land" from "which conversation backend
we use", per spec §2 and §7.

Implements **Module 2** of the spec (§3). Can run in parallel with TASK-822
(no file overlap).

---

## Scope

- Create `packages/ai-parrot/src/parrot/storage/overflow.py` with a new `OverflowStore` class whose constructor accepts `FileManagerInterface` (not `S3FileManager` specifically).
- Preserve method surface byte-for-byte: `maybe_offload`, `resolve`, `delete`.
- Preserve `INLINE_THRESHOLD = 200 * 1024`.
- Modify `packages/ai-parrot/src/parrot/storage/s3_overflow.py`: `S3OverflowManager` becomes a thin subclass of `OverflowStore` that keeps its existing constructor signature (`s3_file_manager: S3FileManager`) for back-compat with `tests/storage/test_artifact_store.py`.
- Re-export `OverflowStore` from `parrot/storage/__init__.py`.
- Write unit tests at `packages/ai-parrot/tests/storage/test_overflow_store.py`:
  - Payload < 200 KB stays inline; the file manager is NOT called.
  - Payload ≥ 200 KB is passed to `file_manager.create_from_bytes`; `maybe_offload` returns `(None, s3_key)`.
  - `delete(ref)` calls `file_manager.delete_file(ref)` and returns its boolean result.
  - `resolve(inline, None)` returns `inline` unchanged; `resolve(None, ref)` downloads via `file_manager.download_file`.
  - `S3OverflowManager(s3_mgr)` still constructs and behaves identically (back-compat smoke test).

**NOT in scope**: Changes to `ArtifactStore` (TASK-825). Changes to `ConversationDynamoDB` (TASK-824). The factory function `build_overflow_store()` (TASK-829). New backend implementations. Observability hooks (TASK-831).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/storage/overflow.py` | CREATE | `OverflowStore` class |
| `packages/ai-parrot/src/parrot/storage/s3_overflow.py` | MODIFY | `S3OverflowManager` becomes subclass of `OverflowStore` |
| `packages/ai-parrot/src/parrot/storage/__init__.py` | MODIFY | Re-export `OverflowStore` |
| `packages/ai-parrot/tests/storage/test_overflow_store.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from parrot.interfaces.file.abstract import FileManagerInterface   # parrot/interfaces/file/abstract.py:18
from parrot.interfaces.file.s3 import S3FileManager                # parrot/interfaces/file/s3.py:15
# Stdlib — safe:
import io
import json
from typing import Any, Dict, Optional, Tuple
```

### Existing Signatures to Use

```python
# parrot/storage/s3_overflow.py (current implementation — study this verbatim)
class S3OverflowManager:                                                       # line 19
    INLINE_THRESHOLD: int = 200 * 1024                                         # line 32
    def __init__(self, s3_file_manager: S3FileManager) -> None: ...            # line 34
    async def maybe_offload(self, data: Dict[str, Any], key_prefix: str) -> Tuple[Optional[Dict[str, Any]], Optional[str]]: ...  # line 42
    # NOTE: current class also has `resolve(inline, ref)` and `delete(ref)` methods —
    # READ the full file to copy exact semantics before starting.

# parrot/interfaces/file/abstract.py
class FileManagerInterface(ABC):                                               # line 18
    async def download_file(self, source: str, destination) -> Path: ...       # line 37
    async def delete_file(self, path: str) -> bool: ...                        # line 47
    async def create_from_bytes(self, path: str, data) -> bool: ...            # line 72

# parrot/storage/__init__.py (current exports — add OverflowStore beside S3OverflowManager)
from .s3_overflow import S3OverflowManager                                     # line 14
```

### Does NOT Exist

- ~~`parrot.storage.OverflowStore`~~ — does not exist today; this task creates it.
- ~~`parrot.storage.overflow`~~ module — does not exist; this task creates it.
- ~~`FileManagerInterface.upload` or `.put`~~ — the correct method is `create_from_bytes` (line 72).
- ~~`FileManagerInterface.get`~~ — the correct method is `download_file` (line 37).
- ~~A `MinIOFileManager`~~ — not in scope, explicitly rejected in the brainstorm.
- ~~Changes to `FileManagerInterface` itself~~ — it is already polymorphic and needs no modification.

---

## Implementation Notes

### Pattern to Follow

Study `parrot/storage/s3_overflow.py` in full first — the new `OverflowStore`
must preserve every behavior, just parameterize on the interface type. Example
generalization:

```python
# parrot/storage/overflow.py (NEW)
import io
import json
from typing import Any, Dict, Optional, Tuple

from navconfig.logging import logging
from parrot.interfaces.file.abstract import FileManagerInterface


class OverflowStore:
    """Generic artifact overflow store backed by any FileManagerInterface."""

    INLINE_THRESHOLD: int = 200 * 1024  # 200 KB

    def __init__(self, file_manager: FileManagerInterface) -> None:
        self._fm = file_manager
        self.logger = logging.getLogger("parrot.storage.OverflowStore")

    async def maybe_offload(
        self, data: Dict[str, Any], key_prefix: str,
    ) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
        # Copy logic from s3_overflow.py:42 but call self._fm.create_from_bytes
        ...

    async def resolve(
        self, inline: Optional[Dict[str, Any]], ref: Optional[str],
    ) -> Optional[Dict[str, Any]]:
        # Copy logic; call self._fm.download_file
        ...

    async def delete(self, ref: str) -> bool:
        # Copy logic; call self._fm.delete_file
        ...
```

Then in `s3_overflow.py`:

```python
# parrot/storage/s3_overflow.py (modified)
from parrot.interfaces.file.s3 import S3FileManager
from .overflow import OverflowStore


class S3OverflowManager(OverflowStore):
    """Back-compat subclass: OverflowStore bound to S3FileManager."""

    def __init__(self, s3_file_manager: S3FileManager) -> None:
        super().__init__(file_manager=s3_file_manager)
```

### Key Constraints

- `INLINE_THRESHOLD` must stay at `200 * 1024` (see spec §7 "S3 key prefix back-compat").
- Existing `tests/storage/test_artifact_store.py` must continue to pass unchanged — do NOT change `S3OverflowManager.__init__` signature.
- Use `self._fm` (not `self._s3`) as the attribute name in the new class to signal the type is generic. Keep backward compatibility by NOT renaming the inner behavior.
- Preserve the existing fallback-on-upload-error behavior from `s3_overflow.py:76-80` (store inline if upload fails).
- Logger name: `"parrot.storage.OverflowStore"` for the new class; keep `"parrot.storage.S3OverflowManager"` for the subclass to preserve log line continuity.

### References in Codebase

- `parrot/storage/s3_overflow.py:19` — source class to generalize.
- `parrot/interfaces/file/s3.py:15` — concrete `S3FileManager` used today.
- `parrot/interfaces/file/local.py:13` — `LocalFileManager` the tests can use without any cloud deps.

---

## Acceptance Criteria

- [ ] `parrot/storage/overflow.py` exists and defines `OverflowStore` with constructor `__init__(self, file_manager: FileManagerInterface)`.
- [ ] `OverflowStore.INLINE_THRESHOLD == 200 * 1024`.
- [ ] `OverflowStore.maybe_offload`, `resolve`, `delete` behave identically to the existing `S3OverflowManager` equivalents.
- [ ] `S3OverflowManager` in `parrot/storage/s3_overflow.py` is a subclass of `OverflowStore`; its constructor still accepts `s3_file_manager: S3FileManager`.
- [ ] Existing `tests/storage/test_artifact_store.py` passes unchanged: `source .venv/bin/activate && pytest packages/ai-parrot/tests/storage/test_artifact_store.py -v`.
- [ ] New tests pass: `pytest packages/ai-parrot/tests/storage/test_overflow_store.py -v`.
- [ ] `from parrot.storage import OverflowStore` resolves.

---

## Test Specification

```python
# packages/ai-parrot/tests/storage/test_overflow_store.py
import pytest
from unittest.mock import AsyncMock, MagicMock

from parrot.interfaces.file.abstract import FileManagerInterface
from parrot.storage.overflow import OverflowStore


@pytest.fixture
def mock_fm():
    fm = MagicMock(spec=FileManagerInterface)
    fm.create_from_bytes = AsyncMock(return_value=True)
    fm.download_file = AsyncMock(return_value=b"...")
    fm.delete_file = AsyncMock(return_value=True)
    return fm


@pytest.fixture
def store(mock_fm):
    return OverflowStore(file_manager=mock_fm)


@pytest.mark.asyncio
async def test_inline_under_threshold(store, mock_fm):
    small = {"k": "v"}
    inline, ref = await store.maybe_offload(small, "prefix")
    assert inline == small
    assert ref is None
    mock_fm.create_from_bytes.assert_not_called()


@pytest.mark.asyncio
async def test_offload_over_threshold(store, mock_fm):
    big = {"data": "x" * (OverflowStore.INLINE_THRESHOLD + 1)}
    inline, ref = await store.maybe_offload(big, "artifacts/test")
    assert inline is None
    assert ref is not None
    mock_fm.create_from_bytes.assert_awaited_once()


@pytest.mark.asyncio
async def test_delete_calls_fm(store, mock_fm):
    ok = await store.delete("artifacts/test.json")
    assert ok is True
    mock_fm.delete_file.assert_awaited_once_with("artifacts/test.json")


@pytest.mark.asyncio
async def test_s3_overflow_manager_back_compat():
    from parrot.storage.s3_overflow import S3OverflowManager
    from parrot.interfaces.file.s3 import S3FileManager
    mock_s3 = MagicMock(spec=S3FileManager)
    mgr = S3OverflowManager(mock_s3)
    assert isinstance(mgr, OverflowStore)
    assert mgr._fm is mock_s3
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at §2 "New Public Interfaces" (line 221-231) and §7 "Known Risks — S3 key prefix back-compat".
2. **Read the existing `parrot/storage/s3_overflow.py` in full** — you need to preserve every behavior.
3. **Check dependencies** — none.
4. **Verify the Codebase Contract** — confirm `FileManagerInterface` still has `create_from_bytes`/`download_file`/`delete_file` at the listed lines.
5. **Update status** in `sdd/tasks/.index.json` → `"in-progress"`.
6. **Implement** — create `overflow.py`, adapt `s3_overflow.py` to subclass, update `__init__.py` exports.
7. **Run tests**:
   - `pytest packages/ai-parrot/tests/storage/test_overflow_store.py -v`
   - `pytest packages/ai-parrot/tests/storage/test_artifact_store.py -v` (must still pass unchanged)
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
