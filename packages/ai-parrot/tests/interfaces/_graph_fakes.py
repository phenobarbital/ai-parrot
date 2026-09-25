"""In-memory fakes of the msgraph request-builder tree and aiohttp (FEAT-603 TASK-3748).

Import these directly from test modules; there is intentionally no conftest.py.
"""

from __future__ import annotations

import datetime as dt
import itertools
import json
import logging
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
    """Mimic kiota ``APIError`` response status and headers."""

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
    folder: Optional[Any] = None
    file: Optional[Any] = None
    last_modified_date_time: Optional[dt.datetime] = None
    parent_reference: Optional[Any] = None
    additional_data: Dict[str, Any] = field(default_factory=dict)
    data: bytes = b""


class FakeDrive:
    """In-memory drive keyed by drive-relative path (no leading slash)."""

    def __init__(self, drive_id: str = "drive-1") -> None:
        self.drive_id = drive_id
        self.root = FakeDriveItem(id=f"{drive_id}-root", name="root", folder=SimpleNamespace(child_count=0))
        self.by_id: Dict[str, FakeDriveItem] = {self.root.id: self.root}
        self.path_of: Dict[str, str] = {self.root.id: ""}

    def _parent_reference(self, parent: FakeDriveItem) -> SimpleNamespace:
        """Build the parent reference used by Graph item responses."""
        parent_path = self.path_of[parent.id]
        suffix = "" if not parent_path else f":/{parent_path}"
        return SimpleNamespace(id=parent.id, drive_id=self.drive_id, path=f"/drive/root:{suffix}")

    def _refresh_child_count(self, item: FakeDriveItem) -> None:
        """Refresh the Graph folder child-count field."""
        if item.folder is not None:
            item.folder.child_count = len(self.children(item.id))

    def put_folder(self, path: str) -> FakeDriveItem:
        """Create every missing folder of ``path`` and return the last one."""
        current = self.root
        clean = path.strip("/")
        if not clean:
            return current
        accumulated: List[str] = []
        for segment in clean.split("/"):
            accumulated.append(segment)
            current_path = "/".join(accumulated)
            existing = self.lookup(current_path)
            if existing is None:
                existing = FakeDriveItem(
                    id=f"item-{next(_ids)}",
                    name=segment,
                    folder=SimpleNamespace(child_count=0),
                    parent_reference=self._parent_reference(current),
                )
                self.by_id[existing.id] = existing
                self.path_of[existing.id] = current_path
                self._refresh_child_count(current)
            current = existing
        return current

    def put_file(self, path: str, data: bytes, *, mime: str = "application/octet-stream") -> FakeDriveItem:
        """Create or replace a file, retaining an existing item's id."""
        clean = path.strip("/")
        parent_path, _, name = clean.rpartition("/")
        parent = self.put_folder(parent_path)
        item = self.lookup(clean)
        if item is None:
            item = FakeDriveItem(
                id=f"item-{next(_ids)}",
                name=name,
                parent_reference=self._parent_reference(parent),
            )
            self.by_id[item.id] = item
            self.path_of[item.id] = clean
            self._refresh_child_count(parent)
        item.folder = None
        item.file = SimpleNamespace(mime_type=mime)
        item.data = data
        item.size = len(data)
        item.web_url = f"https://contoso.sharepoint.com/{clean}"
        item.last_modified_date_time = dt.datetime.now(dt.timezone.utc)
        item.additional_data["@microsoft.graph.downloadUrl"] = FAKE_DOWNLOAD + item.id
        return item

    def lookup(self, path: str) -> Optional[FakeDriveItem]:
        """Return an item by exact drive-relative path."""
        clean = path.strip("/")
        return next((item for item_id, item in self.by_id.items() if self.path_of[item_id] == clean), None)

    def children(self, item_id: str) -> List[FakeDriveItem]:
        """Return direct children sorted by name."""
        parent_path = self.path_of.get(item_id)
        if parent_path is None:
            return []
        prefix = f"{parent_path}/" if parent_path else ""
        parent_segments = parent_path.count("/") + 1 if parent_path else 0
        depth = parent_segments + 1
        return sorted(
            [
                item
                for child_id, item in self.by_id.items()
                if child_id != item_id
                and self.path_of[child_id].startswith(prefix)
                and self.path_of[child_id].count("/") + 1 == depth
            ],
            key=lambda item: item.name,
        )

    def remove(self, item_id: str) -> None:
        """Remove an item and its subtree."""
        if item_id == self.root.id or item_id not in self.by_id:
            return
        path = self.path_of[item_id]
        parent = self.by_id.get(self.by_id[item_id].parent_reference.id)
        doomed = [key for key, value in self.path_of.items() if value == path or value.startswith(f"{path}/")]
        for key in doomed:
            self.by_id.pop(key, None)
            self.path_of.pop(key, None)
        if parent is not None:
            self._refresh_child_count(parent)

    def move(self, item: FakeDriveItem, parent_id: str, name: Optional[str] = None) -> None:
        """Move or rename an item and update the paths of its descendants."""
        parent = self.by_id.get(parent_id)
        if parent is None:
            raise FakeAPIError(404)
        old_path = self.path_of[item.id]
        old_parent = self.by_id.get(item.parent_reference.id) if item.parent_reference else None
        item.name = name or item.name
        new_path = "/".join(value for value in (self.path_of[parent.id], item.name) if value)
        updates = {
            key: value.replace(old_path, new_path, 1)
            for key, value in self.path_of.items()
            if value == old_path or value.startswith(f"{old_path}/")
        }
        self.path_of.update(updates)
        item.parent_reference = self._parent_reference(parent)
        if old_parent is not None:
            self._refresh_child_count(old_parent)
        self._refresh_child_count(parent)


