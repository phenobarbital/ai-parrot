"""Interactive HTML artifact catalog (libraries + scaffold templates).

See :mod:`parrot.tools.interactive.catalog_registry` for the on-disk catalog
loader and :class:`parrot.tools.interactive_toolkit.InteractiveToolkit` for the
agent-facing tools.
"""
from .catalog_registry import (
    InteractiveCatalogRegistry,
    get_interactive_catalog,
    build_head,
    BASE_CSS,
)

__all__ = [
    "InteractiveCatalogRegistry",
    "get_interactive_catalog",
    "build_head",
    "BASE_CSS",
]
