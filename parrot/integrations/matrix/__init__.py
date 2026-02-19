"""Matrix protocol integration for AI-Parrot.

Provides Matrix-based communication for agents via mautrix-python:
- MatrixClientWrapper: async client wrapper
- MatrixStreamHandler: edit-based streaming
- MatrixA2ATransport: A2A over Matrix events
- MatrixAppService: Application Service with virtual MXIDs
- Custom m.parrot.* event types
"""
import importlib
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .client import MatrixClientWrapper
    from .streaming import MatrixStreamHandler
    from .a2a_transport import MatrixA2ATransport
    from .appservice import MatrixAppService
    from .models import MatrixAppServiceConfig


def __getattr__(name: str):
    """Lazy-import to avoid pulling mautrix at package import time."""
    _lazy_map = {
        "MatrixClientWrapper": ".client",
        "MatrixStreamHandler": ".streaming",
        "MatrixA2ATransport": ".a2a_transport",
        "MatrixAppService": ".appservice",
        "MatrixAppServiceConfig": ".models",
        "ParrotEventType": ".events",
        "TaskEventContent": ".events",
        "ResultEventContent": ".events",
        "StatusEventContent": ".events",
        "AgentCardEventContent": ".events",
        "generate_registration": ".registration",
        "generate_tokens": ".registration",
    }
    if name in _lazy_map:
        module = importlib.import_module(_lazy_map[name], package=__name__)
        return getattr(module, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "MatrixClientWrapper",
    "MatrixStreamHandler",
    "MatrixA2ATransport",
    "MatrixAppService",
    "MatrixAppServiceConfig",
    "ParrotEventType",
    "TaskEventContent",
    "ResultEventContent",
    "StatusEventContent",
    "AgentCardEventContent",
    "generate_registration",
    "generate_tokens",
]
