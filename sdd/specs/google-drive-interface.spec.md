---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
# projects: parts of the codebase this doc concerns. Use `packages/*` dir names
#   (ai-parrot, ai-parrot-server, parrot-formdesigner, …) or an area
#   (sdd-tooling, dev-loop, admin-ui, docs, ci). Unknown values warn, not fail.
projects: [ai-parrot, ai-parrot-tools]
# tags: free-form kebab-case keywords for organizing specs (e.g. memory, mcp).
tags: [filemanager, google-drive, google-workspace, aiogoogle, storage, toolkit]
---

# Feature Specification: Google Drive FileManager

**Feature ID**: FEAT-608
**Date**: 2026-09-26
**Author**: Jesus Lara (with Claude)
**Status**: draft
**Target version**: 1.1.0 (next minor after 1.0.6)
**Proposal**: `sdd/proposals/google-drive-interface.proposal.md` (accepted; research audit at `sdd/state/FEAT-608/`)
**Precedent**: FEAT-603 `sdd/specs/sharepoint-filemanager.spec.md` (merged to `dev` in PR #1501)

---

## 1. Motivation & Business Requirements

> Why does this feature exist? What problem does it solve?

### Problem Statement

AI-Parrot's uniform storage contract — `FileManagerInterface` from `navigator.utils.file`
(navigator-api 4.0.0), implemented by `LocalFileManager`, `TempFileManager`, `S3FileManager`,
`GCSFileManager` and, since FEAT-603, the parrot-native `SharePointFileManager` /
`OneDriveFileManager` — has **no Google Drive backend**. Nothing Drive-related exists in the
repo: the only Google plumbing is `GoogleClient` (`parrot/interfaces/google.py`), an
aiogoogle discovery client with service-account and OAuth-user authentication whose
`get_drive_client()` still returns a bare `{"service": "drive", "version": "v3"}` config
dict, and `GoogleBaseTool` (`parrot_tools/google/base.py`), which no Drive tool subclasses.
Google Cloud Storage is covered upstream (`GCSFileManager`, `manager_type="gcs"`) but it is a
bucket/blob model over a synchronous SDK and cannot serve Drive.

Consequences:

1. Nothing that speaks `FileManagerInterface` (`FileManagerTool`, `FileManagerToolkit`,
   `ReportPersistenceMixin`, artifact stores) can read from or write to a Google Drive folder
   or shared drive; agents that must deliver reports to Drive need bespoke code.
2. There is no agent-facing Drive toolkit at all (the Google tools that exist cover Search,
   Places, Routes, Calendar and Lyria).
3. `GoogleClient.execute_api_call` re-runs discovery and opens a fresh `Aiogoogle` session on
   every call — acceptable for a calendar insert, prohibitive for paginated listings, chunked
   uploads and batches.

**Who is affected**: agent authors (want `FileManagerToolkit(manager_type="gdrive")` and a
`GoogleDriveToolkit`), report/artifact persistence users (bytes-in-memory to Drive), and
Google Workspace tenants that standardise on Drive rather than SharePoint.

**Why now**: FEAT-603 fixed the manager façade, the registration seams, the batch models and
the test-harness pattern; Drive is the same shape with a different transport, and the
proposal's Q&A already settled every parameter choice.

### Goals

- G1. Implement `FileManagerInterface` for Google Drive v3 in a single concrete
  `GoogleDriveFileManager` (`parrot/interfaces/file/gdrive.py`) with the same extension
  surface as `GraphDriveFileManager`: `list_entries`, `find_entries`, server-side
  `find_files`, `upload_file_from_bytes`, `create_sharing_link`, `upload_files` /
  `download_files` returning `BatchItemResult`, `setup(app, route)` HTTP serving with the
  413 guard. Paths are drive-relative, `prefix + key`, exactly like S3 (proposal U2).
- G2. Compose the **existing** `GoogleClient` for authentication (`service_account`, `user`,
  `cached`, branch-for-branch as `GoogleBaseTool._get_client`) — no second Google auth stack —
  and promote `GoogleClient.get_drive_client()` into a live `DriveClient` wrapper that holds
  one `Aiogoogle` session + one discovered `drive` v3 API per manager (proposal U5).
- G3. Targets: the principal's My Drive by default, plus an optional shared drive
  (`shared_drive_id`, `supportsAllDrives=True` / `includeItemsFromAllDrives=True` on every
  call). Domain-wide delegation is out of scope (proposal U1).
- G4. Path model over an id-addressed store: a segment-walk resolver with a per-manager
  path→id cache, deterministic first match (`orderBy="modifiedTime desc"`, then `id`), and an
  upload `conflict_behavior` of `replace` (default) | `fail` | `rename` (proposal U2).
- G5. `get_file_url(path, expiry)` returns the item's `webViewLink` **without changing
  permissions**; explicit sharing is the extension `create_sharing_link(path, *, scope, role,
  expiry, email_address)` over `permissions.create` (proposal U3).
- G6. Register the manager everywhere a file manager is discoverable: both lazy shims,
  `FileManagerFactory._PARROT_NATIVE["gdrive"]`, the `ManagerType` literal and both
  `_DRIVE_RELATIVE_BACKENDS` sets; `FileManagerToolkit(manager_type="gdrive")` works with the
  existing `find` / `batch_upload` / `batch_download` ops unchanged.
- G7. Ship a net-new `GoogleDriveToolkit(AbstractToolkit)` under `parrot_tools.google`
  (list / search / download / upload / share / link) delegating to the manager, in the
  `GoogleCalendarToolkit` mould (proposal U4). Workspace `files.export` is out of scope.
- G8. Packaging + docs: a dedicated `ai-parrot[gdrive]` extra included in `all`;
  `docs/interfaces/gdrive-filemanager.md` and `docs/integrations/google-oauth2.md`.
- G9. Verification: fake-aiogoogle unit tests in CI (no network, no real `GoogleClient`
  construction), an opt-in `@pytest.mark.live` suite gated on environment variables, and the
  FEAT-603 cross-cutting guards (interface-signature parity, no SDK leak on shim import,
  TID251, signature snapshot of touched public classes).

### Non-Goals (explicitly out of scope)

- No domain-wide delegation (`subject=`) in v1 — aiogoogle's `ServiceAccountCreds` supports
  it (`aiogoogle/auth/creds.py:259`), so it is a future constructor kwarg, not a design change.
- No Workspace export (`files.export` of Docs/Sheets/Slides); a native Workspace file is
  listed (size 0, `content_type` = its `application/vnd.google-apps.*` MIME) but
  `download_file` on it raises `GoogleDriveFileManagerError` naming the export follow-up.
- No changes to `GoogleClient` authentication paths (`initialize`, `interactive_login`,
  Redis/file caches), to `GoogleBaseTool`, or to the existing Search/Places/Routes/Calendar/
  Lyria tools. The only edit to `google.py` is the additive `DriveClient` class and the
  `get_drive_client()` promotion (its dict return has no callers — proposal F006).
- No behaviour change to `GraphDriveFileManager`, `SharePointFileManager`,
  `OneDriveFileManager` or the O365 tools; the only edit to `graph.py` is a behaviour-neutral
  relocation of `DriveEntry` / the guarded serving extension into a Graph-free module (M5),
  re-exported under their old names.
- No shared batch engine: `_run_batch` is re-implemented in `gdrive.py` with the AC8 contract
  (≈70 lines); extracting a common `BatchRunnerMixin` is a follow-up (§8 Q3), not part of
  this feature.
- No Drive **loader** for RAG (`parrot_loaders`) and no changes to `GCSFileManager`
  (`manager_type="gcs"` stays the Cloud Storage backend).
- No E2E gate (`parrot e2e`) surface — the frontmatter `e2e` key is omitted.
- The `aiogoogle==5.17.0` pins inside the `agents` bundles (`pyproject.toml:432, 483, 518`)
  are not touched; the new extra declares its own range.

---

## 2. Architectural Design

### Overview

Google Drive addresses every item by **id**; folders are files with MIME
`application/vnd.google-apps.folder`; sibling names are not unique; a shared drive is a
second root addressed by `driveId`. The design maps navigator's path-based contract onto that
model in one class and keeps every Google concern behind one wrapper:

- **`DriveClient`** (`parrot/interfaces/google.py`, new, additive) — promoted from the config
  dict `get_drive_client()` used to return, exactly as FEAT-453 promoted `CalendarClient`
  (`google.py:160-224`). Unlike `CalendarClient` it owns a **long-lived** `Aiogoogle` session
  (`aiogoogle/client.py:27, 60`) and one discovered `drive` v3 API (`client.py:157`) for the
  life of the manager, dispatching every call through `as_service_account` or `as_user`
  (`client.py:278, 223`) according to `GoogleClient.using_service_account()`
  (`google.py:642`). It exposes typed coroutines for `files.list/get/create/update/copy/delete`,
  `permissions.create`, media download, and `send_raw(Request, *, full_res, raise_for_status)`
  for the resumable-upload session (`aiogoogle.models.Request`, `models.py:141-195`).
- **`GoogleDriveFileManager(FileManagerInterface)`** (`parrot/interfaces/file/gdrive.py`, new)
  — a **sibling** of `GraphDriveFileManager`, not a subclass (that base is msgraph-specific end
  to end: `graph.py:33-46, :53`). It shares only the backend-neutral `batch.py` models
  (`BatchItemResult`, `BatchSummary`, `BatchErrorCode` — `batch.py:14-71`) and the relocated
  `DriveEntry` / `GuardedFileServingExtension` (M5). Two protected hooks mirror FEAT-603's
  shape for future subclasses (`_build_client()`, `_resolve_root_id()`), but v1 ships one
  concrete class.
- **Root and targets (U1)**: `root_id` (a folder id) or `root_path` (a path walked from the
  drive root) scope the manager; `shared_drive_id` switches the root to that drive and adds
  `corpora="drive"`, `driveId`, `supportsAllDrives=True`, `includeItemsFromAllDrives=True` to
  every `files.list`, and `supportsAllDrives=True` to every other `files.*` /
  `permissions.*` call. Without a shared drive the root alias is `"root"` (My Drive).
- **Path model (U2)**: `_prefixed` / `_unprefixed` as S3 (`gcs.py:120-128`); `_resolve(path)`
  walks segments with `files.list(q="'<parent>' in parents and name = '<escaped>' and
  trashed = false", orderBy="modifiedTime desc", pageSize=2)` and caches `path → (id,
  is_folder)` per manager (`_path_cache`, invalidated on every write to that path or its
  parents). Names are escaped for the `q` grammar (`\` → `\\`, `'` → `\'`). `..` segments
  raise `ValueError`. Duplicate siblings resolve to the newest by `modifiedTime`, then the
  lexicographically smallest `id` when the timestamps tie (deterministic, documented).
- **Uploads**: below `SMALL_FILE_THRESHOLD` (5 MiB, Google's resumable recommendation) →
  multipart `files.create` / `files.update` through aiogoogle's `upload_file` (Path) or
  `pipe_from` (async iterator over a `BinaryIO`) with `upload_file_content_type`
  (`aiogoogle/resource.py:394-397, 563-601`; `sessions/aiohttp_session.py:123-153`). At or
  above → a **resumable session** that `gdrive.py` drives itself because aiogoogle only builds
  the `ResumableUpload` object and never speaks the protocol (`resource.py:654-690`;
  `sessions/` has no resumable code): `POST …/upload/drive/v3/files?uploadType=resumable`
  (or `PATCH …/files/{id}` for `replace`) via `DriveClient.send_raw(full_res=True)` →
  `Location`; then `CHUNK_SIZE` (8 MiB, a multiple of 256 KiB) PUTs with `Content-Range`
  through `send_raw(raise_for_status=False)`, treating 308 as "resume incomplete" and reading
  the returned `Range` header to continue; 5xx/429 chunks retry under the single policy.
  The session URL is validated by `_validate_upload_url` (https, host in `ALLOWED_HOSTS` =
  `www.googleapis.com`), never logged, never sent a second `Authorization` header (aiogoogle
  authorises the `Request`).
- **Conflicts (U2)**: `replace` (default) updates the existing item in place (same id, new
  revision — S3 overwrite parity); `fail` → `FileExistsError`; `rename` → `name (n).ext` with
  the first free `n`.
- **Downloads**: `files.get(fileId, alt="media", supportsAllDrives=True)` with
  `download_file=str(path)` for a `Path` or `pipe_to=_AsyncSink(binary_io)` for a `BinaryIO`
  (aiogoogle awaits `pipe_to.write(chunk)`, `aiohttp_session.py:74-76`); returns `Path(source)`
  for `BinaryIO` destinations as S3 does. Native Workspace MIME → `GoogleDriveFileManagerError`.
- **Deletes**: `delete_file` trashes (`files.update(trashed=True)`) — recycle-bin parity with
  FEAT-603; `permanent_delete=True` (constructor) switches to `files.delete`. Missing → `False`.
- **Copy / rename / move**: `files.copy(fileId, json={"name", "parents"})` is synchronous;
  `rename_file` / `rename_folder` use `files.update(name=…, addParents=…, removeParents=…)`.
- **Sharing (U3)**: `get_file_url(path, expiry=3600)` keeps the exact interface signature
  (`abstract.py:67`) and returns `webViewLink` — `expiry` is accepted and ignored with a
  debug log; **no permission is created**. `create_sharing_link(path, *, scope="user",
  role="reader", email_address=None, domain=None, expiry=0)` creates a permission
  (`type=scope`; `emailAddress` required for `user`/`group`, `domain` for `domain`;
  `expirationTime` only for `user`/`group` — Drive rejects it elsewhere) with
  `sendNotificationEmail=False` and returns `webViewLink`; a policy-forbidden `anyone` →
  `PermissionError`.
- **Listing semantics**: `list_files` = files only (`FileMetadata` has no folder flag), all
  pages via `nextPageToken`; `list_entries` includes folders (`DriveEntry.is_folder`);
  `find_entries` / `find_files` use server-side `q` (`name contains '<kw>'`, `fileExtension`
  is applied client-side; `prefix` resolves to a parent id and the walk is recursive), all
  pages, `max_results` only after filtering (AC20 parity).
- **Authentication (AC3 parity)**: `connect()` reproduces `GoogleBaseTool._get_client`
  branch-for-branch (`base.py:110-135`): `service_account` → `initialize()`; `user` →
  `interactive_login(**interactive_login_kwargs)` + `initialize()`; `cached` → `initialize()`
  and, only on the `"User credentials not available"` `RuntimeError`, `interactive_login` +
  `initialize()`. One credential load per manager. `adopt_client(client)` accepts an
  already-initialised `GoogleClient` (what `GoogleBaseTool._get_client` returns) and never
  closes it. `GoogleClient` is constructed **only inside `connect()`** because
  `parrot.interfaces.google` imports selenium / playwright / webdriver_manager / redis at
  module import (`google.py:23-31`) and its constructor eagerly builds an `aioredis` client
  (`google.py:299-302`).
- **Retry policy**: one bounded `_retrying(op, *, label, idempotent)` policy for aiogoogle
  calls and resumable PUTs — retryable `{429, 500, 502, 503, 504}`, `Retry-After` honoured and
  capped at 60 s, exponential backoff otherwise, `max_retries=3`; non-idempotent requests
  (session creation POST, `files.copy`, `permissions.create`) are never retried. Status codes
  are read from `aiogoogle.excs.HTTPError.res.status_code` (`excs.py:22-25`).
- **Registration**: `parrot.interfaces.file.__init__` / `parrot_tools.file.__init__` gain
  `GoogleDriveFileManager` as lazy names (`file/__init__.py:37-43`,
  `parrot_tools/file/__init__.py:22-24`); `FileManagerFactory._PARROT_NATIVE["gdrive"]`,
  `ManagerType` and both `_DRIVE_RELATIVE_BACKENDS` sets widen (`filemanager.py:28, 49-51,
  259, 864`). The toolkit's `find` / `batch_*` ops need no change: they already dispatch on
  `hasattr(self.manager, "upload_files")` (`filemanager.py:598, 665, 1312`).
- **Agent surface (U4)**: `FileManagerToolkit(manager_type="gdrive", root_id=…,
  shared_drive_id=…, credentials=…, auth_mode=…)` plus `GoogleDriveToolkit` with
  `tool_prefix="gdrive"` exposing `gdrive_list_files`, `gdrive_search_files`,
  `gdrive_download_file`, `gdrive_upload_file`, `gdrive_share_file`, `gdrive_get_file_link`.
- **Decided defaults**: `manager_name="gdrivefile"` (S3's `"s3file"` convention);
  `SMALL_FILE_THRESHOLD=5 MiB`; `CHUNK_SIZE=8 MiB`; `MAX_CONCURRENCY=5`; `MAX_RETRIES=3`;
  `SERVING_MAX_BYTES=64 MiB`; default scopes `"drive"` (`DEFAULT_SCOPES["drive"]`,
  `google.py:42-47`); `list_files` `pageSize=1000`; `fields` fixed to
  `id,name,mimeType,size,modifiedTime,webViewLink,webContentLink,parents,trashed`.

### Component Diagram

```
FileManagerToolkit / FileManagerTool                GoogleDriveToolkit (parrot_tools.google.drive)
 (manager_type="gdrive", fs_* incl. find/batch_*)    gdrive_list/search/download/upload/share/get_link
        │ FileManagerFactory.create("gdrive")                 │ builds or receives the manager
        ▼                                                     ▼
 ┌──────────────────────────────────────────────────────────────────────────────┐
 │ GoogleDriveFileManager(FileManagerInterface)   parrot/interfaces/file/gdrive.py│
 │  list/upload/download/copy/delete/exists/metadata/create · folders + rename    │
 │  list_entries · find_entries/find_files (q=) · upload_file_from_bytes          │
 │  get_file_url (webViewLink) · create_sharing_link (permissions.create)         │
 │  upload_files/download_files → BatchItemResult · setup()/handle_file (413)     │
 │  path resolver + cache · conflict_behavior · resumable session (raw Request)   │
 │  hooks: _build_client() · _resolve_root_id()                                   │
 └───────────────┬──────────────────────────────────────────────┬───────────────┘
                 │ connect()/adopt_client()                       │ models
          GoogleClient (parrot/interfaces/google.py)      batch.py · entries.py (M5)
           initialize / interactive_login / caches          BatchItemResult · DriveEntry
                 │ get_drive_client()  → DriveClient (NEW)        GuardedFileServingExtension
                 ▼
          DriveClient: one Aiogoogle session + discovered drive v3
           files.* · permissions.create · media up/download · send_raw(Request)
                 │
          aiogoogle 5.19 (aiohttp transport, aiofiles chunking, token refresh)
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `navigator.utils.file.FileManagerInterface` / `FileMetadata` | extends | all 9 abstract methods + 4 folder/rename hooks + `find_files` override (`abstract.py:36-296`) |
| `navigator.utils.file.web.FileServingExtension` | uses | via the relocated `GuardedFileServingExtension` (M5); `FileServingExtension(manager, route, manager_name)` (`web.py:28, 48-60`) |
| `parrot.interfaces.google.GoogleClient` | modifies (additive) | new `DriveClient` class; `get_drive_client()` returns it; new `aiogoogle_credentials()` helper exposing the creds objects `DriveClient` needs |
| `parrot_tools.google.base.GoogleBaseTool._get_client` | mirrors | auth branch table copied into `connect()` (`base.py:110-135`); a tool can pass its client to `adopt_client` |
| `parrot.interfaces.file.graph` | modifies (neutral) | `DriveEntry` and `_GuardedFileServingExtension` move to `entries.py`; `graph.py` re-imports them under the same names |
| `parrot.interfaces.file.batch` | uses (unchanged) | `BatchItemResult`, `BatchSummary`, `BatchErrorCode` |
| `parrot.interfaces.file` shim / `parrot_tools.file` shim | modifies | lazy `GoogleDriveFileManager` (no aiogoogle / selenium / redis at import) |
| `parrot.tools.filemanager.FileManagerFactory` / `FileManagerTool` / `FileManagerToolkit` | modifies | `ManagerType` + `_PARROT_NATIVE["gdrive"]` + both `_DRIVE_RELATIVE_BACKENDS` + docstrings; ops untouched |
| `parrot_tools.google.__init__` | modifies | exports `GoogleDriveToolkit` |
| `parrot.conf` | uses | `GOOGLE_CREDENTIALS_FILE` (`conf.py:434-436`) through `GoogleClient`'s default credential resolution |
| `packages/ai-parrot/pyproject.toml` | modifies | new `gdrive` extra; added to `all` |
| `packages/ai-parrot/tests/interfaces/test_file_shim.py` | modifies | leak / lazy / parity / factory tests extended for `gdrive` |
| `packages/ai-parrot/tests/tools/test_filemanager_batch_ops.py` | modifies | `_storage_path` drive-relative test covers `"gdrive"` |
| FEAT-603 suites (`test_graph_filemanager.py`, `test_sharepoint_filemanager.py`, `test_onedrive_filemanager.py`, `test_graph_fakes.py`) | depends on | must stay green after the M5 relocation |

### Data Models

```python
# parrot/interfaces/file/entries.py  (new, M5 — Graph-free; moved verbatim from graph.py:73-118)
class DriveEntry(BaseModel):          # unchanged fields: id, name, path, is_folder, size, modified_at, web_url, content_type
class GuardedFileServingExtension(FileServingExtension):   # was graph.py:73 `_GuardedFileServingExtension`
    def __init__(self, *args: Any, max_bytes: int, **kwargs: Any) -> None: ...
    async def handle_file(self, request: web.Request) -> web.StreamResponse: ...   # 413 above max_bytes

# parrot/interfaces/file/gdrive.py  (new)
from parrot.interfaces.file.batch import BatchErrorCode, BatchItemResult, BatchState, BatchSummary   # verified: batch.py:14-71
GoogleAuthModeLiteral = Literal["service_account", "user", "cached"]    # same strings as GoogleAuthMode (base.py:18-20)
ConflictBehavior = Literal["replace", "fail", "rename"]
ShareScope = Literal["user", "group", "domain", "anyone"]               # Drive permission `type`
ShareRole = Literal["reader", "commenter", "writer"]                    # Drive permission `role`
FOLDER_MIME = "application/vnd.google-apps.folder"
WORKSPACE_MIME_PREFIX = "application/vnd.google-apps."

class GoogleDriveFileManagerError(RuntimeError):
    """Base error; carries ``status_code`` when known (mirrors GraphFileManagerError, graph.py:128-140)."""
    def __init__(self, message: str, *, status_code: Optional[int] = None) -> None: ...

class _AsyncSink:
    """Adapter giving a sync ``BinaryIO`` the ``await sink.write(chunk)`` contract aiogoogle's ``pipe_to`` expects."""
    def __init__(self, target: BinaryIO) -> None: ...
    async def write(self, chunk: bytes) -> None: ...
```

### New Public Interfaces

```python
from parrot.interfaces.file import GoogleDriveFileManager                 # lazy — no aiogoogle/selenium/redis at package load
from parrot.interfaces.file.gdrive import GoogleDriveFileManager, GoogleDriveFileManagerError
from parrot.interfaces.google import GoogleClient, DriveClient
from parrot_tools.google import GoogleDriveToolkit

gd = GoogleDriveFileManager(root_path="Reports/2026", prefix="q3/", credentials="env/google/key.json")        # service account
sd = GoogleDriveFileManager(shared_drive_id="0AB…", root_path="Finance", auth_mode="cached")                 # shared drive, cached OAuth user
me = GoogleDriveFileManager(root_id="1xYz…", auth_mode="user", interactive_login_kwargs={"port": 5050})

await gd.connect()                                          # one credential load; resolves root id
await gd.list_files("", "*.xlsx")                           # List[FileMetadata], files only, all pages
await gd.list_entries("")                                   # List[DriveEntry] incl. folders
await gd.upload_file(Path("q3.xlsx"), "q3.xlsx")             # multipart < 5 MiB, resumable session otherwise
await gd.upload_file_from_bytes(data, "q3.pdf", "application/pdf")   # str (webViewLink)
await gd.download_file("q3.xlsx", Path("/tmp/q3.xlsx"))     # streamed via aiogoogle download_file
await gd.get_file_url("q3.xlsx")                            # webViewLink; no permission change
await gd.create_sharing_link("q3.xlsx", scope="user", role="reader", email_address="a@b.com", expiry=3600)
await gd.find_files(keywords="q3", extension=".xlsx", prefix="")
await gd.upload_files([(Path("a.csv"), "in/a.csv"), (b"...", "in/b.bin")])    # List[BatchItemResult]
gd.setup(app, route="/gdrive")                              # GET /gdrive/<path>; 413 above serving_max_bytes
await gd.close()

FileManagerFactory.create("gdrive", root_path="Reports", credentials={...})
FileManagerToolkit(manager_type="gdrive", shared_drive_id="0AB…", auth_mode="service_account")   # fs_* tools incl. fs_find_files / fs_batch_*
GoogleDriveToolkit(root_path="Reports", credentials="env/google/key.json")                       # gdrive_* tools
GoogleDriveToolkit(google_client=client)                                                         # reuse an authenticated GoogleClient
```

---

## 3. Module Breakdown

> Define the discrete modules that will be implemented.
> These directly map to Task Artifacts in Phase 2.

#### Delegation-eligible modules

| Module | Eligible? | Decided patterns / exact contracts | Why not (if no) |
|---|---|---|---|
| M0: Drive test harness | yes | file layout, public names, fake behaviours fixed below | — |
| M1: `DriveClient` in `google.py` | yes | method list, dispatch rule, `send_raw` contract, `get_drive_client()` promotion fixed | — |
| M2: `gdrive.py` core (models, path resolver, lifecycle, retry) | yes | constructor, cache rule, escaping, error mapping, auth branch table fixed | — |
| M3: read ops | yes | `q` strings, `fields`, pagination, `_AsyncSink` contract fixed | — |
| M4: write ops (uploads, resumable, conflicts, copy/delete/rename, sharing, batch, serving) | yes | endpoints, thresholds, 308 handling, conflict policy, permission body, AC8 batch contract fixed | — |
| M5: `entries.py` relocation | yes | verbatim move + re-export; FEAT-603 tests are the gate | — |
| M6: registration (shims + factory + literals + tests) | yes | exact edit sites in §6 | — |
| M7: `GoogleDriveToolkit` | yes | constructor, tool names, response dict keys fixed | — |
| M8: packaging + docs | yes | extra name `gdrive`, pins, doc sections named | — |
| M9: live gate suite | yes | env knobs and skip rule fixed | — |
| M10: feature guards | yes | guard list fixed (parity, leak, TID251, signature snapshot) | — |

### Module 0: Drive test harness
- **Path**: `packages/ai-parrot/tests/interfaces/_gdrive_fakes.py` (new)
- **Responsibility**: in-memory Google Drive plus a fake `DriveClient` that the manager drives
  through the same coroutine names as the real one (M1), so M2–M4, M6, M7 and M10 tests never
  construct a real `GoogleClient` (its constructor needs Redis + credentials,
  `google.py:299-302, 412-420`). Mirrors `_graph_fakes.py` (`FakeGraphClient.fail_next`,
  `_bare`, `make_sharepoint_client` — `_graph_fakes.py:178, 207, 620, 644`).
- **Depends on**: nothing in this spec (M1's `DriveClient` is faked, not imported)
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot/tests/interfaces/_gdrive_fakes.py  (new)
  class FakeHTTPError(Exception):
      """Mimics aiogoogle.excs.HTTPError: ``res.status_code`` and ``res.headers`` (excs.py:22-25)."""
      def __init__(self, status: int, *, retry_after: Optional[float] = None, message: str = "") -> None: ...

  class FakeDriveFile:
      """id, name, mimeType, size, modifiedTime, parents, trashed, webViewLink, webContentLink, content: bytes."""

  class FakeDrive:
      """In-memory Drive keyed by id; ``root_id`` is ``"root"`` for My Drive or the shared drive id.
      Records every API call as ``(resource, method, params)`` in ``calls``."""
      def __init__(self, *, drive_id: Optional[str] = None) -> None: ...
      def put_folder(self, path: str) -> FakeDriveFile: ...
      def put_file(self, path: str, data: bytes, *, mime: str = "application/octet-stream", modified: Optional[datetime] = None) -> FakeDriveFile: ...
      def duplicate(self, path: str, data: bytes, *, modified: datetime) -> FakeDriveFile:
          """Add a same-name sibling (duplicate-name tests)."""

  class FakeDriveClient:
      """Stand-in for parrot.interfaces.google.DriveClient with the same coroutine names (M1) over FakeDrive.
      ``files_list`` honours q (parents / name / name contains / mimeType / trashed), order_by, page_size and page_token
      (``page_size`` pages so pagination tests script 3 pages); ``send_raw`` scripts the resumable session
      (POST → Location, PUT chunks → 308 with Range, final 200) and records every request."""
      def __init__(self, drive: FakeDrive, *, page_size: int = 2, service_account: bool = True) -> None: ...
      def fail_next(self, status: int, *, retry_after: Optional[float] = None, times: int = 1, method: Optional[str] = None) -> None: ...

  def make_google_client(fake: FakeDriveClient, *, auth_type: str = "service_account") -> GoogleClient:
      """A real GoogleClient built without ``__init__`` (``_bare`` pattern, _graph_fakes.py:620): ``_authenticated=True``,
      ``auth_type`` set, ``get_drive_client`` returning ``fake``, ``close`` recording the call."""

  def make_manager(fake: FakeDriveClient, **kwargs: Any) -> "GoogleDriveFileManager":
      """GoogleDriveFileManager(**kwargs) with ``adopt_client(make_google_client(fake))`` applied."""
  ```

### Module 1: `DriveClient` and the `get_drive_client()` promotion
- **Path**: `packages/ai-parrot/src/parrot/interfaces/google.py` (modifies)
- **Responsibility**: one long-lived `Aiogoogle` session + one discovered `drive` v3 API per
  manager; typed coroutines for the Drive calls the manager makes; `send_raw` for the
  resumable protocol; dispatch through `as_service_account` / `as_user` by
  `GoogleClient.using_service_account()`. `get_drive_client()` returns it (hard cut of the
  config-dict return; no callers). Adds the read-only helper `aiogoogle_credentials()` so
  `DriveClient` never touches `_service_account_creds` / `_user_creds` directly.
- **Depends on**: nothing in this spec
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot/src/parrot/interfaces/google.py  (modifies google.py:160 [CalendarClient precedent], :771-773, :642-648)
  from aiogoogle import Aiogoogle                                        # verified: google.py:29
  from aiogoogle.models import Request                                   # verified: aiogoogle/models.py:141

  class DriveClient:
      """A live Google Drive v3 client over one ``Aiogoogle`` session (FEAT-608).

      Unlike ``CalendarClient`` (google.py:160) it keeps the session and the discovered API open between calls:
      ``open()`` once, then every method is one authorised request; ``close()`` releases the session.
      """
      def __init__(self, google_client: "GoogleClient", version: str = "v3", *, supports_all_drives: bool = True) -> None: ...
      async def open(self) -> "DriveClient":
          """``Aiogoogle(**google_client.aiogoogle_credentials())`` + ``discover("drive", version)``; idempotent."""
      async def close(self) -> None: ...
      async def __aenter__(self) -> "DriveClient": ...
      async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None: ...
      @property
      def api(self) -> Any:
          """The discovered GoogleAPI (raises RuntimeError before ``open()``)."""
      async def execute(self, request: Any, *, full_res: bool = False, raise_for_status: bool = True) -> Any:
          """``as_service_account`` when ``google_client.using_service_account()`` else ``as_user`` (client.py:278, 223)."""
      async def send_raw(self, request: Request, *, full_res: bool = True, raise_for_status: bool = True) -> Any:
          """Authorise and send a hand-built ``aiogoogle.models.Request`` (resumable-upload session and chunk PUTs)."""
      # Typed wrappers — each builds ``self.api.files.<m>(**params)`` / ``self.api.permissions.create(...)`` and calls ``execute``.
      async def files_list(self, *, q: str, fields: str, page_size: int = 1000, page_token: Optional[str] = None,
                           order_by: Optional[str] = None, drive_id: Optional[str] = None) -> Dict[str, Any]: ...
      async def files_get(self, file_id: str, *, fields: str) -> Dict[str, Any]: ...
      async def files_create(self, metadata: Dict[str, Any], *, fields: str, upload_file: Optional[str] = None,
                             pipe_from: Any = None, content_type: Optional[str] = None) -> Dict[str, Any]: ...
      async def files_update(self, file_id: str, metadata: Optional[Dict[str, Any]] = None, *, fields: str,
                             add_parents: Optional[str] = None, remove_parents: Optional[str] = None,
                             upload_file: Optional[str] = None, pipe_from: Any = None, content_type: Optional[str] = None) -> Dict[str, Any]: ...
      async def files_copy(self, file_id: str, metadata: Dict[str, Any], *, fields: str) -> Dict[str, Any]: ...
      async def files_delete(self, file_id: str) -> None: ...
      async def files_download(self, file_id: str, *, download_file: Optional[str] = None, pipe_to: Any = None) -> None:
          """``files.get(fileId, alt="media", download_file=… | pipe_to=…)`` (resource.py:563-587)."""
      async def permissions_create(self, file_id: str, body: Dict[str, Any], *, send_notification_email: bool = False) -> Dict[str, Any]: ...

  class GoogleClient(CredentialsInterface, ABC):                         # existing, google.py:226
      def aiogoogle_credentials(self) -> Dict[str, Any]:                 # NEW, additive
          """``{"service_account_creds": …, "user_creds": …}`` for ``Aiogoogle(...)``; raises RuntimeError when not initialised."""
      async def get_drive_client(self, version: str = "v3") -> "DriveClient":   # PROMOTED (was Dict[str, Any], google.py:771-773)
          """Return a not-yet-opened DriveClient bound to this client (FEAT-453 pattern, get_calendar_client :783)."""
  ```

### Module 2: `gdrive.py` core — models, path resolver, lifecycle, retry
- **Path**: `packages/ai-parrot/src/parrot/interfaces/file/gdrive.py` (new)
- **Responsibility**: class skeleton, constructor and tunables, `connect` / `adopt_client` /
  `close` / async context manager, the auth branch table, the path model (`_prefixed`,
  `_unprefixed`, `_escape_q`, `_resolve`, `_resolve_parent`, `_path_cache` + invalidation),
  metadata mapping, the single retry policy and error mapping, `_validate_upload_url`.
- **Depends on**: M1 (`DriveClient`, `GoogleClient.get_drive_client`), M5 (`DriveEntry`,
  `GuardedFileServingExtension`), `batch.py`
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot/src/parrot/interfaces/file/gdrive.py  (new)
  from navigator.utils.file import FileManagerInterface, FileMetadata            # verified: graph.py:49; abstract.py:16, :36
  from .batch import BatchErrorCode, BatchItemResult, BatchState, BatchSummary   # verified: batch.py:14-71
  from .entries import DriveEntry, GuardedFileServingExtension                  # M5
  # NOTE: ``from parrot.interfaces.google import GoogleClient, DriveClient`` is imported INSIDE connect()/adopt_client()
  #       (TYPE_CHECKING-only at module level) — google.py loads selenium/playwright/redis (google.py:23-31).

  class GoogleDriveFileManager(FileManagerInterface):
      """FileManagerInterface over one Google Drive root (My Drive folder or shared drive).

      Paths are drive-relative and prefixed with ``prefix`` exactly like S3's ``prefix + key`` (gcs.py:120-128).
      """
      manager_name: str = "gdrivefile"
      FOLDER_MIME: str = "application/vnd.google-apps.folder"
      WORKSPACE_MIME_PREFIX: str = "application/vnd.google-apps."
      SMALL_FILE_THRESHOLD: int = 5 * 1024 * 1024
      CHUNK_SIZE: int = 8 * 1024 * 1024                    # multiple of 256 KiB (resumable requirement)
      MAX_CONCURRENCY: int = 5
      MAX_RETRIES: int = 3
      RETRYABLE_STATUS: frozenset = frozenset({429, 500, 502, 503, 504})
      SERVING_MAX_BYTES: int = 64 * 1024 * 1024
      ALLOWED_HOSTS: tuple = ("www.googleapis.com",)       # resumable session URLs
      LIST_PAGE_SIZE: int = 1000
      FIELDS: str = "id,name,mimeType,size,modifiedTime,webViewLink,webContentLink,parents,trashed"
      LIST_FIELDS: str = "nextPageToken,files(" + FIELDS + ")"

      def __init__(
          self,
          *,
          root_id: Optional[str] = None,
          root_path: str = "",
          shared_drive_id: Optional[str] = None,
          prefix: str = "",
          credentials: Optional[Union[str, Dict[str, Any], Path]] = None,
          auth_mode: GoogleAuthModeLiteral = "service_account",
          scopes: Optional[Union[str, List[str]]] = None,           # default "drive" → DEFAULT_SCOPES["drive"] (google.py:42-47)
          user_creds_cache_file: Optional[Union[str, Path]] = None,
          interactive_login_kwargs: Optional[Dict[str, Any]] = None,
          conflict_behavior: ConflictBehavior = "replace",
          permanent_delete: bool = False,
          max_concurrency: Optional[int] = None,
          max_retries: Optional[int] = None,
          chunk_size: Optional[int] = None,
          small_file_threshold: Optional[int] = None,
          serving_max_bytes: Optional[int] = None,
          **kwargs: Any,
      ) -> None:
          """Store configuration; NO network I/O and NO GoogleClient construction (graph.py:166-223 parity).
          ``root_id`` and ``root_path`` are mutually exclusive (ValueError); ``prefix`` normalises to ``"a/b/"`` or ``""``;
          ``chunk_size`` must be a multiple of 262144 (ValueError); unknown kwargs are logged and ignored."""

      # ---- hooks (subclass points; v1 ships one concrete class) ----------
      def _build_client(self) -> "GoogleClient":
          """``GoogleClient(credentials=self.credentials, scopes=self.scopes or "drive", user_creds_cache_file=…)`` (google.py:275-281)."""
      async def _resolve_root_id(self) -> str:
          """shared_drive_id → that id; root_id → verified via files.get; else "root"; then walk ``root_path`` (FileNotFoundError)."""

      # ---- lifecycle -------------------------------------------------------
      async def connect(self) -> "GoogleDriveFileManager":
          """Build + authenticate per ``auth_mode`` (GoogleBaseTool._get_client branch table, base.py:110-135), open the
          DriveClient, resolve the root id. Idempotent; one credential load per manager (AC3)."""
      def adopt_client(self, client: "GoogleClient") -> None:
          """Reuse an already-initialised GoogleClient (``is_authenticated`` must be True, google.py:637-640); ``close()``
          never closes an adopted client. The DriveClient is still opened lazily by ``_ready()``."""
      async def close(self) -> None:
          """Close the DriveClient session; ``await client.close()`` only when the manager built it; clear caches."""
      async def __aenter__(self) -> "GoogleDriveFileManager": ...
      async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None: ...
      @property
      def client(self) -> "GoogleClient": ...                # raises GoogleDriveFileManagerError before connect/adopt
      @property
      def drive(self) -> "DriveClient": ...
      @property
      def root_id(self) -> str: ...
      async def _ready(self) -> str:
          """Ensure DriveClient is open and root resolved; returns root id (graph.py:354 parity)."""

      # ---- path model & mapping --------------------------------------------
      def _prefixed(self, key: str) -> str:                   # gcs.py:120; rejects ".." segments with ValueError
      def _unprefixed(self, key: str) -> str:                 # gcs.py:124
      @staticmethod
      def _escape_q(value: str) -> str:
          """Escape for the Drive ``q`` grammar: backslash → ``\\\\``, apostrophe → ``\\'``."""
      def _list_params(self, **extra: Any) -> Dict[str, Any]:
          """``supportsAllDrives=True`` always; with ``shared_drive_id``: ``includeItemsFromAllDrives=True``, ``corpora="drive"``, ``driveId``."""
      async def _resolve(self, full_path: str, *, want_folder: Optional[bool] = None) -> Tuple[str, bool]:
          """Segment walk from ``root_id`` via ``files_list(q="'<parent>' in parents and name = '<seg>' and trashed = false",
          order_by="modifiedTime desc")``; newest wins, ties by smallest id; cached in ``_path_cache``; FileNotFoundError."""
      async def _resolve_parent(self, full_path: str, *, create: bool) -> str:
          """Parent folder id of ``full_path``; creates missing folders when ``create`` (FOLDER_MIME)."""
      def _invalidate(self, full_path: str) -> None:
          """Drop ``full_path`` and every descendant from ``_path_cache``."""
      def _make_metadata(self, item: Dict[str, Any], *, full_path: str) -> FileMetadata:
          """name, unprefixed path, int(size or 0), mimeType, modifiedTime (RFC 3339), webViewLink."""
      def _make_entry(self, item: Dict[str, Any], *, full_path: str) -> DriveEntry: ...
      def _is_folder(self, item: Dict[str, Any]) -> bool: ...
      def _is_workspace_native(self, item: Dict[str, Any]) -> bool: ...

      # ---- errors & retry ---------------------------------------------------
      @staticmethod
      def _status_code_of(error: BaseException) -> Optional[int]:
          """``error.res.status_code`` for aiogoogle HTTPError (excs.py:22-25), else status/status_code attributes."""
      @staticmethod
      def _retry_after_seconds(error: BaseException) -> Optional[float]:
          """Same semantics as graph.py:411-438 over ``error.res.headers``."""
      def _map_error(self, exc: BaseException, *, path: str) -> BaseException:
          """404 → FileNotFoundError; 401/403 → PermissionError; 409 → FileExistsError; else GoogleDriveFileManagerError(status_code)."""
      async def _retrying(self, op: Callable[[], Awaitable[Any]], *, label: str, idempotent: bool = True) -> Tuple[Any, int]:
          """graph.py:450-468 policy: RETRYABLE_STATUS, Retry-After capped 60 s, 2**(n-1) backoff, ``max_retries``; never for non-idempotent ops."""
      async def _sleep(self, seconds: float) -> None: ...      # patched in tests
      def _validate_upload_url(self, url: str) -> str:
          """https + host in ALLOWED_HOSTS or GoogleDriveFileManagerError; never logged."""
  ```

### Module 3: read operations
- **Path**: `packages/ai-parrot/src/parrot/interfaces/file/gdrive.py` (extends M2's class)
- **Responsibility**: listing, existence, metadata, search, streaming download.
- **Depends on**: M2
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot/src/parrot/interfaces/file/gdrive.py  (M3 — methods on GoogleDriveFileManager)
  async def _iter_children(self, folder_id: str) -> AsyncIterator[Dict[str, Any]]:
      """``files_list(q="'<id>' in parents and trashed = false", fields=LIST_FIELDS, page_size=LIST_PAGE_SIZE)`` following
      ``nextPageToken`` to exhaustion (AC20 parity)."""
  async def _iter_query(self, q: str, *, order_by: Optional[str] = None) -> AsyncIterator[Dict[str, Any]]: ...
  async def list_files(self, path: str = "", pattern: str = "*") -> List[FileMetadata]:
      """Non-recursive; folders excluded; fnmatch on name; all pages."""
  async def list_entries(self, path: str = "") -> List[DriveEntry]:
      """Non-recursive INCLUDING folders; all pages."""
  async def exists(self, path: str) -> bool:                # True for folders (documented, graph parity)
  async def get_file_metadata(self, path: str) -> FileMetadata:   # FileNotFoundError when missing
  async def find_entries(self, keywords: Optional[Union[str, List[str]]] = None, extension: Optional[str] = None,
                         prefix: Optional[str] = None) -> List[DriveEntry]:
      """Server-side ``name contains '<kw>'`` for the first keyword (AND of the rest client-side), recursive under ``prefix``
      (walk of folder ids, all pages); ``extension`` client-side; files only."""
  async def find_files(self, keywords=None, extension=None, prefix=None) -> List[FileMetadata]:   # abstract.py:265 override
  async def download_file(self, source: str, destination: Union[Path, BinaryIO]) -> Path:
      """``files_download(id, download_file=str(path))`` or ``pipe_to=_AsyncSink(binary_io)``; parent dirs created;
      Workspace-native MIME → GoogleDriveFileManagerError("export not supported"); returns ``Path(source)`` for BinaryIO."""
  ```

### Module 4: write operations — uploads, resumable session, conflicts, copy/delete/rename, sharing, batch, serving
- **Path**: `packages/ai-parrot/src/parrot/interfaces/file/gdrive.py` (extends M2's class)
- **Responsibility**: everything that mutates Drive, the sharing extension, the batch engine
  (AC8 contract re-implemented) and HTTP serving.
- **Depends on**: M2, M3 (`_iter_children` for `rename` conflict checks), M5 (`GuardedFileServingExtension`)
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot/src/parrot/interfaces/file/gdrive.py  (M4 — methods on GoogleDriveFileManager)
  RESUMABLE_URL: str = "https://www.googleapis.com/upload/drive/v3/files"

  async def _find_conflict(self, parent_id: str, name: str) -> Optional[Dict[str, Any]]:
      """Newest non-trashed sibling named ``name`` or None."""
  def _renamed(self, name: str, taken: set[str]) -> str:
      """``name (1).ext``, ``name (2).ext`` … first free (conflict_behavior="rename")."""
  async def _upload_small(self, *, parent_id: str, name: str, existing_id: Optional[str], source: Union[Path, BinaryIO], content_type: str) -> Dict[str, Any]:
      """multipart ``files_create`` (new) or ``files_update`` (replace) through aiogoogle upload_file / pipe_from (resource.py:563-601)."""
  async def _upload_resumable(self, *, parent_id: str, name: str, existing_id: Optional[str], read: Callable[[int], Awaitable[bytes]], size: int, content_type: str) -> Dict[str, Any]:
      """POST RESUMABLE_URL?uploadType=resumable[&supportsAllDrives=true] (PATCH RESUMABLE_URL/{id} for replace) with JSON metadata
      via ``drive.send_raw(full_res=True)`` → ``Location`` (validated by _validate_upload_url); PUT ``chunk_size`` chunks with
      ``Content-Range: bytes a-b/size`` via ``send_raw(raise_for_status=False)``; 308 → continue from the ``Range`` header;
      200/201 → final item JSON; 5xx/429 → ``_retrying`` re-PUTs the same chunk; the session POST is never retried."""
  async def upload_file(self, source: Union[BinaryIO, Path], destination: str) -> FileMetadata:
      """Route by ``small_file_threshold``; apply ``conflict_behavior``; ensure parents (create=True); invalidate cache."""
  async def create_file(self, path: str, content: bytes) -> bool: ...
  async def upload_file_from_bytes(self, file_obj: bytes, destination_key: str, content_type: str = "application/octet-stream") -> str:
      """Returns ``webViewLink`` (S3 parity; graph.py:796-802)."""
  async def copy_file(self, source: str, destination: str) -> FileMetadata:
      """``files_copy(id, {"name", "parents": [dest_parent]})`` — synchronous in Drive; never retried (non-idempotent)."""
  async def delete_file(self, path: str) -> bool:
      """``files_update(id, {"trashed": True})`` or ``files_delete`` when ``permanent_delete``; missing → False."""
  async def create_folder(self, folder_name: str) -> None: ...          # files_create(FOLDER_MIME), idempotent
  async def remove_folder(self, folder_name: str) -> None: ...          # trash / delete the folder item (Drive cascades)
  async def rename_file(self, old_file_name: str, new_file_name: str) -> None: ...
  async def rename_folder(self, old_folder_name: str, new_folder_name: str) -> None: ...
  async def _move_or_rename(self, old: str, new: str) -> None:
      """``files_update(id, {"name"}, add_parents=…, remove_parents=…)`` when the parent changes; conflict per ``conflict_behavior``."""
  async def create_sharing_link(self, path: str, *, scope: ShareScope = "user", role: ShareRole = "reader",
                                email_address: Optional[str] = None, domain: Optional[str] = None, expiry: int = 0) -> str:
      """``permissions_create(id, {"type": scope, "role": role, "emailAddress"/"domain", "expirationTime" iff expiry>0 and
      scope in {user, group}})`` then ``files_get(fields="webViewLink")``. ValueError when the scope's required field is
      missing; PermissionError (403 with a sharing-policy reason) for a forbidden scope; never retried."""
  async def get_file_url(self, path: str, expiry: int = 3600) -> str:    # exact interface signature (abstract.py:67)
      """``webViewLink`` of the item; no permission change; ``expiry`` ignored with a debug log (U3)."""
  async def upload_files(self, items: Sequence[Tuple[Union[Path, BinaryIO, bytes], str]]) -> List[BatchItemResult]: ...
  async def download_files(self, items: Sequence[Tuple[str, Union[Path, BinaryIO]]]) -> List[BatchItemResult]: ...
  def _reject_shared_streams(self, objs: List[Any]) -> None: ...        # graph.py:1014-1022 contract (ValueError)
  async def _run_batch(self, items: List[Tuple[Any, Any]], run_one: Callable[[int, Any, Any], Awaitable[FileMetadata]]) -> List[BatchItemResult]:
      """AC8 contract re-implemented from graph.py:1024-1093: Semaphore(max_concurrency), results in input order, never raises
      per item, first 401/403 marks the remainder ``skipped`` (attempts=0), outer cancellation propagates."""
  def _classify(self, exc: BaseException) -> Tuple[BatchErrorCode, Optional[int]]: ...
  def setup(self, app: Any, route: str = "gdrive", base_url: Optional[str] = None) -> Any:
      """``GuardedFileServingExtension(manager=self, route=route, manager_name=self.manager_name, max_bytes=self.serving_max_bytes).setup(app)``
      (gcs.py:507-527 shape)."""
  async def handle_file(self, request: Any) -> Any: ...
  ```

### Module 5: Graph-free `entries.py` (relocation)
- **Path**: `packages/ai-parrot/src/parrot/interfaces/file/entries.py` (new);
  `packages/ai-parrot/src/parrot/interfaces/file/graph.py` (modifies, behaviour-neutral)
- **Responsibility**: move `DriveEntry` (`graph.py:104-118`) and `_GuardedFileServingExtension`
  (`graph.py:73-102`, renamed `GuardedFileServingExtension`) verbatim into a module that
  imports neither msgraph nor aiogoogle, and re-import them in `graph.py` under the old
  names so `graph.DriveEntry` and `graph._GuardedFileServingExtension` keep resolving
  (the O365 tools import `DriveEntry` from `graph` — `parrot_tools/o365/{sharepoint,onedrive}.py`).
- **Depends on**: nothing in this spec
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot/src/parrot/interfaces/file/entries.py  (new)
  from navigator.utils.file.web import FileServingExtension   # verified: graph.py:50; web.py:28
  class DriveEntry(BaseModel): ...                             # verbatim from graph.py:104-118
  class GuardedFileServingExtension(FileServingExtension): ... # verbatim from graph.py:73-102

  # packages/ai-parrot/src/parrot/interfaces/file/graph.py  (modifies graph.py:73 and :93)
  from .entries import DriveEntry, GuardedFileServingExtension
  _GuardedFileServingExtension = GuardedFileServingExtension   # keeps graph.py:1113-1126 setup() and tests unchanged
  ```

### Module 6: registration — shims, factory, literals, tests
- **Path**: `packages/ai-parrot/src/parrot/interfaces/file/__init__.py`,
  `packages/ai-parrot-tools/src/parrot_tools/file/__init__.py`,
  `packages/ai-parrot/src/parrot/tools/filemanager.py`,
  `packages/ai-parrot/tests/interfaces/test_file_shim.py`,
  `packages/ai-parrot/tests/tools/test_filemanager_batch_ops.py` (all modify)
- **Responsibility**: make `gdrive` discoverable everywhere FEAT-603 made `sharepoint` /
  `onedrive` discoverable; extend the existing guard tests.
- **Depends on**: M2 (`parrot.interfaces.file.gdrive.GoogleDriveFileManager` must import)
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot/src/parrot/interfaces/file/__init__.py  (modifies :26-35 __all__, :37-43 _LAZY_MANAGERS)
  __all__ = (..., "OneDriveFileManager", "GoogleDriveFileManager")
  _LAZY_MANAGERS = {..., "GoogleDriveFileManager": "parrot.interfaces.file.gdrive"}   # lazy: no aiogoogle/selenium/redis at import

  # packages/ai-parrot-tools/src/parrot_tools/file/__init__.py  (modifies :10-19 __all__, :24 lazy tuple)
  if name in ("S3FileManager", "GCSFileManager", "SharePointFileManager", "OneDriveFileManager", "GoogleDriveFileManager"): ...

  # packages/ai-parrot/src/parrot/tools/filemanager.py  (modifies :27-28, :49-51, :60, :183, :198, :256, :259, :748, :773, :847, :864)
  ManagerType = Literal["fs", "temp", "s3", "gcs", "sharepoint", "onedrive", "gdrive"]
  _PARROT_NATIVE = {..., "gdrive": ("parrot.interfaces.file.gdrive", "GoogleDriveFileManager")}
  _DRIVE_RELATIVE_BACKENDS = frozenset({"sharepoint", "onedrive", "gdrive"})    # both FileManagerTool (:259) and FileManagerToolkit (:864)
  # docstrings/description strings list "gdrive" next to onedrive (:60, :183, :198, :256, :748, :773, :847)

  # packages/ai-parrot/tests/interfaces/test_file_shim.py  (modifies)
  def test_no_gdrive_leak_on_import(): ...            # after :43 pattern — "aiogoogle", "selenium", "redis", "parrot.interfaces.file.gdrive" absent
  def test_shim_exports_gdrive_lazily(): ...          # after :140 pattern
  def test_parrot_tools_file_shim_gdrive_parity(): ...# after :151 pattern
  def test_factory_gdrive_native(monkeypatch): ...    # after test_factory_sharepoint_and_onedrive_native; ValueError message lists 7 keys
  # packages/ai-parrot/tests/tools/test_filemanager_batch_ops.py  (modifies :170-181)
  #   test_storage_path_is_drive_relative_for_graph_and_unchanged_otherwise also asserts manager_type="gdrive"
  ```

### Module 7: `GoogleDriveToolkit`
- **Path**: `packages/ai-parrot-tools/src/parrot_tools/google/drive.py` (new);
  `packages/ai-parrot-tools/src/parrot_tools/google/__init__.py` (modifies);
  `packages/ai-parrot-tools/tests/google/test_drive_toolkit.py` (new)
- **Responsibility**: agent-facing Drive tools delegating to `GoogleDriveFileManager`, in
  the `GoogleCalendarToolkit` mould (`calendar.py:74-112`: constructor stores config,
  `_open()` acquires the live client, `_close()` releases it). Importing
  `parrot_tools.google` already loads `parrot.interfaces.google` (`base.py:12`), so no
  lazy-import guard applies here.
- **Depends on**: M2, M3, M4
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot-tools/src/parrot_tools/google/drive.py  (new)
  from parrot.tools.toolkit import AbstractToolkit                    # verified: toolkit.py:203 (tool_prefix :254, auto_open :316, _open :398)
  from parrot.interfaces.google import GoogleClient                    # verified: google.py:226
  from parrot.interfaces.file.gdrive import GoogleDriveFileManager, ShareScope, ShareRole, ConflictBehavior

  class GoogleDriveToolkit(AbstractToolkit):
      """Google Drive tools for agents: ``gdrive_list_files``, ``gdrive_search_files``, ``gdrive_download_file``,
      ``gdrive_upload_file``, ``gdrive_share_file``, ``gdrive_get_file_link`` — all delegating to GoogleDriveFileManager."""
      tool_prefix: str = "gdrive"
      auto_open: bool = True

      def __init__(
          self,
          manager: Optional[GoogleDriveFileManager] = None,
          *,
          google_client: Optional[GoogleClient] = None,
          root_id: Optional[str] = None,
          root_path: str = "",
          shared_drive_id: Optional[str] = None,
          prefix: str = "",
          credentials: Optional[Union[str, Dict[str, Any], Path]] = None,
          auth_mode: str = "service_account",
          scopes: Optional[Union[str, List[str]]] = None,
          download_dir: Optional[Union[str, Path]] = None,        # default parrot.conf.OUTPUT_DIR / "gdrive"
          max_results: int = 50,
          **kwargs: Any,
      ) -> None:
          """``manager`` wins; else the manager is built from the remaining kwargs in ``_open()``."""
      async def _open(self) -> None:
          """Build the manager if needed; ``adopt_client(google_client)`` when given, else ``await manager.connect()``."""
      async def _close(self) -> None: ...                           # closes only a manager the toolkit built

      async def list_files(self, path: str = "", pattern: str = "*", include_folders: bool = False) -> Dict[str, Any]:
          """→ {"entries": [{name, path, is_folder, size, content_type, modified_at, web_url}], "count", "path"}"""
      async def search_files(self, keywords: Optional[Union[str, List[str]]] = None, extension: Optional[str] = None,
                             prefix: Optional[str] = None, max_results: Optional[int] = None) -> Dict[str, Any]:
          """→ {"files": [...FileMetadata dicts...], "count", "truncated": bool}  (max_results applied after filtering)"""
      async def download_file(self, path: str, destination_name: Optional[str] = None) -> Dict[str, Any]:
          """→ {"downloaded": True, "path": <drive path>, "local_path", "size", "content_type"}"""
      async def upload_file(self, source_path: str, destination: str, conflict_behavior: Optional[ConflictBehavior] = None) -> Dict[str, Any]:
          """→ {"uploaded": True, "name", "path", "size", "content_type", "url"}  (FileNotFoundError for a missing local file)"""
      async def share_file(self, path: str, scope: ShareScope = "user", role: ShareRole = "reader",
                           email_address: Optional[str] = None, domain: Optional[str] = None, expiry: int = 0) -> Dict[str, Any]:
          """→ {"shared": True, "path", "scope", "role", "url"}"""
      async def get_file_link(self, path: str) -> Dict[str, Any]:
          """→ {"path", "url"}  (webViewLink, no permission change)"""

  # packages/ai-parrot-tools/src/parrot_tools/google/__init__.py  (modifies :11 and :22)
  from .drive import GoogleDriveToolkit
  __all__ = (..., "LyriaToolkit", "GoogleDriveToolkit")
  ```

### Module 8: packaging + docs
- **Path**: `packages/ai-parrot/pyproject.toml` (modifies);
  `packages/ai-parrot/tests/test_gdrive_extra.py` (new);
  `docs/interfaces/gdrive-filemanager.md` (new); `docs/integrations/google-oauth2.md` (new)
- **Responsibility**: a `gdrive` extra mirroring `msgraph` (`pyproject.toml:400-404`) and
  folded into `all` (`:886-887`); docs in the `docs/interfaces/graph-filemanager.md` shape
  (Install · Quick start · Authentication · Paths · Uploads and downloads · Sharing links ·
  Batch operations · Search · Serving over HTTP · Agents) plus an OAuth/service-account setup
  page (scopes, shared-drive membership, `GOOGLE_CREDENTIALS_FILE`, cached-session files).
- **Depends on**: nothing in this spec (docs reference M2–M7 names, fixed above)
- **Interface Skeleton**:
  ```toml
  # packages/ai-parrot/pyproject.toml  (modifies: new block before `agents = [` at :406; `all` self-ref at :887 gains ",gdrive")
  gdrive = [
      "aiogoogle>=5.17,<6",
      "aiofiles>=23.0",
  ]
  ```
  ```python
  # packages/ai-parrot/tests/test_gdrive_extra.py  (new; copies test_msgraph_extra.py:1-24 shape)
  def test_gdrive_extra_present_and_in_all(): ...
  def test_agents_extra_keeps_its_aiogoogle_pin(): ...     # "aiogoogle==5.17.0" still present in the agents bundle (:432)
  ```

### Module 9: live gate suite
- **Path**: `packages/ai-parrot/tests/interfaces/test_gdrive_filemanager_live.py` (new)
- **Responsibility**: opt-in round trips against a real Drive, skipped unless
  `PARROT_LIVE_GDRIVE=1` (pattern `test_graph_filemanager_live.py:10-26`).
- **Depends on**: M2, M3, M4
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot/tests/interfaces/test_gdrive_filemanager_live.py  (new)
  pytestmark = pytest.mark.live
  # knobs: PARROT_LIVE_GDRIVE=1 (required), PARROT_LIVE_GDRIVE_ROOT_ID or PARROT_LIVE_GDRIVE_ROOT_PATH (one required),
  #        PARROT_LIVE_GDRIVE_SHARED_DRIVE (optional), PARROT_LIVE_GDRIVE_SHARE_EMAIL (optional; enables the sharing test),
  #        credentials via GOOGLE_CREDENTIALS_FILE (service account) — all writes under parrot-live/<uuid>/
  async def test_live_roundtrip(): ...            # upload bytes → exists → metadata → list → find → get_file_url → download → copy → rename → delete
  async def test_live_shared_drive_roundtrip(): ...   # skipped without PARROT_LIVE_GDRIVE_SHARED_DRIVE
  async def test_live_batch_upload_download(): ...    # 12 files, max_concurrency=3, all ok, order preserved
  async def test_live_large_resumable_upload(): ...   # 12 MiB → resumable session, ≥2 chunks
  async def test_live_sharing_link_user_scope(): ...  # skipped without PARROT_LIVE_GDRIVE_SHARE_EMAIL
  ```

### Module 10: feature guards (cross-cutting)
- **Path**: `packages/ai-parrot/tests/interfaces/test_gdrive_guards.py` (new)
- **Responsibility**: the FEAT-603 guard set applied to this feature — interface-signature
  parity (`test_graph_filemanager.py:523-528` pattern), no-httpx AST scan of
  `gdrive.py` / `entries.py` / `drive.py`, signature snapshot of `GoogleClient` (every
  existing public method except the promoted `get_drive_client` return annotation),
  `GoogleBaseTool`, `FileManagerFactory.create`, `FileManagerTool.__init__`,
  `FileManagerToolkit.__init__`, and the M5 relocation invariant (`graph.DriveEntry is
  entries.DriveEntry`, `graph._GuardedFileServingExtension is entries.GuardedFileServingExtension`).
- **Depends on**: M1, M2, M5, M6, M7
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot/tests/interfaces/test_gdrive_guards.py  (new)
  def test_all_interface_methods_implemented_with_exact_signatures(): ...
  def test_get_file_url_signature_matches_interface(): ...
  def test_no_httpx_or_requests_in_new_modules(): ...
  def test_public_signatures_unchanged_vs_snapshot(): ...
  def test_graph_reexports_relocated_names(): ...
  def test_gdrive_module_imports_no_google_client_at_module_level(): ...   # importing gdrive.py leaves "parrot.interfaces.google" out of sys.modules
  ```

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_fake_drive_paths_and_duplicates` / `test_fake_client_pagination_and_fail_next` | M0 | harness self-tests (as `test_graph_fakes.py`) |
| `test_drive_client_open_is_idempotent_and_discovers_once` / `test_drive_client_dispatches_service_account_vs_user` / `test_drive_client_send_raw_authorises_request` / `test_get_drive_client_returns_drive_client` / `test_aiogoogle_credentials_requires_initialised` | M1 | one `Aiogoogle` + one `discover` per client; dispatch by `using_service_account()`; promotion |
| `test_constructor_defaults_and_validation` | M2 | `root_id` xor `root_path`; prefix normalisation; chunk multiple of 256 KiB; no I/O, no GoogleClient construction |
| `test_connect_auth_mode_branches` | M2 | `service_account` → `initialize`; `user` → `interactive_login` + `initialize`; `cached` → `initialize`, fallback only on the exact RuntimeError; one credential load |
| `test_adopt_client_skips_auth_and_never_closes` | M2 | AC3 analogue |
| `test_resolve_root_shared_drive_root_id_root_path` | M2 | three root modes; `files.get` verification of `root_id`; FileNotFoundError on a missing `root_path` |
| `test_resolve_walks_segments_with_escaped_q_and_caches` | M2 | `q` strings exact; second lookup hits `_path_cache`; `_invalidate` on write |
| `test_resolve_duplicate_names_newest_then_smallest_id` | M2 | deterministic first match |
| `test_prefixed_unprefixed_roundtrip` / `test_rejects_parent_segments` | M2 | S3 parity; `..` → ValueError |
| `test_map_error_and_status_from_httperror` / `test_retry_policy_caps_retry_after_and_never_non_idempotent` | M2 | `HTTPError.res.status_code`; 429/5xx retried; copy / session POST / permissions never |
| `test_validate_upload_url_rejects_http_and_foreign_hosts` | M2 | host allow-list; never logged |
| `test_list_files_excludes_folders_and_follows_page_tokens` / `test_list_entries_includes_folders_all_pages` | M3 | three scripted pages |
| `test_list_params_shared_drive_flags` | M3 | `corpora`, `driveId`, `includeItemsFromAllDrives`, `supportsAllDrives` present iff configured (supportsAllDrives always) |
| `test_find_files_server_side_contains_then_client_filters` / `test_search_paginates_then_applies_max_results` | M3 | `name contains`; extension client-side; recursive under prefix |
| `test_download_to_path_and_binaryio_streams` / `test_download_workspace_native_raises` | M3 | `download_file=` vs `pipe_to=_AsyncSink`; returns `Path(source)` for BinaryIO |
| `test_upload_small_multipart_create_and_replace` | M4 | `< threshold` → `files_create` / `files_update(existing)` with `upload_file` or `pipe_from` + content type |
| `test_upload_resumable_session_chunks_308_and_range_resume` | M4 | POST → Location; PUTs with `Content-Range`; 308 + `Range` continue; final 200; session POST never retried; chunk 503 retried |
| `test_upload_conflict_replace_fail_rename` | M4 | same id on replace; `FileExistsError`; `name (1).ext` |
| `test_create_file_and_upload_file_from_bytes_returns_webviewlink` | M4 | bytes path |
| `test_copy_is_synchronous_and_never_retried` / `test_delete_trashes_by_default_permanent_optional_missing_false` | M4 | copy/delete contracts |
| `test_folders_create_remove_rename_and_move_across_parents` | M4 | `addParents` / `removeParents` |
| `test_get_file_url_returns_webviewlink_without_permissions` / `test_get_file_url_signature_matches_interface` | M4 | U3; `expiry` ignored with debug log; no `permissions.create` call |
| `test_create_sharing_link_bodies_per_scope_and_expiry_rules` / `test_create_sharing_link_forbidden_scope_permission_error` | M4 | `user`/`group` need `email_address`, `domain` needs `domain`, `expirationTime` only for user/group; 403 policy → PermissionError |
| `test_upload_files_per_item_results_order_and_no_raise` / `test_batch_retries_429_with_retry_after_then_succeeds` / `test_batch_auth_failure_skips_remaining` / `test_batch_concurrency_bounded` / `test_batch_rejects_shared_binaryio` / `test_batch_cancellation_propagates` | M4 | AC8 contract |
| `test_setup_mounts_guarded_extension_and_413_over_limit` | M4 | `GuardedFileServingExtension(max_bytes=…)` |
| `test_entries_module_is_graph_free` / `test_graph_reexports_relocated_names` | M5 | `entries.py` imports no msgraph / aiogoogle; FEAT-603 suites still pass |
| `test_no_gdrive_leak_on_import` / `test_shim_exports_gdrive_lazily` / `test_parrot_tools_file_shim_gdrive_parity` / `test_factory_gdrive_native` / `test_factory_unknown_lists_seven_keys` / `test_storage_path_is_drive_relative_for_gdrive` | M6 | shim + factory + toolkit literal; `FileManagerToolkit(manager_type="gdrive")` with the fake |
| `test_toolkit_builds_manager_or_adopts_google_client` / `test_toolkit_tool_names_and_response_shapes` / `test_toolkit_download_uses_download_dir` / `test_toolkit_share_and_link` | M7 | `gdrive_*` names; response dict keys exactly as §3 M7 |
| `test_gdrive_extra_present_and_in_all` / `test_agents_extra_keeps_its_aiogoogle_pin` | M8 | pyproject parse |
| `test_all_interface_methods_implemented_with_exact_signatures` / `test_no_httpx_or_requests_in_new_modules` / `test_public_signatures_unchanged_vs_snapshot` / `test_gdrive_module_imports_no_google_client_at_module_level` | M10 | guards |

Test locations: `packages/ai-parrot/tests/interfaces/test_gdrive_fakes.py` (M0),
`packages/ai-parrot/tests/interfaces/test_drive_client.py` (M1),
`packages/ai-parrot/tests/interfaces/test_gdrive_filemanager.py` (M2–M4),
`packages/ai-parrot/tests/interfaces/test_entries.py` (M5), `test_file_shim.py` +
`tests/tools/test_filemanager_batch_ops.py` (M6, extended),
`packages/ai-parrot-tools/tests/google/test_drive_toolkit.py` (M7),
`packages/ai-parrot/tests/test_gdrive_extra.py` (M8),
`packages/ai-parrot/tests/interfaces/test_gdrive_guards.py` (M10).

### Integration Tests
| Test | Description |
|---|---|
| `test_live_roundtrip` (M9, `@pytest.mark.live`) | upload bytes → exists → metadata → list → find → get_file_url → download to BinaryIO → copy → rename → delete; all under `parrot-live/<uuid>/` |
| `test_live_shared_drive_roundtrip` (M9) | same against `PARROT_LIVE_GDRIVE_SHARED_DRIVE` |
| `test_live_batch_upload_download` (M9) | 12 files, `max_concurrency=3`, all `ok`, order preserved |
| `test_live_large_resumable_upload` (M9) | 12 MiB file exercises the resumable session (≥ 2 chunks) |
| `test_live_sharing_link_user_scope` (M9) | `create_sharing_link(scope="user", email_address=PARROT_LIVE_GDRIVE_SHARE_EMAIL, expiry=3600)` |

Run manually: `PARROT_LIVE_GDRIVE=1 PARROT_LIVE_GDRIVE_ROOT_PATH=parrot-live pytest packages/ai-parrot/tests/interfaces/test_gdrive_filemanager_live.py -m live -v`.

### Test Data / Fixtures
```python
# packages/ai-parrot/tests/interfaces/test_gdrive_filemanager.py (uses M0)
@pytest.fixture
def fake_drive():
    drive = FakeDrive()
    drive.put_folder("reports/2026")
    drive.put_file("reports/2026/q3.xlsx", b"x" * 10, mime="application/vnd.ms-excel")
    return drive

@pytest.fixture
def manager(fake_drive, monkeypatch):
    fake = FakeDriveClient(fake_drive, page_size=2)
    m = make_manager(fake, root_path="reports", prefix="2026/")
    monkeypatch.setattr(m, "_sleep", _no_sleep)
    return m, fake
```

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] AC1. `GoogleDriveFileManager` implements every abstract method of `FileManagerInterface` with the exact signatures at `navigator/utils/file/abstract.py:53-155`, plus `create_folder` / `remove_folder` / `rename_folder` / `rename_file` (:170-212) and a server-side `find_files` override (:265); `issubclass` and `inspect.signature` parity tests pass.
- [ ] AC2. `GoogleDriveFileManager` is a direct `FileManagerInterface` subclass (not a `GraphDriveFileManager` subclass); `gdrive.py` imports nothing from `graph.py` or `msgraph`, and importing `gdrive.py` does not import `parrot.interfaces.google` at module level.
- [ ] AC3. `connect()` reproduces the three `GoogleBaseTool._get_client` branches (`base.py:110-135`) with **one** credential load per manager; `adopt_client()` performs no authentication and `close()` never closes an adopted client.
- [ ] AC4. `DriveClient` opens one `Aiogoogle` session and runs `discover("drive", "v3")` once per manager lifetime; every call dispatches through `as_service_account` or `as_user` according to `GoogleClient.using_service_account()`; `GoogleClient.get_drive_client()` returns a `DriveClient`; every other `GoogleClient` public signature is unchanged (snapshot test).
- [ ] AC5. Root targets: `root_id`, `root_path` and `shared_drive_id` resolve as specified; with `shared_drive_id` every `files.list` carries `corpora="drive"`, `driveId`, `includeItemsFromAllDrives=True`, and every `files.*` / `permissions.*` call carries `supportsAllDrives=True`.
- [ ] AC6. Path resolution walks segments with the exact escaped `q` strings, caches per manager, invalidates on writes, resolves duplicate siblings newest-first then smallest id, and rejects `..` with `ValueError`.
- [ ] AC7. Uploads route by `small_file_threshold` (multipart `files.create` / `files.update` below; resumable session at/above with `Content-Range` chunks, 308 + `Range` resume, session POST never retried, session URL validated and never logged); `conflict_behavior` `replace` (same id) / `fail` (`FileExistsError`) / `rename` (`name (n).ext`) is honoured.
- [ ] AC8. `upload_files` / `download_files` return `List[BatchItemResult]` in input order with `index` identity and `state ∈ {succeeded, failed, skipped}` (+ `error_code`), never raise for an item, bound concurrency to `max_concurrency` (default 5), retry `{429, 500, 502, 503, 504}` honouring `Retry-After` (capped 60 s) up to `max_retries` (default 3), mark the remainder `skipped` on 401/403, reject a reused `BinaryIO` with `ValueError`, and propagate outer cancellation.
- [ ] AC9. `download_file` streams through aiogoogle (`download_file=` for `Path`, `pipe_to=_AsyncSink` for `BinaryIO`) without buffering the whole object, returns `Path(source)` for `BinaryIO`, and raises `GoogleDriveFileManagerError` for Workspace-native MIME types.
- [ ] AC10. `get_file_url(path, expiry=3600)` keeps the exact interface signature, returns `webViewLink`, and issues **no** `permissions.create`; `create_sharing_link` builds the permission body per scope (`emailAddress` for user/group, `domain` for domain, `expirationTime` only for user/group, `sendNotificationEmail=False`), returns `webViewLink`, raises `ValueError` for a missing required field and `PermissionError` for a policy-forbidden scope, and is never retried.
- [ ] AC11. `delete_file` trashes by default (`permanent_delete=True` → `files.delete`) and returns `False` for a missing path; `copy_file` uses `files.copy` and is never retried; rename/move use `addParents` / `removeParents`.
- [ ] AC12. Every listing and search follows `nextPageToken` to exhaustion; `list_files` excludes folders, `list_entries` includes them; `max_results` in the toolkit search is applied after filtering (three-page fake test).
- [ ] AC13. `from parrot.interfaces.file import GoogleDriveFileManager` and the `parrot_tools.file` parity import work; importing either shim leaves `aiogoogle`, `selenium`, `redis` and `parrot.interfaces.file.gdrive` out of `sys.modules` (extends `test_no_msgraph_leak_on_import`, `test_file_shim.py:43-49`).
- [ ] AC14. `FileManagerFactory.create("gdrive", **kwargs)` resolves locally through `_PARROT_NATIVE`; unknown keys raise `ValueError` listing all seven keys; `FileManagerTool` and `FileManagerToolkit` accept `manager_type="gdrive"`; `_storage_path` treats `gdrive` as drive-relative; `fs_find_files` / `fs_batch_upload` / `fs_batch_download` use the manager's native methods.
- [ ] AC15. `GoogleDriveToolkit` exposes exactly `gdrive_list_files`, `gdrive_search_files`, `gdrive_download_file`, `gdrive_upload_file`, `gdrive_share_file`, `gdrive_get_file_link` with the response dict keys in §3 M7, builds its manager in `_open()` or adopts a supplied `GoogleClient`, and is exported from `parrot_tools.google`.
- [ ] AC16. M5 relocation is behaviour-neutral: `parrot.interfaces.file.graph.DriveEntry is parrot.interfaces.file.entries.DriveEntry`, `graph._GuardedFileServingExtension is entries.GuardedFileServingExtension`, `entries.py` imports neither `msgraph` nor `aiogoogle`, and the FEAT-603 suites (`test_graph_filemanager.py`, `test_graph_fakes.py`, `test_sharepoint_filemanager.py`, `test_onedrive_filemanager.py`, `test_onedrive_client_user_drive.py`) pass unchanged.
- [ ] AC17. `packages/ai-parrot/pyproject.toml` has a `gdrive` extra (`aiogoogle>=5.17,<6`, `aiofiles>=23.0`) and `all` includes it; the `agents` bundle pins are untouched; `uv pip install -e "packages/ai-parrot[gdrive]"` resolves in the dev venv (recorded in `artifacts/logs/`).
- [ ] AC18. No `httpx`, `requests`, `langchain*` or `print(` in any new or modified module (`ruff check` TID251 clean; AST test over `gdrive.py`, `entries.py`, `drive.py`).
- [ ] AC19. Docs: `docs/interfaces/gdrive-filemanager.md` and `docs/integrations/google-oauth2.md` exist with the sections named in §3 M8, including the `serving_max_bytes` limit and the "no Workspace export in v1" note.
- [ ] AC20. All new unit tests pass under `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-tools/src pytest packages/ai-parrot/tests/interfaces packages/ai-parrot/tests/tools/test_filemanager_batch_ops.py packages/ai-parrot/tests/test_gdrive_extra.py packages/ai-parrot-tools/tests/google/test_drive_toolkit.py -v`; `test_file_shim.py` and `test_msgraph_extra.py` still pass.
- [ ] AC21. The live suite (M9) is run once manually by the owner against the knobs in §3 M9 before `/sdd-done` and its output is saved under `artifacts/logs/FEAT-608-live.log`; a skipped live suite is recorded as such in the task's Completion Note, never as a pass.
- [ ] AC22. `handle_file` returns HTTP 413 for objects larger than `serving_max_bytes` (default 64 MiB) before the buffering `FileServingExtension` path runs.
- [ ] AC23. No breaking change: every existing public method of `GoogleClient` (except the `get_drive_client` return type, which had no callers), `GoogleBaseTool`, `GoogleCalendarToolkit`, `FileManagerFactory`, `FileManagerTool`, `FileManagerToolkit`, `GraphDriveFileManager`, `SharePointFileManager` and `OneDriveFileManager` keeps its signature (snapshot test against the base commit).

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> This section is the single source of truth for what exists in the codebase.
> Implementation agents MUST NOT reference imports, attributes, or methods
> not listed here without first verifying they exist via `grep` or `read`.
> Verified 2026-09-26 against base commit `fe035e260` (dev, includes FEAT-603 via PR #1501),
> venv python3.12, `aiogoogle 5.19.0`, `aiofiles 24.1.0`, `navigator-api 4.0.0`.

### Verified Imports
```python
from navigator.utils.file import FileManagerInterface, FileMetadata                 # verified: graph.py:49; abstract.py:36, :16
from navigator.utils.file.web import FileServingExtension                           # verified: graph.py:50; web.py:28 (__init__ :48-60: manager, route="/data", manager_name)
from parrot.interfaces.file import FileManagerInterface, FileMetadata, S3FileManager, GCSFileManager, SharePointFileManager, OneDriveFileManager   # verified: file/__init__.py:19-24, :26-35, :37-43
from parrot.interfaces.file.batch import BatchErrorCode, BatchItemResult, BatchState, BatchSummary   # verified: batch.py:14, :18, :21, :41 (from_items :54)
from parrot.interfaces.file.graph import GraphDriveFileManager, GraphFileManagerError, DriveEntry   # verified: graph.py:142, :128, :104
from parrot.interfaces.file.sharepoint import SharePointFileManager                 # verified: sharepoint.py:12
from parrot.interfaces.google import GoogleClient, CalendarClient, DEFAULT_SCOPES, create_google_client   # verified: google.py:226, :160, :40, :1091
from parrot.tools.filemanager import FileManagerFactory, FileManagerTool, FileManagerToolkit, ManagerType   # verified: filemanager.py:31, :154, :721, :28
from parrot.tools import FileManagerTool, FileManagerToolkit                        # verified: parrot/tools/__init__.py:241-243 (lazy map :269-271)
from parrot.tools.toolkit import AbstractToolkit                                    # verified: toolkit.py:203
from parrot_tools.google.base import GoogleBaseTool, GoogleAuthMode, GoogleToolArgsSchema   # verified: base.py:36, :15, :23
from parrot_tools.google.calendar import GoogleCalendarToolkit                      # verified: calendar.py:74
from parrot_tools.google import GoogleBaseTool, LyriaToolkit                        # verified: parrot_tools/google/__init__.py:10-11, :22
from parrot.conf import GOOGLE_CREDENTIALS_FILE, GOOGLE_API_KEY                     # verified: conf.py:434-436, :430
from aiogoogle import Aiogoogle                                                     # verified: google.py:29; aiogoogle/client.py:27
from aiogoogle.auth.creds import ServiceAccountCreds, UserCreds                     # verified: google.py:30; creds.py:282 (subject kwarg :259)
from aiogoogle.models import Request, Response, MediaUpload, MediaDownload           # verified: models.py:141, :253, :33, :121
from aiogoogle.excs import HTTPError, AuthError                                      # verified: excs.py:22 (.res :25), :29
```

### Existing Class Signatures
```python
# .venv/lib/python3.12/site-packages/navigator/utils/file/abstract.py (navigator-api 4.0.0)
class FileMetadata: name: str; path: str; size: int; content_type: Optional[str]; modified_at: Optional[datetime]; url: Optional[str]   # :15-33
class FileManagerInterface(ABC):                                                             # :36
    async def list_files(self, path: str = "", pattern: str = "*") -> List[FileMetadata]     # :53
    async def get_file_url(self, path: str, expiry: int = 3600) -> str                       # :67
    async def upload_file(self, source: Union[BinaryIO, Path], destination: str) -> FileMetadata   # :79
    async def download_file(self, source: str, destination: Union[Path, BinaryIO]) -> Path   # :93
    async def copy_file(self, source: str, destination: str) -> FileMetadata                 # :107
    async def delete_file(self, path: str) -> bool                                           # :119
    async def exists(self, path: str) -> bool                                                # :130
    async def get_file_metadata(self, path: str) -> FileMetadata                             # :141
    async def create_file(self, path: str, content: bytes) -> bool                           # :155
    async def create_folder / remove_folder / rename_folder / rename_file                    # :170-224 (raise NotImplementedError)
    async def find_files(self, keywords=None, extension=None, prefix=None) -> List[FileMetadata]   # :265 (in-memory default)

# packages/ai-parrot/src/parrot/interfaces/file/graph.py (FEAT-603)
class _GuardedFileServingExtension(FileServingExtension):                                    # :73 — moves to entries.py (M5)
    def __init__(self, *args: Any, max_bytes: int, **kwargs: Any) -> None                    # :76
    async def handle_file(self, request: web.Request) -> web.StreamResponse                  # :80
class DriveEntry(BaseModel)                                                                  # :104 — moves to entries.py (M5)
class GraphFileManagerError(RuntimeError): def __init__(self, message: str, *, status_code: Optional[int] = None)   # :128-131
class GraphDriveFileManager(FileManagerInterface, ABC):                                      # :142
    SMALL_FILE_THRESHOLD / CHUNK_SIZE / MAX_CONCURRENCY / MAX_RETRIES / RETRYABLE_STATUS / SERVING_MAX_BYTES / ALLOWED_ORIGINS / ALLOWED_HOST_SUFFIXES   # :150-164
    def __init__(self, *, prefix="", credentials=None, auth_mode="direct", user_assertion=None, scopes=None, conflict_behavior="replace", link_type="view", link_scope="organization", max_concurrency=None, max_retries=None, chunk_size=None, small_file_threshold=None, **kwargs)   # :166-223
    async def connect(self) / def adopt_client(self, client) / async def _ready(self) / async def close(self)   # :307, :339, :354, :372
    def _status_code_of(error) / def _retry_after_seconds(error) / def _map_error(self, exc, *, path) / async def _retrying(self, op, *, label, idempotent=True)   # :399, :411, :439, :450
    async def upload_files(...) / download_files(...) / _reject_shared_streams / _run_batch / _classify   # :992, :1002, :1014, :1024, :1095
    def setup(self, app, route, base_url) / async def handle_file(self, request)              # :1113, :1127

# packages/ai-parrot/src/parrot/interfaces/file/batch.py
BatchState = Literal["succeeded", "failed", "skipped"]                                        # :14
BatchErrorCode = Literal["not_found", "throttled", "timeout", "auth", "conflict", "invalid_path", "io", "unknown"]   # :18
class BatchItemResult(BaseModel): index, source, destination, state, ok, metadata, error, error_code, status_code, attempts   # :21-38
class BatchSummary(BaseModel): total, succeeded, failed, skipped, aborted, items; @classmethod from_items(items, *, aborted=False)   # :41-71

# packages/ai-parrot/src/parrot/interfaces/google.py
DEFAULT_SCOPES = {"drive": [".../auth/drive", ".../auth/drive.file", ".../auth/drive.metadata.readonly"], ...}   # :40-47
class CalendarClient: def __init__(self, google_client: "GoogleClient", version: str = "v3")  # :160, :172
class GoogleClient(CredentialsInterface, ABC):                                               # :226
    def __init__(self, credentials: Optional[Union[str, dict, Path]] = None, scopes: Optional[Union[List[str], str]] = None, user_creds_cache_file: Optional[Union[str, Path]] = None, **kwargs)   # :275-281
    self.redis = aioredis.from_url(self.redis_url, ...)   # EAGER in __init__                # :299-302
    self._service_account_creds: Optional[ServiceAccountCreds]; self._user_creds: Optional[UserCreds]   # :311-312
    def _load_credentials(self, credentials)   # raises RuntimeError when None and GOOGLE_CREDENTIALS_FILE is missing   # :412
    @property active_credentials / credentials_source / is_authenticated                     # :627-640
    def using_service_account(self) -> bool / def using_user_credentials(self) -> bool       # :642, :646
    async def initialize(self) -> GoogleClient                                               # :650  (RuntimeError "User credentials not available. Run interactive_login() first.")
    async def execute_api_call(self, service_name, api_name, method_chain, version=None, **kwargs)   # :705 (new Aiogoogle + discover per call)
    async def get_drive_client(self, version: str = "v3") -> Dict[str, Any]                  # :771-773  ← promoted by M1
    async def get_calendar_client(self, version: str = "v3") -> "CalendarClient"             # :783
    async def interactive_login(self, scopes=None, port=5050, redirect_uri=None, open_browser=True, browser="system", login_callback=None, timeout=300) -> Dict[str, Any]   # :827-836
    async def close(self) -> None   # only flips _authenticated                               # :1051
    async def ensure_interactive_session(self, scopes=None) -> None                          # :1059

# packages/ai-parrot-tools/src/parrot_tools/google/base.py
class GoogleAuthMode: SERVICE_ACCOUNT = "service_account"; USER = "user"; CACHED = "cached"   # :15-20
class GoogleBaseTool(AbstractTool):                                                          # :36
    def __init__(self, credentials=None, default_auth_mode=GoogleAuthMode.SERVICE_ACCOUNT, scopes=None, user_creds_cache_file=None, open_browser=True, login_callback=None, interactive_login_kwargs=None, interactive_timeout=300, **kwargs)   # :44-47
    async def _get_client(self, auth_mode=None, scopes=None) -> GoogleClient   # branch table :110-135

# packages/ai-parrot-tools/src/parrot_tools/google/calendar.py
class GoogleCalendarToolkit(AbstractToolkit): def __init__(self, google_client: GoogleClient, ...); async def _open(self); async def _close(self)   # :74, :84, :104, :108

# packages/ai-parrot/src/parrot/tools/toolkit.py
class AbstractToolkit(ABC): exclude_tools: tuple = (); tool_prefix: str | None = None; auto_open: bool = False; def __init__(self, **kwargs); async def _open(self)   # :203, :240, :254, :316, :329, :398

# packages/ai-parrot/src/parrot/tools/filemanager.py (FEAT-603 state)
ManagerType = Literal["fs", "temp", "s3", "gcs", "sharepoint", "onedrive"]                   # :28
class FileManagerFactory: _PARROT_TO_UPSTREAM (:41); _PARROT_NATIVE = {"sharepoint": (...), "onedrive": (...)} (:49-52); def create(manager_type: ManagerType, **kwargs) -> FileManagerInterface (:55; native lookup :69; ValueError listing both maps :76-77)
class FileManagerTool(AbstractTool): description (:183); __init__(manager_type: ManagerType = "fs", ...) (:188); _create_manager (:241-257); _DRIVE_RELATIVE_BACKENDS (:259); _storage_path (:261)
_OP_TO_METHOD (:704-717) incl. "find", "batch_upload", "batch_download"; _ALL_OPS (:718)
class FileManagerToolkit(AbstractToolkit): __init__(manager_type: ManagerType = "fs", ...) (:762); _create_manager (:822-848); _DRIVE_RELATIVE_BACKENDS (:864); _storage_path (:866); batch_upload uses hasattr(self.manager, "upload_files") (:1312)

# aiogoogle 5.19.0 (.venv)
class Aiogoogle: __init__(session_factory=AiohttpSession, api_key=None, user_creds=None, client_creds=None, service_account_creds=None, ...)   # client.py:27, :60
    async def discover(self, api_name, api_version=None, validate=False, *, disco_doc_ver=None) -> GoogleAPI   # client.py:157
    async def as_user(self, *requests, timeout=None, full_res=False, user_creds=None, raise_for_status=True)   # client.py:223
    async def as_service_account(self, *requests, timeout=None, full_res=False, service_account_creds=None, raise_for_status=True)   # client.py:278 (refreshes the SA token :313)
    async def __aenter__ / __aexit__                                                          # client.py:425, :433
Method.__call__(..., upload_file=None, pipe_from=None, download_file=None, pipe_to=None, ...)   # resource.py:394-397; validation :563-601; _build_upload_media :654-690 (resumable object only — no protocol)
class Request(method, url, batch_url, headers, json, data, media_upload, media_download, timeout, callback, _verify_ssl, upload_file_content_type)   # models.py:141, :181-195
class Response(status_code, headers, url, json, data, reason, req, ...)                       # models.py:253, :288-304
AiohttpSession.send(..., full_res=False, raise_for_status=True): pipe_to → `await pipe_to.write(chunk)`; download_file → aiofiles   # aiohttp_session.py:51-56, :71-81
class HTTPError(AiogoogleError): __init__(self, msg, req=None, res: Response | None = None); .res   # excs.py:22-25
class ServiceAccountManager: async def refresh(self)  # token refresh; supports `subject` (managers.py:1132, :1328, :1293-1305)
```

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `DriveClient.open()` | `Aiogoogle(**GoogleClient.aiogoogle_credentials())` + `discover("drive", "v3")` | constructor + coroutine | `client.py:60, :157` |
| `DriveClient.execute()` | `Aiogoogle.as_service_account` / `as_user` | `GoogleClient.using_service_account()` | `client.py:278, :223`; `google.py:642` |
| `DriveClient.send_raw()` | `Aiogoogle.as_service_account(Request, full_res=…, raise_for_status=…)` | hand-built `aiogoogle.models.Request` | `models.py:181-195`; `client.py:278` |
| `GoogleDriveFileManager.connect()` | `GoogleClient.initialize / interactive_login` | `GoogleBaseTool._get_client` branch table | `google.py:650, :827`; `base.py:110-135` |
| `GoogleDriveFileManager.connect()` | `GoogleClient.get_drive_client()` → `DriveClient` | promoted return | `google.py:771` |
| `GoogleDriveFileManager.download_file` | aiogoogle `download_file=` / `pipe_to=_AsyncSink` | `DriveClient.files_download` | `resource.py:563-587`; `aiohttp_session.py:71-81` |
| `GoogleDriveFileManager.setup()` | `GuardedFileServingExtension(manager, route, manager_name, max_bytes).setup(app)` | M5 relocation of `graph.py:73-102` | `web.py:48-60, :78` |
| `GoogleDriveFileManager.upload_files` | `BatchItemResult` / `BatchSummary` | `batch.py` models | `batch.py:21, :41` |
| `FileManagerFactory.create("gdrive")` | `_PARROT_NATIVE` lazy import | one map entry | `filemanager.py:49-51, :69` |
| `FileManagerToolkit.batch_upload` | `manager.upload_files` | existing `hasattr` dispatch | `filemanager.py:1312` |
| `GoogleDriveToolkit._open()` | `GoogleDriveFileManager.connect()` / `adopt_client()` | `AbstractToolkit.auto_open` lifecycle | `toolkit.py:316, :398`; `calendar.py:104` |
| `parrot.interfaces.file.__getattr__` | `parrot.interfaces.file.gdrive.GoogleDriveFileManager` | `_LAZY_MANAGERS` | `file/__init__.py:46-51` |

### Does NOT Exist (Anti-Hallucination)
- ~~`parrot.interfaces.file.gdrive`~~, ~~`GoogleDriveFileManager`~~, ~~`DriveClient`~~, ~~`GoogleDriveToolkit`~~, ~~`parrot.interfaces.file.entries`~~ — all created by this feature.
- ~~`GoogleClient.aiogoogle_credentials()`~~ — added by M1; today the creds live in private `_service_account_creds` / `_user_creds` (`google.py:311-312`).
- ~~`GoogleClient.drive`~~, ~~`GoogleClient.list_drive_files()`~~, ~~`GoogleClient.upload_to_drive()`~~ — no Drive helpers exist; `get_drive_client()` returns a dict (`google.py:771-773`).
- ~~`parrot_tools.google.drive`~~, ~~`GoogleDriveTool`~~, ~~`DriveSearchTool`~~ — no Drive tool of any kind (repo-wide grep, proposal F006).
- ~~`parrot_loaders.gdrive`~~ / ~~`GoogleDriveLoader`~~ — no Drive loader.
- ~~`GraphDriveFileManager` as a base for Drive~~ — msgraph-specific (`graph.py:33-46, :53`); do not subclass it.
- ~~`BatchRunnerMixin`~~ / a shared batch engine in `batch.py` — `batch.py` holds models only (`:14-71`); the engine is `GraphDriveFileManager._run_batch` (`graph.py:1024`) and is re-implemented, not imported.
- ~~aiogoogle resumable-upload protocol~~ — `MediaUpload.resumable` is built (`resource.py:663-690`) but no session code sends chunks (`grep resumable aiogoogle/sessions/` → docstring only); `gdrive.py` implements it with `send_raw`.
- ~~`GoogleClient.close()` closing Redis or sessions~~ — it only flips `_authenticated` (`google.py:1051-1054`).
- ~~`FileManagerInterface.list_entries` / `.find_entries` / `.upload_file_from_bytes` / `.create_sharing_link`~~ — extensions, not interface methods (`abstract.py:36-296`).
- ~~`packages/ai-parrot/tests/interfaces/conftest.py`~~ — does not exist; FEAT-603 fixtures live inside the test modules.
- ~~`packages/ai-parrot/tests/tools/test_filemanager_toolkit.py`~~ — does not exist on `dev` (the FEAT-603 spec's reference is stale); the toolkit tests are `test_filemanager_batch_ops.py`.
- ~~`docs/integrations/google-oauth2.md`~~, ~~`docs/interfaces/gdrive-filemanager.md`~~ — created by M8.
- ~~`ai-parrot[gdrive]`~~ extra — created by M8; the existing `google` extra (`pyproject.toml:603`) is the GenAI client bundle, not Workspace.

### Edit Sites (Blueprint Anchors)

Verified against: `fe035e260` (dev, 2026-09-26)

| File | Action | Verbatim anchor line | Verified at | Occurrences |
|---|---|---|---|---|
| `packages/ai-parrot/src/parrot/interfaces/file/gdrive.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/interfaces/file/entries.py` | CREATE | — | — | — |
| `packages/ai-parrot-tools/src/parrot_tools/google/drive.py` | CREATE | — | — | — |
| `packages/ai-parrot/tests/interfaces/_gdrive_fakes.py` | CREATE | — | — | — |
| `packages/ai-parrot/tests/interfaces/test_gdrive_fakes.py` | CREATE | — | — | — |
| `packages/ai-parrot/tests/interfaces/test_drive_client.py` | CREATE | — | — | — |
| `packages/ai-parrot/tests/interfaces/test_gdrive_filemanager.py` | CREATE | — | — | — |
| `packages/ai-parrot/tests/interfaces/test_entries.py` | CREATE | — | — | — |
| `packages/ai-parrot/tests/interfaces/test_gdrive_guards.py` | CREATE | — | — | — |
| `packages/ai-parrot/tests/interfaces/test_gdrive_filemanager_live.py` | CREATE | — | — | — |
| `packages/ai-parrot/tests/test_gdrive_extra.py` | CREATE | — | — | — |
| `packages/ai-parrot-tools/tests/google/test_drive_toolkit.py` | CREATE | — | — | — |
| `docs/interfaces/gdrive-filemanager.md` | CREATE | — | — | — |
| `docs/integrations/google-oauth2.md` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/interfaces/google.py` | MODIFY | `class CalendarClient:` (new `DriveClient` class inserted after `CalendarClient`'s body, before `class GoogleClient`) | `google.py:160` | 1 |
| `packages/ai-parrot/src/parrot/interfaces/google.py` | MODIFY | `    def using_service_account(self) -> bool:` (new `aiogoogle_credentials()` inserted before it) | `google.py:642` | 1 |
| `packages/ai-parrot/src/parrot/interfaces/google.py` | MODIFY | `    async def get_drive_client(self, version: str = "v3") -> Dict[str, Any]:` | `google.py:771` | 1 |
| `packages/ai-parrot/src/parrot/interfaces/file/graph.py` | MODIFY | `class _GuardedFileServingExtension(FileServingExtension):` (block :73-102 replaced by the `entries` import + alias) | `graph.py:73` | 1 |
| `packages/ai-parrot/src/parrot/interfaces/file/graph.py` | MODIFY | `class DriveEntry(BaseModel):` (block :104-118 removed; name re-imported) | `graph.py:104` | 1 |
| `packages/ai-parrot/src/parrot/interfaces/file/__init__.py` | MODIFY | `__all__ = (` | `file/__init__.py:26` | 1 |
| `packages/ai-parrot/src/parrot/interfaces/file/__init__.py` | MODIFY | `    "OneDriveFileManager": "parrot.interfaces.file.onedrive",` | `file/__init__.py:42` | 1 |
| `packages/ai-parrot-tools/src/parrot_tools/file/__init__.py` | MODIFY | `__all__ = (` | `parrot_tools/file/__init__.py:10` | 1 |
| `packages/ai-parrot-tools/src/parrot_tools/file/__init__.py` | MODIFY | `    if name in ("S3FileManager", "GCSFileManager", "SharePointFileManager", "OneDriveFileManager"):` | `parrot_tools/file/__init__.py:24` | 1 |
| `packages/ai-parrot/src/parrot/tools/filemanager.py` | MODIFY | `#: parrot-native Microsoft Graph managers (``"sharepoint"``, ``"onedrive"``) (FEAT-603)` | `filemanager.py:27` | 1 |
| `packages/ai-parrot/src/parrot/tools/filemanager.py` | MODIFY | `ManagerType = Literal["fs", "temp", "s3", "gcs", "sharepoint", "onedrive"]` | `filemanager.py:28` | 1 |
| `packages/ai-parrot/src/parrot/tools/filemanager.py` | MODIFY | `        "onedrive": ("parrot.interfaces.file.onedrive", "OneDriveFileManager"),` | `filemanager.py:51` | 1 |
| `packages/ai-parrot/src/parrot/tools/filemanager.py` | MODIFY | `                ``"onedrive"`` (parrot-native Microsoft Graph managers, lazily imported).` | `filemanager.py:60` | 1 |
| `packages/ai-parrot/src/parrot/tools/filemanager.py` | MODIFY | `    description: str = "Manage files across different storage backends (local, S3, GCS, SharePoint, OneDrive, temp)"` | `filemanager.py:183` | 1 |
| `packages/ai-parrot/src/parrot/tools/filemanager.py` | MODIFY | `            manager_type: Type of file manager ("fs", "temp", "s3", "gcs", "sharepoint", "onedrive").` | `filemanager.py:198` | 1 |
| `packages/ai-parrot/src/parrot/tools/filemanager.py` | MODIFY | `        else:  # s3, gcs, sharepoint, or onedrive` (inside `FileManagerTool._create_manager`, after `    def _create_manager(` at :241) | `filemanager.py:256` | 2 (ambiguous — use the `class FileManagerTool` context) |
| `packages/ai-parrot/src/parrot/tools/filemanager.py` | MODIFY | `    _DRIVE_RELATIVE_BACKENDS = frozenset({"sharepoint", "onedrive"})` (inside `class FileManagerTool`, preceded by the `#: Backends whose paths are drive-relative` comment) | `filemanager.py:259` | 2 (ambiguous — use the `class FileManagerTool` context) |
| `packages/ai-parrot/src/parrot/tools/filemanager.py` | MODIFY | `      - ``"onedrive"`` — a user's OneDrive (requires ai-parrot[msgraph])` | `filemanager.py:748` | 1 |
| `packages/ai-parrot/src/parrot/tools/filemanager.py` | MODIFY | `                ``"s3"``, ``"gcs"``, ``"sharepoint"``, ``"onedrive"``.` | `filemanager.py:773` | 1 |
| `packages/ai-parrot/src/parrot/tools/filemanager.py` | MODIFY | `        else:  # s3, gcs, sharepoint, or onedrive` (inside `FileManagerToolkit._create_manager`, after `    def _create_manager(` at :822) | `filemanager.py:847` | 2 (ambiguous — use the `class FileManagerToolkit` context) |
| `packages/ai-parrot/src/parrot/tools/filemanager.py` | MODIFY | `    _DRIVE_RELATIVE_BACKENDS = frozenset({"sharepoint", "onedrive"})` (inside `class FileManagerToolkit`, followed by `    def _storage_path(` at :866) | `filemanager.py:864` | 2 (ambiguous — use the `class FileManagerToolkit` context) |
| `packages/ai-parrot-tools/src/parrot_tools/google/__init__.py` | MODIFY | `from .lyria import LyriaToolkit` | `parrot_tools/google/__init__.py:11` | 1 |
| `packages/ai-parrot-tools/src/parrot_tools/google/__init__.py` | MODIFY | `    "LyriaToolkit",` | `parrot_tools/google/__init__.py:22` | 1 |
| `packages/ai-parrot/pyproject.toml` | MODIFY | `agents = [` (new `gdrive = [` block inserted before it) | `pyproject.toml:406` | 1 |
| `packages/ai-parrot/pyproject.toml` | MODIFY | `    "ai-parrot[agents,images,llms,integrations,db,bigquery,pdf,ocr,audio,finance,flowtask,reddit,mcp,charts,docling,visualizations,rust,msgraph]",` (inside `all = [` at :886; `all = [` itself occurs 2× — :886 and `all-fast = [` :894) | `pyproject.toml:887` | 1 |
| `packages/ai-parrot/tests/interfaces/test_file_shim.py` | MODIFY | `def test_no_msgraph_leak_on_import():` | `test_file_shim.py:43` | 1 |
| `packages/ai-parrot/tests/interfaces/test_file_shim.py` | MODIFY | `def test_parrot_tools_file_shim_parity():` (new tests appended after the factory-native test that follows it) | `test_file_shim.py:151` | 1 |
| `packages/ai-parrot/tests/tools/test_filemanager_batch_ops.py` | MODIFY | `def test_storage_path_is_drive_relative_for_graph_and_unchanged_otherwise():` | `test_filemanager_batch_ops.py:170` | 1 |

Files explicitly NOT touched: `packages/ai-parrot/src/parrot/interfaces/file/batch.py`,
`packages/ai-parrot/src/parrot/interfaces/file/sharepoint.py`, `.../file/onedrive.py`,
`packages/ai-parrot-tools/src/parrot_tools/google/base.py`, `.../google/calendar.py`,
`.../google/tools.py`, `packages/ai-parrot-tools/src/parrot_tools/o365/*`,
`.venv/.../navigator/utils/file/*` (upstream).

---

## 7. Implementation Notes & Constraints

> Architecture decisions stay with the thinking model. A delegated
> implementation may only express a decision already recorded here and in
> the TASK's implementation blocks — it must never invent an API, choose a
> file, or resolve an open design question.

### Patterns to Follow
- **S3/Graph parity first**: `_prefixed` / `_unprefixed` / `_make_metadata` / `upload_file_from_bytes` / `setup` mirror `gcs.py:120-149, 507-527` and `graph.py:245-305, :796-802, :1113-1126`; when in doubt about a return value, do what S3 does (`download_file` to `BinaryIO` returns `Path(source)`).
- **One session per manager**: never call `GoogleClient.execute_api_call` (it re-discovers per call, `google.py:705-769`); every Drive call goes through the `DriveClient` opened in `connect()` / `_ready()`.
- **Lazy Google imports**: `gdrive.py` imports `parrot.interfaces.google` only inside `connect()` / `adopt_client()` (guarded by `TYPE_CHECKING` at module level) — `google.py:23-31` loads selenium / playwright / webdriver_manager / redis. The shims only import `gdrive` from `__getattr__`. `parrot_tools.google.drive` may import `GoogleClient` at module level (the package already does, `base.py:12`).
- **Tests never build a real `GoogleClient`**: `_gdrive_fakes.make_google_client` uses the `_bare` pattern (`_graph_fakes.py:620`) and `adopt_client`; `connect()` branch tests monkeypatch `gdrive.GoogleClient` with a recording fake.
- **Auth**: reproduce `GoogleBaseTool._get_client` branch-for-branch (`base.py:110-135`); the `cached` fallback triggers only on the exact `"User credentials not available"` `RuntimeError`; `connect()` idempotent; `adopt_client()` requires `client.is_authenticated`.
- **`q` grammar**: always `trashed = false`; escape with `_escape_q`; one `files_list` per segment with `orderBy="modifiedTime desc"`; never `name contains` for exact resolution.
- **Shared-drive flags**: `_list_params()` is the single place that adds `supportsAllDrives` / `includeItemsFromAllDrives` / `corpora` / `driveId`; every `DriveClient` call takes its params from it.
- **Uploads**: multipart via aiogoogle below the threshold (`upload_file=` for `Path`, `pipe_from=` async iterator of `chunk_size` reads for `BinaryIO`); resumable session above it through `send_raw` with `Request(method="POST", url=RESUMABLE_URL, headers={"X-Upload-Content-Type", "X-Upload-Content-Length"}, json=metadata)` then `Request(method="PUT", url=session_url, headers={"Content-Range", "Content-Length"}, data=chunk)`; `raise_for_status=False` on PUTs so 308 is inspectable; resume offset from the `Range: bytes=0-N` header.
- **Retry policy**: one `_retrying(idempotent=)` policy (`graph.py:450-468` shape) over `HTTPError.res.status_code`; session POST, `files.copy`, `permissions.create` run with `idempotent=False`.
- **Errors**: `FileNotFoundError` for 404 on reads, `PermissionError` for 401/403, `FileExistsError` for `conflict_behavior="fail"`, `ValueError` for bad paths / bad chunk sizes / missing sharing fields, `GoogleDriveFileManagerError(status_code=…)` otherwise; never let `aiogoogle.excs.HTTPError` escape a public method.
- **Batch engine**: copy the AC8 semantics from `graph.py:1024-1111` (Semaphore, `gather(return_exceptions=True)`, input order, first 401/403 sets an `asyncio.Event` that short-circuits pending items as `skipped`, `attempts=0`).
- **Toolkit**: `tool_prefix = "gdrive"`, `auto_open = True`; response dicts are plain JSON-able dicts (no Pydantic objects, no `Path`), `modified_at` ISO strings — the `FileManagerToolkit.list_files` shape (`filemanager.py:923-938`).
- **M5 relocation is a pure move**: identical class bodies, `graph.py` keeps `_GuardedFileServingExtension` as an alias, no test in the FEAT-603 suites is edited.
- Google-style docstrings, strict typing, `self.logger = logging.getLogger(__name__)`, aiohttp only (aiogoogle's transport), Pydantic v2, black 120.
- **Worktree testing**: `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-tools/src` before `pytest` inside a worktree (`.claude/rules/worktree-management.md` §4).

### Known Risks / Gotchas
- **`GoogleClient.__init__` needs credentials or `GOOGLE_CREDENTIALS_FILE`** (`google.py:412-420` raises `RuntimeError`) and creates an `aioredis` client — construct it only in `connect()`; document `REDIS_HISTORY_URL` as a soft requirement (connection is lazy).
- **`GoogleClient.close()` does not close Redis or sessions** (`google.py:1051-1054`); the manager's `close()` closes the `DriveClient` session itself and, for an owned client, also `await client.redis.aclose()` when `client.redis` is set (guarded with `contextlib.suppress`).
- **Service-account My Drive quota**: a service account's own My Drive may reject uploads in some tenants; the docs steer service accounts to shared drives or folders shared with the SA (proposal C15 — unverified in-repo, verified only by the live suite).
- **Duplicate names**: Drive allows same-name siblings; `replace` updates the newest match only and leaves older duplicates in place — documented, and `rename` never collides with a trashed item (`trashed = false` in every `q`).
- **Workspace-native files** have no `size` and cannot be downloaded with `alt=media`; `list_files` reports `size=0` + Google MIME; `download_file` raises with the export follow-up (§8 Q2).
- **`pipe_to` contract**: aiogoogle awaits `pipe_to.write(chunk)` (`aiohttp_session.py:74-76`) — a sync `BinaryIO` must be wrapped by `_AsyncSink`; passing the raw stream fails at runtime.
- **`pipe_from` needs a known size for multipart**: for `BinaryIO` sources the manager measures `seek(0, 2)` / `tell()` up front and rewinds; unseekable streams are read into memory only below the threshold and refused above it (`ValueError`).
- **`aiogoogle==5.17.0` pins** in the `agents` bundles (`pyproject.toml:432, 483, 518`) vs installed 5.19.0 — the new extra uses `>=5.17,<6`; do not edit the bundles (AC17 test asserts the pin is still there).
- **403 rate limits**: Drive signals quota exhaustion as 403 with `errors[0].reason` in `{userRateLimitExceeded, rateLimitExceeded}` — such a 403 is re-classified `throttled` and retried; any other 403 is `auth` (batch remainder skipped), exactly like Graph. Decision recorded here; tested.
- **Resumable chunk size** must be a multiple of 256 KiB except the last chunk; the constructor validates it.
- **`FileServingExtension` buffers whole objects** (FEAT-603 §7); the `serving_max_bytes` guard applies (AC22).
- **pytest hang after summary** (leaked non-daemon threads) — wrap full-suite runs in `timeout -s KILL`.
- **Shared checkout hazard**: another session switched the primary checkout's branch and removed a worktree during this spec run; implementation must happen in the feature worktree only, pushed early.

### External Dependencies
| Package | Version | Reason |
|---|---|---|
| `aiogoogle` | `>=5.17,<6` (installed 5.19.0) | Drive v3 discovery, auth managers, media upload/download, raw `Request` sending |
| `aiofiles` | `>=23.0` (24.1.0) | chunked local reads/writes (already in the `agents` bundle, `pyproject.toml:779`) |
| `aiohttp` | existing (3.14.3) | aiogoogle transport; nothing direct |
| `navigator-api` | `>=3.2.2` (4.0.0) | `FileManagerInterface`, `FileMetadata`, `FileServingExtension` |
| `pydantic` | v2 (existing) | `DriveEntry`, batch models |
| `redis` | existing | `GoogleClient` user-session cache (constructor side effect) |

---

## 8. Open Questions

> Questions that must be resolved before or during implementation.

- [x] Which Drive targets in v1? — *Resolved in proposal (U1)*: My Drive + shared drives via optional `shared_drive_id`; domain-wide delegation out of scope.
- [x] How do paths map onto Drive's id-addressed model? — *Resolved in proposal (U2)*: path-based like S3/Graph — segment resolver + per-manager cache, deterministic first match, upload `conflict_behavior` replace | fail | rename.
- [x] What does `get_file_url()` return? — *Resolved in proposal (U3)*: `webViewLink` with no permission change; explicit sharing via `create_sharing_link(scope, role, expiry, email_address)`.
- [x] Which agent-facing surface? — *Resolved in proposal (U4)*: `FileManagerToolkit(manager_type="gdrive")` + net-new `GoogleDriveToolkit`; `files.export` out of scope.
- [x] Promote `GoogleClient.get_drive_client()` to a live `DriveClient`? — *Resolved in proposal (U5, defaulted)*: yes — no callers exist.
- [x] Resumable uploads above ~5 MiB? — *Resolved at spec time*: aiogoogle builds the `ResumableUpload` object but no session code speaks the protocol (`sessions/` grep) → `gdrive.py` drives the session through `DriveClient.send_raw` (§2, §3 M4).
- [x] Where do `DriveEntry` / the guarded serving extension live? — *Resolved at spec time*: relocated verbatim to `parrot/interfaces/file/entries.py` with `graph.py` re-exports (M5).
- [x] Delete semantics? — *Resolved at spec time*: trash by default (recycle-bin parity with Graph), `permanent_delete=True` for `files.delete`.
- [x] Default `create_sharing_link` scope? — *Resolved at spec time*: `scope="user"` (requires `email_address`) — the least-privilege default; `anyone` must be requested explicitly.
- [ ] Q1. Live-gate tenant: confirm the Drive folder / shared drive the live suite may write to under `parrot-live/<uuid>/`, and that `PARROT_LIVE_GDRIVE`, `PARROT_LIVE_GDRIVE_ROOT_ID` / `PARROT_LIVE_GDRIVE_ROOT_PATH`, `PARROT_LIVE_GDRIVE_SHARED_DRIVE`, `PARROT_LIVE_GDRIVE_SHARE_EMAIL` are acceptable knob names (test-only env vars). — *Owner: Jesus* (M9 proceeds with the proposed names; only the target values block AC21).
- [ ] Q2. Workspace export follow-up: add `export_file(path, mime)` (`files.export`) to the manager and a `gdrive_export_file` tool in a later feature? — *Owner: Jesus* (does not block; v1 raises a clear error).
- [ ] Q3. Batch-engine extraction follow-up: move the AC8 engine (`_run_batch`, `_reject_shared_streams`, `_classify`) into a `BatchRunnerMixin` in `batch.py` shared by Graph and Drive once both are stable? — *Owner: Jesus* (does not block; v1 duplicates ≈70 lines deliberately).
- [ ] Q4. Domain-wide delegation (`subject=` on `ServiceAccountCreds`, `creds.py:259`) as a later constructor kwarg? — *Owner: Jesus* (does not block).

---

## 9. Design Research Cross-Check

> Independent design opinion from the `codex` seat over the **accepted exploration
> doc** (never over this spec). Model: `gpt-5.6-luna` · Status: skipped (model probe failed
> for gpt-5.6-luna: HTTP 401 Unauthorized from the Codex backend — the API key the CLI uses
> under `--ignore-user-config` was rejected; codex-cli 0.157.0; three probe attempts)
> · Transcript: `sdd/state/FEAT-608/design_research/` (brief rendered, no suggestions produced)
> Every row is a suggestion the reviewer made; the disposition is the spec author's
> call (CONFIRM = folded into the spec, REJECT = reason recorded, ESCALATE = §8 question).

| # | Suggestion (kind) | Disposition | Reason | Landed in |
|---|---|---|---|---|
| — | — | — | no suggestions (seat skipped) | — |

Summary: **0** confirmed · **0** rejected · **0** escalated. Re-run `/sdd-spec google-drive-interface`'s
§3b once the Codex credential is fixed if an external opinion is wanted before `/sdd-task`.

---

## Worktree Strategy

- **Isolation**: ONE feature worktree for FEAT-608 (`feat-FEAT-608-google-drive-interface`, from `origin/dev`); the `sdd-coder` engine gives each task its own sub-worktree inside it.
- **Module dependency graph** (edge = import or contract dependency, with evidence):
  - M0 → (none) — fakes stand in for `DriveClient`; no source import of M1
  - M1 → (none) — additive change to `google.py`
  - M2 → M1 (`GoogleClient.get_drive_client` → `DriveClient`; `aiogoogle_credentials`), M5 (`from .entries import DriveEntry, GuardedFileServingExtension`)
  - M3 → M2 (methods on the same class); M4 → M2, M3 (same class; `_iter_children` for conflict checks)
  - M5 → (none) — behaviour-neutral relocation, gated by the FEAT-603 suites
  - M6 → M2 (lazy target `parrot.interfaces.file.gdrive` must import)
  - M7 → M2, M3, M4 (`GoogleDriveFileManager` public surface)
  - M8 → (none) for packaging; docs reference M2–M7 names (written last)
  - M9 → M2, M3, M4; M10 → M1, M2, M5, M6, M7
  - **No edge**: M0, M1, M5, M8-packaging are mutually independent → run concurrently from day one; M6 ‖ M7 after M4; M9 ‖ M10 last.
- **Shared files**: `packages/ai-parrot/src/parrot/interfaces/file/gdrive.py` is built by M2 → M3 → M4 (serialized, same class). `packages/ai-parrot/src/parrot/interfaces/google.py` is M1 only. `graph.py` is M5 only. `parrot/tools/filemanager.py`, both shims and `test_file_shim.py` are M6 only. `parrot_tools/google/__init__.py` is M7 only.
- **Exclusive resources**: `packages/ai-parrot/pyproject.toml` (M8) — its task is `parallel: false` (no `uv.lock` regeneration inside the worktree; the main-checkout operator installs the extra). The live suite (M9) shares one real Drive — `parallel: false`, manual run only.
- **Cross-feature dependencies**: FEAT-603 is merged (PR #1501) — none blocking. No open spec touches `parrot/interfaces/google.py`, `parrot/interfaces/file/`, `parrot/tools/filemanager.py` or `parrot_tools/google/`.
- **Suggested lanes**: Wave 1 = {M0, M1, M5, M8-packaging} ; Wave 2 = M2 ; Wave 3 = M3 → M4 ; Wave 4 = {M6, M7} ; Wave 5 = {M9 (manual live run), M10, M8-docs}.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-09-26 | Jesus Lara (with Claude) | Initial draft from the accepted proposal (U1–U5 carried forward); spec-time resolutions for resumable uploads, `entries.py` relocation, delete/sharing defaults; design research skipped (Codex 401) |
