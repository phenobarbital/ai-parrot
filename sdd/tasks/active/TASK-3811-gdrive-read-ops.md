# TASK-3811: `gdrive.py` read operations — list, exists, metadata, search, download

**Feature**: FEAT-608 — Google Drive FileManager
**Spec**: `sdd/specs/google-drive-interface.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3810
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 3 (AC5, AC9, AC12). Adds the read surface to `GoogleDriveFileManager`
(created by TASK-3810 in the same file). Every listing follows `nextPageToken` to exhaustion.

---

## Scope

Add these methods to `GoogleDriveFileManager` (spec §3 M3 signatures, verbatim):
`_iter_children`, `_iter_query`, `list_files`, `list_entries`, `exists`, `get_file_metadata`,
`find_entries`, `find_files`, `download_file`. Append the M3 tests to `test_gdrive_filemanager.py`.

**NOT in scope**: any write op; the toolkit's `max_results` (TASK-3816 applies it; here
`find_*` return all matches).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/interfaces/file/gdrive.py` | MODIFY | Read methods |
| `packages/ai-parrot/tests/interfaces/test_gdrive_filemanager.py` | MODIFY | M3 tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# Already in gdrive.py from TASK-3810: fnmatch is NOT — add `import fnmatch` to the stdlib import block.
from navigator.utils.file import FileManagerInterface, FileMetadata    # verified: abstract.py:16, :36
from .entries import DriveEntry                                         # TASK-3808
```

### Existing Signatures to Use
```python
# navigator/utils/file/abstract.py — exact signatures to implement
async def list_files(self, path: str = "", pattern: str = "*") -> List[FileMetadata]          # :53
async def download_file(self, source: str, destination: Union[Path, BinaryIO]) -> Path         # :93
async def exists(self, path: str) -> bool                                                      # :130
async def get_file_metadata(self, path: str) -> FileMetadata                                   # :141
async def find_files(self, keywords=None, extension=None, prefix=None) -> List[FileMetadata]   # :265 (in-memory default; we override)

