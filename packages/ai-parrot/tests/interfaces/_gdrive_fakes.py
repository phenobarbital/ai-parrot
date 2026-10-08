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
    """Mimic an aiogoogle HTTPError response."""

    def __init__(
        self,
        status: int,
        *,
        retry_after: Optional[float] = None,
        message: str = "",
        reason: Optional[str] = None,
    ) -> None:
        super().__init__(message or f"fake Drive error (status {status})")
        headers = {} if retry_after is None else {"Retry-After": str(retry_after)}
        body = {"error": {"errors": [{"reason": reason}]}} if reason else None
        self.res = SimpleNamespace(status_code=status, headers=headers, json=body)


@dataclass
class FakeDriveFile:
    """Minimal Drive v3 file resource retained by ``FakeDrive``."""

    id: str
    name: str
    mimeType: str
    parents: List[str]
    content: bytes = b""
    modifiedTime: dt.datetime = field(default_factory=lambda: dt.datetime.now(dt.timezone.utc))
    trashed: bool = False

    def as_json(self) -> Dict[str, Any]:
        """Return the camelCase Google Drive file-resource representation."""
        resource: Dict[str, Any] = {
            "id": self.id,
            "name": self.name,
            "mimeType": self.mimeType,
            "modifiedTime": self.modifiedTime.astimezone(dt.timezone.utc).isoformat().replace("+00:00", "Z"),
            "parents": self.parents.copy(),
            "trashed": self.trashed,
            "webViewLink": f"https://drive.google.com/file/d/{self.id}/view",
            "webContentLink": f"https://drive.google.com/uc?id={self.id}&export=download",
        }
        if self.mimeType != FOLDER_MIME:
            resource["size"] = str(len(self.content))
        return resource


class FakeDrive:
    """In-memory Drive keyed by id; root is ``root`` or the supplied shared-drive id."""

    def __init__(self, *, drive_id: Optional[str] = None) -> None:
        self.root_id = drive_id or "root"
        self.by_id: Dict[str, FakeDriveFile] = {}
        self.calls: List[Tuple[str, str, Dict[str, Any]]] = []

    def _child(self, parent_id: str, name: str) -> Optional[FakeDriveFile]:
        """Return the first active direct child with ``name``."""
        return next(
            (
                item
                for item in self.by_id.values()
                if parent_id in item.parents and item.name == name and not item.trashed
            ),
            None,
        )

    def put_folder(self, path: str) -> FakeDriveFile:
        """Create each missing path segment and return the leaf folder."""
        parent_id = self.root_id
        current: Optional[FakeDriveFile] = None
        for segment in (part for part in path.strip("/").split("/") if part):
            current = self._child(parent_id, segment)
            if current is None:
                current = FakeDriveFile(
                    id=f"fake-{next(_ids)}",
                    name=segment,
                    mimeType=FOLDER_MIME,
                    parents=[parent_id],
                )
                self.by_id[current.id] = current
            parent_id = current.id
        if current is None:
            return FakeDriveFile(id=self.root_id, name="root", mimeType=FOLDER_MIME, parents=[])
        return current

    def put_file(
        self,
        path: str,
        data: bytes,
        *,
        mime: str = "application/octet-stream",
        modified: Optional[dt.datetime] = None,
    ) -> FakeDriveFile:
        """Create or replace a file, creating parent folders as necessary."""
        clean = path.strip("/")
        parent_path, _, name = clean.rpartition("/")
        parent = self.put_folder(parent_path)
        item = self._child(parent.id, name)
        if item is None:
            item = FakeDriveFile(
                id=f"fake-{next(_ids)}",
                name=name,
                mimeType=mime,
                parents=[parent.id],
            )
            self.by_id[item.id] = item
        item.mimeType = mime
        item.content = data
        item.modifiedTime = modified or dt.datetime.now(dt.timezone.utc)
        item.trashed = False
        return item

    def duplicate(self, path: str, data: bytes, *, modified: dt.datetime) -> FakeDriveFile:
        """Add a same-name sibling for duplicate-name tests."""
        clean = path.strip("/")
        parent_path, _, name = clean.rpartition("/")
        parent = self.put_folder(parent_path)
        item = FakeDriveFile(
            id=f"fake-{next(_ids)}",
            name=name,
            mimeType="application/octet-stream",
            parents=[parent.id],
            content=data,
            modifiedTime=modified,
        )
        self.by_id[item.id] = item
        return item


