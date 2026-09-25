# TASK-3752: GraphDriveFileManager transfer ops — folder chain, small PUT, upload session, bytes upload, streaming download

**Feature**: FEAT-603 — SharePoint & OneDrive FileManager
**Spec**: `sdd/specs/sharepoint-filemanager.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-3751
**Assigned-to**: unassigned

---

## Context

Spec §3 **Module 1** (fourth of six `graph.py` tasks), AC5 (upload routing + conflict behaviour), AC6 (streaming
download), AC9 (`upload_file_from_bytes`), AC21 (outbound URL boundary) and design research S5/S6. The Upload/Download
tools (TASK-3762, TASK-3764) and the batch engine (TASK-3754) are built on these methods.

**Task-time decision — conflict behaviour on small files.** Graph's `PUT …/content` has no request-body slot for
`@microsoft.graph.conflictBehavior` in msgraph-sdk 1.63, and its default is *replace*. So: files below
`small_file_threshold` with `conflict_behavior == "replace"` use the single PUT; **every** `fail` / `rename` upload,
regardless of size, goes through an upload session whose body carries the conflict behaviour. This satisfies AC5
("routes by threshold … honours fail / rename") without query-string hacks.

**Task-time finding.** The clients' own session helpers hard-code `"replace"` (`interfaces/sharepoint.py:395`,
`interfaces/onedrive.py:609`) and are not reused; the base builds its own session body.

---

## Scope

- Append to `GraphDriveFileManager`: `_ensure_parent`, `_put_small`, `_create_session`, `_put_session`,
  `upload_file`, `create_file`, `upload_file_from_bytes`, `download_file`.
- Append the tests of this task to `test_graph_filemanager.py`.

**NOT in scope**: copy/links/folders/rename (3753); batch/serving (3754).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/interfaces/file/graph.py` | MODIFY | transfer ops |
| `packages/ai-parrot/tests/interfaces/test_graph_filemanager.py` | MODIFY | append transfer tests |

---

## Codebase Contract (Anti-Hallucination)

> Re-verified 2026-09-25 against `dev` at `8da1f45c3`, msgraph-sdk 1.63.0.

### Verified Imports
```python
import io                                                     # stdlib
from pathlib import Path                                      # stdlib
from typing import BinaryIO                                   # stdlib
import aiofiles                                               # already a dependency (imported by interfaces/onedrive.py:7)
from msgraph.generated.models.drive_item import DriveItem     # verified: interfaces/sharepoint.py:15
from msgraph.generated.models.folder import Folder            # verified: interfaces/sharepoint.py:16
from msgraph.generated.models.drive_item_uploadable_properties import DriveItemUploadableProperties   # verified: interfaces/sharepoint.py:22
from msgraph.generated.drives.item.items.item.create_upload_session.create_upload_session_post_request_body import (
    CreateUploadSessionPostRequestBody,
)                                                             # verified: interfaces/sharepoint.py:19-21
```

