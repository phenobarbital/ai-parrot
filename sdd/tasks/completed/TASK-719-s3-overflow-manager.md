# TASK-719: S3 Overflow Manager

**Feature**: FEAT-103 — Agent Artifact Persistency
**Spec**: `sdd/specs/agent-artifact-persistency.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-717
**Assigned-to**: unassigned

---

## Context

Implements spec Module 3. Handles transparent offloading of large artifact definitions (> 200KB) to S3, keeping a reference in DynamoDB. This prevents hitting the 400KB DynamoDB item limit.

---

## Scope

- Create `parrot/storage/s3_overflow.py` with `S3OverflowManager` class
- Implement `maybe_offload(data, key_prefix)` — decides inline vs S3 based on 200KB threshold
- Implement `resolve(definition, definition_ref)` — returns definition, fetching from S3 if needed
- Implement `delete(definition_ref)` — delete S3 object if ref exists
- Use existing `S3FileManager.create_from_bytes()` for uploads
- S3 key pattern: `{key_prefix}/{artifact_id}.json`
- Configuration: bucket name from `parrot.conf` (`S3_ARTIFACT_BUCKET`)
- Write unit tests

**NOT in scope**: DynamoDB operations, ArtifactStore business logic, API endpoints.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/storage/s3_overflow.py` | CREATE | S3OverflowManager class |
| `parrot/storage/__init__.py` | MODIFY | Export S3OverflowManager |
| `tests/storage/test_s3_overflow.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.interfaces.file.s3 import S3FileManager   # parrot/interfaces/file/s3.py:15
from navconfig.logging import logging
```

### Existing Signatures to Use
```python
# parrot/interfaces/file/s3.py:15
class S3FileManager:
    def __init__(self, bucket_name, aws_id='default', region_name=None,
                 prefix="", ...):  # line 15
    async def create_from_bytes(self, data, remote_path, content_type=None):  # line 470
    async def download_file(self, remote_path, local_path):  # line 355
    async def delete_file(self, remote_path):  # line 417
    async def get_file_url(self, remote_path, expires_in=3600):  # line 337
```

### Does NOT Exist
- ~~`S3FileManager.create_from_json()`~~ — does not exist; use `create_from_bytes()` with JSON bytes
- ~~`S3FileManager.download_to_bytes()`~~ — does not exist; `download_file()` writes to disk
- ~~`S3FileManager.read_bytes()`~~ — does not exist
- ~~`parrot.storage.s3_overflow`~~ — does not exist yet; this task creates it

---

## Implementation Notes

### Pattern to Follow
```python
import json
import tempfile
from parrot.interfaces.file.s3 import S3FileManager
from navconfig.logging import logging


class S3OverflowManager:
    INLINE_THRESHOLD = 200 * 1024  # 200KB

    def __init__(self, s3_file_manager: S3FileManager):
        self._s3 = s3_file_manager
        self.logger = logging.getLogger("parrot.storage.S3OverflowManager")

    async def maybe_offload(self, data: dict, key_prefix: str
                            ) -> tuple[dict | None, str | None]:
        """Returns (inline_data, None) if small, or (None, s3_key) if offloaded."""
        json_bytes = json.dumps(data).encode("utf-8")
        if len(json_bytes) < self.INLINE_THRESHOLD:
            return data, None
        # Offload to S3
        s3_key = f"{key_prefix}.json"
        await self._s3.create_from_bytes(json_bytes, s3_key, content_type="application/json")
        self.logger.info(f"Offloaded {len(json_bytes)} bytes to S3: {s3_key}")
        return None, s3_key
```

### Key Constraints
- `maybe_offload` returns a tuple: `(inline_data, None)` or `(None, s3_key)`
- `resolve` must handle both cases: if `definition` is not None, return it; if `definition_ref` is set, download from S3
- Since `S3FileManager.download_file()` writes to disk, use a temp file for download, read it, then clean up
- Alternatively, use `aioboto3` directly via the S3FileManager's session for `get_object` — check what's available
- JSON encoding uses `json.dumps(...).encode("utf-8")`
- Content-type for S3 uploads: `application/json`

---

## Acceptance Criteria

- [ ] `S3OverflowManager` class exists in `parrot/storage/s3_overflow.py`
- [ ] `from parrot.storage import S3OverflowManager` works
- [ ] Data < 200KB returns inline (no S3 upload)
- [ ] Data >= 200KB uploads to S3 and returns key
- [ ] `resolve()` returns definition when inline
- [ ] `resolve()` downloads from S3 when `definition_ref` is set
- [ ] `delete()` removes S3 object
- [ ] Unit tests pass: `pytest tests/storage/test_s3_overflow.py -v`

---

## Test Specification

```python
# tests/storage/test_s3_overflow.py
import pytest
import json
from unittest.mock import AsyncMock, MagicMock
from parrot.storage.s3_overflow import S3OverflowManager


@pytest.fixture
def mock_s3():
    return AsyncMock()


@pytest.fixture
def overflow(mock_s3):
    return S3OverflowManager(s3_file_manager=mock_s3)


class TestS3OverflowManager:
    @pytest.mark.asyncio
    async def test_small_data_stays_inline(self, overflow, mock_s3):
        small_data = {"key": "value"}
        definition, ref = await overflow.maybe_offload(small_data, "prefix/art-1")
        assert definition == small_data
        assert ref is None
        mock_s3.create_from_bytes.assert_not_called()

    @pytest.mark.asyncio
    async def test_large_data_offloaded(self, overflow, mock_s3):
        large_data = {"data": "x" * (250 * 1024)}  # > 200KB
        definition, ref = await overflow.maybe_offload(large_data, "prefix/art-1")
        assert definition is None
        assert ref is not None
        mock_s3.create_from_bytes.assert_called_once()

    @pytest.mark.asyncio
    async def test_resolve_inline(self, overflow):
        data = {"key": "value"}
        result = await overflow.resolve(definition=data, definition_ref=None)
        assert result == data

    @pytest.mark.asyncio
    async def test_delete_calls_s3(self, overflow, mock_s3):
        await overflow.delete("s3://bucket/key.json")
        mock_s3.delete_file.assert_called_once()
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/agent-artifact-persistency.spec.md` — Section 2 (S3OverflowManager interface)
2. **Check dependencies** — TASK-717 must be completed
3. **Read** `parrot/interfaces/file/s3.py` to verify S3FileManager methods
4. **Update status** in `tasks/.index.json` → `"in-progress"`
5. **Implement** S3OverflowManager
6. **Run tests**: `pytest tests/storage/test_s3_overflow.py -v`
7. **Move this file** to `tasks/completed/`
8. **Update index** → `"done"`

---

## Completion Note

*(Agent fills this in when done)*
