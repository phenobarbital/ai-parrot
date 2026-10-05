# TASK-3806: Drive test harness (in-memory Drive + FakeDriveClient)

**Feature**: FEAT-608 — Google Drive FileManager
**Spec**: `sdd/specs/google-drive-interface.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 0. Every unit test in M2–M4, M6, M7 and M10 drives `GoogleDriveFileManager`
through a fake `DriveClient` so no test ever constructs a real `GoogleClient` (its
`__init__` needs credentials and eagerly builds an `aioredis` client, `google.py:299-302,
412-420`). This harness mirrors FEAT-603's `_graph_fakes.py` (`FakeAPIError`, `_bare`,
`make_sharepoint_client`). It fakes M1's `DriveClient` coroutine names — it does **not**
import `DriveClient` (TASK-3807 creates it in parallel).

---

## Scope

- Create `packages/ai-parrot/tests/interfaces/_gdrive_fakes.py` with `FakeHTTPError`,
  `FakeDriveFile`, `FakeDrive`, `FakeDriveClient`, `make_google_client`, `make_manager`.
- `FakeDriveClient` exposes exactly the M1 coroutine names: `open`, `close`, `files_list`,
  `files_get`, `files_create`, `files_update`, `files_copy`, `files_delete`,
  `files_download`, `permissions_create`, `send_raw`, plus `execute` (unused by the manager
  but present for parity).
- `files_list` parses the `q` grammar the manager emits (spec §2 Path model / §7 `q` grammar):
  `'<id>' in parents`, `name = '<escaped>'`, `name contains '<kw>'`, `mimeType = '<m>'`,
  `mimeType != '<m>'`, `trashed = false`, joined by ` and `; honours `order_by`
  (`"modifiedTime desc"`), `page_size` (the fake's own `page_size` caps it so tests get
  several pages) and `page_token`.
- `send_raw` scripts the resumable protocol: POST to the upload URL → response with a
  `Location` header (`https://www.googleapis.com/upload/drive/v3/files?upload_id=fake-<n>`);
  PUT chunks → 308 with `Range: bytes=0-<last>` until the final chunk → 200 + item JSON.
- `fail_next(status, retry_after=, times=, method=)` injects `FakeHTTPError`s.
- `make_google_client` builds a real `GoogleClient` via `__new__` (the `_bare` pattern) —
  `_authenticated=True`, `auth_type`, `get_drive_client` → the fake, recording `close`.
- `make_manager(fake, **kwargs)` imports `GoogleDriveFileManager` **inside the function**
  (it does not exist until TASK-3810) and applies `adopt_client(make_google_client(fake))`.
- Harness self-tests in `test_gdrive_fakes.py`.

**NOT in scope**: `DriveClient` itself (TASK-3807); any manager code (TASK-3810+);
a `conftest.py` (FEAT-603 deliberately has none — import the fakes directly).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/tests/interfaces/_gdrive_fakes.py` | CREATE | In-memory Drive + fake DriveClient + builders |
| `packages/ai-parrot/tests/interfaces/test_gdrive_fakes.py` | CREATE | Harness self-tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.interfaces.google import GoogleClient        # verified: google.py:226
# aiogoogle.excs.HTTPError shape being mimicked:          # verified: .venv/.../aiogoogle/excs.py:22-25 (__init__(msg, req=None, res=None); .res)
# aiogoogle.models.Response fields mimicked: status_code, headers, json   # verified: models.py:253, :288-304
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/interfaces/google.py
class GoogleClient(CredentialsInterface, ABC):              # :226
    self.auth_type                                          # read by using_service_account :642-644
    self._service_account_creds; self._user_creds           # :311-312
    self._authenticated                                     # :315; is_authenticated property :637-640
    def using_service_account(self) -> bool                 # :642 — auth_type == "service_account" and _service_account_creds is not None
    async def close(self) -> None                           # :1051

# packages/ai-parrot/tests/interfaces/_graph_fakes.py — pattern to copy
class FakeAPIError(Exception): ...                          # :28-35 (status + Retry-After header dict)
def _bare(cls, fake, **attrs)                               # :620-641 (cls.__new__ + __dict__.update)
```

