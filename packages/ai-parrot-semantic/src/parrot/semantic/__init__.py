"""Governed semantic queries using the native sqlglot compiler."""

from typing import Any

from .version import __version__

__all__ = ["__version__", "SemanticQuery", "SemanticQueryResult", "SemanticLayerToolkit", "SemanticDataSource"]

_LAZY = {
    "SemanticQuery": ".models",
    "SemanticQueryResult": ".models",
    "SemanticLayerToolkit": ".toolkit",
    "SemanticDataSource": ".dataset_source",
}


def __getattr__(name: str) -> Any:
    """Resolve the public names on first use so sub-packages do not load the toolkit.

    Args:
        name: Attribute requested on the package.

    Returns:
        The resolved public object.

    Raises:
        AttributeError: For any name outside ``_LAZY``.
    """
    module = _LAZY.get(name)
    if module is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    import importlib

    value = getattr(importlib.import_module(module, __name__), name)
    globals()[name] = value
    return value
