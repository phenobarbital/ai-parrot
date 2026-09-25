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
tags: [filemanager, sharepoint, onedrive, microsoft-graph, o365, storage]
---

# Feature Specification: SharePoint & OneDrive FileManager

**Feature ID**: FEAT-603
**Date**: 2026-09-25
**Author**: Jesus Lara (with Claude)
**Status**: approved
**Target version**: 1.1.0 (next minor after 1.0.6)
**Brainstorm**: `sdd/proposals/sharepoint-filemanager.brainstorm.md` (accepted, Option B)

---

## 1. Motivation & Business Requirements

> Why does this feature exist? What problem does it solve?

### Problem Statement

AI-Parrot has a uniform storage contract — `FileManagerInterface` from
`navigator.utils.file` (navigator-api 4.0.0), implemented by
`LocalFileManager`, `TempFileManager`, `S3FileManager` and `GCSFileManager` —
that agents, `FileManagerToolkit`, report persistence and artifact storage all
program against. Microsoft SharePoint document libraries and OneDrive drives
are **not** behind that contract. The repo carries two parallel,
non-conforming surfaces instead:

- `parrot/interfaces/sharepoint.py::SharepointClient` and
  `parrot/interfaces/onedrive.py::OneDriveClient` — Graph-SDK clients with
  flowtask-style, stateful method sets (`upload_files`, `file_search`,
  `download_found_files`, `file_lookup`) that configure the target via
  instance attributes (`client.directory`, `client.site`) rather than path
  arguments, and that share almost no method names with each other.
- `parrot_tools/o365/{sharepoint,onedrive}.py` tools that re-implement
  listing/searching/downloading **directly on the raw Graph client** because
  the clients above do not expose those operations in a reusable shape.
  Worse, `O365Tool._get_client()` constructs a plain `O365Client`
  (`parrot_tools/o365/base.py:148`), which has no `verify_sharepoint_access`
  / `_resolve_drive` / `file_list`, so the List/Search/Download/Upload tools
  are typed against a client class they never receive.

Consequences:

1. Nothing that speaks `FileManagerInterface` (the `file_manager` tool,
   `FileManagerToolkit`, `ReportPersistenceMixin`, artifact stores) can target
   SharePoint or OneDrive; every consumer needs bespoke O365 code.
2. Bytes-in-memory uploads (agent-generated reports, charts, exports) have no
   path to SharePoint at all — `SharepointClient.upload_files` only takes
   local filenames.
3. The flowtask sibling of `SharepointClient` has drifted ahead (it gained
   `drive: {type, user}` OneDrive targeting via `_ensure_drive_config` /
   `_resolve_user_drive`), while ai-parrot's `O365Client` gained
   `set_auth_mode`, `is_app_only`, `get_user_context` and an async `close()`
   that flowtask lacks. The two diverge in both directions.
4. Batch upload/download, sharing-link generation and server-side search exist
   as fragments across the clients and tools but never as a single,
   documented, testable API.

**Who is affected**: agent authors (want
`FileManagerToolkit(manager_type="sharepoint")`), pipeline/flowtask users
(need a stable, mockable client), and the O365 toolkit maintainers
(currently duplicating drive-item logic in every tool).

**Why now**: FEAT-539 landed delta enumeration for both drives with a robust
retry/validation helper (`parrot_tools/o365/delta.py`); the Graph plumbing is
mature, and the missing piece is the uniform manager façade.

### Goals

- G1. Implement `FileManagerInterface` **once** for Microsoft Graph drives in an
  abstract `GraphDriveFileManager`, with `SharePointFileManager` (site +
  library) and `OneDriveFileManager` (user or `me`) as thin subclasses that
  differ only in drive resolution. Paths are drive-relative, `prefix + key`
  exactly like S3.
- G2. Compose the **existing** `SharepointClient` / `OneDriveClient` /
  `O365Client` for auth (app-only client credentials, delegated/cached
  interactive, on-behalf-of, username/password), site/drive/folder
  resolution and resumable upload sessions. No second Graph auth stack.
- G3. Port flowtask's `_resolve_user_drive` into `OneDriveClient` so any
  user's OneDrive (`users/{upn|id}/drive`) or the signed-in user's (`me/drive`)
  can be targeted. Do **not** port the `drive.type=onedrive` shim into
  `SharepointClient`.
- G4. Extensions with S3 parity and beyond: `upload_file_from_bytes`,
  batch `upload_files` / `download_files` with per-item results that never
  raise mid-batch, server-side `find_files`, `get_file_url` as a Graph
  `createLink` sharing link, folder/rename hooks, and `setup(app, route)`
  HTTP serving through `FileServingExtension`.
- G5. Register the managers everywhere a file manager is discoverable:
  `parrot.interfaces.file` (+ `parrot_tools.file`) lazy re-exports,
  `FileManagerFactory` keys `sharepoint` / `onedrive`,
  `FileManagerTool` / `FileManagerToolkit` `manager_type` literals, and three
  new agent-facing operations `find`, `batch_upload`, `batch_download`
  (with a generic fallback for backends lacking the batch methods).
- G6. Refactor the O365 List/Search/Download/Upload tools (both drives) to
  delegate to the managers, preserving tool names, args and response dict
  shapes; leave the FEAT-539 Delta tools and `delta.py` untouched.
- G7. Packaging + docs: a dedicated `ai-parrot[msgraph]` extra included in
  `all`; document application/delegated permissions for the managers.
- G8. Verification: mocked Graph request-builder tests in CI plus an opt-in
  `@pytest.mark.live` suite gated on environment variables, run manually
  before `/sdd-done`.

### Non-Goals (explicitly out of scope)

- No changes to `SharepointClient`'s public methods (`upload_files`,
  `file_search`, `download_found_files`, `file_lookup`, `upload_folder`,
  `create_subscription`) — flowtask and the Delta tools call them.
- No edits to `parrot_tools/o365/delta.py` or the `DeltaSharePointFilesTool`
  / `DeltaOneDriveFilesTool` classes (FEAT-539 ownership); this feature only
  imports from `delta.py`.
- No upstreaming into navigator-api (brainstorm Option D rejected) and no
  path-encoded single-class locator design (Option C rejected) — see
  `sdd/proposals/sharepoint-filemanager.brainstorm.md`.
- No removal of the unused `import httpx` lines in the two clients
  (`sharepoint.py:11`, `onedrive.py:10`); new modules simply never import it.
- No flowtask changes (separate repository; a follow-up may retire its
  `drive.type=onedrive` shim in favour of `OneDriveFileManager`).
- No group drives / "shared with me" / drive-by-id targeting in v1 (the base
  makes them a future subclass, not a v1 deliverable).
- No E2E gate (`parrot e2e`) surface — the frontmatter `e2e` key is omitted.

---

## 2. Architectural Design

### Overview

Microsoft Graph models a SharePoint document library and a user's OneDrive as
the same resource: a **drive** addressed by `/drives/{drive-id}`, whose items
are addressed by `/drives/{drive-id}/items/root:/<path>:`. The design exploits
that symmetry:

- **`GraphDriveFileManager`** (`parrot/interfaces/file/graph.py`, abstract) owns
  every drive-item operation of `FileManagerInterface` plus the extensions,
  written once against `client.graph_client.drives.by_drive_id(drive_id)`
  request builders. It has exactly two abstract hooks: `_build_client()` (which
  `O365Client` subclass to instantiate and how) and `_resolve_drive_id()`
  (how to find the drive). Everything else — path prefixing, colon-form item
  references, `FileMetadata` mapping, small vs. resumable uploads, streaming
  downloads, async copy polling, `createLink`, search-with-fallback, the batch
  engine, HTTP serving — lives here.
- **`SharePointFileManager(site, library="Documents", ...)`** builds a
  `SharepointClient` with `credentials={..., "site": site}` and resolves the
  drive through `verify_sharepoint_access()` → `_resolve_drive(library)`
  (sub-site detection and the `"Shared Documents"` → `Documents` alias come
  for free from the client).
- **`OneDriveFileManager(user="me", ...)`** builds a `OneDriveClient` and
  resolves the drive through the newly ported `_resolve_user_drive(user)`
  (`me/drive` under delegated auth, `users/{id}/drive` otherwise).
- **Authentication** reproduces `O365Tool._get_client()` exactly
  (`parrot_tools/o365/base.py:111-197`): `auth_mode` selects
  `acquire_token` (direct / client credentials, run in an executor),
  `acquire_token_on_behalf_of(user_assertion)` (on_behalf_of),
  `interactive_login` then `ensure_interactive_session` (delegated), or
  `ensure_interactive_session` (cached). Username/password (ROPC) is reached by
  passing `username`/`password` in `credentials`, which
  `O365Client._create_credential` already picks up. Credentials fall back to
  `SHAREPOINT_*` (SharePoint) / `O365_*` (OneDrive) conf defaults through the
  clients' existing `_default_*` handling.
