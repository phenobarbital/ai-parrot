"""File management implementations and backward-compat re-exports."""
from parrot.interfaces.file import FileManagerInterface, FileMetadata
from .local import LocalFileManager
from .s3 import S3FileManager
from .tmp import TempFileManager
from .gcs import GCSFileManager

__all__ = (
    "FileManagerInterface",
    "FileMetadata",
    "LocalFileManager",
    "S3FileManager",
    "TempFileManager",
    "GCSFileManager",
)
