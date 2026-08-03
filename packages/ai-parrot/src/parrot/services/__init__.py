"""Parrot service helpers.

Service classes are part of the server layer (ai-parrot-server satellite).
"""
from pkgutil import extend_path
__path__ = extend_path(__path__, __name__)

# Server-side exports (move to satellite in TASK-1373 — lazy via __getattr__)
_SERVER_CLASSES = {
    "AgentService": ("parrot.services.agent_service", "AgentService"),
    "AgentServiceClient": ("parrot.services.client", "AgentServiceClient"),
    "AgentServiceConfig": ("parrot.services.models", "AgentServiceConfig"),
    "AgentTask": ("parrot.services.models", "AgentTask"),
    "DeliveryChannel": ("parrot.services.models", "DeliveryChannel"),
    "DeliveryConfig": ("parrot.services.models", "DeliveryConfig"),
    "HeartbeatConfig": ("parrot.services.models", "HeartbeatConfig"),
    "TaskPriority": ("parrot.services.models", "TaskPriority"),
    "TaskResult": ("parrot.services.models", "TaskResult"),
    "TaskStatus": ("parrot.services.models", "TaskStatus"),
}


def __getattr__(name: str):
    if name in _SERVER_CLASSES:
        from parrot._imports import load_satellite_attr

        module_path, cls_name = _SERVER_CLASSES[name]
        return load_satellite_attr(
            name, module_path, install="ai-parrot-server", attr=cls_name
        )
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "AgentService",
    "AgentServiceClient",
    "AgentServiceConfig",
    "AgentTask",
    "TaskResult",
    "TaskStatus",
    "TaskPriority",
    "DeliveryChannel",
    "DeliveryConfig",
    "HeartbeatConfig",
]
