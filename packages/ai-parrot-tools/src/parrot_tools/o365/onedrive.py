"""
OneDrive Tools for AI-Parrot.

Tools for interacting with OneDrive:
- List files in folders
- Search for files
- Download files
- Upload files
"""
from typing import Dict, Any, Optional, List, Type
from pathlib import Path
import shutil
from pydantic import BaseModel, Field
from .base import O365Tool, O365ToolArgsSchema
from ...interfaces.onedrive import OneDriveClient


# ============================================================================
# LIST ONEDRIVE FILES TOOL
# ============================================================================

class ListOneDriveFilesArgs(O365ToolArgsSchema):
    """Arguments for listing OneDrive files."""
    folder_path: Optional[str] = Field(
        default="",
        description="Folder path in OneDrive (e.g., 'Documents/Projects'). Empty for root."
    )
    recursive: bool = Field(
        default=False,
        description="Whether to list files recursively in subfolders"
    )


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
    description: str = (
        "List files in OneDrive folder. "
        "Returns file names, paths, sizes, and modification dates."
    )
    args_schema: Type[BaseModel] = ListOneDriveFilesArgs

    async def _execute_graph_operation(
        self,
        client: OneDriveClient,
        **kwargs
    ) -> Dict[str, Any]:
        """
        List OneDrive files using the OneDriveClient.

        Args:
            client: Authenticated OneDriveClient instance
            **kwargs: Tool parameters

        Returns:
            Dict with file listing
        """
        folder_path = kwargs.get('folder_path', '')
        recursive = kwargs.get('recursive', False)

        try:
            self.logger.info(f"Listing OneDrive files in: {folder_path or 'root'}")

            # Verify access
            await client.verify_onedrive_access()

            if recursive:
                # Recursive listing
                files = await self._list_recursive(client, folder_path)
            else:
                # Single level listing using the client's file_list method
                files = await client.file_list(folder_path)

            self.logger.info(f"Found {len(files)} items")

            return {
                "folder_path": folder_path or "root",
                "total_items": len(files),
                "files": files,
                "recursive": recursive
            }

        except Exception as e:
            self.logger.error(f"Failed to list OneDrive files: {e}")
            raise

    async def _list_recursive(
        self,
        client: OneDriveClient,
        folder_path: str
    ) -> List[Dict[str, Any]]:
        """Recursively list all files in a folder."""
        all_files = []

        # Get items in current folder
        items = await client.file_list(folder_path)

        for item in items:
            all_files.append(item)

            # Recurse into subfolders
            if item.get('isFolder'):
                subfolder_path = item.get('path', '')
                if subfolder_path:
                    subfolder_files = await self._list_recursive(client, subfolder_path)
                    all_files.extend(subfolder_files)

        return all_files


# ============================================================================
# SEARCH ONEDRIVE FILES TOOL
# ============================================================================

