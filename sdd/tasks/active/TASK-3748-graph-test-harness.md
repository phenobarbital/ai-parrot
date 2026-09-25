# TASK-3748: Graph test harness — in-memory msgraph builder tree, aiohttp fake, fake drive clients

**Feature**: FEAT-603 — SharePoint & OneDrive FileManager
**Spec**: `sdd/specs/sharepoint-filemanager.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 **Module 0**. Every FEAT-603 unit test (TASK-3749..3764, 3768) exercises the Graph file managers
against an in-memory fake instead of a tenant. This task builds that fake once: a drive model, the subset of the
`msgraph` request-builder tree the managers call, an `aiohttp.ClientSession` stand-in for the three pre-authenticated
URLs (upload session, copy monitor, download), and factories that return *real* `SharepointClient` / `OneDriveClient`
instances created **without** running their `__init__` (which would build an aioredis client, `o365.py:198-200`).

**Task-time decision (deviation from spec §6 Edit Sites):** the spec lists a new
`packages/ai-parrot/tests/interfaces/conftest.py`. It is NOT created — fixtures live as plain factory functions in
`_graph_fakes.py` and each test module imports them. Reason: a new `conftest.py` in `tests/interfaces/` would be loaded
by every other test there (including `test_file_shim.py`, edited by TASK-3758), which makes this task *exclusive* under
the task-graph rules; plain imports keep it parallel-safe with no behavioural difference.

---

## Scope

- Create `packages/ai-parrot/tests/interfaces/_graph_fakes.py` with: `FakeAPIError`, `FakeDriveItem`, `FakeDrive`,
  `FakeGraphClient` (+ its builder classes), `FakeResponse`, `FakeAiohttpSession`, `make_sharepoint_client`,
  `make_onedrive_client`, `make_probe`.
- Create `packages/ai-parrot/tests/interfaces/test_graph_fakes.py` — self-tests proving the fake behaves the way the
  later tasks rely on (pagination, failure injection, copy 202 + monitor, upload session assembly, download stream).

**NOT in scope**: any production code; any `conftest.py`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/tests/interfaces/_graph_fakes.py` | CREATE | fakes + factories shared by all FEAT-603 tests |
| `packages/ai-parrot/tests/interfaces/test_graph_fakes.py` | CREATE | self-tests of the harness |

---

## Codebase Contract (Anti-Hallucination)

> Re-verified 2026-09-25 against `dev` at `8da1f45c3` (venv python3.12, msgraph-sdk 1.63.0).

### Verified Imports
```python
from parrot.interfaces.sharepoint import SharepointClient   # verified: packages/ai-parrot/src/parrot/interfaces/sharepoint.py:32
from parrot.interfaces.onedrive import OneDriveClient       # verified: packages/ai-parrot/src/parrot/interfaces/onedrive.py:25
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/interfaces/o365.py
class O365Client(CredentialsInterface):                     # :115
    # __init__ (:167) sets url/tenant_id/tenant/site/auth_mode, _credential, _graph_client, _access_token,
    #   logger, _executor = ThreadPoolExecutor() (:184), redis = aioredis.from_url(...) (:198-200)  -> NEVER run it in tests
    @property
    def graph_client(self) -> GraphServiceClient:           # :339 — returns self._graph_client when set (lazy create otherwise)
    def set_auth_mode(self, auth_mode) -> None              # :360
    @property
    def is_app_only(self) -> bool                           # :364-370 — PROPERTY (spec §6 calls it a method; it is not):
        # (self.auth_mode or "") == "direct" and not (credentials.get("username") or credentials.get("assertion"))
    async def close(self)                                   # :709 — self._executor.shutdown(...) if self._executor; clears auth state
# packages/ai-parrot/src/parrot/interfaces/sharepoint.py — SharepointClient(O365Client) :32; attrs set in __init__ :40-63
#   (_srcfiles list :52, _site_id/_drive_id/_site_info/_drive_info :60-63); verify_sharepoint_access() :96; _resolve_drive(library_name=None) :242
# packages/ai-parrot/src/parrot/interfaces/onedrive.py — OneDriveClient(O365Client) :25; _drive_id :61, _drive_info :62; _resolve_drive() :88

# msgraph-sdk 1.63 shapes the fake must mimic (names only; the fake does not import msgraph builders):
#   drives.by_drive_id(id) -> .items.by_drive_item_id(ref) -> .get() / .delete() / .patch(DriveItem) / .children / .content
#       / .create_link.post(body) / .copy.post(body, request_configuration=...) / .create_upload_session.post(body)
#   drives.by_drive_id(id).root.get() ; drives.by_drive_id(id).search_with_q(q).get() / .with_url(raw_url)
#   .children.get() / .children.with_url(raw_url) / .children.post(DriveItem) ; .content.put(bytes) / .content.get()
#   collection responses: .value (list) + .odata_next_link (str | None)   (base_collection_pagination_count_response.py:18)
#   me.drive.get() ; users.by_user_id(u).drive.get()
#   kiota APIError: .response_status_code (int), .response_headers (dict)   (kiota_abstractions/api_error.py:10-11)
#   copy with ResponseHandlerOption(NativeResponseHandler()) in request_configuration.options -> native response
#       with .status_code and .headers["Location"]  (kiota_http/middleware/options/response_handler_option.py:7)
```

