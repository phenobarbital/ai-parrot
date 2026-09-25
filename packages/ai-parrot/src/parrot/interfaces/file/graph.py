"""FileManagerInterface over Microsoft Graph drives (SharePoint and OneDrive)."""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional
from urllib.parse import quote

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
        parent = parent_path.split("root:", 1)[1].strip("/")
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
