"""
SharePoint Tools for AI-Parrot.

Tools for interacting with SharePoint document libraries:
- List files in folders
- Search for files
- Download files
- Upload files
"""

import asyncio
from typing import Dict, Any, Optional, List, Type
from pathlib import Path
from urllib.parse import urlsplit
from pydantic import BaseModel, Field

from .base import O365Tool, O365ToolArgsSchema
from .delta import DEFAULT_MAX_PAGES, DriveDeltaHelper
from parrot.interfaces.o365 import O365Client
from parrot.interfaces.file.sharepoint import SharePointFileManager

# ============================================================================
# LIST SHAREPOINT FILES TOOL
# ============================================================================


class ListSharePointFilesArgs(O365ToolArgsSchema):
    """Arguments for listing SharePoint files."""

    site: str = Field(description="SharePoint site name (e.g., 'TeamSite', 'ProjectSite')")
    library: Optional[str] = Field(default="Documents", description="Document library name (default: 'Documents')")
    folder_path: Optional[str] = Field(
        default="", description="Folder path within the library (e.g., 'Project/Reports'). Empty for library root."
    )
    recursive: bool = Field(default=False, description="Whether to list files recursively in subfolders")


class ListSharePointFilesTool(O365Tool):
    """
    Tool for listing files in SharePoint document libraries.

    This tool lists all files in a specified SharePoint location, with options
    for recursive listing and filtering by file type.

    Examples:
        # List files in root of Documents library
        result = await tool.run(
            site="TeamSite",
            library="Documents"
        )

        # List files in specific folder
        result = await tool.run(
            site="ProjectSite",
            library="Documents",
            folder_path="Reports/2025"
        )

        # Recursive listing
        result = await tool.run(
            site="TeamSite",
            folder_path="Project Management",
            recursive=True
        )
    """

    name: str = "list_sharepoint_files"
    description: str = (
        "List files in a SharePoint document library or folder. "
        "Returns file names, paths, sizes, and modification dates."
    )
    args_schema: Type[BaseModel] = ListSharePointFilesArgs

    async def _execute_graph_operation(self, client: O365Client, **kwargs) -> Dict[str, Any]:
        """List SharePoint files through SharePointFileManager (one authentication, all pages)."""
        site = kwargs.get("site")
        library = kwargs.get("library", "Documents")
        folder_path = kwargs.get("folder_path", "")
        recursive = kwargs.get("recursive", False)
        manager = SharePointFileManager(site=site, library=library, credentials=dict(self.credentials or {}))
        manager.adopt_client(client)
        try:
            self.logger.info(f"Listing files in: {site}/{library}/{folder_path}".rstrip("/"))
            if recursive:
                files = await self._list_recursive(manager, folder_path)
            else:
                files = [self._entry_dict(e) for e in await manager.list_entries(folder_path)]
            self.logger.info(f"Found {len(files)} items")
            return {
                "site": site,
                "library": library,
                "folder_path": folder_path,
                "total_items": len(files),
                "files": files,
                "recursive": recursive,
            }
        except Exception as e:
            self.logger.error(f"Failed to list SharePoint files: {e}")
            raise
        finally:
            await manager.close()

    async def _list_recursive(self, manager: SharePointFileManager, base_path: str) -> List[Dict[str, Any]]:
        """Breadth-first listing of ``base_path`` and every sub-folder (folders included, all pages)."""
        files: List[Dict[str, Any]] = []
        queue: List[str] = [base_path]
        while queue:
            current_path = queue.pop(0)
            for entry in await manager.list_entries(current_path):
                files.append(self._entry_dict(entry))
                if entry.is_folder:
                    queue.append(entry.path)
        return files

    @staticmethod
    def _entry_dict(entry: Any) -> Dict[str, Any]:
        """Map a ``DriveEntry`` into the tool's list-response file dict."""
        return {
            "name": entry.name,
            "path": entry.path,
            "is_folder": entry.is_folder,
            "size": entry.size or 0,
            "modified": entry.modified_at.isoformat() if entry.modified_at else None,
            "web_url": entry.web_url,
            "id": entry.id,
        }