### Does NOT Exist
- ~~`packages/ai-parrot/tests/interfaces/conftest.py`~~ — does not exist and is deliberately NOT created (see Context).
- ~~`msgraph.testing` / an official Graph mock~~ — there is none; this harness is the fake.
- ~~`parrot.interfaces.file.graph`~~ — created by TASK-3749; the harness must NOT import it (it is written first).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/tests/interfaces/_graph_fakes.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/interfaces/test_graph_fakes.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/interfaces/sharepoint.py#SharepointClient",
    "sym:packages/ai-parrot/src/parrot/interfaces/onedrive.py#OneDriveClient",
    "sym:packages/ai-parrot/src/parrot/interfaces/o365.py#O365Client"
  ]
}
```

---

## Implementation Notes

- **Real client classes, no `__init__`**: `c = SharepointClient.__new__(SharepointClient)` then set attributes. Set
  `c._graph_client = fake` — `graph_client` is a *property* (data descriptor) that returns `_graph_client` when it is
  set. Plain methods (`verify_sharepoint_access`, `_resolve_drive`) are shadowed by assigning instance attributes.
  `is_app_only` is a **property** (`o365.py:364-370`) and CANNOT be shadowed — control it through `auth_mode` /
  `credentials` instead (`app_only=False` sets `auth_mode="delegated"`). `c._executor = None` so the real `close()` works. This keeps `isinstance(c, SharepointClient)` true, which
  `adopt_client` (TASK-3750) relies on.
- **Item references** the fake must resolve (the managers use exactly these forms): `"root"`; `"root:/<quoted/segs>:"`
  (`urllib.parse.unquote` each segment); `"<parent_id>:/<quoted name>:"` (upload target); a bare item id.
- **Pagination**: `FakeGraphClient(page_size=N)` slices children/search results; `odata_next_link` is
  `https://graph.microsoft.com/v1.0/_fake/next/<cursor>` and `with_url()` resumes from `<cursor>`.
- **Failure injection**: `fail_next(status, retry_after=None, times=1, op=None)` makes the next `times` builder calls
  (optionally only for `op` in `{"get","children","content_put","create_link","copy","create_upload_session","patch",
  "delete","search"}`) raise `FakeAPIError`. `FakeAiohttpSession.script(url_kind, status, times, headers)` does the same
  for the raw HTTP side (`url_kind` in `{"upload","monitor","download"}`).
- Every builder call appends `(op, drive_id, ref, extra)` to `fake.calls`; every aiohttp call appends
  `(method, url, headers, allow_redirects)` to `session.requests` — later tests assert on both.

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
1. Write the data layer (`FakeAPIError`, `FakeDriveItem`, `FakeDrive`) — *why*: builders and the aiohttp fake both
   read and write the same in-memory drive.
2. Write `FakeGraphClient` and its builders — *why*: they mirror the SDK chain the managers call; names must match
   the SDK exactly or the production code will not work against the real SDK either.
3. Write `FakeResponse` + `FakeAiohttpSession` — *why*: upload chunks, copy monitor polling and downloads bypass the SDK.
4. Write the client factories and `make_probe` — *why*: TASK-3749..3753 test a still-abstract base class.
5. Write the self-tests.

