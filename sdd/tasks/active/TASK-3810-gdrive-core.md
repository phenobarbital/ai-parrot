# TASK-3810: `gdrive.py` core — constructor, lifecycle/auth, path resolver, retry & errors

**Feature**: FEAT-608 — Google Drive FileManager
**Spec**: `sdd/specs/google-drive-interface.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-3806, TASK-3807, TASK-3808
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 2 (goals G1–G4; AC2, AC3, AC5, AC6). Creates the `GoogleDriveFileManager`
class skeleton that TASK-3811 (reads) and TASK-3812..3814 (writes) extend. The class is a
direct `FileManagerInterface` subclass — never a `GraphDriveFileManager` subclass — and must
not import `parrot.interfaces.google` at module level (that module loads selenium /
playwright / redis at import, `google.py:23-31`).

Until TASK-3811..3814 land, the abstract interface methods are not implemented, so the
class stays abstract; tests instantiate it by clearing `__abstractmethods__` via
`monkeypatch` (FEAT-603 precedent, `test_file_shim.py:159-181`). TASK-3814 removes that need.

---

## Scope

- Create `packages/ai-parrot/src/parrot/interfaces/file/gdrive.py` with: module literals
  (`GoogleAuthModeLiteral`, `ConflictBehavior`, `ShareScope`, `ShareRole`, `FOLDER_MIME`,
  `WORKSPACE_MIME_PREFIX`), `GoogleDriveFileManagerError`, `_AsyncSink`, the retry-counter
  `ContextVar`, and `GoogleDriveFileManager` with every member of the spec §3 M2 skeleton:
  class constants, `__init__`, `_build_client`, `_resolve_root_id`, `connect`, `adopt_client`,
  `close`, `__aenter__/__aexit__`, `client`/`drive`/`root_id` properties, `_ready`,
  `_prefixed`, `_unprefixed`, `_escape_q`, `_list_params`, `_resolve`, `_resolve_parent`,
  `_invalidate`, `_make_metadata`, `_make_entry`, `_is_folder`, `_is_workspace_native`,
  `_status_code_of`, `_retry_after_seconds`, `_map_error`, `_retrying`, `_sleep`,
  `_validate_upload_url`.
- Create `packages/ai-parrot/tests/interfaces/test_gdrive_filemanager.py` with the M2 tests.

**NOT in scope**: list/download/search (TASK-3811), uploads (TASK-3812), mutations/sharing
(TASK-3813), batch/serving (TASK-3814), shim/factory registration (TASK-3815).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/interfaces/file/gdrive.py` | CREATE | Class skeleton + core |
| `packages/ai-parrot/tests/interfaces/test_gdrive_filemanager.py` | CREATE | M2 unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from navigator.utils.file import FileManagerInterface, FileMetadata            # verified: graph.py:49; abstract.py:16, :36
from parrot.interfaces.file.batch import BatchErrorCode, BatchItemResult, BatchState, BatchSummary   # verified: batch.py:14-71
from parrot.interfaces.file.entries import DriveEntry, GuardedFileServingExtension   # created by TASK-3808
# ONLY inside connect()/_build_client()/adopt_client(), and under TYPE_CHECKING at module level:
from parrot.interfaces.google import GoogleClient, DriveClient                 # verified: google.py:226; DriveClient from TASK-3807
# tests:
from ._gdrive_fakes import FakeDrive, FakeDriveClient, FakeHTTPError, make_google_client, make_manager   # TASK-3806
```

### Existing Signatures to Use
```python
# navigator/utils/file/abstract.py
@dataclass class FileMetadata: name: str; path: str; size: int; content_type: Optional[str]; modified_at: Optional[datetime]; url: Optional[str]   # :15-33