### Does NOT Exist
- ~~`packages/ai-parrot/tests/interfaces/conftest.py`~~ — do not create one.
- ~~`parrot.interfaces.google.DriveClient`~~ — created by TASK-3807; do NOT import it here.
- ~~`parrot.interfaces.file.gdrive`~~ — created by TASK-3810; import lazily inside `make_manager` only.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/tests/interfaces/_gdrive_fakes.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/interfaces/test_gdrive_fakes.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/interfaces/google.py#GoogleClient",
    "sym:packages/ai-parrot/tests/interfaces/_graph_fakes.py#_bare"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Test modules must `sys.modules.pop("parrot.interfaces.file", None)` before importing
  anything from `parrot.interfaces.file.*` — `packages/ai-parrot/tests/conftest.py:221-229`
  installs a non-package stub (same workaround as `test_graph_filemanager.py:16-18`).
- Response dicts use Drive's camelCase keys (`id`, `name`, `mimeType`, `size` as a **string**
  — Drive returns int64 as string —, `modifiedTime` RFC 3339 `...Z`, `parents`, `trashed`,
  `webViewLink`, `webContentLink`) because the manager maps them (TASK-3810 `_make_metadata`).
- Folders have `mimeType == "application/vnd.google-apps.folder"` and no `size`.
- `FakeHTTPError.res` must carry `.status_code` and `.headers` (dict) and optionally
  `.json` (for the 403 `errors[0].reason` rate-limit classification, spec §7 Known Risks).

---

## Implementation Blueprint

### Steps (in order)
1. Write `FakeHTTPError`, `FakeDriveFile`, `FakeDrive` — *why*: the data plane every fake call reads.
2. Write the `q` parser and `FakeDriveClient` — *why*: the manager's path resolver and listings are tested through it.
3. Write the resumable `send_raw` script — *why*: TASK-3812 tests 308/Range resume against it.
4. Write `make_google_client` / `make_manager` — *why*: `adopt_client` is how every test injects the fake.
5. Write the self-tests — *why*: a broken fake silently passes broken manager code.

### `packages/ai-parrot/tests/interfaces/_gdrive_fakes.py` (CREATE)
```python
"""In-memory Google Drive + fake DriveClient for FEAT-608 tests (TASK-3806).

Import directly from test modules; there is intentionally no conftest.py.
"""
from __future__ import annotations

import datetime as dt
import itertools
import logging
import re
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any, Dict, List, Optional, Tuple

from parrot.interfaces.google import GoogleClient

FOLDER_MIME = "application/vnd.google-apps.folder"
UPLOAD_URL = "https://www.googleapis.com/upload/drive/v3/files"
_ids = itertools.count(1)


class FakeHTTPError(Exception):
    """Mimics aiogoogle.excs.HTTPError: ``res.status_code`` / ``res.headers`` / ``res.json``."""

    def __init__(self, status: int, *, retry_after: Optional[float] = None, message: str = "",
                 reason: Optional[str] = None) -> None:
        super().__init__(message or f"fake Drive error (status {status})")
        headers = {} if retry_after is None else {"Retry-After": str(retry_after)}
        body = {"error": {"errors": [{"reason": reason}]}} if reason else None
        self.res = SimpleNamespace(status_code=status, headers=headers, json=body)


@dataclass
class FakeDriveFile:
    id: str
    name: str
    mimeType: str
    parents: List[str]
    content: bytes = b""
    modifiedTime: dt.datetime = field(default_factory=lambda: dt.datetime.now(dt.timezone.utc))
    trashed: bool = False

    def as_json(self) -> Dict[str, Any]:
        """Drive v3 file resource (size as string, RFC 3339 time)."""
        # FILL IN: return the camelCase dict incl. webViewLink "https://drive.google.com/file/d/<id>/view"
        #          and webContentLink; omit "size" for folders — bounded by Implementation Notes
        raise NotImplementedError


class FakeDrive:
    """In-memory Drive keyed by id; ``root_id`` is ``"root"`` or the shared drive id."""

    def __init__(self, *, drive_id: Optional[str] = None) -> None:
        self.root_id = drive_id or "root"
        self.by_id: Dict[str, FakeDriveFile] = {}
        self.calls: List[Tuple[str, str, Dict[str, Any]]] = []

    def put_folder(self, path: str) -> FakeDriveFile: ...          # FILL IN: mkdir -p semantics, returns leaf
    def put_file(self, path: str, data: bytes, *, mime: str = "application/octet-stream",
                 modified: Optional[dt.datetime] = None) -> FakeDriveFile: ...   # FILL IN: parents auto-created
    def duplicate(self, path: str, data: bytes, *, modified: dt.datetime) -> FakeDriveFile:
        """Add a same-name sibling (duplicate-name tests)."""
        # FILL IN
        raise NotImplementedError
```
**Why this shape**: names and signatures are fixed by spec §3 M0; tests in TASK-3810..3817 call them.

