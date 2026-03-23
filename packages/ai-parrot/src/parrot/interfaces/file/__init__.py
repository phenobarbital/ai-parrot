"""File manager interfaces and implementations.

- FileManagerInterface / FileMetadata: pure abstract (stdlib only)
- LocalFileManager / TempFileManager: stdlib implementations (always available)
- S3FileManager / GCSFileManager: lazy-loaded (require aioboto3 / google-cloud-storage)
"""
import importlib
import sys

from .abstract import FileManagerInterface, FileMetadata
from .local import LocalFileManager
from .tmp import TempFileManager

__all__ = (
    "FileManagerInterface",
    "FileMetadata",
    "LocalFileManager",
    "TempFileManager",
    "S3FileManager",
    "GCSFileManager",
)

_LAZY_MANAGERS = {
    "S3FileManager": ".s3",
    "GCSFileManager": ".gcs",
}


def __getattr__(name: str):
    if name in _LAZY_MANAGERS:
        mod = importlib.import_module(_LAZY_MANAGERS[name], __name__)
        obj = getattr(mod, name)
        setattr(sys.modules[__name__], name, obj)
        return obj
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
