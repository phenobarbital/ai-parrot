"""Transport layer for OdooToolkit (JSON-RPC + XML-RPC + auto-detect)."""
from .base import AbstractOdooTransport
from .detect import Protocol, auto_detect_transport, build_transport
from .jsonrpc import JsonRpcTransport
from .xmlrpc import XmlRpcTransport

__all__ = [
    "AbstractOdooTransport",
    "JsonRpcTransport",
    "XmlRpcTransport",
    "Protocol",
    "auto_detect_transport",
    "build_transport",
]
