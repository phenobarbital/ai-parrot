"""Lazy loader for the optional QUIC/WebTransport MCP transport.

The QUIC transport is built on ``aioquic``, which ships in the
``ai-parrot-server[mcp]`` extra rather than as a core dependency. Importing
:mod:`parrot.mcp.transports.quic` therefore fails on a bare install — and
because that module used to be imported at the top of the MCP server and
client modules, a missing ``aioquic`` broke *every* transport (stdio, http,
sse, unix, websocket) and not just QUIC.

Every consumer now resolves QUIC symbols through this module, so the MCP
layer imports cleanly without ``aioquic`` and only selecting the ``"quic"``
transport raises — with an actionable install hint.
"""
from types import ModuleType
from typing import Any

__all__ = ("QUIC_INSTALL_HINT", "load_quic", "quic_attr")

QUIC_INSTALL_HINT = (
    "QUIC transport requires the optional 'aioquic' package. "
    "Install it with: pip install 'ai-parrot-server[mcp]'"
)


def load_quic() -> ModuleType:
    """Import the QUIC transport module on demand.

    Returns:
        ModuleType: The :mod:`parrot.mcp.transports.quic` module.

    Raises:
        ImportError: If ``aioquic`` (or the ``ai-parrot-server`` package that
            provides the transport module) is not installed. The message
            carries the install hint.
    """
    try:
        from parrot.mcp.transports import quic
    except ImportError as exc:
        raise ImportError(QUIC_INSTALL_HINT) from exc
    return quic


def quic_attr(name: str) -> Any:
    """Resolve one public symbol from the QUIC transport module.

    Args:
        name: Attribute name to read, e.g. ``"QuicMCPServer"``.

    Returns:
        Any: The requested attribute.

    Raises:
        ImportError: If the QUIC transport is not installed.
        AttributeError: If the transport module has no such attribute.
    """
    return getattr(load_quic(), name)