### `packages/ai-parrot/tests/interfaces/_graph_fakes.py` (CREATE) — part 1: data layer
```python
"""In-memory fakes of the msgraph request-builder tree and aiohttp (FEAT-603 TASK-3748).

Import these directly from test modules; there is intentionally no conftest.py.
"""
from __future__ import annotations

import datetime as dt
import itertools
import json
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import unquote

from parrot.interfaces.onedrive import OneDriveClient
from parrot.interfaces.sharepoint import SharepointClient

FAKE_NEXT = "https://graph.microsoft.com/v1.0/_fake/next/"
FAKE_UPLOAD = "https://contoso.sharepoint.com/_fake/upload/"
FAKE_MONITOR = "https://contoso.sharepoint.com/_fake/monitor/"
FAKE_DOWNLOAD = "https://contoso.sharepoint.com/_fake/download/"
_ids = itertools.count(1)


class FakeAPIError(Exception):
    """Mimics kiota ``APIError``: ``response_status_code`` + ``response_headers``."""

    def __init__(self, status: int, *, retry_after: Optional[float] = None, message: str = "") -> None:
        super().__init__(message or f"fake Graph error (status {status})")
        self.response_status_code = status
        self.response_headers: Dict[str, str] = {} if retry_after is None else {"Retry-After": str(retry_after)}


@dataclass
class FakeDriveItem:
    """Minimal DriveItem stand-in with the attributes the managers read."""

    id: str
    name: str
    size: int = 0
    web_url: Optional[str] = None
    folder: Optional[Any] = None                      # SimpleNamespace(child_count=n) for folders
    file: Optional[Any] = None                        # SimpleNamespace(mime_type="...") for files
    last_modified_date_time: Optional[dt.datetime] = None
    parent_reference: Optional[Any] = None            # SimpleNamespace(id=..., drive_id=..., path="/drive/root:/a")
    additional_data: Dict[str, Any] = field(default_factory=dict)
    data: bytes = b""


class FakeDrive:
    """In-memory drive keyed by drive-relative path (no leading slash; root is "")."""

    def __init__(self, drive_id: str = "drive-1") -> None:
        self.drive_id = drive_id
        self.root = FakeDriveItem(id=f"{drive_id}-root", name="root", folder=SimpleNamespace(child_count=0))
        self.by_id: Dict[str, FakeDriveItem] = {self.root.id: self.root}
        self.path_of: Dict[str, str] = {self.root.id: ""}

    def put_folder(self, path: str) -> FakeDriveItem:
        """Create every missing folder of ``path`` and return the last one."""
        # FILL IN: walk segments; create FakeDriveItem(folder=SimpleNamespace(child_count=0)) with parent_reference
        #          (path "/drive/root:" or "/drive/root:/<parent>") for each missing one; register by_id / path_of

    def put_file(self, path: str, data: bytes, *, mime: str = "application/octet-stream") -> FakeDriveItem:
        """Create or replace a file; sets web_url and additional_data['@microsoft.graph.downloadUrl']."""
        # FILL IN: put_folder(parent); replace an existing same-path item's data (keep its id) or create one;
        #          web_url=f"https://contoso.sharepoint.com/{path}"; downloadUrl=FAKE_DOWNLOAD + item.id; size=len(data)

    def lookup(self, path: str) -> Optional[FakeDriveItem]: ...          # FILL IN: exact-path lookup
    def children(self, item_id: str) -> List[FakeDriveItem]: ...        # FILL IN: direct children, sorted by name
    def remove(self, item_id: str) -> None: ...                         # FILL IN: remove item and its subtree
```