class FakeGraphClient:
    """Builder tree over FakeDrive objects that records Graph calls."""

    def __init__(
        self,
        drives: Dict[str, FakeDrive],
        *,
        me_drive_id: Optional[str] = None,
        user_drives: Optional[Dict[str, str]] = None,
        page_size: int = 1000,
        copy_polls_before_done: int = 1,
    ) -> None:
        self.drives_by_id = drives
        self.me_drive_id = me_drive_id
        self.user_drives = {key.lower(): value for key, value in (user_drives or {}).items()}
        self.page_size = page_size
        self.copy_polls_before_done = copy_polls_before_done
        self.calls: List[Tuple[str, str, str, Any]] = []
        self.sessions: Dict[str, Dict[str, Any]] = {}
        self.monitors: Dict[str, Dict[str, Any]] = {}
        self.link_bodies: List[Any] = []
        self._failures: List[Tuple[Optional[str], int, Optional[float]]] = []
        self._pages: Dict[str, Tuple[List[Any], int, str, str, str]] = {}
        self.drives = SimpleNamespace(by_id=self.drives_by_id, by_drive_id=lambda did: _DriveBuilder(self, did))
        self.me = SimpleNamespace(drive=SimpleNamespace(get=self._me_drive))
        self.users = SimpleNamespace(
            by_user_id=lambda user: SimpleNamespace(drive=SimpleNamespace(get=lambda: self._user_drive(user)))
        )

    def fail_next(
        self, status: int, *, retry_after: Optional[float] = None, times: int = 1, op: Optional[str] = None
    ) -> None:
        """Make the next matching builder calls raise ``FakeAPIError``."""
        self._failures.extend([(op, status, retry_after)] * times)

    def _check_fail(self, op: str) -> None:
        """Raise and consume the first failure applicable to ``op``."""
        for index, (failed_op, status, retry_after) in enumerate(self._failures):
            if failed_op is None or failed_op == op:
                self._failures.pop(index)
                raise FakeAPIError(status, retry_after=retry_after)

    async def _me_drive(self) -> Any:
        """Return the configured ``me`` drive or a Graph not-found error."""
        self._check_fail("get")
        self.calls.append(("get", self.me_drive_id or "", "me", None))
        if self.me_drive_id not in self.drives_by_id:
            raise FakeAPIError(404)
        return SimpleNamespace(id=self.me_drive_id, name="OneDrive")

    async def _user_drive(self, user: str) -> Any:
        """Return a configured user's drive or a Graph not-found error."""
        drive_id = self.user_drives.get(user.lower())
        self._check_fail("get")
        self.calls.append(("get", drive_id or "", user, None))
        if drive_id not in self.drives_by_id:
            raise FakeAPIError(404)
        return SimpleNamespace(id=drive_id, name="OneDrive")


