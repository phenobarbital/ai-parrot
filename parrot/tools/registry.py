"""
Toolkit Registry - Registry of supported toolkits for dynamic loading.

Similar to SUPPORTED_CLIENTS in the clients module, this registry allows
string-based toolkit loading in bot configurations.
"""
from typing import Dict, Type, TYPE_CHECKING

if TYPE_CHECKING:
    from .toolkit import AbstractToolkit


def _get_supported_toolkits() -> Dict[str, Type["AbstractToolkit"]]:
    """Lazy-load toolkit classes to avoid circular imports."""
    from .jiratoolkit import JiraToolkit
    from .zipcode import ZipcodeAPIToolkit
    from .gittoolkit import GitToolkit
    from .openapi_toolkit import OpenAPIToolkit
    from .querytoolkit import QueryToolkit
    from .sitesearch.toolkit import SiteSearchToolkit

    return {
        "jira": JiraToolkit,
        "zipcode": ZipcodeAPIToolkit,
        "git": GitToolkit,
        "openapi": OpenAPIToolkit,
        "query": QueryToolkit,
        "sitesearch": SiteSearchToolkit,
    }


class ToolkitRegistry:
    """Registry for supported toolkits with lazy loading."""

    _registry: Dict[str, Type["AbstractToolkit"]] = None

    @classmethod
    def get_registry(cls) -> Dict[str, Type["AbstractToolkit"]]:
        """Get the toolkit registry, initializing lazily if needed."""
        if cls._registry is None:
            cls._registry = _get_supported_toolkits()
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
