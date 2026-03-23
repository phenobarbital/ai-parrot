import contextlib
import tempfile
import shutil
import mimetypes
from pathlib import Path
from typing import BinaryIO, Optional, List, Union
from datetime import datetime
from io import BytesIO, StringIO
import fnmatch
import asyncio
import atexit
from .abstract import FileManagerInterface, FileMetadata


class TempFileManager(FileManagerInterface):
    """File manager for temporary file storage"""

    def __init__(
        self,
        prefix: str = "ai_parrot_",
        cleanup_on_exit: bool = True,
        cleanup_on_delete: bool = True
    ):
        """
        Initialize temporary file manager.

        Args:
            prefix: Prefix for temp directory name
            cleanup_on_exit: Auto-cleanup temp directory on program exit
            cleanup_on_delete: Auto-cleanup when instance is deleted
        """
        self.temp_dir = tempfile.TemporaryDirectory(prefix=prefix)
        self.base_path = Path(self.temp_dir.name)
        self.cleanup_on_exit = cleanup_on_exit
        self.cleanup_on_delete = cleanup_on_delete

        if cleanup_on_exit:
            atexit.register(self.cleanup)

    def __del__(self):
        """Cleanup on deletion if configured"""
        if self.cleanup_on_delete:
            self.cleanup()

    def cleanup(self):
        """Manually cleanup temporary directory"""
        with contextlib.suppress(AttributeError, FileNotFoundError):
            if hasattr(self, 'temp_dir'):
                self.temp_dir.cleanup()

    async def __aenter__(self):
        """Context manager entry"""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit with cleanup"""
        self.cleanup()
        return False

    def _resolve_path(self, path: str) -> Path:
        """Resolve path within temp directory"""
        target = Path(path)

        if not target.is_absolute():
            target = self.base_path / target

        try:
            resolved = target.resolve(strict=False)
        except (OSError, RuntimeError) as e:
            raise ValueError(f"Cannot resolve path: {path}") from e

        # Ensure path is within temp directory
        try:
            resolved.relative_to(self.base_path.resolve())
        except ValueError as e:
            raise ValueError(
                f"Path '{path}' escapes temp directory '{self.base_path}'"
            ) from e

        return resolved

    def _get_file_metadata(self, path: Path) -> FileMetadata:
        """Extract metadata from a file path"""
        stat = path.stat()
        content_type, _ = mimetypes.guess_type(str(path))

        return FileMetadata(
            name=path.name,
            path=str(path.relative_to(self.base_path)),
            size=stat.st_size,
            content_type=content_type,
            modified_at=datetime.fromtimestamp(stat.st_mtime),
            url=path.as_uri()
        )

    async def list_files(
        self,
        path: str = "",
        pattern: str = "*"
    ) -> List[FileMetadata]:
        """List files matching pattern in temp directory"""
        target_dir = self._resolve_path(path) if path else self.base_path

        if not target_dir.exists():
            raise FileNotFoundError(f"Directory not found: {path}")

        if not target_dir.is_dir():
            raise ValueError(f"Path is not a directory: {path}")

        def _list():
            files = []
            for item in target_dir.iterdir():
                if fnmatch.fnmatch(item.name, pattern) and item.is_file():
                    files.append(self._get_file_metadata(item))

            return sorted(files, key=lambda x: x.name)

        return await asyncio.to_thread(_list)

    async def get_file_url(self, path: str, expiry: int = 3600) -> str:
        """Get file:// URL for temp file"""
        target = self._resolve_path(path)

        if not target.exists():
            raise FileNotFoundError(f"File not found: {path}")

        return target.as_uri()

    async def upload_file(
        self,
        source: BinaryIO | Path,
        destination: str
    ) -> FileMetadata:
        """Upload/copy a file to temp storage"""
        dest_path = self._resolve_path(destination)
        dest_path.parent.mkdir(parents=True, exist_ok=True)

        def _upload():
            if isinstance(source, Path):
                shutil.copy2(str(source), str(dest_path))
            else:
                with open(dest_path, 'wb') as f:
                    shutil.copyfileobj(source, f)

            return self._get_file_metadata(dest_path)

        return await asyncio.to_thread(_upload)

    async def download_file(
        self,
        source: str,
        destination: Path | BinaryIO
    ) -> Path:
        """
        Download/move file from temp to permanent storage.
        This MOVES the file out of temp storage.
        """
        source_path = self._resolve_path(source)

        if not source_path.exists():
            raise FileNotFoundError(f"Source file not found: {source}")

        if not source_path.is_file():
            raise ValueError(f"Source is not a file: {source}")

        def _download():
            if isinstance(destination, Path):
                destination.parent.mkdir(parents=True, exist_ok=True)
                # Move instead of copy (temp files are ephemeral)
                shutil.move(str(source_path), str(destination))
                return destination
            else:
                # For file objects, we have to copy then delete
                with open(source_path, 'rb') as src:
                    shutil.copyfileobj(src, destination)
                source_path.unlink()
                return source_path

        return await asyncio.to_thread(_download)

    async def copy_file(self, source: str, destination: str) -> FileMetadata:
        """
        Copy/move file from temp to permanent storage or within temp.

        If destination is outside temp directory, this MOVES the file.
        If destination is inside temp directory, this COPIES the file.
        """
        source_path = self._resolve_path(source)

        if not source_path.exists():
            raise FileNotFoundError(f"Source file not found: {source}")

        if not source_path.is_file():
            raise ValueError(f"Source is not a file: {source}")

        # Check if destination is outside temp directory
        dest_path = Path(destination)
        if not dest_path.is_absolute():
            # Relative path means within temp
            dest_path = self._resolve_path(destination)
            is_external = False
        else:
            # Absolute path - check if it's outside temp
            try:
                dest_path.relative_to(self.base_path.resolve())
                is_external = False
            except ValueError:
                is_external = True

        dest_path.parent.mkdir(parents=True, exist_ok=True)

        def _copy():
            if is_external:
                # Moving to permanent storage
                shutil.move(str(source_path), str(dest_path))
            else:
                # Copying within temp
                shutil.copy2(str(source_path), str(dest_path))

            return FileMetadata(
                name=dest_path.name,
                path=str(dest_path),
                size=dest_path.stat().st_size,
                content_type=mimetypes.guess_type(str(dest_path))[0],
                modified_at=datetime.fromtimestamp(dest_path.stat().st_mtime),
                url=dest_path.as_uri()
            )

        return await asyncio.to_thread(_copy)

    async def delete_file(self, path: str) -> bool:
        """Delete a temp file"""
        target = self._resolve_path(path)

        if not target.exists():
            return False

        if not target.is_file():
            raise ValueError(f"Path is not a file: {path}")

        def _delete():
            target.unlink()
            return True

        return await asyncio.to_thread(_delete)

    async def exists(self, path: str) -> bool:
        """Check if temp file exists"""
        try:
            target = self._resolve_path(path)
            return await asyncio.to_thread(lambda: target.is_file())
        except (ValueError, OSError):
            return False

    async def get_file_metadata(self, path: str) -> FileMetadata:
        """Get metadata of a temp file"""
        target = self._resolve_path(path)

        if not target.exists():
            raise FileNotFoundError(f"File not found: {path}")

        if not target.is_file():
            raise ValueError(f"Path is not a file: {path}")

        return await asyncio.to_thread(lambda: self._get_file_metadata(target))

    async def create_file(self, path: str, content: bytes) -> bool:
        """Create a temp file with content"""
        target = self._resolve_path(path)
        target.parent.mkdir(parents=True, exist_ok=True)

        def _create():
            with open(target, 'wb') as f:
                f.write(content)
            return True

        return await asyncio.to_thread(_create)

    async def create_from_bytes(
        self,
        path: str,
        source: Union[bytes, BytesIO, StringIO],
        encoding: str = 'utf-8'
    ) -> FileMetadata:
        """Create a temp file from bytes, BytesIO, or StringIO object"""
        target = self._resolve_path(path)
        target.parent.mkdir(parents=True, exist_ok=True)

        def _create():
            if isinstance(source, bytes):
                with open(target, 'wb') as f:
                    f.write(source)
            elif isinstance(source, BytesIO):
                source.seek(0)
                with open(target, 'wb') as f:
                    f.write(source.read())
            elif isinstance(source, StringIO):
                source.seek(0)
                content = source.read()
                with open(target, 'w', encoding=encoding) as f:
                    f.write(content)
            else:
                raise TypeError(
                    f"source must be bytes, BytesIO, or StringIO, got {type(source)}"
                )

            return self._get_file_metadata(target)

        return await asyncio.to_thread(_create)