### Existing Signatures to Use
```python
# msgraph-sdk 1.63 builders (…/msgraph/generated/drives/item/items/item/)
content/content_request_builder.py:       async def put(self, body: bytes, request_configuration=None) -> Optional[DriveItem]   # :69
children/children_request_builder.py:     async def post(self, body: DriveItem, request_configuration=None) -> Optional[DriveItem]   # :71
create_upload_session/create_upload_session_request_builder.py:  async def post(self, body: CreateUploadSessionPostRequestBody, ...) -> Optional[UploadSession]   # :34
# UploadSession.upload_url: str ; DriveItem.additional_data["@microsoft.graph.downloadUrl"]: str (pre-authenticated, ~1 h)

# Body/ref pattern being mirrored — packages/ai-parrot/src/parrot/interfaces/sharepoint.py:390-406
#   body = CreateUploadSessionPostRequestBody(); body.item = DriveItemUploadableProperties()
#   body.item.additional_data = {"@microsoft.graph.conflictBehavior": "replace"}          <- base makes this configurable
#   drives.by_drive_id(drive_id).items.by_drive_item_id(f"{parent_id}:/{quote(name)}:/").create_upload_session.post(body)
# Chunk-PUT pattern being mirrored — sharepoint.py:408-470 (Content-Length + Content-Range "bytes a-b/total";
#   202 = continue, 200/201 = final JSON item). Its "Retry-After only on 202" handling is NOT the model (S5).

# FileManagerInterface (abstract.py) signatures to match EXACTLY:
async def upload_file(self, source: Union[BinaryIO, Path], destination: str) -> FileMetadata       # :79
async def download_file(self, source: str, destination: Union[Path, BinaryIO]) -> Path             # :93
async def create_file(self, path: str, content: bytes) -> bool                                     # :155
# S3 parity — navigator/utils/file/s3.py:571
async def upload_file_from_bytes(self, file_obj: bytes, destination_key: str, content_type: str = "application/octet-stream") -> str
# From TASK-3750/3751: _ready, _prefixed, _item_ref, _drive, _get_item, _get_item_by_id, _retrying, _map_error,
#   _status_code_of, _validate_graph_url, _http_session, _RawHTTPError, _make_metadata
```

