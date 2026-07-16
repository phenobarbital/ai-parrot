---
type: Wiki Overview
title: 'TASK-1037: FAISS persistence to S3'
id: doc:sdd-tasks-completed-task-1037-faiss-s3-persistence-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'from parrot.stores.faiss_store import FAISSStore # parrot/stores/faiss_store.py:32'
relates_to:
- concept: mod:parrot.stores.faiss_store
  rel: mentions
- concept: mod:parrot.tools.filemanager
  rel: mentions
---

# TASK-1037: FAISS persistence to S3

**Feature**: FEAT-149 — Ephemeral User Agents
**Spec**: `sdd/specs/ephemeral-agents.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

> When an ephemeral agent using `rag_mode="vector"` is promoted to persistent, its in-memory
> FAISS index must be serialized and stored in S3 so it can be reloaded on future startups
> (spec §3 Module 6). The spec decides on parquet for S3 upload format (§8 Open Questions).

---

## Scope

- Add `async def dump_to_s3(self, key: str, file_manager: FileManagerToolkit) -> str` to `FAISSStore`.
  - Serialize the in-memory index to a temporary file using the existing `save()` method.
  - Upload the file to S3 via `FileManagerToolkit.upload_file()`.
  - Return the S3 path.
- Add `classmethod async def load_from_s3(cls, key: str, file_manager: FileManagerToolkit, **kwargs) -> FAISSStore` to `FAISSStore`.
  - Download the file from S3 via `FileManagerToolkit.download_file()`.
  - Load the index using the existing `load()` method.
  - Return the hydrated `FAISSStore` instance.
- Write unit tests with a stub S3 backend (mock FileManagerToolkit).

**NOT in scope**: Warm-up logic (Module 3), handler routes (Module 4), ephemeral registry (Module 1).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/stores/faiss_store.py` | MODIFY | Add `dump_to_s3` and `load_from_s3` methods |
| `tests/unit/test_faiss_s3.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.stores.faiss_store import FAISSStore                     # parrot/stores/faiss_store.py:32
from parrot.tools.filemanager import FileManagerToolkit               # parrot/tools/filemanager.py:515
```

### Existing Signatures to Use
```python
# parrot/stores/faiss_store.py:32
class FAISSStore(AbstractStore):
    def __init__(self, ...) -> None: ...                             # line 48
    def save(self, file_path: Union[str, Path]) -> None: ...         # line 993
    def load(self, file_path: Union[str, Path]) -> None: ...         # line 1039
    async def add_documents(self, documents, **kwargs): ...          # line 367

# parrot/tools/filemanager.py:515
class FileManagerToolkit(AbstractToolkit):
    async def upload_file(                                           # line 719
        self,
        source_path: str,
        destination: Optional[str] = None,
        destination_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        # Returns {"uploaded": True, "name": ..., "path": ..., "size": ..., "url": ...}

    async def download_file(                                         # line 768
        self,
        path: str,
        destination: Optional[str] = None,
    ) -> Dict[str, Any]: ...
```

### Does NOT Exist
- ~~`FAISSStore.dump_to_s3()`~~ — does not exist yet; this task creates it.
- ~~`FAISSStore.load_from_s3()`~~ — does not exist yet; this task creates it.
- ~~`FileManagerToolkit.put_object()`~~ — use `upload_file()` instead.
- ~~`FileManagerToolkit.get_object()`~~ — use `download_file()` instead.

---

## Implementation Notes

### Pattern to Follow
```python
import tempfile
from pathlib import Path

async def dump_to_s3(self, key: str, file_manager: FileManagerToolkit) -> str:
    with tempfile.TemporaryDirectory() as tmpdir:
        local_path = Path(tmpdir) / f"{key}.faiss"
        self.save(local_path)
        result = await file_manager.upload_file(
            source_path=str(local_path),
            destination=f"faiss/{key}",
        )
        return result["path"]

@classmethod
async def load_from_s3(cls, key: str, file_manager: FileManagerToolkit, **kwargs) -> "FAISSStore":
    with tempfile.TemporaryDirectory() as tmpdir:
        local_path = str(Path(tmpdir) / f"{key}.faiss")
        await file_manager.download_file(path=key, destination=local_path)
        store = cls(**kwargs)
        store.load(local_path)
        return store
```

