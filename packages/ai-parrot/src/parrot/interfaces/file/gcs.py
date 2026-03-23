from typing import BinaryIO, Optional, List, Union
import mimetypes
from pathlib import Path
import logging
import asyncio
from datetime import datetime, timedelta
from io import BytesIO, StringIO
import fnmatch
import json
import google.auth
from google.cloud import storage
from google.oauth2 import service_account
from .abstract import FileManagerInterface, FileMetadata


class GCSFileManager(FileManagerInterface):
    """File manager for Google Cloud Storage operations"""

    # Resumable upload threshold (Google recommends 5MB+)
    RESUMABLE_THRESHOLD = 5 * 1024 * 1024  # 5MB
    CHUNK_SIZE = 256 * 1024  # 256KB upload chunks

    def __init__(
        self,
        bucket_name: str,
        prefix: str = "",
        json_credentials: Optional[dict] = None,
        credentials: Optional[str] = None,
        scopes: Optional[List[str]] = None,
        project: Optional[str] = None,
        resumable_threshold: Optional[int] = None,
        **kwargs
    ):
        """
        Initialize GCS file manager.

        Args:
            bucket_name: GCS bucket name
            prefix: Default prefix/folder for all operations
            json_credentials: Service account credentials as dict
            credentials: Path to service account JSON file
            scopes: OAuth2 scopes (default: cloud-platform)
            project: GCP project ID (auto-detected if not provided)
            resumable_threshold: File size threshold for resumable upload
            **kwargs: Additional arguments
        """
        self.bucket_name = bucket_name
        self.prefix = prefix.rstrip('/') + '/' if prefix else ''
        self.scopes = scopes or ['https://www.googleapis.com/auth/cloud-platform']
        self.resumable_threshold = resumable_threshold or self.RESUMABLE_THRESHOLD
        self.logger = logging.getLogger('ai_parrot.storage.GCS')

        # Initialize credentials
        scoped_credentials = None
        if json_credentials:
            # Using JSON credentials dict
            self.credentials = service_account.Credentials.from_service_account_info(
                json_credentials
            )
            self.project = project or json_credentials.get('project_id')
        elif credentials:
            # Using service account file
            self.credentials = service_account.Credentials.from_service_account_file(
                credentials
            )
            # Extract project from file if not provided
            if not project:
                with open(credentials) as f:
                    cred_data = json.load(f)
                    self.project = cred_data.get('project_id')
            else:
                self.project = project
        else:
            # Use default credentials
            self.credentials, self.project = google.auth.default(
                scopes=self.scopes
            )
            if project:
                self.project = project

        # Apply scopes if provided
        if self.scopes and hasattr(self.credentials, 'with_scopes'):
            scoped_credentials = self.credentials.with_scopes(self.scopes)

        # Initialize GCS client
        if scoped_credentials:
            self.client = storage.Client(
                credentials=scoped_credentials,
                project=self.project
            )
        else:
            self.client = storage.Client(
                credentials=self.credentials,
                project=self.project
            )

        self.bucket = self.client.bucket(bucket_name)

        self.logger.info(f"Started GCSFileManager for bucket: {bucket_name}")

    def _resolve_path(self, path: str) -> str:
        """Resolve path with prefix"""
        path = path.lstrip('/')

        if self.prefix and not path.startswith(self.prefix):
            path = self.prefix + path

        return path

    def _strip_prefix(self, path: str) -> str:
        """Remove prefix from path for display"""
        if self.prefix and path.startswith(self.prefix):
            return path[len(self.prefix):]
        return path

    def _blob_to_metadata(self, blob: storage.Blob) -> FileMetadata:
        """Convert GCS Blob to FileMetadata"""
        # Generate signed URL (valid for 1 hour)
        try:
            url = blob.generate_signed_url(
                version="v4",
                expiration=timedelta(hours=1),
                method="GET"
            )
        except Exception:
            # Fallback to public URL if signing fails
            url = blob.public_url

        return FileMetadata(
            name=Path(blob.name).name,
            path=self._strip_prefix(blob.name),
            size=blob.size or 0,
            content_type=blob.content_type,
            modified_at=blob.updated,
            url=url
        )

    async def list_files(
        self,
        path: str = "",
        pattern: str = "*"
    ) -> List[FileMetadata]:
        """List files matching pattern in GCS bucket"""
        prefix = self._resolve_path(path)

        def _list():
            files = []
            blobs = self.client.list_blobs(
                self.bucket_name,
                prefix=prefix
            )

            for blob in blobs:
                # Skip directory markers
                if blob.name.endswith('/'):
                    continue

                name = Path(blob.name).name

                # Apply pattern matching
                if fnmatch.fnmatch(name, pattern):
                    files.append(self._blob_to_metadata(blob))

            return sorted(files, key=lambda x: x.name)

        return await asyncio.to_thread(_list)

    async def get_file_url(self, path: str, expiry: int = 3600) -> str:
        """Get signed URL for GCS blob"""
        blob_name = self._resolve_path(path)

        def _get_url():
            blob = self.bucket.blob(blob_name)

            if not blob.exists():
                raise FileNotFoundError(f"File not found: {path}")

            url = blob.generate_signed_url(
                version="v4",
                expiration=timedelta(seconds=expiry),
                method="GET"
            )
            return url

        return await asyncio.to_thread(_get_url)

    async def upload_file(
        self,
        source: BinaryIO | Path,
        destination: str
    ) -> FileMetadata:
        """
        Upload file to GCS with automatic resumable upload for large files.

        Files larger than resumable_threshold will use resumable upload.
        """
        blob_name = self._resolve_path(destination)

        # Guess content type
        content_type, _ = mimetypes.guess_type(destination)

        def _upload():
            blob = self.bucket.blob(blob_name)

            if content_type:
                blob.content_type = content_type

            if isinstance(source, Path):
                file_size = source.stat().st_size

                # Use resumable upload for large files
                if file_size >= self.resumable_threshold:
                    blob.chunk_size = self.CHUNK_SIZE
                    blob.upload_from_filename(
                        str(source),
                        timeout=300  # 5 minute timeout
                    )
                else:
                    blob.upload_from_filename(str(source))
            else:
                # For file objects, determine size
                current_pos = source.tell()
                source.seek(0, 2)
                file_size = source.tell()
                source.seek(current_pos)

                if file_size >= self.resumable_threshold:
                    blob.chunk_size = self.CHUNK_SIZE

                source.seek(0)
                blob.upload_from_file(source, timeout=300)

            # Reload blob to get updated metadata
            blob.reload()
            return self._blob_to_metadata(blob)

        return await asyncio.to_thread(_upload)

    async def download_file(
        self,
        source: str,
        destination: Path | BinaryIO
    ) -> Path:
        """Download file from GCS"""
        blob_name = self._resolve_path(source)

        def _download():
            blob = self.bucket.blob(blob_name)

            if not blob.exists():
                raise FileNotFoundError(f"File not found: {source}")

            if isinstance(destination, Path):
                destination.parent.mkdir(parents=True, exist_ok=True)
                blob.download_to_filename(str(destination))
                return destination
            else:
                blob.download_to_file(destination)
                return Path(blob_name)

        return await asyncio.to_thread(_download)

    async def copy_file(self, source: str, destination: str) -> FileMetadata:
        """Copy blob within GCS bucket"""
        source_blob_name = self._resolve_path(source)
        dest_blob_name = self._resolve_path(destination)

        def _copy():
            source_blob = self.bucket.blob(source_blob_name)

            if not source_blob.exists():
                raise FileNotFoundError(f"Source file not found: {source}")

            # Copy blob
            dest_blob = self.bucket.copy_blob(
                source_blob,
                self.bucket,
                dest_blob_name
            )

            return self._blob_to_metadata(dest_blob)

        return await asyncio.to_thread(_copy)

    async def delete_file(self, path: str) -> bool:
        """Delete blob from GCS"""
        blob_name = self._resolve_path(path)

        def _delete():
            blob = self.bucket.blob(blob_name)

            if not blob.exists():
                return False

            blob.delete()
            return True

        return await asyncio.to_thread(_delete)

    async def exists(self, path: str) -> bool:
        """Check if blob exists in GCS"""
        blob_name = self._resolve_path(path)

        def _check():
            blob = self.bucket.blob(blob_name)
            return blob.exists()

        return await asyncio.to_thread(_check)

    async def get_file_metadata(self, path: str) -> FileMetadata:
        """Get metadata of GCS blob"""
        blob_name = self._resolve_path(path)

        def _get_metadata():
            blob = self.bucket.blob(blob_name)

            if not blob.exists():
                raise FileNotFoundError(f"File not found: {path}")

            blob.reload()  # Ensure we have latest metadata
            return self._blob_to_metadata(blob)

        return await asyncio.to_thread(_get_metadata)

    async def create_file(self, path: str, content: bytes) -> bool:
        """Create blob in GCS with content"""
        blob_name = self._resolve_path(path)

        # Guess content type
        content_type, _ = mimetypes.guess_type(path)

        def _create():
            blob = self.bucket.blob(blob_name)

            if content_type:
                blob.content_type = content_type

            blob.upload_from_string(content)
            return True

        return await asyncio.to_thread(_create)

    async def create_from_bytes(
        self,
        path: str,
        source: Union[bytes, BytesIO, StringIO],
        encoding: str = 'utf-8'
    ) -> FileMetadata:
        """Create GCS blob from bytes, BytesIO, or StringIO"""
        blob_name = self._resolve_path(path)

        # Guess content type
        content_type, _ = mimetypes.guess_type(path)

        def _create():
            blob = self.bucket.blob(blob_name)

            if content_type:
                blob.content_type = content_type

            if isinstance(source, bytes):
                blob.upload_from_string(source)
            elif isinstance(source, BytesIO):
                source.seek(0)
                blob.upload_from_file(source)
            elif isinstance(source, StringIO):
                source.seek(0)
                content = source.read().encode(encoding)
                blob.upload_from_string(content)
            else:
                raise TypeError(
                    f"source must be bytes, BytesIO, or StringIO, got {type(source)}"
                )

            blob.reload()
            return self._blob_to_metadata(blob)

        return await asyncio.to_thread(_create)