### `_gdrive_fakes.py` — FakeDriveClient + builders (same file, continued)
```python
_Q_TERM = re.compile(r"'(?P<pid>[^']+)' in parents|name (?P<op>=|contains) '(?P<name>(?:\\.|[^'])*)'"
                     r"|mimeType (?P<mop>=|!=) '(?P<mime>[^']+)'|trashed = (?P<trashed>true|false)")


class FakeDriveClient:
    """Stand-in for parrot.interfaces.google.DriveClient (same coroutine names) over FakeDrive."""

    def __init__(self, drive: FakeDrive, *, page_size: int = 2, service_account: bool = True) -> None:
        self.drive = drive
        self.page_size = page_size
        self.service_account = service_account
        self.opened = 0
        self.closed = 0
        self.requests: List[Any] = []        # every send_raw request, in order
        self._failures: List[Tuple[int, Optional[float], Optional[str], Optional[str]]] = []
        self._sessions: Dict[str, Dict[str, Any]] = {}

    def fail_next(self, status: int, *, retry_after: Optional[float] = None, times: int = 1,
                  method: Optional[str] = None, reason: Optional[str] = None) -> None:
        self._failures.extend([(status, retry_after, method, reason)] * times)

    def _maybe_fail(self, method: str) -> None:
        # FILL IN: pop the first failure whose method is None or == method and raise FakeHTTPError
        return None

    async def open(self) -> "FakeDriveClient": ...
    async def close(self) -> None: ...
    async def files_list(self, *, q: str, fields: str, page_size: int = 1000, page_token: Optional[str] = None,
                         order_by: Optional[str] = None, drive_id: Optional[str] = None, **params: Any) -> Dict[str, Any]:
        # FILL IN: record ("files", "list", {...all params...}); filter by _Q_TERM terms (unescape \\ and \');
        #          order "modifiedTime desc" then id asc; page with min(page_size, self.page_size); nextPageToken=str offset
        raise NotImplementedError
    async def files_get(self, file_id: str, *, fields: str, **params: Any) -> Dict[str, Any]: ...      # FILL IN: 404 FakeHTTPError if missing
    async def files_create(self, metadata: Dict[str, Any], *, fields: str, upload_file: Optional[str] = None,
                           pipe_from: Any = None, content_type: Optional[str] = None, **params: Any) -> Dict[str, Any]: ...
    async def files_update(self, file_id: str, metadata: Optional[Dict[str, Any]] = None, *, fields: str,
                           add_parents: Optional[str] = None, remove_parents: Optional[str] = None,
                           upload_file: Optional[str] = None, pipe_from: Any = None,
                           content_type: Optional[str] = None, **params: Any) -> Dict[str, Any]: ...
    async def files_copy(self, file_id: str, metadata: Dict[str, Any], *, fields: str, **params: Any) -> Dict[str, Any]: ...
    async def files_delete(self, file_id: str, **params: Any) -> None: ...
    async def files_download(self, file_id: str, *, download_file: Optional[str] = None, pipe_to: Any = None,
                             **params: Any) -> None: ...   # FILL IN: pipe_to → `await pipe_to.write(chunk)` in 3 chunks
    async def permissions_create(self, file_id: str, body: Dict[str, Any], *, send_notification_email: bool = False,
                                 **params: Any) -> Dict[str, Any]: ...
    async def execute(self, request: Any, *, full_res: bool = False, raise_for_status: bool = True) -> Any: ...
    async def send_raw(self, request: Any, *, full_res: bool = True, raise_for_status: bool = True) -> Any:
        # FILL IN: POST/PATCH to UPLOAD_URL → SimpleNamespace(status_code=200, headers={"Location": ...}, json=None);
        #          PUT to a session URL: parse Content-Range "bytes a-b/total", append data, 308 + Range until b+1 == total,
        #          then 200 with the created/updated item json — bounded by spec §7 Uploads bullet
        raise NotImplementedError


def make_google_client(fake: FakeDriveClient, *, auth_type: str = "service_account") -> GoogleClient:
    """A real GoogleClient built without ``__init__`` (``_bare`` pattern, _graph_fakes.py:620)."""
    client = GoogleClient.__new__(GoogleClient)
    closes: List[int] = []

    async def _get_drive_client(version: str = "v3") -> FakeDriveClient:
        return fake

    async def _close() -> None:
        closes.append(1)

    client.__dict__.update(dict(
        auth_type=auth_type, _authenticated=True, _service_account_creds=object() if auth_type == "service_account" else None,
        _user_creds=None if auth_type == "service_account" else object(), redis=None,
        logger=logging.getLogger("fake.google"), get_drive_client=_get_drive_client, close=_close, closes=closes,
    ))
    return client


def make_manager(fake: FakeDriveClient, **kwargs: Any) -> Any:
    """GoogleDriveFileManager(**kwargs) with ``adopt_client(make_google_client(fake))`` applied."""
    from parrot.interfaces.file.gdrive import GoogleDriveFileManager   # lazy: created by TASK-3810

    manager = GoogleDriveFileManager(**kwargs)
    manager.adopt_client(make_google_client(fake, auth_type="service_account" if fake.service_account else "user"))
    return manager
```
**Why**: the coroutine names and keyword arguments equal the M1 skeleton (spec §3 M1) so the
manager code under test cannot tell the fake from the real `DriveClient`. `**params` absorbs the
`supportsAllDrives` / `includeItemsFromAllDrives` / `corpora` flags, which the fake records in
`drive.calls` so TASK-3811's `test_list_params_shared_drive_flags` can assert them.

