# SharePoint & OneDrive file managers

`SharePointFileManager` and `OneDriveFileManager` implement navigator's `FileManagerInterface` over Microsoft Graph, so anything that works with `S3FileManager` works with a SharePoint document library or a OneDrive (FEAT-603).

## Install

    pip install "ai-parrot[msgraph]"

## Quick start

SharePoint:

```python
from parrot.interfaces.file import SharePointFileManager

async with SharePointFileManager(
    site="troc",
    library="Documents",
    prefix="reports/",
    credentials={
        "client_id": "your-client-id",
        "client_secret": "your-client-secret",
        "tenant_id": "your-tenant-id",
        "tenant": "troc",
    },
) as sp:
    files = await sp.list_files("2026/", "*.xlsx")
    for f in files:
        print(f.name, f.size)
```

OneDrive:

```python
from parrot.interfaces.file import OneDriveFileManager

async with OneDriveFileManager(
    user="me",
    credentials={
        "client_id": "your-client-id",
        "client_secret": "your-client-secret",
        "tenant_id": "your-tenant-id",
    },
    auth_mode="delegated",
) as od:
    files = await od.list_files()
    for f in files:
        print(f.name, f.size)
```

## Authentication

The managers support four `auth_mode` values:

- `direct` — client credentials (app-only). Use this for background jobs that need to act on behalf of the app.
- `on_behalf_of` — on-behalf-of flow. Callers that already hold a user token (e.g., an OAuth2 callback) can pass it via `user_assertion`.
- `delegated` — interactive login. The signed-in user consents; `user="me"` requires this mode.
- `cached` — cached token from the O365 client. Use this when you already have an authenticated `O365Client` and want to reuse its token.

For username/password (ROPC) credentials, pass `username` and `password` in the `credentials` dict; the underlying `O365Client` picks them up.

If you already hold an authenticated `O365Client` (e.g., the O365 tools do), use `adopt_client(client)` to let the manager reuse it instead of creating a new one.

## Paths

All paths are **drive-relative** (not site-relative). The `prefix` parameter works like S3: it's prepended to every key before sending to Graph.

- `site` is a sub-site path like `"parent/sub"`. The manager resolves it to `/sites/parent/sub`.
- `library` defaults to `"Documents"`. The manager resolves it to the drive for that library.
- `"Shared Documents"` is an alias for `"Documents"` on SharePoint.
- `..` segments are rejected; the manager validates paths before sending them to Graph.

Example:

```python
sp = SharePointFileManager(
    site="parent/sub",
    library="Documents",
    prefix="reports/2026/",
)
# Uploads to: /drives/{drive-id}/items/root:/reports/2026/q3.xlsx
```

## Uploads and downloads

- **Threshold routing**: files smaller than `small_file_threshold` (default 4 MiB) are uploaded in a single request, but **only when `conflict_behavior == "replace"`** — Graph's simple content-PUT endpoint has no `conflictBehavior` parameter, so `"fail"`/`"rename"` always go through the resumable upload session regardless of size, even for a tiny file.
- **Conflict behavior**: `conflict_behavior` defaults to `"replace"`. Set to `"fail"` to raise on collision, or `"rename"` to append a suffix.
- **MIME type**: derived from the file name (`content_type` is not sent to Graph).
- **Bytes uploads**: `upload_file_from_bytes(data, path, content_type)` returns a sharing link (organization, view) for the uploaded item.

```python
# File upload
await sp.upload_file(Path("q3.xlsx"), "2026/q3.xlsx")

# Bytes upload (returns sharing link)
url = await sp.upload_file_from_bytes(
    data=b"content",
    path="2026/q3.pdf",
    content_type="application/pdf",
)

# Download
await sp.download_file("2026/q3.xlsx", Path("/tmp/q3.xlsx"))
```

## Sharing links

- `get_file_url(path, expiry=0)` creates an organization/view sharing link. If `expiry > 0`, the link expires at `now + expiry` seconds.
- `create_sharing_link(path, *, link_type="view", scope="organization", expiry=0)` creates a sharing permission on the item with explicit options.

```python
# Get a view link (no expiration)
url = await sp.get_file_url("2026/q3.xlsx")

# Create an edit link for users only, expiring in 1 hour
link = await sp.create_sharing_link(
    "2026/q3.xlsx",
    link_type="edit",
    scope="users",
    expiry=3600,
)
```

## Batch operations

`upload_files` and `download_files` process multiple items in parallel:

