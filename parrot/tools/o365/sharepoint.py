"""
SharePoint Tools for AI-Parrot.

Tools for interacting with SharePoint document libraries:
- List files in folders
- Search for files
- Download files
- Upload files
"""
from typing import Dict, Any, Optional, List, Type
from pathlib import Path
from pydantic import BaseModel, Field

from .base import O365Tool, O365ToolArgsSchema
from ...interfaces.sharepoint import SharepointClient


# ============================================================================
# LIST SHAREPOINT FILES TOOL
# ============================================================================

class ListSharePointFilesArgs(O365ToolArgsSchema):
    """Arguments for listing SharePoint files."""
    site: str = Field(
        description="SharePoint site name (e.g., 'TeamSite', 'ProjectSite')"
    )
    library: Optional[str] = Field(
        default="Documents",
        description="Document library name (default: 'Documents')"
    )
    folder_path: Optional[str] = Field(
        default="",
        description="Folder path within the library (e.g., 'Project/Reports'). Empty for library root."
    )
    recursive: bool = Field(
        default=False,
        description="Whether to list files recursively in subfolders"
    )


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

    async def _execute_graph_operation(
        self,
        client: SharepointClient,
        **kwargs
    ) -> Dict[str, Any]:
        """
        List SharePoint files using the SharepointClient.

        Args:
            client: Authenticated SharepointClient instance
            **kwargs: Tool parameters

        Returns:
            Dict with file listing
        """
        site = kwargs.get('site')
        library = kwargs.get('library', 'Documents')
        folder_path = kwargs.get('folder_path', '')
        recursive = kwargs.get('recursive', False)

        try:
            # Configure client
            client.site = site
            client.credentials['tenant'] = site

            # Build full path
            full_path = f"{library}/{folder_path}".strip('/') if folder_path else library

            self.logger.info(f"Listing files in: {site}/{full_path}")

            # Resolve site and drive
            await client.verify_sharepoint_access()
            drive_info = await client._resolve_drive(library)

            # Get folder contents
            if folder_path:
                folder_item = await client.graph_client.drives.by_drive_id(drive_info.id)\
                    .items.by_drive_item_id(f"root:/{folder_path}:").get()
            else:
                folder_item = await client.graph_client.drives.by_drive_id(drive_info.id).root.get()

            files = []

            if recursive:
                # Recursive listing
                files = await self._list_recursive(
                    client,
                    drive_info.id,
                    folder_item.id,
                    folder_path
                )
            else:
                # Single level listing
                children = await client.graph_client.drives.by_drive_id(drive_info.id)\
                    .items.by_drive_item_id(folder_item.id).children.get()

                if children and children.value:
                    for item in children.value:
                        file_info = {
                            "name": item.name,
                            "path": f"{folder_path}/{item.name}".strip('/'),
                            "is_folder": item.folder is not None,
                            "size": item.size or 0,
                            "modified": item.last_modified_date_time.isoformat() if item.last_modified_date_time else None,
                            "web_url": item.web_url,
                            "id": item.id
                        }
                        files.append(file_info)

            self.logger.info(f"Found {len(files)} items")

            return {
                "site": site,
                "library": library,
                "folder_path": folder_path,
                "total_items": len(files),
                "files": files,
                "recursive": recursive
            }

        except Exception as e:
            self.logger.error(f"Failed to list SharePoint files: {e}")
            raise

    async def _list_recursive(
        self,
        client: SharepointClient,
        drive_id: str,
        folder_id: str,
        base_path: str
    ) -> List[Dict[str, Any]]:
        """Recursively list all files in a folder."""
        files = []

        children = await client.graph_client.drives.by_drive_id(drive_id)\
            .items.by_drive_item_id(folder_id).children.get()

        if children and children.value:
            for item in children.value:
                item_path = f"{base_path}/{item.name}".strip('/')

                file_info = {
                    "name": item.name,
                    "path": item_path,
                    "is_folder": item.folder is not None,
                    "size": item.size or 0,
                    "modified": item.last_modified_date_time.isoformat() if item.last_modified_date_time else None,
                    "web_url": item.web_url,
                    "id": item.id
                }
                files.append(file_info)

                # Recurse into folders
                if item.folder:
                    subfolder_files = await self._list_recursive(
                        client,
                        drive_id,
                        item.id,
                        item_path
                    )
                    files.extend(subfolder_files)

        return files


