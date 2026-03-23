"""
Toolkit Registry - Registry of supported toolkits for dynamic loading.

Delegates to the multi-source discovery system. The old hardcoded
registry is replaced by TOOL_REGISTRY dicts in installed packages.
"""
import warnings
import importlib
from typing import Dict, Type, TYPE_CHECKING

if TYPE_CHECKING:
    from .toolkit import AbstractToolkit


def _discover_toolkits() -> Dict[str, Type["AbstractToolkit"]]:
    """Discover toolkits from TOOL_REGISTRY in installed packages.

    Returns actual class objects (not dotted paths) for backward compat.
    """
    from .discovery import discover_from_registry, resolve_class

    registry: Dict[str, Type["AbstractToolkit"]] = {}

    # Always include OpenAPIToolkit (core)
    from .openapitoolkit import OpenAPIToolkit
    registry["openapi"] = OpenAPIToolkit

    # Discover from installed packages
    dotted_paths = discover_from_registry()
    for name, path in dotted_paths.items():
        # Only include toolkit classes (not individual tools)
        if "Toolkit" in path.rsplit(".", 1)[-1]:
            try:
                cls = resolve_class(path)
                registry[name] = cls
            except (ImportError, AttributeError):
                pass  # Skip uninstalled toolkits

    return registry


class ToolkitRegistry:
    """Registry for supported toolkits with lazy loading.

    .. deprecated::
        Use ``ToolManager`` with discovery instead. This class is
        maintained for backward compatibility.
    """

    _registry: Dict[str, Type["AbstractToolkit"]] = None

    @classmethod
    def get_registry(cls) -> Dict[str, Type["AbstractToolkit"]]:
        """Get the toolkit registry, initializing lazily if needed."""
        if cls._registry is None:
            cls._registry = _discover_toolkits()
        return cls._registry

    @classmethod
    def get(cls, name: str) -> Type["AbstractToolkit"]:
        """Get a toolkit class by name."""
        registry = cls.get_registry()
        return registry.get(name.lower())

    @classmethod
    def list_toolkits(cls) -> list:
        """List all available toolkit names."""
        return list(cls.get_registry().keys())

    @classmethod
    def register(cls, name: str, toolkit_class: Type["AbstractToolkit"]) -> None:
        """Register a custom toolkit."""
        registry = cls.get_registry()
        registry[name.lower()] = toolkit_class


# Convenience accessor (lazy)
def get_supported_toolkits() -> Dict[str, Type["AbstractToolkit"]]:
    """Get the dictionary of supported toolkits."""
    return ToolkitRegistry.get_registry()


__all__ = [
    "ToolkitRegistry",
    "get_supported_toolkits",
]