### `packages/ai-parrot/tests/interfaces/test_gdrive_fakes.py` (CREATE)
```python
"""FEAT-608 TASK-3806 — harness self-tests."""
import datetime as dt

import pytest

from ._gdrive_fakes import FakeDrive, FakeDriveClient, FakeHTTPError, make_google_client


async def test_fake_drive_paths_and_duplicates():
    # FILL IN: put_file creates parents; duplicate adds a same-name sibling; files_list with
    #          name = '<n>' + order_by modifiedTime desc returns newest first
    ...


async def test_fake_client_pagination_and_fail_next():
    # FILL IN: 5 children with page_size=2 → 3 pages via nextPageToken; fail_next(503) raises once
    #          with res.status_code == 503 then succeeds
    ...


async def test_fake_resumable_session_308_then_200():
    # FILL IN: POST → Location; two PUTs → first 308 with Range, last 200 with item json
    ...


def test_make_google_client_is_authenticated_without_init():
    # FILL IN: is_authenticated True; using_service_account() True for default auth_type
    ...
```

### FILL IN checklist
- [ ] `FakeDriveFile.as_json` — camelCase resource; size string; folders without size.
- [ ] `FakeDrive.put_folder/put_file/duplicate` — path walk + parent creation.
- [ ] `FakeDriveClient.files_list` — q parsing, ordering, pagination, call recording.
- [ ] `FakeDriveClient` CRUD/permissions/download — 404 on unknown id; trashed flag via update.
- [ ] `FakeDriveClient.send_raw` — resumable POST/PATCH + PUT 308/200 script.
- [ ] Four self-tests.

---

## Acceptance Criteria

- [ ] All six public names exist with the spec §3 M0 signatures.
- [ ] `FakeDriveClient` coroutine names/kwargs match spec §3 M1 exactly.
- [ ] Importing `_gdrive_fakes` does not import `parrot.interfaces.file.gdrive`.
- [ ] Self-tests pass.

## Validation Commands
- `pytest packages/ai-parrot/tests/interfaces/test_gdrive_fakes.py -q`

---

## Test Specification
See the `test_gdrive_fakes.py` block above.

---

## Agent Instructions
Standard: read the spec §3 M0, verify the contract, implement from the blueprint, run the
validation command with `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-tools/src` inside the worktree.

---

## Completion Note

*(Agent fills this in when done)*