### Key Constraints
- The existing `save()` produces a pickle + `.index` files. Bundle them together (the `save()` method already handles multi-file output).
- Use `tempfile.TemporaryDirectory` for scratch space — never leave temp files behind.
- S3 key convention: `faiss/{chatbot_id}.faiss` — the caller (promote flow) provides the key.
- The spec's open question §8 settled on parquet, but the existing `save()` uses pickle. If converting to parquet is complex, keep pickle for now and document the deviation.

### References in Codebase
- `parrot/stores/faiss_store.py:993` — existing `save()` implementation (pickle + faiss.write_index)
- `parrot/stores/faiss_store.py:1039` — existing `load()` implementation
- `parrot/tools/filemanager.py:719` — `upload_file` API

---

## Acceptance Criteria

- [ ] `dump_to_s3` serializes the current FAISS index and uploads to S3.
- [ ] `load_from_s3` downloads from S3 and returns an equivalent `FAISSStore` instance.
- [ ] Roundtrip test: `dump_to_s3` → `load_from_s3` → same retrieval results.
- [ ] Temp files are cleaned up after upload/download.
- [ ] All tests pass: `pytest tests/unit/test_faiss_s3.py -v`
- [ ] No linting errors: `ruff check parrot/stores/faiss_store.py`
- [ ] Existing `save()` / `load()` callers are untouched.

---

## Test Specification

```python
# tests/unit/test_faiss_s3.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from parrot.stores.faiss_store import FAISSStore


@pytest.fixture
def mock_file_manager():
    fm = MagicMock()
    fm.upload_file = AsyncMock(return_value={
        "uploaded": True, "name": "test.faiss", "path": "faiss/test.faiss",
        "size": 1024, "url": "s3://bucket/faiss/test.faiss",
    })
    fm.download_file = AsyncMock(return_value={
        "downloaded": True, "path": "/tmp/test.faiss",
    })
    return fm


class TestFAISSDumpToS3:
    async def test_dump_uploads_file(self, mock_file_manager):
        store = FAISSStore(collection_name="test")
        # Add some documents first
        ...
        path = await store.dump_to_s3("test-key", mock_file_manager)
        assert path == "faiss/test.faiss"
        mock_file_manager.upload_file.assert_called_once()

    async def test_dump_cleans_temp_files(self, mock_file_manager):
        ...


class TestFAISSLoadFromS3:
    async def test_load_downloads_and_hydrates(self, mock_file_manager):
        ...

    async def test_roundtrip_equivalence(self):
        # End-to-end: create store, add docs, dump, load, verify same results
        ...
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/ephemeral-agents.spec.md` §3 Module 6, §7 FAISS-on-S3 notes.
2. **Check dependencies** — none for this task.
3. **Verify the Codebase Contract** — read `faiss_store.py` `save()`/`load()` implementations.
4. **Update status** in `sdd/tasks/index/ephemeral-agents.json` → `"in-progress"`
5. **Implement** `dump_to_s3` and `load_from_s3` on `FAISSStore`.
6. **Verify** all acceptance criteria are met.
7. **Move this file** to `sdd/tasks/completed/`
8. **Update index** → `"done"`

---

## Completion Note

**Completed by**: sdd-worker (Claude)
**Date**: 2026-05-07
**Notes**: `dump_to_s3` bundles pickle+index files into a `.tar.gz` then uploads via `file_manager.upload_file()`. `load_from_s3` downloads, extracts the tarball, and calls the existing `load()`. 10 unit tests pass (mocked faiss + mocked FileManagerToolkit). Pylint passes.

**Deviations from spec**: Spec §8 Open Questions settled on parquet, but the existing `save()` uses pickle+faiss binary format. Kept pickle/tar.gz to avoid a custom parquet serializer. Deviation documented; can be revisited if a parquet round-trip path is needed.