- **Decided defaults** (from the brainstorm and its follow-ups): upload
  `conflict_behavior="replace"` (S3 overwrite parity; `fail` / `rename`
  selectable); `delete_file` is a Graph DELETE (recycle bin); sharing links
  are created by the extension method `create_sharing_link(path, *,
  link_type, scope, expiry)` and `get_file_url(path, expiry)` keeps the exact
  interface signature as a wrapper over it with the constructor defaults
  `link_type="view"`, `link_scope="organization"`,
  `expirationDateTime = now + expiry` when `expiry > 0` (`expiry <= 0` → no
  expiration; unsupported-expiration tenants → warning + non-expiring link;
  forbidden anonymous scope → `PermissionError`) (design research S3); batch
  `max_concurrency=5`, `max_retries=3`; `manager_name` values
  `"sharepointfile"` / `"onedrivefile"` (S3's `"s3file"` convention).
- **Listing semantics** (S8): `list_files` returns **files only**
  (`FileMetadata` has no folder flag); the extension `list_entries(path)`
  returns `DriveEntry` rows with `is_folder` / `id` for callers that need
  folders (the O365 List tools). Both follow `@odata.nextLink` to the end
  (S4) — `find_files` / search likewise, applying filters across all pages
  and `max_results` only after filtering. SharePoint tool paths are
  library-relative, which is exactly the manager's drive-relative path with
  `prefix=""`; no path rewriting is needed in the tool refactor.
- **Outbound URLs** (S6): the only URLs the manager dereferences with
  aiohttp are the upload-session `uploadUrl`, the copy `Location` monitor
  and the item `@microsoft.graph.downloadUrl`. Each is validated by
  `_validate_graph_url` (https, host in `ALLOWED_ORIGINS` — the Graph
  origins from `delta.py` plus `*.sharepoint.com` / `*-my.sharepoint.com` /
  `*.files.1drv.com` — no redirects followed) before use, is never logged,
  and is never sent the bearer token (all three are pre-authenticated by
  Graph).
- **Site semantics** (S2): `SharepointClient._detect_and_resolve_subsite`
  reads and mutates the hidden `_srcfiles` list (`sharepoint.py:128-166`);
  the manager never populates `_srcfiles`, so that path is a no-op and the
  sub-site is expressed explicitly in `site="parent/sub"` (which
  `_resolve_site` turns into `…sharepoint.com:/sites/parent/sub`,
  `sharepoint.py:181-183`).
- **Registration**: `parrot.interfaces.file.__init__` and
  `parrot_tools.file.__init__` gain the two names as lazy attributes;
  `parrot.tools.filemanager.FileManagerFactory` resolves `sharepoint` /
  `onedrive` **locally** (they are parrot-native, not upstream), and the
  `manager_type` literals on `FileManagerTool.__init__`,
  `FileManagerToolkit.__init__` and the factory widen accordingly.
- **Agent surface**: `FileManagerToolArgs.operation` gains `find`,
  `batch_upload`, `batch_download`; `FileManagerToolkit` gains
  `find_files`, `batch_upload`, `batch_download` methods (auto-exposed as
  `fs_find_files`, `fs_batch_upload`, `fs_batch_download`). For backends
  without native batch methods the toolkit loops the single-item operation and
  builds the same per-item result list; for backends without a server-side
  `find_files` override the inherited in-memory `FileManagerInterface.find_files`
  is used.
- **O365 tools**: the eight List/Search/Download/Upload tools construct the
  matching manager from their args (site/library/folder or file path) and
  the tool's `credentials` / `auth_mode` / `user_assertion`, call it, and
  re-shape the result into the existing response dicts. This also fixes the
  `O365Client`-vs-`SharepointClient` mismatch noted in §1.

### Component Diagram

```
FileManagerToolkit / FileManagerTool            SharePointToolkit / OneDriveToolkit
   (manager_type="sharepoint"|"onedrive",           (List/Search/Download/Upload tools)
    + find/batch_upload/batch_download)                       │
        │  FileManagerFactory.create()                        │ build manager from args
        ▼                                                     ▼
 ┌──────────────────────────────────────────────────────────────────────┐
 │ GraphDriveFileManager(FileManagerInterface)   parrot/interfaces/file/graph.py │
 │  list/upload/download/copy/delete/exists/metadata/create              │
 │  folders + rename · find_files · get_file_url(createLink)             │
 │  upload_file_from_bytes · upload_files/download_files (BatchItemResult)│
 │  setup(app, route) → FileServingExtension                            │
 │  hooks: _build_client() · _resolve_drive_id()                         │
 └──────────────┬──────────────────────────────────┬────────────────────┘
                │                                  │
  SharePointFileManager                    OneDriveFileManager
   (site, library, prefix)                  (user|"me", prefix)
                │                                  │
        SharepointClient                     OneDriveClient
   verify_sharepoint_access                 _resolve_user_drive (NEW, ported)
   _resolve_site/_resolve_drive             _resolve_drive / _ensure_folder
   _ensure_folder / upload session          upload session (bytes + path)
                └──────────────┬───────────────────┘
                          O365Client
            auth modes · graph_client (GraphServiceClient) · close()
                               │
                 msgraph-sdk 1.63 (kiota RetryHandler) + aiohttp (chunk PUT,
                 copy monitor poll, downloadUrl stream)
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `navigator.utils.file.FileManagerInterface` / `FileMetadata` | extends | `GraphDriveFileManager` subclasses it; all abstract + optional folder/rename methods implemented |
| `navigator.utils.file.web.FileServingExtension` | uses | `setup(app, route, base_url)` mirrors `S3FileManager.setup` (`s3.py:613`) |
| `parrot.interfaces.o365.O365Client` | uses | auth modes, `graph_client`, `set_auth_mode`, `is_app_only`, async `close()` |
| `parrot.interfaces.sharepoint.SharepointClient` | uses (unchanged) | `verify_sharepoint_access`, `_resolve_drive(library)`, `_ensure_folder`, `_create_upload_session`, `_upload_large_file`, `_pattern_is_api_safe` |
| `parrot.interfaces.onedrive.OneDriveClient` | modifies (additive) | new `_resolve_user_drive(user)` + `onedrive_user` / `_user_drive_info` attributes; `_ensure_folder`, `_create_upload_session`, `_upload_large_file`, `_upload_large_file_content` reused |
| `parrot.interfaces.file` shim | modifies | `__all__` + `_LAZY_MANAGERS` gain both managers (targets are parrot modules) |
| `parrot_tools.file` shim | modifies | lazy branch widened to the two new names |
| `parrot.tools.filemanager.FileManagerFactory` | modifies | local `_PARROT_NATIVE` map for `sharepoint` / `onedrive`; literal widened |
| `parrot.tools.filemanager.FileManagerTool` / `FileManagerToolArgs` | modifies | literal widened; `operation` gains `find`, `batch_upload`, `batch_download`; new arg fields |
| `parrot.tools.filemanager.FileManagerToolkit` | modifies | literal widened; `_OP_TO_METHOD` gains three ops; three new public async methods |
| `parrot_tools.o365.sharepoint` (List/Search/Download/Upload) | modifies | `_execute_graph_operation` bodies delegate to `SharePointFileManager`; Delta tool untouched |
| `parrot_tools.o365.onedrive` (List/Search/Download/Upload) | modifies | same with `OneDriveFileManager`; Delta tool untouched |
| `parrot_tools.o365.delta` | uses (unchanged) | `_status_code_of`, `_retry_after_seconds`, `RETRYABLE_STATUS_CODES` reused by the batch engine |
| `parrot.conf` | uses | `SHAREPOINT_APP_ID/APP_SECRET/TENANT_ID/TENANT_NAME/SITE_ID`, `O365_CLIENT_ID/CLIENT_SECRET/TENANT_ID` |
| `packages/ai-parrot/pyproject.toml` | modifies | new `msgraph` extra; added to `all` |
| `docs/integrations/office365-oauth2.md` | modifies | permissions for the managers; new `docs/interfaces/graph-filemanager.md` |
| `packages/ai-parrot/tests/interfaces/test_file_shim.py` | modifies | leak/lazy/factory tests extended |
| `packages/ai-parrot-tools/tests/test_o365_delta_tools.py::TestBundleRegistration` | depends on | must stay green (bundle toolkits unchanged) |

### Data Models

```python
# parrot/interfaces/file/graph.py
from datetime import datetime
from typing import Literal, Optional
from pydantic import BaseModel, ConfigDict, Field
from navigator.utils.file import FileMetadata          # dataclass, verified: navigator/utils/file/abstract.py:16

ConflictBehavior = Literal["replace", "fail", "rename"]
LinkType = Literal["view", "edit"]
LinkScope = Literal["organization", "anonymous", "users"]
AuthMode = Literal["direct", "on_behalf_of", "delegated", "cached"]   # same strings as O365AuthMode (base.py:24-27)

BatchState = Literal["succeeded", "failed", "skipped"]      # skipped = not attempted because the batch aborted (S10)
BatchErrorCode = Literal["not_found", "permission_denied", "throttled", "timeout", "auth", "conflict", "invalid_path", "io", "unknown"]

class BatchItemResult(BaseModel):
    """Outcome of one item inside ``upload_files`` / ``download_files``.

    A batch never raises for a single item: failures are reported here.
    ``attempts`` counts tries including retries on 429/503/504; a skipped item has ``attempts=0``.
    """
    model_config = ConfigDict(arbitrary_types_allowed=True, extra="forbid")
    index: int                       # position in the input sequence (identity; input order is preserved)
    source: str                      # local path / "<bytes>" / drive path
    destination: str                 # drive path / local path / "<stream>"
    state: BatchState
    ok: bool                         # == (state == "succeeded")
    metadata: Optional[FileMetadata] = None
    error: Optional[str] = None
    error_code: Optional[BatchErrorCode] = None
    status_code: Optional[int] = None
    attempts: int = Field(default=1, ge=0)

class BatchSummary(BaseModel):
    """Aggregate returned by the toolkit's batch tools (agent-facing)."""
    model_config = ConfigDict(extra="forbid")
    total: int
    succeeded: int
    failed: int
    skipped: int
    aborted: bool = False            # True when an auth failure short-circuited the rest
    items: list[BatchItemResult]

class DriveEntry(BaseModel):
    """One child of a folder, including folders (``list_entries`` extension, S8)."""
    model_config = ConfigDict(extra="forbid")
    id: str
    name: str
    path: str                        # drive-relative, unprefixed
    is_folder: bool
    size: int = 0
    modified_at: Optional[datetime] = None
    web_url: Optional[str] = None
    content_type: Optional[str] = None
```

### New Public Interfaces

```python
from parrot.interfaces.file import SharePointFileManager, OneDriveFileManager   # lazy, no msgraph import at package load
from parrot.interfaces.file.graph import GraphDriveFileManager, BatchItemResult, BatchSummary

sp = SharePointFileManager(site="troc", library="Documents", prefix="reports/",
                           credentials={"client_id": ..., "client_secret": ..., "tenant_id": ..., "tenant": "troc"})
od = OneDriveFileManager(user="someone@tenant.com", credentials={...}, auth_mode="direct")
me = OneDriveFileManager(user="me", auth_mode="delegated")

await sp.list_files("2026/", "*.xlsx")                 # List[FileMetadata]
await sp.upload_file(Path("q3.xlsx"), "2026/q3.xlsx")   # FileMetadata
await sp.create_from_bytes("2026/q3.pdf", data)         # bool
await sp.upload_file_from_bytes(data, "2026/q3.pdf", "application/pdf")   # str (web_url)
await sp.download_file("2026/q3.xlsx", Path("/tmp/q3.xlsx"))              # Path
await sp.get_file_url("2026/q3.xlsx", expiry=3600)      # sharing link (organization, view) — exact interface signature
await sp.create_sharing_link("2026/q3.xlsx", link_type="edit", scope="users", expiry=0)   # extension with explicit options
await sp.list_entries("2026/")                          # List[DriveEntry] incl. folders (all pages)
await sp.find_files(keywords="q3", extension=".xlsx", prefix="2026/")
await sp.upload_files([(Path("a.csv"), "in/a.csv"), (b"...", "in/b.bin")])   # List[BatchItemResult]
await sp.download_files([("in/a.csv", Path("/tmp/a.csv"))])
sp.setup(app, route="/sp")                              # GET /sp/<path> streams through navigator

FileManagerFactory.create("sharepoint", site="troc", library="Documents")
FileManagerToolkit(manager_type="onedrive", user="me", auth_mode="cached")  # fs_* tools + fs_find_files/fs_batch_upload/fs_batch_download
```

---

## 3. Module Breakdown

> Define the discrete modules that will be implemented.
> These directly map to Task Artifacts in Phase 2.

#### Delegation-eligible modules

| Module | Eligible? | Decided patterns / exact contracts | Why not (if no) |
|---|---|---|---|
| M0: Graph test harness | yes | `FakeGraphClient` builder tree + `FakeAiohttpSession`; file layout and public names fixed in §3/§4 | — |
| M1: `GraphDriveFileManager` base | yes | full skeleton in §3; Graph endpoints, defaults, error mapping and retry rules fixed in §2/§7 | — |
| M2: `OneDriveClient._resolve_user_drive` port | yes | verbatim port of flowtask `_resolve_user_drive` with `user` parameter; wording of errors fixed | — |
| M3: `SharePointFileManager` | yes | constructor + two hooks; credential keys and client calls fixed | — |
| M4: `OneDriveFileManager` | yes | constructor + two hooks; `me` vs user rule fixed | — |
| M5: Registration (shims + factory + literals) | yes | exact edit sites in §6; `_PARROT_NATIVE` map name fixed | — |
| M6: Agent operations (`find`, `batch_upload`, `batch_download`) | yes | arg fields, op keys, method names, fallback rule and `BatchSummary` shape fixed | — |
| M7: SharePoint O365 tools refactor | yes | response dict keys preserved verbatim (§6 "Integration Points"); manager construction rule fixed | — |
| M8: OneDrive O365 tools refactor | yes | same as M7 | — |
| M9: Packaging + docs | yes | extra name `msgraph`, pins copied from `agents`; doc sections named | — |
| M10: Live gate suite | yes | env-var knobs and skip rule fixed in §4; write-scope path fixed | — |

### Module 0: Graph test harness
- **Path**: `packages/ai-parrot/tests/interfaces/_graph_fakes.py` (new)
- **Responsibility**: in-memory fake of the msgraph request-builder tree the
  base uses (`drives.by_drive_id(id).items.by_drive_item_id(ref).get() /
  .children.get() / .content.put() / .create_link.post() / .copy.post() /
  .delete() / .patch() / .search_with_q(q).get()`, `drives.by_drive_id(id).root.get()`,
  `me.drive.get()`, `users.by_user_id(u).drive.get()`), a fake
  `aiohttp.ClientSession` for chunk PUT / monitor poll / download stream, and
  fake `SharepointClient` / `OneDriveClient` objects exposing only the methods
  the managers call. Used by M1, M3, M4, M6, M7, M8 tests.
- **Depends on**: nothing in this spec
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot/tests/interfaces/_graph_fakes.py  (new)
  class FakeDriveItem:
      """Minimal DriveItem stand-in: id, name, size, web_url, folder, file (mime_type),
      last_modified_date_time, parent_reference.path, additional_data['@microsoft.graph.downloadUrl']."""

  class FakeDrive:
      """In-memory drive keyed by drive-relative path; records every Graph call in ``calls``."""
      def put_file(self, path: str, data: bytes, *, mime: str = "application/octet-stream") -> FakeDriveItem: ...
      def put_folder(self, path: str) -> FakeDriveItem: ...

  class FakeGraphClient:
      """Builder tree over one or more FakeDrive objects; raises ``FakeAPIError(status)`` on demand."""
      def __init__(self, drives: dict[str, FakeDrive], *, me_drive_id: str | None = None, user_drives: dict[str, str] | None = None) -> None: ...
      def fail_next(self, status: int, *, retry_after: float | None = None, times: int = 1) -> None: ...

  class FakeAPIError(Exception):
      """Mimics kiota APIError: ``response_status_code`` and ``response_headers``."""

  class FakeAiohttpSession:
      """Async context manager with ``put``/``get`` returning scripted status/json/bytes; records ranges."""

  def make_sharepoint_client(fake: FakeGraphClient, *, drive_id: str) -> object: ...
      """Object with graph_client, verify_sharepoint_access(), _resolve_drive(), _ensure_folder(), _create_upload_session(), close()."""
  def make_onedrive_client(fake: FakeGraphClient, *, drive_id: str) -> object: ...
  ```

### Module 1: `GraphDriveFileManager` base
- **Path**: `packages/ai-parrot/src/parrot/interfaces/file/graph.py` (new)
- **Responsibility**: the whole `FileManagerInterface` implementation over Graph
  drive items, the extensions (bytes upload, batch engine, search, sharing
  links, HTTP serving), lifecycle (`connect`/`close`/async context manager),
  path model and metadata mapping. Subclasses only supply `_build_client()` and
  `_resolve_drive_id()`.
- **Depends on**: `navigator.utils.file` (`FileManagerInterface`, `FileMetadata`,
  `FileServingExtension`), `parrot.interfaces.o365.O365Client`,
  `parrot_tools.o365.delta` helpers **only** if importable — see §7 (the base
  must not hard-depend on `ai-parrot-tools`; the two helper functions are
  re-implemented locally as `_status_code_of` / `_retry_after_seconds` with the
  same semantics, and `delta.py` is cited as the reference).
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot/src/parrot/interfaces/file/graph.py  (new)
  from navigator.utils.file import FileManagerInterface, FileMetadata      # verified: navigator/utils/file/__init__.py exports; abstract.py:16,36
  from navigator.utils.file.web import FileServingExtension                # verified: navigator/utils/file/web.py:28
  from parrot.interfaces.o365 import O365Client                            # verified: parrot/interfaces/o365.py:115

  class GraphFileManagerError(RuntimeError):
      """Base error for Graph file-manager failures; carries ``status_code`` when known."""

  class GraphDriveFileManager(FileManagerInterface, ABC):
      """FileManagerInterface over one Microsoft Graph drive (SharePoint library or OneDrive).

      Paths are drive-relative and prefixed with ``prefix`` exactly like S3's ``prefix + key``.
      Subclasses implement ``_build_client`` and ``_resolve_drive_id`` only.
      """
      manager_name: str = "graphfile"                       # subclasses override ("sharepointfile" / "onedrivefile")
      SMALL_FILE_THRESHOLD: int = 4 * 1024 * 1024           # single PUT below; upload session at/above  (matches sharepoint.py:56)
      CHUNK_SIZE: int = 10 * 1024 * 1024                    # upload-session chunk (matches sharepoint.py:57)
      MAX_CONCURRENCY: int = 5
      MAX_RETRIES: int = 3
      COPY_TIMEOUT_S: float = 120.0
      RETRYABLE_STATUS: frozenset[int] = frozenset({429, 503, 504})
      SERVING_MAX_BYTES: int = 64 * 1024 * 1024                 # S7: FileServingExtension buffers whole objects (web.py:229-232, 257-259)
      ALLOWED_ORIGINS: tuple[str, ...] = ("https://graph.microsoft.com", "https://graph.microsoft.us", "https://dod-graph.microsoft.us", "https://graph.microsoft.de", "https://microsoftgraph.chinacloudapi.cn")   # == delta.py DEFAULT_GRAPH_ORIGINS (delta.py:65-71), copied not imported
      ALLOWED_HOST_SUFFIXES: tuple[str, ...] = (".sharepoint.com", ".sharepoint-df.com", ".files.1drv.com")   # uploadUrl / downloadUrl / copy monitor hosts (S6)

      def __init__(
          self,
          *,
          prefix: str = "",
          credentials: Optional[Dict[str, Any]] = None,
          auth_mode: AuthMode = "direct",
          user_assertion: Optional[str] = None,
          scopes: Optional[List[str]] = None,
          conflict_behavior: ConflictBehavior = "replace",
          link_type: LinkType = "view",
          link_scope: LinkScope = "organization",
          max_concurrency: Optional[int] = None,
          max_retries: Optional[int] = None,
          chunk_size: Optional[int] = None,
          small_file_threshold: Optional[int] = None,
          **kwargs: Any,
      ) -> None:
          """Store configuration; no network I/O. ``prefix`` is normalised to ``"a/b/"`` or ``""``."""

      # ---- abstract hooks -------------------------------------------------
      @abstractmethod
      def _build_client(self) -> O365Client:
          """Return the (not yet authenticated) O365Client subclass for this drive kind."""
      @abstractmethod
      async def _resolve_drive_id(self) -> str:
          """Resolve and return the Graph drive id (cached by the base in ``self._drive_id``)."""

      # ---- lifecycle ------------------------------------------------------
      async def connect(self) -> "GraphDriveFileManager":
          """Build the client, authenticate per ``auth_mode`` (same branches as O365Tool._get_client,
          parrot_tools/o365/base.py:157-190), resolve the drive id. Idempotent."""
      def adopt_client(self, client: O365Client) -> None:                         # S1 — authenticated-client injection boundary
          """Reuse an already-authenticated client instead of authenticating again.

          ``client`` may be a plain ``O365Client`` (what O365Tool._get_client returns, base.py:148) or a
          drive client. The manager builds its own drive client via ``_build_client()`` when the adopted
          object lacks the backend helpers, then copies ``credentials``, ``tenant``, ``tenant_id``, ``site``,
          ``auth_mode``, ``_credential`` and ``_graph_client`` (o365.py:167-200, 339) onto it so no second
          token acquisition occurs (AC3). ``close()`` never closes an adopted client (its owner does)."""
      async def close(self) -> None:
          """Close the client (``await client.close()``, o365.py:709) and drop caches."""
      async def __aenter__(self) -> "GraphDriveFileManager": ...
      async def __aexit__(self, exc_type, exc, tb) -> None: ...
      @property
      def client(self) -> O365Client:
          """Authenticated client; raises GraphFileManagerError if ``connect()`` has not run."""
      @property
      def drive_id(self) -> str: ...

      # ---- path model & mapping ------------------------------------------
      def _prefixed(self, key: str) -> str:                         # mirrors s3.py:120
          """``prefix + key.lstrip('/')``; rejects ``..`` segments with ValueError."""
      def _unprefixed(self, key: str) -> str: ...                   # mirrors s3.py:124
      def _item_ref(self, path: str) -> str:
          """``"root"`` for the drive root, else ``"root:/<segments url-quoted with '/'>:"`` (sharepoint.py:556 rule)."""
      def _make_metadata(self, item: Any) -> FileMetadata:
          """name, drive-relative unprefixed path, size or 0, file.mime_type, last_modified_date_time, web_url."""
      async def _get_item(self, path: str) -> Any:
          """GET the DriveItem; raises FileNotFoundError on 404, GraphFileManagerError otherwise."""
      async def _get_item_by_id(self, item_id: str) -> Any:
          """GET by stable id (used by the OneDrive download-by-id tool, M8)."""
      async def _ensure_parent(self, path: str) -> Any:
          """Ensure the parent folder chain exists (create=True) and return its DriveItem."""
      async def _iter_children(self, item_id: str) -> AsyncIterator[Any]:       # S4 — pagination
          """Yield every child across all pages: ``.children.get()`` then
          ``.children.with_url(resp.odata_next_link).get()`` until ``odata_next_link`` is None
          (DriveItemCollectionResponse.odata_next_link; ChildrenRequestBuilder.with_url, msgraph-sdk 1.63)."""
      async def _iter_search(self, q: str) -> AsyncIterator[Any]:
          """Same pagination rule over ``search_with_q(q).get()``."""
      def _validate_graph_url(self, url: str, *, purpose: str) -> str:            # S6 — outbound URL boundary
          """Accept only https URLs whose host is an ALLOWED_ORIGINS host or ends with an ALLOWED_HOST_SUFFIXES
          entry; raise GraphFileManagerError otherwise. Never logs the URL. aiohttp calls made with the
          validated URL send NO Authorization header and use ``allow_redirects=False``."""

      # ---- FileManagerInterface (abstract methods, abstract.py:53-155) ----
      async def list_files(self, path: str = "", pattern: str = "*") -> List[FileMetadata]:
          """Non-recursive listing of ``path`` filtered by fnmatch ``pattern``; folders excluded; all pages (S4/S8)."""
      async def get_file_url(self, path: str, expiry: int = 3600) -> str:      # exact interface signature (abstract.py:67)
          """Compatibility wrapper: ``await self.create_sharing_link(path, link_type=self.link_type,
          scope=self.link_scope, expiry=expiry)`` (S3)."""
      async def create_sharing_link(self, path: str, *, link_type: LinkType = "view", scope: LinkScope = "organization",
                                    expiry: int = 3600) -> str:                # extension (S3)
          """POST createLink(type, scope, expirationDateTime=now+expiry if expiry>0). Side effect: creates a
          Graph sharing permission. Falls back to a non-expiring link (warning) when the tenant rejects
          expiration; raises PermissionError when the scope is forbidden by policy."""
      async def list_entries(self, path: str = "") -> List[DriveEntry]:         # extension (S8)
          """Non-recursive listing INCLUDING folders, all pages; used by the O365 List tools."""
      async def upload_file(self, source: Union[BinaryIO, Path], destination: str) -> FileMetadata:
          """< SMALL_FILE_THRESHOLD → PUT content; else createUploadSession + chunked PUTs (aiohttp).
          Honours ``conflict_behavior``. Returns metadata of the created item."""
      async def download_file(self, source: str, destination: Union[Path, BinaryIO]) -> Path:
          """Stream ``@microsoft.graph.downloadUrl`` with aiohttp into a Path or BinaryIO.
          Returns the Path (``Path(source)`` for BinaryIO destinations, as S3 does)."""
      async def copy_file(self, source: str, destination: str) -> FileMetadata:
          """POST items/{id}/copy (202 + Location monitor) — the POST itself is NEVER retried (non-idempotent, S5);
          the monitor URL is validated (S6) then polled with aiohttp (GET, retried per policy) until
          status == "completed" or COPY_TIMEOUT_S → TimeoutError."""
      async def delete_file(self, path: str) -> bool:
          """DELETE the item (recycle bin). False when it does not exist."""
      async def exists(self, path: str) -> bool:
          """True for files AND folders that resolve."""
      async def get_file_metadata(self, path: str) -> FileMetadata: ...
      async def create_file(self, path: str, content: bytes) -> bool:
          """Upload bytes (small PUT or session via bytes path); True on success."""

      # ---- optional folder / rename hooks (abstract.py:170-212) ----------
      async def create_folder(self, folder_name: str) -> None: ...
      async def remove_folder(self, folder_name: str) -> None: ...
      async def rename_folder(self, old_folder_name: str, new_folder_name: str) -> None:
          """PATCH name (same parent) or POST copy+delete when the parent changes."""
      async def rename_file(self, old_file_name: str, new_file_name: str) -> None: ...

      # ---- overrides / extensions ----------------------------------------
      async def find_files(self, keywords=None, extension=None, prefix=None) -> List[FileMetadata]:   # overrides abstract.py:265
          """Graph search(q) on the drive when the keyword is API-safe (sharepoint.py:867 rule);
          else recursive children walk under ``prefix``. Filters by extension/prefix/all keywords."""
      async def upload_file_from_bytes(self, file_obj: bytes, destination_key: str,
                                       content_type: str = "application/octet-stream") -> str:   # parity with s3.py:571
          """Upload bytes and return the item's ``web_url``."""
      async def upload_files(self, items: Sequence[Tuple[Union[Path, BinaryIO, bytes], str]]) -> List[BatchItemResult]:
          """Bounded-concurrency batch (asyncio.Semaphore(max_concurrency)); per-item result in input order
          (``index`` = input position); retries RETRYABLE_STATUS honouring Retry-After up to max_retries; never
          raises for an item. A 401/403 on any item marks it ``failed`` (error_code="auth") and every not-yet-started
          item ``skipped`` (attempts=0). The same BinaryIO object appearing twice in ``items`` is rejected up front
          with ValueError (a stream cannot be read twice, S10). Cancellation of the outer task propagates to
          in-flight items; already-finished results are still returned by the toolkit summary as ``aborted``."""
      async def download_files(self, items: Sequence[Tuple[str, Union[Path, BinaryIO]]]) -> List[BatchItemResult]: ...

      # ---- HTTP serving (parity with s3.py:613-660) ----------------------
      def setup(self, app: Any, route: str = "/data", base_url: Optional[str] = None,
                *, serving_max_bytes: Optional[int] = None) -> FileServingExtension:
          """Mount FileServingExtension(manager=self, route=route, manager_name=self.manager_name) on ``app``.
          S7: the extension buffers the whole object in memory for both full and Range responses
          (web.py:229-232, 257-259); ``serving_max_bytes`` (default SERVING_MAX_BYTES) caps what may be served."""
      async def handle_file(self, request: Any) -> Any:
          """Size guard then delegate: files larger than ``serving_max_bytes`` get HTTP 413 with a body naming the
          limit; otherwise the mounted extension's ``handle_file`` runs (buffered; Range served from the buffer)."""

      # ---- internals ------------------------------------------------------
      async def _put_small(self, parent_id: str, name: str, data: bytes, content_type: str) -> Any: ...
      async def _put_session(self, parent_id: str, name: str, stream: BinaryIO, size: int) -> Any:
          """createUploadSession(conflictBehavior) + aiohttp chunk PUTs (Content-Range), Retry-After aware."""
      async def _retrying(self, op: Callable[[], Awaitable[Any]], *, label: str, idempotent: bool = True) -> Tuple[Any, int]:
          """ONE bounded retry policy for SDK and raw-aiohttp paths alike (S5): retries RETRYABLE_STATUS up to
          max_retries, delay = Retry-After if present (capped at 60 s) else exponential backoff from 1 s;
          ``idempotent=False`` (copy POST, upload-session creation) disables retries. Returns (result, attempts)."""
      @staticmethod
      def _status_code_of(error: BaseException) -> Optional[int]: ...        # same semantics as parrot_tools/o365/delta.py:487
      @staticmethod
      def _retry_after_seconds(error: BaseException) -> Optional[float]: ... # same semantics as delta.py:499
  ```

### Module 2: `OneDriveClient._resolve_user_drive` port
- **Path**: `packages/ai-parrot/src/parrot/interfaces/onedrive.py` (modifies)
- **Responsibility**: additive port of flowtask's `_resolve_user_drive`, taking an
  explicit `user` argument (UPN, object id, or `"me"`). **Cache-safe (S9)**: results
  are cached per normalised user key in a new `_user_drives: Dict[str, DriveItem]`
  and the method never writes `_drive_id` / `_drive_info` (those stay owned by
  `_resolve_drive()` for the `me` legacy path), so reusing one client for several
  users or concurrent managers cannot return another user's drive. Error wording
  preserved from flowtask (application permission `Files.ReadWrite.All` hint).
- **Depends on**: nothing in this spec
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot/src/parrot/interfaces/onedrive.py  (modifies parrot/interfaces/onedrive.py:48-62 and :88-106)
  class OneDriveClient(O365Client):                                       # verified: onedrive.py:25
      def __init__(self, *args, **kwargs):                                # verified: onedrive.py:48
          ...
          self._user_drives: Dict[str, DriveItem] = {}                    # NEW, after line 62 — per-user cache (S9)

      async def _resolve_user_drive(self, user: str) -> DriveItem:          # NEW, after _resolve_drive (:88-106)
          """Resolve a user's personal OneDrive, cached per user key (never touches _drive_id/_drive_info).

          ``user`` is a UPN, an object id, or the literal ``"me"`` (key normalised with ``.strip().lower()``).
          ``"me"`` → ``graph_client.me.drive.get()`` (delegated auth only; raises RuntimeError under
          app-only auth via ``self.is_app_only()``, o365.py:365); otherwise
          ``graph_client.users.by_user_id(user).drive.get()``.
          Raises RuntimeError naming the missing ``Files.ReadWrite.All`` application permission on failure.
          """
  ```

### Module 3: `SharePointFileManager`
- **Path**: `packages/ai-parrot/src/parrot/interfaces/file/sharepoint.py` (new)
- **Responsibility**: site + library targeting over `SharepointClient`.
- **Depends on**: Module 1
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot/src/parrot/interfaces/file/sharepoint.py  (new)
  from parrot.interfaces.sharepoint import SharepointClient               # verified: parrot/interfaces/sharepoint.py:32
  from .graph import GraphDriveFileManager

  class SharePointFileManager(GraphDriveFileManager):
      """FileManagerInterface over one SharePoint document library.

      ``site`` is the site path under ``/sites/`` — ``"TeamSite"`` or, for a sub-site, ``"parent/sub"``
      given EXPLICITLY (``_resolve_site`` builds ``…sharepoint.com:/sites/{site}``, sharepoint.py:181-183).
      The client's ``_detect_and_resolve_subsite`` (sharepoint.py:120-172) only acts on the hidden
      ``_srcfiles`` list; the manager never populates it, so no hidden mutable input exists (S2).
      ``library`` defaults to ``"Documents"`` and accepts the ``"Shared Documents"`` alias (sharepoint.py:208).
      Credentials default to SHAREPOINT_APP_ID / SHAREPOINT_APP_SECRET / SHAREPOINT_TENANT_ID /
      SHAREPOINT_TENANT_NAME (sharepoint.py:44-47).
      """
      manager_name: str = "sharepointfile"

      def __init__(self, site: str, library: str = "Documents", *, tenant: Optional[str] = None, **kwargs: Any) -> None:
          """``tenant`` is the *.sharepoint.com host name; falls back to credentials['tenant'] / SHAREPOINT_TENANT_NAME."""

      def _build_client(self) -> SharepointClient:
          """SharepointClient(credentials={**credentials, 'site': site, 'tenant': tenant or credentials.get('tenant')});
          asserts ``client._srcfiles == []`` after construction (S2 invariant, tested)."""
      async def _resolve_drive_id(self) -> str:
          """await client.verify_sharepoint_access() (sharepoint.py:96); drive = await client._resolve_drive(library) (:242); return drive.id."""
  ```

### Module 4: `OneDriveFileManager`
- **Path**: `packages/ai-parrot/src/parrot/interfaces/file/onedrive.py` (new)
- **Responsibility**: user / `me` targeting over `OneDriveClient`.
- **Depends on**: Module 1, Module 2
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot/src/parrot/interfaces/file/onedrive.py  (new)
  from parrot.interfaces.onedrive import OneDriveClient                   # verified: parrot/interfaces/onedrive.py:25
  from .graph import GraphDriveFileManager

  class OneDriveFileManager(GraphDriveFileManager):
      """FileManagerInterface over a user's OneDrive.

      ``user="me"`` requires delegated/cached/on_behalf_of auth; under app-only (direct) auth
      ``user`` must be a UPN or object id and the app needs ``Files.ReadWrite.All``.
      Credentials default to O365_CLIENT_ID / O365_CLIENT_SECRET / O365_TENANT_ID (o365.py:188-191).
      """
      manager_name: str = "onedrivefile"

      def __init__(self, user: str = "me", **kwargs: Any) -> None: ...

      def _build_client(self) -> OneDriveClient: ...
      async def _resolve_drive_id(self) -> str:
          """Rejects user=='me' with RuntimeError when client.is_app_only(); else
          drive = await client._resolve_user_drive(user) (M2); return drive.id."""
  ```

### Module 5: Registration (shims, factory, literals)
- **Path**: `packages/ai-parrot/src/parrot/interfaces/file/__init__.py`,
  `packages/ai-parrot-tools/src/parrot_tools/file/__init__.py`,
  `packages/ai-parrot/src/parrot/tools/filemanager.py` (modifies all three)
- **Responsibility**: make the managers discoverable without importing msgraph at
  package-import time, and creatable by string key.
- **Depends on**: Module 3, Module 4 (import targets must exist)
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot/src/parrot/interfaces/file/__init__.py  (modifies :25-37)
  __all__ = (..., "S3FileManager", "GCSFileManager", "SharePointFileManager", "OneDriveFileManager")   # verified: file/__init__.py:25
  _LAZY_MANAGERS = {
      "S3FileManager": "navigator.utils.file.s3",                              # verified: file/__init__.py:34-37
      "GCSFileManager": "navigator.utils.file.gcs",
      "SharePointFileManager": "parrot.interfaces.file.sharepoint",           # NEW
      "OneDriveFileManager": "parrot.interfaces.file.onedrive",               # NEW
  }

  # packages/ai-parrot-tools/src/parrot_tools/file/__init__.py  (modifies :9-21)
  __all__ = (..., "SharePointFileManager", "OneDriveFileManager")
  def __getattr__(name: str):
      if name in ("S3FileManager", "GCSFileManager", "SharePointFileManager", "OneDriveFileManager"):   # verified: parrot_tools/file/__init__.py:21
          ...

  # packages/ai-parrot/src/parrot/tools/filemanager.py  (modifies :22-62, :174, :551, :218-238, :617-645)
  ManagerType = Literal["fs", "temp", "s3", "gcs", "sharepoint", "onedrive"]    # NEW module-level alias used by all three literals
  class FileManagerFactory:                                                      # verified: filemanager.py:22
      _PARROT_TO_UPSTREAM = {"fs": "local", "temp": "temp", "s3": "s3", "gcs": "gcs"}          # verified: :30
      _PARROT_NATIVE = {                                                          # NEW — resolved locally via importlib, never delegated upstream
          "sharepoint": ("parrot.interfaces.file.sharepoint", "SharePointFileManager"),
          "onedrive": ("parrot.interfaces.file.onedrive", "OneDriveFileManager"),
      }
      @staticmethod
      def create(manager_type: ManagerType, **kwargs: Any) -> FileManagerInterface:
          """Unknown keys still raise ValueError listing BOTH maps' keys (test_file_shim.py:90 contract)."""
  # FileManagerTool.__init__(manager_type: ManagerType = "fs", ...)            # verified: :174
  # FileManagerTool.description → "Manage files across different storage backends (local, S3, GCS, SharePoint, OneDrive, temp)"   # verified: :169
  # FileManagerTool._create_manager / FileManagerToolkit._create_manager: `else:` branch already forwards **kwargs — no change beyond the docstring  # verified: :238, :645
  # FileManagerToolkit.__init__(manager_type: ManagerType = "fs", ...)         # verified: :551
  ```

### Module 6: Agent operations `find`, `batch_upload`, `batch_download`
- **Path**: `packages/ai-parrot/src/parrot/tools/filemanager.py` (modifies)
- **Responsibility**: expose the extensions to agents on every backend.
- **Depends on**: Module 1 (`BatchItemResult`, `BatchSummary`); Module 5 (shared file — tasks serialize)
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot/src/parrot/tools/filemanager.py  (modifies :65-138, :266-320, :501-512, :515-560, :947+)
  class FileManagerToolArgs(AbstractToolArgsSchema):                            # verified: filemanager.py:65
      operation: Literal["list", "upload", "download", "copy", "delete", "exists", "get_url", "get_metadata", "create",
                         "find", "batch_upload", "batch_download"]             # verified anchor: :72
      keywords: Optional[Union[str, List[str]]] = Field(None, description="find: substrings that must all appear in the filename")
      extension: Optional[str] = Field(None, description="find: file extension filter, e.g. '.csv'")
      prefix: Optional[str] = Field(None, description="find: restrict the search to this path prefix")
      items: Optional[List[Dict[str, str]]] = Field(None, description="batch_*: list of {'source': ..., 'destination': ...}")

  _OP_TO_METHOD: Dict[str, str] = {..., "find": "find_files", "batch_upload": "batch_upload", "batch_download": "batch_download"}   # verified: :501-511

  class FileManagerTool(AbstractTool):                                          # verified: :140
      async def _find_files(self, args: FileManagerToolArgs) -> Dict[str, Any]: ...
      async def _batch_upload(self, args: FileManagerToolArgs) -> Dict[str, Any]: ...
      async def _batch_download(self, args: FileManagerToolArgs) -> Dict[str, Any]: ...
      # _execute dispatch (:275-292) gains three elif branches

  class FileManagerToolkit(AbstractToolkit):                                    # verified: :515
      async def find_files(self, keywords: Optional[Union[str, List[str]]] = None, extension: Optional[str] = None,
                           prefix: Optional[str] = None) -> Dict[str, Any]:
          """Find files by keyword(s), extension and/or prefix. Uses the backend's server-side search when
          it overrides find_files, else the in-memory default (abstract.py:265). Returns {"files": [...], "count": n}."""
      async def batch_upload(self, items: List[Dict[str, str]]) -> Dict[str, Any]:
          """Upload many local files. items = [{"source": "<local path>", "destination": "<storage path>"}].
          Uses manager.upload_files when present (Graph managers), else loops manager.upload_file per item.
          Never fails the whole batch for one item; returns BatchSummary.model_dump()."""
      async def batch_download(self, items: List[Dict[str, str]]) -> Dict[str, Any]:
          """Download many files. items = [{"source": "<storage path>", "destination": "<local path>"}]. Same fallback rule."""
  ```

### Module 7: SharePoint O365 tools refactor
- **Path**: `packages/ai-parrot-tools/src/parrot_tools/o365/sharepoint.py` (modifies classes at :36, :204, :325, :459 only)
- **Responsibility**: `ListSharePointFilesTool`, `SearchSharePointFilesTool`,
  `DownloadSharePointFileTool`, `UploadSharePointFileTool` build a
  `SharePointFileManager` from `site` / `library` and the tool's
  `credentials` / resolved `auth_mode` / `user_assertion`, call it, and return
  the **same** response dicts as today (keys listed in §6 Integration Points).
  `DeltaSharePointFilesTool` (:656) and its args are not touched.
- **Depends on**: Module 3
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot-tools/src/parrot_tools/o365/sharepoint.py  (modifies :36-185, :204-305, :325-438, :459-558)
  from parrot.interfaces.file.sharepoint import SharePointFileManager       # NEW import next to :18

  class ListSharePointFilesTool(O365Tool):                                   # verified: :36
      async def _execute_graph_operation(self, client: O365Client, **kwargs) -> Dict[str, Any]:   # signature type widened to O365Client (what _get_client returns, base.py:148)
          """Build SharePointFileManager(site, library, credentials=self.credentials), then
          manager.adopt_client(client) (M1, S1) — the tool's cached, already-authenticated client is reused and
          NO second token acquisition happens; list via manager.list_entries (folders included, all pages — S4/S8;
          recursive optional), return
          {"site","library","folder_path","total_items","files":[{name,path,is_folder,size,modified,web_url,id}],"recursive"}."""
  # Search → manager.find_files / _iter_search, max_results applied AFTER filtering (S4) →
  #   {"site","query","library","folder_path","file_extension","total_results","files":[{name,path,size,modified,web_url,id}]}
  # Download → manager.download_file → {"site","library","file_path","local_path","download_url","size"}
  #   ("download_url" = the item web_url, never the pre-authenticated downloadUrl — S6)
  # Upload → manager.upload_file (conflict_behavior from `overwrite`) → {"site","library","folder_path","uploaded_file","size","web_url","server_relative_url"}
  ```
  Path mapping (S8): the tools' `library` + `folder_path` are library-relative,
  which is the manager's drive-relative path with `prefix=""` — response
  `path` values are therefore identical to today's. The manager is constructed
  per call (cheap: no I/O until `adopt_client` + `_resolve_drive_id`), and its
  `close()` does not close the adopted client (owned by the tool cache).

### Module 8: OneDrive O365 tools refactor
- **Path**: `packages/ai-parrot-tools/src/parrot_tools/o365/onedrive.py` (modifies classes at :34, :133, :213, :348 only)
- **Responsibility**: same as M7 with `OneDriveFileManager(user=kwargs.get("user_id") or "me")`;
  `DownloadOneDriveFileTool` keeps `file_id` support by resolving the id to a
  path through the manager's `_get_item_by_id` helper (M1 internal).
  Response dicts preserved: List `{"folder_path","total_items","files","recursive"}`,
  Search `{"query","total_results","files"}`, Download
  `{"file_path","file_id","local_path","size"}`, Upload
  `{"folder_path","uploaded_file","file_id","size","web_url"}`.
- **Depends on**: Module 4

### Module 9: Packaging + docs
- **Path**: `packages/ai-parrot/pyproject.toml` (modifies :395, :875-877),
  `docs/integrations/office365-oauth2.md` (modifies after :39),
  `docs/interfaces/graph-filemanager.md` (new)
- **Responsibility**: `msgraph = ["azure-identity>=1.18.0", "msgraph-sdk>=1.8.0",
  "microsoft-kiota-authentication-azure>=1.2.0"]` extra (pins copied verbatim
  from `agents`, :440-442) and `msgraph` appended to the `all` meta-extra;
  permissions table gains `Files.ReadWrite.All` (application) and
  `Sites.ReadWrite.All` rows for the managers; new doc covers construction,
  auth modes, path model, batch semantics, sharing links, serving and the live
  gate.
- **Depends on**: nothing (exclusive resource: `pyproject.toml`)

### Module 10: Live gate suite
- **Path**: `packages/ai-parrot/tests/interfaces/test_graph_filemanager_live.py` (new)
- **Responsibility**: `@pytest.mark.live` end-to-end round trips against a real
  tenant, skipped unless `PARROT_LIVE_GRAPH=1` **and** the target knobs are set;
  writes only under a run-scoped folder `parrot-live/<uuid>/` that it removes
  at teardown.
- **Depends on**: Module 3, Module 4

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_prefixed_unprefixed_roundtrip` / `test_rejects_parent_segments` | M1 | S3-parity path model; `..` → ValueError |
| `test_item_ref_root_and_quoted_segments` | M1 | `"root"` for `""`, `root:/a%20b/c%23d.txt:` for `a b/c#d.txt` |
| `test_make_metadata_maps_driveitem` | M1 | name/path/size/mime/modified/url mapping, folder → size 0, content_type None |
| `test_list_files_pattern_excludes_folders` | M1 | fnmatch filter, folders excluded |
| `test_upload_small_uses_content_put` / `test_upload_large_uses_session_chunks` | M1 | threshold routing; Content-Range headers; 202 continue; Retry-After sleep |
| `test_upload_conflict_behavior_replace_fail_rename` | M1 | query/body carries `@microsoft.graph.conflictBehavior` |
| `test_download_streams_to_path_and_binaryio` | M1 | downloadUrl streamed; BinaryIO not buffered; returns Path |
| `test_copy_polls_monitor_until_completed` / `test_copy_timeout` | M1 | 202 + Location; TimeoutError after COPY_TIMEOUT_S |
| `test_delete_recycle_bin_and_missing_returns_false` | M1 | DELETE; 404 → False |
| `test_exists_true_for_folder` | M1 | documented semantics |
| `test_get_file_url_createlink_defaults_and_expiry` | M1 | type/scope/expirationDateTime; `expiry<=0` → none; policy rejection → warning fallback; anonymous forbidden → PermissionError |
| `test_find_files_server_search_vs_recursive_fallback` | M1 | API-safe keyword → `search_with_q`; wildcard → recursive walk; extension/prefix filters |
| `test_upload_files_per_item_results_order_and_no_raise` | M1 | one failing item, others succeed, input order kept |
| `test_batch_retries_429_with_retry_after_then_succeeds` | M1 | attempts=2, sleep called with Retry-After |
| `test_batch_auth_failure_aborts_remaining` | M1 | 401 → remaining items marked aborted, no raise |
| `test_batch_concurrency_bounded` | M1 | never more than `max_concurrency` in flight |
| `test_batch_skipped_state_and_index_identity` / `test_batch_duplicate_destinations_last_write_wins` / `test_batch_rejects_shared_binaryio` / `test_batch_cancellation_propagates` | M1 | S10 semantics: `state`, `index`, `attempts=0` for skipped, ValueError for a reused stream, `asyncio.CancelledError` reaches in-flight items |
| `test_list_files_follows_next_link` / `test_list_entries_includes_folders_all_pages` / `test_search_paginates_then_applies_max_results` | M1 | S4/S8: three scripted pages via `odata_next_link` + `with_url`; folders only in `list_entries` |
| `test_validate_graph_url_accepts_graph_and_sharepoint_hosts` / `test_validate_graph_url_rejects_http_and_foreign_hosts` / `test_outbound_calls_have_no_auth_header_and_no_redirects` | M1 | S6 boundary on uploadUrl, monitor URL and downloadUrl |
| `test_copy_post_never_retried` / `test_retry_policy_caps_retry_after` | M1 | S5 |
| `test_create_sharing_link_options` / `test_get_file_url_signature_matches_interface` | M1 | S3: wrapper keeps `(path, expiry=3600)`; options only on the extension |
| `test_handle_file_413_over_serving_max_bytes` | M1 | S7 guard before the buffering extension runs |
| `test_sharepoint_manager_never_populates_srcfiles` / `test_sharepoint_subsite_via_explicit_site_path` | M3 | S2 |
| `test_resolve_user_drive_cache_per_user_and_leaves_drive_id_alone` | M2 | S9 |
| `test_setup_mounts_fileserving_extension` | M1 | `FileServingExtension(manager=self, route, manager_name)` |
| `test_no_httpx_import_in_new_modules` | M1/M3/M4 | AST scan: `httpx` never imported by `parrot/interfaces/file/{graph,sharepoint,onedrive}.py` |
| `test_resolve_user_drive_me_and_upn` / `test_resolve_user_drive_app_only_me_rejected` / `test_resolve_user_drive_error_names_permission` | M2 | ported behaviour |
| `test_sharepoint_manager_builds_client_with_site_and_tenant` / `test_sharepoint_resolve_drive_uses_library` | M3 | credential keys; `_resolve_drive(library)` |
| `test_onedrive_manager_me_requires_delegated` / `test_onedrive_manager_user_drive` | M4 | rules |
| `test_connect_auth_mode_branches` | M1 | direct → `acquire_token` in executor; obo → `acquire_token_on_behalf_of`; delegated → `interactive_login`; cached → `ensure_interactive_session`; ROPC via `username`/`password` creds |
| `test_shim_exports_new_managers_lazily` / `test_no_msgraph_leak_on_import` / `test_parrot_tools_file_shim_parity` | M5 | extends `test_file_shim.py` |
| `test_factory_sharepoint_and_onedrive_native` / `test_factory_unknown_lists_all_keys` | M5 | local resolution; ValueError message lists both maps |
| `test_toolkit_literal_accepts_new_types` | M5 | `FileManagerToolkit(manager_type="sharepoint", ...)` with fake client |
| `test_tool_find_batch_ops_dispatch` / `test_toolkit_batch_fallback_loops_single_ops` / `test_toolkit_find_uses_backend_override` | M6 | new ops; generic fallback on `temp` backend; `BatchSummary` shape; `allowed_operations` validation accepts new keys |
| `test_list_sharepoint_files_tool_response_shape` (+ search/download/upload) | M7 | keys preserved vs. fixtures captured from current code |
| `test_onedrive_tools_response_shape` (list/search/download-by-path/download-by-id/upload) | M8 | keys preserved |
| `test_delta_tools_untouched` | M7/M8 | `DeltaSharePointFilesTool`/`DeltaOneDriveFilesTool` source unchanged vs. base commit (hash of the class block) |
| `test_msgraph_extra_present_and_in_all` | M9 | parse pyproject: extra keys and `all` contains `msgraph` |

Test locations: `packages/ai-parrot/tests/interfaces/test_graph_filemanager.py`
(M1), `test_onedrive_client_user_drive.py` (M2), `test_sharepoint_filemanager.py`
(M3), `test_onedrive_filemanager.py` (M4), `test_file_shim.py` (M5, extended),
`packages/ai-parrot/tests/tools/test_filemanager_batch_ops.py` (M6),
`packages/ai-parrot-tools/tests/test_o365_file_tools_refactor.py` (M7/M8),
`packages/ai-parrot/tests/test_msgraph_extra.py` (M9).

### Integration Tests
| Test | Description |
|---|---|
| `test_live_sharepoint_roundtrip` (M10, `@pytest.mark.live`) | upload bytes → exists → metadata → list → find → get_file_url → download to BinaryIO → copy → rename → delete; all under `parrot-live/<uuid>/` |
| `test_live_onedrive_user_roundtrip` (M10) | same against `PARROT_LIVE_ONEDRIVE_USER` under app-only auth |
| `test_live_batch_upload_download` (M10) | 12 files, `max_concurrency=3`, all `ok`, order preserved |
| `test_live_large_upload_session` (M10) | 12 MiB file exercises the chunked session |

Live knobs (all required, else skip): `PARROT_LIVE_GRAPH=1`,
`PARROT_LIVE_SHAREPOINT_SITE`, `PARROT_LIVE_SHAREPOINT_LIBRARY` (default
`Documents`), `PARROT_LIVE_ONEDRIVE_USER`; credentials from the existing
`SHAREPOINT_*` / `O365_*` settings. Run manually:
`PARROT_LIVE_GRAPH=1 pytest packages/ai-parrot/tests/interfaces/test_graph_filemanager_live.py -m live -v`.

### Test Data / Fixtures
```python
# packages/ai-parrot/tests/interfaces/conftest.py (extends; uses M0)
@pytest.fixture
def fake_graph():
    drive = FakeDrive(); drive.put_file("reports/2026/q3.xlsx", b"x" * 10, mime="application/vnd.ms-excel")
    return FakeGraphClient({"drive-1": drive}, me_drive_id="drive-1", user_drives={"u@t.com": "drive-1"})

@pytest.fixture
def sp_manager(fake_graph, monkeypatch):
    m = SharePointFileManager(site="TeamSite", library="Documents", prefix="reports/", credentials={"client_id": "x", "client_secret": "y", "tenant_id": "z", "tenant": "t"})
    m.adopt_client(make_sharepoint_client(fake_graph, drive_id="drive-1"))
    monkeypatch.setattr("parrot.interfaces.file.graph.aiohttp.ClientSession", lambda *a, **k: FakeAiohttpSession(fake_graph))
    return m
```

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] AC1. `GraphDriveFileManager` implements every abstract method of `FileManagerInterface` with the exact signatures at `navigator/utils/file/abstract.py:53-155`, plus `create_folder`/`remove_folder`/`rename_folder`/`rename_file` (:170-212) and a server-side `find_files` override (:265); `issubclass` and `inspect.signature` parity tests pass.
- [ ] AC2. `SharePointFileManager` and `OneDriveFileManager` differ from the base **only** by `manager_name`, `__init__`, `_build_client` and `_resolve_drive_id` (test asserts no other overridden attributes).
- [ ] AC3. All four auth modes (`direct`, `on_behalf_of`, `delegated`, `cached`) and username/password credentials reach the corresponding `O365Client` calls, with **one** token acquisition per manager (`test_connect_auth_mode_branches`).
- [ ] AC4. `OneDriveClient._resolve_user_drive` resolves `me/drive` and `users/{id}/drive`, rejects `me` under app-only auth, and its error names `Files.ReadWrite.All`; `OneDriveClient._resolve_drive()` behaviour unchanged. `SharepointClient` has no source change (`git diff --stat` on the file is empty).
- [ ] AC5. Uploads route by `SMALL_FILE_THRESHOLD` (single PUT vs. upload session with `CHUNK_SIZE` chunks and `Content-Range`), default `conflict_behavior="replace"`, and honour `fail` / `rename`.
- [ ] AC6. `download_file` streams `@microsoft.graph.downloadUrl` via aiohttp into `Path` or `BinaryIO` without buffering the whole file; `copy_file` polls the 202 monitor and raises `TimeoutError` after `COPY_TIMEOUT_S`.
- [ ] AC7. `get_file_url(path, expiry=3600)` keeps the exact interface signature and wraps `create_sharing_link(path, *, link_type, scope, expiry)`; the link is a `createLink` URL with `type="view"`, `scope="organization"` by default, `expirationDateTime` set iff `expiry > 0`, a non-expiring link with a logged warning when the tenant rejects expiration, and `PermissionError` for a forbidden scope.
- [ ] AC8. `upload_files` / `download_files` return `List[BatchItemResult]` in input order with `index` identity and `state ∈ {succeeded, failed, skipped}` (+ `error_code`), never raise for an item, bound concurrency to `max_concurrency` (default 5), retry `{429, 503, 504}` honouring `Retry-After` (capped 60 s) up to `max_retries` (default 3), mark the remainder `skipped` (not raised) on 401/403, reject a `BinaryIO` reused across items with `ValueError`, and propagate outer cancellation.
- [ ] AC20. Every listing and search follows `@odata.nextLink` to exhaustion (`list_files`, `list_entries`, `find_files`, the tools' recursive walks); `max_results` in the Search tools is applied after filtering across all pages (three-page fake test).
- [ ] AC21. Upload-session `uploadUrl`, copy `Location` monitor and `@microsoft.graph.downloadUrl` are validated by `_validate_graph_url` (https + allowed host) before any aiohttp call, never logged, never sent an `Authorization` header, and fetched with `allow_redirects=False`; the copy POST is never retried.
- [ ] AC22. `handle_file` returns HTTP 413 for files larger than `serving_max_bytes` (default 64 MiB) before the buffering `FileServingExtension` path runs; the limit is documented in `docs/interfaces/graph-filemanager.md`.
- [ ] AC23. `SharePointFileManager` never populates `SharepointClient._srcfiles` (asserted empty after `_build_client` and after every operation in the fake-client tests); sub-sites are addressed via `site="parent/sub"`.
- [ ] AC24. `OneDriveClient._resolve_user_drive` caches per user key and leaves `_drive_id` / `_drive_info` untouched; two managers over one adopted client resolving different users get different drive ids.
- [ ] AC9. `upload_file_from_bytes(data, key, content_type)` returns the item `web_url` (S3 parity); `setup(app, route, base_url)` mounts `FileServingExtension(manager=self, route=route, manager_name=self.manager_name)`.
- [ ] AC10. `from parrot.interfaces.file import SharePointFileManager, OneDriveFileManager` and the `parrot_tools.file` parity import work, and importing either shim does **not** load `msgraph` into `sys.modules` (extends `test_no_cloud_sdk_leak_on_import`).
- [ ] AC11. `FileManagerFactory.create("sharepoint" | "onedrive", **kwargs)` resolves locally; unknown keys still raise `ValueError` whose message lists all six keys; `FileManagerTool` and `FileManagerToolkit` accept the two new `manager_type` values.
- [ ] AC12. `FileManagerToolArgs.operation` accepts `find`, `batch_upload`, `batch_download`; `FileManagerToolkit` exposes `fs_find_files`, `fs_batch_upload`, `fs_batch_download`; on backends without `upload_files`/`download_files` the toolkit loops the single-item op and returns the same `BatchSummary` shape; `allowed_operations` validation accepts the three new keys.
- [ ] AC13. The eight List/Search/Download/Upload O365 tools delegate to the managers and return response dicts with exactly the keys listed in §6 Integration Points; `DeltaSharePointFilesTool`, `DeltaOneDriveFilesTool` and `parrot_tools/o365/delta.py` are byte-identical to the base commit; `packages/ai-parrot-tools/tests/test_o365_delta_tools.py` and `tests/tools/test_office365_toolkit.py` pass.
- [ ] AC14. `packages/ai-parrot/pyproject.toml` has an `msgraph` extra with the three pins and `all` includes it; `uv pip install -e "packages/ai-parrot[msgraph]"` resolves in the dev venv (recorded in `artifacts/logs/`).
- [ ] AC15. No `httpx`, `requests`, `langchain*` or `print(` in any new or modified module (`ruff check` TID251 clean; AST test for httpx in the three new modules).
- [ ] AC16. Docs: `docs/interfaces/graph-filemanager.md` exists and `docs/integrations/office365-oauth2.md` lists the application/delegated permissions the managers need.
- [ ] AC17. All new unit tests pass under `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-tools/src pytest packages/ai-parrot/tests/interfaces packages/ai-parrot/tests/tools/test_filemanager_batch_ops.py packages/ai-parrot-tools/tests/test_o365_file_tools_refactor.py -v`; existing `packages/ai-parrot/tests/interfaces/test_file_shim.py` and `tests/tools/test_filemanager_toolkit.py` still pass.
- [ ] AC18. The live suite (M10) is run once manually by the owner against the tenant knobs above before `/sdd-done` and its output is saved under `artifacts/logs/FEAT-603-live.log`; a skipped live suite is recorded as such in the task's Completion Note, never as a pass.
- [ ] AC19. No breaking change: every existing public method of `SharepointClient`, `OneDriveClient`, `O365Client`, `FileManagerTool`, `FileManagerToolkit`, and the O365 toolkits keeps its signature (a signature-snapshot test compares against the base commit).

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> This section is the single source of truth for what exists in the codebase.
> Implementation agents MUST NOT reference imports, attributes, or methods
> not listed here without first verifying they exist via `grep` or `read`.
> Verified 2026-09-25 against base commit `42029db04` (dev), venv python3.12.

### Verified Imports
```python
from navigator.utils.file import FileManagerInterface, FileMetadata, FileManagerFactory, FileServingExtension  # verified: .venv/lib/python3.12/site-packages/navigator/utils/file/__init__.py (__all__ at :43)
from navigator.utils.file.abstract import FileManagerInterface, FileMetadata      # verified: abstract.py:36, :16
from navigator.utils.file.s3 import S3FileManager                                  # verified: s3.py:35
from navigator.utils.file.web import FileServingExtension                          # verified: web.py:28
from parrot.interfaces.file import FileManagerInterface, FileMetadata, S3FileManager, LocalFileManager   # verified: packages/ai-parrot/src/parrot/interfaces/file/__init__.py:19-24, :40
from parrot.interfaces.o365 import O365Client, MSALTokenCredential                 # verified: parrot/interfaces/o365.py:115, :40
from parrot.interfaces.sharepoint import SharepointClient                          # verified: parrot/interfaces/sharepoint.py:32
from parrot.interfaces.onedrive import OneDriveClient                              # verified: parrot/interfaces/onedrive.py:25
from parrot.interfaces.credentials import CredentialsInterface                     # verified: parrot/interfaces/credentials.py:24
from parrot.tools.filemanager import FileManagerFactory, FileManagerTool, FileManagerToolkit   # verified: parrot/tools/filemanager.py:22, :140, :515
from parrot.tools import FileManagerToolkit, AbstractToolkit, tool
from parrot_tools.o365.base import O365Tool, O365AuthMode                          # verified: parrot_tools/o365/base.py:49, :22
from parrot_tools.o365.bundle import SharePointToolkit, OneDriveToolkit, Office365FileManagementToolkit   # verified: bundle.py:27, :131, :235
from parrot_tools.o365.sharepoint import ListSharePointFilesTool, DeltaSharePointFilesTool                # verified: sharepoint.py:36, :656
from parrot_tools.o365.delta import DriveDeltaHelper, _retry_after_seconds, RETRYABLE_STATUS_CODES       # verified: delta.py:855, :499, __all__ :1266
from parrot.conf import SHAREPOINT_APP_ID, SHAREPOINT_APP_SECRET, SHAREPOINT_TENANT_ID, SHAREPOINT_TENANT_NAME, SHAREPOINT_SITE_ID, SHAREPOINT_DEFAULT_HOST   # verified: parrot/conf.py:612-617
from parrot.conf import O365_CLIENT_ID, O365_CLIENT_SECRET, O365_TENANT_ID, O365_REDIRECT_URI            # verified: parrot/conf.py:598-603
from msgraph import GraphServiceClient
from msgraph.generated.models.drive_item import DriveItem
from msgraph.generated.models.upload_session import UploadSession
from msgraph.generated.drives.item.items.item.create_link.create_link_post_request_body import CreateLinkPostRequestBody
from kiota_http.middleware.retry_handler import RetryHandler                       # default Graph pipeline retry (429/503)
```
Installed: `msgraph-sdk 1.63.0`, `azure-identity 1.25.3`, `msal 1.39.0`,
`microsoft-kiota-http 1.13.0`, `navigator-api 4.0.0`, `aiohttp 3.14.3`.

### Existing Class Signatures
```python
# .venv/lib/python3.12/site-packages/navigator/utils/file/abstract.py (navigator-api 4.0.0)
@dataclass
class FileMetadata:                                     # line 16
    name: str; path: str; size: int                     # 28-30
    content_type: Optional[str]; modified_at: Optional[datetime]; url: Optional[str]   # 31-33
class FileManagerInterface(ABC):                        # line 36
    async def list_files(self, path: str = "", pattern: str = "*") -> List[FileMetadata]        # 53 abstract
    async def get_file_url(self, path: str, expiry: int = 3600) -> str                         # 67 abstract
    async def upload_file(self, source: Union[BinaryIO, Path], destination: str) -> FileMetadata   # 79 abstract
    async def download_file(self, source: str, destination: Union[Path, BinaryIO]) -> Path     # 93 abstract
    async def copy_file(self, source: str, destination: str) -> FileMetadata                   # 107 abstract
    async def delete_file(self, path: str) -> bool                                             # 119 abstract
    async def exists(self, path: str) -> bool                                                  # 130 abstract
    async def get_file_metadata(self, path: str) -> FileMetadata                               # 141 abstract
    async def create_file(self, path: str, content: bytes) -> bool                             # 155 abstract
    async def create_folder(self, folder_name: str) -> None                                    # 170 default raises NotImplementedError
    async def remove_folder(self, folder_name: str) -> None                                    # 183 default raises
    async def rename_folder(self, old_folder_name: str, new_folder_name: str) -> None          # 196 default raises
    async def rename_file(self, old_file_name: str, new_file_name: str) -> None                # 212 default raises
    async def create_from_text(self, path: str, text: str, encoding: str = "utf-8") -> bool    # 230 concrete
    async def create_from_bytes(self, path: str, data: Union[bytes, BytesIO, StringIO]) -> bool   # 245 concrete → create_file
    async def find_files(self, keywords=None, extension=None, prefix=None) -> List[FileMetadata]  # 265 concrete (list+filter)

# .venv/lib/python3.12/site-packages/navigator/utils/file/s3.py — parity model
class S3FileManager(FileManagerInterface):              # 35
    manager_name: str = "s3file"                        # 49
    MULTIPART_THRESHOLD/MULTIPART_CHUNKSIZE/MAX_CONCURRENCY   # 51-53
    def __init__(self, bucket_name=None, aws_id="default", region_name=None, prefix="", multipart_threshold=None, multipart_chunksize=None, max_concurrency=None, **kwargs)   # 55 (credentials= via kwargs)
    def _prefixed(self, key: str) -> str / def _unprefixed(self, key: str) -> str   # 120 / 124
    def _make_metadata(self, key: str, obj: dict) -> FileMetadata   # 130
    async def upload_file_from_bytes(self, file_obj: bytes, destination_key: str, content_type: str = "application/octet-stream") -> str   # 571
    def setup(self, app, route: str = "/data", base_url: str = None)   # 613
    async def handle_file(self, request)                # 635

# .venv/lib/python3.12/site-packages/navigator/utils/file/web.py
class FileServingExtension(BaseExtension):              # 28; name="fileserving" :44; CHUNK_SIZE 1 MiB :46
    def __init__(self, manager: FileManagerInterface, route: str = "/data", manager_name: Optional[str] = None, **kwargs)   # 48
    def setup(self, app: WebApp) -> WebApp              # 78
    async def handle_file(self, request: web.Request) -> web.StreamResponse   # 150

# .venv/lib/python3.12/site-packages/navigator/utils/file/factory.py
class FileManagerFactory: _EAGER_MANAGERS {"local","temp"}; _LAZY_MANAGERS {"s3","gcs"}; create(manager_type, **kwargs) raises ValueError on unknown   # 14-73

# packages/ai-parrot/src/parrot/interfaces/file/__init__.py
__all__ = ("FileManagerInterface","FileMetadata","LocalFileManager","TempFileManager","S3FileManager","GCSFileManager")   # 25-32
_LAZY_MANAGERS = {"S3FileManager": "navigator.utils.file.s3", "GCSFileManager": "navigator.utils.file.gcs"}   # 34-37
def __getattr__(name: str)                              # 40 (importlib + setattr cache)

# packages/ai-parrot-tools/src/parrot_tools/file/__init__.py
def __getattr__(name): if name in ("S3FileManager", "GCSFileManager"): from parrot.interfaces import file as _file; return getattr(_file, name)   # 19-23

# packages/ai-parrot/src/parrot/tools/filemanager.py
imports: Literal, Optional, Dict, Any, Union, Set (:10); Path (:11); BytesIO (:12); Field (:14); AbstractTool, AbstractToolArgsSchema, ToolResult (:15); AbstractToolkit (:16); OUTPUT_DIR (:17); FileManagerInterface (:18); _UpstreamFileManagerFactory (:19)
class FileManagerFactory:                               # 22
    _PARROT_TO_UPSTREAM = {"fs": "local", "temp": "temp", "s3": "s3", "gcs": "gcs"}   # 30
    @staticmethod def create(manager_type: Literal["fs","temp","s3","gcs"], **kwargs) -> FileManagerInterface   # 38; ValueError message "Available: {sorted(...)}" :60
class FileManagerToolArgs(AbstractToolArgsSchema):      # 65; operation: Literal[...] :72; path :92; pattern :98; source_path :104; destination :108; destination_name :112; source :118; content :124; encoding :128; expiry_seconds :134
class FileManagerTool(AbstractTool):                    # 140; name "file_manager" :168; description :169; args_schema :170
    def __init__(self, manager_type: Literal["fs","temp","s3","gcs"] = "fs", default_output_dir=None, allowed_operations=None, max_file_size=100 MiB, auto_create_dirs=True, **manager_kwargs)   # 172
    def _create_manager(self, manager_type: str, **kwargs) -> FileManagerInterface   # 218; `else:  # s3 or gcs` forwards **kwargs :238
    async def _execute(self, **kwargs) -> ToolResult    # 266; if/elif dispatch :275-292; ToolResult(success, result, error, metadata)
    async def _list_files/_upload_file/_download_file/_copy_file/_delete_file/_exists/_get_file_url/_get_file_metadata/_create_file(self, args) -> Dict[str, Any]   # 320-468
_OP_TO_METHOD: Dict[str, str] = {"list": "list_files", "upload": "upload_file", "download": "download_file", "copy": "copy_file", "delete": "delete_file", "exists": "file_exists", "get_url": "get_file_url", "get_metadata": "get_file_metadata", "create": "create_file"}   # 501-511
_ALL_OPS: frozenset = frozenset(_OP_TO_METHOD)          # 512
class FileManagerToolkit(AbstractToolkit):              # 515; tool_prefix "fs" :547
    def __init__(self, manager_type: Literal["fs","temp","s3","gcs"] = "fs", default_output_dir=None, allowed_operations: Optional[Set[str]]=None, max_file_size=100 MiB, auto_create_dirs=True, **manager_kwargs) -> None   # 549; validates allowed_operations against _ALL_OPS; sets self.exclude_tools from _OP_TO_METHOD before super().__init__()
    def _create_manager(self, manager_type: str, **kwargs) -> FileManagerInterface   # 617; `else:  # s3 or gcs` :645
    async def list_files(:680) / upload_file(:719) / download_file(:768) / copy_file(:803) / delete_file(:837) / file_exists(:862) / get_file_url(:886) / get_file_metadata(:918) / create_file(:947) -> Dict[str, Any]

# packages/ai-parrot/src/parrot/interfaces/credentials.py
class CredentialsInterface(ABC):                        # 24
    def __init__(self, *args, **kwargs): self.credentials = kwargs.pop('credentials', None) ...   # 32-46
    def processing_credentials(self)                    # 70 — resolves each key in _credentials from the dict / env

# packages/ai-parrot/src/parrot/interfaces/o365.py
class O365Client(CredentialsInterface):                 # 115
    _credentials = {"username","password","client_id","client_secret","tenant","site","tenant_id","assertion"}   # 156
    def __init__(self, *args, **kwargs) -> None         # 167 — sets tenant/site/tenant_id None, _default_* from O365_* + SHAREPOINT_TENANT_NAME (:188-191), creates aioredis client (:198-200)
    def processing_credentials(self)                    # 218 — tenant = credentials['tenant'] or _default_tenant_name; site = credentials['site']; tenant_id
    def _create_credential(self) -> TokenCredential     # 237 (client-secret / ROPC / MSAL cache by available creds)
    def _create_graph_client(self, scopes=None) -> GraphServiceClient   # 312
    @property graph_client -> GraphServiceClient        # 339 (lazy create)
    def set_auth_mode(self, auth_mode: Optional[str]) -> None   # 360
    def is_app_only(self) -> bool                       # 365
    def get_user_context(self, user_id: Optional[str] = None)   # 372
    def connection(self)                                # 403 (sync: _start_, processing_credentials, credential, graph client)
    def user_auth(self, username, password, scopes=None) -> Dict   # 475 (ROPC)
    def acquire_token(self, scopes=None) -> Dict        # 562 (client credentials; sync)
    def acquire_token_on_behalf_of(self, user_assertion, scopes=None) -> Dict   # 621
    async def close(self)                               # 709
    async def interactive_login(self, scopes=None, redirect_uri="http://localhost", open_browser=True, login_callback=None, device_flow_callback=None) -> Dict   # 763
    async def ensure_interactive_session(self, scopes=None)   # 923

# packages/ai-parrot/src/parrot/interfaces/sharepoint.py
class SharepointClient(O365Client):                     # 32
    __init__ (:40) — _default_* from SHAREPOINT_TENANT_ID/APP_ID/APP_SECRET/TENANT_NAME (:44-47); small_file_threshold 4 MiB :56; chunk_size 10 MiB :57; _site_id/_drive_id/_site_info/_drive_info :60-63
    def _start_(self, **kwargs)                         # 72 — site_url/url from self.tenant + self.site
    async def verify_sharepoint_access(self)            # 96
    async def _detect_and_resolve_subsite(self) -> tuple[str, str]   # 120
    async def _resolve_site(self) -> DriveItem          # 174 — sites.by_site_id(f"{tenant}.sharepoint.com:/sites/{site}")
    def _parse_directory_path(self, directory: str) -> tuple[str, str]   # 208 — default "Documents"; "Shared Documents" alias :237
    async def _resolve_drive(self, library_name: str = None) -> DriveItem   # 242
    async def _ensure_folder(self, folder_path: str, create: bool = True, drive_id: str = None) -> DriveItem   # 298
    async def _upload_small_file(self, drive_id, parent_id, local_path, target_name)   # 372
    async def _create_upload_session(self, drive_id: str, parent_id: str, target_name: str) -> UploadSession   # 390
    async def _upload_large_file(self, upload_session: UploadSession, local_path) -> DriveItem   # 408-470 — aiohttp.ClientSession chunk PUTs :417, Retry-After handling inside the 202 branch
    def _to_colon_id(self, directory: str, name: str) -> str   # 556
    async def upload_files(self, filenames=None, destination=None, destination_filenames=None) -> List[Dict]   # 565
    async def close(self)                               # 859
    def _pattern_is_api_safe(self, pattern: str) -> bool   # 867
    async def download_found_files(self, found) -> List[Dict[str, str]]   # 880 (writes into self.directory)
    async def file_search(self) -> List[Dict]           # 968 (stateful: self.directory/self.filename)
    async def file_lookup(self, files=None) -> List[Dict]   # 1311
    # NO file_list / file_delete / copy / createLink methods; `import httpx` :11 unused

# packages/ai-parrot/src/parrot/interfaces/onedrive.py
class OneDriveClient(O365Client):                       # 25
    __init__ (:48) — small_file_threshold :57, chunk_size :58, _drive_id :61, `self._drive_info: Optional[DriveItem] = None` :62
    async def verify_onedrive_access(self)              # 77
    async def _resolve_drive(self) -> DriveItem         # 88 — graph_client.me.drive.get() only, no user parameter
    async def _ensure_folder(self, folder_path: str, create: bool = True) -> DriveItem   # 108
    async def file_list(self, folder_path: str = None) -> List[dict]   # 167
    async def file_search(self, search_query: str) -> List[dict]       # 211
    async def file_download(self, item_id: str, destination: Path) -> str   # 244 (by item id)
    async def file_delete(self, item_id: str) -> bool   # 364
    async def upload_file(self, file_path: Path, destination_folder: str = None) -> dict   # 393
    async def _upload_small_file(:588) / _create_upload_session(:604) / _upload_large_file(:621) / _upload_large_file_content(self, upload_session, content: bytes, file_name: str) -> DriveItem (:677)
    async def close(self)                               # 818
    # `import httpx` :10 unused

# packages/ai-parrot-tools/src/parrot_tools/o365/base.py
class O365AuthMode: DIRECT="direct"; OBO="on_behalf_of"; DELEGATED="delegated"; CACHED="cached"   # 22-27
class O365ToolArgsSchema(AbstractToolArgsSchema): auth_mode :32; user_assertion :36; user_id :40
class O365Tool(AbstractTool):                           # 49
    def __init__(self, credentials: Optional[Dict] = None, default_auth_mode=O365AuthMode.DIRECT, scopes=None, **kwargs)   # 85
    async def _get_client(self, auth_mode=None, user_assertion=None, scopes=None) -> O365Client   # 111 — cache key f"{auth_mode}_{user_assertion or 'none'}" :130; builds `O365Client(credentials=client_credentials)` :148; processing_credentials + set_auth_mode :151-152; direct → run_in_executor(acquire_token) :157-162; obo → acquire_token_on_behalf_of :164-171; delegated → interactive_login / ensure_interactive_session :173-178; cached → ensure_interactive_session :179-182
    async def _execute_graph_operation(self, client: O365Client, **kwargs) -> Any   # 200 (abstract hook)
    async def _execute(self, **kwargs) -> ToolResult    # 219 — pops auth_mode/user_assertion, calls _get_client (:262), then _execute_graph_operation(client, **kwargs)

# packages/ai-parrot-tools/src/parrot_tools/o365/sharepoint.py
imports :11-18 (incl. `from parrot.interfaces.sharepoint import SharepointClient` :18)
class ListSharePointFilesArgs(:25) site/library="Documents"/folder_path=""/recursive=False; class ListSharePointFilesTool(O365Tool) :36 name "list_sharepoint_files"; _execute_graph_operation(self, client: SharepointClient, **kwargs) :72 — sets client.site/credentials["tenant"] :90-91, verify_sharepoint_access :100, _resolve_drive(library) :101, items.by_drive_item_id(f"root:/{folder_path}:") :107, children.get() :121; _list_recursive :155
class SearchSharePointFilesArgs(:193) site/query/library/folder_path/file_extension/max_results=20; SearchSharePointFilesTool :204 name "search_sharepoint_files"; _execute_graph_operation :239
class DownloadSharePointFileArgs(:313) site/library/file_path/local_destination/rename_as; DownloadSharePointFileTool :325 name "download_sharepoint_file"; _execute_graph_operation :360 (client.file_lookup :411, download_found_files :417)
class UploadSharePointFileArgs(:446) site/local_file_path/library/folder_path/rename_as/overwrite=True; UploadSharePointFileTool :459 name "upload_sharepoint_file"; _execute_graph_operation :495 (client.upload_files :535)
class DeltaSharePointFilesArgs :596 / DeltaSharePointFilesTool :656 — OUT OF SCOPE (FEAT-539)

# packages/ai-parrot-tools/src/parrot_tools/o365/onedrive.py
imports :11-18 (incl. `from parrot.interfaces.onedrive import OneDriveClient` :18; `import shutil` :13)
ListOneDriveFilesArgs :25 folder_path/recursive; ListOneDriveFilesTool :34 name "list_onedrive_files"; _execute_graph_operation :61 (verify_onedrive_access :79, client.file_list :86)
SearchOneDriveFilesArgs :126 query/max_results; SearchOneDriveFilesTool :133 name "search_onedrive_files"; _execute_graph_operation :158 (client.file_search :179)
DownloadOneDriveFileArgs :199 file_path/file_id/local_destination/rename_as; DownloadOneDriveFileTool :213 name "download_onedrive_file"; _execute_graph_operation :250 (file_id path :286-292; file_path via file_search on basename :299)
UploadOneDriveFileArgs :338 local_file_path/folder_path/rename_as; UploadOneDriveFileTool :348 name "upload_onedrive_file"; _execute_graph_operation :379 (client.upload_file :418)
DeltaOneDriveFilesArgs :474 / DeltaOneDriveFilesTool :522 — OUT OF SCOPE (FEAT-539)

# packages/ai-parrot-tools/src/parrot_tools/o365/bundle.py — plain classes (NOT AbstractToolkit)
SharePointToolkit(:27).__init__(client_id, client_secret=None, tenant_id=None, default_auth_mode=O365AuthMode.DIRECT, scopes=None, **kwargs) :52; OneDriveToolkit :131/:156; Office365FileManagementToolkit :235/:255; factories :378/:394/:410

# packages/ai-parrot-tools/src/parrot_tools/o365/delta.py — reference for retry semantics (do not modify)
def _status_code_of(error: BaseException) -> Optional[int]   # 487
def _retry_after_seconds(error: BaseException) -> Optional[float]   # 499
RETRYABLE_STATUS_CODES / DEFAULT_MAX_RETRIES / DEFAULT_INITIAL_BACKOFF / DEFAULT_MAX_BACKOFF (module constants; __all__ :1266)
```

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `GraphDriveFileManager.connect()` | `O365Client.processing_credentials()`, `set_auth_mode()`, `acquire_token()` / `acquire_token_on_behalf_of()` / `interactive_login()` / `ensure_interactive_session()` | same branches as `O365Tool._get_client` | `parrot_tools/o365/base.py:151-182`; `o365.py:218, 360, 562, 621, 763, 923` |
| `GraphDriveFileManager.*` | `O365Client.graph_client.drives.by_drive_id(id).items.by_drive_item_id(ref)` | msgraph request builders | pattern at `parrot_tools/o365/sharepoint.py:105-123` |
| `GraphDriveFileManager._put_session` | `SharepointClient._create_upload_session` / `OneDriveClient._create_upload_session`; chunk PUT pattern | method calls; aiohttp | `sharepoint.py:390, 408-470`; `onedrive.py:604, 677` |
| `GraphDriveFileManager.close()` | `O365Client.close()` | await | `o365.py:709` |
| `GraphDriveFileManager.setup()` | `FileServingExtension(manager, route, manager_name)` | constructor + `setup(app)` | `navigator/utils/file/web.py:48, 78`; parity `s3.py:613` |
| `SharePointFileManager._resolve_drive_id` | `SharepointClient.verify_sharepoint_access()`, `_resolve_drive(library)` | await | `sharepoint.py:96, 242` |
| `OneDriveFileManager._resolve_drive_id` | `OneDriveClient._resolve_user_drive(user)` (M2), `O365Client.is_app_only()` | await / call | `onedrive.py:88 (insert after)`; `o365.py:365` |
| `FileManagerFactory.create("sharepoint")` | `parrot.interfaces.file.sharepoint.SharePointFileManager` | importlib (local map) | `filemanager.py:38-62` |
| `FileManagerToolkit.batch_upload` | `manager.upload_files` if `hasattr`, else `manager.upload_file` loop | duck typing | `filemanager.py:719` |
| `ListSharePointFilesTool` etc. | `SharePointFileManager.adopt_client(client)` + `list_files/find_files/download_file/upload_file` | method calls | `parrot_tools/o365/sharepoint.py:72, 239, 360, 495` |
| `ListOneDriveFilesTool` etc. | `OneDriveFileManager` same | method calls | `parrot_tools/o365/onedrive.py:61, 158, 250, 379` |
| Response dict keys to preserve | List SP `{site,library,folder_path,total_items,files[{name,path,is_folder,size,modified,web_url,id}],recursive}`; Search SP `{site,query,library,folder_path,file_extension,total_results,files[{name,path,size,modified,web_url,id}]}`; Download SP `{site,library,file_path,local_path,download_url,size}`; Upload SP `{site,library,folder_path,uploaded_file,size,web_url,server_relative_url}`; List OD `{folder_path,total_items,files,recursive}`; Search OD `{query,total_results,files}`; Download OD `{file_path,file_id,local_path,size}`; Upload OD `{folder_path,uploaded_file,file_id,size,web_url}` | — | `sharepoint.py:126-146, 282-301, 427-434, 546-553`; `onedrive.py:90-95, 187, 321-326, 426-431` |

### Does NOT Exist (Anti-Hallucination)
- ~~`parrot.interfaces.file.graph`~~ / ~~`.sharepoint`~~ / ~~`.onedrive`~~ — the directory holds only `__init__.py, abstract.py, gcs.py, local.py, s3.py, tmp.py` (re-export shims). Created by M1/M3/M4.
- ~~`GraphDriveFileManager`~~, ~~`SharePointFileManager`~~, ~~`OneDriveFileManager`~~, ~~`BatchItemResult`~~, ~~`BatchSummary`~~, ~~`GraphFileManagerError`~~, ~~`adopt_client`~~ — nowhere in the repo or navigator-api; all introduced here.
- ~~`navigator.utils.file.msgraph`~~ / ~~`.sharepoint`~~ — navigator-api 4.0.0 ships only `abstract, factory, gcs, local, s3, tmp, web`.
- ~~`FileManagerFactory.create("sharepoint")`~~ — raises `ValueError` today on both factories; ~~`FileManagerFactory._LAZY_MANAGERS`~~ on the parrot-side class (only `_PARROT_TO_UPSTREAM`).
- ~~`SharepointClient.file_list`~~, ~~`.file_delete`~~, ~~`.get_file_url`~~, ~~`.copy_file`~~, ~~`._ensure_drive_config`~~, ~~`._resolve_user_drive`~~, ~~`.drive_type`~~, ~~`.onedrive_user`~~ — the last four exist only in the flowtask copy.
- ~~`OneDriveClient._resolve_user_drive`~~, ~~`OneDriveClient(user=...)`~~, ~~`OneDriveClient.onedrive_user`~~ — added by M2.
- ~~`O365Tool._get_client` returning `SharepointClient`/`OneDriveClient`~~ — it returns a plain `O365Client` (`base.py:148`).
- ~~`S3FileManager.upload_files` / `.download_files`~~ and ~~`FileManagerInterface.upload_file_from_bytes`~~ — no batch API upstream; `upload_file_from_bytes` is S3-only.
- ~~`SharePointToolkit(AbstractToolkit)`~~ — bundle toolkits are plain classes.
- ~~`O365Client.aclose()`~~ — the method is `async def close()` (`o365.py:709`).
- ~~`S3FileManager.__init__(aws_config=...)`~~ — no such kwarg (FEAT-162 F005).
- ~~`FileManagerToolkit.find_files` / `.batch_upload` / `.batch_download`~~, ~~`operation="find"`~~ — added by M6.
- ~~`GraphDriveFileManager.create_sharing_link` / `.list_entries` / `.adopt_client` / `._validate_graph_url` / `._iter_children`~~, ~~`DriveEntry`~~, ~~`OneDriveClient._user_drives`~~ — all introduced by this spec (design research S1–S9); none exist today.
- ~~`FileServingExtension` streaming from the remote~~ — it buffers the whole object into `io.BytesIO` for both full and Range responses (`web.py:229-232, 257-259`); do not describe `setup()` as streaming.
- ~~`DriveItemCollectionResponse.next_link`~~ — the attribute is `odata_next_link` (msgraph `base_collection_pagination_count_response.py:18`); follow it with `ChildrenRequestBuilder.with_url(raw_url)` (`children_request_builder.py:120`).
- ~~`ai-parrot[msgraph]` extra~~ — pins currently live only in `agents` (`pyproject.toml:440-442`); added by M9.
- ~~`PARROT_LIVE_*` settings in `parrot/conf.py`~~ — test-only env knobs read by M10 via `os.environ`, never added to conf.
- ~~`packages/ai-parrot/tests/interfaces/conftest.py`~~ — does not exist yet (directory has `__init__.py` + tests only); M0 creates it.

### Edit Sites (Blueprint Anchors)

Verified against: `42029db04` (dev, 2026-09-25)

| File | Action | Verbatim anchor line | Verified at | Occurrences |
|---|---|---|---|---|
| `packages/ai-parrot/src/parrot/interfaces/file/graph.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/interfaces/file/sharepoint.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/interfaces/file/onedrive.py` | CREATE | — | — | — |
| `packages/ai-parrot/tests/interfaces/_graph_fakes.py` | CREATE | — | — | — |
| `packages/ai-parrot/tests/interfaces/conftest.py` | CREATE | — | — | — |
| `packages/ai-parrot/tests/interfaces/test_graph_filemanager.py` | CREATE | — | — | — |
| `packages/ai-parrot/tests/interfaces/test_onedrive_client_user_drive.py` | CREATE | — | — | — |
| `packages/ai-parrot/tests/interfaces/test_sharepoint_filemanager.py` | CREATE | — | — | — |
| `packages/ai-parrot/tests/interfaces/test_onedrive_filemanager.py` | CREATE | — | — | — |
| `packages/ai-parrot/tests/interfaces/test_graph_filemanager_live.py` | CREATE | — | — | — |
| `packages/ai-parrot/tests/tools/test_filemanager_batch_ops.py` | CREATE | — | — | — |
| `packages/ai-parrot-tools/tests/test_o365_file_tools_refactor.py` | CREATE | — | — | — |
| `packages/ai-parrot/tests/test_msgraph_extra.py` | CREATE | — | — | — |
| `docs/interfaces/graph-filemanager.md` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/interfaces/onedrive.py` | MODIFY | `        self._drive_info: Optional[DriveItem] = None` | `onedrive.py:62` | 1 |
| `packages/ai-parrot/src/parrot/interfaces/onedrive.py` | MODIFY | `    async def _resolve_drive(self) -> DriveItem:` | `onedrive.py:88` | 1 |
| `packages/ai-parrot/src/parrot/interfaces/file/__init__.py` | MODIFY | `__all__ = (` | `file/__init__.py:25` | 1 |
| `packages/ai-parrot/src/parrot/interfaces/file/__init__.py` | MODIFY | `_LAZY_MANAGERS = {` | `file/__init__.py:34` | 1 |
| `packages/ai-parrot-tools/src/parrot_tools/file/__init__.py` | MODIFY | `    if name in ("S3FileManager", "GCSFileManager"):` | `parrot_tools/file/__init__.py:21` | 1 |
| `packages/ai-parrot/src/parrot/tools/filemanager.py` | MODIFY | `    _PARROT_TO_UPSTREAM = {` | `filemanager.py:30` | 1 |
| `packages/ai-parrot/src/parrot/tools/filemanager.py` | MODIFY | `        manager_type: Literal["fs", "temp", "s3", "gcs"],` (factory `create`, preceded by `    def create(` at :38) | `filemanager.py:39` | 3 (ambiguous — use the `def create(` context) |
| `packages/ai-parrot/src/parrot/tools/filemanager.py` | MODIFY | `        manager_type: Literal["fs", "temp", "s3", "gcs"] = "fs",` inside `class FileManagerTool` after `    def __init__(` (:172) and `        self,` (:173) | `filemanager.py:174` | 3 (ambiguous — context: `class FileManagerTool(AbstractTool):` block) |
| `packages/ai-parrot/src/parrot/tools/filemanager.py` | MODIFY | `        manager_type: Literal["fs", "temp", "s3", "gcs"] = "fs",` inside `class FileManagerToolkit` after `    def __init__(` (:549) and `        self,` (:550) | `filemanager.py:551` | 3 (ambiguous — context: `class FileManagerToolkit(AbstractToolkit):` block) |
| `packages/ai-parrot/src/parrot/tools/filemanager.py` | MODIFY | `    description: str = "Manage files across different storage backends (local, S3, GCS, temp)"` | `filemanager.py:169` | 1 |
| `packages/ai-parrot/src/parrot/tools/filemanager.py` | MODIFY | `    operation: Literal[` | `filemanager.py:72` | 1 |
| `packages/ai-parrot/src/parrot/tools/filemanager.py` | MODIFY | `            elif operation == "create":` (dispatch in `FileManagerTool._execute`) | `filemanager.py:291` | 1 |
| `packages/ai-parrot/src/parrot/tools/filemanager.py` | MODIFY | `_OP_TO_METHOD: Dict[str, str] = {` | `filemanager.py:501` | 1 |
| `packages/ai-parrot/src/parrot/tools/filemanager.py` | MODIFY | `    async def create_file(` (toolkit; last public method, new methods appended after its body) | `filemanager.py:947` | 1 |
| `packages/ai-parrot-tools/src/parrot_tools/o365/sharepoint.py` | MODIFY | `from parrot.interfaces.sharepoint import SharepointClient` | `o365/sharepoint.py:18` | 1 |
| `packages/ai-parrot-tools/src/parrot_tools/o365/sharepoint.py` | MODIFY | `class ListSharePointFilesTool(O365Tool):` | `o365/sharepoint.py:36` | 1 (the bare prefix `class ListSharePointFile` matches 2 — Args + Tool; use the full line) |
| `packages/ai-parrot-tools/src/parrot_tools/o365/sharepoint.py` | MODIFY | `class SearchSharePointFilesTool(O365Tool):` | `o365/sharepoint.py:204` | 1 |
| `packages/ai-parrot-tools/src/parrot_tools/o365/sharepoint.py` | MODIFY | `class DownloadSharePointFileTool(O365Tool):` | `o365/sharepoint.py:325` | 1 |
| `packages/ai-parrot-tools/src/parrot_tools/o365/sharepoint.py` | MODIFY | `class UploadSharePointFileTool(O365Tool):` | `o365/sharepoint.py:459` | 1 |
| `packages/ai-parrot-tools/src/parrot_tools/o365/onedrive.py` | MODIFY | `from parrot.interfaces.onedrive import OneDriveClient` | `o365/onedrive.py:18` | 1 |
| `packages/ai-parrot-tools/src/parrot_tools/o365/onedrive.py` | MODIFY | `class ListOneDriveFilesTool(O365Tool):` | `o365/onedrive.py:34` | 1 |
| `packages/ai-parrot-tools/src/parrot_tools/o365/onedrive.py` | MODIFY | `class SearchOneDriveFilesTool(O365Tool):` | `o365/onedrive.py:133` | 1 |
| `packages/ai-parrot-tools/src/parrot_tools/o365/onedrive.py` | MODIFY | `class DownloadOneDriveFileTool(O365Tool):` | `o365/onedrive.py:213` | 1 |
| `packages/ai-parrot-tools/src/parrot_tools/o365/onedrive.py` | MODIFY | `class UploadOneDriveFileTool(O365Tool):` | `o365/onedrive.py:348` | 1 |
| `packages/ai-parrot/pyproject.toml` | MODIFY | `agents = [` (new `msgraph = [` block inserted before it) | `pyproject.toml:395` | 1 |
| `packages/ai-parrot/pyproject.toml` | MODIFY | `    "ai-parrot[agents,images,llms,integrations,db,bigquery,pdf,ocr,audio,finance,flowtask,reddit,mcp,charts,docling,visualizations,rust]",` (inside the first `all = [` at :875) | `pyproject.toml:876` | 1 (`all = [` itself occurs 2×) |
| `docs/integrations/office365-oauth2.md` | MODIFY | `## Required delegated scopes` | `office365-oauth2.md:39` | 1 |
| `packages/ai-parrot/tests/interfaces/test_file_shim.py` | MODIFY | `def test_lazy_identity():` | `test_file_shim.py:42` | 1 |
| `packages/ai-parrot/tests/interfaces/test_file_shim.py` | MODIFY | `def test_factory_unknown_type_raises_valueerror():` | `test_file_shim.py:90` | 1 |

Files explicitly NOT touched: `packages/ai-parrot/src/parrot/interfaces/sharepoint.py`,
`packages/ai-parrot/src/parrot/interfaces/o365.py`,
`packages/ai-parrot-tools/src/parrot_tools/o365/delta.py`,
`packages/ai-parrot-tools/src/parrot_tools/o365/bundle.py`,
`packages/ai-parrot-tools/src/parrot_tools/o365/base.py`.

---

## 7. Implementation Notes & Constraints

> Architecture decisions stay with the thinking model. A delegated
> implementation may only express a decision already recorded here and in
> the TASK's implementation blocks — it must never invent an API, choose a
> file, or resolve an open design question.

### Patterns to Follow
- **S3 parity first**: `_prefixed`/`_unprefixed`/`_make_metadata`/`upload_file_from_bytes`/`setup` mirror `navigator/utils/file/s3.py:120-135, 571, 613`. When in doubt about a return value (e.g. `download_file` to `BinaryIO` returns `Path(source)`), do what S3 does.
- **Graph addressing**: always `drives.by_drive_id(drive_id).items.by_drive_item_id("root:/<path>:")` for path lookups and `.items.by_drive_item_id(item.id)` for follow-up calls (children, content, copy, create_link, delete, patch) — the pattern at `parrot_tools/o365/sharepoint.py:105-123`. URL-quote each segment separately; keep `/` (`SharepointClient._to_colon_id`, `sharepoint.py:556`).
- **Uploads**: below `SMALL_FILE_THRESHOLD` → `items.by_drive_item_id(f"{parent_id}:/{name}:").content.put(bytes)` with `@microsoft.graph.conflictBehavior` in the request configuration; at/above → `create_upload_session` body `DriveItemUploadableProperties(additional_data={"@microsoft.graph.conflictBehavior": ...})` (as `sharepoint.py:390-406`) and aiohttp chunk PUTs with `Content-Range`, honouring `Retry-After` on 202/429 (as `sharepoint.py:417-467`).
- **Auth**: reproduce `O365Tool._get_client` branch-for-branch (`base.py:151-182`); sync `acquire_token*` run through `loop.run_in_executor`; `connect()` idempotent; `adopt_client()` skips authentication entirely.
- **Retry policy (S5)**: ONE `_retrying` policy wraps both SDK calls (in addition to kiota's `RetryHandler`) and raw aiohttp paths (chunk PUT, monitor poll, download stream) with the same status set and `Retry-After` parsing semantics as `delta.py:487-539` (re-implemented locally; **no import from `parrot_tools`** inside `parrot.interfaces` — core must not depend on the tools distribution). Non-idempotent requests (copy POST, upload-session creation) run with `idempotent=False` and are never retried; the existing client code's "Retry-After only on 202" (`sharepoint.py:455-458`) is not the model.
- **Outbound URL boundary (S6)**: `_validate_graph_url` runs before every aiohttp call; pattern is `delta.py:387` `validate_continuation_link` (structural validation of a remote-supplied URL before dereferencing). Never log these URLs; never attach the bearer token; `allow_redirects=False`.
- **Pagination (S4)**: every `.children.get()` / `search_with_q(q).get()` goes through `_iter_children` / `_iter_search`; a single-page call is a bug, not an optimisation.
- **Folders vs files (S8)**: `list_files` → files only; `list_entries` → `DriveEntry` with `is_folder`; the tools use `list_entries` so their `is_folder` field survives the refactor.
- **Client injection (S1)**: tools call `adopt_client(client)` with the `O365Tool._get_client` result and never construct or authenticate a second client; direct users call `connect()`. `close()` closes only clients the manager built.
- **Batch engine**: `asyncio.Semaphore(max_concurrency)` + `asyncio.gather(..., return_exceptions=True)`; build results in input order; the first 401/403 sets an `asyncio.Event` that makes pending items short-circuit with `error="aborted after authentication failure"`.
- **Errors**: `FileNotFoundError` for 404 on reads, `PermissionError` for policy-denied sharing scopes, `TimeoutError` for copy monitors, `ValueError` for bad paths (`..`), `GraphFileManagerError(status_code=...)` for everything else. Never let a kiota `APIError` escape unwrapped from a public method.
- **Toolkit fallback** (M6): `hasattr(self.manager, "upload_files")` decides native vs. looped batch; both paths produce `BatchSummary`. `find_files` always calls `self.manager.find_files` (the interface default exists on every backend).
- **Tool refactor** (M7/M8): keep `name`, `description`, `args_schema`, and response keys; delete the inline Graph walks; do not touch the Delta classes or their imports (`DEFAULT_MAX_PAGES`, `DriveDeltaHelper` stay imported because the Delta tools use them).
- **Lazy imports**: the shims must not import `parrot.interfaces.file.graph` at module import (it imports msgraph). Only `__getattr__` triggers the import.
- Google-style docstrings, strict typing, `self.logger = logging.getLogger(__name__)`, aiohttp only, Pydantic v2, black 120.
- **Worktree testing**: `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-tools/src` before `pytest` inside a worktree (rule in `.claude/rules/worktree-management.md` §4).

### Known Risks / Gotchas
- **`O365Client.__init__` opens a Redis client object** (`o365.py:198-200`, `aioredis.from_url`) — constructing a manager therefore needs `REDIS_HISTORY_URL` resolvable in config; connection is lazy, but `close()` must run to avoid warnings. Tests use `adopt_client` with fakes and never construct a real client.
- **`_get_client` returns `O365Client`, not the drive clients** (`base.py:148`) — `adopt_client` must accept a plain `O365Client`; the manager builds its own `SharepointClient`/`OneDriveClient` from `client.credentials` and copies the authenticated `_credential`/`_graph_client`/`auth_mode` so no second token acquisition happens (AC3). Blueprint detail, contract fixed.
- **`ListSharePointFilesTool` sets `client.credentials["tenant"] = site`** (`parrot_tools/o365/sharepoint.py:91`) — a legacy quirk; the manager takes `site` and `tenant` separately and must not replicate it.
- **Hidden mutable input in sub-site detection (S2)**: `SharepointClient._detect_and_resolve_subsite` reads `self._srcfiles[0]["directory"]` and rewrites every `_srcfiles` entry (`sharepoint.py:128-166`). The manager leaves `_srcfiles` empty (no-op path, returns `(self.site, "")`), expresses sub-sites in `site`, and AC23 tests the invariant.
- **`FileServingExtension` buffers whole objects (S7)** — `web.py:229-232` (Range) and `:257-259` (full) call `download_file(path, BytesIO())`; `serving_max_bytes` (AC22) bounds memory. A true streaming/range implementation is an open question (§8 Q4), not a v1 promise.
- **`OneDriveClient` single-slot caches (S9)** — `_drive_id`/`_drive_info` are per-client, not per-user; the ported `_resolve_user_drive` uses its own `_user_drives` dict and the manager caches its own `_drive_id`.
- **Graph `copy` is asynchronous** (202 + `Location` monitor URL) — poll with aiohttp; the SDK returns no body.
- **Sharing-link policy**: `expirationDateTime` on `createLink` is rejected by some tenants (400 `invalidRequest`) and `anonymous` scope may be disabled — handle as in AC7; do not retry these.
- **`@microsoft.graph.downloadUrl` is short-lived (~1 h) and pre-authenticated** — never expose it as `get_file_url`; use it only inside `download_file`.
- **Path characters**: `#`, `%`, `:` in names must be quoted per segment; `..` rejected; `"Shared Documents"` normalised by the client.
- **`exists()` is true for folders** — documented; `get_file_metadata` on a folder returns `size=0`, `content_type=None`.
- **Upload session interrupted** → `GraphFileManagerError` with the byte offset; Graph discards incomplete sessions, no partial file is left.
- **Unused `import httpx`** in the two clients stays (out of scope) but ruff TID251 bans it in new/modified modules — do not copy those import blocks.
- **Ledger/FEAT-539 overlap**: `parrot_tools/o365/{sharepoint,onedrive}.py` also host the Delta tools; M7/M8 tasks must diff-check that the Delta class blocks are unchanged (AC13 test).
- **`FileManagerToolkit` tool generation** reads `exclude_tools` before `super().__init__()` (`filemanager.py:590-598`) — adding methods means also adding their `_OP_TO_METHOD` entries or they will be exposed even when `allowed_operations` excludes them.
- **`tests/tools/test_filemanager_toolkit.py`** stubs `FileManagerFactory.create` (`:68`) — keep the factory `create` signature `(manager_type, **kwargs)`.
- **pytest hang after summary** (leaked non-daemon threads) — wrap full-suite runs in `timeout -s KILL`; `O365Client._executor` (`ThreadPoolExecutor`, `o365.py:184`) must be shut down in `close()` paths the tests exercise.

### External Dependencies
| Package | Version | Reason |
|---|---|---|
| `msgraph-sdk` | `>=1.8.0` (installed 1.63.0) | drive-item request builders, `createLink`, `createUploadSession`, `copy`, `search`; already in `agents` extra, mirrored into new `msgraph` extra |
| `azure-identity` | `>=1.18.0` (1.25.3) | credentials used by `O365Client._create_credential` |
| `microsoft-kiota-authentication-azure` | `>=1.2.0` | Graph auth provider (existing pin) |
| `microsoft-kiota-http` | transitive (1.13.0) | `RetryHandler` middleware in the default pipeline |
| `aiohttp` | existing (3.14.3) | chunk PUTs, monitor polling, download streaming |
| `aiofiles` | existing | chunked local reads/writes |
| `navigator-api` | `>=3.2.2` (4.0.0) | `FileManagerInterface`, `FileMetadata`, `FileServingExtension` |
| `pydantic` | v2 (existing) | `BatchItemResult`, `BatchSummary` |

---

## 8. Open Questions

> Questions that must be resolved before or during implementation.

- [x] Feature or hotfix, and base branch? — *Resolved in brainstorm*: feature on `dev`.
- [x] Where do the managers live and do they reuse the existing clients? — *Resolved in brainstorm*: ai-parrot core, `parrot/interfaces/file/`, composing `SharepointClient`/`OneDriveClient`.
- [x] One class or two? — *Resolved in brainstorm*: two (`SharePointFileManager`, `OneDriveFileManager`) on a shared `GraphDriveFileManager` base; drive-relative paths.
- [x] Auth modes in v1? — *Resolved in brainstorm*: app-only client credentials, delegated/OBO, and username/password (all existing `O365Client` modes).
- [x] `get_file_url` semantics? — *Resolved in brainstorm*: Graph `createLink` sharing link (organization scope default, expiry when allowed).
- [x] Whose OneDrive, and backport flowtask's drive-targeting? — *Resolved in brainstorm*: any user's drive + `me`; port `_resolve_user_drive` into `OneDriveClient`; do not port the `SharepointClient` `drive.type` shim.
- [x] Batch failure semantics? — *Resolved in brainstorm*: per-item results, never raise mid-batch, bounded concurrency.
- [x] Registration surfaces? — *Resolved in brainstorm*: all four — shim re-exports, factory/tool/toolkit literals, O365 toolkit refactor, HTTP serving `setup()`.
- [x] Verification strategy? — *Resolved in brainstorm*: mocked unit tests in CI + opt-in env-gated live suite run manually before `/sdd-done`.
- [x] Should `FileManagerToolArgs.operation` / the toolkit gain `find` / `batch_upload` / `batch_download`? — *Resolved at spec time (owner)*: yes, all three, with a generic looped fallback for backends lacking native batch methods (M6).
- [x] Dedicated `ai-parrot[msgraph]` extra? — *Resolved at spec time (owner)*: yes, add `msgraph` and include it in `all` (M9).
- [x] Upload conflict default and kwarg? — *Resolved at spec time (owner did not object to the assumption)*: `conflict_behavior="replace"` default, `fail` / `rename` via constructor kwarg.
- [x] Sharing-link defaults? — *Resolved at spec time*: `link_type="view"`, `link_scope="organization"`, `expiry <= 0` → no expiration.
- [x] Batch concurrency / retry defaults? — *Resolved at spec time*: `max_concurrency=5`, `max_retries=3`, retryable `{429, 503, 504}`; overridable per manager.
- [x] `manager_name` values? — *Resolved at spec time*: `"sharepointfile"` / `"onedrivefile"` (S3's `"s3file"` convention).
- [ ] Q1. Live-gate tenant: confirm the site/library and OneDrive user the live suite may write to under `parrot-live/<uuid>/`, and that `PARROT_LIVE_GRAPH`, `PARROT_LIVE_SHAREPOINT_SITE`, `PARROT_LIVE_SHAREPOINT_LIBRARY`, `PARROT_LIVE_ONEDRIVE_USER` are acceptable knob names (they stay test-only env vars, not `parrot.conf` settings). — *Owner: Jesus* (M10 can proceed with the proposed names; only the target values block AC18).
- [ ] Q2. After this feature, should flowtask's `SharepointClient` drop its `drive.type=onedrive` shim in favour of `OneDriveFileManager`? — *Owner: Jesus* (separate repository follow-up; does not block).
- [ ] Q3. Should `FileManagerToolkit.batch_upload` accept in-memory payloads (`{"content_b64": ...}`) for agent-generated files, or only local paths in v1? — *Owner: Jesus* (spec assumes local paths only; bytes go through `fs_create_file` / direct manager use).
- [ ] Q4. (Escalated from design research S7) `FileServingExtension` buffers whole objects in memory; v1 ships a `serving_max_bytes` guard (AC22). Should this feature also add a streaming, range-aware serving path for Graph (a `GraphFileServingExtension` subclass in core that streams `downloadUrl` with `Range` headers), or is the guard acceptable until navigator-api adds a seekable download interface? — *Owner: Jesus* (does not block M1–M9; if "yes", it becomes an extra module).

---

## 9. Design Research Cross-Check

> Independent design opinion from the `codex` seat over the **accepted exploration
> doc** (never over this spec). Model: `gpt-5.6-luna` (codex-cli 0.156.1, reasoning high, 4 m 16 s) · Status: completed
> · Transcript: `sdd/state/FEAT-603/design_research/`
> Every `affected_paths` entry passed repository containment and `test -e`; the three
> source-level claims (S2, S4, S7) were re-read in the cited files before disposition.
> S2's `rationale` text is truncated in `suggestions.json` (the reviewer's output cut off
> mid-sentence); its claim was verified directly from `sharepoint.py:120-172`.

| # | Suggestion (kind) | Disposition | Reason | Landed in |
|---|---|---|---|---|
| S1 | Define an authenticated-client injection boundary (architecture) | CONFIRM | `O365Tool._get_client` returns a plain `O365Client` (base.py:148) while the drive helpers live on the subclasses; the brainstorm left "one authentication" implicit. Fixed as `adopt_client(client)` on the base with a copy-over contract and "close() never closes an adopted client". | §3 M1 `adopt_client`, M7/M8, §7 "Client injection", AC3 |
| S2 | Remove SharePoint site resolution's hidden mutable input (architecture) | CONFIRM | Verified: `_detect_and_resolve_subsite` reads `_srcfiles[0]["directory"]` and rewrites `_srcfiles` (sharepoint.py:128-166). The brainstorm's "sub-site detection for free" was wrong. Manager never populates `_srcfiles`; sub-sites via explicit `site="parent/sub"`. | §2 "Site semantics", §3 M3 docstring + `_build_client` invariant, §7 gotcha, AC23 |
| S3 | Keep sharing-link options off the exact interface method (api) | CONFIRM | AC1 demands signature parity with `abstract.py:67`; options belong on an extension. `create_sharing_link(path, *, link_type, scope, expiry)` added; `get_file_url(path, expiry)` is the wrapper. | §2 defaults, §2 New Public Interfaces, §3 M1, AC7 |
| S4 | Implement pagination for every list and search operation (risk) | CONFIRM | The existing tools call `.children.get()` once (sharepoint.py:107-121); msgraph exposes `odata_next_link` + `with_url`. `_iter_children` / `_iter_search` mandated; `max_results` after filtering. | §3 M1, §7 "Pagination", AC20, §4 tests |
| S5 | Use one bounded retry policy for SDK and raw HTTP paths (risk) | CONFIRM | Brainstorm split retry between kiota and ad-hoc aiohttp handling; existing client only honours Retry-After on 202. One `_retrying(idempotent=)` policy; copy POST / session creation never retried. | §3 M1 `_retrying`, `copy_file`, §7 "Retry policy", AC21 |
| S6 | Validate copy-monitor URLs before sending credentials (risk) | CONFIRM | Remote-supplied URLs (uploadUrl, monitor, downloadUrl) were dereferenced without a boundary; `delta.py:387` already models the check. `_validate_graph_url` + no auth header + no redirects + never logged. | §2 "Outbound URLs", §3 M1, §7, AC21 |
| S7 | Do not claim streaming while using the existing serving extension unchanged (risk) | CONFIRM (guard) + ESCALATE (streaming) | Verified: `web.py:229-232, 257-259` buffer the object in `BytesIO` for both Range and full responses. v1 adds a `serving_max_bytes` guard (413) and stops calling `setup()` "streaming"; whether to build a streaming subclass is the owner's call. | §3 M1 `setup`/`handle_file`, §7 gotcha, AC22, §8 Q4 |
| S8 | Specify path and folder semantics separately from legacy tool paths (api) | CONFIRM | `FileMetadata` has no folder flag and the tools return folders. `list_files` = files only; new `list_entries` → `DriveEntry(is_folder)`; library-relative tool paths == drive-relative manager paths with `prefix=""`. | §2 "Listing semantics", §2 Data Models, §3 M1/M7, §7 |
| S9 | Make OneDrive user targeting cache-safe (risk) | CONFIRM | `OneDriveClient` has single-slot `_drive_id`/`_drive_info` (onedrive.py:61-62); flowtask's port would overwrite them. Per-user `_user_drives` dict; manager caches its own drive id. | §3 M2 skeleton, §7 gotcha, AC24 |
| S10 | Test batch result and cancellation semantics explicitly (testing) | CONFIRM | "Never raise" vs "abort on auth failure" was ambiguous. `BatchItemResult` gains `index`, `state`, `error_code`; skipped items `attempts=0`; shared `BinaryIO` rejected; cancellation and duplicate-destination tests listed. | §2 Data Models, §3 M1 `upload_files`, §4 tests, AC8 |
| S11 | Preserve lazy-import and optional-dependency guarantees (testing) | CONFIRM | Already decided at spec time (owner: `msgraph` extra) and in the shim design; the explicit lazy-import tests for both managers are listed. | §3 M5/M9, AC10, AC14, §4 |

Summary: **11** confirmed (S7 additionally escalated) · **0** rejected · **1** escalated (S7 → §8 Q4).

---

## Worktree Strategy

- **Isolation**: ONE feature worktree for FEAT-603 (`feat-FEAT-603-sharepoint-filemanager`, from `origin/dev`); the `sdd-coder` engine gives each task its own sub-worktree inside it.
- **Module dependency graph** (edge = import or contract dependency, with evidence):
  - M1 → M0 (M1's tests import `_graph_fakes`; M1 source itself has no dependency on M0)
  - M2 → (none) — additive change to `onedrive.py`
  - M3 → M1 (`from .graph import GraphDriveFileManager`)
  - M4 → M1, M2 (`from .graph import ...`; calls `OneDriveClient._resolve_user_drive`)
  - M5 → M3, M4 (lazy-import targets `parrot.interfaces.file.sharepoint` / `.onedrive` must exist for the shim/factory tests)
  - M6 → M1 (`BatchItemResult`, `BatchSummary` from `graph.py`), M5 (same file `filemanager.py` — serialized, see Shared files)
  - M7 → M3 (`SharePointFileManager`, `adopt_client`)
  - M8 → M4 (`OneDriveFileManager`, `adopt_client`)
  - M9 → (none)
  - M10 → M3, M4
  - **No edge**: M0, M2, M9 are mutually independent and independent of M1 → they run concurrently from day one; M3 ‖ M4 after M1 (M4 also needs M2); M7 ‖ M8 ‖ M10 after M3/M4.
- **Shared files**: `packages/ai-parrot/src/parrot/tools/filemanager.py` is modified by M5 (literals/factory) and M6 (ops) — their tasks are serialized (M5 first). `packages/ai-parrot/src/parrot/interfaces/file/__init__.py` is M5 only. `parrot_tools/o365/sharepoint.py` is M7 only, `parrot_tools/o365/onedrive.py` is M8 only. `test_file_shim.py` is M5 only.
- **Exclusive resources**: `packages/ai-parrot/pyproject.toml` (M9) — its task is `parallel: false` (and `uv.lock` must not be regenerated inside the worktree; the main-checkout operator installs the extra, per `.claude/rules/worktree-management.md` §4). The live suite (M10) shares one real tenant — `parallel: false`, manual run only.
- **Cross-feature dependencies**: none blocking. FEAT-539 (`contracts-card-ontology`, still open) owns `parrot_tools/o365/delta.py` and the Delta tool classes inside the two files M7/M8 edit — those class blocks must stay byte-identical (AC13). No open spec touches `parrot/interfaces/file/`, `parrot/tools/filemanager.py` or `parrot/interfaces/onedrive.py`.
- **Suggested lanes**: Wave 1 = {M0, M2, M9} ‖ M1 ; Wave 2 = {M3, M4} ; Wave 3 = M5 → M6 (serialized) ‖ {M7, M8} ; Wave 4 = M10 (manual live run) + docs polish.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-09-25 | Jesus Lara (with Claude) | Initial draft from brainstorm (Option B); spec-time resolutions for agent ops, `msgraph` extra and defaults; design research S1–S11 folded (adopt_client, explicit sub-site path, create_sharing_link, pagination, unified retry, URL boundary, serving guard, list_entries, per-user cache, batch states) |