### Does NOT Exist
- ~~a `conflictBehavior` parameter on `ContentRequestBuilder.put`~~ — hence the routing decision in Context.
- ~~`SharepointClient._create_upload_session(..., conflict=...)`~~ — hard-coded `replace`; do not call it.
- ~~`OneDriveClient._upload_large_file_content` for the manager~~ — superseded by `_put_session` (configurable, S5/S6).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/interfaces/file/graph.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/interfaces/test_graph_filemanager.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/interfaces/sharepoint.py#SharepointClient._create_upload_session",
    "sym:packages/ai-parrot/src/parrot/interfaces/sharepoint.py#SharepointClient._upload_large_file"
  ]
}
```

---

## Implementation Notes

- **`_ensure_parent(full_path)`**: walk the parent segments from the drive root; `_get_item` each; on status 404 create it
  with `children.post(DriveItem(name=seg, folder=Folder(), additional_data={"@microsoft.graph.conflictBehavior":
  "fail"}))` on the previous folder's id; a 409 (lost race) re-`_get_item`s. Returns the parent DriveItem (root when the
  path has one segment).
- **`_put_session(upload_url, read, size)`**: `self._validate_graph_url(upload_url, purpose="upload session")` first.
  `read(n)` is an async callable returning the next `n` bytes. For each chunk of `chunk_size`: PUT with ONLY
  `Content-Length` and `Content-Range: bytes {start}-{end}/{size}` headers, `allow_redirects=False`, inside
  `_retrying(..., label="upload-chunk")` (re-sending the same range is idempotent). 202 → next chunk; 200/201 → return
  the JSON dict; other → `_RawHTTPError`. Ending without a final response → `GraphFileManagerError` naming the byte offset
  (spec §7) — never the URL.
- **`upload_file(source, destination)`**: accept `Path`, `str` (a path) or a binary stream. Size: `Path.stat()` via
  `asyncio.to_thread`; for a seekable stream use `tell()/seek()`; a non-seekable stream is read fully into memory first.
  Routing rule in Context. Local file reads use `aiofiles`; stream reads use `asyncio.to_thread(stream.read, n)`. After a
  session completes, fetch `_get_item_by_id(result["id"])` and return `_make_metadata(item, full_path=dest_full)`.
  `_create_session` runs with `idempotent=False` (S5).
- **`create_file(path, content)`** → `upload_file(io.BytesIO(content), path)`; returns `True`.
- **`upload_file_from_bytes(file_obj, destination_key, content_type)`** → `upload_file(...)`, return `metadata.url`.
  `content_type` is logged at DEBUG only: Graph derives the MIME type from the file name (documented in TASK-3766).
- **`download_file(source, destination)`**: item via `_get_item`; a folder → `IsADirectoryError`; the URL is
  `item.additional_data["@microsoft.graph.downloadUrl"]` (missing → `GraphFileManagerError`), validated with
  `purpose="download"`, fetched with `allow_redirects=False` and no auth header, streamed with
  `resp.content.iter_chunked(1024 * 1024)`. A `Path`/`str` destination is written with `aiofiles` (create parent dirs via
  `asyncio.to_thread`); a stream destination via `asyncio.to_thread(dest.write, chunk)`. Never buffer the whole file.
  Return `Path(destination)` for path destinations, `Path(source)` for streams (S3 parity).

### Key Constraints (all FEAT-603 tasks)
- **aiohttp only** for raw HTTP. `httpx`, `requests`, `langchain*` are banned (ruff TID251). The two legacy
  clients carry an unused `import httpx` (`interfaces/sharepoint.py:11`, `interfaces/onedrive.py:10`) — never copy
  their import blocks into new code.
- **Core never imports the tools distribution**: nothing under `packages/ai-parrot/src/parrot/` may import
  `parrot_tools` (the retry helpers of `parrot_tools/o365/delta.py` are *re-implemented*, not imported).
- Pydantic v2 models; Google-style docstrings and strict type hints on every function/class; `self.logger`
  (or a module `logger = logging.getLogger(__name__)`), never `print`; `black` line length 120; `ruff check` clean.
- **Never log** upload-session `uploadUrl`s, copy monitor URLs, `@microsoft.graph.downloadUrl`s, tokens or secrets.
- **Byte-identical files** (no edit, ever, in this feature): `packages/ai-parrot/src/parrot/interfaces/sharepoint.py`,
  `packages/ai-parrot/src/parrot/interfaces/o365.py`, `packages/ai-parrot-tools/src/parrot_tools/o365/delta.py`,
  `packages/ai-parrot-tools/src/parrot_tools/o365/bundle.py`, `packages/ai-parrot-tools/src/parrot_tools/o365/base.py`,
  and the `Delta*Args` / `Delta*Tool` class blocks inside `parrot_tools/o365/{sharepoint,onedrive}.py` (FEAT-539).
- Tests never construct a real `O365Client` / `SharepointClient` / `OneDriveClient` (their `__init__` builds an
  aioredis client, `o365.py:198-200`) — use the fakes of TASK-3748 and `GraphDriveFileManager.adopt_client`.
- Tests are async with `asyncio_mode = auto` (`pytest.ini:3`); the `live` marker is registered (`pytest.ini:6`).
- **Worktree testing**: the shared `.venv` is editable-installed against the MAIN checkout, so run
  `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-tools/src timeout -s KILL 600 pytest <file> -q`.
  Never `uv sync` inside a worktree.

---

## Implementation Blueprint

### Steps (in order)
1. Add the imports — *why*: models, session body and aiofiles.
2. Append the private helpers, then the public methods — *why*: the batch engine (3754) calls the public ones.
3. Append the tests.

### `packages/ai-parrot/src/parrot/interfaces/file/graph.py` (MODIFY) — imports
```python
# occurrences: 1 (expected after TASK-3749; verify: grep -c '^from navigator.utils.file import FileManagerInterface, FileMetadata$' graph.py)
# BEFORE — insert these lines above `from navigator.utils.file import FileManagerInterface, FileMetadata`
import io
from pathlib import Path
from typing import BinaryIO

