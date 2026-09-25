"""FileManagerInterface over Microsoft Graph drives (SharePoint and OneDrive)."""

from __future__ import annotations

import fnmatch
import io
import logging
import re
from abc import ABC, abstractmethod
import asyncio
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, AsyncIterator, Awaitable, BinaryIO, Callable, Dict, List, Literal, Optional, Tuple, Union
from urllib.parse import quote, urlsplit

import aiohttp
import aiofiles
from msgraph.generated.drives.item.items.item.create_upload_session.create_upload_session_post_request_body import (
    CreateUploadSessionPostRequestBody,
)
from msgraph.generated.models.drive_item import DriveItem
from msgraph.generated.models.drive_item_uploadable_properties import DriveItemUploadableProperties
from msgraph.generated.models.folder import Folder

from navigator.utils.file import FileManagerInterface, FileMetadata
from pydantic import BaseModel, ConfigDict

from parrot.interfaces.o365 import O365Client

from .batch import BatchErrorCode, BatchItemResult, BatchState, BatchSummary

__all__ = (
    "BatchErrorCode",
    "BatchItemResult",
    "BatchState",
    "BatchSummary",
    "DriveEntry",
    "GraphDriveFileManager",
    "GraphFileManagerError",
)

ConflictBehavior = Literal["replace", "fail", "rename"]
LinkType = Literal["view", "edit"]
LinkScope = Literal["organization", "anonymous", "users"]
AuthMode = Literal["direct", "on_behalf_of", "delegated", "cached"]


class DriveEntry(BaseModel):
    """One child of a folder, including folders returned by ``list_entries``."""

    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    path: str
    is_folder: bool
    size: int = 0
    modified_at: Optional[datetime] = None
    web_url: Optional[str] = None
    content_type: Optional[str] = None


class _RawHTTPError(Exception):
    """Non-2xx aiohttp response shaped like a kiota API error for retry handling."""

    def __init__(self, status: int, headers: Optional[Dict[str, str]] = None) -> None:
        super().__init__(f"HTTP {status}")
        self.response_status_code = status
        self.response_headers = dict(headers or {})


class GraphFileManagerError(RuntimeError):
    """Base error for Graph file-manager failures, with an optional status code."""

    def __init__(self, message: str, *, status_code: Optional[int] = None) -> None:
        """Initialize the error.

        Args:
            message: Human-readable failure description.
            status_code: Graph HTTP response status when known.
        """
        super().__init__(message)
        self.status_code = status_code


