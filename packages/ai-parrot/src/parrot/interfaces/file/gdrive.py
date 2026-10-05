"""FileManagerInterface over Google Drive v3 (My Drive folders and shared drives) — FEAT-608."""

from __future__ import annotations

import asyncio
import contextlib
import contextvars
import fnmatch
import io
import logging
import mimetypes
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import (
    TYPE_CHECKING,
    Any,
    AsyncIterator,
    Awaitable,
    BinaryIO,
    Callable,
    Dict,
    List,
    Literal,
    Optional,
    Set,
    Tuple,
    Union,
)
from urllib.parse import urlsplit

from navigator.utils.file import FileManagerInterface, FileMetadata

from .batch import BatchItemResult, BatchSummary
from .entries import DriveEntry

if TYPE_CHECKING:
    from parrot.interfaces.google import DriveClient, GoogleClient

__all__ = (
    "BatchItemResult",
    "BatchSummary",
    "ConflictBehavior",
    "DriveEntry",
    "GoogleDriveFileManager",
    "GoogleDriveFileManagerError",
    "ShareRole",
    "ShareScope",
)

GoogleAuthModeLiteral = Literal["service_account", "user", "cached"]
ConflictBehavior = Literal["replace", "fail", "rename"]
ShareScope = Literal["user", "group", "domain", "anyone"]
ShareRole = Literal["reader", "commenter", "writer"]
FOLDER_MIME = "application/vnd.google-apps.folder"
WORKSPACE_MIME_PREFIX = "application/vnd.google-apps."
_RATE_LIMIT_REASONS = frozenset({"userRateLimitExceeded", "rateLimitExceeded"})
_RETRY_COUNTER: contextvars.ContextVar[Optional[List[int]]] = contextvars.ContextVar(
    "_gdrive_retry_counter", default=None
)