_Q_TERM = re.compile(
    r"'(?P<pid>[^']+)' in parents|name (?P<op>=|contains) '(?P<name>(?:\\.|[^'])*)'"
    r"|mimeType (?P<mop>=|!=) '(?P<mime>[^']+)'|trashed = (?P<trashed>true|false)"
)
_CONTENT_RANGE = re.compile(r"bytes (?P<start>\d+)-(?P<end>\d+)/(?P<total>\d+)")


class FakeDriveClient:
    """Stand-in for ``DriveClient`` over a ``FakeDrive``."""

    def __init__(self, drive: FakeDrive, *, page_size: int = 2, service_account: bool = True) -> None:
        self.drive = drive
        self.page_size = page_size
        self.service_account = service_account
        self.opened = 0
        self.closed = 0
        self.requests: List[Any] = []
        self._failures: List[Tuple[int, Optional[float], Optional[str], Optional[str]]] = []
        self._sessions: Dict[str, Dict[str, Any]] = {}

    def fail_next(
        self,
        status: int,
        *,
        retry_after: Optional[float] = None,
        times: int = 1,
        method: Optional[str] = None,
        reason: Optional[str] = None,
    ) -> None:
        """Inject one or more errors for the next matching API method."""
        self._failures.extend([(status, retry_after, method, reason)] * times)

    def _maybe_fail(self, method: str) -> None:
        """Raise and remove the first matching scripted failure."""
        for index, failure in enumerate(self._failures):
            status, retry_after, failure_method, reason = failure
            if failure_method is None or failure_method == method:
                self._failures.pop(index)
                raise FakeHTTPError(status, retry_after=retry_after, reason=reason)

    def _record(self, resource: str, method: str, **params: Any) -> None:
        """Record a fake Drive API operation."""
        self.drive.calls.append((resource, method, params))

    def _get(self, file_id: str) -> FakeDriveFile:
        """Get a file or raise the Drive-shaped missing-resource error."""
        item = self.drive.by_id.get(file_id)
        if item is None:
            raise FakeHTTPError(404)
        return item

    @staticmethod
    def _unescape(value: str) -> str:
        """Undo Drive query escaping for backslashes and apostrophes."""
        return value.replace("\\'", "'").replace("\\\\", "\\")

    async def _content_from(self, pipe_from: Any, upload_file: Optional[str] = None) -> bytes:
        """Collect a bytes payload from an async or synchronous source."""
        if pipe_from is None:
            if upload_file is not None:
                with open(upload_file, "rb") as source:
                    return source.read()
            return b""
        if isinstance(pipe_from, bytes):
            return pipe_from
        chunks: List[bytes] = []
        if hasattr(pipe_from, "__aiter__"):
            async for chunk in pipe_from:
                chunks.append(chunk)
        else:
            value = pipe_from.read()
            if hasattr(value, "__await__"):
                value = await value
            chunks.append(value)
        return b"".join(chunks)

    async def open(self) -> "FakeDriveClient":
        """Record a client open operation."""
        self.opened += 1
        return self

    async def close(self) -> None:
        """Record a client close operation."""
        self.closed += 1

    async def files_list(
        self,
        *,
        q: str,
        fields: str,
        page_size: int = 1000,
        page_token: Optional[str] = None,
        order_by: Optional[str] = None,
        drive_id: Optional[str] = None,
        **params: Any,
    ) -> Dict[str, Any]:
        """List Drive resources filtered by the manager's supported query grammar."""
        self._maybe_fail("files.list")
        request_params = {
            "q": q,
            "fields": fields,
            "page_size": page_size,
            "page_token": page_token,
            "order_by": order_by,
            "drive_id": drive_id,
            **params,
        }
        self._record("files", "list", **request_params)
        items = list(self.drive.by_id.values())
        for match in _Q_TERM.finditer(q):
            groups = match.groupdict()
            if groups["pid"] is not None:
                items = [item for item in items if groups["pid"] in item.parents]
            elif groups["op"] is not None:
                name = self._unescape(groups["name"])
                if groups["op"] == "=":
                    items = [item for item in items if item.name == name]
                else:
                    items = [item for item in items if name in item.name]
            elif groups["mop"] is not None:
                if groups["mop"] == "=":
                    items = [item for item in items if item.mimeType == groups["mime"]]
                else:
                    items = [item for item in items if item.mimeType != groups["mime"]]
            elif groups["trashed"] is not None:
                expected = groups["trashed"] == "true"
                items = [item for item in items if item.trashed == expected]
        if order_by == "modifiedTime desc":
            items.sort(key=lambda item: (-item.modifiedTime.timestamp(), item.id))
        else:
            items.sort(key=lambda item: item.id)
        offset = int(page_token or "0")
        limit = min(page_size, self.page_size)
        page = items[offset : offset + limit]
        response: Dict[str, Any] = {"files": [item.as_json() for item in page]}
        if offset + limit < len(items):
            response["nextPageToken"] = str(offset + limit)
        return response

    async def files_get(self, file_id: str, *, fields: str, **params: Any) -> Dict[str, Any]:
        """Fetch a Drive file resource by id."""
        self._maybe_fail("files.get")
        self._record("files", "get", file_id=file_id, fields=fields, **params)
        return self._get(file_id).as_json()

    async def files_create(
        self,
        metadata: Dict[str, Any],
        *,
        fields: str,
        upload_file: Optional[str] = None,
        pipe_from: Any = None,
        content_type: Optional[str] = None,
        **params: Any,
    ) -> Dict[str, Any]:
        """Create a Drive resource from metadata and optional payload data."""
        self._maybe_fail("files.create")
        self._record("files", "create", metadata=metadata, fields=fields, upload_file=upload_file, **params)
        content = await self._content_from(pipe_from, upload_file)
        parent_ids = metadata.get("parents") or [self.drive.root_id]
        item = FakeDriveFile(
            id=f"fake-{next(_ids)}",
            name=metadata["name"],
            mimeType=metadata.get("mimeType") or content_type or "application/octet-stream",
            parents=list(parent_ids),
            content=content,
        )
        self.drive.by_id[item.id] = item
        return item.as_json()

    async def files_update(
        self,
        file_id: str,
        metadata: Optional[Dict[str, Any]] = None,
        *,
        fields: str,
        add_parents: Optional[str] = None,
        remove_parents: Optional[str] = None,
        upload_file: Optional[str] = None,
        pipe_from: Any = None,
        content_type: Optional[str] = None,
        **params: Any,
    ) -> Dict[str, Any]:
        """Update a Drive resource's fields, parents, or content."""
        self._maybe_fail("files.update")
        self._record("files", "update", file_id=file_id, metadata=metadata, fields=fields, **params)
        item = self._get(file_id)
        for key in ("name", "mimeType", "trashed"):
            if metadata is not None and key in metadata:
                setattr(item, key, metadata[key])
        if add_parents:
            for parent_id in add_parents.split(","):
                if parent_id not in item.parents:
                    item.parents.append(parent_id)
        if remove_parents:
            item.parents = [parent_id for parent_id in item.parents if parent_id not in remove_parents.split(",")]
        if pipe_from is not None or upload_file is not None:
            item.content = await self._content_from(pipe_from, upload_file)
        if content_type:
            item.mimeType = content_type
        item.modifiedTime = dt.datetime.now(dt.timezone.utc)
        return item.as_json()

    async def files_copy(
        self,
        file_id: str,
        metadata: Dict[str, Any],
        *,
        fields: str,
        **params: Any,
    ) -> Dict[str, Any]:
        """Copy a file resource with optionally overridden metadata."""
        self._maybe_fail("files.copy")
        self._record("files", "copy", file_id=file_id, metadata=metadata, fields=fields, **params)
        source = self._get(file_id)
        item = FakeDriveFile(
            id=f"fake-{next(_ids)}",
            name=metadata.get("name", source.name),
            mimeType=metadata.get("mimeType", source.mimeType),
            parents=list(metadata.get("parents", source.parents)),
            content=source.content,
        )
        self.drive.by_id[item.id] = item
        return item.as_json()

    async def files_delete(self, file_id: str, **params: Any) -> None:
        """Permanently delete a Drive resource."""
        self._maybe_fail("files.delete")
        self._record("files", "delete", file_id=file_id, **params)
        self._get(file_id)
        del self.drive.by_id[file_id]

    async def files_download(
        self,
        file_id: str,
        *,
        download_file: Optional[str] = None,
        pipe_to: Any = None,
        **params: Any,
    ) -> None:
        """Download content to a file or asynchronous sink in three chunks."""
        self._maybe_fail("files.download")
        self._record("files", "download", file_id=file_id, **params)
        content = self._get(file_id).content
        if download_file is not None:
            with open(download_file, "wb") as output:
                output.write(content)
        if pipe_to is not None:
            chunk_size = max(1, (len(content) + 2) // 3)
            for offset in range(0, len(content), chunk_size):
                await pipe_to.write(content[offset : offset + chunk_size])

    async def permissions_create(
        self,
        file_id: str,
        body: Dict[str, Any],
        *,
        send_notification_email: bool = False,
        **params: Any,
    ) -> Dict[str, Any]:
        """Create a synthetic Drive permission for an existing file."""
        self._maybe_fail("permissions.create")
        self._record(
            "permissions",
            "create",
            file_id=file_id,
            body=body,
            send_notification_email=send_notification_email,
            **params,
        )
        self._get(file_id)
        return {"id": f"permission-{next(_ids)}", **body}

    async def execute(self, request: Any, *, full_res: bool = False, raise_for_status: bool = True) -> Any:
        """Record an execute call and return the supplied fake request response."""
        self._maybe_fail("execute")
        self._record("request", "execute", full_res=full_res, raise_for_status=raise_for_status)
        return request

    async def send_raw(self, request: Any, *, full_res: bool = True, raise_for_status: bool = True) -> Any:
        """Script resumable-upload POST/PATCH and chunk PUT responses."""
        method = request.method.upper()
        self._maybe_fail(method)
        self.requests.append(request)
        self._record("raw", method, full_res=full_res, raise_for_status=raise_for_status)
        if method in {"POST", "PATCH"} and str(request.url).startswith(UPLOAD_URL):
            session_id = f"fake-{next(_ids)}"
            location = f"{UPLOAD_URL}?upload_id={session_id}"
            self._sessions[location] = {"metadata": request.json or {}, "content": bytearray()}
            return SimpleNamespace(status_code=200, headers={"Location": location}, json=None)
        session = self._sessions.get(request.url)
        if method != "PUT" or session is None:
            raise FakeHTTPError(404)
        content_range = _CONTENT_RANGE.fullmatch(request.headers["Content-Range"])
        if content_range is None:
            raise FakeHTTPError(400)
        end = int(content_range["end"])
        total = int(content_range["total"])
        data = request.data
        if hasattr(data, "__await__"):
            data = await data
        session["content"].extend(data)
        if end + 1 < total:
            return SimpleNamespace(status_code=308, headers={"Range": f"bytes=0-{end}"}, json=None)
        metadata = session["metadata"]
        parent_ids = metadata.get("parents") or [self.drive.root_id]
        item = FakeDriveFile(
            id=f"fake-{next(_ids)}",
            name=metadata.get("name", "upload"),
            mimeType=metadata.get("mimeType", "application/octet-stream"),
            parents=list(parent_ids),
            content=bytes(session["content"]),
        )
        self.drive.by_id[item.id] = item
        del self._sessions[request.url]
        return SimpleNamespace(status_code=200, headers={}, json=item.as_json())


def make_google_client(fake: FakeDriveClient, *, auth_type: str = "service_account") -> GoogleClient:
    """Build a real GoogleClient instance without invoking its initializer."""
    client = GoogleClient.__new__(GoogleClient)
    closes: List[int] = []

    async def _get_drive_client(version: str = "v3") -> FakeDriveClient:
        return fake

    async def _close() -> None:
        closes.append(1)

    client.__dict__.update(
        {
            "auth_type": auth_type,
            "_authenticated": True,
            "_service_account_creds": object() if auth_type == "service_account" else None,
            "_user_creds": None if auth_type == "service_account" else object(),
            "redis": None,
            "logger": logging.getLogger("fake.google"),
            "get_drive_client": _get_drive_client,
            "close": _close,
            "closes": closes,
        }
    )
    return client


def make_manager(fake: FakeDriveClient, **kwargs: Any) -> Any:
    """Build a manager and inject the fake through its real client-adoption hook."""
    from parrot.interfaces.file.gdrive import GoogleDriveFileManager

    manager = GoogleDriveFileManager(**kwargs)
    manager.adopt_client(make_google_client(fake, auth_type="service_account" if fake.service_account else "user"))
    return manager
