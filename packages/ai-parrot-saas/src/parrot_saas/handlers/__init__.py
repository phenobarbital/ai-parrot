"""HTTP surface for the SaaS plane.

``setup_saas_api`` is the single wiring entry point; import it lazily so that
importing this package does not require aiohttp or navigator to be present.
"""
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover - import only for type checkers
    from .setup import setup_saas_api

__all__ = ("setup_saas_api",)

_LAZY_EXPORTS = {"setup_saas_api": ("parrot_saas.handlers.setup", "setup_saas_api")}


def __getattr__(name: str) -> Any:
    """Resolve lazily-exported names on first access (PEP 562)."""
    try:
        module_path, attr = _LAZY_EXPORTS[name]
    except KeyError:
        raise AttributeError(
            f"module {__name__!r} has no attribute {name!r}"
        ) from None
    from importlib import import_module

    return getattr(import_module(module_path), attr)
