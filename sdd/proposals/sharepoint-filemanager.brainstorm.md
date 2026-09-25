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

# Brainstorm: SharePoint & OneDrive FileManager

**Date**: 2026-09-25
**Author**: Jesus Lara (with Claude)
**Status**: exploration
**Recommended Option**: B

---

## Problem Statement

AI-Parrot has a uniform storage contract — `FileManagerInterface` from
`navigator.utils.file` (navigator-api 4.0.0), implemented by
`LocalFileManager`, `TempFileManager`, `S3FileManager` and `GCSFileManager` —
that agents, `FileManagerToolkit`, report persistence and artifact storage all
program against. Microsoft SharePoint document libraries and OneDrive drives
are **not** behind that contract. Instead the repo carries two parallel,
non-conforming surfaces:

- `parrot/interfaces/sharepoint.py::SharepointClient` and
  `parrot/interfaces/onedrive.py::OneDriveClient` — Graph-SDK clients with
  flowtask-style, stateful method sets (`upload_files`, `file_search`,
  `download_found_files`, `file_lookup`) that configure the target via
  instance attributes (`client.directory`, `client.site`) rather than
  path arguments, and that share almost no method names with each other.
- `parrot_tools/o365/{sharepoint,onedrive}.py` tools that re-implement
  listing/searching/downloading **directly on the raw Graph client** because
  the clients above do not expose those operations in a reusable shape.

Consequences:

1. Nothing that speaks `FileManagerInterface` (the `file_manager` tool,
   `FileManagerToolkit`, `ReportPersistenceMixin`, artifact stores) can target
   SharePoint or OneDrive. Every consumer needs bespoke O365 code.
2. Bytes-in-memory uploads (agent-generated reports, charts, exports) have no
   path to SharePoint at all — `SharepointClient.upload_files` only takes
   local filenames.
3. The flowtask sibling of `SharepointClient` (which the user pointed at as
   the reference) has drifted ahead: it gained `drive: {type, user}` OneDrive
   targeting (`_ensure_drive_config`, `_resolve_user_drive`) that ai-parrot's
   copy lacks, while ai-parrot's `O365Client` gained `set_auth_mode`,
   `is_app_only`, `get_user_context` and an async `close()` that flowtask
   lacks. The two are diverging in both directions.
4. Batch upload/download, sharing-link generation and server-side search
   exist as fragments across the clients and tools but never as a single,
   documented, testable API.

**Who is affected**: agent authors (want `FileManagerToolkit(manager_type=
"sharepoint")`), pipeline/flowtask users (need a stable, mockable client),
and the O365 toolkit maintainers (currently duplicating drive-item logic in
every tool).

**Why now**: FEAT-539 just landed delta enumeration for both drives with a
robust retry/validation helper (`parrot_tools/o365/delta.py`), so the Graph
plumbing is mature; the missing piece is the uniform manager façade.

## Constraints & Requirements

- **Contract fidelity**: implement every abstract method of
  `FileManagerInterface` (`list_files`, `get_file_url`, `upload_file`,
  `download_file`, `copy_file`, `delete_file`, `exists`, `get_file_metadata`,
  `create_file`) with the exact signatures at
  `navigator/utils/file/abstract.py:53-155`, plus the optional folder/rename
  hooks (`create_folder`, `remove_folder`, `rename_folder`, `rename_file`,
  lines 170-212), the inherited `create_from_bytes`/`create_from_text`
  helpers and a server-side `find_files` override.
- **Home & reuse (decided)**: new modules under
  `packages/ai-parrot/src/parrot/interfaces/file/` that **compose** the
  existing `SharepointClient` / `OneDriveClient` (auth, site/drive
  resolution, upload sessions). No second Graph auth stack.
- **Shape (decided)**: two public classes, `SharePointFileManager` and
  `OneDriveFileManager`, over one shared abstract `GraphDriveFileManager`
  that owns drive-item operations. Paths are **drive-relative**, exactly
  like S3 `prefix + key`.
- **Auth (decided)**: app-only client credentials, delegated/OBO, and
  username/password (ROPC) — i.e. every mode `O365Client._create_credential`
  already supports. Credentials arrive as a `credentials` dict or fall back
  to the `SHAREPOINT_*` / `O365_*` values in `parrot/conf.py:598-617`.
- **OneDrive scope (decided)**: any user's drive via `users/{upn|id}/drive`
  under app-only auth, or `me/drive` under delegated auth. Port flowtask's
  `_resolve_user_drive` into `OneDriveClient`; do **not** port the
  `drive.type=onedrive` shim into `SharepointClient` (the class split makes
  it redundant).
- **URLs (decided)**: `get_file_url` returns a Graph `createLink` sharing
  link (organization scope by default, `expirationDateTime` derived from
  `expiry` when the tenant allows it).
- **Batch (decided)**: `upload_files` / `download_files` return per-item
  results and never raise mid-batch; a bounded semaphore (default 5) drives
  concurrency; Graph 429/503 `Retry-After` is honoured.
- **Registration (decided, all four)**: `parrot.interfaces.file` lazy
  re-exports; `FileManagerFactory` + `FileManagerTool`/`FileManagerToolkit`
  `manager_type` literals `sharepoint` / `onedrive`; refactor
  `SharePointToolkit`/`OneDriveToolkit` tools onto the managers; mirror
  S3's `setup(app, route)` HTTP file-serving extension.
- **Verification (decided)**: mocked unit tests in CI + an opt-in
  `@pytest.mark.live` suite gated on `SHAREPOINT_*`/`O365_*` env vars, run
  manually before `/sdd-done`.
- **Conflict semantics (assumed, user did not object)**: uploads default to
  `@microsoft.graph.conflictBehavior=replace` (S3 overwrite parity);
  `delete_file` is a Graph DELETE (recycle bin), not permanent deletion.
- **Conventions**: aiohttp only for raw HTTP (upload-session chunk PUTs
  already use `aiohttp.ClientSession` at `sharepoint.py:417`); the
  `import httpx` at `sharepoint.py:11` / `onedrive.py:10` is unused legacy
  and must not spread into new modules (ruff TID251 bans it). msgraph-sdk
  itself depends on httpx transitively via kiota — that is an accepted,
  pre-existing dependency (`ai-parrot[agents]` extra,
  `packages/ai-parrot/pyproject.toml:440-442`).
- **No blocking I/O** in async paths; Pydantic v2 models for batch results;
  Google docstrings; `self.logger`.
- **Backwards compatibility**: `SharepointClient`/`OneDriveClient` public
  methods stay (flowtask and the delta tools call them); additions only.

---

## Options Explored

### Option A: Thin adapters over the existing clients, method by method

Each `FileManagerInterface` method on `SharePointFileManager` calls the
closest existing `SharepointClient` method (`upload_files` for
`upload_file`, `file_search` + `download_found_files` for `download_file`,
`file_lookup` for `exists`/`get_file_metadata`), translating the stateful
`client.directory` / `client.filename` protocol into path arguments before
each call. `OneDriveFileManager` does the same over `OneDriveClient.file_list`,
`file_download`, `upload_file`, `file_delete`. Missing operations (`copy_file`,
`get_file_url`, `rename_*`) are added ad hoc on each manager.

✅ **Pros:**
- Smallest new code; every Graph call already exists somewhere.
- Zero change to the clients' public behaviour.

❌ **Cons:**
- The two clients have **different** method sets (`SharepointClient` has no
  `file_list`/`file_delete`; `OneDriveClient` has no `file_lookup`), so the
  "shared base" would be nearly empty — two divergent adapters, not one
  design.