# gdrive.py (TASK-3810): _prefixed, _resolve, _list_params, _retrying, _map_error, _make_metadata, _make_entry,
#   _is_folder, _is_workspace_native, _ready, drive (property), FIELDS, LIST_FIELDS, LIST_PAGE_SIZE, _AsyncSink,
#   GoogleDriveFileManagerError
# DriveClient (TASK-3807): files_list(*, q, fields, page_size, page_token, order_by, drive_id, **params);
#   files_get(file_id, *, fields, **params); files_download(file_id, *, download_file=None, pipe_to=None, **params)
```

### Does NOT Exist
- ~~`FileManagerInterface.list_entries` / `.find_entries`~~ — extensions, not interface methods.
- ~~Server-side `fileExtension` filter~~ — apply `extension` client-side (spec §2 Listing semantics).

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

- Every Drive call goes through `self._retrying(lambda: ..., label=...)` and errors through
  `self._map_error(exc, path=...)` — never let `aiogoogle.excs.HTTPError` escape (spec §7 Errors).
- `_iter_children(folder_id)`: `q = f"'{folder_id}' in parents and trashed = false"`.
- `find_entries`: first keyword server-side `name contains '<escaped kw>'` combined with
  `mimeType != '{FOLDER_MIME}' and trashed = false`; the query is scoped by walking folder ids
  under `prefix` (BFS over `_iter_children` folders) — issue one `_iter_query` per folder id
  with `'<id>' in parents and ...`; AND the remaining keywords (case-insensitive substring) and
  `extension` (case-insensitive suffix, leading `.` optional) client-side.
- Paths returned are unprefixed and relative to the manager root (as S3).
- `download_file` to `Path`: `destination.parent.mkdir(parents=True, exist_ok=True)`, then
  `files_download(id, download_file=str(destination))`, return `destination`; to `BinaryIO`:
  `pipe_to=_AsyncSink(destination)`, return `Path(source)`. Resolve with `want_folder=False`;
  Workspace-native MIME → `GoogleDriveFileManagerError("Google Workspace files cannot be downloaded; export is not supported in v1")`.
- `exists` returns `True` for folders; `False` on `FileNotFoundError`.

---

## Implementation Blueprint

### Steps (in order)
1. Add `import fnmatch` to the stdlib imports — *why*: `list_files` pattern match.
2. Add the two iterators — *why*: every listing shares the pagination loop (AC12).
3. Add the public read methods — *why*: interface + extension surface.
4. Append tests.

### `gdrive.py` (MODIFY — methods appended to `GoogleDriveFileManager`)
```python
# occurrences: 1 (verified: grep -c '    def _validate_upload_url(self, url: str) -> str:' gdrive.py)
# AFTER — append below the body of `_validate_upload_url` (last method written by TASK-3810)
    # ---- read operations (TASK-3811) -------------------------------------
    async def _iter_query(self, q: str, *, order_by: Optional[str] = None) -> AsyncIterator[Dict[str, Any]]:
        """Yield every file matching ``q`` across all pages (AC12)."""
        page_token: Optional[str] = None
        while True:
            # FILL IN: page, _ = await self._retrying(lambda: self.drive.files_list(q=q, fields=self.LIST_FIELDS,
            #          page_size=self.LIST_PAGE_SIZE, page_token=page_token, order_by=order_by, **self._list_params()),
            #          label="list"); map errors; yield each of page.get("files", []); break when no nextPageToken
            raise NotImplementedError

    async def _iter_children(self, folder_id: str) -> AsyncIterator[Dict[str, Any]]:
        async for item in self._iter_query(f"'{folder_id}' in parents and trashed = false"):
            yield item

    async def list_files(self, path: str = "", pattern: str = "*") -> List[FileMetadata]:
        """Non-recursive; folders excluded; fnmatch on name; all pages."""
        await self._ready()
        full = self._prefixed(path)
        folder_id, _ = await self._resolve(full, want_folder=True)
        # FILL IN: collect _make_metadata(item, full_path=f"{full}/{item['name']}".strip("/")) for non-folder
        #          children whose name matches pattern
        raise NotImplementedError

    async def list_entries(self, path: str = "") -> List[DriveEntry]:
        """Non-recursive INCLUDING folders; all pages."""
        # FILL IN: as list_files but every child, via _make_entry
        raise NotImplementedError

    async def exists(self, path: str) -> bool:
        # FILL IN: _ready(); _resolve(_prefixed(path)) → True; FileNotFoundError → False
        raise NotImplementedError

    async def get_file_metadata(self, path: str) -> FileMetadata:
        # FILL IN: _resolve → files_get(id, fields=FIELDS, **_list_params()) via _retrying → _make_metadata
        raise NotImplementedError

    async def find_entries(self, keywords: Optional[Union[str, List[str]]] = None, extension: Optional[str] = None,
                           prefix: Optional[str] = None) -> List[DriveEntry]:
        """Server-side ``name contains`` for the first keyword, recursive under ``prefix``; files only."""
        # FILL IN: per Implementation Notes (BFS over folder ids, client-side AND of remaining keywords + extension)
        raise NotImplementedError

    async def find_files(self, keywords=None, extension=None, prefix=None) -> List[FileMetadata]:
        # FILL IN: map find_entries results to FileMetadata (keep the interface signature exactly, abstract.py:265)
        raise NotImplementedError

    async def download_file(self, source: str, destination: Union[Path, BinaryIO]) -> Path:
        """Stream via aiogoogle (``download_file=`` / ``pipe_to=_AsyncSink``); Workspace-native → error (AC9)."""
        # FILL IN: per Implementation Notes
        raise NotImplementedError
```
**Why**: signatures fixed by spec §3 M3 and `abstract.py`; `find_files` must keep the untyped
interface signature so TASK-3817's `inspect.signature` parity test passes (AC1).

### `test_gdrive_filemanager.py` (MODIFY — append)
```python
# AFTER — append at end of file (created by TASK-3810)
async def test_list_files_excludes_folders_and_follows_page_tokens(manager): ...   # 5 children, page_size=2 → 3 pages
async def test_list_entries_includes_folders_all_pages(manager): ...
async def test_list_params_shared_drive_flags(): ...    # corpora/driveId/includeItemsFromAllDrives iff shared_drive_id; supportsAllDrives always
async def test_exists_and_metadata(manager): ...
async def test_find_files_server_side_contains_then_client_filters(manager): ...
async def test_search_paginates_then_applies_extension(manager): ...
async def test_download_to_path_and_binaryio_streams(manager, tmp_path): ...
async def test_download_workspace_native_raises(manager): ...
```

### FILL IN checklist
- [ ] `_iter_query` pagination; `list_files` / `list_entries` / `exists` / `get_file_metadata`.
- [ ] `find_entries` BFS + client-side filters; `find_files`.
- [ ] `download_file` both destinations + Workspace error.
- [ ] 8 tests.

---

## Acceptance Criteria

- [ ] AC9, AC12 (manager side), AC5 listing flags.
- [ ] TASK-3810 tests still pass.

## Validation Commands
- `pytest packages/ai-parrot/tests/interfaces/test_gdrive_filemanager.py -q`

---

## Agent Instructions
Standard. `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-tools/src` inside the worktree.

---

## Completion Note

*(Agent fills this in when done)*