# parrot/interfaces/google.py
GoogleClient.__init__(self, credentials=None, scopes=None, user_creds_cache_file=None, **kwargs)   # :275-281
GoogleClient.is_authenticated (property)                        # :637-640
async def initialize(self) -> GoogleClient                      # :650 — RuntimeError "User credentials not available. Run interactive_login() first."
async def interactive_login(self, scopes=None, port=5050, redirect_uri=None, open_browser=True, browser="system", login_callback=None, timeout=300)   # :827-836
async def get_drive_client(self, version="v3") -> DriveClient   # TASK-3807
async def close(self) -> None                                   # :1051 (only flips _authenticated)
self.redis  # aioredis client built eagerly in __init__         # :299-302

# parrot_tools/google/base.py — auth branch table to reproduce   # :110-135
#   service_account → await client.initialize()
#   user → await client.interactive_login(scopes=..., **interactive_login_kwargs); await client.initialize()
#   cached → try initialize(); except RuntimeError as e: if "User credentials not available" not in str(e): raise; interactive_login(...); initialize()
#   else → ValueError(f"Unsupported Google auth mode: {mode}")

# parrot/interfaces/file/graph.py — retry/error patterns to copy (adapt attribute access to error.res)
_status_code_of :399 · _retry_after_seconds :411-438 · _map_error :439-448 · _retrying :450-468 · _RETRY_COUNTER :58-60
# navigator gcs.py:120-128 — _prefixed / _unprefixed shape
```

### Does NOT Exist
- ~~`GraphDriveFileManager` as a base~~ — do not subclass or import `graph.py`.
- ~~`GoogleClient.execute_api_call` for Drive~~ — never call it (re-discovers per call).
- ~~`packages/ai-parrot/tests/interfaces/conftest.py`~~.
- ~~`FileMetadata.is_folder`~~ — `FileMetadata` has no folder flag; folders are `DriveEntry` only.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/interfaces/file/gdrive.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/interfaces/test_gdrive_filemanager.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/interfaces/google.py#GoogleClient",
    "sym:packages/ai-parrot/src/parrot/interfaces/google.py#GoogleClient.initialize",
    "sym:packages/ai-parrot/src/parrot/interfaces/google.py#GoogleClient.interactive_login",
    "sym:packages/ai-parrot-tools/src/parrot_tools/google/base.py#GoogleBaseTool._get_client",
    "sym:packages/ai-parrot/src/parrot/interfaces/file/graph.py#GraphDriveFileManager._retrying",
    "sym:packages/ai-parrot/src/parrot/interfaces/file/graph.py#GraphDriveFileManager._map_error"
  ]
}
```

---

## Implementation Notes

- **Module-level Google import is forbidden** (AC2): `if TYPE_CHECKING: from parrot.interfaces.google import DriveClient, GoogleClient`;
  `_build_client()` does `from parrot.interfaces.google import GoogleClient` locally. Tests of
  `connect()` monkeypatch `parrot.interfaces.google.GoogleClient` with a recording fake class.
- **Status extraction**: aiogoogle `HTTPError.res.status_code` / `.res.headers` (excs.py:22-25);
  fall back to `status_code` / `status` attributes (so `FakeHTTPError` and plain errors both work).
- **403 rate limit** (spec §7 Known Risks): a 403 whose `res.json["error"]["errors"][0]["reason"]`
  is `userRateLimitExceeded` or `rateLimitExceeded` is treated as retryable in `_retrying` and
  mapped to `GoogleDriveFileManagerError(status_code=403)` (not `PermissionError`) by `_map_error`.
- **Path cache**: `_path_cache: Dict[str, Tuple[str, bool]]` keyed by the full prefixed path
  (`""` → root id). `_invalidate(p)` drops `p` and every key starting with `p + "/"`.
- **Duplicate names**: `files_list(..., order_by="modifiedTime desc", page_size=2)` returns the
  newest first; when the first two share `modifiedTime`, pick the smaller `id`.
