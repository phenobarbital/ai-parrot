"""Lazy compatibility exports for the moved LLM wiki toolkit."""

from typing import Any

_EXPORTS: dict[str, str] = {
    "LLMWikiToolkit": "parrot_tools.wiki.toolkit",
    "_is_federated": "parrot_tools.wiki.toolkit",
}

__all__ = list(_EXPORTS)


def __getattr__(name: str) -> Any:
    """Resolve the moved toolkit only when requested."""
    module_path = _EXPORTS.get(name)
    if module_path is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    import importlib

    value = getattr(importlib.import_module(module_path), name)
    globals()[name] = value
    return value