- Inherits the clients' stateful protocol: `file_search` reads
  `self.directory`/`self.filename`, so concurrent batch calls on one manager
  race on instance attributes. Batch ops would need a lock or a client per
  call.
- `download_found_files` writes into `self.directory` on local disk — cannot
  satisfy `download_file(source, destination: BinaryIO)`.
- Still has to reach into `client.graph_client` for `copy_file`, `createLink`,
  `rename`, so it is not actually "thin".

📊 **Effort:** Medium (looks Low, becomes Medium once the stateful protocol
is worked around)

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `msgraph-sdk` 1.63.0 (installed) | Graph client already used by the clients | `ai-parrot[agents]` extra pins `>=1.8.0` |
| `azure-identity` 1.25.3, `msal` 1.39.0 | credentials, already wired in `O365Client` | no change |

🔗 **Existing Code to Reuse:**
- `packages/ai-parrot/src/parrot/interfaces/sharepoint.py:565` `upload_files`, `:968` `file_search`, `:1311` `file_lookup`
- `packages/ai-parrot/src/parrot/interfaces/onedrive.py:167` `file_list`, `:244` `file_download`, `:393` `upload_file`, `:364` `file_delete`

---

### Option B: Shared `GraphDriveFileManager` base owning drive-item ops; clients supply auth + drive resolution  ⭐

Introduce `parrot/interfaces/file/graph.py::GraphDriveFileManager(FileManagerInterface)`
— an abstract base whose only backend-specific hook is
`async _resolve_drive_id() -> str` (plus a `client` factory). The base
implements **all** `FileManagerInterface` methods once, directly against
`client.graph_client.drives.by_drive_id(drive_id).items.by_drive_item_id(
"root:/<path>:")` builders (the same pattern `ListSharePointFilesTool` already
uses at `parrot_tools/o365/sharepoint.py:100-125`), reusing the clients only
for what they are good at:

- `O365Client` — credential/auth-mode handling (`_create_credential`,
  `set_auth_mode`, `is_app_only`, `acquire_token_on_behalf_of`, `user_auth`).
- `SharepointClient` — `verify_sharepoint_access`, `_resolve_site`
  (sub-site detection), `_resolve_drive(library)`, `_ensure_folder`,
  `_create_upload_session` + `_upload_large_file` (chunked, aiohttp).
- `OneDriveClient` — `_resolve_drive` (`me`) plus the newly ported
  `_resolve_user_drive(user)`; `_upload_large_file_content` for bytes.

`SharePointFileManager(site, library="Documents", prefix="", credentials=None,
auth_mode="direct", ...)` and `OneDriveFileManager(user="me", prefix="",
credentials=None, auth_mode=..., ...)` become ~60-line subclasses: constructor
+ `_resolve_drive_id` + `manager_name`. Extensions beyond the interface, on
the base: `upload_files`, `download_files` (batch, per-item results),
`upload_file_from_bytes` (S3 parity), `find_files` (Graph `search(q)` with
local pattern fallback, lifted from `SharepointClient.file_search`'s
`_pattern_is_api_safe` logic), `get_file_url(..., scope=, link_type=)`,
`create_folder`/`remove_folder`/`rename_*`, and `setup(app, route)` via
`navigator.utils.file.web.FileServingExtension`.

✅ **Pros:**
- One implementation of every drive-item operation; SharePoint vs OneDrive
  differ **only** in how the drive id is found — which is exactly how Graph
  models them (`/drives/{id}/...` is identical for both).
- Stateless, path-argument API — safe for concurrent batches, satisfies
  `BinaryIO` destinations, testable with a fake request-builder tree.
- The O365 toolkit tools (`List*`, `Search*`, `Download*`, `Upload*` for both
  drives) collapse to thin calls on the managers, deleting their duplicated
  Graph walks; `Delta*` tools keep their own `DriveDeltaHelper` path.
- Ports flowtask's `_resolve_user_drive` **once** into `OneDriveClient`,
  closing the drift the user flagged.

❌ **Cons:**
- More new code than A (the base is the bulk of the feature).
- Two Graph request styles coexist for a while (the clients' own
  `upload_files`/`file_search` remain for flowtask compatibility).
- `copy_file` on Graph is asynchronous (HTTP 202 + monitor URL) — the base
  must poll with aiohttp; not a one-liner.

📊 **Effort:** Medium-High

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `msgraph-sdk` 1.63.0 | drive-item request builders, `createLink`, `createUploadSession`, `copy`, `search` | already a dependency; `CreateLinkPostRequestBody` verified importable |
| `microsoft-kiota-http` 1.13.0 | ships `RetryHandler` middleware (429/503 with `Retry-After`) in the default Graph pipeline | verified `kiota_http.middleware.retry_handler.RetryHandler` |
| `aiohttp` 3.14.3 | resumable-upload chunk PUTs, `copy` monitor polling, `@microsoft.graph.downloadUrl` streaming | codebase standard |
| `aiofiles` | chunked local reads/writes | already imported by both clients |
| `navigator-api` 4.0.0 | `FileManagerInterface`, `FileMetadata`, `FileServingExtension` | pinned `>=3.2.2` in `ai-parrot/pyproject.toml:124` |

🔗 **Existing Code to Reuse:**
- `packages/ai-parrot/src/parrot/interfaces/o365.py:115-978` `O365Client` — all auth modes, `graph_client` property, `get_user_context`.
- `packages/ai-parrot/src/parrot/interfaces/sharepoint.py:96-357` site/drive/folder resolution; `:390-470` upload session + chunked upload; `:867-873` `_pattern_is_api_safe`.
- `packages/ai-parrot/src/parrot/interfaces/onedrive.py:88-165` drive/folder resolution; `:677-735` `_upload_large_file_content` (bytes → session).
- `/home/jesuslara/proyectos/flowtask/flowtask/interfaces/Sharepoint.py:145-188` `_resolve_user_drive` — to port into `OneDriveClient`.
- `packages/ai-parrot-tools/src/parrot_tools/o365/sharepoint.py:72-185` listing walk (`root:/{path}:` + `.children.get()`), to be moved into the base.
- `packages/ai-parrot-tools/src/parrot_tools/o365/delta.py:487-539` `_status_code_of` / `_retry_after_seconds` — reuse for batch throttling.
- `.venv/.../navigator/utils/file/s3.py:571` `upload_file_from_bytes`, `:613` `setup`, `:635` `handle_file` — API shape to mirror.
- `.venv/.../navigator/utils/file/web.py:28` `FileServingExtension(manager, route, manager_name)`.

---

### Option C: One generic `GraphDriveFileManager` keyed by a drive URL, no SharePoint/OneDrive subclasses

A single concrete manager configured with a **drive locator** string —
`sharepoint://{tenant}/sites/{site}/{library}`, `onedrive://{upn}`,
`onedrive://me`, or a raw `drive://{drive-id}` — parsed at construction into
a resolver strategy. Paths inside the manager remain drive-relative. The
`FileManagerFactory` gets one key, `msgraph`, with `drive=` kwarg.

✅ **Pros:**
- One class, one factory key, one set of tests; adding a third target
  (a group drive, a shared library by id) is a new URL scheme, not a class.
- Naturally supports "any drive in the tenant" for admin/ops agents.

❌ **Cons:**
- Contradicts the decided two-class shape; agent-facing ergonomics suffer
  (`manager_type="msgraph", drive="sharepoint://..."` vs
  `manager_type="sharepoint", site=..., library=...`).
- URL grammar is a new mini-language to document and validate; sub-site
  auto-detection (`_detect_and_resolve_subsite`) gets awkward inside a URL.
