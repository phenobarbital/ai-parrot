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
)


def __getattr__(name: str):
    """Lazy re-export S3/GCS managers from core."""
    if name in ("S3FileManager", "GCSFileManager"):
        from parrot.interfaces import file as _file
        return getattr(_file, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