# ============================================================================
# SEARCH SHAREPOINT FILES TOOL
# ============================================================================

class SearchSharePointFilesArgs(O365ToolArgsSchema):
    """Arguments for searching SharePoint files."""
    site: str = Field(
        description="SharePoint site name"
    )
    query: str = Field(
        description="Search query (filename or content search)"
    )
    library: Optional[str] = Field(
        default="Documents",
        description="Document library to search in"
    )
    folder_path: Optional[str] = Field(
        default="",
        description="Limit search to specific folder path"
    )
    file_extension: Optional[str] = Field(
        default=None,
        description="Filter by file extension (e.g., 'pdf', 'docx')"
    )
    max_results: int = Field(
        default=20,
        description="Maximum number of results to return (1-100)"
    )


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
        "Search for files in SharePoint by name or content. "
        "Supports filtering by file type and location."
    )
    args_schema: Type[BaseModel] = SearchSharePointFilesArgs

    async def _execute_graph_operation(
        self,
        client: SharepointClient,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Search SharePoint files using the SharepointClient.

        Args:
            client: Authenticated SharepointClient instance
            **kwargs: Tool parameters

        Returns:
            Dict with search results
        """
        site = kwargs.get('site')
        query = kwargs.get('query')
        library = kwargs.get('library', 'Documents')
        folder_path = kwargs.get('folder_path', '')
        file_extension = kwargs.get('file_extension')
        max_results = min(kwargs.get('max_results', 20), 100)

        try:
            # Configure client
            client.site = site
            client.credentials['tenant'] = site

            self.logger.info(f"Searching SharePoint for: {query}")

            # Configure search spec
            client._srcfiles = [{
                'directory': f"{library}/{folder_path}".strip('/'),
                'pattern': query,
                'extension': file_extension
            }]

            # Verify access and perform search
            await client.verify_sharepoint_access()
            search_results = await client.file_search()

            # Limit results
            if len(search_results) > max_results:
                search_results = search_results[:max_results]

            # Format results
            files = []
            for result in search_results:
                if item := result.get('item'):
                    file_info = {
                        "name": item.name,
                        "path": result.get('path', ''),
                        "size": item.size or 0,
                        "modified": item.last_modified_date_time.isoformat() if item.last_modified_date_time else None,
                        "web_url": item.web_url,
                        "id": item.id
                    }
                    files.append(file_info)

            self.logger.info(f"Found {len(files)} matching files")

            return {
                "site": site,
                "query": query,
                "library": library,
                "folder_path": folder_path,
                "file_extension": file_extension,
                "total_results": len(files),
                "files": files
            }

        except Exception as e:
            self.logger.error(f"Failed to search SharePoint: {e}")
            raise


# ============================================================================
# DOWNLOAD SHAREPOINT FILE TOOL
# ============================================================================

class DownloadSharePointFileArgs(O365ToolArgsSchema):
    """Arguments for downloading SharePoint files."""
    site: str = Field(
        description="SharePoint site name"
    )
    library: str = Field(
        default="Documents",
        description="Document library name"
    )
    file_path: str = Field(
        description="Path to file within library (e.g., 'Reports/Q4_Report.pdf')"
    )
    local_destination: Optional[str] = Field(
        default=None,
        description="Local path to save file. If not provided, saves to current directory."
    )
    rename_as: Optional[str] = Field(
        default=None,
        description="Rename file when downloading"
    )


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
        "Download a file from SharePoint to local storage. "
        "Supports renaming and custom destination paths."
    )
    args_schema: Type[BaseModel] = DownloadSharePointFileArgs

    async def _execute_graph_operation(
        self,
        client: SharepointClient,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Download SharePoint file using the SharepointClient.

        Args:
            client: Authenticated SharepointClient instance
            **kwargs: Tool parameters

        Returns:
            Dict with download details
        """
        site = kwargs.get('site')
        library = kwargs.get('library', 'Documents')
        file_path = kwargs.get('file_path')
        local_destination = kwargs.get('local_destination')
        rename_as = kwargs.get('rename_as')

        try:
            # Configure client
            client.site = site
            client.credentials['tenant'] = site

            # Parse file path
            path_parts = file_path.rsplit('/', 1)
            if len(path_parts) == 2:
                folder_path, filename = path_parts
            else:
                folder_path = ""
                filename = file_path

            full_directory = f"{library}/{folder_path}".strip('/')

            self.logger.info(f"Downloading: {site}/{full_directory}/{filename}")

            # Set up download destination
            dest_dir = Path(local_destination) if local_destination else Path.cwd()

            dest_dir.mkdir(parents=True, exist_ok=True)
            client.directory = str(dest_dir)

            # Configure file lookup
            client._srcfiles = [{
                'directory': full_directory,
                'filename': filename
            }]

            # Set rename if requested
            if rename_as:
                client._filenames = [rename_as]

            # Verify access
            await client.verify_sharepoint_access()

            # Find file
            found_files = await client.file_lookup()

            if not found_files:
                raise FileNotFoundError(f"File not found: {file_path}")

            # Download files
            downloaded = await client.download_found_files(found_files)

            if not downloaded:
                raise RuntimeError("Download failed")

            download_info = downloaded[0]
            local_path = download_info['filename']

            self.logger.info(f"Downloaded to: {local_path}")

            return {
                "site": site,
                "library": library,
                "file_path": file_path,
                "local_path": local_path,
                "download_url": download_info.get('download_url', ''),
                "size": Path(local_path).stat().st_size if Path(local_path).exists() else 0
            }

        except Exception as e:
            self.logger.error(f"Failed to download SharePoint file: {e}")
            raise


# ============================================================================
# UPLOAD SHAREPOINT FILE TOOL
# ============================================================================

class UploadSharePointFileArgs(O365ToolArgsSchema):
    """Arguments for uploading files to SharePoint."""
    site: str = Field(
        description="SharePoint site name"
    )
    local_file_path: str = Field(
        description="Local file path to upload"
    )
    library: str = Field(
        default="Documents",
        description="Target document library"
    )
    folder_path: Optional[str] = Field(
        default="",
        description="Target folder path within library (e.g., 'Reports/2025')"
    )
    rename_as: Optional[str] = Field(
        default=None,
        description="Rename file when uploading"
    )
    overwrite: bool = Field(
        default=True,
        description="Whether to overwrite existing files"
    )


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
        "Upload a file to SharePoint document library. "
        "Creates folders as needed and supports file renaming."
    )
    args_schema: Type[BaseModel] = UploadSharePointFileArgs

    async def _execute_graph_operation(
        self,
        client: SharepointClient,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Upload file to SharePoint using the SharepointClient.

        Args:
            client: Authenticated SharepointClient instance
            **kwargs: Tool parameters

        Returns:
            Dict with upload details
        """
        site = kwargs.get('site')
        local_file_path = kwargs.get('local_file_path')
        library = kwargs.get('library', 'Documents')
        folder_path = kwargs.get('folder_path', '')
        rename_as = kwargs.get('rename_as')
        overwrite = kwargs.get('overwrite', True)

        try:
            # Validate local file
            local_path = Path(local_file_path)
            if not local_path.exists():
                raise FileNotFoundError(f"Local file not found: {local_file_path}")

            # Configure client
            client.site = site
            client.credentials['tenant'] = site

            # Build destination path
            destination = f"{library}/{folder_path}".strip('/')

            self.logger.info(f"Uploading {local_path.name} to {site}/{destination}")

            # Verify access
            await client.verify_sharepoint_access()

            # Upload file
            filenames = [local_path]
            destination_filenames = [rename_as] if rename_as else None

            upload_results = await client.upload_files(
                filenames=filenames,
                destination=destination,
                destination_filenames=destination_filenames
            )

            if not upload_results:
                raise RuntimeError("Upload failed")

            result = upload_results[0]['filename']

            self.logger.info(f"Uploaded successfully: {result['name']}")

            return {
                "site": site,
                "library": library,
                "folder_path": folder_path,
                "uploaded_file": result['name'],
                "size": result['size'],
                "web_url": result.get('web_url', ''),
                "server_relative_url": result.get('serverRelativeUrl', '')
            }

        except Exception as e:
            self.logger.error(f"Failed to upload to SharePoint: {e}")
            raise


# ============================================================================
# EXPORT ALL SHAREPOINT TOOLS
# ============================================================================

__all__ = [
    'ListSharePointFilesTool',
    'SearchSharePointFilesTool',
    'DownloadSharePointFileTool',
    'UploadSharePointFileTool'
]