- Credentials still differ by target (SharePoint defaults from
  `SHAREPOINT_*`, OneDrive delegated from `O365_*`), so the "one class" hides
  two configuration surfaces behind a string.

📊 **Effort:** Medium

📦 **Libraries / Tools:** same as Option B.

🔗 **Existing Code to Reuse:** same as Option B, plus
`parrot_tools/o365/delta.py:364` `normalize_drive_path` and `:387`
`validate_continuation_link` as the model for locator validation.

---

### Option D (unconventional): Implement the managers upstream in navigator-api and re-export

Add `navigator/utils/file/msgraph.py` next to `s3.py` in the
`navigator-api` repo, register `sharepoint`/`onedrive` in the upstream
`FileManagerFactory._LAZY_MANAGERS`, and let ai-parrot's shim pick them up
through its existing `__getattr__` lazy map.

✅ **Pros:**
- Every navigator-based app (not just ai-parrot) gets the managers; the
  parrot shim needs a two-line change.
- Keeps `parrot/interfaces/file/` a pure re-export, as TASK-851 intended.

❌ **Cons:**
- Rejected in Round 1: navigator-api has no O365/MSAL stack, so the whole
  `O365Client` auth layer would have to move or be duplicated upstream.
- Cross-repo release coupling; the live-test gate and the toolkit refactor
  would straddle two repositories.

📊 **Effort:** High (cross-repo)

---

## Recommendation

**Option B** is recommended because:

- It is the only option in which "two classes on a shared base" is a real
  design rather than a naming convention: Graph treats a SharePoint library
  and a OneDrive as the same `drive` resource, so a base that owns all
  drive-item operations and delegates *only* drive resolution to subclasses
  mirrors the API's own shape. Option A's base would be hollow because the
  two existing clients share almost no methods.
- It resolves the stateful-protocol problem (instance-attribute
  `directory`/`filename`) that makes Option A unsafe for the decided
  per-item concurrent batch semantics.
- It pays for the O365 toolkit refactor the user put in scope: the four
  List/Search/Download/Upload tools per drive already contain the drive-item
  code Option B centralises, so the refactor is a net deletion.
- The trade-off is more new code than a thin adapter and a temporary
  coexistence of two request styles (`SharepointClient.upload_files` stays
  for flowtask parity). That is acceptable: the clients' public surface is
  untouched, additions are confined to `OneDriveClient._resolve_user_drive`,
  and the base is the reusable asset every later Graph feature (group
  drives, shared-with-me) will build on.
- Option C's URL grammar is elegant but fights the decided ergonomics and
  the split configuration defaults; Option D was ruled out by the home
  decision.

---

## Feature Description

### User-Facing Behavior

- **Direct use**
  `SharePointFileManager(site="troc", library="Documents",
  prefix="reports/", credentials={...})` and
  `OneDriveFileManager(user="someone@tenant.com", credentials={...})`
  behave like `S3FileManager`: paths are relative to `library` (or the
  drive root) plus `prefix`; `list_files("2026/", "*.xlsx")`,
  `upload_file(Path|BinaryIO, "2026/q3.xlsx")`, `create_from_bytes(...)`,
  `download_file("2026/q3.xlsx", Path|BinaryIO)`, `exists`,
  `get_file_metadata`, `copy_file`, `delete_file`, `rename_file`,
  `create_folder`/`remove_folder`/`rename_folder`, `find_files(keywords,
  extension, prefix)` (server-side Graph search when the query is
  API-safe, recursive walk otherwise) and `get_file_url(path, expiry)`
  returning an organization-scoped sharing link.
- **Batch**: `upload_files([(src, dest), ...])` and
  `download_files([(src, dest), ...])` return a list of
  `BatchItemResult(path, ok, metadata | error, attempts)`; the call never
  raises for a single item, concurrency is bounded (default 5), and 429/503
  responses are retried with `Retry-After`.
- **Bytes**: `upload_file_from_bytes(data, "dest/name.pdf",
  content_type=...)` returns the item's `web_url`, mirroring S3.
- **Agents**: `FileManagerToolkit(manager_type="sharepoint", site=...,
  library=..., credentials=...)` and `manager_type="onedrive"` expose the
  existing `fs_*` tools against SharePoint/OneDrive with no new tool
  schema. `SharePointToolkit` / `OneDriveToolkit` keep their tool names and
  args but execute through the managers.
- **Serving**: `manager.setup(app, route="/sp")` mounts a
  `FileServingExtension` so `GET /sp/<path>` streams the file through
  navigator (range requests supported by the extension).
- **Auth**: `auth_mode="direct"` (client credentials, default),
  `"delegated"`/`"cached"` (interactive/device-code token cache),
  `"on_behalf_of"` (with `user_assertion`), or username/password via the
  same `credentials` dict `O365Client` already accepts.
- **Import paths**: `from parrot.interfaces.file import
  SharePointFileManager, OneDriveFileManager` (lazy, no msgraph import at
  package load) and, for the shim parity test, `parrot_tools.file`.

### Internal Behavior

1. **Construction** stores target + prefix + credentials + auth mode and
   builds (lazily) the matching client: `SharepointClient` for SharePoint,
   `OneDriveClient` for OneDrive. `credentials` fall back to
   `SHAREPOINT_*` (SharePoint) or `O365_*` (OneDrive) conf values via the
   clients' existing `_default_*` handling and `CredentialsInterface`.
2. **Drive resolution** is the only subclass hook.
   SharePoint: `verify_sharepoint_access()` → `_resolve_site()` (sub-site
   detection) → `_resolve_drive(library)`; OneDrive: `_resolve_user_drive(
   user)` (ported from flowtask; `me/drive` when user == "me" and auth is
   delegated, `users/{id}/drive` otherwise, erroring clearly when app-only
   lacks `Files.ReadWrite.All`). The drive id is cached per manager.
3. **Path model**: `_prefixed(path)` / `_unprefixed(path)` exactly like S3;
   item addressing uses the `root:/<url-encoded path>:` colon form
   (`SharepointClient._to_colon_id` semantics) so no item-id lookups are
   needed for reads. Folder creation for uploads reuses `_ensure_folder`.
4. **Uploads**: ≤ 4 MB → single PUT `content`; larger → `createUploadSession`
   + aiohttp chunk PUTs (existing `_upload_large_file` /
   `_upload_large_file_content`), `conflictBehavior=replace`.
5. **Downloads**: read `@microsoft.graph.downloadUrl` from the item and
   stream with aiohttp to a `Path` or `BinaryIO`; `download_file` returns the
   `Path` (for `BinaryIO` destinations, a synthetic `Path(source)` as S3
   does).
6. **Copy**: `items.copy` POST returns 202 + `Location` monitor; poll with
   aiohttp until `status == completed`, then fetch the new item's metadata.
7. **Metadata mapping**: one `_make_metadata(DriveItem) -> FileMetadata`
   (name, drive-relative path, size, `file.mime_type`,
   `last_modified_date_time`, `web_url`).
8. **URLs**: `items.create_link` with `type="view"|"edit"`,
   `scope="organization"` default, `expirationDateTime = now + expiry`
   when `expiry > 0`; tenant policies that reject expiration fall back to a
   non-expiring link with a warning.
9. **Search**: `find_files` → Graph `search(q)` on the drive when the
   keyword is API-safe, filtered by `extension` and `prefix`; otherwise
   recursive `children` walk under `prefix`.
10. **Batch engine**: `asyncio.Semaphore(max_concurrency)`; each item runs
    the single-item op, catches exceptions into its result, retries
    429/503/504 using `_retry_after_seconds` semantics from `delta.py`.
