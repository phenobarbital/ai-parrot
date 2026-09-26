"""
OneDrive Tools for AI-Parrot.

Tools for interacting with OneDrive:
- List files in folders
- Search for files
- Download files
- Upload files
"""

import asyncio
from pathlib import Path
from typing import Any, Dict, List, Optional, Type

from pydantic import BaseModel, Field

from parrot.interfaces.file.onedrive import OneDriveFileManager
from parrot.interfaces.o365 import O365Client

from .base import O365Tool, O365ToolArgsSchema
from .delta import DEFAULT_MAX_PAGES, DriveDeltaHelper

# ============================================================================
# LIST ONEDRIVE FILES TOOL
# ============================================================================


class ListOneDriveFilesArgs(O365ToolArgsSchema):
    """Arguments for listing OneDrive files."""

    folder_path: Optional[str] = Field(
        default="", description="Folder path in OneDrive (e.g., 'Documents/Projects'). Empty for root."
    )
    recursive: bool = Field(default=False, description="Whether to list files recursively in subfolders")


class ListOneDriveFilesTool(O365Tool):
    """
    Tool for listing files in OneDrive.

    This tool lists all files in a specified OneDrive location, with options
    for recursive listing and filtering.

    Examples:
        # List files in root
        result = await tool.run()

        # List files in specific folder
        result = await tool.run(
            folder_path="Documents/Projects"
        )

        # Recursive listing
        result = await tool.run(
            folder_path="Work",
            recursive=True
        )
    """

    name: str = "list_onedrive_files"
    description: str = "List files in OneDrive folder. " "Returns file names, paths, sizes, and modification dates."
    args_schema: Type[BaseModel] = ListOneDriveFilesArgs

    async def _execute_graph_operation(self, client: O365Client, **kwargs) -> Dict[str, Any]:
        """List OneDrive files through OneDriveFileManager (user_id or "me"; all pages)."""
        folder_path = kwargs.get("folder_path", "")
        recursive = kwargs.get("recursive", False)
        manager = OneDriveFileManager(user=kwargs.get("user_id") or "me", credentials=dict(self.credentials or {}))
        manager.adopt_client(client)
        try:
            self.logger.info(f"Listing OneDrive files in: {folder_path or 'root'}")
            if recursive:
                files = await self._list_recursive(manager, folder_path)
            else:
                files = [self._entry_dict(entry) for entry in await manager.list_entries(folder_path)]
            self.logger.info(f"Found {len(files)} items")
            return {
                "folder_path": folder_path or "root",
                "total_items": len(files),
                "files": files,
                "recursive": recursive,
            }

        except Exception as e:
            self.logger.error(f"Failed to list OneDrive files: {e}")
            raise
        finally:
            await manager.close()

    async def _list_recursive(self, manager: OneDriveFileManager, folder_path: str) -> List[Dict[str, Any]]:
        """Breadth-first listing of ``folder_path`` and every sub-folder (folders included, all pages)."""
        files: List[Dict[str, Any]] = []
        queue: List[str] = [folder_path]
        while queue:
            current_path = queue.pop(0)
            for entry in await manager.list_entries(current_path):
                files.append(self._entry_dict(entry))
                if entry.is_folder:
                    queue.append(entry.path)
        return files

    @staticmethod
    def _entry_dict(entry: Any) -> Dict[str, Any]:
        """Map a ``DriveEntry`` into the legacy OneDrive response shape."""
        return {
            "name": entry.name,
            "id": entry.id,
            "webUrl": entry.web_url,
            "path": entry.path,
            "isFolder": entry.is_folder,
            "size": entry.size or 0,
            "modified": entry.modified_at.isoformat() if entry.modified_at else None,
        }


# ============================================================================
# SEARCH ONEDRIVE FILES TOOL
# ============================================================================


class SearchOneDriveFilesArgs(O365ToolArgsSchema):
    """Arguments for searching OneDrive files."""

    query: str = Field(description="Search query (filename or content search)")
    max_results: int = Field(default=20, description="Maximum number of results to return (1-100)")


