# TASK-3812: `gdrive.py` uploads — multipart, resumable session, conflict behaviour

**Feature**: FEAT-608 — Google Drive FileManager
**Spec**: `sdd/specs/google-drive-interface.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-3811
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 4 (upload half; AC7). Below `small_file_threshold` (5 MiB) uploads are
multipart through aiogoogle (`upload_file=` / `pipe_from=`); at or above, `gdrive.py` drives a
**resumable session** itself, because aiogoogle only builds a `ResumableUpload` object and
never speaks the protocol (`aiogoogle/resource.py:654-690`; nothing in `sessions/`).
`conflict_behavior` = `replace` (default, same id) | `fail` | `rename`.

---

## Scope

Add to `GoogleDriveFileManager`: `RESUMABLE_URL`, `_find_conflict`, `_renamed`,
`_upload_small`, `_upload_resumable`, `_apply_conflict` (helper returning
`(name, existing_id)`), `upload_file`, `create_file`, `upload_file_from_bytes`.
Append the upload tests.

**NOT in scope**: copy/delete/rename/folders/sharing (TASK-3813); batch/serving (TASK-3814).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/interfaces/file/gdrive.py` | MODIFY | Upload methods |
| `packages/ai-parrot/tests/interfaces/test_gdrive_filemanager.py` | MODIFY | Upload tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from aiogoogle.models import Request          # verified: .venv/.../aiogoogle/models.py:141 — import INSIDE _upload_resumable
                                              #   (keeps gdrive.py free of module-level aiogoogle, AC13 leak test)
import io, mimetypes                          # stdlib — add to gdrive.py imports
```

### Existing Signatures to Use
```python
# navigator abstract.py
async def upload_file(self, source: Union[BinaryIO, Path], destination: str) -> FileMetadata   # :79
async def create_file(self, path: str, content: bytes) -> bool                                  # :155
# aiogoogle models.py:181-195
Request(method=None, url=None, batch_url=None, headers=None, json=None, data=None, media_upload=None,
        media_download=None, timeout=None, callback=None, _verify_ssl=True, upload_file_content_type=None)
# Response (full_res=True): .status_code, .headers, .json          # models.py:253, :288-304
# DriveClient (TASK-3807): files_create(metadata, *, fields, upload_file=None, pipe_from=None, content_type=None, **params)
#   files_update(file_id, metadata=None, *, fields, add_parents=None, remove_parents=None, upload_file=None,
#                pipe_from=None, content_type=None, **params); send_raw(request, *, full_res=True, raise_for_status=True)
# gdrive.py (TASK-3810/3811): _prefixed, _resolve_parent(create=True), _invalidate, _iter_query, _escape_q,
#   _retrying(idempotent=), _map_error, _make_metadata, _validate_upload_url, _list_params, FIELDS, chunk_size,
#   small_file_threshold, conflict_behavior
# graph.py:796-802 — upload_file_from_bytes precedent (returns the URL string)
```

### Does NOT Exist
- ~~aiogoogle resumable protocol~~ — implement it with `send_raw`.
- ~~`FileManagerInterface.upload_file_from_bytes`~~ — extension (S3 parity).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/interfaces/file/gdrive.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/interfaces/test_gdrive_filemanager.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/interfaces/file/gdrive.py#GoogleDriveFileManager"
  ]
}
```

---

## Implementation Notes