- **`_escape_q`**: `value.replace("\\", "\\\\").replace("'", "\\'")`.
- **`..` segments** → `ValueError("invalid path: '..' segments are not allowed")` (include the word
  "path" — TASK-3814's `_classify` keys `invalid_path` on it, graph.py:1105).
- **`close()`** for an owned client: close the DriveClient, `await client.close()`, then
  `with contextlib.suppress(Exception): await client.redis.aclose()` when `client.redis` is set
  (spec §7 Known Risks). Never close an adopted client.
- Test module header: `sys.modules.pop("parrot.interfaces.file", None)` before imports.
- Construction tests: `monkeypatch.setattr(GoogleDriveFileManager, "__abstractmethods__", frozenset())`.

---

## Implementation Blueprint

### Steps (in order)
1. Write the module header, literals, error, `_AsyncSink` — *why*: TASK-3811..3816 import these names.
2. Write the class constants and `__init__` — *why*: spec §3 M2 fixes them; no I/O in the constructor.
3. Write lifecycle + auth branch table — *why*: AC3.
4. Write the path model — *why*: AC5, AC6.
5. Write retry/error helpers — *why*: single retry policy used by every later task.
6. Write the tests.

### `packages/ai-parrot/src/parrot/interfaces/file/gdrive.py` (CREATE — header)
```python
"""FileManagerInterface over Google Drive v3 (My Drive folders and shared drives) — FEAT-608."""
from __future__ import annotations

import asyncio
import contextlib
import contextvars
import logging
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import (TYPE_CHECKING, Any, AsyncIterator, Awaitable, BinaryIO, Callable, Dict, List, Literal,
                    Optional, Sequence, Tuple, Union)
from urllib.parse import urlsplit

from navigator.utils.file import FileManagerInterface, FileMetadata

from .batch import BatchErrorCode, BatchItemResult, BatchState, BatchSummary
from .entries import DriveEntry, GuardedFileServingExtension

if TYPE_CHECKING:
    from parrot.interfaces.google import DriveClient, GoogleClient

__all__ = ("BatchItemResult", "BatchSummary", "ConflictBehavior", "DriveEntry", "GoogleDriveFileManager",
           "GoogleDriveFileManagerError", "ShareRole", "ShareScope")

GoogleAuthModeLiteral = Literal["service_account", "user", "cached"]
ConflictBehavior = Literal["replace", "fail", "rename"]
ShareScope = Literal["user", "group", "domain", "anyone"]
ShareRole = Literal["reader", "commenter", "writer"]
FOLDER_MIME = "application/vnd.google-apps.folder"
WORKSPACE_MIME_PREFIX = "application/vnd.google-apps."
_RATE_LIMIT_REASONS = frozenset({"userRateLimitExceeded", "rateLimitExceeded"})

# Incremented by _retrying on every retry; set per batch item by _run_batch (TASK-3814).
_RETRY_COUNTER: contextvars.ContextVar[Optional[List[int]]] = contextvars.ContextVar(
    "_gdrive_retry_counter", default=None
)


class GoogleDriveFileManagerError(RuntimeError):
    """Base error for Google Drive file-manager failures, with an optional status code."""

    def __init__(self, message: str, *, status_code: Optional[int] = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class _AsyncSink:
    """Adapter giving a sync ``BinaryIO`` the ``await sink.write(chunk)`` contract aiogoogle's ``pipe_to`` expects."""

    def __init__(self, target: BinaryIO) -> None:
        self.target = target

    async def write(self, chunk: bytes) -> None:
        self.target.write(chunk)
```

### `gdrive.py` (CREATE — class constants + constructor)
```python
class GoogleDriveFileManager(FileManagerInterface):
    """FileManagerInterface over one Google Drive root (My Drive folder or shared drive).

    Paths are drive-relative and prefixed with ``prefix`` exactly like S3's ``prefix + key``.
    """

    manager_name: str = "gdrivefile"
    FOLDER_MIME: str = FOLDER_MIME
    WORKSPACE_MIME_PREFIX: str = WORKSPACE_MIME_PREFIX
    SMALL_FILE_THRESHOLD: int = 5 * 1024 * 1024
    CHUNK_SIZE: int = 8 * 1024 * 1024
    MAX_CONCURRENCY: int = 5
    MAX_RETRIES: int = 3
    RETRYABLE_STATUS: frozenset = frozenset({429, 500, 502, 503, 504})
    SERVING_MAX_BYTES: int = 64 * 1024 * 1024
    ALLOWED_HOSTS: tuple = ("www.googleapis.com",)
    LIST_PAGE_SIZE: int = 1000
    FIELDS: str = "id,name,mimeType,size,modifiedTime,webViewLink,webContentLink,parents,trashed"
    LIST_FIELDS: str = "nextPageToken,files(" + FIELDS + ")"

    def __init__(self, *, root_id: Optional[str] = None, root_path: str = "", shared_drive_id: Optional[str] = None,
                 prefix: str = "", credentials: Optional[Union[str, Dict[str, Any], Path]] = None,
                 auth_mode: GoogleAuthModeLiteral = "service_account", scopes: Optional[Union[str, List[str]]] = None,
                 user_creds_cache_file: Optional[Union[str, Path]] = None,
                 interactive_login_kwargs: Optional[Dict[str, Any]] = None,
                 conflict_behavior: ConflictBehavior = "replace", permanent_delete: bool = False,
                 max_concurrency: Optional[int] = None, max_retries: Optional[int] = None,
                 chunk_size: Optional[int] = None, small_file_threshold: Optional[int] = None,
                 serving_max_bytes: Optional[int] = None, **kwargs: Any) -> None:
        """Store configuration; NO network I/O and NO GoogleClient construction.

        Raises:
            ValueError: ``root_id`` and ``root_path`` both given; ``chunk_size`` not a multiple of 262144;
                unknown ``auth_mode`` / ``conflict_behavior``.
        """
        self.logger = logging.getLogger(__name__)
        # FILL IN: validate + store every argument (defaults from the class constants); normalise prefix to
        #          "a/b/" or ""; normalise root_path (strip "/"); log-and-ignore unknown kwargs;
        #          init _client=None, _owns_client=False, _drive=None, _root_id=None, _path_cache={}
        #          — bounded by spec §3 M2 constructor docstring
```

### `gdrive.py` (CREATE — lifecycle)
```python
    def _build_client(self) -> "GoogleClient":
        from parrot.interfaces.google import GoogleClient   # lazy: google.py loads selenium/redis

        kwargs: Dict[str, Any] = {}
        if self.user_creds_cache_file is not None:
            kwargs["user_creds_cache_file"] = self.user_creds_cache_file
        return GoogleClient(credentials=self.credentials, scopes=self.scopes or "drive", **kwargs)

    async def _authenticate(self, client: "GoogleClient") -> None:
        # FILL IN: GoogleBaseTool._get_client branch table (base.py:110-135) over self.auth_mode,
        #          interactive_login(scopes=self.scopes or "drive", **self.interactive_login_kwargs) — bounded by AC3
        raise NotImplementedError

    async def _resolve_root_id(self) -> str:
        # FILL IN: shared_drive_id → it; root_id → files_get(root_id, fields="id,mimeType", **self._list_params())
        #          (FileNotFoundError on 404); else "root"; then walk self.root_path segments with _resolve — bounded by AC5
        raise NotImplementedError

    async def connect(self) -> "GoogleDriveFileManager":
        """Build + authenticate per ``auth_mode``, open the DriveClient, resolve the root id. Idempotent (AC3)."""
        if self._client is None:
            client = self._build_client()
            await self._authenticate(client)
            self._client, self._owns_client = client, True
        await self._ready()
        return self

    def adopt_client(self, client: "GoogleClient") -> None:
        """Reuse an already-initialised GoogleClient; ``close()`` never closes it."""
        if not client.is_authenticated:
            raise GoogleDriveFileManagerError("adopt_client() requires an initialised GoogleClient")
        self._client, self._owns_client = client, False

    async def _ready(self) -> str:
        if self._client is None:
            await self.connect()      # FILL IN: guard recursion — connect() calls _ready() only after _client is set
        if self._drive is None:
            self._drive = await self._client.get_drive_client()
            await self._drive.open()
        if self._root_id is None:
            self._root_id = await self._resolve_root_id()
        return self._root_id

    async def close(self) -> None:
        # FILL IN: close DriveClient; if _owns_client: await client.close() + suppress(redis.aclose());
        #          clear _drive/_root_id/_path_cache (and _client only when owned) — bounded by Implementation Notes
        ...

    async def __aenter__(self) -> "GoogleDriveFileManager":
        return await self.connect()

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        await self.close()

    # FILL IN: properties client / drive / root_id raising GoogleDriveFileManagerError before connect/adopt/_ready
```

### `gdrive.py` (CREATE — path model & mapping)
```python
    def _prefixed(self, key: str) -> str:
        # FILL IN: strip "/" ; reject any ".." segment (ValueError mentioning "path"); return (self.prefix + key).strip("/")
        raise NotImplementedError

    def _unprefixed(self, key: str) -> str:
        return key[len(self.prefix):] if self.prefix and key.startswith(self.prefix) else key

    @staticmethod
    def _escape_q(value: str) -> str:
        return value.replace("\\", "\\\\").replace("'", "\\'")

    def _list_params(self, **extra: Any) -> Dict[str, Any]:
        params: Dict[str, Any] = {"supportsAllDrives": True}
        if self.shared_drive_id:
            params.update(includeItemsFromAllDrives=True, corpora="drive", driveId=self.shared_drive_id)
        params.update(extra)
        return params

    async def _resolve(self, full_path: str, *, want_folder: Optional[bool] = None) -> Tuple[str, bool]:
        """Segment walk from the root; newest wins, ties by smallest id; cached; FileNotFoundError."""
        # FILL IN: q = f"'{parent}' in parents and name = '{self._escape_q(seg)}' and trashed = false";
        #          files_list(q=q, fields=self.LIST_FIELDS, page_size=2, order_by="modifiedTime desc", **self._list_params())
        #          wrapped in _retrying(label="resolve"); cache every intermediate prefix; want_folder mismatch → FileNotFoundError
        raise NotImplementedError

    async def _resolve_parent(self, full_path: str, *, create: bool) -> str:
        # FILL IN: parent of full_path ("" → root id); when create, files_create({"name", "mimeType": FOLDER_MIME,
        #          "parents": [pid]}, fields=FIELDS, **_list_params()) for each missing segment; cache them
        raise NotImplementedError

    def _invalidate(self, full_path: str) -> None:
        for key in [k for k in self._path_cache if k == full_path or k.startswith(full_path + "/")]:
            self._path_cache.pop(key, None)

    # FILL IN: _is_folder / _is_workspace_native (mimeType checks) ; _make_metadata(item, *, full_path) →
    #          FileMetadata(name, _unprefixed(full_path), int(item.get("size") or 0), item.get("mimeType"),
    #          parsed modifiedTime (fromisoformat after replacing "Z" with "+00:00"), item.get("webViewLink"));
    #          _make_entry → DriveEntry(id, name, path, is_folder, size, modified_at, web_url, content_type)
```

### `gdrive.py` (CREATE — errors & retry)
```python
    @staticmethod
    def _status_code_of(error: BaseException) -> Optional[int]:
        res = getattr(error, "res", None)
        code = getattr(res, "status_code", None)
        if isinstance(code, int) and code:
            return code
        for attribute in ("status_code", "status"):
            code = getattr(error, attribute, None)
            if isinstance(code, int) and code:
                return code
        return None

    @staticmethod
    def _retry_after_seconds(error: BaseException) -> Optional[float]:
        # FILL IN: graph.py:411-438 semantics over getattr(getattr(error, "res", None), "headers", None)
        raise NotImplementedError

    @staticmethod
    def _is_rate_limited_403(error: BaseException) -> bool:
        # FILL IN: 403 and res.json["error"]["errors"][0]["reason"] in _RATE_LIMIT_REASONS (defensive dict access)
        raise NotImplementedError

    def _map_error(self, exc: BaseException, *, path: str) -> BaseException:
        status = self._status_code_of(exc)
        if status == 404:
            return FileNotFoundError(path)
        if status in {401, 403} and not self._is_rate_limited_403(exc):
            return PermissionError("Google Drive access was denied")
        if status == 409:
            return FileExistsError(path)
        return GoogleDriveFileManagerError(str(exc), status_code=status)

    async def _retrying(self, op: Callable[[], Awaitable[Any]], *, label: str, idempotent: bool = True) -> Tuple[Any, int]:
        # FILL IN: copy graph.py:450-468; retryable = status in RETRYABLE_STATUS or _is_rate_limited_403;
        #          delay = min(retry_after or 2 ** (attempts - 1), 60); bump _RETRY_COUNTER; never when not idempotent
        raise NotImplementedError

    async def _sleep(self, seconds: float) -> None:
        await asyncio.sleep(seconds)

    def _validate_upload_url(self, url: str) -> str:
        parts = urlsplit(url)
        if parts.scheme != "https" or parts.hostname not in self.ALLOWED_HOSTS:
            raise GoogleDriveFileManagerError("resumable session URL rejected by the host allow-list")
        return url
```
**Why**: `_validate_upload_url` must never include the URL in the message or logs (AC7 — it
carries an upload token). The retry helper returns `(result, attempts)` exactly like Graph so
TASK-3814's batch engine can reuse the counter.

### `packages/ai-parrot/tests/interfaces/test_gdrive_filemanager.py` (CREATE)
```python
"""FEAT-608 GoogleDriveFileManager unit tests (TASK-3810 core; extended by TASK-3811..3814)."""
import datetime as dt
import sys

import pytest

sys.modules.pop("parrot.interfaces.file", None)
from parrot.interfaces.file.gdrive import GoogleDriveFileManager, GoogleDriveFileManagerError  # noqa: E402

from ._gdrive_fakes import FakeDrive, FakeDriveClient, FakeHTTPError, make_google_client, make_manager  # noqa: E402


async def _no_sleep(seconds: float) -> None:
    return None


@pytest.fixture(autouse=True)
def _concrete(monkeypatch):
    # Remove once TASK-3814 lands (all abstract methods implemented).
    monkeypatch.setattr(GoogleDriveFileManager, "__abstractmethods__", frozenset())


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


def test_constructor_defaults_and_validation(): ...
async def test_connect_auth_mode_branches(monkeypatch): ...
async def test_adopt_client_skips_auth_and_never_closes(manager): ...
async def test_resolve_root_shared_drive_root_id_root_path(): ...
async def test_resolve_walks_segments_with_escaped_q_and_caches(manager): ...
async def test_resolve_duplicate_names_newest_then_smallest_id(): ...
def test_prefixed_unprefixed_roundtrip(): ...
def test_rejects_parent_segments(): ...
def test_map_error_and_status_from_httperror(): ...
async def test_retry_policy_caps_retry_after_and_never_non_idempotent(manager): ...
async def test_rate_limited_403_is_retried(manager): ...
def test_validate_upload_url_rejects_http_and_foreign_hosts(caplog): ...
def test_gdrive_import_does_not_load_google_module(): ...   # subprocess: import gdrive → "parrot.interfaces.google" not in sys.modules
```

### FILL IN checklist
- [ ] `__init__` validation/normalisation — spec §3 M2.
- [ ] `_authenticate` branch table — AC3.
- [ ] `_resolve_root_id`, `_resolve`, `_resolve_parent` — AC5/AC6.
- [ ] `_ready` recursion guard; `close`; properties.
- [ ] `_make_metadata` / `_make_entry` / `_is_folder` / `_is_workspace_native`.
- [ ] `_retry_after_seconds`, `_is_rate_limited_403`, `_retrying`.
- [ ] 13 tests.

---

## Acceptance Criteria

- [ ] AC2, AC3, AC5, AC6 covered by the tests above.
- [ ] `ruff check packages/ai-parrot/src/parrot/interfaces/file/gdrive.py` clean.

## Validation Commands
- `pytest packages/ai-parrot/tests/interfaces/test_gdrive_filemanager.py -q`

---

## Agent Instructions
Standard. `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-tools/src` inside the worktree.

---

## Completion Note

*(Agent fills this in when done)*
