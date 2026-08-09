"""AI-Parrot SaaS — multi-tenant control plane and agentic business flows.

This distribution is the acyclic **leaf** of the workspace. It is the only
package allowed to depend on ``ai-parrot`` (flows/agents), ``ai-parrot-server``
(HTTP layer, ``JobManager``), ``ai-parrot-tools`` (``PulumiExecutor``) and
``navrules`` at the same time; nothing in the workspace depends on it.

Deliberately a **distinct top-level module** (``parrot_saas``) rather than a
contributor to the ``parrot.*`` namespace: three distributions already merge
into that namespace via :func:`pkgutil.extend_path`, and the repository's root
``conftest.py`` documents the import-shadowing that causes. This package
follows the ``parrot_tools`` / ``parrot_formdesigner`` / ``parrot_pipelines``
convention instead.

Sub-packages are imported lazily so that importing ``parrot_saas`` (e.g. to
read ``__version__``) never drags in aiohttp, asyncdb or the agent stack.
"""
from typing import TYPE_CHECKING, Any

from .version import (
    __author__,
    __author_email__,
    __description__,
    __license__,
    __title__,
    __version__,
)

if TYPE_CHECKING:  # pragma: no cover - import only for type checkers
    from .tenancy.context import TenantContext, TenantMode

__all__ = (
    "TenantContext",
    "TenantMode",
    "__author__",
    "__author_email__",
    "__description__",
    "__license__",
    "__title__",
    "__version__",
)

_LAZY_EXPORTS = {
    "TenantContext": ("parrot_saas.tenancy.context", "TenantContext"),
    "TenantMode": ("parrot_saas.tenancy.context", "TenantMode"),
}


def __getattr__(name: str) -> Any:
    """Resolve lazily-exported names on first access (PEP 562).

    Args:
        name: Attribute being looked up on the package.

    Returns:
        The resolved object.

    Raises:
        AttributeError: If ``name`` is not a known lazy export.
    """
    try:
        module_path, attr = _LAZY_EXPORTS[name]
    except KeyError:
        raise AttributeError(
            f"module {__name__!r} has no attribute {name!r}"
        ) from None
    from importlib import import_module

    return getattr(import_module(module_path), attr)


def __dir__() -> list[str]:
    """Expose lazy exports to ``dir()`` and tab-completion."""
    return sorted(__all__)