- **Resumable** (spec §7 Uploads): session request
  `Request(method="POST", url=f"{RESUMABLE_URL}?uploadType=resumable&supportsAllDrives=true", headers={"X-Upload-Content-Type": ct, "X-Upload-Content-Length": str(size), "Content-Type": "application/json; charset=UTF-8"}, json=metadata)`
  (`PATCH f"{RESUMABLE_URL}/{existing_id}?uploadType=resumable&supportsAllDrives=true"` for replace;
  metadata then omits `parents`). Send with `send_raw(full_res=True)` wrapped in
  `_retrying(idempotent=False)` → `Location` header → `_validate_upload_url`. Then loop:
  read `chunk_size` bytes, `PUT` with `Content-Range: bytes {start}-{end}/{size}` and
  `Content-Length`, `send_raw(raise_for_status=False)` wrapped in `_retrying(idempotent=True)`
  — raise a synthetic `GoogleDriveFileManagerError(status_code=s)` inside the op for 429/5xx
  so `_retrying` sees it; 308 → next offset = `int(Range.split("-")[1]) + 1` (no `Range` → 0);
  200/201 → return `res.json`. Never log the session URL; never add an `Authorization` header.
- **Sources**: `Path` → size from `stat()`; reads via `aiofiles` is optional — reading the
  file with `open(..., "rb")` in chunks inside `asyncio.to_thread` is acceptable; `BinaryIO` →
  size via `seek(0, 2)`/`tell()` then rewind; unseekable → read into memory only below the
  threshold, else `ValueError` (spec §7 Known Risks). `bytes` for `upload_file_from_bytes` /
  `create_file` → wrap in `io.BytesIO`.
- **Multipart**: `Path` → `upload_file=str(path)`; `BinaryIO` → `pipe_from=<async generator of chunk_size reads>`;
  always `content_type=` (guess with `mimetypes.guess_type(name)` else `application/octet-stream`).
- **Conflicts**: `_find_conflict(parent_id, name)` = first item of
  `_iter_query(f"'{pid}' in parents and name = '{esc}' and trashed = false", order_by="modifiedTime desc")`.
  `replace` → pass its id as `existing_id`; `fail` → `FileExistsError(destination)`;
  `rename` → `_renamed(name, taken)` where `taken` = all child names of the parent:
  `report.pdf` → `report (1).pdf`, `report (2).pdf` … first free.
- After every write: `self._invalidate(full_path)`; return `_make_metadata(item, full_path=...)`.
- `upload_file_from_bytes(file_obj, destination_key, content_type)` returns `webViewLink` (str).

---

## Implementation Blueprint

### Steps (in order)
1. Add `import io`, `import mimetypes` and the `RESUMABLE_URL` class constant — *why*: used below.
2. Add conflict helpers — *why*: shared by uploads and TASK-3813's rename/move.
3. Add `_upload_small` and `_upload_resumable` — *why*: AC7 routing.
4. Add the public upload methods; append tests.

### `gdrive.py` (MODIFY — class constant)
```python
# occurrences: 1 (verified: grep -c '    LIST_FIELDS: str = ' gdrive.py — created by TASK-3810)
# AFTER — insert below `    LIST_FIELDS: str = "nextPageToken,files(" + FIELDS + ")"`
    RESUMABLE_URL: str = "https://www.googleapis.com/upload/drive/v3/files"
```

