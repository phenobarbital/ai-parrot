"""FilesystemTransport — zero-dependency local transport for multi-agent coordination."""

from .config import FilesystemTransportConfig
from .hook import FilesystemHook
from .transport import FilesystemTransport

__all__ = [
    "FilesystemTransport",
    "FilesystemTransportConfig",
    "FilesystemHook",
]