class GraphDriveFileManager(FileManagerInterface, ABC):
    """FileManagerInterface over one Microsoft Graph drive.

    Paths are drive-relative and use ``prefix`` with S3-compatible semantics.
    """

    manager_name: str = "graphfile"
    client_class: type = O365Client
    SMALL_FILE_THRESHOLD: int = 4 * 1024 * 1024
    CHUNK_SIZE: int = 10 * 1024 * 1024
    MAX_CONCURRENCY: int = 5
    MAX_RETRIES: int = 3
    COPY_TIMEOUT_S: float = 120.0
    RETRYABLE_STATUS: frozenset = frozenset({429, 503, 504})
    SERVING_MAX_BYTES: int = 64 * 1024 * 1024
    ALLOWED_ORIGINS: tuple = (
        "https://graph.microsoft.com",
        "https://graph.microsoft.us",
        "https://dod-graph.microsoft.us",
        "https://microsoftgraph.chinacloudapi.cn",
        "https://graph.microsoft.de",
    )
    ALLOWED_HOST_SUFFIXES: tuple = (".sharepoint.com", ".sharepoint-df.com", ".files.1drv.com")

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
        """Store configuration without performing network I/O.

        Args:
            prefix: Drive-relative folder used to scope all paths.
            credentials: O365 credential configuration.
            auth_mode: O365 authentication mode.
            user_assertion: Incoming user token for on-behalf-of authentication.
            scopes: Optional Graph scopes.
            conflict_behavior: Upload conflict behaviour.
            link_type: Default sharing-link type.
            link_scope: Default sharing-link scope.
            max_concurrency: Batch concurrency limit.
            max_retries: Retry budget for retryable Graph responses.
            chunk_size: Upload-session chunk size.
            small_file_threshold: Single-request upload size threshold.
            **kwargs: Ignored factory or toolkit pass-through options.
        """
        self.logger = logging.getLogger(__name__)
        normalized_prefix = prefix.replace("\\", "/").strip("/")
        self.prefix = f"{normalized_prefix}/" if normalized_prefix else ""
        self.credentials = dict(credentials or {})
        if user_assertion is not None:
            self.credentials["assertion"] = user_assertion
        self.auth_mode = auth_mode
        self.user_assertion = user_assertion
        self.scopes = scopes
        self.conflict_behavior = conflict_behavior
        self.link_type = link_type
        self.link_scope = link_scope
        self.max_concurrency = max_concurrency or self.MAX_CONCURRENCY
        self.max_retries = max_retries if max_retries is not None else self.MAX_RETRIES
        self.chunk_size = chunk_size or self.CHUNK_SIZE
        self.small_file_threshold = small_file_threshold or self.SMALL_FILE_THRESHOLD
        self._client: Optional[O365Client] = None
        self._drive_id: Optional[str] = None
        self._owns_client = False
        self._adopted = None
        if kwargs:
            self.logger.debug("Ignoring Graph file manager options: %s", sorted(kwargs))

    @abstractmethod
    def _build_client(self) -> O365Client:
        """Return the unauthenticated O365Client subclass for this drive kind."""

    @abstractmethod
    async def _resolve_drive_id(self) -> str:
        """Resolve and return the Graph drive id."""

    @property
    def client(self) -> O365Client:
        """Return the authenticated client after it has been connected or adopted."""
        if self._client is None:
            raise GraphFileManagerError("Graph client is not connected")
        return self._client

    @property
    def drive_id(self) -> str:
        """Return the resolved drive id after connection."""
        if self._drive_id is None:
            raise GraphFileManagerError("Graph drive id is not resolved")
        return self._drive_id

    def _prefixed(self, key: str) -> str:
        """Return ``prefix + key`` while rejecting parent-directory segments."""
        normalized_key = key.replace("\\", "/").lstrip("/")
        if any(segment == ".." for segment in normalized_key.split("/")):
            raise ValueError("Parent-directory segments are not allowed")
        if not normalized_key:
            return self.prefix.rstrip("/")
        return f"{self.prefix}{normalized_key}"

    def _unprefixed(self, key: str) -> str:
        """Strip the configured prefix from a drive-relative path when present."""
        normalized_key = key.replace("\\", "/").lstrip("/")
        if self.prefix and normalized_key.startswith(self.prefix):
            return normalized_key[len(self.prefix) :]
        return normalized_key

    def _item_ref(self, full_path: str) -> str:
        """Return a root or per-segment-quoted Microsoft Graph item reference."""
        segments = [segment for segment in (full_path or "").strip("/").split("/") if segment]
        if not segments:
            return "root"
        return "root:/" + "/".join(quote(segment, safe="") for segment in segments) + ":"

    def _item_path(self, item: Any) -> Optional[str]:
        """Return an item's drive-relative path, or None when Graph omitted it."""
        parent_reference = getattr(item, "parent_reference", None)
        parent_path = getattr(parent_reference, "path", None)
        if not parent_path or "root:" not in parent_path:
            return None
        parent = parent_path.split("root:", 1)[1].strip(":/")
        return "/".join(part for part in (parent, item.name) if part)

    def _make_metadata(self, item: Any, *, full_path: Optional[str] = None) -> FileMetadata:
        """Map a Graph DriveItem into its FileMetadata representation."""
        path = self._unprefixed(full_path or self._item_path(item) or item.name)
        is_folder = getattr(item, "folder", None) is not None
        file_info = getattr(item, "file", None)
        return FileMetadata(
            name=item.name,
            path=path,
            size=0 if is_folder else (getattr(item, "size", None) or 0),
            content_type=None if is_folder or file_info is None else getattr(file_info, "mime_type", None),
            modified_at=getattr(item, "last_modified_date_time", None),
            url=getattr(item, "web_url", None),
        )

    def _make_entry(self, item: Any, *, full_path: Optional[str] = None) -> DriveEntry:
        """Map a Graph DriveItem into a DriveEntry, preserving folders."""
        path = self._unprefixed(full_path or self._item_path(item) or item.name)
        is_folder = getattr(item, "folder", None) is not None
        file_info = getattr(item, "file", None)
        return DriveEntry(
            id=item.id,
            name=item.name,
            path=path,
            is_folder=is_folder,
            size=0 if is_folder else (getattr(item, "size", None) or 0),
            modified_at=getattr(item, "last_modified_date_time", None),
            web_url=getattr(item, "web_url", None),
            content_type=None if is_folder or file_info is None else getattr(file_info, "mime_type", None),
        )

    async def connect(self) -> "GraphDriveFileManager":
        """Build, authenticate, and resolve the drive id once."""
        async with self._get_lock():
            if self._client is None:
                client = self._build_client()
                client.processing_credentials()
                client.set_auth_mode(self.auth_mode)
                loop = asyncio.get_running_loop()
                if self.auth_mode == "direct":
                    username = self.credentials.get("username")
                    password = self.credentials.get("password")
                    if username is not None and password is not None:
                        await loop.run_in_executor(None, client.user_auth, username, password, self.scopes)
                    else:
                        await loop.run_in_executor(None, client.acquire_token, self.scopes)
                elif self.auth_mode == "on_behalf_of":
                    if self.user_assertion is None:
                        raise ValueError("user_assertion is required for on_behalf_of authentication")
                    await loop.run_in_executor(
                        None, client.acquire_token_on_behalf_of, self.user_assertion, self.scopes
                    )
                elif self.auth_mode == "delegated":
                    await client.interactive_login(scopes=self.scopes)
                elif self.auth_mode == "cached":
                    await client.ensure_interactive_session(scopes=self.scopes)
                else:
                    raise ValueError(f"Unknown authentication mode: {self.auth_mode}")
                self._client, self._owns_client = client, True
            if self._drive_id is None:
                self._drive_id = await self._resolve_drive_id()
        return self

    def adopt_client(self, client: O365Client) -> None:
        """Reuse an authenticated client without acquiring another token."""
        if isinstance(client, self.client_class):
            self._client = client
            self._owns_client = False
        else:
            wrapper = self._build_client()
            wrapper.processing_credentials()
            for attribute in ("_credential", "_graph_client", "_access_token", "auth_mode"):
                setattr(wrapper, attribute, getattr(client, attribute))
            self._client = wrapper
            self._owns_client = True
        self._adopted = client
        self._drive_id = None

    async def _ready(self) -> str:
        """Return the drive id, connecting or resolving it on an adopted client."""
        if self._drive_id is None:
            if self._client is None:
                await self.connect()
            else:
                async with self._get_lock():
                    if self._drive_id is None:
                        self._drive_id = await self._resolve_drive_id()
        return self._drive_id

    def _get_lock(self) -> asyncio.Lock:
        """Return the lazily-created lifecycle lock."""
        lock = self.__dict__.get("_lock_obj")
        if lock is None:
            lock = self.__dict__["_lock_obj"] = asyncio.Lock()
        return lock

    async def close(self) -> None:
        """Close only a client owned by this manager and clear cached state."""
        client = self._client
        if client is not None and self._owns_client:
            await client.close()
        self._client = None
        self._drive_id = None
        self._owns_client = False
        self._adopted = None

    async def __aenter__(self) -> "GraphDriveFileManager":
        """Connect the manager for asynchronous context-manager use."""
        return await self.connect()

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        """Release manager-owned resources at context exit."""
        await self.close()

    def _http_session(self) -> aiohttp.ClientSession:
        """Return a session for pre-authenticated raw Graph URLs."""
        return aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=None, sock_read=300))

    async def _sleep(self, seconds: float) -> None:
        """Sleep for retry backoff; separated for deterministic tests."""
        await asyncio.sleep(seconds)

    @staticmethod
    def _status_code_of(error: BaseException) -> Optional[int]:
        """Extract an HTTP status code from Graph or raw HTTP errors."""
        code = getattr(error, "response_status_code", None)
        if isinstance(code, int) and code:
            return code
        for attribute in ("status_code", "status", "code"):
            code = getattr(error, attribute, None)
            if isinstance(code, int) and code:
                return code
        return None

    @staticmethod
    def _retry_after_seconds(error: BaseException) -> Optional[float]:
        """Extract a non-negative Retry-After delay from an HTTP error."""
        headers = getattr(error, "response_headers", None)
        getter = getattr(headers, "get", None)
        if not callable(getter):
            return None
        try:
            raw = getter("Retry-After") or getter("retry-after")
        except TypeError:
            return None
        if isinstance(raw, (set, frozenset, list, tuple)):
            raw = next(iter(sorted(str(value) for value in raw)), None)
        if raw is None:
            return None
        try:
            value = float(str(raw).strip())
        except (TypeError, ValueError):
            try:
                when = parsedate_to_datetime(str(raw).strip())
            except (TypeError, ValueError):
                return None
            if when is None:
                return None
            if when.tzinfo is None:
                when = when.replace(tzinfo=timezone.utc)
            value = (when - datetime.now(timezone.utc)).total_seconds()
        return value if value >= 0 else None

    def _map_error(self, exc: BaseException, *, path: str) -> BaseException:
        """Map a Graph error to the public file-manager exception contract."""
        status = self._status_code_of(exc)
        if status == 404:
            return FileNotFoundError(path)
        if status in {401, 403}:
            return PermissionError("Graph access was denied")
        if status == 409:
            return FileExistsError(path)
        return GraphFileManagerError(str(exc), status_code=status)

    async def _retrying(
        self, op: Callable[[], Awaitable[Any]], *, label: str, idempotent: bool = True
    ) -> Tuple[Any, int]:
        """Run an operation with the single bounded Graph retry policy."""
        attempts = 1
        while True:
            try:
                return await op(), attempts
            except Exception as exc:
                status = self._status_code_of(exc)
                if not idempotent or status not in self.RETRYABLE_STATUS or attempts > self.max_retries:
                    raise
                delay = min(self._retry_after_seconds(exc) or 2 ** (attempts - 1), 60)
                self.logger.warning("Retrying Graph operation %s after status %s (attempt %s)", label, status, attempts)
                await self._sleep(delay)
                attempts += 1

    def _validate_graph_url(self, url: str, *, purpose: str) -> str:
        """Accept only approved HTTPS Graph, SharePoint, and OneDrive URLs."""
        parts = urlsplit(url)
        host = (parts.hostname or "").lower()
        allowed = f"https://{host}" in self.ALLOWED_ORIGINS or host.endswith(self.ALLOWED_HOST_SUFFIXES)
        if parts.scheme != "https" or not host or not allowed:
            raise GraphFileManagerError(f"Invalid {purpose} URL")
        return url

    def _drive(self) -> Any:
        """``graph_client.drives.by_drive_id(<resolved drive>)`` request builder."""
        return self.client.graph_client.drives.by_drive_id(self.drive_id)

    async def _get_item(self, full_path: str) -> Any:
        """GET the DriveItem at a prefixed drive path (retried; raw errors propagate to the caller's mapping)."""
        item, _ = await self._retrying(
            lambda: self._drive().items.by_drive_item_id(self._item_ref(full_path)).get(), label="get"
        )
        if item is None:
            raise FileNotFoundError(full_path)
        return item

    async def _get_item_by_id(self, item_id: str) -> Any:
        """GET by stable item id (search hits without a path; the OneDrive download-by-id tool)."""
        item, _ = await self._retrying(lambda: self._drive().items.by_drive_item_id(item_id).get(), label="get")
        if item is None:
            raise FileNotFoundError(item_id)
        return item

    async def _iter_children(self, item_id: str) -> AsyncIterator[Any]:
        """Yield every child of ``item_id`` across all pages (S4)."""
        builder = self._drive().items.by_drive_item_id(item_id).children
        resp, _ = await self._retrying(lambda: builder.get(), label="children")
        while resp is not None:
            for child in resp.value or []:
                yield child
            nxt = getattr(resp, "odata_next_link", None)
            if not nxt:
                break
            resp, _ = await self._retrying(lambda: builder.with_url(nxt).get(), label="children-next")

    async def _iter_search(self, q: str) -> AsyncIterator[Any]:
        """Yield every ``search(q)`` hit on the drive across all pages (S4)."""
        builder = self._drive().search_with_q(q)
        resp, _ = await self._retrying(lambda: builder.get(), label="search")
        while resp is not None:
            for hit in resp.value or []:
                yield hit
            nxt = getattr(resp, "odata_next_link", None)
            if not nxt:
                break
            resp, _ = await self._retrying(lambda: builder.with_url(nxt).get(), label="search-next")

    @staticmethod
    def _query_is_api_safe(query: str) -> bool:
        """True when ``query`` has no wildcard/regex metacharacters (rule of sharepoint.py:867-873)."""
        return not re.search(r"[*?\[\]\{\}\(\)\^\$|\\]", query or "")

    async def list_files(self, path: str = "", pattern: str = "*") -> List[FileMetadata]:
        """Non-recursive listing of ``path``: files only, fnmatch ``pattern``, all pages (S4/S8)."""
        await self._ready()
        full = self._prefixed(path)
        try:
            folder = await self._get_item(full)
            out: List[FileMetadata] = []
            async for child in self._iter_children(folder.id):
                if getattr(child, "folder", None) is not None:
                    continue
                if not fnmatch.fnmatch(child.name, pattern):
                    continue
                child_path = f"{full}/{child.name}" if full else child.name
                out.append(self._make_metadata(child, full_path=child_path))
            return out
        except Exception as exc:
            raise self._map_error(exc, path=path) from exc

    async def list_entries(self, path: str = "") -> List[DriveEntry]:
        """Non-recursive listing INCLUDING folders, all pages; used by the O365 List tools (S8)."""
        await self._ready()
        full = self._prefixed(path)
        try:
            folder = await self._get_item(full)
            out: List[DriveEntry] = []
            async for child in self._iter_children(folder.id):
                child_path = f"{full}/{child.name}" if full else child.name
                out.append(self._make_entry(child, full_path=child_path))
            return out
        except Exception as exc:
            raise self._map_error(exc, path=path) from exc

    async def exists(self, path: str) -> bool:
        """True for files AND folders that resolve; False on 404."""
        await self._ready()
        full = self._prefixed(path)
        try:
            await self._get_item(full)
            return True
        except Exception as exc:
            mapped = self._map_error(exc, path=path)
            if isinstance(mapped, FileNotFoundError):
                return False
            raise mapped from exc

    async def get_file_metadata(self, path: str) -> FileMetadata:
        """Metadata of one item; FileNotFoundError on 404."""
        await self._ready()
        full = self._prefixed(path)
        try:
            item = await self._get_item(full)
            return self._make_metadata(item, full_path=full)
        except Exception as exc:
            raise self._map_error(exc, path=path) from exc

    async def find_entries(
        self,
        keywords: Optional[Union[str, List[str]]] = None,
        extension: Optional[str] = None,
        prefix: Optional[str] = None,
    ) -> List[DriveEntry]:
        """Graph search when the keyword is API-safe, else a recursive walk under ``prefix``; files only, all pages (AC20)."""
        await self._ready()
        full_prefix = self._prefixed(prefix if prefix is not None else "")
        prefix_check = f"{full_prefix}/" if full_prefix else ""
        keyword_list = [keywords] if isinstance(keywords, str) else list(keywords or [])
        keywords_lower = [keyword.lower() for keyword in keyword_list if keyword]
        out: List[DriveEntry] = []
        try:
            if keyword_list and keyword_list[0] and self._query_is_api_safe(keyword_list[0]):
                async for hit in self._iter_search(keyword_list[0]):
                    if getattr(hit, "folder", None) is not None:
                        continue
                    item_path = self._item_path(hit)
                    if item_path is None:
                        resolved = await self._get_item_by_id(hit.id)
                        item_path = self._item_path(resolved)
                        if item_path is not None:
                            hit = resolved
                    if item_path is None:
                        continue
                    if prefix_check and not item_path.startswith(prefix_check):
                        continue
                    if keywords_lower and not all(keyword in item_path.lower() for keyword in keywords_lower):
                        continue
                    if extension and not item_path.endswith(extension):
                        continue
                    out.append(self._make_entry(hit, full_path=item_path))
            else:
                root_item = await self._get_item(full_prefix)
                queue: List[Tuple[str, str]] = [(root_item.id, full_prefix)]
                while queue:
                    current_id, current_path = queue.pop(0)
                    async for child in self._iter_children(current_id):
                        child_path = f"{current_path}/{child.name}" if current_path else child.name
                        if getattr(child, "folder", None) is not None:
                            queue.append((child.id, child_path))
                            continue
                        if keywords_lower and not all(keyword in child_path.lower() for keyword in keywords_lower):
                            continue
                        if extension and not child_path.endswith(extension):
                            continue
                        out.append(self._make_entry(child, full_path=child_path))
            return out
        except Exception as exc:
            raise self._map_error(exc, path=full_prefix) from exc

    async def find_files(
        self,
        keywords: Optional[Union[str, List[str]]] = None,
        extension: Optional[str] = None,
        prefix: Optional[str] = None,
    ) -> List[FileMetadata]:
        """FileManagerInterface override (abstract.py:265): ``find_entries`` mapped to FileMetadata."""
        entries = await self.find_entries(keywords=keywords, extension=extension, prefix=prefix)
        return [
            FileMetadata(
                name=entry.name,
                path=entry.path,
                size=entry.size,
                content_type=entry.content_type,
                modified_at=entry.modified_at,
                url=entry.web_url,
            )
            for entry in entries
        ]

    async def delete_file(self, path: str) -> bool:
        """DELETE the item (goes to the recycle bin). False when it does not exist."""
        await self._ready()
        full = self._prefixed(path)
        try:
            item = await self._get_item(full)
        except Exception as exc:
            mapped = self._map_error(exc, path=path)
            if isinstance(mapped, FileNotFoundError):
                return False
            raise mapped from exc
        try:
            await self._retrying(lambda: self._drive().items.by_drive_item_id(item.id).delete(), label="delete")
            return True
        except Exception as exc:
            raise self._map_error(exc, path=path) from exc

    async def _ensure_parent(self, full_path: str) -> Any:
        """Ensure the parent folder chain of ``full_path`` exists and return its final item."""
        parent = await self._get_item("")
        segments = [segment for segment in full_path.strip("/").split("/") if segment][:-1]
        current_path = ""
        for segment in segments:
            current_path = f"{current_path}/{segment}".strip("/")
            try:
                parent = await self._get_item(current_path)
            except Exception as exc:
                if self._status_code_of(exc) != 404:
                    raise
                folder = DriveItem(
                    name=segment,
                    folder=Folder(),
                    additional_data={"@microsoft.graph.conflictBehavior": "fail"},
                )
                try:
                    parent, _ = await self._retrying(
                        lambda: self._drive().items.by_drive_item_id(parent.id).children.post(folder), label="create-folder"
                    )
                except Exception as create_error:
                    if self._status_code_of(create_error) != 409:
                        raise
                    parent = await self._get_item(current_path)
        return parent

    async def _put_small(self, parent_id: str, name: str, data: bytes) -> Any:
        """Single PUT for replace-conflict uploads below the configured threshold."""
        ref = f"{parent_id}:/{quote(name, safe='')}:"
        item, _ = await self._retrying(
            lambda: self._drive().items.by_drive_item_id(ref).content.put(data), label="content-put"
        )
        return item

    async def _create_session(self, parent_id: str, name: str) -> str:
        """Create a configurable-conflict upload session and return its pre-authenticated URL."""
        body = CreateUploadSessionPostRequestBody()
        body.item = DriveItemUploadableProperties()
        body.item.name = name
        body.item.additional_data = {"@microsoft.graph.conflictBehavior": self.conflict_behavior}
        ref = f"{parent_id}:/{quote(name, safe='')}:"
        session, _ = await self._retrying(
            lambda: self._drive().items.by_drive_item_id(ref).create_upload_session.post(body),
            label="create-upload-session",
            idempotent=False,
        )
        return session.upload_url

    async def _put_session(
        self, upload_url: str, read: Callable[[int], Awaitable[bytes]], size: int
    ) -> Dict[str, Any]:
        """Upload chunks to a validated pre-authenticated session URL."""
        url = self._validate_graph_url(upload_url, purpose="upload session")
        offset = 0
        async with self._http_session() as session:
            while offset < size:
                chunk = await read(min(self.chunk_size, size - offset))
                if not chunk:
                    break
                end = offset + len(chunk) - 1
                headers = {
                    "Content-Length": str(len(chunk)),
                    "Content-Range": f"bytes {offset}-{end}/{size}",
                }

                async def put_chunk() -> Tuple[int, Dict[str, Any]]:
                    async with session.put(url, data=chunk, headers=headers, allow_redirects=False) as response:
                        if response.status not in {200, 201, 202}:
                            raise _RawHTTPError(response.status, dict(response.headers))
                        return response.status, await response.json()

                (status, result), _ = await self._retrying(put_chunk, label="upload-chunk")
                if status in {200, 201}:
                    return result
                offset += len(chunk)
        raise GraphFileManagerError(f"upload session ended at byte {offset} of {size} without a final item")

    async def upload_file(self, source: Union[BinaryIO, Path], destination: str) -> FileMetadata:
        """Upload a local file or binary stream and return Graph metadata."""
        await self._ready()
        dest_full = self._prefixed(destination)
        try:
            parent = await self._ensure_parent(dest_full)
            name = dest_full.rsplit("/", 1)[-1]

            if isinstance(source, (str, Path)):
                local_path = Path(source)
                size = (await asyncio.to_thread(local_path.stat)).st_size
                if size < self.small_file_threshold and self.conflict_behavior == "replace":
                    async with aiofiles.open(local_path, "rb") as handle:
                        item = await self._put_small(parent.id, name, await handle.read())
                else:
                    async with aiofiles.open(local_path, "rb") as handle:
                        upload_url = await self._create_session(parent.id, name)
                        result = await self._put_session(upload_url, handle.read, size)
                    item = await self._get_item_by_id(result["id"])
            else:
                try:
                    position = await asyncio.to_thread(source.tell)
                    await asyncio.to_thread(source.seek, 0, 2)
                    size = await asyncio.to_thread(source.tell)
                    await asyncio.to_thread(source.seek, position)
                except (AttributeError, OSError, io.UnsupportedOperation):
                    source = io.BytesIO(await asyncio.to_thread(source.read))
                    size = len(source.getvalue())
                if size < self.small_file_threshold and self.conflict_behavior == "replace":
                    item = await self._put_small(parent.id, name, await asyncio.to_thread(source.read))
                else:
                    upload_url = await self._create_session(parent.id, name)

                    async def read_stream(length: int) -> bytes:
                        return await asyncio.to_thread(source.read, length)

                    result = await self._put_session(upload_url, read_stream, size)
                    item = await self._get_item_by_id(result["id"])
            return self._make_metadata(item, full_path=dest_full)
        except Exception as exc:
            raise self._map_error(exc, path=destination) from exc

    async def create_file(self, path: str, content: bytes) -> bool:
        """Upload raw bytes to ``path`` and report completion."""
        await self.upload_file(io.BytesIO(content), path)
        return True

    async def upload_file_from_bytes(
        self, file_obj: bytes, destination_key: str, content_type: str = "application/octet-stream"
    ) -> str:
        """Upload bytes with S3-compatible arguments and return the Graph web URL."""
        self.logger.debug("upload_file_from_bytes: content_type=%s (Graph infers MIME from the name)", content_type)
        metadata = await self.upload_file(io.BytesIO(file_obj), destination_key)
        return metadata.url or ""

    async def download_file(self, source: str, destination: Union[Path, BinaryIO]) -> Path:
        """Stream a Graph download URL into a local path or writable binary stream."""
        await self._ready()
        full_path = self._prefixed(source)
        try:
            item = await self._get_item(full_path)
            if getattr(item, "folder", None) is not None:
                raise IsADirectoryError(source)
            url = getattr(item, "additional_data", {}).get("@microsoft.graph.downloadUrl")
            if not url:
                raise GraphFileManagerError("Graph item has no download URL")
            url = self._validate_graph_url(url, purpose="download")
            async with self._http_session() as session:
                async with session.get(url, headers={}, allow_redirects=False) as response:
                    if response.status != 200:
                        raise _RawHTTPError(response.status, dict(response.headers))
                    if isinstance(destination, (str, Path)):
                        target = Path(destination)
                        await asyncio.to_thread(target.parent.mkdir, parents=True, exist_ok=True)
                        async with aiofiles.open(target, "wb") as handle:
                            async for chunk in response.content.iter_chunked(1024 * 1024):
                                await handle.write(chunk)
                        return target
                    async for chunk in response.content.iter_chunked(1024 * 1024):
                        await asyncio.to_thread(destination.write, chunk)
            return Path(source)
        except IsADirectoryError:
            raise
        except Exception as exc:
            raise self._map_error(exc, path=source) from exc