### `gdrive.py` (MODIFY — upload methods appended after TASK-3811's `download_file`)
```python
    # ---- uploads (TASK-3812) ---------------------------------------------
    async def _find_conflict(self, parent_id: str, name: str) -> Optional[Dict[str, Any]]:
        q = f"'{parent_id}' in parents and name = '{self._escape_q(name)}' and trashed = false"
        async for item in self._iter_query(q, order_by="modifiedTime desc"):
            return item
        return None

    def _renamed(self, name: str, taken: set[str]) -> str:
        stem, dot, ext = name.rpartition(".") if "." in name.lstrip(".") else (name, "", "")
        # FILL IN: first n>=1 with f"{stem} ({n}){dot}{ext}" not in taken
        raise NotImplementedError

    async def _apply_conflict(self, parent_id: str, name: str, destination: str) -> Tuple[str, Optional[str]]:
        """Return ``(final_name, existing_id)`` per ``conflict_behavior``."""
        # FILL IN: replace → (name, id|None); fail → FileExistsError(destination) when existing;
        #          rename → (_renamed(name, taken), None) when existing — bounded by AC7
        raise NotImplementedError

    async def _upload_small(self, *, parent_id: str, name: str, existing_id: Optional[str],
                            source: Union[Path, BinaryIO], content_type: str) -> Dict[str, Any]:
        # FILL IN: files_create({"name", "parents": [parent_id]}, ...) or files_update(existing_id, {"name"}, ...)
        #          with upload_file=str(path) | pipe_from=async-gen, content_type=, fields=FIELDS, **_list_params();
        #          via _retrying(label="upload") — bounded by Implementation Notes (Multipart)
        raise NotImplementedError

    async def _upload_resumable(self, *, parent_id: str, name: str, existing_id: Optional[str],
                                read: Callable[[int], Awaitable[bytes]], size: int, content_type: str) -> Dict[str, Any]:
        from aiogoogle.models import Request   # lazy: no module-level aiogoogle import in gdrive.py

        # FILL IN: session POST/PATCH (idempotent=False) → Location → _validate_upload_url; chunk loop with
        #          308/Range resume and 200/201 completion — bounded by Implementation Notes (Resumable), AC7
        raise NotImplementedError

    async def upload_file(self, source: Union[BinaryIO, Path], destination: str) -> FileMetadata:
        """Route by ``small_file_threshold``; apply ``conflict_behavior``; ensure parents; invalidate cache."""
        await self._ready()
        full = self._prefixed(destination)
        parent_id = await self._resolve_parent(full, create=True)
        name = full.rsplit("/", 1)[-1]
        final_name, existing_id = await self._apply_conflict(parent_id, name, destination)
        # FILL IN: measure size (Path.stat / seek-tell / unseekable rule), guess content type, route to
        #          _upload_small or _upload_resumable, map errors with _map_error(path=destination),
        #          _invalidate(parent path + final name), return _make_metadata
        raise NotImplementedError

    async def create_file(self, path: str, content: bytes) -> bool:
        await self.upload_file(io.BytesIO(content), path)
        return True

    async def upload_file_from_bytes(self, file_obj: bytes, destination_key: str,
                                     content_type: str = "application/octet-stream") -> str:
        """Upload raw bytes and return the item's ``webViewLink`` (S3 parity)."""
        # FILL IN: as upload_file but honour the explicit content_type; return item["webViewLink"] (or metadata.url)
        raise NotImplementedError
```
**Why**: the session POST is non-idempotent (a retry would open a second session), chunk PUTs
are idempotent for the same byte range — hence the two `idempotent` values (AC7, spec §7 Retry policy).

### `test_gdrive_filemanager.py` (MODIFY — append)
```python
async def test_upload_small_multipart_create_and_replace(manager, tmp_path): ...
async def test_upload_resumable_session_chunks_308_and_range_resume(manager, monkeypatch): ...
    # small_file_threshold=chunk_size=262144, 600 KiB payload → POST + 3 PUTs; Content-Range exact;
    # fail_next(503, method="PUT") retried; fail_next(503, method="POST") NOT retried (raises)
async def test_upload_session_url_validated_and_not_logged(manager, caplog): ...
async def test_upload_conflict_replace_fail_rename(manager): ...
async def test_upload_unseekable_stream_above_threshold_refused(manager): ...
async def test_create_file_and_upload_file_from_bytes_returns_webviewlink(manager): ...
```

### FILL IN checklist
- [ ] `_renamed`, `_apply_conflict`.
- [ ] `_upload_small` (Path / BinaryIO).
- [ ] `_upload_resumable` protocol.
- [ ] `upload_file` routing + size measurement; `upload_file_from_bytes`.
- [ ] 6 tests.

---

## Acceptance Criteria

- [ ] AC7 fully covered.
- [ ] Earlier tests in the module still pass.

## Validation Commands
- `pytest packages/ai-parrot/tests/interfaces/test_gdrive_filemanager.py -q`

---

## Agent Instructions
Standard. `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-tools/src` inside the worktree.

---

## Completion Note

*(Agent fills this in when done)*