11. **Registration**: `parrot.interfaces.file.__init__._LAZY_MANAGERS`
    gains both classes; `parrot.tools.filemanager.FileManagerFactory`
    resolves `sharepoint`/`onedrive` locally (not via the navigator
    factory) and widens the `Literal` on `FileManagerTool` and
    `FileManagerToolkit`; `FileManagerTool.description` string updated.
12. **Toolkit refactor**: `ListSharePointFilesTool`, `Search…`, `Download…`,
    `Upload…` (and the OneDrive four) build a manager from their args and
    call it; response dict shapes are preserved so
    `test_o365_delta_tools.py::TestBundleRegistration` and the permission
    context bridge tests keep passing. `Delta*` tools are untouched.
13. **Serving**: `setup(app, route, base_url)` constructs
    `FileServingExtension(manager=self, route=route,
    manager_name=self.manager_name)` as S3 does.

### Edge Cases & Error Handling

- **Missing folder on upload**: created via `_ensure_folder`; `auto_create_dirs`
  semantics match `FileManagerToolkit`.
- **Path with reserved characters** (`#`, `%`, `:` in names): URL-encode
  segments individually (`_to_colon_id` pattern); reject `..` segments.
- **Library alias**: `"Shared Documents"` normalises to `Documents`
  (existing `_parse_directory_path` rule).
- **Sub-site targets** (`site="hr/benefits"`) resolved by
  `_detect_and_resolve_subsite`.
- **`exists` on a folder** returns `True` (Graph item exists) —
  documented; `get_file_metadata` on a folder returns size 0 and
  `content_type=None`.
- **Throttling**: kiota `RetryHandler` covers SDK calls; raw aiohttp paths
  (chunk PUT, monitor poll, download stream) implement their own
  `Retry-After` wait with a bounded attempt count.
- **Upload session expiry / interrupted chunk**: surface a
  `RuntimeError` with the byte offset; no silent partial file (Graph
  discards incomplete sessions).
- **Copy timeout**: monitor polling bounded (default 120 s) →
  `TimeoutError` with the monitor URL.
- **Sharing-link policy**: tenant forbids anonymous → `scope="anonymous"`
  raises `PermissionError`; expiration unsupported → warning + link without
  expiry.
- **App-only OneDrive without `Files.ReadWrite.All`**: explicit
  `RuntimeError` naming the missing application permission (flowtask
  wording).
- **`user="me"` with app-only auth**: rejected at resolution time with a
  clear message (`me` requires delegated auth).
- **Batch with duplicate destinations**: processed in order; last write
  wins under `replace`; results list preserves input order.
- **Auth failure mid-batch**: the first `401/403` marks that item failed
  and aborts the remaining items with a shared `AuthenticationError`
  result (no point retrying 4 more times against a dead token) — the only
  case where the batch short-circuits, and it still does not raise.
- **`download_file` to a `BinaryIO`**: stream, do not buffer whole file.
- **Unused `import httpx`** in the two clients is left in place (out of
  scope) but the new modules import only aiohttp.

---

## Capabilities

### New Capabilities
- `graph-drive-filemanager`: abstract `GraphDriveFileManager` base
  implementing `FileManagerInterface` over Microsoft Graph drive items
  (list/upload/download/copy/delete/exists/metadata/create, folders,
  rename, search, sharing links, batch, bytes upload, HTTP serving).
- `sharepoint-filemanager`: `SharePointFileManager` — site + library
  targeting over `SharepointClient`.
- `onedrive-filemanager`: `OneDriveFileManager` — user/`me` targeting over
  `OneDriveClient`, including the ported `_resolve_user_drive`.
- `filemanager-graph-registration`: lazy re-exports, factory keys,
  `FileManagerTool`/`FileManagerToolkit` literals, serving extension.
- `o365-toolkit-manager-refactor`: List/Search/Download/Upload tools for
  both drives delegate to the managers.
- `graph-filemanager-live-gate`: env-gated live test suite.

### Modified Capabilities
- `fileinterface-migration` (FEAT-123, `sdd/specs/fileinterface-migration.spec.md`):
  the shim gains two lazy managers that are **parrot-native**, not
  upstream re-exports — the "pure re-export" invariant is relaxed for these
  two names; `test_file_shim.py::test_no_cloud_sdk_leak_on_import` must be
  extended to assert msgraph is not imported eagerly.
- `filemanagertool-migration-toolkit` (FEAT-127,
  `sdd/specs/filemanagertool-migration-toolkit.spec.md`): `manager_type`
  literal widened; `_create_manager` gains two branches.
- `o365` toolkits (FEAT-266/267/539 lineage): tool internals change,
  public tool names/args/response shapes do not.

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `packages/ai-parrot/src/parrot/interfaces/file/__init__.py` | modifies | add `SharePointFileManager`, `OneDriveFileManager` to `__all__` + `_LAZY_MANAGERS` (module targets `parrot.interfaces.file.sharepoint` / `.onedrive`) |
| `packages/ai-parrot/src/parrot/interfaces/file/graph.py` (new) | extends | `GraphDriveFileManager`, `BatchItemResult`, metadata mapping, batch engine |
| `packages/ai-parrot/src/parrot/interfaces/file/sharepoint.py` (new) | extends | `SharePointFileManager` |
| `packages/ai-parrot/src/parrot/interfaces/file/onedrive.py` (new) | extends | `OneDriveFileManager` |
| `packages/ai-parrot/src/parrot/interfaces/onedrive.py` | modifies | add `_resolve_user_drive(user)` + `onedrive_user` attribute (port from flowtask); additive |
| `packages/ai-parrot/src/parrot/interfaces/sharepoint.py` | depends on | reused as-is (`verify_sharepoint_access`, `_resolve_drive`, `_ensure_folder`, upload session helpers) |
| `packages/ai-parrot/src/parrot/interfaces/o365.py` | depends on | auth modes; no change |
| `packages/ai-parrot/src/parrot/tools/filemanager.py` | modifies | `FileManagerFactory` local resolution for `sharepoint`/`onedrive`; `Literal` widened on `FileManagerTool.__init__:172` and `FileManagerToolkit.__init__:549`; `_create_manager` branches at `:218` and `:617` |
| `packages/ai-parrot-tools/src/parrot_tools/file/__init__.py` | modifies | lazy re-export of the two new names for shim parity |
| `packages/ai-parrot-tools/src/parrot_tools/o365/sharepoint.py` | modifies | List/Search/Download/Upload tools delegate to `SharePointFileManager`; Delta tool untouched |
| `packages/ai-parrot-tools/src/parrot_tools/o365/onedrive.py` | modifies | same for OneDrive |
| `packages/ai-parrot-tools/src/parrot_tools/o365/bundle.py` | depends on | toolkits unchanged; `TestBundleRegistration` must keep passing |
| `packages/ai-parrot/pyproject.toml` | depends on | msgraph-sdk/azure-identity already in `agents` extra (L440-442); consider a dedicated `msgraph` extra so `FileManagerFactory.create("sharepoint")` has a documented install |
| `packages/ai-parrot/tests/interfaces/test_file_shim.py` | modifies | extend leak/lazy/factory tests for the two names |
| `packages/ai-parrot/tests/interfaces/test_graph_filemanager*.py` (new) | extends | mocked Graph request-builder tests; `@pytest.mark.live` suite |
| `packages/ai-parrot-tools/tests/test_o365_*` | depends on | must stay green after the tool refactor |
| `docs/integrations/office365-oauth2.md` | modifies | document `Files.ReadWrite`, `Sites.ReadWrite.All` and application-permission requirements for the managers |
| flowtask (`/home/jesuslara/proyectos/flowtask/flowtask/interfaces/Sharepoint.py`) | depends on | out of repo; after this feature flowtask can drop its `drive.type=onedrive` shim in favour of `OneDriveFileManager` (follow-up, not in scope) |