import aiofiles
from msgraph.generated.drives.item.items.item.create_upload_session.create_upload_session_post_request_body import (
    CreateUploadSessionPostRequestBody,
)
from msgraph.generated.models.drive_item import DriveItem
from msgraph.generated.models.drive_item_uploadable_properties import DriveItemUploadableProperties
from msgraph.generated.models.folder import Folder
```

### `packages/ai-parrot/src/parrot/interfaces/file/graph.py` (MODIFY) — private transfer helpers (append)
```python
# occurrences: 1 (expected after TASK-3751; verify: grep -c '    async def delete_file(self, path: str) -> bool:' graph.py)
# AFTER — append at the end of the class body (after `delete_file`)
    async def _ensure_parent(self, full_path: str) -> Any:
        """Ensure the parent folder chain of ``full_path`` exists and return the parent DriveItem."""
        # FILL IN: rule in Implementation Notes

    async def _put_small(self, parent_id: str, name: str, data: bytes) -> Any:
        """Single PUT …/{parent}:/{name}:/content (Graph default conflict behaviour: replace)."""
        ref = f"{parent_id}:/{quote(name, safe='')}:"
        item, _ = await self._retrying(
            lambda: self._drive().items.by_drive_item_id(ref).content.put(data), label="content-put"
        )
        return item

    async def _create_session(self, parent_id: str, name: str) -> str:
        """POST createUploadSession with ``conflict_behavior``; returns the pre-authenticated upload URL."""
        body = CreateUploadSessionPostRequestBody()
        body.item = DriveItemUploadableProperties()
        body.item.additional_data = {"@microsoft.graph.conflictBehavior": self.conflict_behavior}
        ref = f"{parent_id}:/{quote(name, safe='')}:"
        session, _ = await self._retrying(
            lambda: self._drive().items.by_drive_item_id(ref).create_upload_session.post(body),
            label="create-upload-session",
            idempotent=False,
        )
        return session.upload_url

    async def _put_session(
        self, upload_url: str, read: Callable[[int], Awaitable[bytes]], size: int
    ) -> Dict[str, Any]:
        """Chunked PUTs to the upload session (validated URL, no auth header, no redirects)."""
        url = self._validate_graph_url(upload_url, purpose="upload session")
        offset = 0
        async with self._http_session() as session:
            while offset < size:
                chunk = await read(min(self.chunk_size, size - offset))
                # FILL IN: PUT rule in Implementation Notes; 202 -> offset += len(chunk); 200/201 -> return JSON
        raise GraphFileManagerError(f"upload session ended at byte {offset} of {size} without a final item")
```

### `packages/ai-parrot/src/parrot/interfaces/file/graph.py` (MODIFY) — public transfer ops (append)
```python
# AFTER — append below `_put_session` (added by the previous block of this task)
    async def upload_file(self, source: Union[BinaryIO, Path], destination: str) -> FileMetadata:
        """Upload a local file or binary stream; single PUT or upload session (AC5). Returns the item metadata."""
        await self._ready()
        dest_full = self._prefixed(destination)
        try:
            parent = await self._ensure_parent(dest_full)
            name = dest_full.rsplit("/", 1)[-1]
            # FILL IN: size + reader per Implementation Notes; routing per Context; after a session, refetch by id;
            #          return self._make_metadata(item, full_path=dest_full)
        except Exception as exc:
            raise self._map_error(exc, path=destination) from exc

    async def create_file(self, path: str, content: bytes) -> bool:
        """Upload ``content`` to ``path``; True on success."""
        await self.upload_file(io.BytesIO(content), path)
        return True

    async def upload_file_from_bytes(
        self, file_obj: bytes, destination_key: str, content_type: str = "application/octet-stream"
    ) -> str:
        """S3-parity bytes upload; returns the item's ``web_url``."""
        self.logger.debug("upload_file_from_bytes: content_type=%s (Graph infers MIME from the name)", content_type)
        meta = await self.upload_file(io.BytesIO(file_obj), destination_key)
        return meta.url or ""

    async def download_file(self, source: str, destination: Union[Path, BinaryIO]) -> Path:
        """Stream ``@microsoft.graph.downloadUrl`` into a path or stream without buffering the file (AC6)."""
        # FILL IN: rule in Implementation Notes; public-boundary try/map as in list_files
```
**Why this shape**: `_create_session` is written out because `idempotent=False` and the configurable conflict body are
exactly the S5 / AC5 fixes over the existing client helper; `_put_session` fixes the URL-boundary preamble (S6) and the
final error message (spec §7) so no task can leak the upload URL.

### `packages/ai-parrot/tests/interfaces/test_graph_filemanager.py` (MODIFY)
```python
# AFTER — append at end of file
from ._graph_fakes import FakeAiohttpSession