class SearchOneDriveFilesTool(O365Tool):
    """
    Tool for searching files in OneDrive.

    This tool searches for files in OneDrive by name or content.

    Examples:
        # Search by filename
        result = await tool.run(
            query="budget spreadsheet"
        )

        # Search with limit
        result = await tool.run(
            query="meeting notes",
            max_results=10
        )
    """

    name: str = "search_onedrive_files"
    description: str = (
        "Search for files in OneDrive by name or content. " "Returns matching files with their locations."
    )
    args_schema: Type[BaseModel] = SearchOneDriveFilesArgs

    async def _execute_graph_operation(self, client: O365Client, **kwargs) -> Dict[str, Any]:
        """Search OneDrive through OneDriveFileManager.find_entries (all pages; max_results after filtering)."""
        query = kwargs.get("query")
        max_results = min(kwargs.get("max_results", 20), 100)
        manager = OneDriveFileManager(user=kwargs.get("user_id") or "me", credentials=dict(self.credentials or {}))
        manager.adopt_client(client)
        try:
            self.logger.info(f"Searching OneDrive for: {query}")
            entries = await manager.find_entries(keywords=query)
            files = [ListOneDriveFilesTool._entry_dict(entry) for entry in entries[:max_results]]
            self.logger.info(f"Found {len(files)} matching files")
            return {"query": query, "total_results": len(files), "files": files}
        except Exception as e:
            self.logger.error(f"Failed to search OneDrive: {e}")
            raise
        finally:
            await manager.close()


# ============================================================================
# DOWNLOAD ONEDRIVE FILE TOOL
# ============================================================================


class DownloadOneDriveFileArgs(O365ToolArgsSchema):
    """Arguments for downloading OneDrive files."""

    file_path: Optional[str] = Field(
        default=None,
        description="Path to file in OneDrive (e.g., 'Documents/report.pdf'). " "Use either file_path or file_id.",
    )
    file_id: Optional[str] = Field(default=None, description="OneDrive file ID. Use either file_path or file_id.")
    local_destination: Optional[str] = Field(
        default=None, description="Local directory to save file. If not provided, saves to current directory."
    )
    rename_as: Optional[str] = Field(default=None, description="Rename file when downloading")


class DownloadOneDriveFileTool(O365Tool):
    """
    Tool for downloading files from OneDrive.

    This tool downloads a specific file from OneDrive to the local filesystem.
    Can identify files by path or ID.

    Examples:
        # Download by path
        result = await tool.run(
            file_path="Documents/report.pdf"
        )

        # Download by ID
        result = await tool.run(
            file_id="01ABCDEF1234567890"
        )

        # Download and rename
        result = await tool.run(
            file_path="Contracts/agreement.docx",
            rename_as="Client_Agreement.docx"
        )

        # Download to specific location
        result = await tool.run(
            file_path="Data/export.xlsx",
            local_destination="/tmp/downloads"
        )
    """

    name: str = "download_onedrive_file"
    description: str = (
        "Download a file from OneDrive to local storage. " "Supports renaming and custom destination paths."
    )
    args_schema: Type[BaseModel] = DownloadOneDriveFileArgs

    async def _execute_graph_operation(self, client: O365Client, **kwargs) -> Dict[str, Any]:
        """Download a OneDrive file by path or id through OneDriveFileManager (streamed to disk)."""
        file_path = kwargs.get("file_path")
        file_id = kwargs.get("file_id")
        local_destination = kwargs.get("local_destination")
        rename_as = kwargs.get("rename_as")
        if not file_path and not file_id:
            raise ValueError("Either file_path or file_id must be provided")
        dest_dir = Path(local_destination) if local_destination else Path.cwd()
        dest_dir.mkdir(parents=True, exist_ok=True)
        manager = OneDriveFileManager(user=kwargs.get("user_id") or "me", credentials=dict(self.credentials or {}))
        manager.adopt_client(client)
        try:
            if file_id:
                await manager._ready()
                item = await manager._get_item_by_id(file_id)
                file_path = manager._item_path(item) or item.name

            local = dest_dir / (rename_as or Path(file_path).name)
            await manager.download_file(file_path, local)
            if not file_id:
                file_id = (await manager._get_item(manager._prefixed(file_path))).id
            local_exists = await asyncio.to_thread(local.exists)
            return {
                "file_path": file_path,
                "file_id": file_id,
                "local_path": str(local),
                "size": (await asyncio.to_thread(local.stat)).st_size if local_exists else 0,
            }
        except Exception as e:
            self.logger.error(f"Failed to download OneDrive file: {e}")
            raise
        finally:
            await manager.close()


# ============================================================================
# UPLOAD ONEDRIVE FILE TOOL
# ============================================================================


class UploadOneDriveFileArgs(O365ToolArgsSchema):
    """Arguments for uploading files to OneDrive."""

    local_file_path: str = Field(description="Local file path to upload")
    folder_path: Optional[str] = Field(
        default="", description="Target folder path in OneDrive (e.g., 'Documents/Projects')"
    )
    rename_as: Optional[str] = Field(default=None, description="Rename file when uploading")