# ============================================================================
# SEARCH SHAREPOINT FILES TOOL
# ============================================================================


class SearchSharePointFilesArgs(O365ToolArgsSchema):
    """Arguments for searching SharePoint files."""

    site: str = Field(description="SharePoint site name")
    query: str = Field(description="Search query (filename or content search)")
    library: Optional[str] = Field(default="Documents", description="Document library to search in")
    folder_path: Optional[str] = Field(default="", description="Limit search to specific folder path")
    file_extension: Optional[str] = Field(default=None, description="Filter by file extension (e.g., 'pdf', 'docx')")
    max_results: int = Field(default=20, description="Maximum number of results to return (1-100)")


class SearchSharePointFilesTool(O365Tool):
    """
    Tool for searching files in SharePoint.

    This tool searches for files in SharePoint by name, content, or metadata.
    Supports filtering by file type and location.

    Examples:
        # Search by filename
        result = await tool.run(
            site="TeamSite",
            query="quarterly report"
        )

        # Search for PDFs only
        result = await tool.run(
            site="ProjectSite",
            query="invoice",
            file_extension="pdf"
        )

        # Search in specific folder
        result = await tool.run(
            site="TeamSite",
            query="meeting notes",
            folder_path="Project/Meetings"
        )
    """

    name: str = "search_sharepoint_files"
    description: str = (
        "Search for files in SharePoint by name or content. " "Supports filtering by file type and location."
    )
    args_schema: Type[BaseModel] = SearchSharePointFilesArgs

    async def _execute_graph_operation(self, client: O365Client, **kwargs) -> Dict[str, Any]:
        """Search SharePoint files through SharePointFileManager.find_entries (all pages; max_results after filtering)."""
        site = kwargs.get("site")
        query = kwargs.get("query")
        library = kwargs.get("library", "Documents")
        folder_path = kwargs.get("folder_path", "")
        file_extension = kwargs.get("file_extension")
        max_results = min(kwargs.get("max_results", 20), 100)
        manager = SharePointFileManager(site=site, library=library, credentials=dict(self.credentials or {}))
        manager.adopt_client(client)
        try:
            self.logger.info(f"Searching SharePoint for: {query}")
            extension = f".{file_extension.lstrip('.')}" if file_extension else None
            entries = await manager.find_entries(keywords=query, extension=extension, prefix=folder_path or None)
            entries = entries[:max_results]
            files = [
                {
                    "name": entry.name,
                    "path": entry.path,
                    "size": entry.size or 0,
                    "modified": entry.modified_at.isoformat() if entry.modified_at else None,
                    "web_url": entry.web_url,
                    "id": entry.id,
                }
                for entry in entries
            ]
            self.logger.info(f"Found {len(files)} matching files")
            return {
                "site": site,
                "query": query,
                "library": library,
                "folder_path": folder_path,
                "file_extension": file_extension,
                "total_results": len(files),
                "files": files,
            }
        except Exception as e:
            self.logger.error(f"Failed to search SharePoint: {e}")
            raise
        finally:
            await manager.close()


# ============================================================================
# DOWNLOAD SHAREPOINT FILE TOOL
# ============================================================================


class DownloadSharePointFileArgs(O365ToolArgsSchema):
    """Arguments for downloading SharePoint files."""

    site: str = Field(description="SharePoint site name")
    library: str = Field(default="Documents", description="Document library name")
    file_path: str = Field(description="Path to file within library (e.g., 'Reports/Q4_Report.pdf')")
    local_destination: Optional[str] = Field(
        default=None, description="Local path to save file. If not provided, saves to current directory."
    )
    rename_as: Optional[str] = Field(default=None, description="Rename file when downloading")


