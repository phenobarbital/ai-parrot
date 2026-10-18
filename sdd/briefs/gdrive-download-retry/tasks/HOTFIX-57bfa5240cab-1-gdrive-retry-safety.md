# HOTFIX-57bfa5240cab-1: Fix download retry byte duplication and resumable chunk Retry-After

**Feature**: 57bfa5240cab — gdrive download retry safety
**Spec**: `sdd/briefs/gdrive-download-retry.brief.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned
**Discovered-from**: `issue:57bfa5240cab`

---

## Context

Two bugs in `GoogleDriveFileManager` discovered in FEAT-608 code review:
1. Download to a `BinaryIO` stream inside `_retrying` appends duplicate bytes on retry.
2. Resumable upload chunk errors don't carry the response object, so `Retry-After` is ignored.

---

## Scope

- Fix `download_file` to seek back to the initial stream position before each
  retry attempt (seekable streams), or mark the download as `idempotent=False`
  when the stream is not seekable.
- Fix `_upload_resumable._put` to attach the response object to the raised
  `GoogleDriveFileManagerError` so `_retry_after_seconds` can read the
  `Retry-After` header.
- Add regression tests for both bugs.

**NOT in scope**: changing the `Path` download path (already safe), modifying
`_retrying` itself, fixing `issue:25a6ca04919c` (ruff residuals).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/interfaces/file/gdrive.py` | MODIFY | Fix download retry and resumable chunk error |
| `packages/ai-parrot/tests/interfaces/test_gdrive_filemanager.py` | MODIFY | Add regression tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.interfaces.file.gdrive import GoogleDriveFileManager, GoogleDriveFileManagerError, _AsyncSink  # verified: gdrive.py:64,72
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/interfaces/file/gdrive.py:64
class GoogleDriveFileManagerError(RuntimeError):
    def __init__(self, message: str, *, status_code: Optional[int] = None) -> None:  # L67
        self.status_code = status_code  # L69

# packages/ai-parrot/src/parrot/interfaces/file/gdrive.py:72
class _AsyncSink:
    def __init__(self, target: BinaryIO) -> None:  # L75
    async def write(self, chunk: bytes) -> None:  # L78

# packages/ai-parrot/src/parrot/interfaces/file/gdrive.py:443
async def _retrying(self, op, *, label, idempotent=True) -> Tuple[Any, int]:  # L443-460

# packages/ai-parrot/src/parrot/interfaces/file/gdrive.py:398
@staticmethod
def _retry_after_seconds(error: BaseException) -> Optional[float]:  # L399-417
    # reads: getattr(getattr(error, "res", None), "headers", None)

# packages/ai-parrot/src/parrot/interfaces/file/gdrive.py:620
async def download_file(self, source: str, destination: Union[Path, BinaryIO]) -> Path:  # L620-649

# packages/ai-parrot/src/parrot/interfaces/file/gdrive.py:733
async def _upload_resumable(self, *, parent_id, name, existing_id, read, size, content_type) -> Dict:  # L733-800
```

### Does NOT Exist
- ~~`GoogleDriveFileManagerError.res`~~ — not a field; needs to be set manually
- ~~`_AsyncSink.seek`~~ — no seek method on the async adapter

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/interfaces/file/gdrive.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/interfaces/test_gdrive_filemanager.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/interfaces/file/gdrive.py#GoogleDriveFileManagerError",
    "sym:packages/ai-parrot/src/parrot/interfaces/file/gdrive.py#_AsyncSink",
    "sym:packages/ai-parrot/src/parrot/interfaces/file/gdrive.py#GoogleDriveFileManager._retrying",
    "sym:packages/ai-parrot/src/parrot/interfaces/file/gdrive.py#GoogleDriveFileManager._retry_after_seconds",
    "sym:packages/ai-parrot/src/parrot/interfaces/file/gdrive.py#GoogleDriveFileManager.download_file",
    "sym:packages/ai-parrot/src/parrot/interfaces/file/gdrive.py#GoogleDriveFileManager._upload_resumable"
  ]
}
```

---

## Implementation Notes

### Bug 1 fix: download_file BinaryIO retry

In `download_file`, before the `_retrying` call for the `BinaryIO` path (L641-644):
1. Record the initial stream position: `start_pos = destination.tell()` (if seekable).
2. Wrap the download lambda to seek back to `start_pos` before each attempt.
3. If the stream is not seekable, pass `idempotent=False` to `_retrying`.

### Bug 2 fix: _upload_resumable _put Retry-After

In the `_put` closure inside `_upload_resumable` (L785-790):
1. When raising `GoogleDriveFileManagerError`, attach the response: `exc.res = res`.
2. This allows `_retry_after_seconds` at L400 to read `error.res.headers["Retry-After"]`.

### References
- `_gdrive_fakes.py:FakeHTTPError` (L23-37) — sets `.res` on exceptions, confirming the pattern.
- `test_retry_policy_caps_retry_after_and_never_non_idempotent` (L116-133) — existing retry test to follow.

---

## Acceptance Criteria

- [ ] BinaryIO download retries seek back to start position; no duplicate bytes
- [ ] Non-seekable BinaryIO downloads do not retry (idempotent=False)
- [ ] Path downloads remain unchanged (still retry, still safe)
- [ ] Resumable upload chunk 429 honors Retry-After header
- [ ] All existing gdrive tests pass
- [ ] Regression tests cover both bugs
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/interfaces/file/gdrive.py`

---

## Validation Commands

- `pytest packages/ai-parrot/tests/interfaces/test_gdrive_filemanager.py -q`
- `ruff check packages/ai-parrot/src/parrot/interfaces/file/gdrive.py`

---

## Test Specification

```python
# packages/ai-parrot/tests/interfaces/test_gdrive_filemanager.py

@pytest.mark.asyncio
async def test_download_to_stream_seeks_back_on_retry(manager):
    """Bug 1: retry to a BinaryIO sink must not duplicate bytes."""
    result, drive = manager
    drive.drive.put_file("doc.bin", b"hello world")
    buf = io.BytesIO()
    # Patch files_download to fail on first call, succeed on second
    # Assert buf.getvalue() == b"hello world" (no duplication)

@pytest.mark.asyncio
async def test_download_to_non_seekable_stream_does_not_retry(manager):
    """Bug 1: non-seekable BinaryIO must not retry."""
    # Use a stream that raises on seek/tell
    # Assert only one attempt is made

@pytest.mark.asyncio
async def test_resumable_chunk_429_honours_retry_after(manager):
    """Bug 2: resumable upload chunk 429 must read Retry-After from response."""
    # Mock send_raw to return 429 with Retry-After header, then 200
    # Assert the sleep delay matches the Retry-After value
```

---

## Agent Instructions

When you pick up this task:

1. **Work in this worktree** — `.claude/worktrees/fix-57bfa5240cab-gdrive-download-retry`
2. **Read the brief** at the path listed above for full context
3. **Verify the Codebase Contract** before writing code
4. **Implement** the fixes described in Implementation Notes
5. **Run** the validation commands
6. **Commit the code** — stage only the files this task lists
7. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
