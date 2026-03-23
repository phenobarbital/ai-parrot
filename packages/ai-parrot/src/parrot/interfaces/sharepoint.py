import os
import re
import asyncio
from typing import List, Optional, Union, Dict, Any
import contextlib
from pathlib import Path, PurePath
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse, quote, unquote
import aiofiles
from tqdm import tqdm
import httpx
import aiohttp
# Microsoft Graph SDK imports (replacing office365-rest-python-client)
from msgraph.generated.models.subscription import Subscription
from msgraph.generated.models.drive_item import DriveItem
from msgraph.generated.models.folder import Folder
from msgraph.generated.models.file import File
from msgraph.generated.models.upload_session import UploadSession
from msgraph.generated.drives.item.items.item.create_upload_session.create_upload_session_post_request_body import (
    CreateUploadSessionPostRequestBody
)
from msgraph.generated.models.drive_item_uploadable_properties import DriveItemUploadableProperties
from .o365 import O365Client
from ..conf import (
    SHAREPOINT_APP_ID,
    SHAREPOINT_APP_SECRET,
    SHAREPOINT_TENANT_ID,
    SHAREPOINT_TENANT_NAME
)


class SharepointClient(O365Client):
    """
    SharePoint Client - Migrated to Microsoft Graph SDK

    Uses Microsoft Graph SDK for all SharePoint operations.

    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Default credentials for SharePoint-specific config
        self._default_tenant_id = SHAREPOINT_TENANT_ID
        self._default_client_id = SHAREPOINT_APP_ID
        self._default_client_secret = SHAREPOINT_APP_SECRET
        self._default_tenant_name = SHAREPOINT_TENANT_NAME

        # SharePoint-specific properties
        self.directory: Optional[str] = None
        self.filename: Optional[str] = None
        self._srcfiles: List = []
        self._destination: List = []

        # Upload settings
        self.small_file_threshold = 4 * 1024 * 1024  # 4 MB
        self.chunk_size = 10 * 1024 * 1024  # 10 MB

        # Cached SharePoint objects
        self._site_id: Optional[str] = None
        self._drive_id: Optional[str] = None
        self._site_info: Optional[DriveItem] = None
        self._drive_info: Optional[DriveItem] = None

    def get_context(self, url: str, *args):
        """
        Backwards compatibility method.
        Returns the Graph client instead of office365 context.
        """
        return self.graph_client

    def _start_(self, **kwargs):
        """Initialize SharePoint-specific configuration."""
        # Process URL and site information
        site = f"sites/{self.site}/" if self.site is not None else ""
        self.site_url = f"https://{self.tenant}.sharepoint.com"
        self.url = f"{self.site_url}/{site}".rstrip('/')
        self.logger.info(
            f"SharePoint target: {self.url}"
        )
        return True

    def connection(self):
        """
        Establish SharePoint connection using the migrated O365Client.

        This replaces the old office365-rest-python-client authentication
        with Microsoft Graph SDK authentication.
        """
        # Use the parent O365Client connection method
        super().connection()

        self.logger.info("SharePoint connection established successfully")
        return self

    async def verify_sharepoint_access(self):
        """Verify SharePoint-specific access and cache site/drive info."""
        try:
            # Resolve and cache site info
            self._site_info = await self._resolve_site()
            self.logger.info(
                f"SharePoint site accessible: {self._site_info.display_name}"
            )

            # Update the URL if sub-site was detected
            if hasattr(self, '_site_info') and self._site_info:
                # Reconstruct URL based on actual site used
                actual_site_path = self._site_info.web_url.split('/sites/')[-1] if self._site_info.web_url else self.site
                self.url = f"https://{self.tenant}.sharepoint.com/sites/{actual_site_path}"
                self.logger.debug(f"Updated SharePoint URL: {self.url}")

        except Exception as e:
            self.logger.error(
                f"SharePoint access verification failed: {e}"
            )
            raise RuntimeError(
                f"SharePoint access verification failed: {e}"
            ) from e

    async def _detect_and_resolve_subsite(self) -> tuple[str, str]:
        """
        Detect if the first part of the directory path is a sub-site.

        Returns:
            tuple: (actual_site_to_use, cleaned_directory_path)
        """
        # Get the directory from _srcfiles
        if not hasattr(self, '_srcfiles') or not self._srcfiles:
            return self.site, ""

        first_file = self._srcfiles[0]
        directory_raw = first_file.get('directory', '') if isinstance(first_file, dict) else ''

        if not directory_raw:
            return self.site, ""

        directory = directory_raw.replace("\\", "/").strip().strip("/")
        if not directory:
            return self.site, ""

        parts = directory.split("/")
        potential_subsite = parts[0]
        remaining_path = "/".join(parts[1:]) if len(parts) > 1 else ""

        # Try to access the potential sub-site
        with contextlib.suppress(Exception):
            subsite_path = f"{self.site}/{potential_subsite}"
            site_identifier = f"{self.tenant}.sharepoint.com:/sites/{subsite_path}"

            self.logger.debug(f"Testing potential sub-site: {site_identifier}")

            # Try to access the sub-site
            site = await self.graph_client.sites.by_site_id(site_identifier).get()

            if site and site.id:
                self.logger.info(f"Detected sub-site: {potential_subsite}")

                # Update all _srcfiles to remove the sub-site part from directory
                for file_spec in self._srcfiles:
                    if isinstance(file_spec, dict) and 'directory' in file_spec:
                        old_dir = file_spec['directory']
                        # Remove the sub-site part
                        clean_parts = old_dir.replace("\\", "/").strip().strip("/").split("/")
                        if len(clean_parts) > 1 and clean_parts[0] == potential_subsite:
                            new_dir = "/".join(clean_parts[1:])
                            file_spec['directory'] = new_dir
                            self.logger.debug(f"Updated directory: '{old_dir}' → '{new_dir}'")

                return subsite_path, remaining_path

        # Not a sub-site, return original
        return self.site, directory

    async def _resolve_site(self) -> DriveItem:
        """Resolve SharePoint site using Graph API with auto sub-site detection."""
        if self._site_info:
            return self._site_info

        try:
            # Detect if we need to use a sub-site
            actual_site, _ = await self._detect_and_resolve_subsite()

            site_path = f"/sites/{actual_site}" if actual_site else ""
            site_identifier = f"{self.tenant}.sharepoint.com:{site_path}"

            self.logger.debug(
                f"Resolving site: {site_identifier}"
            )
            site = await self.graph_client.sites.by_site_id(site_identifier).get()

            if site and site.id:
                self._site_id = site.id
                self._site_info = site
                self.logger.info(
                    f"Site resolved: {site.display_name}"
                )
                return site
            else:
                raise RuntimeError(
                    f"Could not resolve SharePoint site: {site_identifier}"
                )

        except Exception as e:
            raise RuntimeError(
                f"Failed to resolve SharePoint site: {e}"
            ) from e

    def _parse_directory_path(self, directory: str) -> tuple[str, str]:
        """
        Parse directory path to extract library name and folder path.

        Examples:
        - "troc/Project Management/Epson/Store and Product MSL"
        → library: "troc", path: "Project Management/Epson/Store and Product MSL"
        - "Shared Documents/Stores/"
        → library: "Shared Documents", path: "Stores"
        - "Documents/folder/subfolder"
        → library: "Documents", path: "folder/subfolder"
        """
        if not directory:
            return "Documents", ""  # Default library

        directory = directory.replace("\\", "/").strip().strip("/")
        if not directory:
            return "Documents", ""

        parts = directory.split("/")

        # First part is the library name
        library_name = parts[0]
        # Rest is the path within that library
        path_within_library = "/".join(parts[1:]) if len(parts) > 1 else ""

        self.logger.debug(
            f"Parsed directory '{directory}' → library: '{library_name}', path: '{path_within_library}'"
        )
        if library_name.lower() == "shared documents":
            library_name = "Documents"

        return library_name, path_within_library

    async def _resolve_drive(self, library_name: str = None) -> DriveItem:
        """Resolve document library drive using Graph API with dynamic library name."""
        if self._drive_info and not library_name:
            return self._drive_info

        try:
            site_info = await self._resolve_site()
            drives = await self.graph_client.sites.by_site_id(site_info.id).drives.get()
            if drives and drives.value:
                self.logger.debug(
                    f"Available libraries: {[d.name for d in drives.value]}"
                )

                # If library_name specified, try to find it
                if library_name:
                    for drive in drives.value:
                        if drive.name.lower() == library_name.lower():  # Case insensitive match
                            self.logger.info(f"Found library: {drive.name}")
                            # Don't cache if we're doing a specific lookup
                            return drive

                    # Library not found by name, log available options
                    available_names = [d.name for d in drives.value]
                    self.logger.warning(
                        f"Library '{library_name}' not found. Available: {available_names}"
                    )

                    # Try common name mappings
                    if library_name.lower() == "shared documents":
                        for drive in drives.value:
                            if drive.name.lower() in ["documents", "shared documents"]:
                                self.logger.info(f"Using '{drive.name}' for 'Shared Documents'")
                                return drive

                    raise RuntimeError(
                        f"Library '{library_name}' not found. Available: {available_names}"
                    )

                # No specific library requested, use cached or default
                if self._drive_info:
                    return self._drive_info

                # Default to first drive and cache it
                default_drive = drives.value[0]
                self._drive_id = default_drive.id
                self._drive_info = default_drive
                self.logger.info(f"Using default library: {default_drive.name}")
                return default_drive

            raise RuntimeError(
                f"No document libraries found in site: {site_info.display_name}"
            )

        except Exception as e:
            raise RuntimeError(f"Failed to resolve document library: {e}") from e

    async def _ensure_folder(self, folder_path: str, create: bool = True, drive_id: str = None) -> DriveItem:
        """Ensure folder exists using Graph API, optionally in a specific library."""

        # If no drive_id specified, get the default drive
        if not drive_id:
            drive_info = await self._resolve_drive()
            drive_id = drive_info.id

        folder_path = (folder_path or "").strip("/")
        if not folder_path:
            # Return root folder of the specified drive
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
        return await self.graph_client.drives.by_drive_id(drive_id)\
            .items.by_drive_item_id(parent_id).get()

    async def _build_full_path(self, drive_id: str, parent_id: str, filename: str) -> str:
        """Return path relative to drive root: e.g. 'Shared Documents/Sub/Folder/output.pptx'."""
        parent = await self.graph_client.drives.by_drive_id(drive_id).items.by_drive_item_id(parent_id).get()
        base = (parent.parent_reference.path or "")  # e.g. '/drives/{driveId}/root:/Shared Documents/Sub/Folder'
        # Strip the "/drives/{id}/root:" prefix to make it drive-root relative
        marker = "/root:"
        idx = base.find(marker)
        if idx != -1:
            base = base[idx + len(marker):]
        base = base.strip("/")
        # Path already points to the parent folder itself, so just append the filename
        return f"{base}/{filename}".strip("/")

    async def _upload_small_file(self, drive_id, parent_id, local_path, target_name):
        try:
            async with aiofiles.open(local_path, "rb") as f:
                content = await f.read()

            # URL encode the target name to handle special characters
            encoded_name = quote(target_name)

            # Use the direct content upload endpoint for small files with conflict behavior
            # PUT /drives/{driveId}/items/{parentId}:/{filename}:/content?@microsoft.graph.conflictBehavior=replace
            request_path = f"{parent_id}:/{encoded_name}:"

            # The Graph SDK may not support query parameters directly on the content endpoint
            # So we use the basic path and let the SDK handle the upload
            return await self.graph_client.drives.by_drive_id(drive_id).items.by_drive_item_id(request_path).content.put(content)  # noqa
        except Exception as e:
            raise RuntimeError(f"Small file upload failed for {target_name}: {e}") from e

    async def _create_upload_session(self, drive_id: str, parent_id: str, target_name: str) -> UploadSession:
        try:
            body = CreateUploadSessionPostRequestBody()
            body.item = DriveItemUploadableProperties()
            # no "name" here; filename is in the URL
            body.item.additional_data = {"@microsoft.graph.conflictBehavior": "replace"}

            # URL encode the target name to handle special characters
            encoded_name = quote(target_name)

            # POST /drives/{driveId}/items/{parentId}:/{fileName}:/createUploadSession
            return await self.graph_client.drives.by_drive_id(drive_id)\
                .items.by_drive_item_id(f"{parent_id}:/{encoded_name}:/")\
                .create_upload_session.post(body)

        except Exception as e:
            raise RuntimeError(f"Upload session creation failed for {target_name}: {e}") from e

    async def _upload_large_file(
        self,
        upload_session: UploadSession,
        local_path: Union[str, Path]
    ) -> DriveItem:
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
                                raise RuntimeError(
                                    f"Chunk upload failed: {response.status} {error_text}"
                                )

        raise RuntimeError(
            "Upload session completed without final item response"
        )

    def _normalize_directory(self, directory: str, drive_info) -> str:
        """
        Normalize a SharePoint directory path so it is **relative to the drive root**.

        Accepts inputs like:
        - "Project Management/Epson/Store and Product MSL"
        - "Documents/Project Management/Epson/Store and Product MSL"
        - "Shared Documents/Project Management/..."
        - "sites/<site>/Shared Documents/Project Management/..."
        - "troc/Documents/Project Management/..."                # stray tenant/site prefix
        - "/drives/<id>/root:/Project Management/...             # SDK-style path"
        - "/drive/root:/Project Management/..."

        Returns a drive-root relative string such as:
        "Project Management/Epson/Store and Product MSL" (or "" for library root)
        """
        if not directory:
            return ""

        p = directory.replace("\\", "/").strip()
        if not p:
            return ""

        self.logger.debug(f"Normalizing directory: '{directory}' -> initial clean: '{p}'")

        # If path contains a /root: prefix, strip everything up to it.
        if "/root:" in p:
            p = p.split("/root:", 1)[1]

        # Strip any leading "root:" marker and leading/trailing slashes
        p = p.lstrip("root:").strip("/")

        # Split into parts and work in lower for comparisons
        parts = [seg for seg in p.split("/") if seg]
        lower = [seg.lower() for seg in parts]

        # Helper: return remainder after a given index
        def after(idx: int) -> str:
            return "/".join(parts[idx + 1:])

        # 1) If the path contains a document library segment, keep only what's after it
        for i, seg in enumerate(lower):
            if seg in ("shared documents", "documents"):
                normalized = after(i)
                self.logger.debug(f"Removed library segment '{parts[i]}', remaining: '{normalized}'")
                self.logger.debug(f"Final normalized directory: '{directory}' -> '{normalized}'")
                return normalized

        # 2) If it starts with 'sites/<sitename>/*', drop those two segments, then
        #    drop a leading library name if it immediately follows.
        if len(lower) >= 2 and lower[0] == "sites":
            parts = parts[2:]
            lower = lower[2:]
            if parts:
                if lower and lower[0] in ("shared documents", "documents"):
                    parts = parts[1:]
            normalized = "/".join(parts)
            self.logger.debug(f"Removed '/sites/<site>/' prefix, remaining: '{normalized}'")
            self.logger.debug(f"Final normalized directory: '{directory}' -> '{normalized}'")
            return normalized

        # 3) If the first segment equals site/tenant name (stray prefix), drop it and retry library removal
        stray_prefixes = set()
        if getattr(self, "site", None):
            stray_prefixes.add(str(self.site).strip("/").lower())
        if getattr(self, "tenant", None):
            stray_prefixes.add(str(self.tenant).strip("/").lower())

        if lower and lower[0] in stray_prefixes:
            parts = parts[1:]
            lower = lower[1:]
            # If next is a library name, drop it as well
            if lower and lower[0] in ("shared documents", "documents"):
                parts = parts[1:]
            normalized = "/".join(parts)
            self.logger.debug(f"Removed stray site/tenant prefix, remaining: '{normalized}'")
            self.logger.debug(f"Final normalized directory: '{directory}' -> '{normalized}'")
            return normalized

        # Otherwise assume it's already drive-root relative
        normalized = "/".join(parts)
        self.logger.debug(f"Final normalized directory: '{directory}' -> '{normalized}'")
        return normalized

    def _to_colon_id(self, directory: str, name: str) -> str:
        """
        Build a root-based colon id with URL-encoded segments:
        "root:/dir1/dir2/file.ext:"
        """
        dir_clean = "/".join(quote(seg, safe="") for seg in (directory.strip("/").split("/") if directory else []))
        name_enc = quote(name, safe="")
        return f"root:/{dir_clean}/{name_enc}:" if dir_clean else f"root:/{name_enc}:"

    async def upload_files(
        self,
        filenames: Optional[List[Union[Path, PurePath, str]]] = None,
        destination: Optional[str] = None,
        destination_filenames: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """
        Upload files to SharePoint using Microsoft Graph API.

        This replaces the old office365-rest-python-client upload method.
        """
        if not filenames:
            filenames = getattr(self, '_srcfiles', [])

        target_folder = destination or getattr(self, 'directory', '')
        # Again: Validate destination names (if provided)
        if destination_filenames is not None and len(destination_filenames) != len(filenames):
            raise RuntimeError(
                "destination_filenames length must match filenames length"
            )

        # Parse the directory to extract library and path (same as file_search and file_lookup)
        library_name, path_within_library = self._parse_directory_path(target_folder)

        # Get the specific library
        try:
            drive_info = await self._resolve_drive(library_name)
            self.logger.debug(f"Using library: {drive_info.name} (ID: {drive_info.id})")
        except Exception as e:
            self.logger.error(f"Failed to access library '{library_name}': {e}")
            # Fall back to default library
            drive_info = await self._resolve_drive()

        # Ensure target folder exists using the path within the library
        folder_info = await self._ensure_folder(path_within_library, create=True, drive_id=drive_info.id)

        results: List[Dict[str, Any]] = []

        target_folder = path_within_library or '/'

        for idx, file_path in enumerate(filenames):
            file_path = Path(file_path)

            if not file_path.exists():
                self.logger.error(f"❌ File not found: {file_path}")
                continue

            # Desired name in SharePoint (rename)
            target_name = (
                destination_filenames[idx] if destination_filenames else file_path.name
            )

            try:
                file_size = file_path.stat().st_size
                self.logger.notice(
                    f"Uploading {file_path.name} → {target_name} "
                    f"to '{target_folder}' ({file_size:,} bytes)"
                )

                if file_size <= self.small_file_threshold:
                    # Small file upload
                    result = await self._upload_small_file(
                        drive_info.id,
                        folder_info.id,
                        file_path,
                        target_name,
                    )
                else:
                    # Large file upload
                    upload_session = await self._create_upload_session(
                        drive_info.id,
                        folder_info.id,
                        target_name
                    )
                    result = await self._upload_large_file(upload_session, file_path)

                self.logger.info(f"Uploaded successfully: {result.name}")
                # Build server-relative path including subfolders and renamed file
                server_relative_path = await self._build_full_path(
                    drive_info.id, folder_info.id, target_name
                )
                if hasattr(result, 'web_url') and result.web_url:
                    self.logger.info(f"SharePoint URL: {result.web_url}")

                # Backwards compatibility format
                results.append({
                    "filename": {
                        "name": result.name,
                        "size": getattr(result, 'size', file_size),
                        "web_url": getattr(result, 'web_url', ''),
                        "serverRelativeUrl": f"/{server_relative_path}",
                    }
                })

            except Exception as e:
                self.logger.error(f"Upload failed for {target_name}: {e}")
                raise RuntimeError(f"Upload failed for {target_name}: {e}") from e

        return results

    async def test_permissions(self) -> Dict[str, Any]:
        """
        Test SharePoint permissions using Microsoft Graph API.

        This replaces the old office365-rest-python-client permission test.
        """
        results = {
            "site_access": False,
            "folder_access": False,
            "upload_access": False,
            "errors": []
        }

        try:
            # Test 1: Site access
            site_info = await self._resolve_site()
            results["site_access"] = True
            self.logger.info(f"Site access: {site_info.display_name}")

            # Test 2: Drive access
            drive_info = await self._resolve_drive()
            results["folder_access"] = True
            self.logger.info(f"Drive access: {drive_info.name}")

            # Test 3: Folder creation (upload capability test)
            test_folder = await self._ensure_folder("test-folder-permissions", create=True)
            results["upload_access"] = True
            self.logger.info("Upload permissions confirmed")

            # Clean up test folder
            with contextlib.suppress(Exception):
                await self.graph_client.drives.by_drive_id(
                    drive_info.id
                ).items.by_drive_item_id(test_folder.id).delete()
                self.logger.info("Test folder cleaned up")

        except Exception as e:
            results["errors"].append(str(e))
            self.logger.error(f"Permission test failed: {e}")

        return results

    async def upload_folder(
        self,
        local_folder: PurePath,
        destination: str = None,
        destination_filenames: Optional[List[str]] = None,
    ):
        """
        Upload an entire folder to SharePoint using Microsoft Graph API.

        Args:
            local_folder: Local folder path to upload
            sharepoint_folder: SharePoint destination folder (optional)

        Returns:
            List of upload results
        """
        try:
            local_path = Path(local_folder)
            if not local_path.exists() or not local_path.is_dir():
                raise FileNotFoundError(
                    f"Local folder does not exist or is not a directory: {local_folder}"
                )

            # Get all files in the folder recursively
            all_files = []
            all_files.extend(
                file_path
                for file_path in local_path.rglob("*")
                if file_path.is_file()
            )

            if not all_files:
                self.logger.warning(
                    f"No files found in folder: {local_folder}"
                )
                return []

            self.logger.debug(
                f"Uploading folder with {len(all_files)} files from {local_folder}"
            )

            # Use the existing upload_files method for each file
            results = []
            target_folder = destination or getattr(self, 'directory', 'Shared Documents')

            # Group files by their relative directory structure
            for idx, file_path in enumerate(all_files):
                # Calculate relative path from the source folder
                relative_path = file_path.relative_to(local_path)

                # If file is in a subdirectory, include that in the SharePoint path
                if relative_path.parent != Path('.'):
                    file_target_folder = f"{target_folder}/{relative_path.parent}".replace("\\", "/")
                else:
                    file_target_folder = target_folder

                try:
                    self.logger.debug(
                        f"Uploading {relative_path} to {file_target_folder}"
                    )

                    # Upload single file to the appropriate folder
                    file_result = await self.upload_files(
                        filenames=[file_path],
                        destination=file_target_folder,
                        destination_filenames=[destination_filenames[idx]] if destination_filenames else None
                    )
                    results.extend(file_result)

                except Exception as e:
                    self.logger.error(f"Failed to upload {relative_path}: {e}")
                    # Continue with other files even if one fails
                    continue

            self.logger.info(
                f"Folder upload completed. {len(results)} files uploaded successfully."
            )
            return results

        except Exception as e:
            self.logger.error(f"Folder upload failed: {e}")
            raise RuntimeError(
                f"Folder upload failed: {e}"
            ) from e

    async def create_subscription(
        self,
        library_id: str,
        webhook_url: str,
        client_state: str = "secret_string",
        expiration_days: int = 1
    ) -> dict:
        """Create webhook subscription using Graph API."""
        try:
            # Set up expiration for the subscription (max 180 days)
            expiration_date = datetime.now(timezone.utc) + timedelta(days=expiration_days)
            expiration_datetime = f"{expiration_date.isoformat()}Z"

            # Use Graph SDK for subscription creation
            subscription = Subscription()
            subscription.change_type = "created,updated,deleted"
            subscription.notification_url = webhook_url
            subscription.resource = f"sites/{self.tenant}/lists/{library_id}"
            subscription.expiration_date_time = expiration_datetime
            subscription.client_state = client_state

            # Create subscription using Graph SDK
            created_subscription = await self.graph_client.subscriptions.post(subscription)

            self.logger.info("✅ Subscription created successfully")
            return {
                "id": created_subscription.id,
                "resource": created_subscription.resource,
                "notification_url": created_subscription.notification_url,
                "expiration_date_time": created_subscription.expiration_date_time
            }

        except Exception as e:
            self.logger.error(f"❌ Failed to create subscription: {e}")
            raise RuntimeError(f"Failed to create subscription: {e}") from e

    async def get_library_id(self, absolute_url: str) -> str:
        """Get library ID using Graph API."""
        try:
            # Parse the absolute URL to get site and document library path
            parsed_url = urlparse(absolute_url)
            path_parts = parsed_url.path.strip("/").split("/")

            # Format the site name and library path
            site_name = path_parts[1]  # e.g., 'sites/mysite'
            library_name = "/".join(path_parts[2:])  # e.g., 'Documents'

            # Use Graph SDK to get library info
            site_identifier = f"{self.tenant}.sharepoint.com:/{site_name}"
            site = await self.graph_client.sites.by_site_id(site_identifier).get()

            # Get drives for the site
            drives = await self.graph_client.sites.by_site_id(site.id).drives.get()

            if drives and drives.value:
                for drive in drives.value:
                    if library_name in drive.name or drive.name == "Documents":
                        self.logger.info(
                            f"📋 Library ID for {absolute_url} is {drive.id}"
                        )
                        return drive.id

            raise RuntimeError("Library not found")

        except Exception as e:
            raise RuntimeError(f"Failed to retrieve library ID: {e}") from e

    async def close(self):
        """Clean up resources."""
        await super().close()
        self._site_info = None
        self._drive_info = None
        self._site_id = None
        self._drive_id = None

    def _pattern_is_api_safe(self, pattern: str) -> bool:
        """
        Return True if 'pattern' can be safely passed to Graph search (no wildcards/regex),
        otherwise False (e.g., contains * ? [ ] { } ( ) ^ $ | \ ).
        """
        return not re.search(r'[*?\[\]\{\}\(\)\^\$|\\]', pattern or "")

    def _in_dir(self, path_rel_to_drive: str, dir_rel_to_drive: str) -> bool:
        p = (path_rel_to_drive or "").strip("/").lower()
        d = (dir_rel_to_drive or "").strip("/").lower()
        return p.startswith(d) if d else True

    async def download_found_files(
        self,
        found: List[Dict[str, Any]],
    ) -> List[Dict[str, str]]:
        """
        Download all items in 'found' (from file_search) into local self.directory.
        Uses aiofiles for writing and httpx (downloadUrl) for streaming.
        If self._filenames is provided and its length matches len(found),
        files are renamed accordingly; otherwise warn and keep original names.

        Returns: List[{"filename": <local_path>, "download_url": <url or "">}]
        """
        results: List[Dict[str, str]] = []

        # Ensure local destination directory exists
        dest_dir = Path(getattr(self, "directory", ".")).expanduser().resolve()
        dest_dir.mkdir(parents=True, exist_ok=True)

        # Handle desired names
        desired_names = getattr(self, "_filenames", None)
        if desired_names and len(desired_names) != len(found):
            self.logger.warning(
                f"⚠️ Matched files ({len(found)}) != self._filenames ({len(desired_names)}). "
                f"Will keep original names."
            )
            desired_names = None

        def _sanitize(name: str) -> str:
            # make it a safe filename for local FS
            name = Path(name).name  # strip any path
            return re.sub(r'[\\/:*?"<>|]+', "_", name).strip()

        # Resolve drive once for content fallback (if needed)
        drive_info = await self._resolve_drive()
        drive_id = drive_info.id

        async with httpx.AsyncClient(follow_redirects=True, timeout=None) as client:
            for idx, entry in enumerate(found):
                item = entry.get("item")
                if not item or not getattr(item, "name", None):
                    self.logger.warning("Skipping entry without a valid drive item")
                    continue

                # Determine target local filename
                target_name = _sanitize(desired_names[idx]) if desired_names else _sanitize(item.name)
                dest_path = dest_dir / target_name

                # Get pre-authenticated download URL if available
                download_url = ""
                try:
                    add = getattr(item, "additional_data", {}) or {}
                    download_url = add.get("@microsoft.graph.downloadUrl", "") or ""
                except Exception:
                    download_url = ""

                self.logger.debug(
                    f"⬇️  Downloading {item.name} → {dest_path.name}"
                )

                try:
                    if download_url:
                        # Stream via downloadUrl
                        async with client.stream("GET", download_url) as resp:
                            resp.raise_for_status()
                            async with aiofiles.open(dest_path, "wb") as f:
                                async for chunk in resp.aiter_bytes(1 << 20):  # 1 MiB
                                    await f.write(chunk)
                    else:
                        # Fallback: GET /content via Graph (loads into memory)
                        data = await self.graph_client.drives.by_drive_id(drive_id)\
                            .items.by_drive_item_id(item.id).content.get()
                        async with aiofiles.open(dest_path, "wb") as f:
                            await f.write(data)

                    self.logger.debug(
                        f"✅ Saved: {dest_path}"
                    )
                    results.append(
                        {"filename": str(dest_path), "download_url": download_url}
                    )
                except Exception as e:
                    self.logger.error(
                        f"❌ Download failed for {item.name}: {e}"
                    )
                    # Continue with the rest; do not raise to allow partial completion

        return results

    async def file_search(self) -> List[Dict[str, Any]]:
        """
        Search for files with Graph API (when safe) and recursive fallback starting at the target folder.
        Logs every tested file during recursion. Does not raise on desired-name count mismatches.
        """
        destinations: List[Dict[str, Any]] = []

        try:
            for spec in getattr(self, "_srcfiles", []):
                directory_raw: str = (spec.get("directory") or "").strip()
                pattern: str = spec.get("pattern") or spec.get("filename") or ""
                extension = (spec.get("extension") or "").strip()
                wanted_ext: Optional[str] = extension.lower().lstrip(".") if extension else None

                if not directory_raw:
                    raise RuntimeError("file_search: each spec must include a 'directory'")

                # Parse the directory to extract library and path (same as file_lookup)
                library_name, directory = self._parse_directory_path(directory_raw)

                # Get the specific library
                try:
                    drive_info = await self._resolve_drive(library_name)
                    drive_id = drive_info.id
                    self.logger.debug(f"Using library: {drive_info.name} (ID: {drive_id})")
                except Exception as e:
                    self.logger.error(f"Failed to access library '{library_name}': {e}")
                    continue

                found_files: List[Dict[str, Any]] = []

                # Try API search only if pattern is simple/safe
                if pattern and self._pattern_is_api_safe(pattern):
                    # A conservative sanitizer for Graph search term
                    clean_q = re.sub(r"[^A-Za-z0-9._-]+", " ", pattern).strip()
                    if len(clean_q) >= 2:
                        try:
                            self.logger.debug(f"Attempting API search with term: '{clean_q}'")
                            api_res = await self.graph_client.drives.by_drive_id(drive_id).search_with_q(clean_q).get()  # noqa
                            if api_res and api_res.value:
                                self.logger.debug(f"API search returned {len(api_res.value)} result(s)")
                                for item in api_res.value:
                                    if not getattr(item, "file", None) or not item.name:
                                        continue
                                    name = item.name
                                    # Extension check
                                    ext_ok = True
                                    if wanted_ext:
                                        ext_ok = name.lower().endswith(f".{wanted_ext}")
                                    # Pattern check (supports literal/regex/wildcard via existing helper)
                                    name_ok = self._matches_pattern(name, pattern)
                                    item_path = self._get_item_path_from_item(item)  # drive-root relative

                                    self.logger.info(
                                        f"🔎 [API] {item_path} "
                                        f"(ext: {'✓' if ext_ok else '×'}, name: {'✓' if name_ok else '×'})"
                                    )

                                    if ext_ok and name_ok and self._in_dir(item_path, directory):
                                        found_files.append({
                                            "item": item,
                                            "path": item_path,
                                            "server_relative_url": item_path
                                        })
                                        self.logger.info(f"✅ [API] Match: {item_path}")
                            else:
                                self.logger.debug("API search returned no results")
                        except Exception as api_err:
                            self.logger.warning(f"API search failed: {api_err}")

                # Fallback to recursive (or if API found nothing)
                if not found_files:
                    self.logger.info(
                        f"No API results or pattern not API-safe. Recursive in '{directory or '/'}'..."
                    )
                    found_files = await self._search_pattern_recursive(
                        drive_id=drive_id,
                        directory=directory,
                        pattern=pattern,
                        wanted_ext=wanted_ext
                    )

                if not found_files:
                    err = f"No files found for '{pattern or '<empty>'}' in '{directory_raw}'"
                    self.logger.error(err)
                    raise RuntimeError(err)

                destinations.extend(found_files)
                self.logger.info(
                    f"=== Found {len(found_files)} file(s) for '{pattern or '<empty>'}' ==="
                )

            # Warn (do not fail) on name-count mismatch
            desired = getattr(self, "_filenames", None)
            if desired and len(desired) != len(destinations):
                self.logger.warning(
                    f"⚠️ Matched files ({len(destinations)}) != self._filenames ({len(desired)}). "
                    f"Downloads will keep original names where needed."
                )

            return destinations

        except Exception as e:
            self.logger.error(f"File search failed: {e}")
            raise RuntimeError(f"File search failed: {e}") from e

    def _matches_pattern(self, filename: str, pattern: str) -> bool:
        """
        Check if filename matches the search pattern with detailed logging.
        """
        try:
            # Convert shell-style wildcards to regex if needed
            if '*' in pattern and '.*' not in pattern:
                # Simple wildcard pattern like "mkdocs*.yml"
                regex_pattern = pattern.replace("*", ".*").replace("?", ".")
                # Add anchors for exact matching
                regex_pattern = f"^{regex_pattern}$"
            elif '.*' in pattern or '[' in pattern or '^' in pattern or '$' in pattern:
                # Already a regex pattern
                regex_pattern = pattern
            else:
                # Exact match
                regex_pattern = f"^{re.escape(pattern)}$"

            # self.logger.debug(f"Pattern matching: '{filename}' against regex '{regex_pattern}'")
            return bool(re.match(regex_pattern, filename, re.IGNORECASE))

        except re.error as e:
            self.logger.warning(
                f"Regex pattern '{pattern}' failed: {e}, falling back to substring match"
            )
            # Remove regex characters and do substring match
            clean_pattern = re.sub(r'[.*+?^${}()|[\]\\]', '', pattern)
            result = clean_pattern.lower() in filename.lower()
            self.logger.debug(f"Substring match result: {result}")
            return result

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
                with contextlib.suppress(Exception):
                    web_url = item.web_url

                    # Look for the document library part in the URL
                    if "/Shared%20Documents/" in web_url:
                        path_part = web_url.split("/Shared%20Documents/", 1)[1]
                        return unquote(path_part)
                    elif "/Shared Documents/" in web_url:
                        path_part = web_url.split("/Shared Documents/", 1)[1]
                        return unquote(path_part)

            # Final fallback: just return the filename
            return item.name or ""

        except Exception as e:
            self.logger.debug(f"Error extracting path from item: {e}")
            return item.name or ""

    def _is_in_target_directory(self, file_path: str, target_directory: str) -> bool:
        """
        Check if a file path is within the target directory.
        """
        # Normalize paths
        file_path = file_path.strip().strip("/")
        target_directory = target_directory.strip().strip("/")

        # Remove "Shared Documents" prefix if present in target but not in file path
        if target_directory.startswith("Shared Documents/"):
            target_dir_without_prefix = target_directory[17:]  # Remove "Shared Documents/"
            if target_dir_without_prefix in file_path:
                return True

        # Direct directory match
        if target_directory in file_path:
            return True

        # Check if file is in subdirectory
        file_dir = "/".join(file_path.split("/")[:-1])  # Remove filename
        return file_dir == target_directory or file_dir.endswith(f"/{target_directory}")

    async def _search_pattern_recursive(
        self,
        drive_id: str,
        directory: str,
        pattern: str,
        wanted_ext: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Depth-first search starting at the *target folder*.
        Logs EVERY file tested with ✓/× for extension and name.
        """
        matches: List[Dict[str, Any]] = []
        counter = {"tested": 0}

        # Resolve the starting folder using colon-path id (no item_with_path)
        start_path = (directory or "").strip().strip("/")
        if start_path:
            try:
                start_folder = await self.graph_client.drives.by_drive_id(drive_id)\
                    .items.by_drive_item_id(f"root:/{start_path}:/").get()
                self.logger.notice(
                    f"📂 Recursive start: '{start_path}' (ID: {start_folder.id})"
                )
            except Exception as e:
                # If normalization is correct and the folder truly exists (as uploads did),
                # this should not hit. Log and re-raise to avoid silently walking the root.
                self.logger.error(f"❌ Start folder not found for '{start_path}': {e}")
                raise
        else:
            start_folder = await self.graph_client.drives.by_drive_id(drive_id).root.get()
            self.logger.notice("📂 Recursive start: drive root")

        matcher = self._matches_pattern  # your existing helper

        async def _dfs(folder_id: str, base_rel_path: str):
            children = await self.graph_client.drives.by_drive_id(drive_id)\
                .items.by_drive_item_id(folder_id).children.get()
            if not children or not children.value:
                return

            for entry in children.value:
                if getattr(entry, "folder", None):
                    sub_rel = f"{base_rel_path}/{entry.name}".strip("/")
                    await _dfs(entry.id, sub_rel)
                    continue
                if not getattr(entry, "file", None) or not entry.name:
                    continue

                name = entry.name.strip()
                # Extension check
                ext_ok = True
                if wanted_ext:
                    ext_ok = name.lower().endswith("." + wanted_ext)

                # Pattern check (supports literal/regex/wildcard)
                name_ok = matcher(name, pattern)

                # Compute full path (drive-root relative) for logging/return
                full_path = await self._get_item_full_path(drive_id, entry.id)

                counter["tested"] += 1
                # self.logger.debug(
                #     f"🔎 [{counter['tested']}] {full_path}  "
                #     f"(ext: {'✓' if ext_ok else '×'}, name: {'✓' if name_ok else '×'})"
                # )

                if ext_ok and name_ok:
                    matches.append({
                        "item": entry,
                        "path": full_path,
                        "server_relative_url": full_path
                    })
                    self.logger.info(f"✅ Match: {full_path}")

        await _dfs(start_folder.id, start_path)
        return matches

    async def _get_item_full_path(self, drive_id: str, item_id: str) -> str:
        """
        Get the full server relative path of an item.
        """
        try:
            item = await self.graph_client.drives.by_drive_id(drive_id).items.by_drive_item_id(item_id).get()

            if hasattr(item, 'parent_reference') and item.parent_reference:
                parent_path = item.parent_reference.path or ""
                if parent_path.startswith("/drive/root:"):
                    parent_path = parent_path[12:]

                full_path = f"{parent_path}/{item.name}".replace("//", "/").lstrip("/")
                return full_path
            else:
                return item.name or ""

        except Exception as e:
            self.logger.warning(f"Could not get full path for item {item_id}: {e}")
            return ""

    async def _resolve_existing_directory(
        self,
        drive_id: str,
        directory_raw: str,
        drive_info,
    ):
        """
        Resolve an existing folder under the drive.
        Tries the normalized directory; if not found, drops the first path segment and retries.
        Returns (folder_item, used_directory_relative_to_drive_root).
        """
        directory_raw = (directory_raw or "").strip()
        dir_norm = self._normalize_directory(directory_raw, drive_info)

        candidates = []
        if dir_norm:
            candidates.append(dir_norm)
            if "/" in dir_norm:
                candidates.append(dir_norm.split("/", 1)[1])
        else:
            candidates.append("")

        last_err = None
        for cand in candidates:
            colon_id = f"root:/{cand}:/".replace("//", "/") if cand else "root:/"
            try:
                folder = await self.graph_client.drives.by_drive_id(drive_id)\
                    .items.by_drive_item_id(colon_id).get()
                if getattr(folder, "folder", None):
                    self.logger.debug(
                        f"Resolved directory '{directory_raw}' -> '{cand or '/'}' (ID: {folder.id})"
                    )
                    return folder, cand
            except Exception as e:
                last_err = e
                self.logger.debug(
                    f"Directory candidate not found '{cand or '/'}': {e}"
                )

        raise RuntimeError(
            f"Start directory not found: '{directory_raw}' (normalized '{dir_norm}')"
        ) from last_err

    async def file_lookup(
        self,
        files: Optional[List[Dict[str, str]]] = None,
    ) -> List[Dict[str, Any]]:
        """
        Resolve exact files (no search) into 'destinations' items.
        Robustly handles extra leading path segments like 'TROC/...'
        and resolves the file under the resolved parent folder ID.
        """
        specs = files if files is not None else getattr(self, "_srcfiles", [])
        if not specs:
            raise RuntimeError("file_lookup: no files provided and self._srcfiles is empty")

        drive_info = await self._resolve_drive()
        drive_id = drive_info.id

        destinations: List[Dict[str, Any]] = []

        for spec in specs:
            directory_raw: str = (spec.get("directory") or "").strip()
            filename_raw: str = (spec.get("filename") or "").strip()
            if not filename_raw:
                self.logger.warning("file_lookup: skipping entry without 'filename'")
                continue

            # Parse the directory to extract library and path
            library_name, path_within_library = self._parse_directory_path(directory_raw)

            self.logger.notice(
                f"Looking up file: '{filename_raw}' in library '{library_name}', path '{path_within_library}'"
            )

            # Get the specific library
            try:
                drive_info = await self._resolve_drive(library_name)
                drive_id = drive_info.id
            except Exception as e:
                self.logger.error(f"Failed to access library '{library_name}': {e}")
                continue

            # Build the Microsoft Graph API path within the library
            if path_within_library:
                colon_id = f"root:/{path_within_library}/{filename_raw}:"
            else:
                colon_id = f"root:/{filename_raw}:"

            self.logger.debug(
                f"Using Graph API item ID: '{colon_id}' in library '{library_name}'"
            )
            # First try direct by parent folder ID + :/filename:/ (avoids full-path encoding pitfalls)
            try:
                file_item = await self.graph_client.drives.by_drive_id(drive_id)\
                    .items.by_drive_item_id(colon_id).get()
            except Exception as e:
                self.logger.error(
                    f"Direct lookup failed for '{filename_raw}' in library '{library_name}', path '{path_within_library}', error: {e}"
                )

                # Fallback: list children and match by exact name
                try:
                    if path_within_library:
                        # Get the directory first
                        dir_colon_id = f"root:/{path_within_library}:"
                        folder = await self.graph_client.drives.by_drive_id(drive_id)\
                            .items.by_drive_item_id(dir_colon_id).get()
                    else:
                        # Use root of this library
                        folder = await self.graph_client.drives.by_drive_id(drive_id).root.get()

                    # List directory contents
                    children = await self.graph_client.drives.by_drive_id(drive_id)\
                        .items.by_drive_item_id(folder.id).children.get()

                    found_item = None
                    if children and children.value:
                        self.logger.debug(
                            f"Directory contains {len(children.value)} items:"
                        )
                        for child in children.value:
                            self.logger.debug(f"  - {child.name} ({'file' if child.file else 'folder'})")
                            if child.file and child.name and child.name == filename_raw:
                                found_item = child
                                break
                    if found_item:
                        item = found_item
                        self.logger.info(f"Found via fallback search: {filename_raw}")
                    else:
                        self.logger.error(f"File '{filename_raw}' not found in library '{library_name}', path '{path_within_library or 'root'}'")
                        continue
                except Exception as e2:
                    self.logger.error(f"Fallback search failed: {e2}")
                    continue

            # Build drive-root-relative path for return/logging
            full_path = await self._get_item_full_path(drive_id, file_item.id)
            destinations.append({
                "item": file_item,
                "path": full_path,
                "server_relative_url": full_path
            })
            self.logger.info(f"✅ Found: {full_path}")

        return destinations or None

    async def debug_root_structure(self):
        """Quick debug to see what's actually at the root of this SharePoint site."""
        try:
            drive_info = await self._resolve_drive()
            drive_id = drive_info.id

            # Get root folder first, then its children
            root = await self.graph_client.drives.by_drive_id(drive_id).root.get()
            children = await self.graph_client.drives.by_drive_id(drive_id).items.by_drive_item_id(root.id).children.get()

            if children and children.value:
                self.logger.notice("=== ROOT STRUCTURE ===")
                for child in children.value:
                    if child.folder:
                        self.logger.notice(f"📁 {child.name}/")
                    else:
                        self.logger.notice(f"📄 {child.name}")
            else:
                self.logger.error("No items found at root")

        except Exception as e:
            self.logger.error(f"Debug failed: {e}")
