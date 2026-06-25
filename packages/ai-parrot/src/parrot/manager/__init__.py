"""Bot Manager for AI-Parrot.

BotManager is part of the server layer (ai-parrot-server satellite).
"""
from pkgutil import extend_path
__path__ = extend_path(__path__, __name__)

# Server-side exports (move to satellite in TASK-1372 — lazy via __getattr__)
_SERVER_CLASSES = {
    "BotManager": ("parrot.manager.manager", "BotManager"),
    "EphemeralRegistry": ("parrot.manager.ephemeral", "EphemeralRegistry"),
    "EphemeralAgentStatus": ("parrot.manager.ephemeral", "EphemeralAgentStatus"),
}


def __getattr__(name: str):
    if name in _SERVER_CLASSES:
        module_path, cls_name = _SERVER_CLASSES[name]
        try:
            import importlib
            mod = importlib.import_module(module_path)
            return getattr(mod, cls_name)
        except ImportError as e:
            raise ImportError(
                f"{name!r} requires the ai-parrot-server package. "
                f"Install it with: pip install ai-parrot-server"
            ) from e
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "BotManager",
    "EphemeralRegistry",
    "EphemeralAgentStatus",
]
