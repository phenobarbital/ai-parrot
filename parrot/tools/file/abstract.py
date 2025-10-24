from abc import ABC, abstractmethod
from typing import BinaryIO, Optional, List, Union
from io import BytesIO, StringIO
from datetime import datetime
from pathlib import Path
from dataclasses import dataclass

@dataclass
class FileMetadata:
    """Metadata for a file in the file manager"""
    name: str
    path: str
    size: int
    content_type: Optional[str]
    modified_at: Optional[datetime]
    url: Optional[str]  # Public URL if available

class FileManagerInterface(ABC):
    """Base interface for all file managers"""

    @abstractmethod
    async def list_files(self, path: str = "", pattern: str = "*") -> List[FileMetadata]:
        """List files in a directory/bucket"""
        pass

    @abstractmethod
    async def get_file_url(self, path: str, expiry: int = 3600) -> str:
        """Get a signed/public URL for a file"""
        pass

    @abstractmethod
    async def upload_file(self, source: BinaryIO | Path, destination: str) -> FileMetadata:
        """Upload/save a file"""
        pass

    @abstractmethod
    async def download_file(self, source: str, destination: Path | BinaryIO) -> Path:
        """Download a file"""
        pass

    @abstractmethod
    async def copy_file(self, source: str, destination: str) -> FileMetadata:
        """Copy file within the same storage"""
        pass

    @abstractmethod
    async def delete_file(self, path: str) -> bool:
        """Delete a file"""
        pass

    @abstractmethod
    async def exists(self, path: str) -> bool:
        """Check if file exists"""
        pass

    @abstractmethod
    async def get_file_metadata(self, path: str) -> FileMetadata:
        """Get metadata of a file"""
        pass

    @abstractmethod
    async def create_file(self, path: str, content: bytes) -> bool:
        """Create a file"""
        pass

    async def create_from_text(self, path: str, text: str, encoding: str = "utf-8") -> bool:
        """Create a text file from string content"""
        return await self.create_file(
            path, text.encode(encoding)
        )

    async def create_from_bytes(self, path: str, data: Union[bytes, BytesIO, StringIO]) -> bool:
        """Create a binary file from bytes content"""
        return await self.create_file(
            path, data.read() if hasattr(data, 'read') else data
        )