class _DriveBuilder:
    """Implement the drive-level branch of the SDK builder tree."""

    def __init__(self, fake: FakeGraphClient, drive_id: str) -> None:
        self.fake = fake
        self.drive_id = drive_id
        self.items = SimpleNamespace(by_drive_item_id=lambda ref: _ItemBuilder(fake, drive_id, ref))
        self.root = SimpleNamespace(get=self._root_get)

    def _drive(self) -> FakeDrive:
        if self.drive_id not in self.fake.drives_by_id:
            raise FakeAPIError(404)
        return self.fake.drives_by_id[self.drive_id]

    async def _root_get(self) -> FakeDriveItem:
        self.fake._check_fail("get")
        self.fake.calls.append(("get", self.drive_id, "root", None))
        return self._drive().root

    def search_with_q(self, query: str) -> "_PagedBuilder":
        """Build a paged, case-insensitive name search request."""
        drive = self._drive()
        values = [item for item in drive.by_id.values() if query.lower() in item.name.lower()]
        return _PagedBuilder(self.fake, self.drive_id, "search", query, values, "search")

    def with_url(self, raw_url: str) -> "_PagedBuilder":
        """Resume a previously-issued page by its fake next-link URL."""
        return _PagedBuilder.from_url(self.fake, raw_url)


class _ItemBuilder:
    """Implement item, content, children, and operation request builders."""

    def __init__(self, fake: FakeGraphClient, drive_id: str, ref: str) -> None:
        self.fake = fake
        self.drive_id = drive_id
        self.ref = ref
        self.children = _ChildrenBuilder(fake, drive_id, ref)
        self.content = _ContentBuilder(fake, drive_id, ref)
        self.create_link = SimpleNamespace(post=self._create_link)
        self.copy = SimpleNamespace(post=self._copy)
        self.create_upload_session = SimpleNamespace(post=self._create_upload_session)

    def _drive(self) -> FakeDrive:
        drive = self.fake.drives_by_id.get(self.drive_id)
        if drive is None:
            raise FakeAPIError(404)
        return drive

    def _item(self) -> FakeDriveItem:
        drive = self._drive()
        if self.ref == "root":
            return drive.root
        if self.ref.startswith("root:/") and self.ref.endswith(":"):
            path = "/".join(unquote(segment) for segment in self.ref[6:-1].split("/"))
            item = drive.lookup(path)
        elif ":/" in self.ref and self.ref.endswith(":"):
            parent_id, encoded_name = self.ref[:-1].split(":/", 1)
            parent_path = drive.path_of.get(parent_id)
            item = drive.lookup(f"{parent_path}/{unquote(encoded_name)}") if parent_path is not None else None
        else:
            item = drive.by_id.get(self.ref)
        if item is None:
            raise FakeAPIError(404)
        return item

    async def get(self) -> FakeDriveItem:
        self.fake._check_fail("get")
        self.fake.calls.append(("get", self.drive_id, self.ref, None))
        return self._item()

    async def delete(self) -> None:
        self.fake._check_fail("delete")
        self.fake.calls.append(("delete", self.drive_id, self.ref, None))
        self._drive().remove(self._item().id)

    async def patch(self, body: Any) -> FakeDriveItem:
        self.fake._check_fail("patch")
        self.fake.calls.append(("patch", self.drive_id, self.ref, body))
        item = self._item()
        parent_reference = getattr(body, "parent_reference", None) or getattr(body, "parentReference", None)
        parent_id = getattr(parent_reference, "id", None) or item.parent_reference.id
        self._drive().move(item, parent_id, getattr(body, "name", None))
        return item

    async def _create_link(self, body: Any) -> Any:
        self.fake._check_fail("create_link")
        self.fake.calls.append(("create_link", self.drive_id, self.ref, body))
        self.fake.link_bodies.append(body)
        item = self._item()
        return SimpleNamespace(
            link=SimpleNamespace(web_url=item.web_url or f"https://contoso.sharepoint.com/{item.name}")
        )

    async def _copy(self, body: Any, request_configuration: Any = None) -> Any:
        self.fake._check_fail("copy")
        self.fake.calls.append(("copy", self.drive_id, self.ref, body))
        source = self._item()
        parent_reference = getattr(body, "parent_reference", None) or getattr(body, "parentReference", None)
        parent_id = getattr(parent_reference, "id", None)
        job_id = f"copy-{next(_ids)}"
        self.fake.monitors[job_id] = {
            "polls_left": self.fake.copy_polls_before_done,
            "source": source,
            "drive_id": self.drive_id,
            "parent_id": parent_id or source.parent_reference.id,
            "name": getattr(body, "name", None) or source.name,
        }
        return SimpleNamespace(status_code=202, headers={"Location": FAKE_MONITOR + job_id})

    async def _create_upload_session(self, body: Any) -> Any:
        self.fake._check_fail("create_upload_session")
        self.fake.calls.append(("create_upload_session", self.drive_id, self.ref, body))
        self._item()
        item = getattr(body, "item", body)
        additional_data = getattr(item, "additional_data", {})
        session_id = f"upload-{next(_ids)}"
        self.fake.sessions[session_id] = {
            "drive_id": self.drive_id,
            "parent_id": self._item().id,
            "name": getattr(item, "name", None),
            "conflict": additional_data.get("@microsoft.graph.conflictBehavior", "replace"),
            "buffer": bytearray(),
            "total": None,
        }
        return SimpleNamespace(upload_url=FAKE_UPLOAD + session_id)