class SearchOneDriveFilesArgs(O365ToolArgsSchema):
    """Arguments for searching OneDrive files."""
    query: str = Field(
        description="Search query (filename or content search)"
    )
    max_results: int = Field(
        default=20,
        description="Maximum number of results to return (1-100)"
    )


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
        "Search for files in OneDrive by name or content. "
        "Returns matching files with their locations."
    )
    args_schema: Type[BaseModel] = SearchOneDriveFilesArgs

    async def _execute_graph_operation(
        self,
        client: OneDriveClient,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Search OneDrive files using the OneDriveClient.

        Args:
            client: Authenticated OneDriveClient instance
            **kwargs: Tool parameters

        Returns:
            Dict with search results
        """
        query = kwargs.get('query')
        max_results = min(kwargs.get('max_results', 20), 100)

        try:
            self.logger.info(f"Searching OneDrive for: {query}")

            # Verify access
            await client.verify_onedrive_access()

            # Perform search
            search_results = await client.file_search(query)

            # Limit results
            if len(search_results) > max_results:
                search_results = search_results[:max_results]

            self.logger.info(f"Found {len(search_results)} matching files")

            return {
                "query": query,
                "total_results": len(search_results),
                "files": search_results
            }

        except Exception as e:
            self.logger.error(f"Failed to search OneDrive: {e}")
            raise


# ============================================================================
# DOWNLOAD ONEDRIVE FILE TOOL
# ============================================================================

class DownloadOneDriveFileArgs(O365ToolArgsSchema):
    """Arguments for downloading OneDrive files."""
    file_path: Optional[str] = Field(
        default=None,
        description="Path to file in OneDrive (e.g., 'Documents/report.pdf'). "
                    "Use either file_path or file_id."
    )
    file_id: Optional[str] = Field(
        default=None,
        description="OneDrive file ID. Use either file_path or file_id."
    )
    local_destination: Optional[str] = Field(
        default=None,
        description="Local directory to save file. If not provided, saves to current directory."
    )
    rename_as: Optional[str] = Field(
        default=None,
        description="Rename file when downloading"
    )


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
        "Download a file from OneDrive to local storage. "
        "Supports renaming and custom destination paths."
    )
    args_schema: Type[BaseModel] = DownloadOneDriveFileArgs

    async def _execute_graph_operation(
        self,
        client: OneDriveClient,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Download OneDrive file using the OneDriveClient.

        Args:
            client: Authenticated OneDriveClient instance
            **kwargs: Tool parameters

        Returns:
            Dict with download details
        """
        file_path = kwargs.get('file_path')
        file_id = kwargs.get('file_id')
        local_destination = kwargs.get('local_destination')
        rename_as = kwargs.get('rename_as')

        try:
            if not file_path and not file_id:
                raise ValueError("Either file_path or file_id must be provided")

            # Set up download destination
            if local_destination:
                dest_dir = Path(local_destination)
            else:
                dest_dir = Path.cwd()

            dest_dir.mkdir(parents=True, exist_ok=True)

            # Verify access
            await client.verify_onedrive_access()

            if file_id:
                # Download by ID
                self.logger.info(f"Downloading OneDrive file ID: {file_id}")

                # Get file info first
                drive_info = await client._resolve_drive()
                item = await client.graph_client.drives.by_drive_id(drive_info.id)\
                    .items.by_drive_item_id(file_id).get()

                filename = rename_as or item.name
                destination = dest_dir / filename

                downloaded_path = await client.file_download(file_id, destination)

            else:
                # Download by path
                self.logger.info(f"Downloading OneDrive file: {file_path}")

                # Search for the file
                search_results = await client.file_search(file_path.split('/')[-1])

                # Find exact match
                matching_file = None
                for result in search_results:
                    if result.get('path', '').endswith(file_path):
                        matching_file = result
                        break

                if not matching_file:
                    raise FileNotFoundError(f"File not found: {file_path}")

                file_id = matching_file['id']
                filename = rename_as or matching_file['name']
                destination = dest_dir / filename

                downloaded_path = await client.file_download(file_id, destination)

            local_path = Path(downloaded_path)

            self.logger.info(f"Downloaded to: {local_path}")

            return {
                "file_path": file_path,
                "file_id": file_id,
                "local_path": str(local_path),
                "size": local_path.stat().st_size if local_path.exists() else 0
            }

        except Exception as e:
            self.logger.error(f"Failed to download OneDrive file: {e}")
            raise


# ============================================================================
# UPLOAD ONEDRIVE FILE TOOL
# ============================================================================

class UploadOneDriveFileArgs(O365ToolArgsSchema):
    """Arguments for uploading files to OneDrive."""
    local_file_path: str = Field(
        description="Local file path to upload"
    )
    folder_path: Optional[str] = Field(
        default="",
        description="Target folder path in OneDrive (e.g., 'Documents/Projects')"
    )
    rename_as: Optional[str] = Field(
        default=None,
        description="Rename file when uploading"
    )


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
    description: str = (
        "Upload a file to OneDrive. "
        "Creates folders as needed and supports file renaming."
    )
    args_schema: Type[BaseModel] = UploadOneDriveFileArgs

    async def _execute_graph_operation(
        self,
        client: OneDriveClient,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Upload file to OneDrive using the OneDriveClient.

        Args:
            client: Authenticated OneDriveClient instance
            **kwargs: Tool parameters

        Returns:
            Dict with upload details
        """
        local_file_path = kwargs.get('local_file_path')
        folder_path = kwargs.get('folder_path', '')
        rename_as = kwargs.get('rename_as')

        try:
            # Validate local file
            local_path = Path(local_file_path)
            if not local_path.exists():
                raise FileNotFoundError(f"Local file not found: {local_file_path}")

            self.logger.info(f"Uploading {local_path.name} to OneDrive:{folder_path or 'root'}")

            # Verify access
            await client.verify_onedrive_access()

            # If rename requested, we need to temporarily copy/rename
            if rename_as:
                # Create temporary renamed file
                temp_path = local_path.parent / rename_as
                shutil.copy2(local_path, temp_path)
                upload_path = temp_path
                cleanup_temp = True
            else:
                upload_path = local_path
                cleanup_temp = False

            try:
                # Upload file
                upload_result = await client.upload_file(
                    upload_path,
                    folder_path if folder_path else None
                )
            finally:
                # Clean up temporary file if created
                if cleanup_temp and temp_path.exists():
                    temp_path.unlink()

            self.logger.info(f"Uploaded successfully: {upload_result['name']}")

            return {
                "folder_path": folder_path or "root",
                "uploaded_file": upload_result['name'],
                "file_id": upload_result['id'],
                "size": upload_result['size'],
                "web_url": upload_result.get('webUrl', '')
            }

        except Exception as e:
            self.logger.error(f"Failed to upload to OneDrive: {e}")
            raise


# ============================================================================
# EXPORT ALL ONEDRIVE TOOLS
# ============================================================================

__all__ = [
    'ListOneDriveFilesTool',
    'SearchOneDriveFilesTool',
    'DownloadOneDriveFileTool',
    'UploadOneDriveFileTool'
]
