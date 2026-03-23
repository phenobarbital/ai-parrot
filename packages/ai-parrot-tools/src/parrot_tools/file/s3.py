from typing import BinaryIO, Optional, List, Union
import asyncio
import contextlib
from pathlib import Path
import mimetypes
from datetime import datetime
from io import BytesIO, StringIO
import fnmatch
import aioboto3
from botocore.exceptions import ClientError
from .abstract import FileManagerInterface, FileMetadata
from ...conf import AWS_CREDENTIALS


class S3FileManager(FileManagerInterface):
    """File manager for AWS S3 bucket operations"""

    # Multipart upload configuration
    MULTIPART_THRESHOLD = 100 * 1024 * 1024  # 100MB
    MULTIPART_CHUNKSIZE = 10 * 1024 * 1024   # 10MB per part
    MAX_CONCURRENCY = 10  # Concurrent part uploads

    def __init__(
        self,
        bucket_name: Optional[str] = None,
        aws_id: str = 'default',
        region_name: Optional[str] = None,
        prefix: str = "",
        multipart_threshold: Optional[int] = None,
        multipart_chunksize: Optional[int] = None,
        max_concurrency: Optional[int] = None,
        **kwargs
    ):
        """
        Initialize S3 file manager.

        Args:
            bucket_name: S3 bucket name (if None, read from credentials)
            aws_id: Identifier for credentials in AWS_CREDENTIALS dict
            region_name: AWS region (if None, read from credentials)
            prefix: Default prefix/folder for all operations
            multipart_threshold: File size threshold for multipart upload (bytes)
            multipart_chunksize: Size of each part in multipart upload (bytes)
            max_concurrency: Max concurrent part uploads
            **kwargs: Additional arguments, including 'credentials' override
        """
        # Get credentials from config or kwargs
        credentials = kwargs.get('credentials', AWS_CREDENTIALS.get(aws_id, 'default'))

        if isinstance(credentials, str) and credentials == 'default':
            credentials = AWS_CREDENTIALS.get('default', {})

        # Extract bucket_name from credentials if not provided
        self.bucket_name = bucket_name or credentials.get('bucket_name')
        if not self.bucket_name:
            raise ValueError("bucket_name must be provided or present in credentials")

        # Build AWS config
        self.aws_config = {
            'aws_access_key_id': credentials.get('aws_access_key_id'),
            'aws_secret_access_key': credentials.get('aws_secret_access_key'),
            'region_name': region_name or credentials.get('region_name', 'us-east-1'),
        }

        # Add optional session token if present
        if 'aws_session_token' in credentials:
            self.aws_config['aws_session_token'] = credentials['aws_session_token']

        # Remove None values
        self.aws_config = {k: v for k, v in self.aws_config.items() if v is not None}

        self.prefix = prefix.rstrip('/') + '/' if prefix else ''
        self.session = aioboto3.Session(**self.aws_config)

        # Multipart upload configuration
        self.multipart_threshold = multipart_threshold or self.MULTIPART_THRESHOLD
        self.multipart_chunksize = multipart_chunksize or self.MULTIPART_CHUNKSIZE
        self.max_concurrency = max_concurrency or self.MAX_CONCURRENCY

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

    async def _get_object_metadata(self, key: str) -> FileMetadata:
        """Get metadata for an S3 object"""
        async with self.session.client('s3') as s3:
            try:
                response = await s3.head_object(Bucket=self.bucket_name, Key=key)

                url = await s3.generate_presigned_url(
                    'get_object',
                    Params={'Bucket': self.bucket_name, 'Key': key},
                    ExpiresIn=3600
                )

                return FileMetadata(
                    name=Path(key).name,
                    path=self._strip_prefix(key),
                    size=response['ContentLength'],
                    content_type=response.get('ContentType'),
                    modified_at=response['LastModified'],
                    url=url
                )
            except ClientError as e:
                if e.response['Error']['Code'] == '404':
                    raise FileNotFoundError(
                        f"File not found: {key}"
                    ) from e
                raise

    async def _upload_part(
        self,
        s3_client,
        upload_id: str,
        key: str,
        part_number: int,
        data: bytes
    ) -> dict:
        """Upload a single part in multipart upload"""
        response = await s3_client.upload_part(
            Bucket=self.bucket_name,
            Key=key,
            UploadId=upload_id,
            PartNumber=part_number,
            Body=data
        )

        return {
            'PartNumber': part_number,
            'ETag': response['ETag']
        }

    async def _multipart_upload(
        self,
        source: Path | BinaryIO,
        key: str,
        content_type: Optional[str]
    ) -> FileMetadata:
        """Perform multipart upload for large files"""
        async with self.session.client('s3') as s3:
            # Initiate multipart upload
            extra_args = {}
            if content_type:
                extra_args['ContentType'] = content_type

            response = await s3.create_multipart_upload(
                Bucket=self.bucket_name,
                Key=key,
                **extra_args
            )
            upload_id = response['UploadId']

            parts = []
            part_number = 1

            try:
                # Open file for reading
                if isinstance(source, Path):
                    file_obj = open(source, 'rb')
                    should_close = True
                else:
                    source.seek(0)
                    file_obj = source
                    should_close = False

                # Create upload tasks with concurrency limit
                semaphore = asyncio.Semaphore(self.max_concurrency)
                upload_tasks = []

                async def upload_with_semaphore(part_num: int, chunk: bytes):
                    async with semaphore:
                        return await self._upload_part(
                            s3, upload_id, key, part_num, chunk
                        )

                # Read and upload chunks
                while True:
                    chunk = file_obj.read(self.multipart_chunksize)
                    if not chunk:
                        break

                    task = asyncio.create_task(
                        upload_with_semaphore(part_number, chunk)
                    )
                    upload_tasks.append(task)
                    part_number += 1

                # Wait for all uploads to complete
                parts = await asyncio.gather(*upload_tasks)

                # Close file if we opened it
                if should_close:
                    file_obj.close()

                # Complete multipart upload
                await s3.complete_multipart_upload(
                    Bucket=self.bucket_name,
                    Key=key,
                    UploadId=upload_id,
                    MultipartUpload={'Parts': parts}
                )

                return await self._get_object_metadata(key)

            except Exception as e:
                # Abort multipart upload on error
                with contextlib.suppress(Exception):
                    await s3.abort_multipart_upload(
                        Bucket=self.bucket_name,
                        Key=key,
                        UploadId=upload_id
                    )
                raise IOError(f"Multipart upload failed: {e}")

    async def upload_file(
        self,
        source: BinaryIO | Path,
        destination: str
    ) -> FileMetadata:
        """
        Upload file to S3 with automatic multipart upload for large files.

        Files larger than multipart_threshold will use multipart upload
        with concurrent part uploads for better performance.
        """
        key = self._resolve_path(destination)

        # Guess content type
        content_type, _ = mimetypes.guess_type(destination)
        extra_args = {}
        if content_type:
            extra_args['ContentType'] = content_type

        # Determine file size
        if isinstance(source, Path):
            file_size = source.stat().st_size
        else:
            # For file objects, try to get size
            current_pos = source.tell()
            source.seek(0, 2)  # Seek to end
            file_size = source.tell()
            source.seek(current_pos)  # Reset position

        # Use multipart upload for large files
        if file_size >= self.multipart_threshold:
            return await self._multipart_upload(source, key, content_type)

        # Use standard upload for small files
        async with self.session.client('s3') as s3:
            try:
                if isinstance(source, Path):
                    await s3.upload_file(
                        str(source),
                        self.bucket_name,
                        key,
                        ExtraArgs=extra_args
                    )
                else:
                    source.seek(0)
                    await s3.upload_fileobj(
                        source,
                        self.bucket_name,
                        key,
                        ExtraArgs=extra_args
                    )

                return await self._get_object_metadata(key)

            except ClientError as e:
                raise IOError(
                    f"Failed to upload file: {e}"
                ) from e

    async def list_files(
        self,
        path: str = "",
        pattern: str = "*"
    ) -> List[FileMetadata]:
        """List files matching pattern in S3 bucket/prefix"""
        prefix = self._resolve_path(path)

        async with self.session.client('s3') as s3:
            try:
                paginator = s3.get_paginator('list_objects_v2')
                files = []

                async for page in paginator.paginate(
                    Bucket=self.bucket_name,
                    Prefix=prefix
                ):
                    if 'Contents' not in page:
                        continue

                    for obj in page['Contents']:
                        key = obj['Key']
                        name = Path(key).name

                        if key.endswith('/'):
                            continue

                        if fnmatch.fnmatch(name, pattern):
                            url = await s3.generate_presigned_url(
                                'get_object',
                                Params={'Bucket': self.bucket_name, 'Key': key},
                                ExpiresIn=3600
                            )

                            files.append(FileMetadata(
                                name=name,
                                path=self._strip_prefix(key),
                                size=obj['Size'],
                                content_type=None,
                                modified_at=obj['LastModified'],
                                url=url
                            ))

                return sorted(files, key=lambda x: x.name)

            except ClientError as e:
                if e.response['Error']['Code'] == 'NoSuchBucket':
                    raise ValueError(
                        f"Bucket not found: {self.bucket_name}"
                    ) from e
                raise

    async def get_file_url(self, path: str, expiry: int = 3600) -> str:
        """Get presigned URL for S3 object"""
        key = self._resolve_path(path)

        async with self.session.client('s3') as s3:
            try:
                return await s3.generate_presigned_url(
                    'get_object',
                    Params={'Bucket': self.bucket_name, 'Key': key},
                    ExpiresIn=expiry
                )
            except ClientError as e:
                if e.response['Error']['Code'] == '404':
                    raise FileNotFoundError(
                        f"File not found: {path}"
                    ) from e
                raise

    async def download_file(
        self,
        source: str,
        destination: Path | BinaryIO
    ) -> Path:
        """Download file from S3"""
        key = self._resolve_path(source)

        async with self.session.client('s3') as s3:
            try:
                if isinstance(destination, Path):
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    await s3.download_file(
                        self.bucket_name,
                        key,
                        str(destination)
                    )
                    return destination
                else:
                    response = await s3.get_object(
                        Bucket=self.bucket_name,
                        Key=key
                    )
                    async with response['Body'] as stream:
                        data = await stream.read()
                        destination.write(data)
                    return Path(key)

            except ClientError as e:
                if e.response['Error']['Code'] == 'NoSuchKey':
                    raise FileNotFoundError(
                        f"File not found: {source}"
                    ) from e
                raise

    async def copy_file(self, source: str, destination: str) -> FileMetadata:
        """Copy file within S3 bucket"""
        source_key = self._resolve_path(source)
        dest_key = self._resolve_path(destination)

        copy_source = {
            'Bucket': self.bucket_name,
            'Key': source_key
        }

        async with self.session.client('s3') as s3:
            try:
                await s3.copy_object(
                    CopySource=copy_source,
                    Bucket=self.bucket_name,
                    Key=dest_key
                )

                return await self._get_object_metadata(dest_key)

            except ClientError as e:
                if e.response['Error']['Code'] == 'NoSuchKey':
                    raise FileNotFoundError(
                        f"Source file not found: {source}"
                    ) from e
                raise

    async def delete_file(self, path: str) -> bool:
        """Delete file from S3"""
        key = self._resolve_path(path)

        async with self.session.client('s3') as s3:
            try:
                await s3.delete_object(
                    Bucket=self.bucket_name,
                    Key=key
                )
                return True
            except ClientError:
                return False

    async def exists(self, path: str) -> bool:
        """Check if file exists in S3"""
        key = self._resolve_path(path)

        async with self.session.client('s3') as s3:
            try:
                await s3.head_object(Bucket=self.bucket_name, Key=key)
                return True
            except ClientError:
                return False

    async def get_file_metadata(self, path: str) -> FileMetadata:
        """Get metadata of S3 object"""
        key = self._resolve_path(path)
        return await self._get_object_metadata(key)

    async def create_file(self, path: str, content: bytes) -> bool:
        """Create file in S3 with content"""
        key = self._resolve_path(path)

        content_type, _ = mimetypes.guess_type(path)
        extra_args = {}
        if content_type:
            extra_args['ContentType'] = content_type

        async with self.session.client('s3') as s3:
            try:
                await s3.put_object(
                    Bucket=self.bucket_name,
                    Key=key,
                    Body=content,
                    **extra_args
                )
                return True
            except ClientError as e:
                raise IOError(
                    f"Failed to create file: {e}"
                ) from e

    async def create_from_bytes(
        self,
        path: str,
        source: Union[bytes, BytesIO, StringIO],
        encoding: str = 'utf-8'
    ) -> FileMetadata:
        """Create S3 object from bytes, BytesIO, or StringIO"""
        key = self._resolve_path(path)

        content_type, _ = mimetypes.guess_type(path)
        extra_args = {}
        if content_type:
            extra_args['ContentType'] = content_type

        async with self.session.client('s3') as s3:
            try:
                if isinstance(source, bytes):
                    body = source
                elif isinstance(source, BytesIO):
                    source.seek(0)
                    body = source.read()
                elif isinstance(source, StringIO):
                    source.seek(0)
                    body = source.read().encode(encoding)
                else:
                    raise TypeError(
                        f"source must be bytes, BytesIO, or StringIO, got {type(source)}"
                    )

                await s3.put_object(
                    Bucket=self.bucket_name,
                    Key=key,
                    Body=body,
                    **extra_args
                )

                return await self._get_object_metadata(key)

            except ClientError as e:
                raise IOError(
                    f"Failed to create file: {e}"
                ) from e