class _ChildrenBuilder:
    """Implement the children collection request builder."""

    def __init__(self, fake: FakeGraphClient, drive_id: str, ref: str) -> None:
        self.fake = fake
        self.drive_id = drive_id
        self.ref = ref

    def _paged(self) -> "_PagedBuilder":
        item = _ItemBuilder(self.fake, self.drive_id, self.ref)._item()
        return _PagedBuilder(
            self.fake,
            self.drive_id,
            self.ref,
            None,
            self.fake.drives_by_id[self.drive_id].children(item.id),
            "children",
        )

    async def get(self) -> Any:
        return await self._paged().get()

    def with_url(self, raw_url: str) -> "_PagedBuilder":
        return _PagedBuilder.from_url(self.fake, raw_url)

    async def post(self, body: Any) -> FakeDriveItem:
        self.fake._check_fail("children")
        self.fake.calls.append(("children", self.drive_id, self.ref, body))
        parent = _ItemBuilder(self.fake, self.drive_id, self.ref)._item()
        if parent.folder is None:
            raise FakeAPIError(409)
        name = getattr(body, "name", None)
        if not name:
            raise FakeAPIError(409)
        drive = self.fake.drives_by_id[self.drive_id]
        path = "/".join(value for value in (drive.path_of[parent.id], name) if value)
        if drive.lookup(path) is not None:
            raise FakeAPIError(409)
        return drive.put_folder(path)


class _ContentBuilder:
    """Implement a drive item's content request builder."""

    def __init__(self, fake: FakeGraphClient, drive_id: str, ref: str) -> None:
        self.fake = fake
        self.drive_id = drive_id
        self.ref = ref

    async def put(self, data: bytes, request_configuration: Any = None) -> FakeDriveItem:
        self.fake._check_fail("content_put")
        self.fake.calls.append(("content_put", self.drive_id, self.ref, data))
        item_builder = _ItemBuilder(self.fake, self.drive_id, self.ref)
        drive = item_builder._drive()
        try:
            item = item_builder._item()
            return drive.put_file(
                drive.path_of[item.id], data, mime=item.file.mime_type if item.file else "application/octet-stream"
            )
        except FakeAPIError as error:
            if error.response_status_code != 404 or ":/" not in self.ref:
                raise
            parent_id, encoded_name = self.ref[:-1].split(":/", 1)
            parent_path = "" if parent_id == "root" else drive.path_of.get(parent_id)
            if parent_path is None:
                raise
            return drive.put_file(f"{parent_path}/{unquote(encoded_name)}", data)

    async def get(self) -> bytes:
        self.fake._check_fail("content")
        self.fake.calls.append(("content", self.drive_id, self.ref, None))
        return _ItemBuilder(self.fake, self.drive_id, self.ref)._item().data