No breaking changes. New dependency: none (msgraph-sdk already present).

---

## Code Context

### User-Provided Code

```python
# Source: /home/jesuslara/proyectos/flowtask/flowtask/interfaces/Sharepoint.py:106-188
# (reference implementation the user asked to use; NOT in this repo)
    def _ensure_drive_config(self) -> None:
        """Resolve the optional ``drive`` config into drive targeting attributes.
        ...
            drive:
              type: onedrive        # "site" (default) | "onedrive"
              user: someone@tenant.com   # UPN, user-id, or "me"
        """
        if self._drive_cfg_done:
            return
        drive_cfg = getattr(self, "drive", None)
        if isinstance(drive_cfg, dict):
            self.drive_type = (drive_cfg.get("type") or "site").strip().lower()
            self.onedrive_user = drive_cfg.get("user")
        else:
            self.drive_type = "site"
            self.onedrive_user = None
        if self.drive_type not in ("site", "onedrive"):
            raise ConfigError(...)
        if self.drive_type == "onedrive" and not self.onedrive_user:
            raise ConfigError(...)
        self._drive_cfg_done = True

    async def _resolve_user_drive(self) -> DriveItem:
        """Resolve and cache a user's personal OneDrive drive.
        Uses ``/users/{id}/drive`` for app-only or another user's OneDrive, or
        ``/me/drive`` when ``drive.user`` is the literal ``"me"`` (delegated auth only).
        """
        if self._user_drive_info:
            return self._user_drive_info
        self._ensure_drive_config()
        try:
            if str(self.onedrive_user).strip().lower() == "me":
                drive = await self.graph_client.me.drive.get()
            else:
                drive = await self.graph_client.users\
                    .by_user_id(self.onedrive_user).drive.get()
        except Exception as e:
            raise RuntimeError(
                f"Failed to resolve OneDrive for '{self.onedrive_user}': {e}. "
                "For app-only auth this requires the application permission "
                "'Files.ReadWrite.All' (admin-consented)."
            ) from e
        if not drive or not getattr(drive, "id", None):
            raise RuntimeError(f"Could not resolve OneDrive for user '{self.onedrive_user}'")
        self._user_drive_info = drive
        self._drive_id = drive.id
        return drive
```

Drift summary (method-name diff, verified 2026-09-25):
- flowtask `SharepointClient` has `_ensure_drive_config`, `_resolve_user_drive`
  that ai-parrot's lacks; otherwise identical method sets.
- ai-parrot `O365Client` has `set_auth_mode`, `is_app_only`,
  `get_user_context`, `_filter_reserved_scopes` and an **async** `close()`
  that flowtask's lacks (flowtask `close()` is sync).
- flowtask `OneDrive.py` has `get_context`/`_start_` that ai-parrot's lacks
  (trivial).

### Verified Codebase References

