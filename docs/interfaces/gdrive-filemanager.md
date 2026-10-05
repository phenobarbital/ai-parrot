# Google Drive file manager

`GoogleDriveFileManager` implements navigator's `FileManagerInterface` over Google Drive v3, so anything that works with `S3FileManager` works with a Google Drive folder (FEAT-608).

## Install

```bash
pip install "ai-parrot[gdrive]"
```

## Quick start

Service account:

```python
from parrot.interfaces.file import GoogleDriveFileManager

async with GoogleDriveFileManager(
    root_path="Reports/2026",
    prefix="q3/",
    credentials="env/google/key.json",
) as gd:
    files = await gd.list_files("", "*.xlsx")
    for f in files:
        print(f.name, f.size)
```

Shared drive:

```python
from parrot.interfaces.file import GoogleDriveFileManager

async with GoogleDriveFileManager(
    shared_drive_id="0AB…",
    root_path="Finance",
    auth_mode="cached",
) as sd:
    files = await sd.list_files()
    for f in files:
        print(f.name, f.size)
```

User (interactive login):

```python
from parrot.interfaces.file import GoogleDriveFileManager

async with GoogleDriveFileManager(
    root_id="1xYz…",
    auth_mode="user",
    interactive_login_kwargs={"port": 5050},
) as me:
    files = await me.list_files()
    for f in files:
        print(f.name, f.size)
```

## Authentication

The manager supports three `auth_mode` values:

- `service_account` — service account credentials (default). Use this for background jobs that need to act on behalf of the app.
- `user` — interactive login. The signed-in user consents; `interactive_login_kwargs` (e.g., `port`) configure the local OAuth2 server.
- `cached` — cached token from a previously authenticated `GoogleClient`. Use this when you already have an authenticated client and want to reuse its token.

Service accounts can access a shared drive, but the shared drive's My Drive quota applies to the service account, not the organization.

## Paths

All paths are **drive-relative** (not root-relative). The `prefix` parameter works like S3: it's prepended to every key before sending to Drive.

- `root_path` is a folder path under the configured root (My Drive or shared drive). The manager resolves it to the folder's Drive ID.
- `root_id` is the Drive folder ID to use as the root (mutually exclusive with `root_path`).
- `shared_drive_id` is the shared drive ID to use as the root. When set, `supportsAllDrives=True` and `includeItemsFromAllDrives=True` are sent on every API call.
- `..` segments are rejected; the manager validates paths before sending them to Drive.

Example:

```python
gd = GoogleDriveFileManager(
    root_path="Reports/2026",
    prefix="q3/",
)
# Uploads to: /drive/items/root:/Reports/2026/q3.xlsx
```

## Uploads and downloads

- **Threshold routing**: files smaller than `small_file_threshold` (default 5 MiB) are uploaded in a single request, but **only when `conflict_behavior == "replace"`** — Google Drive's simple content-PUT endpoint has no `conflictBehavior` parameter, so `"fail"`/`"rename"` always go through the resumable upload session regardless of size, even for a tiny file.
- **Conflict behavior**: `conflict_behavior` defaults to `"replace"`. Set to `"fail"` to raise on collision, or `"rename"` to append a suffix.
- **MIME type**: derived from the file name (`content_type` is not sent to Drive).
- **Bytes uploads**: `upload_file_from_bytes(data, path, content_type)` returns a sharing link (organization, view) for the uploaded item.

```python
# File upload
await gd.upload_file(Path("q3.xlsx"), "q3.xlsx")

# Bytes upload (returns sharing link)
url = await gd.upload_file_from_bytes(
    data=b"content",
    path="q3.pdf",
    content_type="application/pdf",
)

# Download
await gd.download_file("q3.xlsx", Path("/tmp/q3.xlsx"))
```

## Sharing links

- `get_file_url(path, expiry=0)` returns the item's `webViewLink` without changing permissions. If `expiry > 0`, the link expires at `now + expiry` seconds.
- `create_sharing_link(path, *, scope, role, email_address, expiry)` creates a sharing permission on the item with explicit options.