class _PagedBuilder:
    """Implement collection pagination and fake next-link resumption."""

    def __init__(
        self, fake: FakeGraphClient, drive_id: str, ref: str, extra: Any, values: List[Any], op: str, offset: int = 0
    ) -> None:
        self.fake = fake
        self.drive_id = drive_id
        self.ref = ref
        self.extra = extra
        self.values = values
        self.op = op
        self.offset = offset

    @classmethod
    def from_url(cls, fake: FakeGraphClient, raw_url: str) -> "_PagedBuilder":
        """Restore the collection state stored for a fake next link."""
        token = raw_url.removeprefix(FAKE_NEXT)
        try:
            values, offset, drive_id, ref, op = fake._pages[token]
        except KeyError as error:
            raise FakeAPIError(404) from error
        return cls(fake, drive_id, ref, None, values, op, offset)

    async def get(self) -> Any:
        self.fake._check_fail(self.op)
        self.fake.calls.append((self.op, self.drive_id, self.ref, self.extra))
        page = self.values[self.offset : self.offset + self.fake.page_size]
        next_offset = self.offset + self.fake.page_size
        next_link = None
        if next_offset < len(self.values):
            token = f"{next(_ids)}"
            self.fake._pages[token] = (self.values, next_offset, self.drive_id, self.ref, self.op)
            next_link = FAKE_NEXT + token
        return SimpleNamespace(value=page, odata_next_link=next_link)

    def with_url(self, raw_url: str) -> "_PagedBuilder":
        """Resume the supplied fake next-link URL."""
        return self.from_url(self.fake, raw_url)


class FakeResponse:
    """Async-context-manager response with JSON, text, and chunked content."""

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
        """Decode the response body as JSON."""
        return json.loads(self._body or b"null")

    async def text(self) -> str:
        """Decode the response body as UTF-8 text."""
        return self._body.decode("utf-8", "replace")

    async def _iter_chunked(self, size: int):
        """Yield body chunks of ``size`` bytes."""
        for offset in range(0, len(self._body), size):
            yield self._body[offset : offset + size]


class FakeAiohttpSession:
    """Stand in for aiohttp.ClientSession for fake upload, monitor, and download URLs."""

    def __init__(self, fake: FakeGraphClient) -> None:
        self.fake = fake
        self.requests: List[Tuple[str, str, Dict[str, str], Optional[bool]]] = []
        self.closed = False
        self._scripts: List[Tuple[str, int, Dict[str, str]]] = []

    def script(self, url_kind: str, status: int, *, times: int = 1, headers: Optional[Dict[str, str]] = None) -> None:
        """Script one or more raw HTTP responses for a URL kind."""
        self._scripts.extend([(url_kind, status, headers or {})] * times)

    async def __aenter__(self) -> "FakeAiohttpSession":
        return self

    async def __aexit__(self, *exc: Any) -> None:
        self.closed = True

    async def close(self) -> None:
        """Mark this fake session as closed."""
        self.closed = True

    def _scripted(self, kind: str) -> Optional[FakeResponse]:
        for index, (script_kind, status, headers) in enumerate(self._scripts):
            if script_kind == kind:
                self._scripts.pop(index)
                return FakeResponse(status, headers=headers)
        return None

    def _record(
        self, method: str, url: str, headers: Optional[Dict[str, str]], allow_redirects: Optional[bool]
    ) -> None:
        self.requests.append((method, url, headers or {}, allow_redirects))

    def put(
        self,
        url: str,
        *,
        data: bytes = b"",
        headers: Optional[Dict[str, str]] = None,
        allow_redirects: Optional[bool] = None,
        **_: Any,
    ) -> FakeResponse:
        """Accept an upload-session chunk and assemble it in the in-memory drive."""
        self._record("PUT", url, headers, allow_redirects)
        scripted = self._scripted("upload")
        if scripted is not None:
            return scripted
        session = self.fake.sessions.get(url.removeprefix(FAKE_UPLOAD))
        if session is None:
            return FakeResponse(404)
        content_range = (headers or {}).get("Content-Range", "")
        try:
            range_part, total = content_range.removeprefix("bytes ").split("/")
            start, end = (int(value) for value in range_part.split("-"))
            total_bytes = int(total)
        except ValueError:
            return FakeResponse(400)
        buffer: bytearray = session["buffer"]
        if len(buffer) < total_bytes:
            buffer.extend(b"\0" * (total_bytes - len(buffer)))
        buffer[start : end + 1] = data
        session["total"] = total_bytes
        if end + 1 < total_bytes:
            body = json.dumps({"nextExpectedRanges": [f"{end + 1}-{total_bytes - 1}"]}).encode()
            return FakeResponse(202, body=body)
        drive = self.fake.drives_by_id[session["drive_id"]]
        parent_path = drive.path_of[session["parent_id"]]
        path = "/".join(value for value in (parent_path, session["name"]) if value)
        if session["conflict"] == "fail" and drive.lookup(path) is not None:
            return FakeResponse(409)
        item = drive.put_file(path, bytes(buffer))
        body = json.dumps({"id": item.id, "name": item.name, "size": item.size, "webUrl": item.web_url}).encode()
        return FakeResponse(201, body=body)

    def get(
        self, url: str, *, headers: Optional[Dict[str, str]] = None, allow_redirects: Optional[bool] = None, **_: Any
    ) -> FakeResponse:
        """Poll a copy monitor or download an in-memory file."""
        self._record("GET", url, headers, allow_redirects)
        kind = "monitor" if url.startswith(FAKE_MONITOR) else "download" if url.startswith(FAKE_DOWNLOAD) else "unknown"
        scripted = self._scripted(kind)
        if scripted is not None:
            return scripted
        if kind == "monitor":
            job = self.fake.monitors.get(url.removeprefix(FAKE_MONITOR))
            if job is None:
                return FakeResponse(404)
            if job["polls_left"] > 0:
                job["polls_left"] -= 1
                return FakeResponse(202, body=b'{"status": "inProgress"}')
            source: FakeDriveItem = job["source"]
            drive = self.fake.drives_by_id[job["drive_id"]]
            parent_path = drive.path_of[job["parent_id"]]
            copied = drive.put_file(
                "/".join(value for value in (parent_path, job["name"]) if value),
                source.data,
                mime=source.file.mime_type,
            )
            return FakeResponse(200, body=json.dumps({"status": "completed", "resourceId": copied.id}).encode())
        if kind == "download":
            item_id = url.removeprefix(FAKE_DOWNLOAD)
            for drive in self.fake.drives_by_id.values():
                if item_id in drive.by_id:
                    return FakeResponse(200, body=drive.by_id[item_id].data)
            return FakeResponse(404)
        return FakeResponse(404)


