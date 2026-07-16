"""Ingress adapters for the unified EventBus v2 (FEAT-310).

``WebSocketIngress`` is always available (aiohttp is a core dependency);
``GrpcIngress`` is exposed lazily so the core package never imports grpc —
install the optional extra with ``pip install ai-parrot[grpc]``.
"""
from typing import Any

from parrot.core.events.bus.ingress.websocket import WebSocketIngress

__all__ = (
    "GrpcIngress",
    "WebSocketIngress",
)


def __getattr__(name: str) -> Any:
    """Lazily resolve grpc-dependent exports."""
    if name == "GrpcIngress":
        from parrot.core.events.bus.ingress.grpc import GrpcIngress
        return GrpcIngress
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