- Each item gets a `BatchItemResult` with `state` (`succeeded` / `failed` / `skipped`).
- No exception is raised for a single item; failures are reported in the results.
- If an auth failure occurs, the rest of the batch is skipped (`aborted=True`).
- A stream object may not appear twice in the same batch.
- Concurrency defaults to 5; retries default to 3. Retryable status codes: 429, 503, 504. `Retry-After` is capped at 60 seconds.

```python
# Upload multiple files
results = await sp.upload_files([
    (Path("a.csv"), "in/a.csv"),
    (Path("b.bin"), "in/b.bin"),
])

# Download multiple files
results = await sp.download_files([
    ("in/a.csv", Path("/tmp/a.csv")),
    ("in/b.bin", Path("/tmp/b.bin")),
])
```

## Search

- `find_files(keywords, extension=None, prefix=None, max_results=None)` performs server-side search on the drive.
- `find_entries(path, max_results=None)` returns `DriveEntry` rows (including folders) for a directory.
- Both methods follow `@odata.nextLink` to the end; `max_results` is applied after filtering all pages.

```python
# Find files by keyword and extension
files = await sp.find_files(
    keywords="q3",
    extension=".xlsx",
    prefix="2026/",
)

# List entries (including folders)
entries = await sp.find_entries("2026/")
for e in entries:
    print(e.name, e.is_folder)
```

## Serving over HTTP

`setup(app, route)` registers a GET handler that serves files through `FileServingExtension`. The extension buffers whole files in memory; files larger than `serving_max_bytes` (default 64 MiB) return HTTP 413.

```python
from aiohttp import web

app = web.Application()
sp.setup(app, route="/sp")
web.run_app(app, port=8080)
# GET http://localhost:8080/sp/2026/q3.xlsx streams the file
```

## Agents (FileManagerToolkit)

`FileManagerToolkit(manager_type="sharepoint" | "onedrive", ...)` exposes the manager as a set of tools:

- `fs_list_files`, `fs_list_entries`, `fs_find_files`, `fs_exists`, `fs_get_file_metadata`
- `fs_upload_file`, `fs_create_file`, `fs_upload_file_from_bytes`, `fs_download_file`, `fs_copy_file`, `fs_delete_file`
- `fs_create_folder`, `fs_remove_folder`, `fs_rename_file`, `fs_rename_folder`, `fs_get_file_url`, `fs_create_sharing_link`
- `fs_batch_upload`, `fs_batch_download`

The toolkit also provides the agent-facing operations from the base `FileManagerTool`:

- `find` — server-side search (or in-memory fallback for backends without native `find_files`).
- `batch_upload` — parallel upload of multiple items.
- `batch_download` — parallel download of multiple items.

```python
from parrot.tools.filemanager import FileManagerToolkit

toolkit = FileManagerToolkit(
    manager_type="sharepoint",
    site="troc",
    library="Documents",
    credentials={...},
    auth_mode="direct",
)

# Tools are auto-exposed as fs_* methods
await toolkit.fs_find_files(keywords="q3", extension=".xlsx")
await toolkit.fs_batch_upload([(Path("a.csv"), "in/a.csv")])
await toolkit.fs_batch_download([("in/a.csv", Path("/tmp/a.csv"))])
```

## Permissions

The managers require the following permissions, depending on the auth mode:

| Mode | Permission | Why |
|------|------------|-----|
| Application (app-only) | `Sites.ReadWrite.All` | read/write SharePoint document libraries |
| Application (app-only) | `Files.ReadWrite.All` | read/write any user's OneDrive (`user="<upn>"`) |
| Delegated | `Files.ReadWrite` | the signed-in user's OneDrive (`user="me"`) |
| Delegated | `Sites.ReadWrite.All` | SharePoint libraries the user can write to |

Application permissions require admin consent.

## Live tests

The feature includes an opt-in live test suite gated on environment variables:

- `PARROT_LIVE_SHAREPOINT_ENABLED` — enable SharePoint live tests.
- `PARROT_LIVE_ONEDRIVE_ENABLED` — enable OneDrive live tests.
- `PARROT_LIVE_SHAREPOINT_SITE` — SharePoint site to test against.
- `PARROT_LIVE_ONEDRIVE_USER` — OneDrive user to test against.

Run the live suite manually before `/sdd-done`:

```bash
pytest packages/ai-parrot/tests/test_graph_filemanager_docs.py -m live
```

The suite exercises the real Graph API with a small synthetic dataset and validates the manager's behavior against the documented contract.
