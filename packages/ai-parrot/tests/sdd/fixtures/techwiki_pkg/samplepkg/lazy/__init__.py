"""A namespace package whose public names resolve lazily.

``__all__`` names nothing that static analysis can see on this module: every export is
fetched from a submodule on first attribute access, exactly like ``parrot.auth``.
"""

from typing import Any

_LAZY_ATTRS: dict[str, str] = {"LazyThing": "samplepkg.lazy.impl"}

__all__ = ["LazyThing"]


def __getattr__(name: str) -> Any:
    """Resolve a public export from its owning submodule on first access.

    Args:
        name: Attribute requested on the package.

    Returns:
        The object defined in the owning submodule.

    Raises:
        AttributeError: If ``name`` is not a public export.
    """
    module_path = _LAZY_ATTRS.get(name)
    if module_path is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    import importlib

    return getattr(importlib.import_module(module_path), name)