```python
# Get a view link (no expiration)
url = await gd.get_file_url("q3.xlsx")

# Create an edit link for users only, expiring in 1 hour
link = await gd.create_sharing_link(
    "q3.xlsx",
    scope="users",
    role="reader",
    email_address="a@b.com",
    expiry=3600,
)
```

## Batch operations

`upload_files` and `download_files` process multiple items in parallel:

- Each item gets a `BatchItemResult` with `state` (`succeeded` / `failed` / `skipped`).
- No exception is raised for a single item; failures are reported in the results.
- If an auth failure occurs, the rest of the batch is skipped (`aborted=True`).
- A stream object may not appear twice in the same batch.
- Concurrency defaults to 5; retries default to 3. Retryable status codes: 429, 500, 502, 503, 504. `Retry-After` is capped at 60 seconds.

```python
# Upload multiple files
results = await gd.upload_files([
    (Path("a.csv"), "in/a.csv"),
    (Path("b.bin"), "in/b.bin"),
])

# Download multiple files
results = await gd.download_files([
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
files = await gd.find_files(
    keywords="q3",
    extension=".xlsx",
    prefix="2026/",
)

# List entries (including folders)
entries = await gd.find_entries("2026/")
for e in entries:
    print(e.name, e.is_folder)
```

## Serving over HTTP

`setup(app, route)` registers a GET handler that serves files through `FileServingExtension`. The extension buffers whole files in memory; files larger than `serving_max_bytes` (default 64 MiB) return HTTP 413.

```python
from aiohttp import web

app = web.Application()
gd.setup(app, route="/gdrive")
web.run_app(app, port=8080)
# GET http://localhost:8080/gdrive/2026/q3.xlsx streams the file
```

**Note**: Workspace export (`files.export`) is not supported in v1.

## Agents (GoogleDriveToolkit)

`GoogleDriveToolkit` exposes the manager as a set of tools:

- `gdrive_list_files`, `gdrive_list_entries`, `gdrive_find_files`, `gdrive_exists`, `gdrive_get_file_metadata`
- `gdrive_upload_file`, `gdrive_create_file`, `gdrive_upload_file_from_bytes`, `gdrive_download_file`, `gdrive_copy_file`, `gdrive_delete_file`
- `gdrive_create_folder`, `gdrive_remove_folder`, `gdrive_rename_file`, `gdrive_rename_folder`, `gdrive_get_file_url`, `gdrive_create_sharing_link`
- `gdrive_batch_upload`, `gdrive_batch_download`

The toolkit also provides the agent-facing operations from the base `FileManagerTool`:

- `find` — server-side search (or in-memory fallback for backends without native `find_files`).
- `batch_upload` — parallel upload of multiple items.
- `batch_download` — parallel download of multiple items.

```python
from parrot_tools.google import GoogleDriveToolkit

toolkit = GoogleDriveToolkit(
    root_path="Reports",
    credentials="env/google/key.json",
)

# Tools are auto-exposed as gdrive_* methods
await toolkit.gdrive_find_files(keywords="q3", extension=".xlsx")
await toolkit.gdrive_batch_upload([(Path("a.csv"), "in/a.csv")])
await toolkit.gdrive_batch_download([("in/a.csv", Path("/tmp/a.csv"))])
```

## Permissions

The manager requires the following permissions, depending on the auth mode:

| Mode | Permission | Why |
|------|------------|-----|
| Service account | `drive` (full access) | read/write any user's Drive files |
| User | `drive` (full access) | the signed-in user's Drive files |
| Cached | `drive` (full access) | reuse a previously authenticated user token |

Service account permissions require admin consent.

## Live tests

The feature includes an opt-in live test suite gated on environment variables:

- `PARROT_LIVE_GDRIVE_ENABLED` — enable Google Drive live tests.
- `PARROT_LIVE_GDRIVE_ROOT_ID` — Drive folder ID to test against.

Run the live suite manually before `/sdd-done`:

```bash
pytest packages/ai-parrot/tests/test_gdrive_docs.py -m live
```

The suite exercises the real Google Drive API with a small synthetic dataset and validates the manager's behavior against the documented contract.