#### Classes & Signatures
```python
# From .venv/lib/python3.12/site-packages/navigator/utils/file/abstract.py (navigator-api 4.0.0)
@dataclass
class FileMetadata:                                     # line 16
    name: str; path: str; size: int                     # lines 28-30
    content_type: Optional[str]; modified_at: Optional[datetime]; url: Optional[str]  # 31-33

class FileManagerInterface(ABC):                        # line 36
    async def list_files(self, path: str = "", pattern: str = "*") -> List[FileMetadata]  # 53 (abstract)
    async def get_file_url(self, path: str, expiry: int = 3600) -> str                   # 67 (abstract)
    async def upload_file(self, source: Union[BinaryIO, Path], destination: str) -> FileMetadata  # 79 (abstract)
    async def download_file(self, source: str, destination: Union[Path, BinaryIO]) -> Path        # 93 (abstract)
    async def copy_file(self, source: str, destination: str) -> FileMetadata           # 107 (abstract)
    async def delete_file(self, path: str) -> bool                                     # 119 (abstract)
    async def exists(self, path: str) -> bool                                          # 130 (abstract)
    async def get_file_metadata(self, path: str) -> FileMetadata                       # 141 (abstract)
    async def create_file(self, path: str, content: bytes) -> bool                     # 155 (abstract)
    async def create_folder(self, folder_name: str) -> None                            # 170 (default raises NotImplementedError)
    async def remove_folder(self, folder_name: str) -> None                            # 183 (default raises)
    async def rename_folder(self, old_folder_name: str, new_folder_name: str) -> None  # 196 (default raises)
    async def rename_file(self, old_file_name: str, new_file_name: str) -> None        # 212 (default raises)
    async def create_from_text(self, path: str, text: str, encoding: str = "utf-8") -> bool  # 230 (concrete)
    async def create_from_bytes(self, path: str, data: Union[bytes, BytesIO, StringIO]) -> bool  # 245 (concrete → create_file)
    async def find_files(self, keywords=None, extension=None, prefix=None) -> List[FileMetadata]  # 265 (concrete; list+filter; override for server-side)

# From .venv/lib/python3.12/site-packages/navigator/utils/file/s3.py — the model to mirror
class S3FileManager(FileManagerInterface):              # line 35
    manager_name: str = "s3file"                        # 49
    MULTIPART_THRESHOLD = 100 MiB; MULTIPART_CHUNKSIZE = 10 MiB; MAX_CONCURRENCY = 10  # 51-53
    def __init__(self, bucket_name=None, aws_id="default", region_name=None, prefix="",
                 multipart_threshold=None, multipart_chunksize=None, max_concurrency=None, **kwargs)  # 55
    def _prefixed(self, key: str) -> str                # 120
    def _unprefixed(self, key: str) -> str              # 124
    def _make_metadata(self, key: str, obj: dict) -> FileMetadata  # 130
    async def upload_file_from_bytes(self, file_obj: bytes, destination_key: str,
                                     content_type: str = "application/octet-stream") -> str  # 571 (returns URL)
    def setup(self, app, route: str = "/data", base_url: str = None)  # 613 → FileServingExtension
    async def handle_file(self, request)                # 635

# From .venv/lib/python3.12/site-packages/navigator/utils/file/web.py
class FileServingExtension(BaseExtension):              # line 28
    name = "fileserving"; CHUNK_SIZE = 1 MiB            # 44, 46
    def __init__(self, manager: FileManagerInterface, route: str = "/data", manager_name: Optional[str] = None, **kwargs)  # 48
    def setup(self, app: WebApp) -> WebApp              # 78
    async def handle_file(self, request: web.Request) -> web.StreamResponse  # 150 (range-aware)

# From .venv/lib/python3.12/site-packages/navigator/utils/file/factory.py
class FileManagerFactory:                               # line 14
    _EAGER_MANAGERS = {"local": (...), "temp": (...)}; _LAZY_MANAGERS = {"s3": (...), "gcs": (...)}
    @staticmethod
    def create(manager_type: str, **kwargs) -> FileManagerInterface  # relative importlib; UNKNOWN keys raise ValueError

# From packages/ai-parrot/src/parrot/interfaces/file/__init__.py
__all__ = ("FileManagerInterface","FileMetadata","LocalFileManager","TempFileManager","S3FileManager","GCSFileManager")  # 26-33
_LAZY_MANAGERS = {"S3FileManager": "navigator.utils.file.s3", "GCSFileManager": "navigator.utils.file.gcs"}  # 34-37
def __getattr__(name: str)                              # 40 (importlib + setattr cache)

# From packages/ai-parrot/src/parrot/tools/filemanager.py
class FileManagerFactory:                               # line 22 (parrot-side delegate)
    _PARROT_TO_UPSTREAM = {"fs": "local", "temp": "temp", "s3": "s3", "gcs": "gcs"}  # 30
    @staticmethod
    def create(manager_type: Literal["fs","temp","s3","gcs"], **kwargs) -> FileManagerInterface  # 38
class FileManagerToolArgs(AbstractToolArgsSchema):      # 65 — operation Literal at 72, expiry_seconds at 134
class FileManagerTool(AbstractTool):                    # 140
    name = "file_manager"; description = "Manage files across different storage backends (local, S3, GCS, temp)"  # 168-169
    def __init__(self, manager_type: Literal["fs","temp","s3","gcs"] = "fs", default_output_dir=None,
                 allowed_operations=None, max_file_size=100 MiB, auto_create_dirs=True, **manager_kwargs)  # 172
    def _create_manager(self, manager_type: str, **kwargs) -> FileManagerInterface  # 218
class FileManagerToolkit(AbstractToolkit):              # 515
    tool_prefix = "fs"                                  # 547
    def __init__(self, manager_type: Literal["fs","temp","s3","gcs"] = "fs", ...)  # 549
    def _create_manager(self, manager_type: str, **kwargs) -> FileManagerInterface  # 617
    async def list_files / upload_file / download_file / copy_file / delete_file / file_exists /
              get_file_url / get_file_metadata / create_file  # 680-947 (each -> Dict[str, Any])

# From packages/ai-parrot/src/parrot/interfaces/o365.py
class O365Client(CredentialsInterface):                 # line 115
    _credentials = {"username","password","client_id","client_secret","tenant","site","tenant_id","assertion"}  # 156
    def __init__(self, *args, **kwargs) -> None         # 167
    def _create_credential(self) -> TokenCredential     # 237 (picks app-only / ROPC / cached MSAL by available creds)
    def _create_graph_client(self, scopes=None) -> GraphServiceClient  # 312
    @property graph_client -> GraphServiceClient        # 339
    def set_auth_mode(self, auth_mode: Optional[str]) -> None  # 360
    def is_app_only(self) -> bool                       # 365
    def get_user_context(self, user_id: Optional[str] = None)  # 372 (me vs users.by_user_id)
    async def __aenter__ / __aexit__                    # 393-401
    def connection(self)                                # 403 (sync; builds credential + graph client)
    def user_auth(self, username, password, scopes=None) -> Dict  # 475 (ROPC)
    def acquire_token(self, scopes=None) -> Dict        # 562 (client credentials)
    def acquire_token_on_behalf_of(self, user_assertion, scopes=None) -> Dict  # 621
    async def close(self)                               # 709
    async def interactive_login(...) -> Dict            # 763 ; async def ensure_interactive_session(scopes=None)  # 923

# From packages/ai-parrot/src/parrot/interfaces/sharepoint.py
class SharepointClient(O365Client):                     # line 32
    def __init__(self, *args, **kwargs)                 # 40 — defaults from SHAREPOINT_TENANT_ID/APP_ID/APP_SECRET/TENANT_NAME
    small_file_threshold = 4 MiB; chunk_size = 10 MiB   # 56-57
    _site_id/_drive_id/_site_info/_drive_info caches    # 60-63
    def _start_(self, **kwargs)                         # 72 — builds self.site_url / self.url from self.tenant + self.site
    def connection(self)                                # 83
    async def verify_sharepoint_access(self)            # 96
    async def _detect_and_resolve_subsite(self) -> tuple[str, str]  # 120
    async def _resolve_site(self) -> DriveItem          # 174 — sites.by_site_id(f"{tenant}.sharepoint.com:/sites/{site}")
    def _parse_directory_path(self, directory: str) -> tuple[str, str]  # 208 — "Shared Documents" → "Documents"; default library "Documents"
    async def _resolve_drive(self, library_name: str = None) -> DriveItem  # 242
    async def _ensure_folder(self, folder_path: str, create: bool = True, drive_id: str = None) -> DriveItem  # 298
    async def _upload_small_file(self, drive_id, parent_id, local_path, target_name)  # 372
    async def _create_upload_session(self, drive_id: str, parent_id: str, target_name: str) -> UploadSession  # 390
    async def _upload_large_file(self, upload_session: UploadSession, local_path) -> DriveItem  # 408 — aiohttp chunk PUTs, honours Retry-After
    def _normalize_directory(self, directory: str, drive_info) -> str  # 472
    def _to_colon_id(self, directory: str, name: str) -> str  # 556 — "root:/<quoted segs>/<name>:"
    async def upload_files(self, filenames=None, destination=None, destination_filenames=None) -> List[Dict]  # 565
    async def upload_folder(self, local_folder, destination=None, destination_filenames=None)  # 707
    async def close(self)                               # 859
    def _pattern_is_api_safe(self, pattern: str) -> bool  # 867
    async def download_found_files(self, found: List[Dict]) -> List[Dict[str, str]]  # 880 — writes into self.directory
    async def file_search(self) -> List[Dict]           # 968 — reads self.directory / self.filename (stateful)
    async def _search_pattern_recursive(self, drive_id, directory, pattern, wanted_ext=None) -> List[Dict]  # 1170
    async def file_lookup(self, files=None) -> List[Dict]  # 1311
    # NOTE: NO file_list / file_delete / copy / createLink methods exist on SharepointClient.

# From packages/ai-parrot/src/parrot/interfaces/onedrive.py
class OneDriveClient(O365Client):                       # line 25
    def __init__(self, *args, **kwargs)                 # 48 — small_file_threshold 4 MiB, chunk_size 10 MiB, _drive_id/_drive_info
    async def verify_onedrive_access(self)              # 77
    async def _resolve_drive(self) -> DriveItem         # 88 (current user's drive only; no user parameter)
    async def _ensure_folder(self, folder_path: str, create: bool = True) -> DriveItem  # 108
    async def file_list(self, folder_path: str = None) -> List[dict]  # 167
    async def file_search(self, search_query: str) -> List[dict]  # 211
    async def file_download(self, item_id: str, destination: Path) -> str  # 244 (by item id, not path)
    async def download_files(self, items: List[dict], destination_folder: Path) -> List[str]  # 294
    async def file_delete(self, item_id: str) -> bool   # 364
    async def upload_file(self, file_path: Path, destination_folder: str = None) -> dict  # 393
    async def upload_files(self, files: List[Path], destination_folder: str = None) -> List[dict]  # 439
    async def _upload_small_file(self, drive_id, parent_id, local_path: Path, target_name) -> DriveItem  # 588
    async def _create_upload_session(self, drive_id, parent_id, target_name) -> UploadSession  # 604
    async def _upload_large_file(self, upload_session, local_path) -> DriveItem  # 621
    async def _upload_large_file_content(self, upload_session, content: bytes, file_name: str) -> DriveItem  # 677
    async def close(self)                               # 818

# From packages/ai-parrot-tools/src/parrot_tools/o365/base.py
class O365AuthMode: DIRECT="direct"; OBO="on_behalf_of"; DELEGATED="delegated"; CACHED="cached"  # 22-27
class O365ToolArgsSchema(AbstractToolArgsSchema): auth_mode, user_assertion, user_id  # 30-40
class O365Tool(AbstractTool):                           # 49
    def __init__(self, credentials: Optional[Dict] = None, default_auth_mode=O365AuthMode.DIRECT, scopes=None, **kwargs)  # 85
    async def _get_client(self, auth_mode=None, user_assertion=None, scopes=None) -> O365Client  # 111 (cached per auth_mode)
    async def _execute_graph_operation(self, client: O365Client, **kwargs) -> Any  # 200 (subclass hook)
    async def _execute(self, **kwargs) -> ToolResult    # 219
    async def cleanup(self)                             # 301

# From packages/ai-parrot-tools/src/parrot_tools/o365/sharepoint.py (tools to refactor)
class ListSharePointFilesTool(O365Tool)                 # 36 — _execute_graph_operation(client: SharepointClient, **kwargs) at 72:
    #   client.site = site; client.credentials["tenant"] = site; await client.verify_sharepoint_access();
    #   drive_info = await client._resolve_drive(library);
    #   graph_client.drives.by_drive_id(drive_info.id).items.by_drive_item_id(f"root:/{folder_path}:").get()
    #   ...children.get() → dicts {name, path, is_folder, size, modified, web_url, id}   (lines 100-140)
class SearchSharePointFilesTool(O365Tool)               # 204
class DownloadSharePointFileTool(O365Tool)              # 325
class UploadSharePointFileTool(O365Tool)                # 459
class DeltaSharePointFilesTool(O365Tool)                # 656 — NOT in scope (uses DriveDeltaHelper)
# parrot_tools/o365/onedrive.py mirrors: ListOneDriveFilesTool 34, SearchOneDriveFilesTool 133,
#   DownloadOneDriveFileTool 213, UploadOneDriveFileTool 348, DeltaOneDriveFilesTool 522 (not in scope)

# From packages/ai-parrot-tools/src/parrot_tools/o365/bundle.py
class SharePointToolkit:  __init__(self, client_id: str, client_secret=None, tenant_id=None, default_auth_mode=O365AuthMode.DIRECT, scopes=None, **kwargs)  # 27/52
class OneDriveToolkit:    __init__(... same ...)        # 131/156
class Office365FileManagementToolkit: __init__(..., enable_sharepoint=True, enable_onedrive=True, **kwargs)  # 235/255
# NOTE: these are plain classes (not AbstractToolkit) exposing get_tools()/get_tool_by_name()/cleanup().

# From packages/ai-parrot-tools/src/parrot_tools/o365/delta.py (reuse for throttling)
def _status_code_of(error: BaseException) -> Optional[int]        # 487
def _retry_after_seconds(error: BaseException) -> Optional[float] # 499
RETRYABLE_STATUS_CODES, DEFAULT_MAX_RETRIES, DEFAULT_INITIAL_BACKOFF, DEFAULT_MAX_BACKOFF  # module constants (in __all__, line 1266)
```

