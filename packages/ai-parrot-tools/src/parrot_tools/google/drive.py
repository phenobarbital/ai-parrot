"""Google Drive tools for agents (FEAT-608, Module 7)."""

from __future__ import annotations

import fnmatch
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from parrot.conf import OUTPUT_DIR
from parrot.interfaces.file.gdrive import ConflictBehavior, GoogleDriveFileManager, ShareRole, ShareScope
from parrot.interfaces.google import GoogleClient
from parrot.tools.toolkit import AbstractToolkit


class GoogleDriveToolkit(AbstractToolkit):
    """Google Drive tools delegating to :class:`GoogleDriveFileManager`."""

    tool_prefix: str = "gdrive"
    auto_open: bool = True

    def __init__(
        self,
        manager: Optional[GoogleDriveFileManager] = None,
        *,
        google_client: Optional[GoogleClient] = None,
        root_id: Optional[str] = None,
        root_path: str = "",
        shared_drive_id: Optional[str] = None,
        prefix: str = "",
        credentials: Optional[Union[str, Dict[str, Any], Path]] = None,
        auth_mode: str = "service_account",
        scopes: Optional[Union[str, List[str]]] = None,
        download_dir: Optional[Union[str, Path]] = None,
        max_results: int = 50,
        **kwargs: Any,
    ) -> None:
        """Initialize the toolkit, deferring manager creation until first use.

        Args:
            manager: Existing Drive manager. When supplied, it takes precedence.
            google_client: Authenticated client to adopt into a built manager.
            root_id: Optional Drive folder id to use as the root.
            root_path: Optional Drive path to use as the root.
            shared_drive_id: Optional shared-drive id.
            prefix: Drive-relative prefix beneath the configured root.
            credentials: Google credential configuration for a built manager.
            auth_mode: Google authentication mode.
            scopes: Optional Google OAuth scopes.
            download_dir: Local destination directory for downloads.
            max_results: Default maximum search results.
            **kwargs: Additional :class:`AbstractToolkit` configuration.
        """
        super().__init__(**kwargs)
        self.logger = logging.getLogger(__name__)
        self._manager = manager
        self._owns_manager = manager is None
        self._google_client = google_client
        self._manager_kwargs = {
            "root_id": root_id,
            "root_path": root_path,
            "shared_drive_id": shared_drive_id,
            "prefix": prefix,
            "credentials": credentials,
            "auth_mode": auth_mode,
            "scopes": scopes,
        }
        self.download_dir = Path(download_dir) if download_dir else Path(OUTPUT_DIR) / "gdrive"
        self.max_results = max_results

    async def _open(self) -> None:
        """Build a manager and connect or adopt the configured Google client."""
        if self._manager is None:
            self._manager = GoogleDriveFileManager(**self._manager_kwargs)
        if self._google_client is not None:
            self._manager.adopt_client(self._google_client)
            await self._manager._ready()
        else:
            await self._manager.connect()

    async def _close(self) -> None:
        """Close only a Drive manager created by this toolkit."""
        if self._owns_manager and self._manager is not None:
            await self._manager.close()
            self._manager = None
        await super()._close()

    async def list_files(self, path: str = "", pattern: str = "*", include_folders: bool = False) -> Dict[str, Any]:
        """List a Google Drive folder without recursing.

        Args:
            path: Folder path relative to the configured root.
            pattern: Glob pattern matched against entry names.
            include_folders: Whether sub-folders are included.

        Returns:
            A mapping containing entries, their count, and the requested path.
        """
        await self._ensure_open()
        entries = await self._manager.list_entries(path)
        result = [
            {
                "name": entry.name,
                "path": entry.path,
                "is_folder": entry.is_folder,
                "size": entry.size,
                "content_type": entry.content_type,
                "modified_at": entry.modified_at.isoformat() if entry.modified_at else None,
                "web_url": entry.web_url,
            }
            for entry in entries
            if fnmatch.fnmatch(entry.name, pattern) and (include_folders or not entry.is_folder)
        ]
        return {"entries": result, "count": len(result), "path": path}

    async def search_files(
        self,
        keywords: Optional[Union[str, List[str]]] = None,
        extension: Optional[str] = None,
        prefix: Optional[str] = None,
        max_results: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Search Google Drive files beneath an optional path prefix.

        Args:
            keywords: One or more filename keywords.
            extension: Optional filename extension filter.
            prefix: Optional Drive path beneath which to search.
            max_results: Result limit applied after Drive filtering.

        Returns:
            A mapping containing matching files, count, and truncation status.
        """
        await self._ensure_open()
        files = await self._manager.find_files(keywords=keywords, extension=extension, prefix=prefix)
        limit = self.max_results if max_results is None else max_results
        selected = files[:limit]
        return {
            "files": [
                {
                    "name": item.name,
                    "path": item.path,
                    "size": item.size,
                    "content_type": item.content_type,
                    "modified_at": item.modified_at.isoformat() if item.modified_at else None,
                    "url": item.url,
                }
                for item in selected
            ],
            "count": len(selected),
            "truncated": len(files) > len(selected),
        }

    async def download_file(self, path: str, destination_name: Optional[str] = None) -> Dict[str, Any]:
        """Download a Drive file into the toolkit's local download directory.

        Args:
            path: Drive-relative source file path.
            destination_name: Optional local filename replacing the source basename.

        Returns:
            A mapping describing the downloaded local file.
        """
        await self._ensure_open()
        local_path = self.download_dir / (destination_name or Path(path).name)
        downloaded = await self._manager.download_file(path, local_path)
        metadata = await self._manager.get_file_metadata(path)
        return {
            "downloaded": True,
            "path": path,
            "local_path": str(downloaded),
            "size": metadata.size,
            "content_type": metadata.content_type,
        }

    async def upload_file(
        self,
        source_path: str,
        destination: str,
        conflict_behavior: Optional[ConflictBehavior] = None,
    ) -> Dict[str, Any]:
        """Upload a local file to Google Drive.

        Args:
            source_path: Existing local file path.
            destination: Drive-relative destination path.
            conflict_behavior: Optional per-upload conflict policy.

        Returns:
            A mapping describing the uploaded Drive file.

        Raises:
            FileNotFoundError: If ``source_path`` does not exist.
        """
        await self._ensure_open()
        source = Path(source_path)
        previous_behavior = self._manager.conflict_behavior
        if conflict_behavior is not None:
            self._manager.conflict_behavior = conflict_behavior
        try:
            metadata = await self._manager.upload_file(source, destination)
        finally:
            self._manager.conflict_behavior = previous_behavior
        return {
            "uploaded": True,
            "name": metadata.name,
            "path": metadata.path,
            "size": metadata.size,
            "content_type": metadata.content_type,
            "url": metadata.url,
        }

    async def share_file(
        self,
        path: str,
        scope: ShareScope = "user",
        role: ShareRole = "reader",
        email_address: Optional[str] = None,
        domain: Optional[str] = None,
        expiry: int = 0,
    ) -> Dict[str, Any]:
        """Create a Google Drive sharing permission and return its file link.

        Args:
            path: Drive-relative file path.
            scope: Permission scope.
            role: Permission role.
            email_address: Recipient address for user or group permissions.
            domain: Recipient domain for domain permissions.
            expiry: Optional permission expiry in seconds.

        Returns:
            A mapping describing the created share permission.
        """
        await self._ensure_open()
        url = await self._manager.create_sharing_link(
            path,
            scope=scope,
            role=role,
            email_address=email_address,
            domain=domain,
            expiry=expiry,
        )
        return {"shared": True, "path": path, "scope": scope, "role": role, "url": url}

    async def get_file_link(self, path: str) -> Dict[str, Any]:
        """Return a file's Drive web link without changing its permissions.

        Args:
            path: Drive-relative file path.

        Returns:
            A mapping containing the path and its web link.
        """
        await self._ensure_open()
        return {"path": path, "url": await self._manager.get_file_url(path)}
