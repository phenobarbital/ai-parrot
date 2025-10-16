import os
from typing import List, Optional, Union, Dict, Any
import contextlib
from pathlib import Path
from urllib.parse import quote, unquote
import asyncio
import aiofiles
from tqdm import tqdm
from io import BytesIO
import httpx
import aiohttp
import pandas as pd
# Microsoft Graph SDK
from msgraph.generated.models.drive_item import DriveItem
from msgraph.generated.models.folder import Folder
from msgraph.generated.models.file import File
from msgraph.generated.models.upload_session import UploadSession
from msgraph.generated.drives.item.items.item.create_upload_session.create_upload_session_post_request_body import (
    CreateUploadSessionPostRequestBody
)
from msgraph.generated.models.drive_item_uploadable_properties import DriveItemUploadableProperties
from .o365 import O365Client


class OneDriveClient(O365Client):
    """
    OneDrive Client - Migrated to Microsoft Graph SDK

    Uses Microsoft Graph SDK for all OneDrive operations.

    Interface for Managing connections to OneDrive resources.

    Methods:
        file_list: Lists files in a specified OneDrive folder.
        file_search: Searches for files matching a query.
        file_download: Downloads a single file by its item ID.
        download_files: Downloads multiple files provided as a list of dictionaries containing file info.
        folder_download: Downloads a folder and its contents recursively.
        file_delete: Deletes a file or folder by its item ID.
        upload_files: Uploads multiple files to a specified OneDrive folder.
        upload_file: Uploads a single file to OneDrive.
        upload_folder: Uploads a local folder and its contents to OneDrive recursively.
        download_excel_file: Downloads Excel files and optionally converts to pandas DataFrame.
        upload_dataframe_as_excel: Uploads pandas DataFrame as Excel file to OneDrive.

    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # OneDrive-specific properties
        self.directory: Optional[str] = None
        self.filename: Optional[str] = None
        self._srcfiles: List = []
        self._destination: List = []

        # Upload settings
        self.small_file_threshold = 4 * 1024 * 1024  # 4 MB
        self.chunk_size = 10 * 1024 * 1024  # 10 MB

        # Cached OneDrive objects
        self._drive_id: Optional[str] = None
        self._drive_info: Optional[DriveItem] = None

    def connection(self):
        """
        Establish OneDrive connection using the migrated O365Client.

        This replaces the old office365-rest-python-client authentication
        with Microsoft Graph SDK authentication.
        """
        # Use the parent O365Client connection method
        super().connection()

        self.logger.info("OneDrive connection established successfully")
        return self

    async def verify_onedrive_access(self):
        """Verify OneDrive access and cache drive info."""
        try:
            # Resolve and cache drive info
            self._drive_info = await self._resolve_drive()
            self.logger.info(f"OneDrive accessible: {self._drive_info.name or 'Personal OneDrive'}")

        except Exception as e:
            self.logger.error(f"OneDrive access verification failed: {e}")
            raise RuntimeError(f"OneDrive access verification failed: {e}") from e

    async def _resolve_drive(self) -> DriveItem:
        """Resolve OneDrive using Graph API."""
        if self._drive_info:
            return self._drive_info

        try:
            # Get user's personal OneDrive
            drive = await self.graph_client.me.drive.get()

            if drive and drive.id:
                self._drive_id = drive.id
                self._drive_info = drive
                self.logger.info(f"OneDrive resolved: {drive.name or drive.id}")
                return drive
            else:
                raise RuntimeError("Could not resolve OneDrive")

        except Exception as e:
            raise RuntimeError(f"Failed to resolve OneDrive: {e}") from e

    async def _ensure_folder(self, folder_path: str, create: bool = True) -> DriveItem:
        """Ensure folder exists in OneDrive using Graph API."""
        drive_info = await self._resolve_drive()
        drive_id = drive_info.id

        folder_path = (folder_path or "").strip("/")
        if not folder_path:
            # Return root folder
            root = await self.graph_client.drives.by_drive_id(drive_id).root.get()
            return root

        # Try to resolve existing folder
        try:
            folder_item = await self.graph_client.drives.by_drive_id(drive_id)\
                .items.by_drive_item_id(f"root:/{folder_path}:").get()
            if folder_item:
                return folder_item
        except Exception:
            if not create:
                raise

        # Create folder recursively
        root = await self.graph_client.drives.by_drive_id(drive_id).root.get()
        parent_id = root.id

        for segment in [s for s in folder_path.split("/") if s]:
            # Check if segment already exists
            children = await self.graph_client.drives.by_drive_id(drive_id)\
                .items.by_drive_item_id(parent_id).children.get()

            existing_folder = None
            if children and children.value:
                for child in children.value:
                    if child.name == segment and child.folder:
                        existing_folder = child
                        break

            if existing_folder:
                parent_id = existing_folder.id
                continue

            # Create new folder
            new_folder = DriveItem()
            new_folder.name = segment
            new_folder.folder = Folder()
            new_folder.additional_data = {
                "@microsoft.graph.conflictBehavior": "replace"
            }

            created = await self.graph_client.drives.by_drive_id(drive_id)\
                .items.by_drive_item_id(parent_id).children.post(new_folder)
            parent_id = created.id
            self.logger.info(f"Created folder: {segment}")

        # Return the final folder
        final_folder = await self.graph_client.drives.by_drive_id(drive_id)\
            .items.by_drive_item_id(parent_id).get()
        return final_folder

    async def file_list(self, folder_path: str = None) -> List[dict]:
        """
        List files in a given OneDrive folder using Microsoft Graph API.
        """
        try:
            drive_info = await self._resolve_drive()
            drive_id = drive_info.id

            if folder_path:
                # Get specific folder
                folder_path = folder_path.strip("/")
                try:
                    folder_item = await self.graph_client.drives.by_drive_id(drive_id)\
                        .items.by_drive_item_id(f"root:/{folder_path}:").get()
                except Exception as e:
                    raise RuntimeError(f"Folder '{folder_path}' not found: {e}") from e
            else:
                # Get root folder
                folder_item = await self.graph_client.drives.by_drive_id(drive_id).root.get()

            # Get children
            children = await self.graph_client.drives.by_drive_id(drive_id)\
                .items.by_drive_item_id(folder_item.id).children.get()

            file_list = []
            if children and children.value:
                for item in children.value:
                    file_info = {
                        "name": item.name,
                        "id": item.id,
                        "webUrl": item.web_url,
                        "path": self._get_item_path_from_item(item),
                        "isFolder": item.folder is not None,
                        "size": item.size or 0,
                        "modified": item.last_modified_date_time.isoformat() if item.last_modified_date_time else None
                    }
                    file_list.append(file_info)

            return file_list

        except Exception as err:
            self.logger.error(f"Error listing files: {err}")
            raise RuntimeError(f"Error listing files: {err}") from err

    async def file_search(self, search_query: str) -> List[dict]:
        """
        Search for files in OneDrive matching the search query using Microsoft Graph API.
        """
        try:
            drive_info = await self._resolve_drive()
            drive_id = drive_info.id

            # Use Graph API search
            search_results = await self.graph_client.drives.by_drive_id(drive_id)\
                .search_with_q(search_query).get()

            results = []
            if search_results and search_results.value:
                for item in search_results.value:
                    if item.file:  # Only include files, not folders
                        file_info = {
                            "name": item.name,
                            "id": item.id,
                            "webUrl": item.web_url,
                            "path": self._get_item_path_from_item(item),
                            "isFolder": False,
                            "size": item.size or 0,
                            "modified": item.last_modified_date_time.isoformat() if item.last_modified_date_time else None   # noqa
                        }
                        results.append(file_info)

            return results

        except Exception as err:
            self.logger.error(f"Error searching files: {err}")
            raise RuntimeError(f"Error searching files: {err}") from err

    async def file_download(self, item_id: str, destination: Path) -> str:
        """
        Download a file from OneDrive by item ID using Microsoft Graph API.
        """
        try:
            drive_info = await self._resolve_drive()
            drive_id = drive_info.id

            # Get item info
            item = await self.graph_client.drives.by_drive_id(drive_id)\
                .items.by_drive_item_id(item_id).get()

            if not item.file:
                raise RuntimeError(f"Item {item_id} is not a file")

            self.logger.info(f"Downloading {item.name} to {destination}")

            # Get download URL if available
            download_url = ""
            try:
                add = getattr(item, "additional_data", {}) or {}
                download_url = add.get("@microsoft.graph.downloadUrl", "") or ""
            except Exception:
                download_url = ""

            # Ensure destination directory exists
            destination.parent.mkdir(parents=True, exist_ok=True)

            if download_url:
                # Stream via downloadUrl
                async with httpx.AsyncClient(follow_redirects=True, timeout=None) as client:
                    async with client.stream("GET", download_url) as resp:
                        resp.raise_for_status()
                        async with aiofiles.open(destination, "wb") as f:
                            async for chunk in resp.aiter_bytes(1 << 20):  # 1 MiB
                                await f.write(chunk)
            else:
                # Fallback: GET /content via Graph
                content = await self.graph_client.drives.by_drive_id(drive_id)\
                    .items.by_drive_item_id(item_id).content.get()
                async with aiofiles.open(destination, "wb") as f:
                    await f.write(content)

            self.logger.info(f"Downloaded {item.name} successfully")
            return str(destination)

        except Exception as err:
            self.logger.error(f"Error downloading file {item_id}: {err}")
            raise RuntimeError(f"Error downloading file {item_id}: {err}") from err

    async def download_files(self, items: List[dict], destination_folder: Path) -> List[str]:
        """
        Download multiple files from OneDrive using Microsoft Graph API.
        """
        downloaded_files = []
        destination_folder = Path(destination_folder)
        destination_folder.mkdir(parents=True, exist_ok=True)

        for item in items:
            try:
                item_id = item.get("id")
                file_name = item.get("name")
                if not item_id or not file_name:
                    self.logger.warning(f"Skipping invalid item: {item}")
                    continue

                destination = destination_folder / file_name
                downloaded_path = await self.file_download(item_id, destination)
                downloaded_files.append(downloaded_path)

            except Exception as e:
                self.logger.error(f"Failed to download {item.get('name', 'unknown')}: {e}")
                continue

        return downloaded_files

    async def folder_download(self, folder_id: str, destination_folder: Path) -> bool:
        """
        Download a folder and its contents from OneDrive using Microsoft Graph API.
        """
        try:
            drive_info = await self._resolve_drive()
            drive_id = drive_info.id

            # Get folder info
            folder_item = await self.graph_client.drives.by_drive_id(drive_id)\
                .items.by_drive_item_id(folder_id).get()

            if not folder_item.folder:
                raise RuntimeError(f"Item {folder_id} is not a folder")

            await self._download_folder_recursive(drive_id, folder_item, destination_folder)
            return True

        except Exception as err:
            self.logger.error(f"Error downloading folder {folder_id}: {err}")
            raise RuntimeError(f"Error downloading folder {folder_id}: {err}") from err

    async def _download_folder_recursive(self, drive_id: str, folder_item: DriveItem, local_path: Path):
        """
        Recursively download a folder's contents using Microsoft Graph API.
        """
        if not local_path.exists():
            local_path.mkdir(parents=True, exist_ok=True)

        # Get children
        children = await self.graph_client.drives.by_drive_id(drive_id)\
            .items.by_drive_item_id(folder_item.id).children.get()

        if children and children.value:
            for item in children.value:
                item_path = local_path / item.name

                if item.folder:
                    # Recursively download subfolder
                    await self._download_folder_recursive(drive_id, item, item_path)
                else:
                    # Download file
                    await self.file_download(item.id, item_path)

    async def file_delete(self, item_id: str) -> bool:
        """
        Delete a file or folder in OneDrive by item ID using Microsoft Graph API.
        """
        try:
            drive_info = await self._resolve_drive()
            drive_id = drive_info.id

            # Get item info for logging
            try:
                item = await self.graph_client.drives.by_drive_id(drive_id)\
                    .items.by_drive_item_id(item_id).get()
                item_name = item.name
                item_type = "folder" if item.folder else "file"
            except Exception:
                item_name = f"item {item_id}"
                item_type = "item"

            # Delete the item
            await self.graph_client.drives.by_drive_id(drive_id)\
                .items.by_drive_item_id(item_id).delete()

            self.logger.info(f"Deleted {item_type}: {item_name}")
            return True

        except Exception as err:
            self.logger.error(f"Error deleting item {item_id}: {err}")
            raise RuntimeError(f"Error deleting item {item_id}: {err}") from err

    async def upload_file(self, file_path: Path, destination_folder: str = None) -> dict:
        """
        Upload a single file to OneDrive using Microsoft Graph API.
        """
        try:
            file_path = Path(file_path)
            if not file_path.exists():
                raise RuntimeError(f"File not found: {file_path}")

            drive_info = await self._resolve_drive()
            drive_id = drive_info.id

            # Ensure destination folder exists
            if destination_folder:
                folder_info = await self._ensure_folder(destination_folder, create=True)
                parent_id = folder_info.id
            else:
                root = await self.graph_client.drives.by_drive_id(drive_id).root.get()
                parent_id = root.id

            file_size = file_path.stat().st_size
            target_name = file_path.name

            self.logger.info(f"Uploading {target_name} ({file_size:,} bytes)")

            if file_size <= self.small_file_threshold:
                # Small file upload
                result = await self._upload_small_file(drive_id, parent_id, file_path, target_name)
            else:
                # Large file upload
                upload_session = await self._create_upload_session(drive_id, parent_id, target_name)
                result = await self._upload_large_file(upload_session, file_path)

            self.logger.info(f"Uploaded successfully: {result.name}")

            return {
                "name": result.name,
                "id": result.id,
                "webUrl": result.web_url,
                "size": getattr(result, 'size', file_size)
            }

        except Exception as err:
            self.logger.error(f"Error uploading file {file_path}: {err}")
            raise RuntimeError(f"Error uploading file {file_path}: {err}") from err

    async def upload_files(self, files: List[Path], destination_folder: str = None) -> List[dict]:
        """
        Upload multiple files to OneDrive using Microsoft Graph API.
        """
        uploaded_files = []

        for file_path in files:
            try:
                uploaded_item = await self.upload_file(file_path, destination_folder)
                uploaded_files.append(uploaded_item)
            except Exception as e:
                self.logger.error(f"Failed to upload {file_path}: {e}")
                continue

        return uploaded_files

    async def upload_folder(self, local_folder: Path, destination_folder: str = None) -> List[dict]:
        """
        Upload a local folder and its contents to OneDrive using Microsoft Graph API.
        """
        try:
            local_path = Path(local_folder)
            if not local_path.exists() or not local_path.is_dir():
                raise FileNotFoundError(
                    f"Local folder does not exist or is not a directory: {local_folder}"
                )

            uploaded_items = []

            # Get all files in the folder recursively
            for root, dirs, files in os.walk(local_path):
                relative_path = Path(root).relative_to(local_path)

                # Calculate OneDrive destination path
                if destination_folder:
                    onedrive_path = f"{destination_folder}/{relative_path}".replace("\\", "/").strip("/")
                else:
                    onedrive_path = str(relative_path).replace("\\", "/")

                # Ensure the directory exists in OneDrive
                if onedrive_path and onedrive_path != ".":
                    await self._ensure_folder(onedrive_path, create=True)

                # Upload files in this directory
                for file_name in files:
                    file_path = Path(root) / file_name
                    try:
                        uploaded_item = await self.upload_file(
                            file_path,
                            onedrive_path if onedrive_path != "." else None
                        )
                        uploaded_items.append(uploaded_item)
                    except Exception as e:
                        self.logger.error(f"Failed to upload {file_path}: {e}")
                        continue

            return uploaded_items

        except Exception as err:
            self.logger.error(f"Error uploading folder {local_folder}: {err}")
            raise RuntimeError(f"Error uploading folder {local_folder}: {err}") from err

    async def download_excel_file(self, item_id: str, destination: Path = None, as_pandas: bool = False):
        """
        Download an Excel file from OneDrive by item ID using Microsoft Graph API.
        If `as_pandas` is True, return as a pandas DataFrame.
        If `as_pandas` is False, save to the destination path.
        """
        try:
            drive_info = await self._resolve_drive()
            drive_id = drive_info.id

            # Get item info
            item = await self.graph_client.drives.by_drive_id(drive_id)\
                .items.by_drive_item_id(item_id).get()

            if not item.file:
                raise RuntimeError(f"Item {item_id} is not a file")

            # Get file content
            content = await self.graph_client.drives.by_drive_id(drive_id)\
                .items.by_drive_item_id(item_id).content.get()

            if as_pandas:
                bytes_buffer = BytesIO(content)
                return pd.read_excel(bytes_buffer)
            else:
                if not destination:
                    raise ValueError("Destination path must be provided when `as_pandas` is False.")

                destination.parent.mkdir(parents=True, exist_ok=True)
                async with aiofiles.open(destination, "wb") as f:
                    await f.write(content)
                return str(destination)

        except Exception as err:
            self.logger.error(f"Error downloading Excel file {item_id}: {err}")
            raise RuntimeError(f"Error downloading Excel file {item_id}: {err}") from err

    async def upload_dataframe_as_excel(self, df: pd.DataFrame, file_name: str, destination_folder: str = None) -> dict:
        """
        Upload a pandas DataFrame as an Excel file to OneDrive using Microsoft Graph API.
        """
        try:
            # Convert DataFrame to Excel bytes
            output = BytesIO()
            df.to_excel(output, index=False)
            excel_content = output.getvalue()

            drive_info = await self._resolve_drive()
            drive_id = drive_info.id

            # Ensure destination folder exists
            if destination_folder:
                folder_info = await self._ensure_folder(destination_folder, create=True)
                parent_id = folder_info.id
            else:
                root = await self.graph_client.drives.by_drive_id(drive_id).root.get()
                parent_id = root.id

            self.logger.info(f"Uploading DataFrame as Excel: {file_name}")

            # Upload the Excel content
            if len(excel_content) <= self.small_file_threshold:
                # Small file upload
                encoded_name = quote(file_name)
                request_path = f"{parent_id}:/{encoded_name}:"

                uploaded_item = await self.graph_client.drives.by_drive_id(drive_id)\
                    .items.by_drive_item_id(request_path).content.put(excel_content)
            else:
                # Large file upload (create upload session)
                upload_session = await self._create_upload_session(drive_id, parent_id, file_name)
                uploaded_item = await self._upload_large_file_content(upload_session, excel_content, file_name)

            self.logger.info(f"Uploaded DataFrame as Excel successfully: {uploaded_item.name}")

            return {
                "name": uploaded_item.name,
                "id": uploaded_item.id,
                "webUrl": uploaded_item.web_url
            }

        except Exception as err:
            self.logger.error(f"Error uploading DataFrame as Excel file {file_name}: {err}")
            raise RuntimeError(f"Error uploading DataFrame as Excel file {file_name}: {err}") from err

    # Helper methods (similar to SharepointClient)

    async def _upload_small_file(self, drive_id: str, parent_id: str, local_path: Path, target_name: str) -> DriveItem:
        """Upload small file using Graph API."""
        try:
            async with aiofiles.open(local_path, "rb") as f:
                content = await f.read()

            # URL encode the target name to handle special characters
            encoded_name = quote(target_name)
            request_path = f"{parent_id}:/{encoded_name}:"

            return await self.graph_client.drives.by_drive_id(drive_id)\
                .items.by_drive_item_id(request_path).content.put(content)

        except Exception as e:
            raise RuntimeError(f"Small file upload failed for {target_name}: {e}") from e

    async def _create_upload_session(self, drive_id: str, parent_id: str, target_name: str) -> UploadSession:
        """Create upload session for large files using Graph API."""
        try:
            body = CreateUploadSessionPostRequestBody()
            body.item = DriveItemUploadableProperties()
            body.item.additional_data = {"@microsoft.graph.conflictBehavior": "replace"}

            # URL encode the target name to handle special characters
            encoded_name = quote(target_name)

            return await self.graph_client.drives.by_drive_id(drive_id)\
                .items.by_drive_item_id(f"{parent_id}:/{encoded_name}:/")\
                .create_upload_session.post(body)

        except Exception as e:
            raise RuntimeError(f"Upload session creation failed for {target_name}: {e}") from e

    async def _upload_large_file(self, upload_session: UploadSession, local_path: Union[str, Path]) -> DriveItem:
        """Upload large file using resumable upload session."""
        file_size = os.path.getsize(local_path)
        uploaded = 0

        async with aiohttp.ClientSession() as session:
            async with aiofiles.open(local_path, "rb") as f:
                with tqdm(total=file_size, unit='B', unit_scale=True, desc=f'Uploading {Path(local_path).name}') as pbar:  # noqa
                    while uploaded < file_size:
                        chunk = await f.read(self.chunk_size)
                        if not chunk:
                            break

                        start = uploaded
                        end = uploaded + len(chunk) - 1

                        headers = {
                            "Content-Length": str(len(chunk)),
                            "Content-Range": f"bytes {start}-{end}/{file_size}"
                        }

                        async with session.put(
                            upload_session.upload_url,
                            headers=headers,
                            data=chunk
                        ) as response:
                            if response.status in (200, 201):
                                # Upload complete
                                pbar.update(file_size - uploaded)
                                result_data = await response.json()

                                # Convert to DriveItem (simplified)
                                drive_item = DriveItem()
                                drive_item.name = result_data.get('name')
                                drive_item.size = result_data.get('size')
                                drive_item.web_url = result_data.get('webUrl')
                                drive_item.additional_data = result_data

                                return drive_item

                            elif response.status == 202:
                                # Continue uploading
                                uploaded = end + 1
                                pbar.update(len(chunk))

                                # Check for retry-after header
                                if (retry_after := response.headers.get('Retry-After')):
                                    await asyncio.sleep(int(retry_after))
                                continue

                            else:
                                error_text = await response.text()
                                raise RuntimeError(f"Chunk upload failed: {response.status} {error_text}")

        raise RuntimeError("Upload session completed without final item response")

    async def _upload_large_file_content(
        self,
        upload_session: UploadSession,
        content: bytes,
        file_name: str
    ) -> DriveItem:
        """Upload large content using resumable upload session."""
        file_size = len(content)
        uploaded = 0

        async with aiohttp.ClientSession() as session:
            with tqdm(total=file_size, unit='B', unit_scale=True, desc=f'Uploading {file_name}') as pbar:
                while uploaded < file_size:
                    chunk = content[uploaded:uploaded + self.chunk_size]
                    if not chunk:
                        break

                    start = uploaded
                    end = uploaded + len(chunk) - 1

                    headers = {
                        "Content-Length": str(len(chunk)),
                        "Content-Range": f"bytes {start}-{end}/{file_size}"
                    }

                    async with session.put(
                        upload_session.upload_url,
                        headers=headers,
                        data=chunk
                    ) as response:
                        if response.status in (200, 201):
                            # Upload complete
                            pbar.update(file_size - uploaded)
                            result_data = await response.json()

                            # Convert to DriveItem (simplified)
                            drive_item = DriveItem()
                            drive_item.name = result_data.get('name')
                            drive_item.size = result_data.get('size')
                            drive_item.web_url = result_data.get('webUrl')
                            drive_item.additional_data = result_data

                            return drive_item

                        elif response.status == 202:
                            # Continue uploading
                            uploaded = end + 1
                            pbar.update(len(chunk))

                            # Check for retry-after header
                            if (retry_after := response.headers.get('Retry-After')):
                                await asyncio.sleep(int(retry_after))
                            continue

                        else:
                            error_text = await response.text()
                            raise RuntimeError(f"Chunk upload failed: {response.status} {error_text}")

        raise RuntimeError("Upload session completed without final item response")

    def _get_item_path_from_item(self, item) -> str:
        """
        Extract the full path from a DriveItem object.
        """
        try:
            # Try to get path from parent_reference
            if hasattr(item, 'parent_reference') and item.parent_reference and item.parent_reference.path:
                parent_path = item.parent_reference.path or ""

                # Clean up the parent path
                if parent_path.startswith("/drive/root:"):
                    parent_path = parent_path[12:]
                elif parent_path.startswith("/drives/") and "/root:" in parent_path:
                    parent_path = parent_path.split("/root:")[-1]

                # Build the full path
                if parent_path:
                    full_path = f"{parent_path}/{item.name}".replace("//", "/").lstrip("/")
                else:
                    full_path = item.name or ""

                return full_path

            # Fallback: try to get path from web_url if available
            if hasattr(item, 'web_url') and item.web_url:
                try:
                    # Extract path from OneDrive web URL
                    web_url = item.web_url
                    if "/personal/" in web_url and "/_layouts/15/onedrive.aspx" in web_url:
                        # Personal OneDrive URL format
                        return item.name or ""
                    else:
                        return unquote(item.name or "")
                except Exception:
                    pass

            # Final fallback: just return the filename
            return item.name or ""

        except Exception as e:
            self.logger.debug(f"Error extracting path from item: {e}")
            return item.name or ""

    async def test_permissions(self) -> Dict[str, Any]:
        """
        Test OneDrive permissions using Microsoft Graph API.
        """
        results = {
            "drive_access": False,
            "folder_access": False,
            "upload_access": False,
            "errors": []
        }

        try:
            # Test 1: Drive access
            drive_info = await self._resolve_drive()
            results["drive_access"] = True
            self.logger.info(f"Drive access: {drive_info.name or 'Personal OneDrive'}")

            # Test 2: Folder access (list root)
            file_list = await self.file_list()
            results["folder_access"] = True
            self.logger.info(f"Folder access: Listed {len(file_list)} items")

            # Test 3: Folder creation (upload capability test)
            test_folder = await self._ensure_folder("test-folder-permissions", create=True)
            results["upload_access"] = True
            self.logger.info("Upload permissions confirmed")

            # Clean up test folder
            with contextlib.suppress(Exception):
                await self.file_delete(test_folder.id)
                self.logger.info("Test folder cleaned up")

        except Exception as e:
            results["errors"].append(str(e))
            self.logger.error(f"Permission test failed: {e}")

        return results

    async def close(self):
        """Clean up resources."""
        await super().close()
        self._drive_info = None
        self._drive_id = None