class DownloadSharePointFileTool(O365Tool):
    """
    Tool for downloading files from SharePoint.

    This tool downloads a specific file from SharePoint to the local filesystem.

    Examples:
        # Download to current directory
        result = await tool.run(
            site="TeamSite",
            library="Documents",
            file_path="Reports/Q4_Report.pdf"
        )

        # Download and rename
        result = await tool.run(
            site="ProjectSite",
            file_path="Contracts/Agreement.docx",
            rename_as="Client_Agreement.docx"
        )

        # Download to specific location
        result = await tool.run(
            site="TeamSite",
            file_path="Data/export.xlsx",
            local_destination="/tmp/downloads"
        )
    """

    name: str = "download_sharepoint_file"
    description: str = (
        "Download a file from SharePoint to local storage. " "Supports renaming and custom destination paths."
    )
    args_schema: Type[BaseModel] = DownloadSharePointFileArgs

    async def _execute_graph_operation(self, client: O365Client, **kwargs) -> Dict[str, Any]:
        """
        Download a SharePoint file through SharePointFileManager (streamed to disk).

        Args:
            client: Authenticated O365Client instance
            **kwargs: Tool parameters

        Returns:
            Dict with download details
        """
        site = kwargs.get("site")
        library = kwargs.get("library", "Documents")
        file_path = kwargs.get("file_path")
        local_destination = kwargs.get("local_destination")
        rename_as = kwargs.get("rename_as")

        manager = SharePointFileManager(site=site, library=library, credentials=dict(self.credentials or {}))
        manager.adopt_client(client)
        try:
            self.logger.info(f"Downloading: {site}/{library}/{file_path}")

            # Set up download destination
            dest_dir = Path(local_destination) if local_destination else Path.cwd()
            dest_dir.mkdir(parents=True, exist_ok=True)
            local_path = dest_dir / (rename_as or file_path.rsplit("/", 1)[-1])

            await manager.download_file(file_path, local_path)
            meta = await manager.get_file_metadata(file_path)

            self.logger.info(f"Downloaded to: {local_path}")

            return {
                "site": site,
                "library": library,
                "file_path": file_path,
                "local_path": str(local_path),
                "download_url": meta.url or "",
                "size": local_path.stat().st_size if local_path.exists() else 0,
            }

        except Exception as e:
            self.logger.error(f"Failed to download SharePoint file: {e}")
            raise
        finally:
            await manager.close()


# ============================================================================
# UPLOAD SHAREPOINT FILE TOOL
# ============================================================================


class UploadSharePointFileArgs(O365ToolArgsSchema):
    """Arguments for uploading files to SharePoint."""

    site: str = Field(description="SharePoint site name")
    local_file_path: str = Field(description="Local file path to upload")
    library: str = Field(default="Documents", description="Target document library")
    folder_path: Optional[str] = Field(
        default="", description="Target folder path within library (e.g., 'Reports/2025')"
    )
    rename_as: Optional[str] = Field(default=None, description="Rename file when uploading")
    overwrite: bool = Field(default=True, description="Whether to overwrite existing files")


