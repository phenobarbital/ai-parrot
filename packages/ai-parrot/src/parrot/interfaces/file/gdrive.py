"""FileManagerInterface over Google Drive v3 (My Drive folders and shared drives) — FEAT-608."""
from __future__ import annotations

import asyncio
import contextlib
import contextvars
import logging
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Awaitable, BinaryIO, Callable, Dict, List, Literal, Optional, Tuple, Union
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
_RETRY_COUNTER: contextvars.ContextVar[Optional[List[int]]] = contextvars.ContextVar("_gdrive_retry_counter", default=None)


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

    def __init__(self, *, root_id: Optional[str] = None, root_path: str = "", shared_drive_id: Optional[str] = None,
                 prefix: str = "", credentials: Optional[Union[str, Dict[str, Any], Path]] = None,
                 auth_mode: GoogleAuthModeLiteral = "service_account", scopes: Optional[Union[str, List[str]]] = None,
                 user_creds_cache_file: Optional[Union[str, Path]] = None,
                 interactive_login_kwargs: Optional[Dict[str, Any]] = None,
                 conflict_behavior: ConflictBehavior = "replace", permanent_delete: bool = False,
                 max_concurrency: Optional[int] = None, max_retries: Optional[int] = None,
                 chunk_size: Optional[int] = None, small_file_threshold: Optional[int] = None,
                 serving_max_bytes: Optional[int] = None, **kwargs: Any) -> None:
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
            response, _ = await self._retrying(lambda: self.drive.files_list(q=query, fields=self.LIST_FIELDS,
                page_size=2, order_by="modifiedTime desc", **self._list_params()), label="resolve")
            items = response.get("files", [])
            if not items:
                raise FileNotFoundError(full_path)
            item = min(items, key=lambda candidate: candidate["id"]) if len(items) > 1 and items[0].get("modifiedTime") == items[1].get("modifiedTime") else items[0]
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
                item, _ = await self._retrying(lambda: self.drive.files_create({"name": segment, "mimeType": FOLDER_MIME, "parents": [parent]}, fields=self.FIELDS, **self._list_params()), label="create-folder")
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
        return item.get("mimeType", "").startswith(WORKSPACE_MIME_PREFIX) and not GoogleDriveFileManager._is_folder(item)

    def _make_metadata(self, item: Dict[str, Any], *, full_path: str) -> FileMetadata:
        modified = item.get("modifiedTime")
        parsed = datetime.fromisoformat(modified.replace("Z", "+00:00")) if modified else None
        return FileMetadata(item["name"], self._unprefixed(full_path), int(item.get("size") or 0), item.get("mimeType"), parsed, item.get("webViewLink"))

    def _make_entry(self, item: Dict[str, Any], *, full_path: str) -> DriveEntry:
        metadata = self._make_metadata(item, full_path=full_path)
        return DriveEntry(id=item["id"], name=metadata.name, path=metadata.path, is_folder=self._is_folder(item), size=metadata.size,
                          modified_at=metadata.modified_at, web_url=metadata.url, content_type=metadata.content_type)

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

    async def _retrying(self, op: Callable[[], Awaitable[Any]], *, label: str, idempotent: bool = True) -> Tuple[Any, int]:
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
