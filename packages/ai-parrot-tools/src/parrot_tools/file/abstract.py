"""Backward-compat re-export — canonical location is parrot.interfaces.file."""
from parrot.interfaces.file.abstract import FileManagerInterface, FileMetadata

__all__ = ("FileManagerInterface", "FileMetadata")