class UploadOneDriveFileTool(O365Tool):
    """
    Tool for uploading files to OneDrive.

    This tool uploads a local file to OneDrive.
    Supports folder creation and file renaming.

    Examples:
        # Upload to root
        result = await tool.run(
            local_file_path="/tmp/report.pdf"
        )

        # Upload to specific folder
        result = await tool.run(
            local_file_path="/data/export.xlsx",
            folder_path="Documents/Reports"
        )

        # Upload and rename
        result = await tool.run(
            local_file_path="/tmp/draft.docx",
            folder_path="Work",
            rename_as="Final_Document.docx"
        )
    """

    name: str = "upload_onedrive_file"
    description: str = "Upload a file to OneDrive. " "Creates folders as needed and supports file renaming."
    args_schema: Type[BaseModel] = UploadOneDriveFileArgs

    async def _execute_graph_operation(self, client: O365Client, **kwargs) -> Dict[str, Any]:
        """Upload a local file to OneDrive through OneDriveFileManager (rename = destination name)."""
        local_file_path = kwargs.get("local_file_path")
        folder_path = kwargs.get("folder_path", "")
        rename_as = kwargs.get("rename_as")
        local_path = Path(local_file_path)
        if not await asyncio.to_thread(local_path.exists):
            raise FileNotFoundError(f"Local file not found: {local_file_path}")
        manager = OneDriveFileManager(user=kwargs.get("user_id") or "me", credentials=dict(self.credentials or {}))
        manager.adopt_client(client)
        try:
            dest = f"{folder_path}/{rename_as or local_path.name}".strip("/")
            meta = await manager.upload_file(local_path, dest)
            item_id = (await manager._get_item(manager._prefixed(dest))).id
            return {
                "folder_path": folder_path or "root",
                "uploaded_file": meta.name,
                "file_id": item_id,
                "size": meta.size,
                "web_url": meta.url or "",
            }
        except Exception as e:
            self.logger.error(f"Failed to upload to OneDrive: {e}")
            raise
        finally:
            await manager.close()


# ============================================================================
# DELTA ONEDRIVE FILES TOOL
# ============================================================================


def _validate_graph_identifier(value: str, field: str) -> str:
    """Validate a configured Graph identifier before it becomes a URL segment.

    Graph drive/user identifiers are opaque strings, but a model-supplied
    value must never be allowed to expand into a different endpoint. Anything
    that looks like a URL, carries whitespace/control characters or is
    implausibly long is rejected outright.

    Args:
        value: The raw identifier.
        field: Field name, used in the error message.

    Returns:
        The stripped, validated identifier.

    Raises:
        ValueError: If the identifier is empty or not a plain Graph id.
    """
    if not value or not str(value).strip():
        raise ValueError(f"{field} must be a non-empty Microsoft Graph identifier")
    candidate = str(value).strip()
    if "://" in candidate or candidate.startswith("//"):
        raise ValueError(f"{field} must be a Graph identifier, not a URL: {candidate!r}")
    if any(ch.isspace() for ch in candidate) or any(ord(ch) < 32 for ch in candidate):
        raise ValueError(f"{field} must not contain whitespace or control characters")
    if len(candidate) > 512:
        raise ValueError(f"{field} is implausibly long ({len(candidate)} chars)")
    return candidate


class DeltaOneDriveFilesArgs(O365ToolArgsSchema):
    """Arguments for tracking OneDrive changes."""

    drive_id: Optional[str] = Field(
        default=None,
        description=(
            "Stable Graph drive identifier. When omitted, the drive of the "
            "target user (or of the signed-in user) is resolved."
        ),
    )
    folder_id: Optional[str] = Field(
        default=None,
        description=(
            "Stable Graph item id of the folder to restrict results to. This "
            "is the reliable folder filter (Graph delta reports "
            "parentReference.id but omits its path), though it matches direct "
            "children only."
        ),
    )
    folder_path: Optional[str] = Field(
        default=None,
        description=(
            "Drive-relative folder path to restrict results to (e.g. "
            "'Documents/Contracts'). Best-effort only: the Graph v1.0 delta API omits "
            "parentReference.path, so prefer folder_id. Items whose membership "
            "cannot be decided are kept and counted in unresolved_parent."
        ),
    )
    delta_link: Optional[str] = Field(
        default=None,
        description=(
            "Opaque delta cursor returned by a previous call. Omit for a full "
            "enumeration. The cursor is validated against the configured "
            "Microsoft Graph origin — and confined to this drive's delta "
            "endpoint — before any credential is forwarded."
        ),
    )
    delta_token: Optional[str] = Field(
        default=None,
        description=(
            "Alias of delta_link accepted for the contracts ingest job. " "delta_link wins when both are supplied."
        ),
    )
    max_pages: Optional[int] = Field(
        default=None, ge=1, le=DEFAULT_MAX_PAGES, description="Optional bound on delta pages followed in this call."
    )


