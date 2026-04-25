"""File manager interfaces — re-exported from navigator.utils.file.

This module is a backward-compat shim. The single source of truth
is navigator.utils.file (navigator-api >= 2.14.1). New code SHOULD
import directly from navigator.utils.file; existing code that
uses parrot.interfaces.file continues to work via this shim.

Eager re-exports: FileManagerInterface, FileMetadata,
                  LocalFileManager, TempFileManager.
Lazy re-exports:  S3FileManager, GCSFileManager — loaded on first
                  access via __getattr__ so importing this package
                  does not pull in aioboto3 or
                  google-cloud-storage.
"""
import importlib
import sys

from navigator.utils.file import (
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

_LAZY_MANAGERS = {
    "S3FileManager": "navigator.utils.file.s3",
    "GCSFileManager": "navigator.utils.file.gcs",
}


def __getattr__(name: str):
    if name in _LAZY_MANAGERS:
        mod = importlib.import_module(_LAZY_MANAGERS[name])
        obj = getattr(mod, name)
        setattr(sys.modules[__name__], name, obj)
        return obj
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
