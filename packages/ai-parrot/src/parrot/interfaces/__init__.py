"""
Interfaces package - Mixins for bot functionality.

This package contains interface classes that provide specific functionality
to bot implementations through multiple inheritance.

Heavy interfaces (ToolInterface, VectorInterface) are lazy-loaded to avoid
pulling in all LLM client dependencies at import time.
"""
import importlib
import sys

from .file import FileManagerInterface, FileMetadata

__all__ = [
    'ToolInterface',
    'VectorInterface',
    'FileManagerInterface',
    'FileMetadata',
    'RSSInterface',
    'OdooInterface',
    'FlowtaskInterface',
]

_LAZY_INTERFACES = {
    "ToolInterface": ".tools",
    "VectorInterface": ".vector",
    "RSSInterface": ".rss",
    "OdooInterface": ".odoointerface",
    "FlowtaskInterface": ".flowtask",
}


def __getattr__(name: str):
    if name in _LAZY_INTERFACES:
        mod = importlib.import_module(_LAZY_INTERFACES[name], __name__)
        obj = getattr(mod, name)
        setattr(sys.modules[__name__], name, obj)
        return obj
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