### `packages/ai-parrot/tests/interfaces/_graph_fakes.py` (CREATE) — part 2: builder tree
```python
class FakeGraphClient:
    """Builder tree over FakeDrive objects: ``drives``, ``me``, ``users``. Records every call in ``calls``."""

    def __init__(self, drives: Dict[str, FakeDrive], *, me_drive_id: Optional[str] = None,
                 user_drives: Optional[Dict[str, str]] = None, page_size: int = 1000,
                 copy_polls_before_done: int = 1) -> None:
        self.drives_by_id = drives
        self.me_drive_id = me_drive_id
        self.user_drives = {k.lower(): v for k, v in (user_drives or {}).items()}
        self.page_size = page_size
        self.copy_polls_before_done = copy_polls_before_done
        self.calls: List[Tuple[str, str, str, Any]] = []
        self.sessions: Dict[str, Dict[str, Any]] = {}     # upload sessions by id: parent_id, name, conflict, buffer
        self.monitors: Dict[str, Dict[str, Any]] = {}     # copy jobs by id: polls_left, resource_id
        self.link_bodies: List[Any] = []
        self._failures: List[Tuple[Optional[str], int, Optional[float]]] = []
        self.drives = SimpleNamespace(by_id=self.drives_by_id, by_drive_id=lambda did: _DriveBuilder(self, did))
        self.me = SimpleNamespace(drive=SimpleNamespace(get=self._me_drive))
        self.users = SimpleNamespace(by_user_id=lambda u: SimpleNamespace(drive=SimpleNamespace(
            get=lambda: self._user_drive(u))))

    def fail_next(self, status: int, *, retry_after: Optional[float] = None, times: int = 1,
                  op: Optional[str] = None) -> None:
        """Make the next ``times`` matching builder calls raise ``FakeAPIError(status)``."""
        self._failures.extend([(op, status, retry_after)] * times)

    def _check_fail(self, op: str) -> None:
        # FILL IN: pop the first failure whose op is None or == op and raise FakeAPIError(status, retry_after=...)

    async def _me_drive(self) -> Any: ...         # FILL IN: SimpleNamespace(id=me_drive_id, name="OneDrive") or FakeAPIError(404)
    async def _user_drive(self, user: str) -> Any: ...   # FILL IN: lookup user_drives[user.lower()] else FakeAPIError(404)


# FILL IN: _DriveBuilder(fake, drive_id) with .items (SimpleNamespace(by_drive_item_id=...)), .root (get()),
#          .search_with_q(q) -> _PagedBuilder over name-substring matches (case-insensitive);
#          _ItemBuilder(fake, drive_id, ref) resolving the four ref forms in Implementation Notes, with async get/delete/
#          patch(body) (rename via body.name, move via body.parent_reference.id), .children (_PagedBuilder + post(DriveItem)),
#          .content (put(bytes, request_configuration=None) creates/replaces and returns the item; get() -> bytes),
#          .create_link.post(body) -> SimpleNamespace(link=SimpleNamespace(web_url=...)) recording body in link_bodies,
#          .copy.post(body, request_configuration=None) -> when request_configuration.options holds a handler option,
#              SimpleNamespace(status_code=202, headers={"Location": FAKE_MONITOR + job_id}); registers the job,
#          .create_upload_session.post(body) -> SimpleNamespace(upload_url=FAKE_UPLOAD + sid) recording
#              body.item.additional_data["@microsoft.graph.conflictBehavior"];
#          _PagedBuilder.get()/with_url(raw) returning SimpleNamespace(value=[...page...], odata_next_link=... | None).
#          Every call: fake._check_fail(op) first, then fake.calls.append((op, drive_id, ref, extra)).
#          Missing refs raise FakeAPIError(404). A "fail" conflict on an existing target raises FakeAPIError(409).
```