class UploadSharePointFileTool(O365Tool):
    """
    Tool for uploading files to SharePoint.

    This tool uploads a local file to a SharePoint document library.
    Supports folder creation and file renaming.

    Examples:
        # Upload to library root
        result = await tool.run(
            site="TeamSite",
            local_file_path="/tmp/report.pdf"
        )

        # Upload to specific folder
        result = await tool.run(
            site="ProjectSite",
            local_file_path="/data/export.xlsx",
            folder_path="Reports/2025"
        )

        # Upload and rename
        result = await tool.run(
            site="TeamSite",
            local_file_path="/tmp/draft.docx",
            folder_path="Contracts",
            rename_as="Final_Agreement.docx"
        )
    """

    name: str = "upload_sharepoint_file"
    description: str = (
        "Upload a file to SharePoint document library. " "Creates folders as needed and supports file renaming."
    )
    args_schema: Type[BaseModel] = UploadSharePointFileArgs

    async def _execute_graph_operation(self, client: O365Client, **kwargs) -> Dict[str, Any]:
        """
        Upload a local file to SharePoint through SharePointFileManager (single PUT or upload session).

        Args:
            client: Authenticated O365Client instance
            **kwargs: Tool parameters

        Returns:
            Dict with upload details
        """
        site = kwargs.get("site")
        local_file_path = kwargs.get("local_file_path")
        library = kwargs.get("library", "Documents")
        folder_path = kwargs.get("folder_path", "")
        rename_as = kwargs.get("rename_as")
        overwrite = kwargs.get("overwrite", True)

        # Validate local file
        local_path = Path(local_file_path)
        if not await asyncio.to_thread(local_path.exists):
            raise FileNotFoundError(f"Local file not found: {local_file_path}")

        manager = SharePointFileManager(
            site=site,
            library=library,
            credentials=dict(self.credentials or {}),
            conflict_behavior="replace" if overwrite else "fail",
        )
        manager.adopt_client(client)
        try:
            destination = f"{folder_path}/{rename_as or local_path.name}".strip("/")

            self.logger.info(f"Uploading {local_path.name} to {site}/{library}/{destination}")

            meta = await manager.upload_file(local_path, destination)

            self.logger.info(f"Uploaded successfully: {meta.name}")

            return {
                "site": site,
                "library": library,
                "folder_path": folder_path,
                "uploaded_file": meta.name,
                "size": meta.size,
                "web_url": meta.url or "",
                "server_relative_url": urlsplit(meta.url).path if meta.url else "",
            }

        except Exception as e:
            self.logger.error(f"Failed to upload to SharePoint: {e}")
            raise
        finally:
            await manager.close()


# ============================================================================
# DELTA SHAREPOINT FILES TOOL
# ============================================================================


