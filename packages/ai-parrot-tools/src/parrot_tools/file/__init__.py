"""Backward-compat re-exports — canonical location is parrot.interfaces.file."""

from parrot.interfaces.file import (
    FileManagerInterface,
    FileMetadata,
    LocalFileManager,
    TempFileManager,
)

__all__ = (
    "FileManagerInterface",
    "FileMetadata",
    "LocalFileManager",
    "TempFileManager",
    "S3FileManager",
    "GCSFileManager",
    "SharePointFileManager",
    "OneDriveFileManager",
)


def __getattr__(name: str):
    """Lazy re-export cloud managers from core."""
    if name in ("S3FileManager", "GCSFileManager", "SharePointFileManager", "OneDriveFileManager"):
        from parrot.interfaces import file as _file

        return getattr(_file, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