class GoogleDriveFileManagerError(RuntimeError):
    """Base error for Google Drive file-manager failures, with an optional status code."""

    def __init__(self, message: str, *, status_code: Optional[int] = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class _AsyncSink:
    """Adapter giving a sync sink aiogoogle's async ``pipe_to`` write contract."""

    def __init__(self, target: BinaryIO) -> None:
        self.target = target

    async def write(self, chunk: bytes) -> None:
        self.target.write(chunk)


class GoogleDriveFileManager(FileManagerInterface):
    """FileManagerInterface over one Google Drive root (My Drive folder or shared drive)."""

    manager_name = "gdrivefile"
    FOLDER_MIME = FOLDER_MIME
    WORKSPACE_MIME_PREFIX = WORKSPACE_MIME_PREFIX
    SMALL_FILE_THRESHOLD = 5 * 1024 * 1024
    CHUNK_SIZE = 8 * 1024 * 1024
    MAX_CONCURRENCY = 5
    MAX_RETRIES = 3
    RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})
    SERVING_MAX_BYTES = 64 * 1024 * 1024
    ALLOWED_HOSTS = ("www.googleapis.com",)
    LIST_PAGE_SIZE = 1000
    FIELDS = "id,name,mimeType,size,modifiedTime,webViewLink,webContentLink,parents,trashed"
    LIST_FIELDS = "nextPageToken,files(" + FIELDS + ")"
    RESUMABLE_URL: str = "https://www.googleapis.com/upload/drive/v3/files"

    def __init__(
        self,
        *,
        root_id: Optional[str] = None,
        root_path: str = "",
        shared_drive_id: Optional[str] = None,
        prefix: str = "",
        credentials: Optional[Union[str, Dict[str, Any], Path]] = None,
        auth_mode: GoogleAuthModeLiteral = "service_account",
        scopes: Optional[Union[str, List[str]]] = None,
        user_creds_cache_file: Optional[Union[str, Path]] = None,
        interactive_login_kwargs: Optional[Dict[str, Any]] = None,
        conflict_behavior: ConflictBehavior = "replace",
        permanent_delete: bool = False,
        max_concurrency: Optional[int] = None,
        max_retries: Optional[int] = None,
        chunk_size: Optional[int] = None,
        small_file_threshold: Optional[int] = None,
        serving_max_bytes: Optional[int] = None,
        **kwargs: Any,
    ) -> None:
        """Store configuration without constructing a client or performing I/O."""
        if root_id and root_path:
            raise ValueError("root_id and root_path are mutually exclusive")
        if auth_mode not in {"service_account", "user", "cached"}:
            raise ValueError(f"Unsupported Google auth mode: {auth_mode}")
        if conflict_behavior not in {"replace", "fail", "rename"}:
            raise ValueError(f"Unsupported conflict behavior: {conflict_behavior}")
        self.chunk_size = chunk_size or self.CHUNK_SIZE
        if self.chunk_size % 262144:
            raise ValueError("chunk_size must be a multiple of 262144")
        self.logger = logging.getLogger(__name__)
        if kwargs:
            self.logger.warning("Ignoring unsupported Google Drive options: %s", ", ".join(sorted(kwargs)))
        self.root_id_config = root_id
        self.root_path = root_path.strip("/")
        self.shared_drive_id = shared_drive_id
        self.prefix = prefix.strip("/") + "/" if prefix.strip("/") else ""
        self.credentials, self.auth_mode, self.scopes = credentials, auth_mode, scopes
        self.user_creds_cache_file = user_creds_cache_file
        self.interactive_login_kwargs = dict(interactive_login_kwargs or {})
        self.conflict_behavior, self.permanent_delete = conflict_behavior, permanent_delete
        self.max_concurrency = max_concurrency or self.MAX_CONCURRENCY
        self.max_retries = self.MAX_RETRIES if max_retries is None else max_retries
        self.small_file_threshold = small_file_threshold or self.SMALL_FILE_THRESHOLD
        self.serving_max_bytes = serving_max_bytes or self.SERVING_MAX_BYTES
        self._client: Optional[GoogleClient] = None
        self._owns_client = False
        self._drive: Optional[DriveClient] = None
        self._root_id: Optional[str] = None
        self._path_cache: Dict[str, Tuple[str, bool]] = {}

    def _build_client(self) -> "GoogleClient":
        from parrot.interfaces.google import GoogleClient

        kwargs: Dict[str, Any] = {}
        if self.user_creds_cache_file is not None:
            kwargs["user_creds_cache_file"] = self.user_creds_cache_file
        return GoogleClient(credentials=self.credentials, scopes=self.scopes or "drive", **kwargs)

    async def _authenticate(self, client: "GoogleClient") -> None:
        if self.auth_mode == "service_account":
            await client.initialize()
        elif self.auth_mode == "user":
            await client.interactive_login(scopes=self.scopes or "drive", **self.interactive_login_kwargs)
            await client.initialize()
        elif self.auth_mode == "cached":
            try:
                await client.initialize()
            except RuntimeError as exc:
                if "User credentials not available" not in str(exc):
                    raise
                await client.interactive_login(scopes=self.scopes or "drive", **self.interactive_login_kwargs)
                await client.initialize()
        else:
            raise ValueError(f"Unsupported Google auth mode: {self.auth_mode}")

    async def _resolve_root_id(self) -> str:
        if self.shared_drive_id:
            root = self.shared_drive_id
        elif self.root_id_config:
            try:
                await self.drive.files_get(self.root_id_config, fields="id,mimeType", **self._list_params())
            except Exception as exc:
                if self._status_code_of(exc) == 404:
                    raise FileNotFoundError(self.root_id_config) from exc
                raise
            root = self.root_id_config
        else:
            root = "root"
        self._path_cache[""] = (root, True)
        if not self.root_path:
            return root
        saved_root = self._root_id
        self._root_id = root
        try:
            return (await self._resolve(self.root_path, want_folder=True))[0]
        finally:
            self._root_id = saved_root

    async def connect(self) -> "GoogleDriveFileManager":
        if self._client is None:
            client = self._build_client()
            await self._authenticate(client)
            self._client, self._owns_client = client, True
        await self._ready()
        return self

    def adopt_client(self, client: "GoogleClient") -> None:
        if not client.is_authenticated:
            raise GoogleDriveFileManagerError("adopt_client() requires an initialised GoogleClient")
        self._client, self._owns_client = client, False

    async def _ready(self) -> str:
        if self._client is None:
            await self.connect()
        if self._drive is None:
            self._drive = await self.client.get_drive_client()
            await self._drive.open()
        if self._root_id is None:
            self._root_id = await self._resolve_root_id()
        return self._root_id

    async def close(self) -> None:
        drive, self._drive = self._drive, None
        if drive is not None:
            await drive.close()
        if self._client is not None and self._owns_client:
            client, self._client = self._client, None
            await client.close()
            redis = getattr(client, "redis", None)
            if redis is not None:
                with contextlib.suppress(Exception):
                    await redis.aclose()
        self._root_id, self._path_cache = None, {}

    async def __aenter__(self) -> "GoogleDriveFileManager":
        return await self.connect()

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        await self.close()

    @property
    def client(self) -> "GoogleClient":
        if self._client is None:
            raise GoogleDriveFileManagerError("Google Drive client is not connected")
        return self._client

    @property
    def drive(self) -> "DriveClient":
        if self._drive is None:
            raise GoogleDriveFileManagerError("Google Drive client is not ready")
        return self._drive

    @property
    def root_id(self) -> str:
        if self._root_id is None:
            raise GoogleDriveFileManagerError("Google Drive root id is not resolved")
        return self._root_id

    def _prefixed(self, key: str) -> str:
        value = key.replace("\\", "/").strip("/")
        if any(part == ".." for part in value.split("/")):
            raise ValueError("invalid path: '..' segments are not allowed")
        return (self.prefix + value).strip("/")

    def _unprefixed(self, key: str) -> str:
        return key[len(self.prefix) :] if self.prefix and key.startswith(self.prefix) else key

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
        full_path = full_path.strip("/")
        cached = self._path_cache.get(full_path)
        if cached is not None:
            if want_folder is not None and cached[1] != want_folder:
                raise FileNotFoundError(full_path)
            return cached
        parent, current = self.root_id, ""
        for segment in [part for part in full_path.split("/") if part]:
            current = "/".join((current, segment)).strip("/")
            cached = self._path_cache.get(current)
            if cached is not None:
                parent = cached[0]
                continue
            query = f"'{parent}' in parents and name = '{self._escape_q(segment)}' and trashed = false"
            response, _ = await self._retrying(
                lambda: self.drive.files_list(
                    q=query, fields=self.LIST_FIELDS, page_size=2, order_by="modifiedTime desc", **self._list_params()
                ),
                label="resolve",
            )
            items = response.get("files", [])
            if not items:
                raise FileNotFoundError(full_path)
            item = (
                min(items, key=lambda candidate: candidate["id"])
                if len(items) > 1 and items[0].get("modifiedTime") == items[1].get("modifiedTime")
                else items[0]
            )
            cached = (item["id"], self._is_folder(item))
            self._path_cache[current] = cached
            parent = cached[0]
        result = self._path_cache.get(full_path)
        if result is None or (want_folder is not None and result[1] != want_folder):
            raise FileNotFoundError(full_path)
        return result

    async def _resolve_parent(self, full_path: str, *, create: bool) -> str:
        parent_path = full_path.strip("/").rpartition("/")[0]
        if not parent_path:
            return self.root_id
        try:
            return (await self._resolve(parent_path, want_folder=True))[0]
        except FileNotFoundError:
            if not create:
                raise
        parent, current = self.root_id, ""
        for segment in parent_path.split("/"):
            current = "/".join((current, segment)).strip("/")
            cached = self._path_cache.get(current)
            if cached is not None:
                parent = cached[0]
                continue
            try:
                parent = (await self._resolve(current, want_folder=True))[0]
            except FileNotFoundError:
                item, _ = await self._retrying(
                    lambda: self.drive.files_create(
                        {"name": segment, "mimeType": FOLDER_MIME, "parents": [parent]},
                        fields=self.FIELDS,
                        **self._list_params(),
                    ),
                    label="create-folder",
                )
                parent = item["id"]
                self._path_cache[current] = (parent, True)
        return parent

    def _invalidate(self, full_path: str) -> None:
        for key in [key for key in self._path_cache if key == full_path or key.startswith(full_path + "/")]:
            self._path_cache.pop(key, None)

    @staticmethod
    def _is_folder(item: Dict[str, Any]) -> bool:
        return item.get("mimeType") == FOLDER_MIME

    @staticmethod
    def _is_workspace_native(item: Dict[str, Any]) -> bool:
        return item.get("mimeType", "").startswith(WORKSPACE_MIME_PREFIX) and not GoogleDriveFileManager._is_folder(
            item
        )

    def _make_metadata(self, item: Dict[str, Any], *, full_path: str) -> FileMetadata:
        modified = item.get("modifiedTime")
        parsed = datetime.fromisoformat(modified.replace("Z", "+00:00")) if modified else None
        return FileMetadata(
            item["name"],
            self._unprefixed(full_path),
            int(item.get("size") or 0),
            item.get("mimeType"),
            parsed,
            item.get("webViewLink"),
        )

    def _make_entry(self, item: Dict[str, Any], *, full_path: str) -> DriveEntry:
        metadata = self._make_metadata(item, full_path=full_path)
        return DriveEntry(
            id=item["id"],
            name=metadata.name,
            path=metadata.path,
            is_folder=self._is_folder(item),
            size=metadata.size,
            modified_at=metadata.modified_at,
            web_url=metadata.url,
            content_type=metadata.content_type,
        )

    @staticmethod
    def _status_code_of(error: BaseException) -> Optional[int]:
        code = getattr(getattr(error, "res", None), "status_code", None)
        if isinstance(code, int) and code:
            return code
        for attribute in ("status_code", "status"):
            code = getattr(error, attribute, None)
            if isinstance(code, int) and code:
                return code
        return None

    @staticmethod
    def _retry_after_seconds(error: BaseException) -> Optional[float]:
        headers = getattr(getattr(error, "res", None), "headers", None)
        getter = getattr(headers, "get", None)
        if not callable(getter):
            return None
        raw = getter("Retry-After") or getter("retry-after")
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
            value = (when.replace(tzinfo=when.tzinfo or timezone.utc) - datetime.now(timezone.utc)).total_seconds()
        return value if value >= 0 else None

    @staticmethod
    def _is_rate_limited_403(error: BaseException) -> bool:
        if GoogleDriveFileManager._status_code_of(error) != 403:
            return False
        body = getattr(getattr(error, "res", None), "json", None)
        try:
            return body["error"]["errors"][0]["reason"] in _RATE_LIMIT_REASONS
        except (KeyError, IndexError, TypeError):
            return False

    def _map_error(self, exc: BaseException, *, path: str) -> BaseException:
        status = self._status_code_of(exc)
        if status == 404:
            return FileNotFoundError(path)
        if status in {401, 403} and not self._is_rate_limited_403(exc):
            return PermissionError("Google Drive access was denied")
        if status == 409:
            return FileExistsError(path)
        return GoogleDriveFileManagerError(str(exc), status_code=status)

    async def _retrying(
        self, op: Callable[[], Awaitable[Any]], *, label: str, idempotent: bool = True
    ) -> Tuple[Any, int]:
        attempts = 1
        while True:
            try:
                return await op(), attempts
            except Exception as exc:
                retryable = self._status_code_of(exc) in self.RETRYABLE_STATUS or self._is_rate_limited_403(exc)
                if not idempotent or not retryable or attempts > self.max_retries:
                    raise
                delay = min(self._retry_after_seconds(exc) or 2 ** (attempts - 1), 60)
                self.logger.warning("Retrying Google Drive operation %s (attempt %s)", label, attempts)
                counter = _RETRY_COUNTER.get()
                if counter is not None:
                    counter[0] += 1
                await self._sleep(delay)
                attempts += 1

    async def _sleep(self, seconds: float) -> None:
        await asyncio.sleep(seconds)

    def _validate_upload_url(self, url: str) -> str:
        parts = urlsplit(url)
        if parts.scheme != "https" or parts.hostname not in self.ALLOWED_HOSTS:
            raise GoogleDriveFileManagerError("resumable session URL rejected by the host allow-list")
        return url

    # ---- read operations (TASK-3811) -------------------------------------
    async def _iter_query(self, q: str, *, order_by: Optional[str] = None) -> AsyncIterator[Dict[str, Any]]:
        """Yield every file matching ``q`` across all pages (AC12)."""
        page_token: Optional[str] = None
        while True:
            try:
                page, _ = await self._retrying(
                    lambda _page_token=page_token: self.drive.files_list(
                        q=q,
                        fields=self.LIST_FIELDS,
                        page_size=self.LIST_PAGE_SIZE,
                        page_token=_page_token,
                        order_by=order_by,
                        **self._list_params(),
                    ),
                    label="list",
                )
            except Exception as exc:
                raise self._map_error(exc, path=q) from exc
            for item in page.get("files", []):
                yield item
            page_token = page.get("nextPageToken")
            if not page_token:
                break

    async def _iter_children(self, folder_id: str) -> AsyncIterator[Dict[str, Any]]:
        """Yield all direct children of a folder across Drive result pages."""
        async for item in self._iter_query(f"'{folder_id}' in parents and trashed = false"):
            yield item

    async def list_files(self, path: str = "", pattern: str = "*") -> List[FileMetadata]:
        """List matching non-folder children of ``path`` across all pages."""
        await self._ready()
        full = self._prefixed(path)
        try:
            folder_id, _ = await self._resolve(full, want_folder=True)
            out: List[FileMetadata] = []
            async for item in self._iter_children(folder_id):
                if self._is_folder(item) or not fnmatch.fnmatch(item["name"], pattern):
                    continue
                child_path = f"{full}/{item['name']}".strip("/")
                out.append(self._make_metadata(item, full_path=child_path))
            return out
        except Exception as exc:
            if isinstance(exc, (FileNotFoundError, GoogleDriveFileManagerError)):
                raise
            raise self._map_error(exc, path=path) from exc

    async def list_entries(self, path: str = "") -> List[DriveEntry]:
        """List all direct children of ``path``, including folders, across all pages."""
        await self._ready()
        full = self._prefixed(path)
        try:
            folder_id, _ = await self._resolve(full, want_folder=True)
            out: List[DriveEntry] = []
            async for item in self._iter_children(folder_id):
                child_path = f"{full}/{item['name']}".strip("/")
                out.append(self._make_entry(item, full_path=child_path))
            return out
        except Exception as exc:
            if isinstance(exc, (FileNotFoundError, GoogleDriveFileManagerError)):
                raise
            raise self._map_error(exc, path=path) from exc

    async def exists(self, path: str) -> bool:
        """Return whether a file or folder resolves beneath the manager root."""
        await self._ready()
        try:
            await self._resolve(self._prefixed(path))
            return True
        except Exception as exc:
            mapped = exc if isinstance(exc, FileNotFoundError) else self._map_error(exc, path=path)
            if isinstance(mapped, FileNotFoundError):
                return False
            raise mapped from exc

    async def get_file_metadata(self, path: str) -> FileMetadata:
        """Return metadata for the file or folder at ``path``."""
        await self._ready()
        full = self._prefixed(path)
        try:
            file_id, _ = await self._resolve(full)
            item, _ = await self._retrying(
                lambda: self.drive.files_get(file_id, fields=self.FIELDS, **self._list_params()),
                label="get-metadata",
            )
            return self._make_metadata(item, full_path=full)
        except Exception as exc:
            if isinstance(exc, (FileNotFoundError, GoogleDriveFileManagerError)):
                raise
            raise self._map_error(exc, path=path) from exc

    async def find_entries(
        self,
        keywords: Optional[Union[str, List[str]]] = None,
        extension: Optional[str] = None,
        prefix: Optional[str] = None,
    ) -> List[DriveEntry]:
        """Recursively find files beneath ``prefix`` using Drive and client-side filters."""
        await self._ready()
        full_prefix = self._prefixed(prefix if prefix is not None else "")
        keyword_list = [keywords] if isinstance(keywords, str) else list(keywords or [])
        active_keywords = [keyword for keyword in keyword_list if keyword]
        first_keyword = active_keywords[0] if active_keywords else None
        remaining_keywords = [keyword.lower() for keyword in active_keywords[1:]]
        normalized_extension = f".{extension.lstrip('.')}".lower() if extension else None
        try:
            root_id, _ = await self._resolve(full_prefix, want_folder=True)
            queue: List[Tuple[str, str]] = [(root_id, full_prefix)]
            out: List[DriveEntry] = []
            while queue:
                folder_id, folder_path = queue.pop(0)
                async for child in self._iter_children(folder_id):
                    if self._is_folder(child):
                        child_path = f"{folder_path}/{child['name']}".strip("/")
                        queue.append((child["id"], child_path))

                query = f"'{folder_id}' in parents and mimeType != '{FOLDER_MIME}' and trashed = false"
                if first_keyword:
                    query += f" and name contains '{self._escape_q(first_keyword)}'"
                async for item in self._iter_query(query):
                    name_lower = item["name"].lower()
                    if not all(keyword in name_lower for keyword in remaining_keywords):
                        continue
                    if normalized_extension and not name_lower.endswith(normalized_extension):
                        continue
                    item_path = f"{folder_path}/{item['name']}".strip("/")
                    out.append(self._make_entry(item, full_path=item_path))
            return out
        except Exception as exc:
            if isinstance(exc, (FileNotFoundError, GoogleDriveFileManagerError)):
                raise
            raise self._map_error(exc, path=prefix or "") from exc

    async def find_files(self, keywords=None, extension=None, prefix=None) -> List[FileMetadata]:
        """Return metadata for every matching non-folder entry."""
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

    async def download_file(self, source: str, destination: Union[Path, BinaryIO]) -> Path:
        """Download a non-workspace file to a local path or writable binary stream."""
        await self._ready()
        full = self._prefixed(source)
        try:
            file_id, _ = await self._resolve(full, want_folder=False)
            item, _ = await self._retrying(
                lambda: self.drive.files_get(file_id, fields=self.FIELDS, **self._list_params()),
                label="get-metadata",
            )
            if self._is_workspace_native(item):
                raise GoogleDriveFileManagerError(
                    "Google Workspace files cannot be downloaded; export is not supported in v1"
                )
            if isinstance(destination, Path):
                destination.parent.mkdir(parents=True, exist_ok=True)
                await self._retrying(
                    lambda: self.drive.files_download(file_id, download_file=str(destination), **self._list_params()),
                    label="download",
                )
                return destination
            await self._retrying(
                lambda: self.drive.files_download(file_id, pipe_to=_AsyncSink(destination), **self._list_params()),
                label="download",
            )
            return Path(source)
        except (FileNotFoundError, GoogleDriveFileManagerError):
            raise
        except Exception as exc:
            raise self._map_error(exc, path=source) from exc

    # ---- uploads (TASK-3812) ---------------------------------------------
    async def _find_conflict(self, parent_id: str, name: str) -> Optional[Dict[str, Any]]:
        """Return the newest active child of ``parent_id`` called ``name``, if any."""
        q = f"'{parent_id}' in parents and name = '{self._escape_q(name)}' and trashed = false"
        async for item in self._iter_query(q, order_by="modifiedTime desc"):
            return item
        return None

    def _renamed(self, name: str, taken: Set[str]) -> str:
        """Return the first free ``stem (n).ext`` name not present in ``taken``."""
        stem, dot, ext = name.rpartition(".") if "." in name.lstrip(".") else (name, "", "")
        index = 1
        while f"{stem} ({index}){dot}{ext}" in taken:
            index += 1
        return f"{stem} ({index}){dot}{ext}"

    async def _apply_conflict(self, parent_id: str, name: str, destination: str) -> Tuple[str, Optional[str]]:
        """Return ``(final_name, existing_id)`` per ``conflict_behavior``."""
        existing = await self._find_conflict(parent_id, name)
        if existing is None:
            return name, None
        if self.conflict_behavior == "fail":
            raise FileExistsError(destination)
        if self.conflict_behavior == "rename":
            taken = {child["name"] async for child in self._iter_children(parent_id)}
            return self._renamed(name, taken), None
        return name, existing["id"]

    async def _upload_small(
        self,
        *,
        parent_id: str,
        name: str,
        existing_id: Optional[str],
        source: Union[Path, BinaryIO],
        content_type: str,
    ) -> Dict[str, Any]:
        """Multipart upload through aiogoogle for payloads below the resumable threshold."""
        start = 0 if isinstance(source, Path) else source.tell()
        chunk_size = self.chunk_size

        async def _pipe() -> AsyncIterator[bytes]:
            assert not isinstance(source, Path)
            source.seek(start)
            while True:
                chunk = await asyncio.to_thread(source.read, chunk_size)
                if not chunk:
                    break
                yield chunk

        async def _op() -> Dict[str, Any]:
            payload: Dict[str, Any] = (
                {"upload_file": str(source)} if isinstance(source, Path) else {"pipe_from": _pipe()}
            )
            if existing_id:
                return await self.drive.files_update(
                    existing_id,
                    {"name": name},
                    fields=self.FIELDS,
                    content_type=content_type,
                    **payload,
                    **self._list_params(),
                )
            return await self.drive.files_create(
                {"name": name, "parents": [parent_id]},
                fields=self.FIELDS,
                content_type=content_type,
                **payload,
                **self._list_params(),
            )

        item, _ = await self._retrying(_op, label="upload")
        return item

    @staticmethod
    def _header(headers: Any, key: str) -> Optional[str]:
        """Case-insensitive header lookup over a mapping-like object."""
        getter = getattr(headers, "get", None)
        if not callable(getter):
            return None
        return getter(key) or getter(key.lower())

    async def _upload_resumable(
        self,
        *,
        parent_id: str,
        name: str,
        existing_id: Optional[str],
        read: Callable[[int], Awaitable[bytes]],
        size: int,
        content_type: str,
    ) -> Dict[str, Any]:
        """Drive the Drive resumable-upload protocol (session, chunked PUTs, 308 resume)."""
        from aiogoogle.models import Request  # lazy: no module-level aiogoogle import in gdrive.py

        metadata: Dict[str, Any] = {"name": name}
        if existing_id:
            method, url = "PATCH", f"{self.RESUMABLE_URL}/{existing_id}"
        else:
            method, url = "POST", self.RESUMABLE_URL
            metadata["parents"] = [parent_id]
        session_request = Request(
            method=method,
            url=f"{url}?uploadType=resumable&supportsAllDrives=true",
            headers={
                "X-Upload-Content-Type": content_type,
                "X-Upload-Content-Length": str(size),
                "Content-Type": "application/json; charset=UTF-8",
            },
            json=metadata,
        )
        response, _ = await self._retrying(
            lambda: self.drive.send_raw(session_request, full_res=True), label="upload-session", idempotent=False
        )
        location = self._header(getattr(response, "headers", None), "Location")
        if not location:
            raise GoogleDriveFileManagerError("resumable upload session returned no Location header")
        session_url = self._validate_upload_url(location)

        position = 0
        pending = b""
        while True:
            if not pending:
                pending = await read(min(self.chunk_size, size - position))
            if not pending:
                raise GoogleDriveFileManagerError("upload source ended before the declared size")
            start, end = position, position + len(pending) - 1
            chunk_request = Request(
                method="PUT",
                url=session_url,
                headers={"Content-Range": f"bytes {start}-{end}/{size}", "Content-Length": str(len(pending))},
                data=pending,
            )

            async def _put(_request: Any = chunk_request) -> Any:
                res = await self.drive.send_raw(_request, full_res=True, raise_for_status=False)
                code = getattr(res, "status_code", None)
                if code not in (200, 201, 308):
                    raise GoogleDriveFileManagerError(f"resumable upload chunk failed ({code})", status_code=code)
                return res

            res, _ = await self._retrying(_put, label="upload-chunk", idempotent=True)
            if res.status_code in (200, 201):
                return res.json
            range_header = self._header(getattr(res, "headers", None), "Range")
            acknowledged = int(range_header.split("-")[1]) + 1 if range_header else 0
            if acknowledged < start or acknowledged > end + 1:
                raise GoogleDriveFileManagerError("resumable upload acknowledged an unexpected offset")
            pending = pending[acknowledged - start :]
            position = acknowledged

    async def _upload_any(
        self, source: Union[BinaryIO, Path], destination: str, content_type: Optional[str]
    ) -> Tuple[Dict[str, Any], FileMetadata]:
        """Shared upload pipeline: conflicts, routing, error mapping and cache invalidation."""
        await self._ready()
        full = self._prefixed(destination)
        try:
            parent_id = await self._resolve_parent(full, create=True)
            name = full.rsplit("/", 1)[-1]
            final_name, existing_id = await self._apply_conflict(parent_id, name, destination)
            guessed = content_type or mimetypes.guess_type(final_name)[0] or "application/octet-stream"
            stream: Optional[BinaryIO] = None
            if isinstance(source, Path):
                size = (await asyncio.to_thread(source.stat)).st_size
            else:
                stream = source
                if not (hasattr(source, "seekable") and source.seekable()):
                    head = await asyncio.to_thread(source.read, self.small_file_threshold + 1)
                    if len(head) > self.small_file_threshold:
                        raise ValueError("unseekable stream exceeds the small-file threshold; provide a seekable source")
                    stream = io.BytesIO(head)
                start = stream.tell()
                size = stream.seek(0, 2) - start
                stream.seek(start)
            if size < self.small_file_threshold:
                item = await self._upload_small(
                    parent_id=parent_id,
                    name=final_name,
                    existing_id=existing_id,
                    source=source if isinstance(source, Path) else stream,
                    content_type=guessed,
                )
            else:
                with contextlib.ExitStack() as stack:
                    if isinstance(source, Path):
                        handle = stack.enter_context(open(source, "rb"))  # noqa: SIM115
                    else:
                        handle = stream

                    async def _read(count: int) -> bytes:
                        return await asyncio.to_thread(handle.read, count)

                    item = await self._upload_resumable(
                        parent_id=parent_id,
                        name=final_name,
                        existing_id=existing_id,
                        read=_read,
                        size=size,
                        content_type=guessed,
                    )
            parent_path = full.rpartition("/")[0]
            final_path = f"{parent_path}/{final_name}".strip("/")
            self._invalidate(final_path)
            return item, self._make_metadata(item, full_path=final_path)
        except (FileNotFoundError, FileExistsError, ValueError, GoogleDriveFileManagerError):
            raise
        except Exception as exc:
            raise self._map_error(exc, path=destination) from exc

    async def upload_file(self, source: Union[BinaryIO, Path], destination: str) -> FileMetadata:
        """Upload ``source`` to ``destination``, routing by size and applying ``conflict_behavior``."""
        _, metadata = await self._upload_any(source, destination, None)
        return metadata

    async def create_file(self, path: str, content: bytes) -> bool:
        """Create (or replace per ``conflict_behavior``) a file with ``content``."""
        await self.upload_file(io.BytesIO(content), path)
        return True

    async def upload_file_from_bytes(
        self, file_obj: bytes, destination_key: str, content_type: str = "application/octet-stream"
    ) -> str:
        """Upload raw bytes and return the item's ``webViewLink`` (S3 parity)."""
        item, metadata = await self._upload_any(io.BytesIO(file_obj), destination_key, content_type)
        return item.get("webViewLink") or metadata.url or ""
