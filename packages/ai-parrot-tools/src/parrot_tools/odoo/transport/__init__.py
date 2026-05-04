"""Transport layer for OdooToolkit (JSON-2 + legacy RPC + auto-detect)."""

from .base import AbstractOdooTransport
from .detect import Protocol, auto_detect_transport, build_transport
from .json2 import Json2Transport
from .jsonrpc import JsonRpcTransport
from .xmlrpc import XmlRpcTransport

__all__ = [
    "AbstractOdooTransport",
    "Json2Transport",
    "JsonRpcTransport",
    "XmlRpcTransport",
    "Protocol",
    "auto_detect_transport",
    "build_transport",
]