@pytest.fixture
def xfer_manager():
    # FILL IN: empty FakeDrive; probe (client_class=SharepointClient) adopting make_sharepoint_client; a
    #          FakeAiohttpSession installed with m._http_session = lambda: session; small_file_threshold=16, chunk_size=8;
    #          return (m, fake, session)


async def test_upload_small_uses_content_put(xfer_manager):
    # FILL IN: 10 bytes -> "content_put" call, no upload requests


async def test_upload_large_uses_session_chunks(xfer_manager):
    # FILL IN: 20 bytes -> create_upload_session + 3 PUTs with Content-Range 0-7/20, 8-15/20, 16-19/20


async def test_upload_conflict_behavior_replace_fail_rename(xfer_manager):
    # FILL IN: fail/rename route through the session with the body value recorded by the fake, even for small files


async def test_outbound_calls_have_no_auth_header_and_no_redirects(xfer_manager):
    # FILL IN: every session.requests entry: no "Authorization" header, allow_redirects is False


async def test_upload_session_rejects_foreign_upload_url(xfer_manager):
    # FILL IN: fake returns https://evil.example/... -> GraphFileManagerError, no PUT issued


async def test_create_file_and_upload_file_from_bytes(xfer_manager):
    # FILL IN: create_file -> True; upload_file_from_bytes -> web_url string


async def test_download_streams_to_path_and_binaryio(xfer_manager, tmp_path):
    # FILL IN: Path destination (parent created) returns that Path; BytesIO destination returns Path(source)


async def test_download_folder_raises_isadirectory(xfer_manager):
    # FILL IN
```

### FILL IN checklist
- [ ] `_ensure_parent`; chunk loop in `_put_session`
- [ ] `upload_file` size/reader/routing; `download_file`
- [ ] test bodies

---

## Acceptance Criteria

- [ ] Uploads route by `small_file_threshold` with `replace`; `fail`/`rename` always use the session and the body
      carries the behaviour (spec AC5 + task-time decision above).
- [ ] Upload-session and download URLs are validated before use, requested with no `Authorization` header and
      `allow_redirects=False`, and never logged (spec AC21).
- [ ] `download_file` streams in chunks to a `Path` or stream; returns `Path(destination)` / `Path(source)` (spec AC6).
- [ ] `upload_file_from_bytes` returns the `web_url` (spec AC9); `create_file` returns `True`.
- [ ] `ruff check` clean.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/interfaces/test_graph_filemanager.py -q`

---

## Test Specification

| Test | Asserts |
|---|---|
| `test_upload_small_uses_content_put` / `test_upload_large_uses_session_chunks` | AC5 routing, Content-Range |
| `test_upload_conflict_behavior_replace_fail_rename` | AC5 conflict behaviour |
| `test_outbound_calls_have_no_auth_header_and_no_redirects` / `test_upload_session_rejects_foreign_upload_url` | AC21 |
| `test_create_file_and_upload_file_from_bytes` | AC9 |
| `test_download_streams_to_path_and_binaryio` / `test_download_folder_raises_isadirectory` | AC6 |

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** `sdd/specs/sharepoint-filemanager.spec.md` (§2, the §3 module named in Context, §6, §7).
2. **Check dependencies** — every `Depends-on` task must be `done` in `sdd/tasks/index/sharepoint-filemanager.json`.
3. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still resolves (`grep` or `read` the source).
   - Re-run the `grep -c` of every MODIFY anchor in the blueprint; a changed count means the anchor moved —
     re-locate it; a count of `0` means STOP and report drift.
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists.
4. **Update status** in `sdd/tasks/index/sharepoint-filemanager.json` → `"in-progress"`.
5. **Implement** — start from the Implementation Blueprint blocks, complete every `# FILL IN:` marker, and never
   change a signature, class name or file path the blueprint fixes.
6. **Verify** every acceptance criterion and run every Validation Command (plus `ruff check` on touched files).
7. **Move this file** to `sdd/tasks/completed/`.
8. **Update the index** → `"done"`.
9. **Fill in the Completion Note** below.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