class DeltaOneDriveFilesTool(O365Tool):
    """
    Tool for tracking changes in a OneDrive.

    Wraps the drive-level Microsoft Graph ``/delta`` feed: it returns the
    items that were added, modified, renamed or moved since the supplied
    cursor, plus tombstones for deleted items, and hands back a new opaque
    cursor to use on the next round.

    The tool is read-only and stateless: it never stores the returned cursor
    and never downloads file content. Persisting the cursor is the caller's
    responsibility, and it must only be persisted once every item has been
    durably processed.

    Examples:
        # First round: full enumeration of a folder subtree
        result = await tool.run(folder_path="Documents/Contracts")

        # Later rounds: incremental, resuming from the stored cursor
        result = await tool.run(
            folder_path="Documents/Contracts",
            delta_link=stored_cursor
        )

        # App-only access to a specific user's drive
        result = await tool.run(user_id="jane@contoso.com")
    """

    name: str = "delta_onedrive_files"
    description: str = (
        "Track changes (additions, edits, renames, moves and deletions) in a "
        "OneDrive since a previous delta cursor. Returns changed items, "
        "deleted-item tombstones and a new cursor."
    )
    args_schema: Type[BaseModel] = DeltaOneDriveFilesArgs

    def __init__(
        self,
        *args,
        delta_helper: Optional[DriveDeltaHelper] = None,
        strict_folder_scope: bool = True,
        **kwargs,
    ):
        """Initialize the OneDrive delta tool.

        Args:
            *args: Positional arguments forwarded to :class:`O365Tool`.
            delta_helper: Optional pre-configured drive delta helper, useful
                for tuning retry/backoff bounds or the trusted Graph origins.
            strict_folder_scope: When True (default), refuse to return
                results whose folder membership could not be decided under a
                folder-scoped request, rather than silently widening the
                scope to the whole drive.
            **kwargs: Keyword arguments forwarded to :class:`O365Tool`.
        """
        super().__init__(*args, **kwargs)
        self._delta_helper = delta_helper or DriveDeltaHelper()
        self.strict_folder_scope = strict_folder_scope

    async def _resolve_drive_id(self, client: O365Client, user_id: Optional[str]) -> str:
        """Resolve the drive identifier for the target OneDrive.

        Delegates identity selection to :meth:`O365Client.get_user_context`,
        the same convention the mail and calendar tools use. That resolver
        also honours a default target user configured in the credentials
        (``user_id`` / ``user_principal_name`` / ``mailbox`` / ``username``)
        and raises an actionable error for app-only auth with no identity,
        instead of falling back to ``/me`` and failing obscurely.

        Args:
            client: Authenticated O365 client.
            user_id: Per-call target user principal name / id, if any. It
                takes precedence over the configured default.

        Returns:
            The stable drive identifier.

        Raises:
            ValueError: If no target identity can be resolved, or Graph
                returned no usable drive.
        """
        validated_user = _validate_graph_identifier(user_id, "user_id") if user_id else None
        owner = client.get_user_context(user_id=validated_user)

        drive = await owner.drive.get()
        drive_id = getattr(drive, "id", None)
        if not drive_id:
            raise ValueError("Could not resolve a OneDrive drive identifier")
        return str(drive_id)

    async def _resolve_folder_id(self, client: O365Client, drive_id: str, folder_path: str) -> Optional[str]:
        """Resolve a drive-relative folder path to its stable item id.

        Graph's delta feed omits ``parentReference.path`` but reports
        ``parentReference.id``, so a path filter can only be applied exactly
        once the path has been turned into an id. Doing that here — rather
        than making every caller supply ``folder_id`` — is what keeps a
        folder-scoped request both exact and usable.

        Args:
            client: Authenticated O365 client.
            drive_id: Drive the folder lives in.
            folder_path: Drive-relative folder path.

        Returns:
            The folder's item id, or None when it could not be resolved
            (the caller then reports the scope as undecidable rather than
            silently widening it).
        """
        cleaned = folder_path.strip("/")
        if not cleaned:
            return None
        try:
            item = await (
                client.graph_client.drives.by_drive_id(drive_id).items.by_drive_item_id(f"root:/{cleaned}:").get()
            )
        except Exception as exc:  # noqa: BLE001 - undecidable, not fatal here
            self.logger.warning(
                "Could not resolve folder %r on drive %s: %s",
                folder_path,
                drive_id,
                exc,
            )
            return None
        resolved = getattr(item, "id", None)
        if not resolved:
            self.logger.warning("Folder %r on drive %s resolved to no item id", folder_path, drive_id)
            return None
        return str(resolved)

    async def _execute_graph_operation(self, client: O365Client, **kwargs) -> Dict[str, Any]:
        """Enumerate the drive's delta feed through the shared helper.

        Args:
            client: Authenticated O365Client instance.
            **kwargs: Tool parameters.

        Returns:
            Dict describing the changed items, tombstones and the new cursor.
        """
        drive_id = kwargs.get("drive_id")
        user_id = kwargs.get("user_id")
        folder_path = kwargs.get("folder_path") or None
        folder_id = kwargs.get("folder_id") or None
        # `delta_token` is the name the contracts ingest job (TASK-3049)
        # passes; accept it as an alias so that consumer resumes from its
        # committed cursor instead of silently re-enumerating the whole
        # drive on every run. This is a name, not a dependency: nothing in
        # this lane imports that package.
        delta_link = kwargs.get("delta_link") or kwargs.get("delta_token") or None
        max_pages = kwargs.get("max_pages")

        if drive_id:
            resolved_drive_id = _validate_graph_identifier(drive_id, "drive_id")
        else:
            resolved_drive_id = await self._resolve_drive_id(client, user_id)

        self.logger.info(
            "Tracking OneDrive delta for drive %s (folder=%s, incremental=%s)",
            resolved_drive_id,
            folder_path or "(whole drive)",
            delta_link is not None,
        )

        if folder_path and not folder_id:
            # Turn the path into an id so membership becomes decidable;
            # otherwise the delta feed gives us nothing to filter on.
            folder_id = await self._resolve_folder_id(client, resolved_drive_id, folder_path)

        enumeration = await self._delta_helper.enumerate(
            client,
            resolved_drive_id,
            delta_link=delta_link,
            folder_path=folder_path,
            folder_id=folder_id,
            max_pages=max_pages,
        )

        scope_requested = folder_path or folder_id
        if scope_requested and self.strict_folder_scope and not enumeration.folder_filter_reliable:
            # Graph omits parentReference.path from delta responses, so a
            # path-only filter usually cannot decide membership. Returning
            # the unfiltered drive under a folder-scoped request would let
            # unrelated documents into the caller's corpus, and the caller
            # cannot be relied on to inspect folder_filter_reliable. Fail
            # loudly and tell the operator how to make it decidable.
            raise ValueError(
                f"Folder scope {scope_requested!r} could not be applied to "
                f"{enumeration.unresolved_parent} of "
                f"{len(enumeration.items)} item(s): the Microsoft Graph "
                f"delta feed does not report a parent path. Pass folder_id "
                f"(the folder's stable item id) instead, or drop the folder "
                f"filter and scope the results in the caller. Set "
                f"strict_folder_scope=False to accept the unfiltered set."
            )

        payload = enumeration.model_dump(mode="json")
        # `path` is a derived property and `sha256` lives inside
        # content_hashes, so model_dump() omits both — yet the contracts
        # ingest job reads them per item (as a source-URI fallback and as
        # the content hash it persists). Project them explicitly.
        for serialized, item in zip(payload["items"], enumeration.items):
            serialized["path"] = item.path
            serialized["sha256"] = item.content_hashes.get("sha256Hash")
        payload.update(
            {
                "source": "onedrive",
                # Keys the contracts ingest job (TASK-3049) reads.
                "tombstones": [i.item_id for i in enumeration.deleted_items],
                "pages": enumeration.pages_fetched,
                # Inverse of `complete`, kept as an explicit key for parity
                # with the payload the core lane's tool emitted.
                "truncated": not enumeration.complete,
                # False by design: a 410 is recovered here by re-enumerating,
                # so the caller gets a completed full rescan rather than being
                # told to retry. `reset_performed` records that it happened.
                "rescan_required": False,
                # A @property, so model_dump() would otherwise drop it — tool
                # consumers need it to know whether the folder filter applied.
                "folder_filter_reliable": enumeration.folder_filter_reliable,
                "user_id": user_id,
                "total_items": len(enumeration.items),
                "changed_count": len(enumeration.changed_items),
                "deleted_count": len(enumeration.deleted_items),
            }
        )
        return payload


# ============================================================================
# EXPORT ALL ONEDRIVE TOOLS
# ============================================================================

__all__ = [
    "ListOneDriveFilesTool",
    "SearchOneDriveFilesTool",
    "DownloadOneDriveFileTool",
    "UploadOneDriveFileTool",
    "DeltaOneDriveFilesTool",
]