#### Verified Imports
```python
# All confirmed importable on 2026-09-25 in the project venv (python3.12):
from navigator.utils.file import FileManagerInterface, FileMetadata, FileManagerFactory, FileServingExtension  # navigator/utils/file/__init__.py
from navigator.utils.file.abstract import FileManagerInterface, FileMetadata
from navigator.utils.file.s3 import S3FileManager
from navigator.utils.file.web import FileServingExtension
from parrot.interfaces.file import FileManagerInterface, FileMetadata, S3FileManager   # packages/ai-parrot/src/parrot/interfaces/file/__init__.py:19-24, 40
from parrot.interfaces.o365 import O365Client, MSALTokenCredential                      # parrot/interfaces/o365.py:115, 40
from parrot.interfaces.sharepoint import SharepointClient                               # parrot/interfaces/sharepoint.py:32
from parrot.interfaces.onedrive import OneDriveClient                                   # parrot/interfaces/onedrive.py:25
from parrot.interfaces.credentials import CredentialsInterface                          # parrot/interfaces/credentials.py:24
from parrot.tools.filemanager import FileManagerFactory, FileManagerTool, FileManagerToolkit  # parrot/tools/filemanager.py:22,140,515
from parrot.tools import FileManagerToolkit, AbstractToolkit, tool
from parrot_tools.o365.base import O365Tool, O365AuthMode                               # parrot_tools/o365/base.py:49,22
from parrot_tools.o365.bundle import SharePointToolkit, OneDriveToolkit, Office365FileManagementToolkit
from parrot_tools.o365.sharepoint import ListSharePointFilesTool, DeltaSharePointFilesTool
from parrot_tools.o365.delta import DriveDeltaHelper, _retry_after_seconds, RETRYABLE_STATUS_CODES
from parrot.conf import SHAREPOINT_APP_ID, SHAREPOINT_APP_SECRET, SHAREPOINT_TENANT_ID, SHAREPOINT_TENANT_NAME, SHAREPOINT_SITE_ID, SHAREPOINT_DEFAULT_HOST  # parrot/conf.py:612-617
from parrot.conf import O365_CLIENT_ID, O365_CLIENT_SECRET, O365_TENANT_ID, O365_REDIRECT_URI  # parrot/conf.py:598-603
from msgraph import GraphServiceClient
from msgraph.generated.models.drive_item import DriveItem
from msgraph.generated.models.upload_session import UploadSession
from msgraph.generated.drives.item.items.item.create_link.create_link_post_request_body import CreateLinkPostRequestBody
from kiota_http.middleware.retry_handler import RetryHandler     # default Graph pipeline retry (429/503)
```

#### Key Attributes & Constants
- Installed versions: `msgraph-sdk 1.63.0`, `azure-identity 1.25.3`, `msal 1.39.0`, `microsoft-kiota-http 1.13.0`, `navigator-api 4.0.0`, `aiohttp 3.14.3`.
- `S3FileManager.manager_name = "s3file"` (s3.py:49) — new managers need `manager_name = "sharepointfile"` / `"onedrivefile"` for `FileServingExtension` registration.
- `SharepointClient.small_file_threshold = 4 MiB`, `chunk_size = 10 MiB` (sharepoint.py:56-57); identical on `OneDriveClient` (onedrive.py:57-58).
- `SharepointClient._parse_directory_path` default library `"Documents"`; `"Shared Documents"` alias (sharepoint.py:220-239).
- `O365Client._credentials` keys: `username, password, client_id, client_secret, tenant, site, tenant_id, assertion` (o365.py:156).
- `O365AuthMode.DIRECT/OBO/DELEGATED/CACHED` (base.py:24-27).
- `parrot.interfaces.file._LAZY_MANAGERS` maps **class name → module path** (file/__init__.py:34-37); the factory in navigator maps **type key → (relative module, class)**.
- `packages/ai-parrot/pyproject.toml:395` `agents = [...]` extra includes `azure-identity>=1.18.0`, `msgraph-sdk>=1.8.0`, `microsoft-kiota-authentication-azure>=1.2.0` (lines 440-442); `packages/ai-parrot-tools/pyproject.toml:72` `office365 = [...]` extra mirrors them.
- Existing tests to extend: `packages/ai-parrot/tests/interfaces/test_file_shim.py` (`test_no_cloud_sdk_leak_on_import` :29, `test_lazy_identity` :42, `test_factory_unknown_type_raises_valueerror` :90); `packages/ai-parrot-tools/tests/test_o365_delta_tools.py::TestBundleRegistration` (:1083); `tests/tools/test_filemanager_toolkit.py`; `tests/tools/test_office365_toolkit.py`.
- Callers of the O365 toolkits outside the package (refactor blast radius): `parrot_tools/__init__.py`, `parrot/auth/oauth2/o365_provider.py`, `examples/msagent/server.py`, `examples/tool/o365.py`, `tests/tools/test_office365_toolkit.py`, `packages/ai-parrot-tools/tests/unit/test_o365_permission_context_bridge.py`, `packages/ai-parrot-tools/tests/contracts/test_ingest_delta.py`.
- `parrot/core/hooks/sharepoint.py` imports only `navigator_eventbus` hook models (no `SharepointClient`) — unaffected.

