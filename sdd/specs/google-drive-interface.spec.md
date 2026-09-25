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
  to end: `graph.py:19-32, 42`). It shares only the backend-neutral `batch.py` models
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
# parrot/interfaces/file/entries.py  (new, M5 — Graph-free; moved verbatim from graph.py:62-107)
class DriveEntry(BaseModel):          # unchanged fields: id, name, path, is_folder, size, modified_at, web_url, content_type
class GuardedFileServingExtension(FileServingExtension):   # was graph.py:62 `_GuardedFileServingExtension`
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
    """Base error; carries ``status_code`` when known (mirrors GraphFileManagerError, graph.py:117-129)."""
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
- **Responsibility**: in-memory Google Drive plus a fake `Aiogoogle` / discovered-API pair
  that the manager's `DriveClient` drives through the same coroutine names as the real one,
  so M2–M4, M6, M7 and M10 tests never construct a real `GoogleClient` (its constructor
  needs Redis + credentials, `google.py:299-302, 412-420`). Mirrors `_graph_fakes.py`
  (`FakeGraphClient.fail_next`, `_bare`, `make_sharepoint_client` — `_graph_fakes.py:178,
  207, 620, 644`).
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
      ``files_list`` honours q (parents / name / name contains / mimeType / trashed), orderBy, pageSize and pageToken
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
  from navigator.utils.file import FileManagerInterface, FileMetadata            # verified: graph.py:38; abstract.py:16, :36
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
          """Store configuration; NO network I/O and NO GoogleClient construction (graph.py:155-212 parity).
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
          """Ensure DriveClient is open and root resolved; returns root id (graph.py:343 parity)."""

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
          """Same semantics as graph.py:400-427 over ``error.res.headers``."""
      def _map_error(self, exc: BaseException, *, path: str) -> BaseException:
          """404 → FileNotFoundError; 401/403 → PermissionError; 409 → FileExistsError; else GoogleDriveFileManagerError(status_code)."""
      async def _retrying(self, op: Callable[[], Awaitable[Any]], *, label: str, idempotent: bool = True) -> Tuple[Any, int]:
          """graph.py:439-457 policy: RETRYABLE_STATUS, Retry-After capped 60 s, 2**(n-1) backoff, ``max_retries``; never for non-idempotent ops."""
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
      """Returns ``webViewLink`` (S3 parity; graph.py:785-791)."""
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
  def _reject_shared_streams(self, objs: List[Any]) -> None: ...        # graph.py:1003-1011 contract (ValueError)
  async def _run_batch(self, items: List[Tuple[Any, Any]], run_one: Callable[[int, Any, Any], Awaitable[FileMetadata]]) -> List[BatchItemResult]:
      """AC8 contract re-implemented from graph.py:1013-1082: Semaphore(max_concurrency), results in input order, never raises
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
- **Responsibility**: move `DriveEntry` (`graph.py:93-107`) and `_GuardedFileServingExtension`
  (`graph.py:62-91`, renamed `GuardedFileServingExtension`) verbatim into a module that
  imports neither msgraph nor aiogoogle, and re-import them in `graph.py` under the old
  names so `graph.DriveEntry` and `graph._GuardedFileServingExtension` keep resolving
  (the O365 tools import `DriveEntry` from `graph` — `parrot_tools/o365/{sharepoint,onedrive}.py`).
- **Depends on**: nothing in this spec
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot/src/parrot/interfaces/file/entries.py  (new)
  from navigator.utils.file.web import FileServingExtension   # verified: graph.py:39; web.py:28
  class DriveEntry(BaseModel): ...                             # verbatim from graph.py:93-107
  class GuardedFileServingExtension(FileServingExtension): ... # verbatim from graph.py:62-91

  # packages/ai-parrot/src/parrot/interfaces/file/graph.py  (modifies graph.py:62 and :93)
  from .entries import DriveEntry, GuardedFileServingExtension
  _GuardedFileServingExtension = GuardedFileServingExtension   # keeps graph.py:1102-1115 setup() and tests unchanged
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

<!-- CONTINUE -->