### `packages/ai-parrot/tests/interfaces/_graph_fakes.py` (CREATE) — part 3: aiohttp fake + factories
```python
class FakeResponse:
    """Async-context-manager response: status, headers, json(), text(), content.iter_chunked(n)."""

    def __init__(self, status: int, *, body: bytes = b"", headers: Optional[Dict[str, str]] = None) -> None:
        self.status = status
        self.headers = headers or {}
        self._body = body
        self.content = SimpleNamespace(iter_chunked=self._iter_chunked)

    async def __aenter__(self) -> "FakeResponse":
        return self

    async def __aexit__(self, *exc: Any) -> None:
        return None

    async def json(self) -> Any:
        return json.loads(self._body or b"null")

    async def text(self) -> str:
        return self._body.decode("utf-8", "replace")

    async def _iter_chunked(self, n: int):
        for i in range(0, len(self._body), n):
            yield self._body[i:i + n]


class FakeAiohttpSession:
    """Stands in for aiohttp.ClientSession for FAKE_UPLOAD / FAKE_MONITOR / FAKE_DOWNLOAD URLs."""

    def __init__(self, fake: FakeGraphClient) -> None:
        self.fake = fake
        self.requests: List[Tuple[str, str, Dict[str, str], Optional[bool]]] = []
        self.closed = False
        self._scripts: List[Tuple[str, int, Dict[str, str]]] = []

    def script(self, url_kind: str, status: int, *, times: int = 1, headers: Optional[Dict[str, str]] = None) -> None:
        self._scripts.extend([(url_kind, status, headers or {})] * times)

    async def __aenter__(self) -> "FakeAiohttpSession":
        return self

    async def __aexit__(self, *exc: Any) -> None:
        self.closed = True

    async def close(self) -> None:
        self.closed = True

    def put(self, url: str, *, data: bytes = b"", headers: Optional[Dict[str, str]] = None,
            allow_redirects: Optional[bool] = None, **_: Any) -> FakeResponse:
        # FILL IN: record; honour a scripted "upload" status; parse "Content-Range: bytes a-b/total"; append to the
        #          session buffer; 202 + JSON {"nextExpectedRanges": [...]} until complete, then write the file into the
        #          FakeDrive (respecting the recorded conflict behaviour) and return 201 + the item's JSON
        #          ({"id","name","size","webUrl"})

    def get(self, url: str, *, headers: Optional[Dict[str, str]] = None, allow_redirects: Optional[bool] = None,
            **_: Any) -> FakeResponse:
        # FILL IN: record; FAKE_MONITOR -> 202 {"status": "inProgress"} while polls_left > 0, then 200
        #          {"status": "completed", "resourceId": new_id} (performing the copy in the FakeDrive on completion);
        #          FAKE_DOWNLOAD -> 200 with the item's bytes; honour scripted statuses; unknown URL -> 404


def _bare(cls: type, fake: FakeGraphClient, **attrs: Any) -> Any:
    """Instantiate ``cls`` WITHOUT __init__ (no aioredis client) and set the attributes the managers read."""
    client = cls.__new__(cls)
    client.__dict__.update(dict(credentials={}, tenant="contoso", tenant_id="t-1", site=None, auth_mode="direct",
                                _credential=object(), _graph_client=fake, _access_token=None, _executor=None,
                                _drive_id=None, _drive_info=None, logger=__import__("logging").getLogger("fake")))
    client.__dict__.update(attrs)
    return client


def make_sharepoint_client(fake: FakeGraphClient, *, drive_id: str, app_only: bool = True) -> SharepointClient:
    """A real SharepointClient instance (no __init__) whose drive resolution returns ``drive_id``."""
    async def _verify() -> None:
        return None

    async def _resolve_drive(library_name: Optional[str] = None) -> Any:
        return SimpleNamespace(id=drive_id, name=library_name or "Documents")

    return _bare(SharepointClient, fake, _srcfiles=[], _destination=[], _site_id=None, _site_info=None,
                 verify_sharepoint_access=_verify, _resolve_drive=_resolve_drive,
                 auth_mode="direct" if app_only else "delegated")


def make_onedrive_client(fake: FakeGraphClient, *, app_only: bool = True) -> OneDriveClient:
    """A real OneDriveClient instance (no __init__); its real ``_resolve_user_drive`` (TASK-3755) hits ``fake``."""
    return _bare(OneDriveClient, fake, _user_drives={}, auth_mode="direct" if app_only else "delegated")


def make_probe(base_cls: type, *, drive_id: str = "drive-1", **kwargs: Any) -> Any:
    """Concrete test subclass of a (possibly still partially abstract) GraphDriveFileManager.

    Implements the two hooks and stubs every remaining abstract method with an AssertionError, so the base class can
    be tested before all of its methods exist (TASK-3749..3753).
    """
    # FILL IN: build type("Probe", (base_cls,), ns) where ns has `_build_client` (raises AssertionError("adopt a fake
    #          client in tests")), `async _resolve_drive_id` (returns drive_id) and an async stub for each name in
    #          base_cls.__abstractmethods__ minus those two; return Probe(**kwargs)
```
**Why this shape**: the three parts together are the whole file (each block under the 80-line cap). Names, URL
prefixes and `fail_next` / `script` semantics are fixed here because eleven later tasks assert against them; the
bodies are mechanical bookkeeping over the in-memory `FakeDrive`.