### Does NOT Exist (Anti-Hallucination)
- ~~`parrot.interfaces.file.sharepoint`~~ / ~~`parrot.interfaces.file.onedrive`~~ / ~~`parrot.interfaces.file.graph`~~ — the directory only contains `__init__.py, abstract.py, gcs.py, local.py, s3.py, tmp.py` (all re-export shims). These are the modules this feature creates.
- ~~`SharePointFileManager`~~, ~~`OneDriveFileManager`~~, ~~`GraphDriveFileManager`~~, ~~`BatchItemResult`~~ — nowhere in the repo or in navigator-api.
- ~~`navigator.utils.file.msgraph`~~ / ~~`navigator.utils.file.sharepoint`~~ — navigator-api 4.0.0 ships only `abstract, factory, gcs, local, s3, tmp, web`.
- ~~`FileManagerFactory.create("sharepoint")`~~ — raises `ValueError` today on both the navigator and the parrot factories.
- ~~`SharepointClient.file_list`~~, ~~`SharepointClient.file_delete`~~, ~~`SharepointClient.get_file_url`~~, ~~`SharepointClient.copy_file`~~ — do not exist; listing in the SharePoint tool is done inline on `graph_client`.
- ~~`SharepointClient._ensure_drive_config`~~, ~~`SharepointClient._resolve_user_drive`~~, ~~`SharepointClient.drive_type`~~, ~~`SharepointClient.onedrive_user`~~ — exist **only** in the flowtask copy, not in ai-parrot.
- ~~`OneDriveClient._resolve_user_drive`~~, ~~`OneDriveClient(user=...)`~~ — `OneDriveClient._resolve_drive()` takes no user; this feature adds user targeting.
- ~~`S3FileManager.upload_files`~~ / ~~`download_files`~~ — no batch API upstream; only `upload_file_from_bytes`.
- ~~`FileManagerInterface.upload_file_from_bytes`~~ — S3-specific, not on the interface (`create_from_bytes` is the interface helper).
- ~~`SharePointToolkit(AbstractToolkit)`~~ — the bundle toolkits are plain classes, not `AbstractToolkit` subclasses.
- ~~`parrot.tools.filemanager.FileManagerFactory._LAZY_MANAGERS`~~ — the parrot-side factory has only `_PARROT_TO_UPSTREAM`.
- ~~`O365Client.aclose()`~~ — the method is `async def close()` (o365.py:709); flowtask's is sync.
- ~~`S3FileManager.__init__(aws_config=...)`~~ — no such kwarg (documented in FEAT-162 F005); the new managers should take `credentials=` like S3, not an `aws_config`-style dict.

---

## Parallelism Assessment

- **Internal parallelism**: moderate. After the base (`graph.py` + models +
  fake-Graph test harness) lands, four lanes are independent:
  (1) `SharePointFileManager` + its tests, (2) `OneDriveClient._resolve_user_drive`
  port + `OneDriveFileManager` + tests, (3) registration (shim `__init__`,
  `parrot_tools.file` shim, `FileManagerFactory`/Tool/Toolkit literals, shim
  tests), (4) `setup()` serving extension + docs. The O365 toolkit refactor
  (SharePoint tools, OneDrive tools) depends on lanes 1 and 2 respectively
  and can then run as two more parallel lanes. The live-gate suite is last.
- **Cross-feature independence**: no in-flight spec touches
  `parrot/interfaces/file/`, `parrot/tools/filemanager.py` or
  `parrot/interfaces/{sharepoint,onedrive}.py`. FEAT-539
  (`contracts-card-ontology`, still `in-progress`/`done-with-issues`) owns
  `parrot_tools/o365/delta.py` and the `Delta*` tools — this feature must
  **not** edit `delta.py` or the Delta tools, only import from `delta.py`.
  `parrot_tools/o365/{sharepoint,onedrive}.py` are shared files with
  FEAT-539's already-merged Delta tool classes; edits here must be confined
  to the List/Search/Download/Upload classes.
- **Recommended isolation**: `per-spec` (one worktree, sequential waves) —
  the base module is a hard prerequisite for everything else and the
  toolkit refactor touches files whose other half belongs to FEAT-539, so a
  single integration worktree keeps the merge simple; within it the lanes
  above can be dispatched to parallel sdd-coder seats per wave.
- **Rationale**: the feature is one new abstraction plus its fan-out; the
  fan-out is wide but shallow, and the only shared-file risk (o365 tool
  modules) is with a feature that is already merged for those files.

---

## Open Questions

- [x] Feature or hotfix, and base branch? — *Owner: Jesus*: feature on `dev`.
- [x] Where do the managers live and do they reuse the existing clients? — *Owner: Jesus*: ai-parrot core, `parrot/interfaces/file/`, composing `SharepointClient`/`OneDriveClient`.
- [x] One class or two? — *Owner: Jesus*: two (`SharePointFileManager`, `OneDriveFileManager`) on a shared `GraphDriveFileManager` base; drive-relative paths.
- [x] Auth modes in v1? — *Owner: Jesus*: app-only client credentials, delegated/OBO, and username/password (all existing `O365Client` modes).
- [x] `get_file_url` semantics? — *Owner: Jesus*: Graph `createLink` sharing link (organization scope default, expiry when allowed).
- [x] Whose OneDrive, and backport flowtask's drive-targeting? — *Owner: Jesus*: any user's drive + `me`; port `_resolve_user_drive` into `OneDriveClient`; do not port the `SharepointClient` `drive.type` shim.
- [x] Batch failure semantics? — *Owner: Jesus*: per-item results, never raise mid-batch, bounded concurrency.
- [x] Registration surfaces? — *Owner: Jesus*: all four — shim re-exports, factory/tool/toolkit literals, O365 toolkit refactor, HTTP serving `setup()`.
- [x] Verification strategy? — *Owner: Jesus*: mocked unit tests in CI + opt-in env-gated live suite run manually before `/sdd-done`.
- [ ] Upload conflict default: `replace` (S3 parity) vs `fail`/`rename`, and should it be a constructor kwarg (`conflict_behavior=`)? — *Owner: Jesus* (assumed `replace`, kwarg exposed).
- [ ] Sharing-link defaults: `type="view"` vs `"edit"`, and should `expiry=0` mean "no expiration"? — *Owner: Jesus* (assumed `view`, `expiry<=0` → no expiration).
- [ ] Batch concurrency default (5) and per-item retry budget (3) — confirm against the tenant's throttling profile. — *Owner: Jesus*.
- [ ] Should `manager_name` values be `"sharepointfile"` / `"onedrivefile"` (S3 convention `"s3file"`) or `"sharepoint"` / `"onedrive"`? — *Owner: Jesus*.
- [ ] Should `FileManagerToolArgs.operation` gain `find`/`batch_upload`/`batch_download` so agents can reach the extension methods, or is v1 limited to the nine interface ops? — *Owner: Jesus* (assumed: nine ops only; batch/find via direct manager use).
- [ ] Add a dedicated `ai-parrot[msgraph]` extra (msgraph-sdk + azure-identity + kiota auth) so `FileManagerFactory.create("sharepoint")` has a documented install path outside `[agents]`? — *Owner: Jesus*.
- [ ] Live-gate tenant: which site/library and which user's OneDrive are safe to write to, and under which env var names (`SHAREPOINT_*` exist in conf; a `PARROT_LIVE_SHAREPOINT_SITE`-style test knob does not)? — *Owner: Jesus*.
- [ ] After this feature, should flowtask's `SharepointClient` drop its `drive.type=onedrive` shim in favour of `OneDriveFileManager` (separate repo follow-up)? — *Owner: Jesus*.