def _validate_graph_identifier(value: str, field: str) -> str:
    """Validate a configured Graph identifier before it becomes a URL segment.

    Graph site/drive identifiers are opaque strings, but a model-supplied
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


class DeltaSharePointFilesArgs(O365ToolArgsSchema):
    """Arguments for tracking SharePoint document-library changes."""

    site_id: Optional[str] = Field(
        default=None,
        description=(
            "Microsoft Graph site identifier (e.g. "
            "'contoso.sharepoint.com,<site-guid>,<web-guid>' or "
            "'contoso.sharepoint.com:/sites/TeamSite'). Required unless "
            "drive_id is supplied. Must be an identifier, never a URL."
        ),
    )
    library: Optional[str] = Field(
        default="Documents", description="Document library (drive) name to track. Default: 'Documents'."
    )
    drive_id: Optional[str] = Field(
        default=None,
        description=(
            "Stable Graph drive identifier. When supplied, the library lookup "
            "is skipped and this drive is tracked directly."
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
            "Library-relative folder path to restrict results to (e.g. "
            "'Contracts/2026'). Best-effort only: the Graph v1.0 delta API omits "
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


class DeltaSharePointFilesTool(O365Tool):
    """
    Tool for tracking changes in a SharePoint document library.

    Wraps the drive-level Microsoft Graph ``/delta`` feed: it returns the
    items that were added, modified, renamed or moved since the supplied
    cursor, plus tombstones for deleted items, and hands back a new opaque
    cursor to use on the next round.

    The tool is read-only and stateless: it never stores the returned cursor
    and never downloads file content. Persisting the cursor is the caller's
    responsibility, and it must only be persisted once every item has been
    durably processed.

    Examples:
        # First round: full enumeration of a library subtree
        result = await tool.run(
            site_id="contoso.sharepoint.com:/sites/Legal",
            library="Documents",
            folder_path="Contracts"
        )

        # Later rounds: incremental, resuming from the stored cursor
        result = await tool.run(
            site_id="contoso.sharepoint.com:/sites/Legal",
            library="Documents",
            folder_path="Contracts",
            delta_link=stored_cursor
        )
    """

    name: str = "delta_sharepoint_files"
    description: str = (
        "Track changes (additions, edits, renames, moves and deletions) in a "
        "SharePoint document library since a previous delta cursor. Returns "
        "changed items, deleted-item tombstones and a new cursor."
    )
    args_schema: Type[BaseModel] = DeltaSharePointFilesArgs

    def __init__(
        self,
        *args,
        delta_helper: Optional[DriveDeltaHelper] = None,
        strict_folder_scope: bool = True,
        **kwargs,
    ):
        """Initialize the SharePoint delta tool.

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

    async def _resolve_library_drive_id(self, client: O365Client, site_id: str, library: Optional[str]) -> str:
        """Resolve a document library name to its stable Graph drive id.

        Args:
            client: Authenticated O365 client.
            site_id: Validated Graph site identifier.
            library: Library (drive) display name, or None to accept the
                site's only drive.

        Returns:
            The stable drive identifier.

        Raises:
            ValueError: If the site exposes no drives, or the named library
                does not exist, or the site is ambiguous with no library name.
        """
        drives = await client.graph_client.sites.by_site_id(site_id).drives.get()
        available = list(getattr(drives, "value", None) or [])
        # The drives collection is pageable. This lookup deliberately reads
        # only the first page, so it must never conclude "absent" or "unique"
        # from a truncated listing — it asks for an explicit drive_id instead.
        truncated = bool(getattr(drives, "odata_next_link", None))

        if not available:
            raise ValueError(f"SharePoint site {site_id!r} exposes no drives")

        if library:
            wanted = library.strip().lower()
            for drive in available:
                if (drive.name or "").strip().lower() == wanted:
                    return str(drive.id)
            if truncated:
                raise ValueError(
                    f"Document library {library!r} was not on the first page of "
                    f"libraries for site {site_id!r}; supply an explicit "
                    f"drive_id. First page: {[d.name for d in available]}"
                )
            raise ValueError(
                f"Document library {library!r} not found on site {site_id!r}. "
                f"Available: {[d.name for d in available]}"
            )

        if truncated or len(available) > 1:
            raise ValueError(
                f"Site {site_id!r} exposes multiple libraries; specify one of "
                f"{[d.name for d in available]}" + (" (list truncated — more pages exist)" if truncated else "")
            )
        return str(available[0].id)

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
        """Enumerate the library's delta feed through the shared helper.

        Args:
            client: Authenticated O365Client instance.
            **kwargs: Tool parameters.

        Returns:
            Dict describing the changed items, tombstones and the new cursor.
        """
        site_id = kwargs.get("site_id")
        library = kwargs.get("library", "Documents")
        drive_id = kwargs.get("drive_id")
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
            if not site_id:
                raise ValueError("Either site_id or drive_id must be provided to track " "SharePoint changes")
            resolved_drive_id = await self._resolve_library_drive_id(
                client, _validate_graph_identifier(site_id, "site_id"), library
            )

        self.logger.info(
            "Tracking SharePoint delta for drive %s (library=%s, folder=%s, " "incremental=%s)",
            resolved_drive_id,
            library,
            folder_path or "(whole library)",
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
        for serialized, item in zip(payload["items"], enumeration.items, strict=True):
            serialized["path"] = item.path
            serialized["sha256"] = item.content_hashes.get("sha256Hash")
        payload.update(
            {
                "source": "sharepoint",
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
                "site_id": site_id,
                "library": library,
                "total_items": len(enumeration.items),
                "changed_count": len(enumeration.changed_items),
                "deleted_count": len(enumeration.deleted_items),
            }
        )
        return payload


# ============================================================================
# EXPORT ALL SHAREPOINT TOOLS
# ============================================================================

__all__ = [
    "ListSharePointFilesTool",
    "SearchSharePointFilesTool",
    "DownloadSharePointFileTool",
    "UploadSharePointFileTool",
    "DeltaSharePointFilesTool",
]