def _bare(cls: type, fake: FakeGraphClient, **attrs: Any) -> Any:
    """Instantiate ``cls`` without its aioredis-creating initializer."""
    client = cls.__new__(cls)
    client.__dict__.update(
        dict(
            credentials={},
            tenant="contoso",
            tenant_id="t-1",
            site=None,
            auth_mode="direct",
            _credential=object(),
            _graph_client=fake,
            _access_token=None,
            _executor=None,
            _drive_id=None,
            _drive_info=None,
            logger=logging.getLogger("fake"),
        )
    )
    client.__dict__.update(attrs)
    return client


def make_sharepoint_client(fake: FakeGraphClient, *, drive_id: str, app_only: bool = True) -> SharepointClient:
    """Return a real SharepointClient instance without running ``__init__``."""

    async def _verify() -> None:
        return None

    async def _resolve_drive(library_name: Optional[str] = None) -> Any:
        return SimpleNamespace(id=drive_id, name=library_name or "Documents")

    return _bare(
        SharepointClient,
        fake,
        _srcfiles=[],
        _destination=[],
        _site_id=None,
        _site_info=None,
        verify_sharepoint_access=_verify,
        _resolve_drive=_resolve_drive,
        auth_mode="direct" if app_only else "delegated",
    )


def make_onedrive_client(fake: FakeGraphClient, *, app_only: bool = True) -> OneDriveClient:
    """Return a real OneDriveClient instance without running ``__init__``."""
    return _bare(OneDriveClient, fake, _user_drives={}, auth_mode="direct" if app_only else "delegated")


def make_probe(base_cls: type, *, drive_id: str = "drive-1", **kwargs: Any) -> Any:
    """Create a concrete test subclass for a partially abstract manager base."""

    async def _resolve_drive_id(self: Any) -> str:
        return drive_id

    def _build_client(self: Any) -> Any:
        raise AssertionError("adopt a fake client in tests")

    def _stub(name: str) -> Any:
        async def method(self: Any, *args: Any, **stub_kwargs: Any) -> Any:
            raise AssertionError(f"unimplemented abstract method: {name}")

        return method

    namespace: Dict[str, Any] = {"_build_client": _build_client, "_resolve_drive_id": _resolve_drive_id}
    for abstract_name in getattr(base_cls, "__abstractmethods__", set()) - set(namespace):
        namespace[abstract_name] = _stub(abstract_name)
    probe_cls = type("Probe", (base_cls,), namespace)
    return probe_cls(**kwargs)
