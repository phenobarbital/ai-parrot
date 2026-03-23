import os
import shutil
import mimetypes
from pathlib import Path
from typing import BinaryIO, Optional, List, Union
from datetime import datetime
from io import BytesIO, StringIO
import fnmatch
import asyncio
from .abstract import FileManagerInterface, FileMetadata


class LocalFileManager(FileManagerInterface):
    """File manager for local filesystem operations"""

    def __init__(
        self,
        base_path: Optional[Path] = None,
        create_base: bool = True,
        follow_symlinks: bool = False,
        sandboxed: bool = True
    ):
        """
        Initialize local file manager.

        Args:
            base_path: Base directory for operations (default: current directory)
            create_base: Create base directory if it doesn't exist
            follow_symlinks: Whether to follow symbolic links
            sandboxed: If True, restrict all operations to base_path
        """
        self.base_path = Path(base_path) if base_path else Path.cwd()
        self.follow_symlinks = follow_symlinks
        self.sandboxed = sandboxed

        if create_base and not self.base_path.exists():
            self.base_path.mkdir(parents=True, exist_ok=True)

        if not self.base_path.is_dir():
            raise ValueError(f"Base path is not a directory: {self.base_path}")

    def _resolve_path(self, path: str) -> Path:
        """
        Resolve and validate a path.

        Args:
            path: Relative or absolute path

        Returns:
            Resolved Path object

        Raises:
            ValueError: If path escapes sandbox when sandboxed=True
        """
        target = Path(path)

        if not target.is_absolute():
            target = self.base_path / target

        try:
            resolved = target.resolve(strict=False)
        except (OSError, RuntimeError) as e:
            raise ValueError(f"Cannot resolve path: {path}") from e

        if self.sandboxed:
            try:
                resolved.relative_to(self.base_path.resolve())
            except ValueError as e:
                raise ValueError(
                    f"Path '{path}' escapes base directory '{self.base_path}'"
                ) from e

        return resolved

    def _get_file_metadata(self, path: Path) -> FileMetadata:
        """Extract metadata from a file path"""
        stat = path.stat()
        content_type, _ = mimetypes.guess_type(str(path))

        return FileMetadata(
            name=path.name,
            path=str(path.relative_to(self.base_path) if self.sandboxed else path),
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
        """List files matching pattern in directory"""
        target_dir = self._resolve_path(path)

        if not target_dir.exists():
            raise FileNotFoundError(f"Directory not found: {path}")

        if not target_dir.is_dir():
            raise ValueError(f"Path is not a directory: {path}")

        def _list():
            files = []
            for item in target_dir.iterdir():
                if not self.follow_symlinks and item.is_symlink():
                    continue

                if fnmatch.fnmatch(item.name, pattern) and item.is_file():
                    files.append(self._get_file_metadata(item))

            return sorted(files, key=lambda x: x.name)

        return await asyncio.to_thread(_list)

    async def get_file_url(self, path: str, expiry: int = 3600) -> str:
        """
        Get file:// URL for local file.
        Note: expiry is ignored for local files.
        """
        target = self._resolve_path(path)

        if not target.exists():
            raise FileNotFoundError(f"File not found: {path}")

        return target.as_uri()

    async def upload_file(
        self,
        source: BinaryIO | Path,
        destination: str
    ) -> FileMetadata:
        """Upload/copy a file to destination"""
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
        """Download/copy file to destination"""
        source_path = self._resolve_path(source)

        if not source_path.exists():
            raise FileNotFoundError(f"Source file not found: {source}")

        if not source_path.is_file():
            raise ValueError(f"Source is not a file: {source}")

        def _download():
            if isinstance(destination, Path):
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(str(source_path), str(destination))
                return destination
            else:
                with open(source_path, 'rb') as src:
                    shutil.copyfileobj(src, destination)
                return source_path

        return await asyncio.to_thread(_download)

    async def copy_file(self, source: str, destination: str) -> FileMetadata:
        """Copy file within filesystem"""
        source_path = self._resolve_path(source)
        dest_path = self._resolve_path(destination)

        if not source_path.exists():
            raise FileNotFoundError(f"Source file not found: {source}")

        if not source_path.is_file():
            raise ValueError(f"Source is not a file: {source}")

        dest_path.parent.mkdir(parents=True, exist_ok=True)

        def _copy():
            shutil.copy2(str(source_path), str(dest_path))
            return self._get_file_metadata(dest_path)

        return await asyncio.to_thread(_copy)

    async def delete_file(self, path: str) -> bool:
        """Delete a file"""
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
        """Check if file exists"""
        try:
            target = self._resolve_path(path)
            return await asyncio.to_thread(lambda: target.is_file())
        except (ValueError, OSError):
            return False

    async def get_file_metadata(self, path: str) -> FileMetadata:
        """Get metadata of a file"""
        target = self._resolve_path(path)

        if not target.exists():
            raise FileNotFoundError(f"File not found: {path}")

        if not target.is_file():
            raise ValueError(f"Path is not a file: {path}")

        return await asyncio.to_thread(lambda: self._get_file_metadata(target))

    async def create_file(self, path: str, content: bytes) -> bool:
        """Create a file with content"""
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
        """
        Create a file from bytes, BytesIO, or StringIO object.

        Args:
            path: Destination path for the file
            source: Bytes, BytesIO, or StringIO object containing the data
            encoding: Text encoding to use when source is StringIO (default: utf-8)

        Returns:
            FileMetadata of the created file
        """
        target = self._resolve_path(path)
        target.parent.mkdir(parents=True, exist_ok=True)

        def _create():
            if isinstance(source, bytes):
                # Direct bytes
                with open(target, 'wb') as f:
                    f.write(source)
            elif isinstance(source, BytesIO):
                # BytesIO object
                source.seek(0)  # Ensure we're at the start
                with open(target, 'wb') as f:
                    f.write(source.read())
            elif isinstance(source, StringIO):
                # StringIO object - encode to bytes
                source.seek(0)  # Ensure we're at the start
                content = source.read()
                with open(target, 'w', encoding=encoding) as f:
                    f.write(content)
            else:
                raise TypeError(
                    f"source must be bytes, BytesIO, or StringIO, got {type(source)}"
                )

            return self._get_file_metadata(target)

        return await asyncio.to_thread(_create)
