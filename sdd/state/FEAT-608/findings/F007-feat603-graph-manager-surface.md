---
id: F007
query_id: Q009
type: tree
intent: FEAT-603 reference implementation layout + GraphDriveFileManager public surface (Q009 + Q010 outline)
executed_at: 2026-09-25T22:53:20Z
duration_ms: 1500
parent_id: null
depth: 0
---

# F007 — The FEAT-603 worktree ships `graph.py` (51.7K) with a base manager whose extension surface is the template for Drive

## Summary

`.claude/worktrees/feat-FEAT-603-sharepoint-filemanager/packages/ai-parrot/src/parrot/interfaces/file/`
holds `__init__.py`, `abstract.py`/`local.py`/`tmp.py`/`s3.py`/`gcs.py` (tiny
upstream re-export stubs), `batch.py`, `graph.py`, `sharepoint.py`,
`onedrive.py`. `graph.py` defines `DriveEntry`, `GraphFileManagerError`,
`_GuardedFileServingExtension` (413 over `serving_max_bytes`) and the abstract
`GraphDriveFileManager(FileManagerInterface, ABC)` with tunables, two abstract
hooks, lifecycle (`connect`/`adopt_client`/`close`), the nine interface
methods, folder/rename hooks, and the extensions `list_entries`,
`find_entries`, `find_files`, `upload_file_from_bytes`, `create_sharing_link`,
`upload_files`, `download_files`, `_run_batch`. Everything in it is Microsoft
Graph-specific (msgraph request builders, `@odata.nextLink`, `createLink`),
so a Drive manager must be a **sibling**, not a subclass.

## Citations

- path: `.claude/worktrees/feat-FEAT-603-sharepoint-filemanager/packages/ai-parrot/src/parrot/interfaces/file/graph.py`
  lines: 93-130
  symbol: `DriveEntry / _RawHTTPError / GraphFileManagerError`
  excerpt: |
    class DriveEntry(BaseModel): ...        # id, name, path, is_folder, size, modified_at, web_url, content_type
    class GraphFileManagerError(RuntimeError):
        def __init__(self, message: str, *, status_code: Optional[int] = None) -> None: ...

- path: `.claude/worktrees/feat-FEAT-603-sharepoint-filemanager/packages/ai-parrot/src/parrot/interfaces/file/graph.py`
  lines: 131-155
  symbol: `GraphDriveFileManager` class attributes
  excerpt: |
    class GraphDriveFileManager(FileManagerInterface, ABC):
        SMALL_FILE_THRESHOLD = 4 MiB; CHUNK_SIZE = 10 MiB; MAX_CONCURRENCY = 5; MAX_RETRIES = 3
        COPY_TIMEOUT_S = 120.0; RETRYABLE_STATUS = {429, 503, 504}; SERVING_MAX_BYTES = 64 MiB
        ALLOWED_ORIGINS = (...graph origins...); ALLOWED_HOST_SUFFIXES = (".sharepoint.com", ".sharepoint-df.com", ".files.1drv.com")

- path: `.claude/worktrees/feat-FEAT-603-sharepoint-filemanager/packages/ai-parrot/src/parrot/interfaces/file/graph.py`
  lines: 213-228
  symbol: `_build_client / _resolve_drive_id / client / drive_id`
  excerpt: |
    def _build_client(self) -> O365Client: ...          # abstract
    async def _resolve_drive_id(self) -> str: ...       # abstract
    @property def client(self) -> O365Client
    @property def drive_id(self) -> str

- path: `.claude/worktrees/feat-FEAT-603-sharepoint-filemanager/packages/ai-parrot/src/parrot/interfaces/file/graph.py`
  lines: 296-361
  symbol: `connect / adopt_client / close`
  excerpt: |
    async def connect(self) -> "GraphDriveFileManager"
    def adopt_client(self, client: O365Client) -> None     # reuse an authenticated client, never close it
    async def close(self) -> None

- path: `.claude/worktrees/feat-FEAT-603-sharepoint-filemanager/packages/ai-parrot/src/parrot/interfaces/file/graph.py`
  lines: 517-983
  symbol: public operation surface
  excerpt: |
    list_files:517  list_entries:535  exists:549  get_file_metadata:562  find_entries:572  find_files:624
    delete_file:644  upload_file:738  create_file:780  upload_file_from_bytes:785  download_file:793
    copy_file:835  create_sharing_link:890  get_file_url:936  create_folder:940  remove_folder:949
    rename_file:959  rename_folder:963  upload_files:983  download_files:~993  _run_batch:~1006

- path: `.claude/worktrees/feat-FEAT-603-sharepoint-filemanager/packages/ai-parrot/src/parrot/interfaces/file/graph.py`
  lines: 62-69
  symbol: `_GuardedFileServingExtension.handle_file`
  excerpt: |
    class _GuardedFileServingExtension(FileServingExtension):
        def __init__(self, *args, max_bytes: int, **kwargs) -> None: ...
        async def handle_file(self, request: web.Request) -> web.StreamResponse: ...   # 413 above max_bytes (AC22)

## Notes

The worktree has four **uncommitted** modifications (`graph.py`,
`sharepoint.py`, `tools/filemanager.py`, `parrot_tools/o365/onedrive.py`) —
a review pass is in flight; line numbers above may shift by a few lines once
it lands.