### `packages/ai-parrot/tests/interfaces/test_graph_fakes.py` (CREATE)
```python
"""FEAT-603 TASK-3748 — the Graph test harness behaves as the manager tests assume."""
from types import SimpleNamespace

import pytest

from ._graph_fakes import (
    FAKE_DOWNLOAD, FakeAiohttpSession, FakeAPIError, FakeDrive, FakeGraphClient, make_onedrive_client,
    make_probe, make_sharepoint_client,
)
from parrot.interfaces.onedrive import OneDriveClient
from parrot.interfaces.sharepoint import SharepointClient


@pytest.fixture
def fake() -> FakeGraphClient:
    drive = FakeDrive("drive-1")
    drive.put_file("reports/2026/q3.xlsx", b"x" * 10, mime="application/vnd.ms-excel")
    return FakeGraphClient({"drive-1": drive}, me_drive_id="drive-1", user_drives={"u@t.com": "drive-1"})


async def test_path_ref_resolves_and_missing_raises_404(fake):
    # FILL IN: by_drive_item_id("root:/reports/2026/q3.xlsx:").get() returns the item; unknown path -> FakeAPIError 404


async def test_children_paginate_with_next_link(fake):
    # FILL IN: put 5 files in one folder, page_size=2 -> three pages via odata_next_link + with_url, all 5 seen once


async def test_fail_next_raises_then_recovers(fake):
    # FILL IN: fail_next(429, retry_after=1.5, op="get") -> first get raises with response_headers["Retry-After"]; second ok


async def test_copy_returns_202_location_and_monitor_completes(fake):
    # FILL IN: copy.post(body, request_configuration=SimpleNamespace(options=[SimpleNamespace(response_handler=object())]))
    #          -> status_code 202 + Location; FakeAiohttpSession.get(Location) -> inProgress then completed + resourceId


async def test_upload_session_assembles_chunks(fake):
    # FILL IN: create_upload_session.post -> upload_url; two PUTs with Content-Range -> 202 then 201; file content in drive


async def test_download_url_streams_bytes(fake):
    # FILL IN: GET FAKE_DOWNLOAD + item.id -> 200; iter_chunked(4) reassembles the 10 bytes


def test_factories_return_real_client_classes_without_init(fake):
    sp = make_sharepoint_client(fake, drive_id="drive-1")
    od = make_onedrive_client(fake)
    assert isinstance(sp, SharepointClient) and isinstance(od, OneDriveClient)
    assert sp.graph_client is fake and sp._srcfiles == []
    assert not hasattr(sp, "redis")
    assert sp.is_app_only is True and make_onedrive_client(fake, app_only=False).is_app_only is False


def test_make_probe_stubs_remaining_abstract_methods():
    # FILL IN: an ABC with two abstract async methods + _build_client/_resolve_drive_id -> make_probe instantiates it
```

### FILL IN checklist
- [ ] `FakeDrive` bodies (folders, replace-in-place keeping the id, subtree removal)
- [ ] builder classes and the four ref forms; `_check_fail`; 404 / 409 behaviour
- [ ] `FakeAiohttpSession.put` / `.get` (chunk assembly, monitor progression, download, scripted statuses)
- [ ] `make_probe`
- [ ] every self-test body

---

## Acceptance Criteria

- [ ] `_graph_fakes.py` exposes exactly the names imported by `test_graph_fakes.py` above, with the URL prefixes and
      `fail_next` / `script` semantics described in Implementation Notes.
- [ ] `make_sharepoint_client` / `make_onedrive_client` return real client-class instances without running `__init__`
      (no `redis` attribute, `_executor is None`).
- [ ] Pagination, failure injection, copy 202 + monitor, upload-session assembly and download streaming are covered
      by passing self-tests.
- [ ] No `conftest.py` created; `ruff check` clean on both files.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/interfaces/test_graph_fakes.py -q`

---

## Test Specification

| Test | Asserts |
|---|---|
| `test_path_ref_resolves_and_missing_raises_404` | colon-path refs + 404 |
| `test_children_paginate_with_next_link` | `odata_next_link` + `with_url` |
| `test_fail_next_raises_then_recovers` | failure injection incl. `Retry-After` header |
| `test_copy_returns_202_location_and_monitor_completes` | native-handler copy contract |
| `test_upload_session_assembles_chunks` | Content-Range handling |
| `test_download_url_streams_bytes` | chunked download |
| `test_factories_return_real_client_classes_without_init` | no aioredis, isinstance preserved |
| `test_make_probe_stubs_remaining_abstract_methods` | probe helper |

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
